"""Tests of the ENG reader and writer."""

from __future__ import annotations

import pytest

from models.errors import FileFormatError, ValidationError
from models.motor_calculations import total_impulse
from services.eng_service import EngService


def test_read_reference_file(data_dir):
    result = EngService().read_file(data_dir / "sample_C6.eng")
    assert len(result.motors) == 1
    motor = result.motors[0]
    meta = motor.metadata
    assert meta.name == "C6"
    assert meta.manufacturer == "Estes"
    assert meta.diameter_mm == 18
    assert meta.length_mm == 70
    assert meta.delays == "0-3-5-7"
    assert meta.propellant_mass_g == pytest.approx(10.8)
    assert meta.total_mass_g == pytest.approx(23.1)
    assert motor.point_count() == 24
    assert motor.points[0].time_s == pytest.approx(0.031)
    assert motor.points[-1].thrust_n == 0.0
    assert meta.eng_comments and "Representative" in meta.eng_comments[0]
    assert result.warnings == []
    # A C motor: total impulse between 5 and 10 N.s
    assert 5.0 < total_impulse(motor.points) <= 10.0


def test_multi_motor_file_and_comments(data_dir):
    result = EngService().read_file(data_dir / "multi_motor.eng")
    assert [m.metadata.name for m in result.motors] == ["A8", "F50T"]
    a8, f50 = result.motors
    assert a8.metadata.eng_comments[:2] == ["File with two motors and comments", "second comment line"]
    assert "trailing note for A8" in f50.metadata.eng_comments
    assert f50.metadata.manufacturer == "AeroTech"
    assert f50.points[1].thrust_n == 65.0  # inline comment stripped


def test_invalid_data_reports_line_number(data_dir):
    with pytest.raises(FileFormatError) as info:
        EngService().read_file(data_dir / "invalid_data.eng")
    assert info.value.line_number == 5
    assert "abc" in str(info.value)


def test_invalid_header_reports_line_number(data_dir):
    with pytest.raises(FileFormatError) as info:
        EngService().read_file(data_dir / "invalid_header.eng")
    assert info.value.line_number == 1
    assert "length" in str(info.value)


@pytest.mark.parametrize("text", ["", "; only a comment\n", "0.1 2.0\n"])
def test_not_an_eng_file(text):
    with pytest.raises(FileFormatError):
        EngService().parse(text)


def test_header_without_data():
    with pytest.raises(FileFormatError):
        EngService().parse("X1 18 70 0 0.01 0.02 Test\n")


def test_unterminated_curve_is_a_warning():
    result = EngService().parse("X1 18 70 0 0.01 0.02 Test\n0.1 5\n0.2 4\n")
    assert any("zero thrust" in w for w in result.warnings)


def test_write_and_reread_roundtrip(data_dir, tmp_path):
    service = EngService()
    original = service.read_file(data_dir / "sample_C6.eng").motors[0]
    out = tmp_path / "out.eng"
    service.write_file(out, [original])
    raw = out.read_bytes()
    assert b"\r\n" in raw and raw.decode("ascii")
    reread = service.read_file(out).motors[0]
    assert reread.points == original.points
    assert reread.metadata.name == original.metadata.name
    assert reread.metadata.total_mass_g == pytest.approx(original.metadata.total_mass_g)
    assert reread.metadata.eng_comments[: len(original.metadata.eng_comments)] == original.metadata.eng_comments


def test_writer_header_format(triangle_motor):
    text = EngService().generate([triangle_motor])
    lines = [line for line in text.splitlines() if line and not line.startswith(";")]
    assert lines[0] == "T10 18 70 3 0.01 0.025 TestCo"
    # the implicit (0, 0) point is not written
    assert lines[1].split() == ["1", "10"]
    assert lines[-1].split() == ["2", "0"]


def test_writer_sanitises_tokens(triangle_motor):
    triangle_motor.metadata.name = "My Motor"
    triangle_motor.metadata.manufacturer = "Société X"
    header = [l for l in EngService().generate([triangle_motor]).splitlines() if l and l[0] != ";"][0]
    assert header.split()[0] == "My_Motor"
    assert header.split()[-1] == "Societe_X"


def test_writer_refuses_invalid_data(triangle_motor):
    triangle_motor.metadata.diameter_mm = None
    with pytest.raises(ValidationError):
        EngService().generate([triangle_motor])


def test_writer_refuses_non_chronological(triangle_motor):
    triangle_motor.points.reverse()
    with pytest.raises(ValidationError):
        EngService().generate([triangle_motor])


def test_writer_warnings_can_block(triangle_motor):
    triangle_motor.points[-1] = type(triangle_motor.points[-1])(2.0, 1.0)  # not terminated
    EngService().generate([triangle_motor], allow_warnings=True)
    with pytest.raises(ValidationError):
        EngService().generate([triangle_motor], allow_warnings=False)


def test_number_format_never_scientific(triangle_motor):
    triangle_motor.points.insert(1, type(triangle_motor.points[0])(0.00001, 0.0000123))
    text = EngService().generate([triangle_motor])
    assert "e-" not in text.lower()
