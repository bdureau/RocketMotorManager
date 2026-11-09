"""Zones 2 and 3 - thrust curve graph and data table, kept synchronised.

Both views read from the :class:`MotorDocument`. Edits made in either view
go through the document, whose ``changed`` signal refreshes both views.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from application.application_controller import CHANGE_LABEL, MotorDocument
from models.thrust_point import ThrustPoint
from ui.theme import PlotColors
from widgets.thrust_plot import ThrustPlotWidget
from widgets.thrust_table import ThrustTableWidget


class ThrustEditorWidget(QWidget):
    """Composite editor: graph (left) and table (right)."""

    def __init__(self, document: MotorDocument, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._document = document
        self.plot = ThrustPlotWidget()
        self.table = ThrustTableWidget(document)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.plot)
        self.splitter.addWidget(self.table)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self._connect()
        self.refresh(keep_view=False)

    def _connect(self) -> None:
        document = self._document
        document.changed.connect(self._on_document_changed)
        self.plot.point_moved.connect(document.update_point)
        self.plot.point_add_requested.connect(lambda point: document.add_point(point))
        self.plot.point_delete_requested.connect(lambda index: document.remove_points([index]))
        self.plot.point_duplicate_requested.connect(document.duplicate_point)
        self.plot.point_selected.connect(self.table.select_row)
        self.table.row_selected.connect(lambda row: self.plot.select_point(row if row >= 0 else None))

    def _on_document_changed(self, kind: str) -> None:
        if kind != CHANGE_LABEL:
            self.refresh(keep_view=kind != "all")

    def refresh(self, keep_view: bool = True) -> None:
        """Redraw the graph from the document."""
        motor = self._document.motor
        self.plot.set_data(motor.points, motor.plot_settings, self._document.characteristics(), keep_view)

    def set_colors(self, colors: PlotColors) -> None:
        """Apply theme colours to the graph."""
        self.plot.set_colors(colors)

    def show_plot(self, visible: bool) -> None:
        """Show or hide the graph."""
        self.plot.setVisible(visible)

    def show_table(self, visible: bool) -> None:
        """Show or hide the table."""
        self.table.setVisible(visible)

    def add_point(self) -> None:
        """Add a point from the table logic (menu/toolbar action)."""
        self.table.add_point()

    def delete_points(self) -> None:
        """Delete the selected points."""
        self.table.delete_selected()

    def add_point_at(self, point: ThrustPoint) -> None:
        """Add a specific point."""
        self._document.add_point(point)
