"""Zoomable image view used by the curve digitizer.

Displays the (corrected) image with overlays: calibration references,
extracted curve points, colour mask, crop rectangle and perspective
corners. The interaction depends on the current :class:`ViewMode`.

* Mouse wheel: zoom around the cursor; middle button or Navigate mode: pan.
* Edit points mode: drag a point, click to add, right-click to delete,
  Shift+drag a rectangle to delete every point inside.
"""

from __future__ import annotations

from localization import _

from enum import Enum, auto
from typing import Optional

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QWidget,
)

POINT_PICK_RADIUS = 6.0


class ViewMode(Enum):
    """Interaction modes of the view."""

    NAVIGATE = auto()
    CALIB_ORIGIN = auto()
    CALIB_TIME = auto()
    CALIB_THRUST = auto()
    CALIB_EXTRA = auto()
    PICK_COLOR = auto()
    CROP = auto()
    PERSPECTIVE = auto()
    EDIT_POINTS = auto()


def numpy_to_qimage(image: np.ndarray) -> QImage:
    """Convert a BGR uint8 array to a QImage (deep copy)."""
    rgb = np.ascontiguousarray(image[:, :, ::-1])
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


class ImageCalibrationWidget(QGraphicsView):
    """Image canvas with calibration, extraction and editing overlays."""

    clicked = pyqtSignal(object, float, float)  # ViewMode, x, y (image pixels)
    crop_selected = pyqtSignal(tuple)  # (x, y, w, h)
    perspective_selected = pyqtSignal(list)  # four (x, y)
    points_edited = pyqtSignal(object)  # np.ndarray (N, 2)
    cursor_moved = pyqtSignal(float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(QColor("#3C3C3C")))
        self.mode = ViewMode.NAVIGATE
        self._pixmap_item = QGraphicsPixmapItem()
        self._mask_item = QGraphicsPixmapItem()
        self._mask_item.setOpacity(0.55)
        self._scene.addItem(self._pixmap_item)
        self._scene.addItem(self._mask_item)
        self._overlay_items: list = []
        self._point_items: list = []
        self._points = np.empty((0, 2))
        self._calibration: list[tuple[float, float, str]] = []
        self._perspective: list[tuple[float, float]] = []
        self._rubber: Optional[QGraphicsRectItem] = None
        self._rubber_start: Optional[QPointF] = None
        self._drag_index: Optional[int] = None
        self._panning: Optional[QPointF] = None
        self.setToolTip(_("Mouse wheel: zoom. Middle button: pan. The active tool is shown in the status bar."))

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------
    def set_image(self, image: Optional[np.ndarray], fit: bool = False) -> None:
        """Display a new image (BGR array)."""
        if image is None:
            self._pixmap_item.setPixmap(QPixmap())
            return
        self._pixmap_item.setPixmap(QPixmap.fromImage(numpy_to_qimage(image)))
        self._scene.setSceneRect(QRectF(self._pixmap_item.pixmap().rect()))
        if fit:
            self.fit()

    def set_mask(self, mask: Optional[np.ndarray]) -> None:
        """Overlay a boolean mask in magenta (None hides it)."""
        if mask is None:
            self._mask_item.setPixmap(QPixmap())
            return
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
        rgba[mask] = (255, 0, 255, 255)
        height, width = mask.shape
        image = QImage(rgba.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self._mask_item.setPixmap(QPixmap.fromImage(image))

    def set_calibration_markers(self, markers: list[tuple[float, float, str]]) -> None:
        """Show calibration references ``(x, y, caption)``."""
        self._calibration = list(markers)
        self._redraw_overlays()

    def set_points(self, points: np.ndarray) -> None:
        """Show the extracted curve pixels."""
        self._points = np.asarray(points, dtype=float).reshape(-1, 2)
        self._redraw_points()

    def points(self) -> np.ndarray:
        """Current (possibly edited) curve pixels."""
        return self._points.copy()

    def set_mode(self, mode: ViewMode) -> None:
        """Change the interaction mode."""
        self.mode = mode
        self._perspective = [] if mode == ViewMode.PERSPECTIVE else self._perspective
        cursor = Qt.CursorShape.OpenHandCursor if mode == ViewMode.NAVIGATE else Qt.CursorShape.CrossCursor
        self.viewport().setCursor(cursor)
        self._redraw_overlays()

    def fit(self) -> None:
        """Fit the whole image in the view."""
        if not self._pixmap_item.pixmap().isNull():
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------
    def _marker_size(self) -> float:
        scale = self.transform().m11() or 1.0
        return 7.0 / scale

    def _clear(self, items: list) -> None:
        for item in items:
            self._scene.removeItem(item)
        items.clear()

    def _redraw_overlays(self) -> None:
        self._clear(self._overlay_items)
        size = self._marker_size()
        pen = QPen(QColor("#00C853"), 2)
        pen.setCosmetic(True)
        font = QFont()
        font.setPointSizeF(9)
        for x, y, caption in self._calibration:
            path = QPainterPath()
            path.moveTo(x - 2 * size, y)
            path.lineTo(x + 2 * size, y)
            path.moveTo(x, y - 2 * size)
            path.lineTo(x, y + 2 * size)
            path.addEllipse(QPointF(x, y), size, size)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            self._scene.addItem(item)
            text = QGraphicsSimpleTextItem(caption)
            text.setBrush(QBrush(QColor("#00C853")))
            text.setFont(font)
            text.setFlag(text.GraphicsItemFlag.ItemIgnoresTransformations)
            text.setPos(x + size, y + size)
            self._scene.addItem(text)
            self._overlay_items.extend([item, text])
        quad_pen = QPen(QColor("#FFAB00"), 2, Qt.PenStyle.DashLine)
        quad_pen.setCosmetic(True)
        for index, (x, y) in enumerate(self._perspective):
            dot = QGraphicsEllipseItem(x - size, y - size, 2 * size, 2 * size)
            dot.setPen(quad_pen)
            self._scene.addItem(dot)
            self._overlay_items.append(dot)
            if index:
                px, py = self._perspective[index - 1]
                line = self._scene.addLine(px, py, x, y, quad_pen)
                self._overlay_items.append(line)

    def _redraw_points(self) -> None:
        self._clear(self._point_items)
        if not len(self._points):
            return
        size = self._marker_size() * 0.45
        path = QPainterPath()
        path.moveTo(*self._points[0])
        for x, y in self._points[1:]:
            path.lineTo(x, y)
        line_pen = QPen(QColor("#00B0FF"), 1.5)
        line_pen.setCosmetic(True)
        curve = QGraphicsPathItem(path)
        curve.setPen(line_pen)
        self._scene.addItem(curve)
        self._point_items.append(curve)
        dots = QPainterPath()
        step = max(1, len(self._points) // 400)  # keep drawing fast for dense curves
        for x, y in self._points[::step]:
            dots.addEllipse(QPointF(x, y), size, size)
        dot_item = QGraphicsPathItem(dots)
        dot_pen = QPen(QColor("#0091EA"), 1)
        dot_pen.setCosmetic(True)
        dot_item.setPen(dot_pen)
        dot_item.setBrush(QBrush(QColor("#80D8FF")))
        self._scene.addItem(dot_item)
        self._point_items.append(dot_item)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        self._redraw_overlays()
        self._redraw_points()

    def _image_pos(self, event: QMouseEvent) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def _nearest_point(self, pos: QPointF) -> Optional[int]:
        if not len(self._points):
            return None
        distances = np.hypot(self._points[:, 0] - pos.x(), self._points[:, 1] - pos.y())
        index = int(np.argmin(distances))
        radius = POINT_PICK_RADIUS / (self.transform().m11() or 1.0)
        return index if distances[index] <= radius else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = self._image_pos(event)
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self.mode == ViewMode.NAVIGATE
        ):
            self._panning = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._pixmap_item.pixmap().isNull():
            return
        if self.mode == ViewMode.EDIT_POINTS:
            self._edit_press(event, pos)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == ViewMode.CROP:
            self._start_rubber(pos, QColor("#FFAB00"))
        elif self.mode == ViewMode.PERSPECTIVE:
            self._perspective.append((pos.x(), pos.y()))
            self._redraw_overlays()
            if len(self._perspective) == 4:
                corners, self._perspective = list(self._perspective), []
                self._redraw_overlays()
                self.perspective_selected.emit(corners)
        else:
            self.clicked.emit(self.mode, pos.x(), pos.y())

    def _edit_press(self, event: QMouseEvent, pos: QPointF) -> None:
        index = self._nearest_point(pos)
        if event.button() == Qt.MouseButton.RightButton and index is not None:
            self._points = np.delete(self._points, index, axis=0)
            self._redraw_points()
            self.points_edited.emit(self.points())
        elif event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._start_rubber(pos, QColor("#FF1744"))
            elif index is not None:
                self._drag_index = index
            else:
                self._points = np.vstack([self._points, [pos.x(), pos.y()]])
                self._points = self._points[np.argsort(self._points[:, 0], kind="stable")]
                self._redraw_points()
                self.points_edited.emit(self.points())

    def _start_rubber(self, pos: QPointF, color: QColor) -> None:
        self._rubber_start = pos
        self._rubber = QGraphicsRectItem(QRectF(pos, pos))
        pen = QPen(color, 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self._rubber.setPen(pen)
        self._scene.addItem(self._rubber)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = self._image_pos(event)
        self.cursor_moved.emit(pos.x(), pos.y())
        if self._panning is not None:
            delta = event.position() - self._panning
            self._panning = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        if self._rubber is not None and self._rubber_start is not None:
            self._rubber.setRect(QRectF(self._rubber_start, pos).normalized())
            return
        if self._drag_index is not None:
            self._points[self._drag_index] = (pos.x(), pos.y())
            self._redraw_points()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning is not None:
            self._panning = None
            self.set_mode(self.mode)
            return
        if self._rubber is not None:
            rect = self._rubber.rect()
            self._scene.removeItem(self._rubber)
            self._rubber, self._rubber_start = None, None
            self._finish_rubber(rect)
            return
        if self._drag_index is not None:
            self._drag_index = None
            self._points = self._points[np.argsort(self._points[:, 0], kind="stable")]
            self._redraw_points()
            self.points_edited.emit(self.points())

    def _finish_rubber(self, rect: QRectF) -> None:
        if rect.width() < 3 or rect.height() < 3:
            return
        if self.mode == ViewMode.CROP:
            self.crop_selected.emit((int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())))
        elif self.mode == ViewMode.EDIT_POINTS and len(self._points):
            inside = ((self._points[:, 0] >= rect.left()) & (self._points[:, 0] <= rect.right())
                      & (self._points[:, 1] >= rect.top()) & (self._points[:, 1] <= rect.bottom()))
            if inside.any():
                self._points = self._points[~inside]
                self._redraw_points()
                self.points_edited.emit(self.points())
