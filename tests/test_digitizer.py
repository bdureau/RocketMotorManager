"""Tests of the image digitizer on synthetic graphs with a known curve."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from models.errors import CalibrationError, FileFormatError
from models.motor_calculations import total_impulse
from services.image_digitizer import (
    AxisCalibration, CalibrationPoint, DigitizerSettings, ImageCorrection, apply_corrections, color_at,
    detect_curve_color, digitize, load_image, order_quad, remove_outliers, rotate,
)

# Graph geometry: origin at (80, 420) px, 1 s = 300 px, 1 N = 20 px (20 N = 400 px)
ORIGIN = (80, 420)
PX_PER_S, PX_PER_N = 300.0, 20.0


def thrust_function(t: np.ndarray) -> np.ndarray:
    """A realistic motor shape: fast rise, peak at 0.3 s, sustain, tail-off at 1.8 s."""
    peak = 15.0 * np.exp(-((t - 0.3) / 0.12) ** 2)
    sustain = np.where(t < 1.6, 5.0, np.clip(5.0 * (1.8 - t) / 0.2, 0.0, None))
    rise = np.clip(t / 0.15, 0.0, 1.0)
    return np.clip(rise * (peak + sustain), 0.0, None)


def to_px(t: float, f: float) -> tuple[int, int]:
    return int(round(ORIGIN[0] + t * PX_PER_S)), int(round(ORIGIN[1] - f * PX_PER_N))


@pytest.fixture
def graph_image() -> np.ndarray:
    image = np.full((480, 760, 3), 255, dtype=np.uint8)
    for i in range(1, 8):  # grid
        x = ORIGIN[0] + int(i * 0.25 * PX_PER_S)
        cv2.line(image, (x, 20), (x, ORIGIN[1]), (215, 215, 215), 1)
    for i in range(1, 5):
        y = ORIGIN[1] - int(i * 5 * PX_PER_N)
        cv2.line(image, (ORIGIN[0], y), (740, y), (215, 215, 215), 1)
    cv2.line(image, ORIGIN, (740, ORIGIN[1]), (0, 0, 0), 2)  # axes
    cv2.line(image, ORIGIN, (ORIGIN[0], 15), (0, 0, 0), 2)
    cv2.putText(image, "Thrust (N)", (90, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    times = np.linspace(0.0, 1.85, 600)
    curve = np.array([to_px(t, f) for t, f in zip(times, thrust_function(times))], dtype=np.int32)
    cv2.polylines(image, [curve], False, (30, 30, 220), 3, cv2.LINE_AA)
    return image


@pytest.fixture
def calibration() -> AxisCalibration:
    cal = AxisCalibration()
    cal.set_point(CalibrationPoint(*to_px(0, 0), 0.0, 0.0, "Origin"))
    cal.set_point(CalibrationPoint(*to_px(2.0, 0), 2.0, 0.0, "Time max"))
    cal.set_point(CalibrationPoint(*to_px(0, 20.0), 0.0, 20.0, "Thrust max"))
    return cal


def test_calibration_mapping(calibration):
    physical = calibration.pixel_to_physical(np.array([to_px(1.0, 10.0)]))
    assert physical[0] == pytest.approx([1.0, 10.0], abs=1e-6)
    pixel = calibration.physical_to_pixel(np.array([[0.5, 5.0]]))
    assert pixel[0] == pytest.approx(to_px(0.5, 5.0), abs=1e-6)
    assert calibration.rms_error() == pytest.approx(0.0, abs=1e-9)


def test_calibration_with_extra_points_least_squares(calibration):
    calibration.set_point(CalibrationPoint(*to_px(1.0, 10.0), 1.0, 10.0))
    calibration.set_point(CalibrationPoint(to_px(1.5, 15.0)[0] + 1, to_px(1.5, 15.0)[1], 1.5, 15.0))
    assert len(calibration.points) == 5
    assert 0.0 < calibration.rms_error() < 1.0


def test_calibration_replaces_standard_points(calibration):
    calibration.set_point(CalibrationPoint(0, 0, 0.0, 0.0, "Origin"))
    assert sum(p.label == "Origin" for p in calibration.points) == 1


def test_degenerate_calibration():
    cal = AxisCalibration()
    with pytest.raises(CalibrationError):
        cal.matrix()
    for i in range(3):
        cal.set_point(CalibrationPoint(10 * i, 10 * i, float(i), float(i)))
    assert not cal.is_ready()
    with pytest.raises(CalibrationError):
        cal.matrix()


def test_rotated_graph_calibration(calibration):
    # affine fit absorbs a small rotation of the picture
    angle = np.radians(3.0)
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    cal = AxisCalibration()
    for p in calibration.points:
        x, y = rot @ np.array([p.px, p.py])
        cal.set_point(CalibrationPoint(x, y, p.time_s, p.thrust_n, p.label))
    x, y = rot @ np.array(to_px(1.0, 10.0), dtype=float)
    assert cal.pixel_to_physical(np.array([[x, y]]))[0] == pytest.approx([1.0, 10.0], abs=1e-6)


def test_detect_color(graph_image):
    b, g, r = detect_curve_color(graph_image)
    assert r > 150 and b < 120 and g < 120


def test_full_extraction_accuracy(graph_image, calibration):
    settings = DigitizerSettings(color_bgr=detect_curve_color(graph_image), tolerance=45)
    result = digitize(graph_image, calibration, settings)
    times = np.array([p.time_s for p in result.points])
    thrusts = np.array([p.thrust_n for p in result.points])
    assert len(result.points) > 400
    assert np.all(np.diff(times) > 0)
    error = np.abs(thrusts[:-1] - thrust_function(times[:-1]))
    assert np.median(error) < 0.1  # Newtons
    assert np.percentile(error, 95) < 0.5
    assert np.max(thrusts) == pytest.approx(np.max(thrust_function(times)), abs=0.4)
    reference = total_impulse([type(result.points[0])(t, f) for t, f in zip(times, thrust_function(times))])
    assert total_impulse(result.points) == pytest.approx(reference, rel=0.02)
    assert result.points[-1].thrust_n == 0.0  # curve closed


def test_extraction_with_resampling(graph_image, calibration):
    settings = DigitizerSettings(color_bgr=detect_curve_color(graph_image), max_points=50, close_curve=False)
    result = digitize(graph_image, calibration, settings)
    assert len(result.points) == 50


def test_wrong_color_raises(graph_image, calibration):
    with pytest.raises(ValueError):
        digitize(graph_image, calibration, DigitizerSettings(color_bgr=(0, 255, 0), tolerance=5))


def test_outlier_removal():
    values = np.sin(np.linspace(0, 3, 100)) * 10
    values[50] += 40
    keep = remove_outliers(values, threshold=4)
    assert not keep[50]
    assert keep.sum() >= 97


def test_corrections_pipeline(graph_image):
    settings = ImageCorrection(rotation_deg=5, crop=(10, 10, 500, 300), contrast=1.3, brightness=10,
                               grayscale=True, denoise="median", denoise_strength=1)
    result = apply_corrections(graph_image, settings)
    assert result.shape == (300, 500, 3)
    assert np.array_equal(result[:, :, 0], result[:, :, 1])  # grey
    assert rotate(graph_image, 90).shape[:2] == (760, 480)
    assert ImageCorrection().is_identity()


def test_perspective_correction(graph_image):
    corners = [(700, 450), (20, 10), (700, 10), (20, 450)]
    ordered = order_quad(corners)
    assert ordered[0].tolist() == [20, 10] and ordered[2].tolist() == [700, 450]
    result = apply_corrections(graph_image, ImageCorrection(perspective=corners))
    assert result.shape[:2] == (440, 680)


def test_color_pipette(graph_image):
    assert color_at(graph_image, 5, 5) == (255, 255, 255)


def test_load_image_roundtrip(graph_image, tmp_path):
    path = tmp_path / "graphé.png"  # non-ASCII file name
    ok, encoded = cv2.imencode(".png", graph_image)
    path.write_bytes(encoded.tobytes())
    assert np.array_equal(load_image(path), graph_image)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(FileFormatError):
        load_image(bad)


def test_grayscale_and_alpha_normalisation(tmp_path):
    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    rgba[:, :, 3] = 0  # fully transparent -> white
    path = tmp_path / "alpha.png"
    path.write_bytes(cv2.imencode(".png", rgba)[1].tobytes())
    assert load_image(path)[0, 0].tolist() == [255, 255, 255]
