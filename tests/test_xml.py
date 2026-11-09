"""Tests of the native XML project format."""

from __future__ import annotations

import pytest

from models.errors import FileFormatError
from models.label_template import LabelTemplate
from models.motor_calculations import MotorCalculator
from services.xml_service import CURRENT_FORMAT_VERSION, XmlService


def test_save_and_load_roundtrip(triangle_motor, tmp_path):
    triangle_motor.metadata.description = "Description <with> & special chars é"
    triangle_motor.metadata.eng_comments = ["first", "second"]
    triangle_motor.metadata.extra = {"test_stand": "TS-1"}
    triangle_motor.plot_settings.show_grid = False
    triangle_motor.plot_settings.x_max = 2.5
    triangle_motor.label = LabelTemplate(name="Mine", width_mm=80.0, fields=["total_impulse", "burn_time"])
    triangle_motor.points.insert(1, type(triangle_motor.points[0])(0.1 + 0.2, 1 / 3))
    service = XmlService()
    path = tmp_path / "project.rmm.xml"
    service.save(path, triangle_motor, MotorCalculator().analyse(triangle_motor))
    result = service.load(path)
    loaded = result.motor
    assert result.format_version == CURRENT_FORMAT_VERSION
    assert loaded.points == triangle_motor.points  # bit-exact floats
    assert loaded.metadata.description == triangle_motor.metadata.description
    assert loaded.metadata.casing_mass_g == 12.0
    assert loaded.metadata.total_mass_g == 25.0
    assert loaded.metadata.eng_comments == ["first", "second"]
    assert loaded.metadata.extra == {"test_stand": "TS-1"}
    assert loaded.metadata.created and loaded.metadata.modified
    assert loaded.plot_settings.show_grid is False
    assert loaded.plot_settings.x_max == 2.5
    assert loaded.plot_settings.y_max is None
    assert loaded.label.name == "Mine"
    assert loaded.label.fields == ["total_impulse", "burn_time"]
    assert loaded.label.width_mm == 80.0


def test_characteristics_are_stored(triangle_motor):
    data = XmlService().to_xml_bytes(triangle_motor, MotorCalculator().analyse(triangle_motor))
    assert b'key="total_impulse_ns"' in data
    assert b"<ImpulseClass>C</ImpulseClass>" in data


def test_migration_from_1_0():
    legacy = b"""<?xml version='1.0'?>
<RocketMotorProject formatVersion="1.0">
  <Motor>
    <General><Name>OLD</Name><Manufacturer>Legacy</Manufacturer></General>
    <Masses unit="g"><Propellant>5</Propellant><Total>12</Total></Masses>
    <ThrustCurve><Point time="0.1" thrust="3"/><Point time="0.5" thrust="0"/></ThrustCurve>
  </Motor>
</RocketMotorProject>"""
    result = XmlService().from_xml_bytes(legacy)
    assert result.motor.metadata.declared_total_mass_g == 12.0
    assert result.motor.points[0].thrust_n == 3.0
    assert any("upgraded" in w for w in result.warnings)


@pytest.mark.parametrize(
    "content, fragment",
    [
        (b"<RocketMotorProject><Motor>", "corrupted"),
        (b"<Other/>", "Not a Rocket Motor Manager project"),
        (b'<RocketMotorProject formatVersion="1.1"/>', "Motor"),
        (b'<RocketMotorProject formatVersion="9.0"><Motor/></RocketMotorProject>', "newer"),
        (b'<RocketMotorProject formatVersion="1.1"><Motor><Dimensions><Diameter>abc</Diameter></Dimensions></Motor></RocketMotorProject>', "Invalid number"),
        (b'<RocketMotorProject formatVersion="1.1"><Motor><ThrustCurve count="3"><Point t="0" f="1"/></ThrustCurve></Motor></RocketMotorProject>', "incomplete"),
        (b'<RocketMotorProject formatVersion="1.1"><Motor><ThrustCurve><Point t="x" f="1"/></ThrustCurve></Motor></RocketMotorProject>', "Invalid thrust point"),
    ],
)
def test_invalid_projects(content, fragment):
    with pytest.raises(FileFormatError) as info:
        XmlService().from_xml_bytes(content)
    assert fragment in str(info.value)


def test_newer_minor_version_is_warning():
    result = XmlService().from_xml_bytes(b'<RocketMotorProject formatVersion="1.9"><Motor/></RocketMotorProject>')
    assert result.warnings


def test_failed_save_keeps_original(triangle_motor, tmp_path, monkeypatch):
    path = tmp_path / "keep.rmm.xml"
    path.write_text("original")
    service = XmlService()

    def broken(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "to_xml_bytes", broken)
    with pytest.raises(RuntimeError):
        service.save(path, triangle_motor)
    assert path.read_text() == "original"
