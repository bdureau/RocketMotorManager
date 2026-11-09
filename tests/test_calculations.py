"""Tests of the physics calculations, units and validation."""

from __future__ import annotations

import math

import pytest

from models.motor import Motor
from models.motor_calculations import MotorCalculator, burn_window, impulse_class, total_impulse
from models.motor_metadata import MotorMetadata
from models.thrust_point import ThrustPoint
from models.units import convert, display_unit, Quantity
from models.validation import Severity, validate_metadata, validate_points
from services.thrust_analysis import ThrustAnalysisService, resample, simplify, smooth


def test_triangle_impulse_and_average(triangle_motor):
    result = MotorCalculator("curve").analyse(triangle_motor)
    assert result.total_impulse_ns == pytest.approx(10.0)
    assert result.maximum_thrust_n == 10.0
    assert result.time_to_max_thrust_s == 1.0
    assert result.burn_time_s == pytest.approx(2.0)
    assert result.average_thrust_n == pytest.approx(5.0)
    assert result.initial_mass_g == 25.0
    assert result.propellant_mass_fraction == pytest.approx(0.4)
    assert result.specific_impulse_s == pytest.approx(10.0 / (0.010 * 9.80665))
    assert result.impulse_class == "C"  # 10 N.s is the upper bound of class C
    assert result.suggested_designation == "C5"


def test_implicit_origin_is_used():
    # first sample at 1 s: the area of (0,0)-(1,10) must be counted
    points = [ThrustPoint(1.0, 10.0), ThrustPoint(2.0, 0.0)]
    assert total_impulse(points) == pytest.approx(10.0)


def test_rectangle_impulse():
    points = [ThrustPoint(0, 0), ThrustPoint(0.001, 20), ThrustPoint(1.0, 20), ThrustPoint(1.001, 0)]
    # 0.01 (ramp up) + 19.98 (plateau) + 0.01 (ramp down)
    assert total_impulse(points) == pytest.approx(20.0, rel=1e-9)


def test_threshold_burn_time(triangle_motor):
    start, end = burn_window(triangle_motor.points, "threshold")
    assert start == pytest.approx(0.05)
    assert end == pytest.approx(1.95)
    result = MotorCalculator("threshold").analyse(triangle_motor)
    assert result.average_thrust_n == pytest.approx(10.0 / 1.9)


def test_curve_burn_time_with_leading_zeros():
    points = [ThrustPoint(0, 0), ThrustPoint(0.5, 0), ThrustPoint(1.0, 4), ThrustPoint(2.0, 4), ThrustPoint(2.5, 0), ThrustPoint(3, 0)]
    assert burn_window(points, "curve") == (0.5, 2.5)


def test_unavailable_results_are_reported():
    motor = Motor(metadata=MotorMetadata(name="X"), points=[ThrustPoint(0.1, 1.0)])
    result = MotorCalculator().analyse(motor)
    assert result.total_impulse_ns is None
    assert "total_impulse_ns" in result.unavailable
    assert "specific_impulse_s" in result.unavailable
    assert "propellant_mass_fraction" in result.unavailable


def test_non_chronological_curve_not_computed():
    motor = Motor(points=[ThrustPoint(1, 1), ThrustPoint(0.5, 2), ThrustPoint(2, 0)])
    result = MotorCalculator().analyse(motor)
    assert result.total_impulse_ns is None
    assert "increasing" in result.unavailable["total_impulse_ns"]


def test_truncated_curve_warning():
    motor = Motor(points=[ThrustPoint(0.5, 5), ThrustPoint(1, 5)])
    assert any("truncated" in w for w in MotorCalculator().analyse(motor).warnings)


@pytest.mark.parametrize(
    "impulse, letter",
    [(0.2, "1/8A"), (0.5, "1/4A"), (1.0, "1/2A"), (2.0, "A"), (2.5, "A"), (2.51, "B"), (10.0, "C"),
     (10.01, "D"), (80.0, "F"), (640.0, "I"), (40960.0, "O")],
)
def test_impulse_classes(impulse, letter):
    assert impulse_class(impulse)[0] == letter


def test_total_mass_computed_from_components():
    meta = MotorMetadata(propellant_mass_g=10, casing_mass_g=5, declared_total_mass_g=99)
    assert meta.total_mass_g == 15
    meta.casing_mass_g = None
    assert meta.total_mass_g == 99
    assert meta.empty_mass_g == 89


def test_thrust_interpolation(triangle_motor):
    assert triangle_motor.thrust_at(0.5) == pytest.approx(5.0)
    assert triangle_motor.thrust_at(1.5) == pytest.approx(5.0)
    assert triangle_motor.thrust_at(3.0) is None


# ----------------------------------------------------------------------
# Units
# ----------------------------------------------------------------------
def test_unit_conversions():
    assert convert(1.0, "lbf", "N") == pytest.approx(4.4482216152605)
    assert convert(1000.0, "ms", "s") == pytest.approx(1.0)
    assert convert(1.0, "in", "mm") == pytest.approx(25.4)
    assert convert(1.0, "kg", "g") == 1000.0
    assert convert(16.0, "oz", "lb") == pytest.approx(1.0)
    assert convert(1.0, "kgf", "N") == pytest.approx(9.80665)
    assert convert(convert(12.3, "N.s", "lbf.s"), "lbf.s", "N.s") == pytest.approx(12.3)
    with pytest.raises(ValueError):
        convert(1.0, "N", "g")
    assert display_unit("imperial", Quantity.FORCE) == "lbf"


def test_analysis_display_in_imperial(triangle_motor):
    service = ThrustAnalysisService(unit_system="imperial")
    rows = {row.key: row for row in service.display_rows(service.analyse(triangle_motor))}
    assert rows["total_impulse_ns"].unit == "lbf.s"
    assert rows["total_impulse_ns"].value == pytest.approx(10.0 / 4.4482216152605)
    assert rows["initial_mass_g"].unit == "oz"
    assert "Total impulse" in service.report_text(triangle_motor, service.analyse(triangle_motor))


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def test_validation_detects_problems():
    points = [ThrustPoint(-0.1, 1), ThrustPoint(0.2, -5), ThrustPoint(0.2, 3), ThrustPoint(0.1, float("nan")),
              ThrustPoint(0.05, 2)]
    codes = {issue.code for issue in validate_points(points).issues}
    assert {"negative_time", "negative_thrust", "duplicate_time", "non_numeric", "not_chronological", "not_terminated"} <= codes


def test_validation_valid_curve(triangle_motor):
    report = validate_points(triangle_motor.points)
    assert report.is_valid and not report.warnings


def test_metadata_validation(triangle_motor):
    triangle_motor.metadata.delays = "3-x"
    triangle_motor.metadata.casing_mass_g = None
    triangle_motor.metadata.nozzle_closure_mass_g = None
    triangle_motor.metadata.declared_total_mass_g = 20.0
    triangle_motor.metadata.propellant_mass_g = 30
    report = validate_metadata(triangle_motor)
    codes = {issue.code for issue in report.errors}
    assert "bad_delay" in codes and "mass_inconsistent" in codes
    assert all(issue.severity == Severity.ERROR for issue in report.errors)


# ----------------------------------------------------------------------
# Curve tools
# ----------------------------------------------------------------------
def test_resample_preserves_endpoints(triangle_motor):
    points = resample(triangle_motor.points, 21)
    assert len(points) == 21
    assert points[10].thrust_n == pytest.approx(10.0)
    assert total_impulse(points) == pytest.approx(10.0)


def test_simplify_removes_collinear_points():
    points = [ThrustPoint(t / 10, t if t <= 10 else 20 - t) for t in range(21)]
    simplified = simplify(points, 0.01)
    assert [p.time_s for p in simplified] == [0.0, 1.0, 2.0]


def test_smooth_keeps_length_and_positive():
    points = [ThrustPoint(i * 0.1, abs(math.sin(i)) * 5) for i in range(30)]
    smoothed = smooth(points, 7)
    assert len(smoothed) == 30
    assert all(p.thrust_n >= 0 for p in smoothed)
