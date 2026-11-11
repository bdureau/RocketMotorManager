"""Small reusable UI helpers: icons, optional-number fields, colour buttons."""

from __future__ import annotations

from localization import _

import math
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFocusEvent, QIcon
from PyQt6.QtWidgets import QColorDialog, QLineEdit, QPlainTextEdit, QPushButton, QWidget

from application.paths import resource_path


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    """Return the bundled icon ``resources/icons/<name>.svg`` (or .png/.ico)."""
    for extension in (".svg", ".png", ".ico"):
        path = resource_path("resources", "icons", f"{name}{extension}")
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def parse_float(text: str) -> Optional[float]:
    """Parse user input accepting both ``.`` and ``,`` as decimal separator.

    Returns None for an empty string. Raises ValueError for invalid text.
    """
    cleaned = text.strip().replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    value = float(cleaned.replace(",", "."))
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    return value


def format_float(value: Optional[float], decimals: int = 6) -> str:
    """Format a float for an edit field without trailing zeros."""
    if value is None:
        return ""
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


class OptionalNumberEdit(QLineEdit):
    """Line edit holding an optional, non-negative (by default) number.

    Emits :attr:`value_committed` with the new value (or None) when editing
    finishes with a valid entry; invalid entries are shown in red and
    reverted.
    """

    value_committed = pyqtSignal(object)

    def __init__(self, unit: str = "", allow_negative: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value: Optional[float] = None
        self._allow_negative = allow_negative
        self.setPlaceholderText(f"— {unit}" if unit else "—")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.editingFinished.connect(self._commit)
        self.textEdited.connect(self._check)

    def value(self) -> Optional[float]:
        """Current committed value."""
        return self._value

    def set_value(self, value: Optional[float]) -> None:
        """Display a value without emitting a signal."""
        self._value = value
        self.setText(format_float(value))
        self.setStyleSheet("")

    def _parse(self) -> Optional[float]:
        value = parse_float(self.text())
        if value is not None and value < 0 and not self._allow_negative:
            raise ValueError("negative")
        return value

    def _check(self) -> None:
        try:
            self._parse()
            self.setStyleSheet("")
        except ValueError:
            self.setStyleSheet("QLineEdit { background: #F8D7DA; color: #721C24; }")

    def _commit(self) -> None:
        try:
            value = self._parse()
        except ValueError:
            self.set_value(self._value)
            return
        if value != self._value:
            self._value = value
            self.value_committed.emit(value)
        self.setText(format_float(value))


class CommitTextEdit(QPlainTextEdit):
    """Plain text edit emitting :attr:`committed` when it loses focus."""

    committed = pyqtSignal(str)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self.committed.emit(self.toPlainText())


class ColorButton(QPushButton):
    """Button showing a colour and opening a colour picker when clicked."""

    color_changed = pyqtSignal(str)

    def __init__(self, color: str = "#000000", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(70)
        self.clicked.connect(self._choose)
        self._refresh()

    def color(self) -> str:
        """Current colour as ``#RRGGBB``."""
        return self._color

    def set_color(self, color: str) -> None:
        """Set the colour without emitting a signal."""
        self._color = QColor(color).name().upper() if QColor(color).isValid() else "#000000"
        self._refresh()

    def _refresh(self) -> None:
        text_color = "#000000" if QColor(self._color).lightness() > 128 else "#FFFFFF"
        self.setText(self._color)
        self.setStyleSheet(f"QPushButton {{ background: {self._color}; color: {text_color}; border: 1px solid #888; padding: 3px; }}")

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, _("Choose a colour"))
        if chosen.isValid():
            self.set_color(chosen.name())
            self.color_changed.emit(self._color)
