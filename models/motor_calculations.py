"""Computation of motor characteristics from the thrust curve and masses.

All the physics of the application lives here, so that every result can be
verified independently of the user interface. Internal units: s, N, N.s, g.

Conventions (identical to the RASP/ENG format used by OpenRocket/RockSim):

* The curve implicitly starts at (0 s, 0 N) when its first sample is later
  than zero.
* The total impulse is the trapezoidal integral of thrust over time.
* The average thrust is the total impulse divided by the burn time.
* Two burn-time definitions are available:

  - ``"curve"``: duration of the powered part of the curve, from the last
    zero-thrust sample before ignition to the first zero-thrust sample after
    burnout (or the curve ends).
  - ``"threshold"``: NAR/NFPA style, from the instant thrust first reaches
    5 % of the maximum to the instant it last falls back to 5 %, with linear
    interpolation of both crossing instants.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from models.motor import Motor
from models.thrust_point import ThrustPoint
from models.units import STANDARD_GRAVITY

BURN_TIME_METHODS: dict[str, str] = {
    "curve": "Full powered curve",
    "threshold": "5 % of maximum thrust (NAR)",
}

#: Fraction of the maximum thrust used by the "threshold" burn time method.
THRESHOLD_FRACTION = 0.05


def _trapezoid(y: np.ndarray, x: np.ndarray) -> float:
    """Trapezoidal integral, compatible with NumPy 1.x and 2.x."""
    integrate = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(integrate(y, x))


@dataclass
class MotorCharacteristics:
    """Results of the analysis. ``None`` means "cannot be computed"; the
    reason is then available in :attr:`unavailable`."""

    total_impulse_ns: Optional[float] = None
    maximum_thrust_n: Optional[float] = None
    average_thrust_n: Optional[float] = None
    burn_time_s: Optional[float] = None
    burn_start_s: Optional[float] = None
    burn_end_s: Optional[float] = None
    initial_thrust_n: Optional[float] = None
    final_thrust_n: Optional[float] = None
    time_to_max_thrust_s: Optional[float] = None
    initial_mass_g: Optional[float] = None
    propellant_mass_g: Optional[float] = None
    propellant_mass_fraction: Optional[float] = None
    specific_impulse_s: Optional[float] = None
    impulse_class: Optional[str] = None
    class_percent: Optional[float] = None
    suggested_designation: Optional[str] = None
    burn_time_method: str = "curve"
    unavailable: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_rows(self) -> list[tuple[str, str, Optional[float], str]]:
        """Return ``(key, caption, value, unit)`` rows in display order."""
        return [
            ("total_impulse_ns", "Total impulse", self.total_impulse_ns, "N.s"),
            ("maximum_thrust_n", "Maximum thrust", self.maximum_thrust_n, "N"),
            ("average_thrust_n", "Average thrust", self.average_thrust_n, "N"),
            ("burn_time_s", "Burn time", self.burn_time_s, "s"),
            ("initial_thrust_n", "Initial thrust", self.initial_thrust_n, "N"),
            ("final_thrust_n", "Final thrust", self.final_thrust_n, "N"),
            ("time_to_max_thrust_s", "Time to maximum thrust", self.time_to_max_thrust_s, "s"),
            ("initial_mass_g", "Initial motor mass", self.initial_mass_g, "g"),
            ("propellant_mass_g", "Propellant mass", self.propellant_mass_g, "g"),
            ("propellant_mass_fraction", "Propellant mass fraction", self.propellant_mass_fraction, "-"),
            ("specific_impulse_s", "Specific impulse", self.specific_impulse_s, "s"),
        ]


# ----------------------------------------------------------------------
# Elementary functions (pure, individually tested)
# ----------------------------------------------------------------------
def curve_arrays(points: Sequence[ThrustPoint]) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(times, thrusts)`` arrays including the implicit origin.

    Raises:
        ValueError: If points are not finite or not strictly chronological.
    """
    times = np.array([p.time_s for p in points], dtype=float)
    thrusts = np.array([p.thrust_n for p in points], dtype=float)
    if not (np.all(np.isfinite(times)) and np.all(np.isfinite(thrusts))):
        raise ValueError("The thrust curve contains non-numeric values.")
    if times.size > 1 and np.any(np.diff(times) <= 0):
        raise ValueError("Thrust points are not in strictly increasing time order.")
    if times.size and times[0] > 0.0:
        times = np.insert(times, 0, 0.0)
        thrusts = np.insert(thrusts, 0, 0.0)
    return times, thrusts


def total_impulse(points: Sequence[ThrustPoint]) -> float:
    """Total impulse in N.s by trapezoidal integration."""
    times, thrusts = curve_arrays(points)
    if times.size < 2:
        return 0.0
    return _trapezoid(thrusts, times)


def burn_window(points: Sequence[ThrustPoint], method: str = "curve") -> tuple[float, float]:
    """Return ``(start, end)`` instants of the burn in seconds.

    Raises:
        ValueError: If the curve has no positive thrust.
    """
    times, thrusts = curve_arrays(points)
    positive = np.nonzero(thrusts > 0.0)[0]
    if positive.size == 0:
        raise ValueError("The thrust curve has no positive thrust.")
    if method == "threshold":
        return _threshold_window(times, thrusts)
    first, last = int(positive[0]), int(positive[-1])
    start = float(times[first - 1]) if first > 0 else float(times[first])
    end = float(times[last + 1]) if last + 1 < times.size else float(times[last])
    return start, end


def _threshold_window(times: np.ndarray, thrusts: np.ndarray) -> tuple[float, float]:
    """Burn window between the 5 % of maximum thrust crossings."""
    level = THRESHOLD_FRACTION * float(np.max(thrusts))
    above = np.nonzero(thrusts >= level)[0]
    first, last = int(above[0]), int(above[-1])
    start = float(times[first])
    if first > 0:
        start = _interpolate_time(times[first - 1], thrusts[first - 1], times[first], thrusts[first], level)
    end = float(times[last])
    if last + 1 < times.size:
        end = _interpolate_time(times[last], thrusts[last], times[last + 1], thrusts[last + 1], level)
    return start, end


def _interpolate_time(t0: float, f0: float, t1: float, f1: float, level: float) -> float:
    """Instant at which the segment (t0,f0)-(t1,f1) crosses ``level``."""
    if f1 == f0:
        return float(t0)
    return float(t0 + (level - f0) * (t1 - t0) / (f1 - f0))


def impulse_class(total_impulse_ns: float) -> tuple[str, float]:
    """Return the NAR impulse class letter and the percentage within it.

    Class A covers 1.26-2.50 N.s and every following letter doubles the
    upper bound. Smaller motors are 1/2A, 1/4A and 1/8A.
    """
    if total_impulse_ns <= 0:
        return "-", 0.0
    if total_impulse_ns <= 2.5:
        for name, upper in (("1/8A", 0.3125), ("1/4A", 0.625), ("1/2A", 1.25), ("A", 2.5)):
            if total_impulse_ns <= upper:
                lower = upper / 2.0 if name != "1/8A" else 0.0
                return name, 100.0 * (total_impulse_ns - lower) / (upper - lower)
    index = int(math.ceil(math.log2(total_impulse_ns / 2.5)))
    upper = 2.5 * 2 ** index
    lower = upper / 2.0
    letter = ""
    number = index  # 0 -> A, 1 -> B, ... 25 -> Z, 26 -> AA
    while True:
        letter = chr(ord("A") + number % 26) + letter
        number = number // 26 - 1
        if number < 0:
            break
    return letter, 100.0 * (total_impulse_ns - lower) / (upper - lower)


# ----------------------------------------------------------------------
# Full analysis
# ----------------------------------------------------------------------
class MotorCalculator:
    """Compute every characteristic of a motor and report missing data."""

    def __init__(self, burn_time_method: str = "curve") -> None:
        if burn_time_method not in BURN_TIME_METHODS:
            raise ValueError(f"Unknown burn time method '{burn_time_method}'")
        self.burn_time_method = burn_time_method

    def analyse(self, motor: Motor) -> MotorCharacteristics:
        """Return the :class:`MotorCharacteristics` of ``motor``."""
        result = MotorCharacteristics(burn_time_method=self.burn_time_method)
        self._analyse_masses(motor, result)
        self._analyse_curve(motor, result)
        self._analyse_derived(result)
        return result

    # -- masses -----------------------------------------------------------
    @staticmethod
    def _analyse_masses(motor: Motor, result: MotorCharacteristics) -> None:
        meta = motor.metadata
        result.propellant_mass_g = meta.propellant_mass_g
        result.initial_mass_g = meta.total_mass_g
        if meta.propellant_mass_g is None:
            result.unavailable["propellant_mass_g"] = "Propellant mass not specified."
        elif meta.propellant_mass_g <= 0:
            result.warnings.append("Propellant mass must be greater than zero.")
        if result.initial_mass_g is None:
            result.unavailable["initial_mass_g"] = "Total motor mass not specified."
        if (
            result.initial_mass_g is not None
            and meta.propellant_mass_g is not None
            and meta.propellant_mass_g > result.initial_mass_g
        ):
            result.warnings.append("Propellant mass is greater than the total motor mass.")

    # -- curve ------------------------------------------------------------
    def _analyse_curve(self, motor: Motor, result: MotorCharacteristics) -> None:
        points = motor.points
        curve_keys = (
            "total_impulse_ns", "maximum_thrust_n", "average_thrust_n", "burn_time_s",
            "initial_thrust_n", "final_thrust_n", "time_to_max_thrust_s",
        )
        if len(points) < 2:
            for key in curve_keys:
                result.unavailable[key] = "At least two thrust points are required."
            return
        try:
            times, thrusts = curve_arrays(points)
        except ValueError as exc:
            for key in curve_keys:
                result.unavailable[key] = str(exc)
            return
        if np.any(thrusts < 0):
            result.warnings.append("The curve contains negative thrust values.")
        result.total_impulse_ns = _trapezoid(thrusts, times)
        peak = int(np.argmax(thrusts))
        result.maximum_thrust_n = float(thrusts[peak])
        result.time_to_max_thrust_s = float(times[peak])
        result.initial_thrust_n = points[0].thrust_n
        result.final_thrust_n = points[-1].thrust_n
        if points[-1].thrust_n != 0.0:
            result.warnings.append("The last thrust point is not zero: the curve may be truncated.")
        self._analyse_burn(points, result)

    def _analyse_burn(self, points: Sequence[ThrustPoint], result: MotorCharacteristics) -> None:
        try:
            start, end = burn_window(points, self.burn_time_method)
        except ValueError as exc:
            result.unavailable["burn_time_s"] = str(exc)
            result.unavailable["average_thrust_n"] = str(exc)
            return
        result.burn_start_s, result.burn_end_s = start, end
        result.burn_time_s = end - start
        if result.burn_time_s <= 0:
            result.unavailable["average_thrust_n"] = "Burn time is zero."
            return
        result.average_thrust_n = (result.total_impulse_ns or 0.0) / result.burn_time_s

    # -- derived values -----------------------------------------------------
    @staticmethod
    def _analyse_derived(result: MotorCharacteristics) -> None:
        prop, total = result.propellant_mass_g, result.initial_mass_g
        if prop is not None and total and total > 0 and prop > 0:
            result.propellant_mass_fraction = prop / total
        else:
            result.unavailable["propellant_mass_fraction"] = (
                "Requires propellant mass and total motor mass."
            )
        if result.total_impulse_ns is not None and prop and prop > 0:
            result.specific_impulse_s = result.total_impulse_ns / (prop / 1000.0 * STANDARD_GRAVITY)
        else:
            result.unavailable["specific_impulse_s"] = (
                "Requires the total impulse and a positive propellant mass."
            )
        if result.total_impulse_ns is not None and result.total_impulse_ns > 0:
            letter, percent = impulse_class(result.total_impulse_ns)
            result.impulse_class, result.class_percent = letter, percent
            if result.average_thrust_n is not None:
                result.suggested_designation = f"{letter}{round(result.average_thrust_n)}"
