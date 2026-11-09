"""Analysis service: runs the calculator, formats results in the display
unit system and offers curve processing tools (resampling, simplification,
smoothing) used by the editor and the digitizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy.signal import savgol_filter

from models.motor import Motor
from models.motor_calculations import MotorCalculator, MotorCharacteristics
from models.thrust_point import ThrustPoint
from models.units import Quantity, display_unit, from_reference
from services.file_utils import format_number

#: Quantity of each characteristic, used for unit conversion.
_QUANTITIES: dict[str, Optional[Quantity]] = {
    "total_impulse_ns": Quantity.IMPULSE,
    "maximum_thrust_n": Quantity.FORCE,
    "average_thrust_n": Quantity.FORCE,
    "burn_time_s": Quantity.TIME,
    "initial_thrust_n": Quantity.FORCE,
    "final_thrust_n": Quantity.FORCE,
    "time_to_max_thrust_s": Quantity.TIME,
    "initial_mass_g": Quantity.MASS,
    "propellant_mass_g": Quantity.MASS,
    "propellant_mass_fraction": None,
    "specific_impulse_s": None,
}


@dataclass(frozen=True)
class DisplayRow:
    """A characteristic ready to be displayed."""

    key: str
    caption: str
    value: Optional[float]
    unit: str
    text: str
    reason: str


class ThrustAnalysisService:
    """Facade over :class:`MotorCalculator` for the user interface."""

    def __init__(self, burn_time_method: str = "curve", unit_system: str = "metric") -> None:
        self.burn_time_method = burn_time_method
        self.unit_system = unit_system

    def analyse(self, motor: Motor) -> MotorCharacteristics:
        """Compute the characteristics with the configured method."""
        return MotorCalculator(self.burn_time_method).analyse(motor)

    def convert_value(self, key: str, value: Optional[float]) -> tuple[Optional[float], str]:
        """Convert an internal value to the display system: ``(value, unit)``."""
        quantity = _QUANTITIES.get(key)
        if quantity is None:
            return value, "s" if key == "specific_impulse_s" else "-"
        unit = display_unit(self.unit_system, quantity)
        if value is None:
            return None, unit
        return from_reference(value, unit), unit

    def display_rows(self, result: MotorCharacteristics, decimals: int = 3) -> list[DisplayRow]:
        """Return the characteristics converted and formatted."""
        rows = []
        for key, caption, value, _unit in result.as_rows():
            converted, unit = self.convert_value(key, value)
            text = format_number(converted, decimals) if converted is not None else "n/a"
            rows.append(DisplayRow(key, caption, converted, unit, text, result.unavailable.get(key, "")))
        return rows

    def report_text(self, motor: Motor, result: MotorCharacteristics) -> str:
        """Plain-text analysis report (for the clipboard or a file)."""
        meta = motor.metadata
        lines = [
            f"Motor analysis - {meta.designation or meta.name or 'Unnamed motor'}",
            f"Manufacturer: {meta.manufacturer}",
            f"Burn time method: {result.burn_time_method}",
            f"Thrust points: {motor.point_count()}",
            "",
        ]
        for row in self.display_rows(result):
            suffix = f"   ({row.reason})" if row.reason else ""
            lines.append(f"{row.caption:<28} {row.text:>12} {row.unit}{suffix}")
        if result.impulse_class:
            lines.append(f"{'Impulse class':<28} {result.impulse_class:>12} ({result.class_percent:.0f} %)")
        if result.suggested_designation:
            lines.append(f"{'Suggested designation':<28} {result.suggested_designation:>12}")
        if result.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in result.warnings)
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Curve processing tools
# ----------------------------------------------------------------------
def resample(points: Sequence[ThrustPoint], count: int) -> list[ThrustPoint]:
    """Linearly resample a chronological curve to ``count`` equally spaced
    points, keeping the first and last instants."""
    if count < 2 or len(points) < 2:
        return list(points)
    times = np.array([p.time_s for p in points])
    thrusts = np.array([p.thrust_n for p in points])
    new_times = np.linspace(times[0], times[-1], count)
    new_thrusts = np.interp(new_times, times, thrusts)
    return [ThrustPoint(float(t), float(f)) for t, f in zip(new_times, new_thrusts)]


def simplify(points: Sequence[ThrustPoint], tolerance_n: float) -> list[ThrustPoint]:
    """Ramer-Douglas-Peucker simplification on the thrust axis.

    Points are removed only when the curve stays within ``tolerance_n``
    Newtons of the original, which keeps the peak and the burnout.
    """
    if len(points) < 3 or tolerance_n <= 0:
        return list(points)
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    times = np.array([p.time_s for p in points])
    thrusts = np.array([p.thrust_n for p in points])
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        segment_t = times[start + 1:end]
        span = times[end] - times[start]
        ratio = (segment_t - times[start]) / span if span > 0 else np.zeros_like(segment_t)
        expected = thrusts[start] + ratio * (thrusts[end] - thrusts[start])
        errors = np.abs(thrusts[start + 1:end] - expected)
        worst = int(np.argmax(errors))
        if errors[worst] > tolerance_n:
            index = start + 1 + worst
            keep[index] = True
            stack.extend([(start, index), (index, end)])
    return [point for point, kept in zip(points, keep) if kept]


def smooth(points: Sequence[ThrustPoint], window: int = 7, order: int = 2) -> list[ThrustPoint]:
    """Savitzky-Golay smoothing of the thrust values (times unchanged).
    Negative results are clipped to zero."""
    if len(points) <= order + 2:
        return list(points)
    window = min(window if window % 2 else window + 1, len(points) if len(points) % 2 else len(points) - 1)
    if window <= order:
        return list(points)
    thrusts = savgol_filter(np.array([p.thrust_n for p in points]), window, order)
    return [ThrustPoint(p.time_s, float(max(0.0, f))) for p, f in zip(points, thrusts)]
