"""Data validation rules for thrust curves and motor properties.

Validation never modifies data: it produces a :class:`ValidationReport`
that the UI displays and that the exporters use to refuse or warn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from models.motor import Motor
from models.thrust_point import ThrustPoint


class Severity(str, Enum):
    """Severity of a validation issue."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding.

    Attributes:
        severity: Info, warning or error.
        code: Stable machine-readable identifier.
        message: Human-readable explanation in English.
        row: 0-based index of the related thrust point, if any.
    """

    severity: Severity
    code: str
    message: str
    row: Optional[int] = None


@dataclass
class ValidationReport:
    """A collection of :class:`ValidationIssue`."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, severity: Severity, code: str, message: str, row: Optional[int] = None) -> None:
        """Append an issue."""
        self.issues.append(ValidationIssue(severity, code, message, row))

    def extend(self, other: "ValidationReport") -> None:
        """Append every issue of another report."""
        self.issues.extend(other.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Issues with ERROR severity."""
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Issues with WARNING severity."""
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """True when there is no error (warnings are allowed)."""
        return not self.errors

    def summary(self) -> str:
        """Return a multi-line text summary of the issues."""
        if not self.issues:
            return "No problem detected."
        lines = []
        for issue in self.issues:
            where = f" (row {issue.row + 1})" if issue.row is not None else ""
            lines.append(f"[{issue.severity.value.upper()}] {issue.message}{where}")
        return "\n".join(lines)


def validate_points(points: Sequence[ThrustPoint]) -> ValidationReport:
    """Check a thrust curve: missing/non-numeric values, negative times or
    thrusts, chronological order, duplicates and termination."""
    report = ValidationReport()
    if not points:
        report.add(Severity.ERROR, "no_points", "The thrust curve contains no point.")
        return report
    if len(points) < 2:
        report.add(Severity.ERROR, "too_few_points", "At least two thrust points are required.")
    for row, point in enumerate(points):
        if not point.is_finite():
            report.add(Severity.ERROR, "non_numeric", "Missing or non-numeric value.", row)
            continue
        if point.time_s < 0:
            report.add(Severity.ERROR, "negative_time", "Negative time value.", row)
        if point.thrust_n < 0:
            report.add(Severity.ERROR, "negative_thrust", "Negative thrust value.", row)
    _check_order(points, report)
    finite = [p for p in points if p.is_finite()]
    if finite and max(p.thrust_n for p in finite) <= 0:
        report.add(Severity.ERROR, "no_thrust", "The curve has no positive thrust.")
    if finite and finite[-1].thrust_n != 0:
        report.add(
            Severity.WARNING, "not_terminated",
            "The last point should have zero thrust (burnout); ENG readers expect it.",
            len(points) - 1,
        )
    return report


def _check_order(points: Sequence[ThrustPoint], report: ValidationReport) -> None:
    """Report non-chronological and duplicated times (each finite point is
    compared with the previous finite point)."""
    previous = None
    for row, current in enumerate(points):
        if not current.is_finite():
            continue
        if previous is not None:
            if current.time_s == previous.time_s:
                report.add(Severity.ERROR, "duplicate_time", "Duplicate time value.", row)
            elif current.time_s < previous.time_s:
                report.add(Severity.ERROR, "not_chronological", "Time is lower than the previous point.", row)
        previous = current


def validate_metadata(motor: Motor) -> ValidationReport:
    """Check the motor properties required by the ENG format."""
    report = ValidationReport()
    meta = motor.metadata
    if not meta.name.strip():
        report.add(Severity.ERROR, "no_name", "The motor name is required.")
    elif any(ch.isspace() for ch in meta.name.strip()):
        report.add(Severity.WARNING, "name_spaces", "Spaces in the motor name will be replaced by '_' in ENG files.")
    if not meta.manufacturer.strip():
        report.add(Severity.ERROR, "no_manufacturer", "The manufacturer is required by the ENG format.")
    _require_positive(report, meta.diameter_mm, "diameter", "Motor diameter")
    _require_positive(report, meta.length_mm, "length", "Motor length")
    _require_positive(report, meta.propellant_mass_g, "propellant_mass", "Propellant mass")
    _require_positive(report, meta.total_mass_g, "total_mass", "Total motor mass")
    total, prop = meta.total_mass_g, meta.propellant_mass_g
    if total is not None and prop is not None and prop > total:
        report.add(Severity.ERROR, "mass_inconsistent", "Propellant mass exceeds the total motor mass.")
    for token in meta.delay_list():
        if not (token.upper() == "P" or _is_number(token)):
            report.add(Severity.ERROR, "bad_delay", f"Invalid ejection delay '{token}'. Use numbers separated by '-' or 'P'.")
    return report


def _require_positive(report: ValidationReport, value: Optional[float], code: str, caption: str) -> None:
    """Add an error when ``value`` is missing or not strictly positive."""
    if value is None:
        report.add(Severity.ERROR, f"no_{code}", f"{caption} is required.")
    elif not math.isfinite(value) or value <= 0:
        report.add(Severity.ERROR, f"bad_{code}", f"{caption} must be greater than zero.")


def _is_number(text: str) -> bool:
    try:
        return math.isfinite(float(text))
    except ValueError:
        return False


def validate_motor(motor: Motor) -> ValidationReport:
    """Full validation (properties + thrust curve)."""
    report = validate_metadata(motor)
    report.extend(validate_points(motor.points))
    return report
