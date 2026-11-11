"""Tabular data shared by the CSV and Excel importers.

Both importers produce a :class:`TabularData` (raw cells). The user then
maps columns to Time and Thrust in the preview dialog and the
:class:`ColumnMapping` converts the table into thrust points, reporting
every invalid row instead of silently dropping it.
"""

from __future__ import annotations

from localization import _

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from models.errors import ValidationError
from models.thrust_point import ThrustPoint
from models.units import to_reference

Cell = Any  # str, float, int or None


@dataclass
class TabularData:
    """A raw table: optional header and rows of cells."""

    headers: list[str] = field(default_factory=list)
    rows: list[list[Cell]] = field(default_factory=list)

    @property
    def column_count(self) -> int:
        """Largest number of columns among the header and rows."""
        widths = [len(self.headers)] + [len(row) for row in self.rows]
        return max(widths) if widths else 0

    def column_names(self) -> list[str]:
        """Return a display name for every column."""
        names = []
        for index in range(self.column_count):
            header = self.headers[index] if index < len(self.headers) else ""
            names.append(header.strip() or f"Column {index + 1}")
        return names

    def cell(self, row: int, column: int) -> Cell:
        """Return a cell, or None when the row is shorter."""
        values = self.rows[row]
        return values[column] if column < len(values) else None


@dataclass
class ConversionResult:
    """Points converted from a table and the rows rejected with reasons."""

    points: list[ThrustPoint] = field(default_factory=list)
    invalid_rows: list[tuple[int, str]] = field(default_factory=list)
    source_rows: list[int] = field(default_factory=list)


def parse_number(value: Cell, decimal_separator: str = ".") -> Optional[float]:
    """Convert a cell to float, or return None when it is not numeric.

    Accepts numbers, numeric strings with ``.`` or ``,`` as decimal
    separator, surrounding spaces and non-breaking spaces.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if decimal_separator == ",":
        text = text.replace(".", "") if text.count(".") and text.count(",") else text
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def looks_like_header(row: Sequence[Cell], decimal_separator: str = ".") -> bool:
    """A row is a header when at least one non-empty cell is not numeric."""
    non_empty = [cell for cell in row if cell not in (None, "")]
    if not non_empty:
        return False
    return any(parse_number(cell, decimal_separator) is None for cell in non_empty)


@dataclass
class ColumnMapping:
    """Association between table columns and the Time/Thrust parameters.

    Attributes:
        time_column: 0-based index of the time column.
        thrust_column: 0-based index of the thrust column.
        time_unit: Unit of the time column (``s`` or ``ms``).
        thrust_unit: Unit of the thrust column (``N``, ``lbf``, ``kgf``).
        decimal_separator: ``.`` or ``,`` for string cells.
    """

    time_column: int = 0
    thrust_column: int = 1
    time_unit: str = "s"
    thrust_unit: str = "N"
    decimal_separator: str = "."

    def convert(self, table: TabularData, skip_invalid: bool = True) -> ConversionResult:
        """Convert the table to thrust points (s, N).

        Empty rows are ignored. Rows with a missing, non-numeric, negative
        time or non-numeric thrust are reported in ``invalid_rows``.

        Raises:
            ValidationError: If invalid rows exist and ``skip_invalid`` is
                False, or if no valid point remains.
        """
        if self.time_column == self.thrust_column:
            raise ValidationError(_('Time and Thrust must be mapped to two different columns.'))
        result = ConversionResult()
        for index in range(len(table.rows)):
            raw_time = table.cell(index, self.time_column)
            raw_thrust = table.cell(index, self.thrust_column)
            if raw_time in (None, "") and raw_thrust in (None, ""):
                continue
            reason = self._convert_row(raw_time, raw_thrust, result)
            if reason:
                result.invalid_rows.append((index, reason))
            else:
                result.source_rows.append(index)
        if result.invalid_rows and not skip_invalid:
            first_row, first_reason = result.invalid_rows[0]
            raise ValidationError(
                _('{count} invalid row(s). First: row {first_row}: {first_reason}').format(count=len(result.invalid_rows), first_row=first_row + 1, first_reason=first_reason)
            )
        if not result.points:
            raise ValidationError(_('No valid numeric data found in the selected columns.'))
        return result

    def _convert_row(self, raw_time: Cell, raw_thrust: Cell, result: ConversionResult) -> str:
        """Convert one row; return an error reason or an empty string."""
        time_value = parse_number(raw_time, self.decimal_separator)
        thrust_value = parse_number(raw_thrust, self.decimal_separator)
        if time_value is None:
            return f"time value '{raw_time}' is missing or not numeric"
        if thrust_value is None:
            return f"thrust value '{raw_thrust}' is missing or not numeric"
        time_s = to_reference(time_value, self.time_unit)
        if time_s < 0:
            return "negative time"
        result.points.append(ThrustPoint(time_s, to_reference(thrust_value, self.thrust_unit)))
        return ""


def guess_columns(table: TabularData) -> tuple[int, int]:
    """Guess the Time and Thrust columns from the header names."""
    names = [name.lower() for name in table.column_names()]
    time_col = next((i for i, n in enumerate(names) if "time" in n or "temps" in n or n in ("t", "s")), 0)
    thrust_col = next(
        (i for i, n in enumerate(names) if i != time_col and any(k in n for k in ("thrust", "force", "pouss", "newton"))),
        1 if time_col != 1 else 0,
    )
    if table.column_count < 2:
        return 0, 0
    return time_col, thrust_col
