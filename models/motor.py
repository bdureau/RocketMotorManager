"""The :class:`Motor` aggregate: metadata, thrust curve and display data."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from models.label_template import LabelTemplate
from models.motor_metadata import MotorMetadata
from models.thrust_point import ThrustPoint


@dataclass
class PlotSettings:
    """Graph display parameters saved with a project."""

    show_grid: bool = True
    show_markers: bool = True
    line_color: str = "#1F77B4"
    marker_color: str = "#D62728"
    fill_under_curve: bool = True
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None


@dataclass
class Motor:
    """A rocket motor: properties, thrust curve and related settings.

    The thrust curve is a plain list of :class:`ThrustPoint`. Mutating
    helpers never silently reorder data: sorting is an explicit operation,
    so the user always sees the data as entered and validation can report
    chronological problems.
    """

    metadata: MotorMetadata = field(default_factory=MotorMetadata)
    points: list[ThrustPoint] = field(default_factory=list)
    plot_settings: PlotSettings = field(default_factory=PlotSettings)
    label: Optional[LabelTemplate] = None

    # ------------------------------------------------------------------
    # Thrust curve accessors
    # ------------------------------------------------------------------
    def times(self) -> list[float]:
        """Return the list of sample times (s)."""
        return [point.time_s for point in self.points]

    def thrusts(self) -> list[float]:
        """Return the list of thrust values (N)."""
        return [point.thrust_n for point in self.points]

    def point_count(self) -> int:
        """Return the number of thrust points."""
        return len(self.points)

    # ------------------------------------------------------------------
    # Thrust curve mutators
    # ------------------------------------------------------------------
    def set_points(self, points: Iterable[ThrustPoint]) -> None:
        """Replace every point of the curve."""
        self.points = list(points)

    def add_point(self, point: ThrustPoint, index: Optional[int] = None) -> int:
        """Insert a point and return its index.

        When ``index`` is None the point is inserted at its chronological
        position (after any point with the same time).
        """
        if index is None:
            index = len(self.points)
            for position, existing in enumerate(self.points):
                if existing.time_s > point.time_s:
                    index = position
                    break
        index = max(0, min(index, len(self.points)))
        self.points.insert(index, point)
        return index

    def update_point(self, index: int, point: ThrustPoint) -> None:
        """Replace the point at ``index``."""
        self.points[index] = point

    def remove_points(self, indices: Iterable[int]) -> None:
        """Remove the points at the given indices."""
        for index in sorted(set(indices), reverse=True):
            if 0 <= index < len(self.points):
                del self.points[index]

    def duplicate_point(self, index: int) -> int:
        """Duplicate a point just after itself and return the new index."""
        self.points.insert(index + 1, self.points[index])
        return index + 1

    def sort_points(self) -> None:
        """Sort the points chronologically (stable)."""
        self.points.sort(key=lambda point: point.time_s)

    def is_chronological(self) -> bool:
        """Return True when times are strictly increasing."""
        return all(b.time_s > a.time_s for a, b in zip(self.points, self.points[1:]))

    def thrust_at(self, time_s: float) -> Optional[float]:
        """Linearly interpolate the thrust at ``time_s``.

        The curve is considered to start at (0, 0) when the first sample is
        later than zero, as in the ENG format. Returns None outside the
        curve or when the data is not chronological.
        """
        if not self.points or not self.is_chronological() or not math.isfinite(time_s):
            return None
        samples = [point.as_tuple() for point in self.points]
        if samples[0][0] > 0.0:
            samples.insert(0, (0.0, 0.0))
        if time_s < samples[0][0] or time_s > samples[-1][0]:
            return None
        for (t0, f0), (t1, f1) in zip(samples, samples[1:]):
            if t0 <= time_s <= t1:
                if t1 == t0:
                    return f1
                return f0 + (f1 - f0) * (time_s - t0) / (t1 - t0)
        return samples[-1][1]

    # ------------------------------------------------------------------
    # Copy helpers
    # ------------------------------------------------------------------
    def clone(self) -> "Motor":
        """Return a deep, independent copy of the motor."""
        return copy.deepcopy(self)
