"""Native project format (``.rmm.xml``): save and load the complete state.

The format is versioned through the ``formatVersion`` attribute of the root
element. Older versions are upgraded by successive migration functions so
that the reader always works on the current structure:

* ``1.0``: pre-release draft (``<Point time= thrust=>``, ``<Total>`` mass).
* ``1.1``: current format.

Floats are written with ``repr`` which round-trips exactly, so saving and
reopening a project never alters a value.
"""

from __future__ import annotations

from localization import _

import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Callable, Optional

from application.version import APP_NAME, APP_VERSION
from models.errors import FileFormatError
from models.label_template import LabelTemplate
from models.motor import Motor, PlotSettings
from models.motor_calculations import MotorCharacteristics
from models.motor_metadata import MotorMetadata
from models.thrust_point import ThrustPoint
from services.file_utils import PathLike, atomic_write_bytes, read_bytes

logger = logging.getLogger(__name__)

ROOT_TAG = "RocketMotorProject"
CURRENT_FORMAT_VERSION = "1.1"
PROJECT_EXTENSION = ".rmm.xml"


@dataclass
class XmlLoadResult:
    """A loaded project and the non-fatal remarks produced while loading."""

    motor: Motor
    format_version: str
    warnings: list[str] = field(default_factory=list)


def _version_tuple(version: str) -> tuple[int, int]:
    try:
        major, minor = version.split(".")[:2]
        return int(major), int(minor)
    except ValueError as exc:
        raise FileFormatError(_("Invalid format version '{version}'.").format(version=version)) from exc


# ----------------------------------------------------------------------
# Migrations: each function upgrades the tree by one version in place.
# ----------------------------------------------------------------------
def _migrate_1_0_to_1_1(root: ET.Element) -> None:
    """1.0 -> 1.1: rename point attributes and the declared total mass."""
    for point in root.iter("Point"):
        if "time" in point.attrib:
            point.set("t", point.attrib.pop("time"))
        if "thrust" in point.attrib:
            point.set("f", point.attrib.pop("thrust"))
    for masses in root.iter("Masses"):
        total = masses.find("Total")
        if total is not None and masses.find("DeclaredTotal") is None:
            total.tag = "DeclaredTotal"


MIGRATIONS: dict[str, tuple[str, Callable[[ET.Element], None]]] = {
    "1.0": ("1.1", _migrate_1_0_to_1_1),
}


class XmlService:
    """Serialise a :class:`Motor` (and its context) to the project XML."""

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def to_xml_bytes(self, motor: Motor, characteristics: Optional[MotorCharacteristics] = None) -> bytes:
        """Build the XML document as UTF-8 bytes."""
        root = ET.Element(ROOT_TAG, {
            "formatVersion": CURRENT_FORMAT_VERSION,
            "application": APP_NAME,
            "applicationVersion": APP_VERSION,
        })
        self._write_metadata(root, motor.metadata)
        self._write_motor(root, motor)
        if characteristics is not None:
            self._write_characteristics(root, characteristics)
        self._write_dataclass(root, "PlotSettings", motor.plot_settings)
        if motor.label is not None:
            self._write_label(root, motor.label)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"

    def save(self, path: PathLike, motor: Motor, characteristics: Optional[MotorCharacteristics] = None) -> None:
        """Atomically write the project file and update timestamps."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not motor.metadata.created:
            motor.metadata.created = now
        motor.metadata.modified = now
        atomic_write_bytes(path, self.to_xml_bytes(motor, characteristics))
        logger.info("Project saved: %s", path)

    @staticmethod
    def _text(parent: ET.Element, tag: str, value: object) -> ET.Element:
        element = ET.SubElement(parent, tag)
        if value is not None:
            element.text = repr(value) if isinstance(value, float) else str(value)
        return element

    def _write_metadata(self, root: ET.Element, meta: MotorMetadata) -> None:
        node = ET.SubElement(root, "Metadata")
        self._text(node, "Created", meta.created)
        self._text(node, "Modified", meta.modified)
        self._text(node, "SourceFile", meta.source_file)
        extra = ET.SubElement(node, "Extra")
        for key, value in meta.extra.items():
            item = ET.SubElement(extra, "Item", {"key": key})
            item.text = value

    def _write_motor(self, root: ET.Element, motor: Motor) -> None:
        meta = motor.metadata
        node = ET.SubElement(root, "Motor")
        general = ET.SubElement(node, "General")
        for tag, value in (("Name", meta.name), ("Manufacturer", meta.manufacturer),
                           ("Designation", meta.designation), ("Delays", meta.delays),
                           ("PropellantType", meta.propellant_type), ("Description", meta.description),
                           ("Comments", meta.comments)):
            self._text(general, tag, value)
        dims = ET.SubElement(node, "Dimensions", {"unit": "mm"})
        self._text(dims, "Diameter", meta.diameter_mm)
        self._text(dims, "Length", meta.length_mm)
        masses = ET.SubElement(node, "Masses", {"unit": "g"})
        self._text(masses, "Propellant", meta.propellant_mass_g)
        self._text(masses, "Casing", meta.casing_mass_g)
        self._text(masses, "NozzleClosure", meta.nozzle_closure_mass_g)
        self._text(masses, "DeclaredTotal", meta.declared_total_mass_g)
        total = self._text(masses, "Total", meta.total_mass_g)
        total.set("computed", "true")
        comments = ET.SubElement(node, "EngComments")
        for line in meta.eng_comments:
            self._text(comments, "Line", line)
        curve = ET.SubElement(node, "ThrustCurve", {"timeUnit": "s", "thrustUnit": "N", "count": str(len(motor.points))})
        for point in motor.points:
            ET.SubElement(curve, "Point", {"t": repr(point.time_s), "f": repr(point.thrust_n)})

    def _write_characteristics(self, root: ET.Element, result: MotorCharacteristics) -> None:
        node = ET.SubElement(root, "CalculatedCharacteristics", {
            "burnTimeMethod": result.burn_time_method, "informative": "true",
        })
        for key, caption, value, unit in result.as_rows():
            item = ET.SubElement(node, "Value", {"key": key, "caption": caption, "unit": unit})
            if value is not None:
                item.text = repr(value)
        if result.impulse_class:
            self._text(node, "ImpulseClass", result.impulse_class)

    @staticmethod
    def _write_dataclass(root: ET.Element, tag: str, instance: object) -> None:
        attributes = {}
        for spec in fields(instance):  # type: ignore[arg-type]
            value = getattr(instance, spec.name)
            if value is not None:
                attributes[spec.name] = repr(value) if isinstance(value, float) else str(value)
        ET.SubElement(root, tag, attributes)

    def _write_label(self, root: ET.Element, template: LabelTemplate) -> None:
        data = template.to_dict()
        selected = data.pop("fields")
        node = ET.SubElement(root, "Label", {k: str(v) for k, v in data.items()})
        for name in selected:
            ET.SubElement(node, "Field", {"name": name})

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self, path: PathLike) -> XmlLoadResult:
        """Read, validate, migrate and decode a project file."""
        data = read_bytes(path)
        try:
            result = self.from_xml_bytes(data)
        except FileFormatError as exc:
            exc.file_path = str(path)
            raise
        logger.info("Project loaded: %s (format %s)", path, result.format_version)
        return result

    def from_xml_bytes(self, data: bytes) -> XmlLoadResult:
        """Decode a project from XML bytes.

        Raises:
            FileFormatError: If the XML is malformed, not a project, of an
                unsupported version or structurally invalid.
        """
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            line = exc.position[0] if hasattr(exc, "position") else None
            raise FileFormatError(_('The project file is corrupted (invalid XML): {value}').format(value=exc), line_number=line) from exc
        if root.tag != ROOT_TAG:
            raise FileFormatError(_("Not a Rocket Motor Manager project (root element '{tag}').").format(tag=root.tag))
        version = root.get("formatVersion", "1.0")
        warnings = self._migrate(root, version)
        motor_node = root.find("Motor")
        if motor_node is None:
            raise FileFormatError(_('Invalid project: the <Motor> element is missing.'))
        motor = Motor(
            metadata=self._read_metadata(root, motor_node),
            points=self._read_points(motor_node),
            plot_settings=self._read_plot_settings(root),
            label=self._read_label(root),
        )
        return XmlLoadResult(motor=motor, format_version=version, warnings=warnings)

    @staticmethod
    def _migrate(root: ET.Element, version: str) -> list[str]:
        warnings: list[str] = []
        current = _version_tuple(CURRENT_FORMAT_VERSION)
        found = _version_tuple(version)
        if found[0] > current[0]:
            raise FileFormatError(
                _('This project was created with a newer, incompatible format ({version}). Please update the application.').format(version=version)
            )
        if found > current:
            warnings.append(_('Project format {version} is newer than {current_format_version}; unknown data may be ignored.').format(version=version, current_format_version=CURRENT_FORMAT_VERSION))
            return warnings
        while version in MIGRATIONS:
            target, migrate = MIGRATIONS[version]
            migrate(root)
            warnings.append(_('Project upgraded from format {version} to {target}.').format(version=version, target=target))
            version = target
        return warnings

    def _read_metadata(self, root: ET.Element, motor_node: ET.Element) -> MotorMetadata:
        meta = MotorMetadata()
        info = root.find("Metadata")
        if info is not None:
            meta.created = self._str(info, "Created")
            meta.modified = self._str(info, "Modified")
            meta.source_file = self._str(info, "SourceFile")
            for item in info.iterfind("Extra/Item"):
                meta.extra[item.get("key", "")] = item.text or ""
        general = motor_node.find("General")
        if general is not None:
            meta.name = self._str(general, "Name")
            meta.manufacturer = self._str(general, "Manufacturer")
            meta.designation = self._str(general, "Designation")
            meta.delays = self._str(general, "Delays") or "0"
            meta.propellant_type = self._str(general, "PropellantType")
            meta.description = self._str(general, "Description")
            meta.comments = self._str(general, "Comments")
        dims = motor_node.find("Dimensions")
        if dims is not None:
            meta.diameter_mm = self._float(dims, "Diameter")
            meta.length_mm = self._float(dims, "Length")
        masses = motor_node.find("Masses")
        if masses is not None:
            meta.propellant_mass_g = self._float(masses, "Propellant")
            meta.casing_mass_g = self._float(masses, "Casing")
            meta.nozzle_closure_mass_g = self._float(masses, "NozzleClosure")
            meta.declared_total_mass_g = self._float(masses, "DeclaredTotal")
        meta.eng_comments = [line.text or "" for line in motor_node.iterfind("EngComments/Line")]
        return meta

    @staticmethod
    def _str(parent: ET.Element, tag: str) -> str:
        node = parent.find(tag)
        return (node.text or "") if node is not None else ""

    @staticmethod
    def _float(parent: ET.Element, tag: str) -> Optional[float]:
        node = parent.find(tag)
        if node is None or node.text is None or not node.text.strip():
            return None
        try:
            value = float(node.text)
        except ValueError as exc:
            raise FileFormatError(_("Invalid number '{text}' in <{tag}/{tag2}>.").format(text=node.text, tag=parent.tag, tag2=tag)) from exc
        if not math.isfinite(value):
            raise FileFormatError(_('Non-finite number in <{tag}/{tag2}>.').format(tag=parent.tag, tag2=tag))
        return value

    @staticmethod
    def _read_points(motor_node: ET.Element) -> list[ThrustPoint]:
        curve = motor_node.find("ThrustCurve")
        if curve is None:
            return []
        points = []
        for index, node in enumerate(curve.iterfind("Point"), start=1):
            try:
                points.append(ThrustPoint(float(node.attrib["t"]), float(node.attrib["f"])))
            except (KeyError, ValueError) as exc:
                raise FileFormatError(_('Invalid thrust point #{index} in <ThrustCurve>: {attrib}.').format(index=index, attrib=node.attrib)) from exc
        declared = curve.get("count")
        if declared is not None and declared.isdigit() and int(declared) != len(points):
            raise FileFormatError(
                _('Thrust curve is incomplete: {count} points found, {declared} declared.').format(count=len(points), declared=declared)
            )
        return points

    @staticmethod
    def _read_plot_settings(root: ET.Element) -> PlotSettings:
        settings = PlotSettings()
        node = root.find("PlotSettings")
        if node is None:
            return settings
        for spec in fields(PlotSettings):
            raw = node.get(spec.name)
            if raw is None:
                continue
            default = getattr(settings, spec.name)
            if isinstance(default, bool):
                setattr(settings, spec.name, raw == "True")
            elif isinstance(default, str):
                setattr(settings, spec.name, raw)
            else:
                try:
                    setattr(settings, spec.name, float(raw))
                except ValueError:
                    logger.warning("Ignoring invalid plot setting %s=%s", spec.name, raw)
        return settings

    @staticmethod
    def _read_label(root: ET.Element) -> Optional[LabelTemplate]:
        node = root.find("Label")
        if node is None:
            return None
        data: dict[str, object] = dict(node.attrib)
        data["fields"] = [field_node.get("name", "") for field_node in node.iterfind("Field")]
        return LabelTemplate.from_dict(data)
