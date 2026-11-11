"""Editable thrust points table synchronised with the document.

The model reads the points from the :class:`MotorDocument` and writes every
edit back through it, so the graph is refreshed immediately and every edit
can be undone. Invalid rows (from the validation report) are highlighted.
"""

from __future__ import annotations

from localization import N_, _, ngettext

import re
from typing import Any, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from application.application_controller import CHANGE_ALL, CHANGE_POINTS, MotorDocument
from models.thrust_point import ThrustPoint
from models.validation import Severity, validate_points
from services.file_utils import format_number
from ui.common import icon, parse_float

def parse_clipboard_rows(text: str) -> list[ThrustPoint]:
    """Parse rows of ``time thrust`` pasted from Excel or a text editor.

    Accepts tab, semicolon or whitespace separators and decimal commas
    (when the field separator is not a comma). Header or invalid lines are
    skipped.
    """
    points = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line or ";" in line:
            cells = [cell for cell in re.split(r"[\t;]", line) if cell.strip()]
        elif line.count(",") == 1 and " " not in line.strip():
            cells = line.split(",")  # "0.1,5" style CSV
        else:
            cells = line.split()
        if len(cells) < 2:
            continue
        try:
            time_s, thrust_n = parse_float(cells[0]), parse_float(cells[1])
        except ValueError:
            continue
        if time_s is not None and thrust_n is not None:
            points.append(ThrustPoint(time_s, thrust_n))
    return points


class ThrustTableModel(QAbstractTableModel):
    """Two-column (Time, Thrust) model over the document points."""

    HEADERS = (N_("Time (s)"), N_("Thrust (N)"))

    def __init__(self, document: MotorDocument) -> None:
        super().__init__()
        self._document = document
        self._issues: dict[int, tuple[Severity, str]] = {}
        document.changed.connect(self._on_document_changed)
        self._refresh_issues()

    # -- Qt model API ------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self._document.motor.point_count()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return _(self.HEADERS[section])
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        point = self._document.motor.points[index.row()]
        value = point.time_s if index.column() == 0 else point.thrust_n
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return format_number(value, 6)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        issue = self._issues.get(index.row())
        if issue and role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(QColor("#F8D7DA") if issue[0] == Severity.ERROR else QColor("#FFF3CD"))
        if issue and role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor("#000000"))
        if role == Qt.ItemDataRole.ToolTipRole:
            return issue[1] if issue else (_("Time since ignition in seconds (>= 0, increasing).") if index.column() == 0
                                           else _("Thrust in Newtons (>= 0)."))
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        try:
            number = parse_float(str(value))
        except ValueError:
            return False
        if number is None:
            return False
        point = self._document.motor.points[index.row()]
        updated = ThrustPoint(number, point.thrust_n) if index.column() == 0 else ThrustPoint(point.time_s, number)
        if updated != point:
            self._document.update_point(index.row(), updated)
        return True

    # -- synchronisation ------------------------------------------------------
    def _on_document_changed(self, kind: str) -> None:
        if kind in (CHANGE_POINTS, CHANGE_ALL):
            self.beginResetModel()
            self._refresh_issues()
            self.endResetModel()

    def _refresh_issues(self) -> None:
        self._issues = {}
        for issue in validate_points(self._document.motor.points).issues:
            if issue.row is not None and (issue.row not in self._issues or issue.severity == Severity.ERROR):
                self._issues[issue.row] = (issue.severity, issue.message)


class ThrustTableWidget(QWidget):
    """Table view with editing tools (add, duplicate, delete, sort, paste)."""

    row_selected = pyqtSignal(int)

    def __init__(self, document: MotorDocument, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._document = document
        self.model = ThrustTableModel(document)
        self._build_ui()
        document.changed.connect(self._update_count)
        self._update_count()

    def _build_ui(self) -> None:
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.setToolTip(_("Thrust points. Double-click a cell to edit it. Red rows contain errors, "
                                     "yellow rows warnings. Ctrl+V pastes data copied from Excel."))
        self.view.selectionModel().currentRowChanged.connect(lambda current, _prev: self.row_selected.emit(current.row()))

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        for icon_name, tip, slot in (
            ("add_point", _("Add a point after the selected row (Ctrl+Ins)"), self.add_point),
            ("duplicate", _("Duplicate the selected point (Ctrl+D)"), self.duplicate_point),
            ("delete_point", _("Delete the selected point(s) (Del)"), self.delete_selected),
            ("sort", _("Sort points chronologically"), self._document.sort_points),
        ):
            button = QToolButton()
            button.setIcon(icon(icon_name))
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        self.count_label = QLabel()
        bar.addWidget(self.count_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(bar)
        layout.addWidget(self.view)

        for sequence, slot in (
            (QKeySequence.StandardKey.Delete, self.delete_selected),
            (QKeySequence.StandardKey.Paste, self.paste),
            (QKeySequence.StandardKey.Copy, self.copy),
            (QKeySequence("Ctrl+D"), self.duplicate_point),
            (QKeySequence("Ctrl+Ins"), self.add_point),
        ):
            shortcut = QShortcut(sequence, self.view)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    def selected_rows(self) -> list[int]:
        """Sorted indices of the selected rows."""
        return sorted({index.row() for index in self.view.selectionModel().selectedIndexes()})

    def select_row(self, row: int) -> None:
        """Select and reveal a row (e.g. a point clicked on the graph)."""
        if 0 <= row < self.model.rowCount():
            self.view.selectRow(row)
            self.view.scrollTo(self.model.index(row, 0))

    def select_all(self) -> None:
        """Select every row."""
        self.view.selectAll()

    # ------------------------------------------------------------------
    # Editing operations
    # ------------------------------------------------------------------
    def add_point(self) -> None:
        """Insert a point after the current row (midpoint with the next)."""
        points = self._document.motor.points
        rows = self.selected_rows()
        if not points:
            self._document.add_point(ThrustPoint(0.0, 0.0), 0)
            self.select_row(0)
            return
        row = rows[-1] if rows else len(points) - 1
        current = points[row]
        if row + 1 < len(points):
            following = points[row + 1]
            new = ThrustPoint(round((current.time_s + following.time_s) / 2, 6),
                              round((current.thrust_n + following.thrust_n) / 2, 6))
        else:
            step = current.time_s - points[row - 1].time_s if row > 0 else 0.1
            new = ThrustPoint(round(current.time_s + (step if step > 0 else 0.1), 6), 0.0)
        self._document.add_point(new, row + 1)
        self.select_row(row + 1)

    def duplicate_point(self) -> None:
        """Duplicate the current point."""
        rows = self.selected_rows()
        if rows:
            self._document.duplicate_point(rows[-1])
            self.select_row(rows[-1] + 1)

    def delete_selected(self) -> None:
        """Delete every selected point."""
        rows = self.selected_rows()
        if rows:
            self._document.remove_points(rows)
            self.select_row(min(rows[0], self.model.rowCount() - 1))

    def copy(self) -> None:
        """Copy the selected rows as tab-separated text (Excel friendly)."""
        points = self._document.motor.points
        rows = self.selected_rows() or range(len(points))
        text = "\n".join(f"{format_number(points[r].time_s)}\t{format_number(points[r].thrust_n)}" for r in rows)
        QGuiApplication.clipboard().setText(text)

    def paste(self) -> None:
        """Paste rows: one value into one cell, or several rows replacing
        the points from the current row (appending beyond the end)."""
        text = QGuiApplication.clipboard().text()
        current = self.view.currentIndex()
        stripped = text.strip()
        if current.isValid() and stripped and "\n" not in stripped and "\t" not in stripped and ";" not in stripped:
            self.model.setData(current, stripped)
            return
        new_points = parse_clipboard_rows(text)
        if not new_points:
            return
        start = current.row() if current.isValid() else len(self._document.motor.points)

        def apply(motor) -> None:
            points = list(motor.points)
            points[start:start + len(new_points)] = new_points
            motor.set_points(points)

        self._document.modify(f"Paste {len(new_points)} point(s)", CHANGE_POINTS, apply)

    def _context_menu(self, position) -> None:
        menu = QMenu(self)
        for text, icon_name, slot in (
            (_("Add point"), "add_point", self.add_point),
            (_("Duplicate point"), "duplicate", self.duplicate_point),
            (_("Delete selected point(s)"), "delete_point", self.delete_selected),
            (None, None, None),
            (_("Copy"), None, self.copy),
            (_("Paste"), None, self.paste),
            (None, None, None),
            (_("Sort chronologically"), "sort", self._document.sort_points),
            (_("Select all"), None, self.select_all),
        ):
            if text is None:
                menu.addSeparator()
                continue
            action = menu.addAction(icon(icon_name) if icon_name else icon("none"), text)
            action.triggered.connect(slot)
        menu.exec(self.view.viewport().mapToGlobal(position))

    def _update_count(self, _kind: str = "") -> None:
        count = self._document.motor.point_count()
        self.count_label.setText(ngettext("{n} point", "{n} points", count).format(n=count))
