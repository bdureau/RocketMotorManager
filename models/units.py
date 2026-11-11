"""Unit definitions and conversions.

Internal reference units: second, Newton, Newton-second, gram, millimetre.
Every conversion goes through these reference units with explicit factors
so that each value displayed or exported can be traced back to its source.
"""

from __future__ import annotations

from localization import _

from dataclasses import dataclass
from enum import Enum

#: Standard gravity in m/s^2 (used for specific impulse and kgf).
STANDARD_GRAVITY = 9.80665


class Quantity(str, Enum):
    """Physical quantities handled by the application."""

    TIME = "time"
    FORCE = "force"
    IMPULSE = "impulse"
    MASS = "mass"
    LENGTH = "length"


@dataclass(frozen=True)
class Unit:
    """A unit expressed relative to the internal reference unit.

    Attributes:
        symbol: Display symbol (``"lbf"``).
        quantity: The physical quantity measured.
        factor: Number of reference units in one of this unit.
    """

    symbol: str
    quantity: Quantity
    factor: float


_UNITS: dict[str, Unit] = {
    unit.symbol: unit
    for unit in (
        Unit("s", Quantity.TIME, 1.0),
        Unit("ms", Quantity.TIME, 1e-3),
        Unit("N", Quantity.FORCE, 1.0),
        Unit("lbf", Quantity.FORCE, 4.4482216152605),
        Unit("kgf", Quantity.FORCE, STANDARD_GRAVITY),
        Unit("N.s", Quantity.IMPULSE, 1.0),
        Unit("lbf.s", Quantity.IMPULSE, 4.4482216152605),
        Unit("g", Quantity.MASS, 1.0),
        Unit("kg", Quantity.MASS, 1000.0),
        Unit("oz", Quantity.MASS, 28.349523125),
        Unit("lb", Quantity.MASS, 453.59237),
        Unit("mm", Quantity.LENGTH, 1.0),
        Unit("cm", Quantity.LENGTH, 10.0),
        Unit("m", Quantity.LENGTH, 1000.0),
        Unit("in", Quantity.LENGTH, 25.4),
    )
}

#: Unit symbols per display system.
UNIT_SYSTEMS: dict[str, dict[Quantity, str]] = {
    "metric": {
        Quantity.TIME: "s",
        Quantity.FORCE: "N",
        Quantity.IMPULSE: "N.s",
        Quantity.MASS: "g",
        Quantity.LENGTH: "mm",
    },
    "imperial": {
        Quantity.TIME: "s",
        Quantity.FORCE: "lbf",
        Quantity.IMPULSE: "lbf.s",
        Quantity.MASS: "oz",
        Quantity.LENGTH: "in",
    },
}


def get_unit(symbol: str) -> Unit:
    """Return the :class:`Unit` registered under ``symbol``.

    Raises:
        KeyError: If the symbol is unknown.
    """
    try:
        return _UNITS[symbol]
    except KeyError as exc:
        raise KeyError(_("Unknown unit '{symbol}'").format(symbol=symbol)) from exc


def units_for(quantity: Quantity) -> list[str]:
    """Return every unit symbol available for a quantity."""
    return [unit.symbol for unit in _UNITS.values() if unit.quantity == quantity]


def convert(value: float, from_symbol: str, to_symbol: str) -> float:
    """Convert ``value`` between two units of the same quantity.

    Raises:
        ValueError: If the units measure different quantities.
    """
    source = get_unit(from_symbol)
    target = get_unit(to_symbol)
    if source.quantity != target.quantity:
        raise ValueError(
            _('Cannot convert {source_quantity} ({from_symbol}) to {target_quantity} ({to_symbol})').format(source_quantity=source.quantity.value, from_symbol=from_symbol, target_quantity=target.quantity.value, to_symbol=to_symbol)
        )
    return value * source.factor / target.factor


def to_reference(value: float, symbol: str) -> float:
    """Convert a value expressed in ``symbol`` to the reference unit."""
    return value * get_unit(symbol).factor


def from_reference(value: float, symbol: str) -> float:
    """Convert a value in the reference unit to ``symbol``."""
    return value / get_unit(symbol).factor


def display_unit(system: str, quantity: Quantity) -> str:
    """Return the unit symbol used by a display system for a quantity."""
    return UNIT_SYSTEMS.get(system, UNIT_SYSTEMS["metric"])[quantity]
