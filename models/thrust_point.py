"""Thrust curve sample point."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ThrustPoint:
    """A single sample of a thrust curve.

    Attributes:
        time_s: Time since ignition, in seconds.
        thrust_n: Thrust at that instant, in Newtons.
    """

    time_s: float
    thrust_n: float

    def is_finite(self) -> bool:
        """Return True when both coordinates are finite numbers."""
        return math.isfinite(self.time_s) and math.isfinite(self.thrust_n)

    def as_tuple(self) -> tuple[float, float]:
        """Return the point as a ``(time_s, thrust_n)`` tuple."""
        return (self.time_s, self.thrust_n)
