"""On-screen label preview drawn with the same renderer as the printer."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from models.label_template import LabelTemplate
from services.label_service import MM_PER_INCH, LabelService


class LabelPreviewWidget(QWidget):
    """Draw the label scaled to fit, or at real size (``zoom`` > 0)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.template = LabelTemplate()
        self.values: dict[str, str] = {}
        self.zoom = 0.0  # 0 = fit, otherwise multiple of the physical size
        self.setMinimumSize(320, 200)
        self.setToolTip(self.tr("Print preview of one label. The printed label has exactly the dimensions entered."))

    def set_content(self, template: LabelTemplate, values: dict[str, str]) -> None:
        """Display a template filled with values."""
        self.template = template
        self.values = values
        self.update()

    def set_zoom(self, zoom: float) -> None:
        """0 = fit to the widget, 1 = real size, 2 = double size..."""
        self.zoom = zoom
        if zoom > 0:
            px_per_mm = self.logicalDpiX() / MM_PER_INCH * zoom
            self.setMinimumSize(int(self.template.width_mm * px_per_mm) + 60, int(self.template.height_mm * px_per_mm) + 60)
        else:
            self.setMinimumSize(320, 200)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#7F8C8D"))
        area = QRectF(self.rect()).adjusted(30, 30, -30, -30)
        if self.zoom > 0:
            px_per_mm = self.logicalDpiX() / MM_PER_INCH * self.zoom
            width, height = self.template.width_mm * px_per_mm, self.template.height_mm * px_per_mm
            area = QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)
        scale = LabelService.paint_preview(painter, area, self.template, self.values)
        width, height = self.template.width_mm * scale, self.template.height_mm * scale
        left = area.left() + (area.width() - width) / 2
        bottom = area.top() + (area.height() + height) / 2
        painter.setPen(QPen(QColor("#ECF0F1")))
        painter.drawText(QRectF(left, bottom + 4, width, 20), Qt.AlignmentFlag.AlignHCenter,
                         f"{self.template.width_mm:g} × {self.template.height_mm:g} mm")
        painter.end()
