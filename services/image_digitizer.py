"""Thrust curve digitizer: image correction, axis calibration and curve
extraction (pure NumPy/OpenCV, independent of the user interface).

Workflow:

1. :func:`load_image` reads a photo, screenshot or scan.
2. :class:`ImageCorrection` + :func:`apply_corrections` straighten and
   clean the image (perspective, rotation, crop, contrast, grey, denoise).
3. :class:`AxisCalibration` maps pixels to physical units with an affine
   least-squares fit over three or more reference points, which also
   compensates a slightly rotated or skewed graph.
4. :func:`detect_curve_color`, :func:`color_mask` and
   :func:`extract_curve_pixels` isolate the curve.
5. :func:`remove_outliers` and :func:`pixels_to_thrust_points` produce the
   final, chronological thrust points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

import cv2
import numpy as np

from models.errors import CalibrationError, FileFormatError
from models.thrust_point import ThrustPoint
from services.file_utils import PathLike, read_bytes
from services.thrust_analysis import resample, simplify

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
DENOISE_METHODS = ("none", "median", "gaussian", "bilateral", "nlmeans")

Point2D = tuple[float, float]
Rect = tuple[int, int, int, int]  # x, y, width, height


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------
def load_image(path: PathLike) -> np.ndarray:
    """Load an image as a BGR uint8 array (unicode paths supported).

    Raises:
        FileAccessError: If the file cannot be read.
        FileFormatError: If the content is not a supported image.
    """
    data = np.frombuffer(read_bytes(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileFormatError(f"Unsupported or corrupted image file: {path}")
    return normalize_image(image)


def normalize_image(image: np.ndarray) -> np.ndarray:
    """Convert any depth / channel layout to 8-bit BGR (alpha flattened on white)."""
    if image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        rgb = image[:, :, :3].astype(np.float32)
        return (rgb * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    return image[:, :, :3].copy()


# ----------------------------------------------------------------------
# Corrections
# ----------------------------------------------------------------------
@dataclass
class ImageCorrection:
    """Corrections applied, in this order, to the original image."""

    perspective: Optional[list[Point2D]] = None  # 4 corners in original pixels
    rotation_deg: float = 0.0
    crop: Optional[Rect] = None  # in pixels after rotation
    contrast: float = 1.0  # multiplier (1 = unchanged)
    brightness: float = 0.0  # offset (-100..100)
    grayscale: bool = False
    denoise: str = "none"
    denoise_strength: int = 3

    def is_identity(self) -> bool:
        """True when no correction is active."""
        return self == ImageCorrection()


def order_quad(points: Sequence[Point2D]) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.array(points, dtype=np.float32)
    if pts.shape != (4, 2):
        raise ValueError("Perspective correction needs exactly four points.")
    sums, diffs = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(sums)], pts[np.argmin(diffs)], pts[np.argmax(sums)], pts[np.argmax(diffs)]],
                    dtype=np.float32)


def correct_perspective(image: np.ndarray, corners: Sequence[Point2D]) -> np.ndarray:
    """Warp the quadrilateral ``corners`` to a straight rectangle."""
    quad = order_quad(corners)
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    height = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    if width < 10 or height < 10:
        raise ValueError("The perspective quadrilateral is too small.")
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(quad, target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def rotate(image: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate counter-clockwise by ``angle_deg``, enlarging the canvas (white fill)."""
    if abs(angle_deg) < 1e-9:
        return image
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(height * sin + width * cos), int(height * cos + width * sin)
    matrix[0, 2] += new_w / 2.0 - center[0]
    matrix[1, 2] += new_h / 2.0 - center[1]
    return cv2.warpAffine(image, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def crop(image: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop to ``(x, y, width, height)`` clamped to the image."""
    x, y, w, h = rect
    height, width = image.shape[:2]
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(width, int(x + w)), min(height, int(y + h))
    if x1 - x0 < 5 or y1 - y0 < 5:
        raise ValueError("The crop rectangle is too small.")
    return image[y0:y1, x0:x1].copy()


def adjust_contrast(image: np.ndarray, contrast: float, brightness: float) -> np.ndarray:
    """Linear contrast/brightness adjustment around mid-grey."""
    if contrast == 1.0 and brightness == 0.0:
        return image
    adjusted = (image.astype(np.float32) - 128.0) * contrast + 128.0 + brightness
    return np.clip(adjusted, 0, 255).astype(np.uint8)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Grey-level image kept as three channels."""
    return cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def denoise(image: np.ndarray, method: str, strength: int = 3) -> np.ndarray:
    """Noise filtering: median, gaussian, bilateral or non-local means."""
    strength = max(1, int(strength))
    kernel = strength * 2 + 1
    if method == "median":
        return cv2.medianBlur(image, kernel)
    if method == "gaussian":
        return cv2.GaussianBlur(image, (kernel, kernel), 0)
    if method == "bilateral":
        return cv2.bilateralFilter(image, kernel, 25 * strength, 25 * strength)
    if method == "nlmeans":
        return cv2.fastNlMeansDenoisingColored(image, None, 3 * strength, 3 * strength, 7, 21)
    return image


def apply_corrections(image: np.ndarray, settings: ImageCorrection) -> np.ndarray:
    """Apply every correction in a fixed, documented order."""
    result = image
    if settings.perspective:
        result = correct_perspective(result, settings.perspective)
    result = rotate(result, settings.rotation_deg)
    if settings.crop:
        result = crop(result, settings.crop)
    result = adjust_contrast(result, settings.contrast, settings.brightness)
    if settings.grayscale:
        result = to_grayscale(result)
    return denoise(result, settings.denoise, settings.denoise_strength)


# ----------------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------------
@dataclass
class CalibrationPoint:
    """A pixel with known physical coordinates."""

    px: float
    py: float
    time_s: float
    thrust_n: float
    label: str = "Extra"


@dataclass
class AxisCalibration:
    """Affine pixel <-> physical mapping fitted on reference points.

    Standard references are ``Origin`` (t0, F0), ``Time max`` (t1, F0) and
    ``Thrust max`` (t0, F1). Extra points improve the precision through a
    least-squares fit.
    """

    points: list[CalibrationPoint] = field(default_factory=list)

    def set_point(self, point: CalibrationPoint) -> None:
        """Add a point, replacing a standard reference with the same label."""
        if point.label != "Extra":
            self.points = [p for p in self.points if p.label != point.label]
        self.points.append(point)

    def remove(self, index: int) -> None:
        """Remove a reference point."""
        del self.points[index]

    def clear(self) -> None:
        """Remove every reference point."""
        self.points.clear()

    def _design(self) -> tuple[np.ndarray, np.ndarray]:
        pixels = np.array([[p.px, p.py, 1.0] for p in self.points])
        physical = np.array([[p.time_s, p.thrust_n] for p in self.points])
        return pixels, physical

    def is_ready(self) -> bool:
        """True when at least three non-collinear points exist."""
        if len(self.points) < 3:
            return False
        pixels, physical = self._design()
        return np.linalg.matrix_rank(pixels) == 3 and np.linalg.matrix_rank(np.c_[physical, np.ones(len(physical))]) == 3

    def matrix(self) -> np.ndarray:
        """2x3 affine matrix M with [t, F] = M @ [px, py, 1].

        Raises:
            CalibrationError: If fewer than three valid points exist.
        """
        if len(self.points) < 3:
            raise CalibrationError("Calibration needs the origin, the time-axis and the thrust-axis reference points.")
        if not self.is_ready():
            raise CalibrationError("Calibration points are aligned or have identical values; the mapping is undefined.")
        pixels, physical = self._design()
        solution, *_ = np.linalg.lstsq(pixels, physical, rcond=None)
        return solution.T

    def pixel_to_physical(self, pixels: np.ndarray) -> np.ndarray:
        """Convert an (N, 2) pixel array to (N, 2) [time, thrust]."""
        pixels = np.atleast_2d(np.asarray(pixels, dtype=float))
        return np.c_[pixels, np.ones(len(pixels))] @ self.matrix().T

    def physical_to_pixel(self, physical: np.ndarray) -> np.ndarray:
        """Inverse mapping: (N, 2) [time, thrust] to pixels."""
        full = np.vstack([self.matrix(), [0.0, 0.0, 1.0]])
        inverse = np.linalg.inv(full)
        physical = np.atleast_2d(np.asarray(physical, dtype=float))
        return (np.c_[physical, np.ones(len(physical))] @ inverse.T)[:, :2]

    def rms_error(self) -> float:
        """RMS residual of the fit, expressed in pixels (0 with three points)."""
        pixels, physical = self._design()
        predicted = self.physical_to_pixel(physical)
        return float(np.sqrt(np.mean(np.sum((predicted - pixels[:, :2]) ** 2, axis=1))))

    def plot_area(self, shape: tuple[int, ...]) -> Rect:
        """Bounding rectangle of the reference points (the plotting area)."""
        xs = [p.px for p in self.points]
        ys = [p.py for p in self.points]
        height, width = shape[:2]
        x0, x1 = max(0, int(min(xs))), min(width, int(np.ceil(max(xs))))
        y0, y1 = max(0, int(min(ys))), min(height, int(np.ceil(max(ys))))
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


# ----------------------------------------------------------------------
# Curve isolation
# ----------------------------------------------------------------------
def color_at(image: np.ndarray, x: float, y: float, radius: int = 1) -> tuple[int, int, int]:
    """Median BGR colour of a small neighbourhood (pipette tool)."""
    height, width = image.shape[:2]
    x0, x1 = max(0, int(x) - radius), min(width, int(x) + radius + 1)
    y0, y1 = max(0, int(y) - radius), min(height, int(y) + radius + 1)
    patch = image[y0:y1, x0:x1].reshape(-1, 3)
    if patch.size == 0:
        raise ValueError("Point outside the image.")
    return tuple(int(v) for v in np.median(patch, axis=0))  # type: ignore[return-value]


def detect_curve_color(image: np.ndarray, roi: Optional[Rect] = None) -> tuple[int, int, int]:
    """Guess the curve colour: the dominant saturated hue, or the darkest
    ink when the graph is monochrome."""
    region = _roi(image, roi)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    saturated = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 50)
    if saturated.sum() > max(20, 0.0005 * saturated.size):
        hues = hsv[:, :, 0][saturated]
        histogram = np.bincount(hues, minlength=180).astype(float)
        histogram = np.convolve(np.r_[histogram[-4:], histogram, histogram[:4]], np.ones(9) / 9, "valid")
        peak = int(np.argmax(histogram))
        distance = np.minimum(np.abs(hues.astype(int) - peak), 180 - np.abs(hues.astype(int) - peak))
        selected = region[saturated][distance <= 8]
        return tuple(int(v) for v in np.median(selected, axis=0))  # type: ignore[return-value]
    dark = hsv[:, :, 2] < 100
    if dark.any():
        return tuple(int(v) for v in np.median(region[dark], axis=0))  # type: ignore[return-value]
    return (0, 0, 0)


def color_mask(image: np.ndarray, color_bgr: Sequence[int], tolerance: float) -> np.ndarray:
    """Boolean mask of pixels whose CIE-Lab distance to the colour is
    within ``tolerance`` (0-100)."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    target = cv2.cvtColor(np.uint8([[list(color_bgr)]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    distance = np.sqrt(np.sum((lab - target) ** 2, axis=2))
    return distance <= tolerance


def _roi(image: np.ndarray, roi: Optional[Rect]) -> np.ndarray:
    if roi is None:
        return image
    x, y, w, h = roi
    return image[y:y + h, x:x + w]


def clean_mask(mask: np.ndarray, min_area: int = 4) -> np.ndarray:
    """Remove isolated specks smaller than ``min_area`` pixels."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def extract_curve_pixels(mask: np.ndarray, roi: Optional[Rect] = None, margin: int = 2, mode: str = "center") -> np.ndarray:
    """One (x, y) pixel per image column containing curve pixels.

    Args:
        roi: Restrict the search to the plotting area (axes excluded with
            ``margin`` pixels).
        mode: ``"center"`` (median of the column, best for thick lines) or
            ``"top"`` (highest pixel, best for filled curves).
    """
    height, width = mask.shape
    x0, y0, x1, y1 = 0, 0, width, height
    if roi is not None:
        x, y, w, h = roi
        x0, y0 = max(0, x + margin), max(0, y + margin)
        x1, y1 = min(width, x + w - margin + 1), min(height, y + h - margin + 1)
    region = mask[y0:y1, x0:x1]
    result = []
    for column in range(region.shape[1]):
        rows = np.nonzero(region[:, column])[0]
        if rows.size == 0:
            continue
        row = float(rows.min()) if mode == "top" else float(np.median(rows))
        result.append((x0 + column, y0 + row))
    return np.array(result, dtype=float).reshape(-1, 2)


def remove_outliers(values: np.ndarray, window: int = 9, threshold: float = 4.0) -> np.ndarray:
    """Boolean mask of samples to keep: a sample is an outlier when it
    deviates from the rolling median by more than ``threshold`` times the
    robust scale (MAD) of the deviations."""
    values = np.asarray(values, dtype=float)
    count = values.size
    if count < 5 or threshold <= 0:
        return np.ones(count, dtype=bool)
    half = max(1, window // 2)
    padded = np.pad(values, half, mode="edge")
    medians = np.array([np.median(padded[i:i + 2 * half + 1]) for i in range(count)])
    deviation = np.abs(values - medians)
    scale = 1.4826 * np.median(deviation)
    if scale <= 1e-12:
        scale = max(1e-12, 0.01 * (np.max(np.abs(values)) or 1.0))
    return deviation <= threshold * scale


@dataclass
class DigitizerSettings:
    """Parameters of the automatic extraction."""

    color_bgr: tuple[int, int, int] = (0, 0, 255)
    tolerance: float = 40.0
    mode: str = "center"
    use_plot_area: bool = True
    axis_margin_px: int = 3
    min_blob_area: int = 4
    outlier_threshold: float = 4.0
    max_points: int = 0  # 0 = keep every column
    simplify_tolerance_n: float = 0.0
    close_curve: bool = True


@dataclass
class DigitizerResult:
    """Pixels found on the curve and the corresponding thrust points."""

    pixels: np.ndarray
    points: list[ThrustPoint]
    removed_outliers: int = 0


def pixels_to_thrust_points(pixels: np.ndarray, calibration: AxisCalibration, settings: DigitizerSettings) -> list[ThrustPoint]:
    """Convert curve pixels to clean, chronological thrust points."""
    if len(pixels) == 0:
        return []
    physical = calibration.pixel_to_physical(pixels)
    physical = physical[np.argsort(physical[:, 0], kind="stable")]
    physical = physical[physical[:, 0] >= 0]
    physical[:, 1] = np.clip(physical[:, 1], 0.0, None)
    points: list[ThrustPoint] = []
    for time_s, thrust_n in physical:
        if points and time_s <= points[-1].time_s:
            continue  # keep strictly increasing times
        points.append(ThrustPoint(round(float(time_s), 6), round(float(thrust_n), 6)))
    if settings.max_points and len(points) > settings.max_points:
        points = resample(points, settings.max_points)
        points = [ThrustPoint(round(p.time_s, 6), round(p.thrust_n, 6)) for p in points]
    if settings.simplify_tolerance_n > 0:
        points = simplify(points, settings.simplify_tolerance_n)
    if settings.close_curve and points and points[-1].thrust_n > 0:
        step = (points[-1].time_s - points[0].time_s) / max(1, len(points) - 1) or 0.001
        points.append(ThrustPoint(round(points[-1].time_s + step, 6), 0.0))
    return points


def digitize(image: np.ndarray, calibration: AxisCalibration, settings: DigitizerSettings) -> DigitizerResult:
    """Run the full extraction pipeline.

    Raises:
        CalibrationError: If the calibration is not usable.
        ValueError: If no curve pixel matches the colour.
    """
    calibration.matrix()  # validates the calibration first
    roi = calibration.plot_area(image.shape) if settings.use_plot_area else None
    mask = color_mask(image, settings.color_bgr, settings.tolerance)
    mask = clean_mask(mask, settings.min_blob_area)
    pixels = extract_curve_pixels(mask, roi, settings.axis_margin_px, settings.mode)
    if len(pixels) == 0:
        raise ValueError("No pixel of the selected colour was found. Increase the tolerance or pick the curve colour.")
    keep = remove_outliers(pixels[:, 1], threshold=settings.outlier_threshold)
    removed = int((~keep).sum())
    pixels = pixels[keep]
    points = pixels_to_thrust_points(pixels, calibration, settings)
    logger.info("Digitized %d pixels -> %d points (%d outliers removed)", len(pixels), len(points), removed)
    return DigitizerResult(pixels=pixels, points=points, removed_outliers=removed)
