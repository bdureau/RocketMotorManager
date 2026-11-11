"""Import of Richard Nakka's "SRM" solid rocket motor design workbooks.

The SRM spreadsheets (versions 1.x and SRM_2023, ``.xls`` or ``.xlsx``)
are not plain tables: the motor information is spread over several sheets
and every value is located by its label, so that both versions (whose rows
differ slightly) are read with the same code.

=================  ==========================================================
Sheet              Information read
=================  ==========================================================
``Data and Kn``    Title and subtitle, chamber Dc/Lc, propellant type (code
                   1/2/3 in v1.x, name in 2023), grain Do/do/Lo/N, densities,
                   grain mass, Kn, throat diameter
``Output``         Summary (grain mass, total impulse, average thrust, thrust
                   time, Isp, class) and a 23-point thrust-time table
``Performance``    Full resolution thrust curve (columns ``t`` and ``F``,
                   about 880 points), maximum thrust, expansion ratio, exit
                   diameter
``Pressure``       Maximum chamber pressure and burn time (informative)
``Nozzle Design``  Nozzle overall length (SRM_2023 only, informative)
=================  ==========================================================

What the workbook does not contain (casing outer diameter, motor length,
hardware masses, manufacturer, delays) must be completed by the user: the
chamber inside dimensions are only proposed as starting values.
"""

from __future__ import annotations

from localization import N_, _

import logging
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

from models.errors import FileFormatError
from models.motor import Motor
from models.motor_calculations import total_impulse
from models.motor_metadata import MotorMetadata
from models.thrust_point import ThrustPoint
from services.excel_service import ExcelService
from services.file_utils import PathLike, format_number
from services.thrust_analysis import resample, simplify

logger = logging.getLogger(__name__)

Grid = list[list[Any]]

REQUIRED_SHEETS = ("Data and Kn", "Output", "Performance")
OPTIONAL_SHEETS = ("Pressure", "Nozzle Design", "Intro")

#: Propellant codes of SRM 1.x ("1=KN/Dextrose (65/35), 2=KN/Sorbitol (65/35), 3=other").
LEGACY_PROPELLANT_CODES = {1: "KNDX", 2: "KNSB", 3: "Other"}

#: SRM propellant abbreviations -> description used by the application.
PROPELLANT_NAMES = {
    "KNDX": "KNDX (Potassium nitrate / dextrose)",
    "KNSB": "KNSB (Potassium nitrate / sorbitol)",
    "KNSU": "KNSU (Potassium nitrate / sucrose)",
    "KNER": "KNER (Potassium nitrate / erythritol)",
    "KNMN": "KNMN (Potassium nitrate / mannitol)",
    "KNFR": "KNFR (Potassium nitrate / fructose)",
    "KNPSB": "KNPSB (Potassium nitrate / potassium perchlorate / sorbitol)",
}


class CurveSource(str, Enum):
    """Which thrust curve of the workbook is imported."""

    PERFORMANCE_SIMPLIFIED = "performance_simplified"
    PERFORMANCE_FULL = "performance_full"
    PERFORMANCE_RESAMPLED = "performance_resampled"
    OUTPUT_TABLE = "output_table"


CURVE_SOURCE_CAPTIONS = {
    CurveSource.PERFORMANCE_SIMPLIFIED: N_("Performance sheet, simplified (recommended)"),
    CurveSource.PERFORMANCE_FULL: N_("Performance sheet, full resolution"),
    CurveSource.PERFORMANCE_RESAMPLED: N_("Performance sheet, resampled"),
    CurveSource.OUTPUT_TABLE: N_("Output sheet table (23 points)"),
}


@dataclass
class SrmSummary:
    """Values computed by the SRM workbook itself (for cross-checking)."""

    total_impulse_ns: Optional[float] = None
    average_thrust_n: Optional[float] = None
    maximum_thrust_n: Optional[float] = None
    thrust_time_s: Optional[float] = None
    burn_time_s: Optional[float] = None
    specific_impulse_s: Optional[float] = None
    motor_class: str = ""
    max_pressure_mpa: Optional[float] = None


@dataclass
class SrmWorkbook:
    """Everything read from an SRM workbook."""

    version: str
    title: str
    subtitle: str
    propellant: str  # SRM abbreviation (KNDX...) or free text
    chamber_diameter_mm: Optional[float]
    chamber_length_mm: Optional[float]
    grain_mass_g: Optional[float]
    nozzle_length_mm: Optional[float]
    summary: SrmSummary
    performance_curve: list[ThrustPoint]
    output_curve: list[ThrustPoint]
    details: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def curve(self, source: CurveSource, tolerance_fraction: float = 0.005, points: int = 100) -> list[ThrustPoint]:
        """Return the thrust curve for the chosen source.

        Args:
            tolerance_fraction: Simplification tolerance as a fraction of
                the maximum thrust (``PERFORMANCE_SIMPLIFIED``).
            points: Number of points (``PERFORMANCE_RESAMPLED``).
        """
        if source == CurveSource.OUTPUT_TABLE:
            return list(self.output_curve)
        curve = list(self.performance_curve)
        if source == CurveSource.PERFORMANCE_FULL or len(curve) < 3:
            return curve
        if source == CurveSource.PERFORMANCE_RESAMPLED:
            resampled = resample(curve, max(2, points))
            return [ThrustPoint(round(p.time_s, 6), round(p.thrust_n, 4)) for p in resampled]
        peak = max(p.thrust_n for p in curve)
        return simplify(curve, max(1e-9, tolerance_fraction * peak))

    def suggested_name(self) -> str:
        """ENG-style code from the class and average thrust (e.g. ``K1423``)."""
        if self.summary.motor_class and self.summary.average_thrust_n:
            return f"{self.summary.motor_class.strip()}{round(self.summary.average_thrust_n)}"
        return re.sub(r"\s+", "_", self.title.strip())[:20] or "SRM_motor"

    def propellant_description(self) -> str:
        """Propellant type text matching the application list when possible."""
        key = self.propellant.strip().upper().split()[0] if self.propellant.strip() else ""
        return PROPELLANT_NAMES.get(key, self.propellant.strip())

    def to_motor(self, curve: Sequence[ThrustPoint], name: str = "", manufacturer: str = "",
                 diameter_mm: Optional[float] = None, length_mm: Optional[float] = None,
                 delays: str = "P", casing_mass_g: Optional[float] = None,
                 nozzle_mass_g: Optional[float] = None, source_file: str = "") -> Motor:
        """Build a :class:`Motor` from the workbook and the user's choices."""
        description = " ".join(part for part in (self.title.strip(), self.subtitle.strip()) if part)
        meta = MotorMetadata(
            name=name or self.suggested_name(),
            manufacturer=manufacturer,
            designation=f"{name or self.suggested_name()}-{delays}" if delays not in ("", "0") else (name or self.suggested_name()),
            diameter_mm=diameter_mm if diameter_mm is not None else self.chamber_diameter_mm,
            length_mm=length_mm if length_mm is not None else self.chamber_length_mm,
            delays=delays or "0",
            propellant_mass_g=self.grain_mass_g,
            casing_mass_g=casing_mass_g,
            nozzle_closure_mass_g=nozzle_mass_g,
            propellant_type=self.propellant_description(),
            description=description,
            comments=self._comment_text(),
            eng_comments=[f"Imported from Richard Nakka SRM workbook ({self.version}): {self.title.strip()}"],
            source_file=source_file,
            extra={f"srm_{key}": value for key, value in self.details.items()},
        )
        return Motor(metadata=meta, points=list(curve))

    def _comment_text(self) -> str:
        s = self.summary
        parts: list[str] = []
        for caption, value, unit, decimals in (
            (N_("Total impulse"), s.total_impulse_ns, "N.s", 2), (N_("Average thrust"), s.average_thrust_n, "N", 2),
            (N_("Maximum thrust"), s.maximum_thrust_n, "N", 2), (N_("Thrust time"), s.thrust_time_s, "s", 4),
            (N_("Burn time"), s.burn_time_s, "s", 4), (N_("Specific impulse"), s.specific_impulse_s, "s", 2),
            (N_("Max chamber pressure"), s.max_pressure_mpa, "MPa", 3),
        ):
            if value is not None:
                parts.append(f"{_(caption)} {format_number(value, decimals)} {unit}")
        if s.motor_class:
            parts.append(_("Class {motor_class}").format(motor_class=s.motor_class))
        return _("SRM workbook results: {results}.").format(results="; ".join(parts))


# ----------------------------------------------------------------------
# Grid helpers
# ----------------------------------------------------------------------
def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _cell(grid: Grid, row: int, column: int) -> Any:
    if 0 <= row < len(grid) and 0 <= column < len(grid[row]):
        return grid[row][column]
    return None


def _normalise(label: Any) -> str:
    """Comparable form of a label: no spaces, no trailing colon, case kept
    (SRM uses 'Do' and 'do' for different diameters)."""
    return re.sub(r"\s+", "", _text(label)).rstrip(":")


def find_label(grid: Grid, labels: Sequence[str], max_column: int = 12) -> Optional[tuple[int, int]]:
    """(row, column) of the first cell whose normalised text equals one of
    ``labels`` (normalised too)."""
    wanted = {_normalise(label) for label in labels}
    for r, row in enumerate(grid):
        for c, value in enumerate(row[:max_column]):
            if isinstance(value, str) and _normalise(value) in wanted:
                return r, c
    return None


def value_right_of(grid: Grid, labels: Sequence[str], numeric: bool = True, max_column: int = 12) -> Any:
    """Value of the first non-empty cell to the right of a label."""
    found = find_label(grid, labels, max_column)
    if found is None:
        return None
    r, c = found
    for column in range(c + 1, min(c + 4, len(grid[r]))):
        value = grid[r][column]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        return _number(value) if numeric else value
    return None


def _strictly_increasing(points: list[ThrustPoint]) -> list[ThrustPoint]:
    result: list[ThrustPoint] = []
    for point in points:
        if point.time_s < 0 or (result and point.time_s <= result[-1].time_s):
            continue
        result.append(ThrustPoint(point.time_s, max(0.0, point.thrust_n)))
    return result


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class SrmService:
    """Detect and read Richard Nakka SRM workbooks."""

    def __init__(self, excel_service: Optional[ExcelService] = None) -> None:
        self.excel = excel_service or ExcelService()

    def is_srm_workbook(self, path: PathLike) -> bool:
        """True when the workbook has the SRM sheet structure."""
        try:
            sheets = set(self.excel.list_sheets(path))
        except Exception:  # unreadable files are simply "not SRM"
            return False
        return all(name in sheets for name in REQUIRED_SHEETS)

    def read(self, path: PathLike) -> SrmWorkbook:
        """Read an SRM workbook.

        Raises:
            FileFormatError: If the workbook is not an SRM workbook or if
                the thrust curve cannot be found.
        """
        sheets = self.excel.list_sheets(path)
        missing = [name for name in REQUIRED_SHEETS if name not in sheets]
        if missing:
            raise FileFormatError(
                _('This workbook is not a Richard Nakka SRM workbook (missing sheet(s): {missing}).').format(missing=', '.join(missing))
            )
        grids = self.excel.read_grids(path, list(REQUIRED_SHEETS) + [s for s in OPTIONAL_SHEETS if s in sheets])
        workbook = self.parse(grids)
        logger.info("SRM workbook %s read (%s): %d performance points, %d output points",
                    path, workbook.version, len(workbook.performance_curve), len(workbook.output_curve))
        return workbook

    # ------------------------------------------------------------------
    def parse(self, grids: dict[str, Grid]) -> SrmWorkbook:
        """Decode the sheets (already read as grids)."""
        data, output, performance = grids["Data and Kn"], grids["Output"], grids["Performance"]
        warnings: list[str] = []
        title, subtitle = self._title(data, output)
        propellant, legacy = self._propellant(data, subtitle)
        version = self._version(grids, legacy)
        summary = self._summary(output, performance, grids.get("Pressure"))
        performance_curve = self._performance_curve(performance)
        output_curve = self._output_curve(output)
        if not performance_curve and not output_curve:
            raise FileFormatError(_("No thrust-time data found in the 'Performance' or 'Output' sheets of the SRM workbook."))
        if not performance_curve:
            warnings.append(_("The 'Performance' sheet curve was not found; the Output table (lower resolution) is used."))
        grain_mass_kg = value_right_of(data, ["m grain"])
        if grain_mass_kg is None:
            grain_mass_kg = value_right_of(output, ["Grain mass"])
        nozzle_length = value_right_of(grids["Nozzle Design"], ["Lo"]) if "Nozzle Design" in grids else None
        workbook = SrmWorkbook(
            version=version,
            title=title,
            subtitle=subtitle,
            propellant=propellant,
            chamber_diameter_mm=value_right_of(data, ["Dc"]),
            chamber_length_mm=value_right_of(data, ["Lc"]),
            grain_mass_g=grain_mass_kg * 1000.0 if grain_mass_kg is not None else None,
            nozzle_length_mm=nozzle_length,
            summary=summary,
            performance_curve=performance_curve,
            output_curve=output_curve,
            details=self._details(data, performance, grids.get("Pressure"), nozzle_length, version),
            warnings=warnings,
        )
        self._check(workbook)
        return workbook

    @staticmethod
    def _title(data: Grid, output: Grid) -> tuple[str, str]:
        found = find_label(data, ["Title:"])
        if found is not None:
            r, c = found
            return _text(_cell(data, r, c + 1)), _text(_cell(data, r + 1, c + 1))
        found = find_label(output, ["Motor Output Data"])
        if found is not None:  # title is a few rows below the heading
            r, c = found
            texts = [_text(_cell(output, row, c)) for row in range(r + 1, r + 8) if _text(_cell(output, row, c))]
            texts = [t for t in texts if not t.lower().startswith(("this page", "may be used"))]
            return (texts[0] if texts else ""), (texts[1] if len(texts) > 1 else "")
        return "", ""

    @staticmethod
    def _propellant(data: Grid, subtitle: str) -> tuple[str, bool]:
        """Return (propellant, legacy_numeric_code_used)."""
        raw = value_right_of(data, ["Propellant type"], numeric=False)
        if raw is not None and _text(raw):
            return _text(raw), False
        code = value_right_of(data, ["Type"])
        if code is not None and int(code) in LEGACY_PROPELLANT_CODES:
            name = LEGACY_PROPELLANT_CODES[int(code)]
            if name == "Other":
                match = re.search(r"\b(KN[A-Z]{2,3})\b", subtitle.upper())
                return (match.group(1) if match else "Other"), True
            return name, True
        match = re.search(r"\b(KN[A-Z]{2,3})\b", subtitle.upper())
        return (match.group(1) if match else ""), False

    @staticmethod
    def _version(grids: dict[str, Grid], legacy: bool) -> str:
        intro = grids.get("Intro") or []
        declared = _text(value_right_of(intro, ["Version:"], numeric=False))
        match = re.match(r"(\d{4}|\d+(?:\.\d+)+)", declared)
        if match:
            return f"SRM {match.group(1)}"
        if "Nozzle Design" in grids or not legacy:
            return "SRM 2023"
        return "SRM 1.x"

    @staticmethod
    def _summary(output: Grid, performance: Grid, pressure: Optional[Grid]) -> SrmSummary:
        summary = SrmSummary(
            total_impulse_ns=value_right_of(output, ["Total impulse"]),
            average_thrust_n=value_right_of(output, ["Average thrust"]),
            thrust_time_s=value_right_of(output, ["Thrust time"]),
            specific_impulse_s=value_right_of(output, ["Specific Impulse"]),
            motor_class=_text(value_right_of(output, ["Motor Classification"], numeric=False)),
            maximum_thrust_n=value_right_of(performance, ["F max"]),
        )
        if pressure is not None:
            summary.max_pressure_mpa = value_right_of(pressure, ["Pmax ="], max_column=20)
            summary.burn_time_s = value_right_of(pressure, ["t burn ="], max_column=20)
        return summary

    @staticmethod
    def _performance_curve(performance: Grid) -> list[ThrustPoint]:
        """Columns 't' (s) and 'F' (N) of the Performance table."""
        for r, row in enumerate(performance):
            headers = [_normalise(v) for v in row]
            if "t" not in headers or "F" not in headers or "Po" not in headers:
                continue
            time_col = headers.index("t")
            units = [_text(v).lower() for v in (performance[r + 1] if r + 1 < len(performance) else [])]
            force_cols = [c for c, h in enumerate(headers) if h == "F"]
            thrust_col = next((c for c in force_cols if c < len(units) and units[c].startswith("n")), force_cols[0])
            points = []
            for data_row in performance[r + 2:]:
                t, f = _number(_cell([data_row], 0, time_col)), _number(_cell([data_row], 0, thrust_col))
                if t is None or f is None:
                    if points:
                        break
                    continue
                points.append(ThrustPoint(t, f))
            return _strictly_increasing(points)
        return []

    @staticmethod
    def _output_curve(output: Grid) -> list[ThrustPoint]:
        """The 'Data pt. / Time / Thrust' table of the Output sheet."""
        found = find_label(output, ["Data pt."])
        if found is None:
            return []
        r, c = found
        points = []
        for row in output[r + 1:]:
            index, t, f = _number(_cell([row], 0, c)), _number(_cell([row], 0, c + 1)), _number(_cell([row], 0, c + 2))
            if index is None:
                if points:
                    break
                continue
            if t is not None and f is not None:
                points.append(ThrustPoint(t, f))
        return _strictly_increasing(points)

    @staticmethod
    def _details(data: Grid, performance: Grid, pressure: Optional[Grid], nozzle_length: Optional[float],
                 version: str) -> dict[str, str]:
        """Design data kept in the project (XML 'extra' metadata)."""
        details: dict[str, str] = {"workbook_version": version}
        for key, sheet, labels, unit in (
            ("chamber_diameter", data, ["Dc"], "mm"), ("chamber_length", data, ["Lc"], "mm"),
            ("grain_outer_diameter", data, ["Do"], "mm"), ("grain_core_diameter", data, ["do"], "mm"),
            ("grain_segment_length", data, ["Lo"], "mm"), ("grain_segments", data, ["N"], ""),
            ("grain_length", data, ["Lgo"], "mm"), ("grain_density", data, ["r grain"], "g/cm3"),
            ("volumetric_loading", data, ["V l"], ""), ("kn_initial", data, ["Kno"], ""),
            ("kn_max", data, ["Kn max"], ""), ("throat_diameter", data, ["Dto"], "mm"),
            ("expansion_ratio", performance, ["Ae/At"], ""), ("exit_diameter", performance, ["De"], "mm"),
        ):
            value = value_right_of(sheet, labels)
            if value is not None:
                details[key] = f"{format_number(value, 4)} {unit}".strip()
        if pressure is not None:
            pmax = value_right_of(pressure, ["Pmax ="], max_column=20)
            if pmax is not None:
                details["max_chamber_pressure"] = f"{format_number(pmax, 4)} MPa"
        if nozzle_length is not None:
            details["nozzle_length"] = f"{format_number(nozzle_length, 2)} mm"
        return details

    @staticmethod
    def _check(workbook: SrmWorkbook) -> None:
        """Compare the imported curve with the workbook's own total impulse."""
        reference = workbook.summary.total_impulse_ns
        curve = workbook.performance_curve or workbook.output_curve
        if reference and len(curve) >= 2:
            deviation = abs(total_impulse(curve) - reference) / reference
            if deviation > 0.02:
                workbook.warnings.append(
                    _('The thrust curve integrates to {curve} N.s whereas the workbook reports {reference} N.s ({deviation} difference). Check that the workbook was recalculated.').format(curve=f"{total_impulse(curve):.1f}", reference=f"{reference:.1f}", deviation=f"{deviation:.1%}")
                )
        if workbook.chamber_diameter_mm is not None:
            workbook.warnings.append(
                _('SRM gives the chamber INSIDE diameter and length: enter the casing outside diameter and the overall motor length for the ENG export.')
            )
