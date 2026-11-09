"""Interactive Matplotlib thrust curve embedded in Qt.

Features: zoom / pan / home (Matplotlib navigation), cursor coordinates and
interpolated thrust readout, grid, automatic axes, export to PNG/SVG/PDF,
and graphical editing:

* drag a point marker to move it (kept between its neighbours, thrust >= 0)
* double-click an empty area to add a point
* right-click a marker to delete or duplicate it

The widget never modifies the motor itself: it emits signals that the main
window forwards to the document, which then refreshes every view.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backend_bases import MouseButton, MouseEvent  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PyQt6.QtCore import QPoint, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget  # noqa: E402

from models.motor import PlotSettings  # noqa: E402
from models.motor_calculations import MotorCharacteristics  # noqa: E402
from models.thrust_point import ThrustPoint  # noqa: E402
from ui.theme import LIGHT_PLOT, PlotColors  # noqa: E402

logger = logging.getLogger(__name__)

PICK_RADIUS_PX = 8.0
EXPORT_FORMATS = "PNG image (*.png);;SVG vector image (*.svg);;PDF document (*.pdf)"


class _NavigationToolbar(NavigationToolbar2QT):
    """Matplotlib toolbar restricted to the useful tools."""

    toolitems = [item for item in NavigationToolbar2QT.toolitems if item[0] in ("Home", "Back", "Forward", "Pan", "Zoom", None)]


class ThrustPlotWidget(QWidget):
    """Thrust curve view with graphical editing."""

    point_moved = pyqtSignal(int, object)  # index, ThrustPoint
    point_add_requested = pyqtSignal(object)  # ThrustPoint
    point_delete_requested = pyqtSignal(int)
    point_duplicate_requested = pyqtSignal(int)
    point_selected = pyqtSignal(int)
    cursor_info = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._points: list[ThrustPoint] = []
        self._settings = PlotSettings()
        self._colors: PlotColors = LIGHT_PLOT
        self._characteristics: Optional[MotorCharacteristics] = None
        self._drag_index: Optional[int] = None
        self._selected_index: Optional[int] = None
        self._editable = True
        self._build_ui()
        self._connect_events()
        self.redraw()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.figure = Figure(figsize=(6, 4), dpi=100, layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.canvas.setToolTip(
            self.tr("Thrust curve. Drag a point to move it, double-click to add a point, "
                    "right-click a point to delete it. Use the toolbar to zoom and pan.")
        )
        self.axes = self.figure.add_subplot(111)
        self.toolbar = _NavigationToolbar(self.canvas, self)
        self.toolbar.setIconSize(self.toolbar.iconSize() * 0.85)
        self.coordinates = QLabel(self.tr("Move the cursor over the graph"))
        self.coordinates.setToolTip(self.tr("Cursor position (time, thrust) and interpolated thrust of the curve at that time."))
        top = QHBoxLayout()
        top.addWidget(self.toolbar)
        top.addStretch(1)
        top.addWidget(self.coordinates)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.canvas, 1)

    def _connect_events(self) -> None:
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("figure_leave_event", lambda _e: self.coordinates.setText(""))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_data(
        self,
        points: Sequence[ThrustPoint],
        settings: PlotSettings,
        characteristics: Optional[MotorCharacteristics] = None,
        keep_view: bool = True,
    ) -> None:
        """Display a curve. ``keep_view`` preserves the current zoom."""
        view = (self.axes.get_xlim(), self.axes.get_ylim()) if keep_view and self._points else None
        self._points = list(points)
        self._settings = settings
        self._characteristics = characteristics
        if self._selected_index is not None and self._selected_index >= len(self._points):
            self._selected_index = None
        self.redraw(view)

    def set_colors(self, colors: PlotColors) -> None:
        """Apply theme colours."""
        self._colors = colors
        self.redraw()

    def set_editable(self, editable: bool) -> None:
        """Enable or disable graphical editing."""
        self._editable = editable

    def select_point(self, index: Optional[int]) -> None:
        """Highlight a point (e.g. the row selected in the table)."""
        self._selected_index = index
        self.redraw((self.axes.get_xlim(), self.axes.get_ylim()) if self._points else None)

    def reset_zoom(self) -> None:
        """Fit the axes to the data."""
        self.toolbar.update()  # clear the navigation history
        self.redraw(None)

    def set_grid(self, visible: bool) -> None:
        """Show or hide the grid."""
        self._settings.show_grid = visible
        self.redraw((self.axes.get_xlim(), self.axes.get_ylim()))

    def export(self, path: str, dpi: int = 200) -> None:
        """Save the figure; the format follows the file extension."""
        self.figure.savefig(path, dpi=dpi, facecolor=self.figure.get_facecolor())
        logger.info("Graph exported to %s", path)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def redraw(self, view: Optional[tuple[tuple[float, float], tuple[float, float]]] = None) -> None:
        """Redraw the whole figure."""
        ax, colors = self.axes, self._colors
        ax.clear()
        self.figure.set_facecolor(colors.figure)
        ax.set_facecolor(colors.axes)
        for spine in ax.spines.values():
            spine.set_color(colors.text)
        ax.tick_params(colors=colors.text)
        ax.set_xlabel("Time (s)", color=colors.text)
        ax.set_ylabel("Thrust (N)", color=colors.text)
        if self._settings.show_grid:
            ax.grid(True, color=colors.grid, linestyle="--", linewidth=0.6)
        self._draw_curve()
        self._apply_view(view)
        self.canvas.draw_idle()

    def _draw_curve(self) -> None:
        ax = self.axes
        if not self._points:
            ax.text(0.5, 0.5, self.tr("No thrust data\nAdd points, import a file or digitize an image"),
                    ha="center", va="center", transform=ax.transAxes, color=self._colors.text, alpha=0.6)
            return
        times = [p.time_s for p in self._points]
        thrusts = [p.thrust_n for p in self._points]
        line_times, line_thrusts = times, thrusts
        if times[0] > 0:
            line_times, line_thrusts = [0.0] + times, [0.0] + thrusts
        settings = self._settings
        ax.plot(line_times, line_thrusts, color=settings.line_color, linewidth=1.8, zorder=2)
        if settings.fill_under_curve:
            ax.fill_between(line_times, line_thrusts, color=settings.line_color, alpha=0.12, zorder=1)
        if settings.show_markers:
            ax.plot(times, thrusts, "o", color=settings.marker_color, markersize=4.5, zorder=3)
        if self._selected_index is not None and self._selected_index < len(self._points):
            point = self._points[self._selected_index]
            ax.plot([point.time_s], [point.thrust_n], "o", markersize=10, markerfacecolor="none",
                    markeredgecolor="#FF8C00", markeredgewidth=2, zorder=4)
        self._draw_characteristics()

    def _draw_characteristics(self) -> None:
        result = self._characteristics
        if result is None or result.maximum_thrust_n is None:
            return
        ax = self.axes
        ax.annotate(
            f"Max {result.maximum_thrust_n:.2f} N",
            xy=(result.time_to_max_thrust_s, result.maximum_thrust_n),
            xytext=(10, -2), textcoords="offset points", fontsize=8, color=self._colors.text,
        )
        if result.average_thrust_n is not None and result.burn_start_s is not None:
            ax.hlines(result.average_thrust_n, result.burn_start_s, result.burn_end_s, colors="#2E8B57",
                      linestyles=":", linewidth=1.2, zorder=1)
        if result.total_impulse_ns is not None:
            summary = f"I = {result.total_impulse_ns:.2f} N.s"
            if result.average_thrust_n is not None:
                summary += f"   Favg = {result.average_thrust_n:.2f} N   tb = {result.burn_time_s:.3f} s"
            ax.text(0.99, 0.98, summary, transform=ax.transAxes, ha="right", va="top", fontsize=8,
                    color=self._colors.text,
                    bbox={"boxstyle": "round", "facecolor": self._colors.annotation_bg, "alpha": 0.8, "edgecolor": "none"})

    def _apply_view(self, view: Optional[tuple[tuple[float, float], tuple[float, float]]]) -> None:
        ax, settings = self.axes, self._settings
        if view is not None:
            ax.set_xlim(view[0])
            ax.set_ylim(view[1])
            return
        if self._points:
            max_t = max(p.time_s for p in self._points)
            max_f = max(max(p.thrust_n for p in self._points), 0.0)
            ax.set_xlim(0.0, max_t * 1.05 if max_t > 0 else 1.0)
            ax.set_ylim(min(0.0, min(p.thrust_n for p in self._points)), max_f * 1.12 if max_f > 0 else 1.0)
        else:
            ax.set_xlim(0.0, 2.0)
            ax.set_ylim(0.0, 10.0)
        if settings.x_min is not None and settings.x_max is not None and settings.x_max > settings.x_min:
            ax.set_xlim(settings.x_min, settings.x_max)
        if settings.y_min is not None and settings.y_max is not None and settings.y_max > settings.y_min:
            ax.set_ylim(settings.y_min, settings.y_max)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def _navigation_active(self) -> bool:
        return bool(self.toolbar.mode.value if hasattr(self.toolbar.mode, "value") else self.toolbar.mode)

    def _nearest_point(self, event: MouseEvent) -> Optional[int]:
        """Index of the marker within PICK_RADIUS_PX of the cursor."""
        if not self._points or event.x is None:
            return None
        transform = self.axes.transData
        best, best_distance = None, PICK_RADIUS_PX
        for index, point in enumerate(self._points):
            px, py = transform.transform((point.time_s, point.thrust_n))
            distance = ((px - event.x) ** 2 + (py - event.y) ** 2) ** 0.5
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    def _on_press(self, event: MouseEvent) -> None:
        if event.inaxes is not self.axes or self._navigation_active():
            return
        index = self._nearest_point(event)
        if event.button == MouseButton.RIGHT and index is not None and self._editable:
            self._show_point_menu(index, event)
            return
        if event.button != MouseButton.LEFT:
            return
        if event.dblclick and index is None and self._editable and event.xdata is not None:
            self.point_add_requested.emit(ThrustPoint(max(0.0, float(event.xdata)), max(0.0, float(event.ydata))))
            return
        if index is not None:
            self._selected_index = index
            self.point_selected.emit(index)
            if self._editable:
                self._drag_index = index

    def _on_motion(self, event: MouseEvent) -> None:
        if event.inaxes is not self.axes or event.xdata is None:
            return
        self._update_readout(float(event.xdata), float(event.ydata))
        if self._drag_index is None:
            return
        self._points[self._drag_index] = self._constrained(self._drag_index, float(event.xdata), float(event.ydata))
        self.redraw((self.axes.get_xlim(), self.axes.get_ylim()))

    def _on_release(self, event: MouseEvent) -> None:
        if self._drag_index is None:
            return
        index, self._drag_index = self._drag_index, None
        self.point_moved.emit(index, self._points[index])

    def _constrained(self, index: int, time_s: float, thrust_n: float) -> ThrustPoint:
        """Keep a dragged point between its neighbours with thrust >= 0."""
        epsilon = 1e-6
        lower = self._points[index - 1].time_s + epsilon if index > 0 else 0.0
        upper = self._points[index + 1].time_s - epsilon if index + 1 < len(self._points) else float("inf")
        time_s = min(max(time_s, lower), upper) if upper >= lower else self._points[index].time_s
        return ThrustPoint(round(time_s, 6), round(max(0.0, thrust_n), 6))

    def _update_readout(self, time_s: float, thrust_n: float) -> None:
        text = f"t = {time_s:.4f} s   F = {thrust_n:.3f} N"
        curve = self._interpolate(time_s)
        if curve is not None:
            text += f"   |  curve F(t) = {curve:.3f} N"
        self.coordinates.setText(text)
        self.cursor_info.emit(text)

    def _interpolate(self, time_s: float) -> Optional[float]:
        samples = [(0.0, 0.0)] + [p.as_tuple() for p in self._points] if self._points and self._points[0].time_s > 0 else [p.as_tuple() for p in self._points]
        for (t0, f0), (t1, f1) in zip(samples, samples[1:]):
            if t0 <= time_s <= t1 and t1 > t0:
                return f0 + (f1 - f0) * (time_s - t0) / (t1 - t0)
        return None

    def _show_point_menu(self, index: int, event: MouseEvent) -> None:
        point = self._points[index]
        menu = QMenu(self)
        menu.addSection(f"t = {point.time_s:g} s, F = {point.thrust_n:g} N")
        delete = QAction(self.tr("Delete point"), menu)
        delete.triggered.connect(lambda: self.point_delete_requested.emit(index))
        duplicate = QAction(self.tr("Duplicate point"), menu)
        duplicate.triggered.connect(lambda: self.point_duplicate_requested.emit(index))
        menu.addAction(delete)
        menu.addAction(duplicate)
        height = self.canvas.height()
        ratio = self.canvas.devicePixelRatioF()
        menu.exec(self.canvas.mapToGlobal(QPoint(int(event.x / ratio), int(height - event.y / ratio))))
