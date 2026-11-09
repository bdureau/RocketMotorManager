"""Label rendering, sheet layout, template library and exports.

A single renderer based on ``QPainter`` draws the label in millimetre
coordinates, so the on-screen preview, the printer, the PDF and the
PNG/JPEG exports are guaranteed to be identical and to respect the physical
dimensions of the label.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PyQt6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QPageLayout, QPageSize, QPagedPaintDevice, QPainter,
    QPainterPath, QPdfWriter, QPen,
)

from application.paths import resource_path, user_templates_dir
from models.errors import FileAccessError, ValidationError
from models.label_template import LABEL_FIELD_CAPTIONS, PAPER_FORMATS, LabelTemplate
from models.motor import Motor
from models.motor_calculations import MotorCharacteristics
from models.units import Quantity, display_unit, from_reference
from services.file_utils import atomic_write_text, format_number

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4
MIN_FONT_PT = 3.0


@dataclass(frozen=True)
class SheetLayout:
    """Placement of labels on a paper sheet (all values in mm)."""

    paper_width: float
    paper_height: float
    columns: int
    rows: int
    positions: tuple[tuple[float, float], ...]  # top-left corners on one page

    @property
    def per_page(self) -> int:
        """Number of labels fitting on one page."""
        return self.columns * self.rows


# ----------------------------------------------------------------------
# Field values
# ----------------------------------------------------------------------
def label_values(motor: Motor, result: MotorCharacteristics, unit_system: str = "metric") -> dict[str, str]:
    """Return the formatted text of every label field."""
    meta = motor.metadata

    def quantity(value: Optional[float], kind: Quantity, decimals: int) -> str:
        if value is None:
            return "—"
        unit = display_unit(unit_system, kind)
        return f"{format_number(from_reference(value, unit), decimals)} {unit}"

    return {
        "motor_name": meta.name or "—",
        "manufacturer": meta.manufacturer or "—",
        "designation": meta.designation or meta.name or "—",
        "diameter": quantity(meta.diameter_mm, Quantity.LENGTH, 1 if unit_system == "metric" else 2),
        "length": quantity(meta.length_mm, Quantity.LENGTH, 1 if unit_system == "metric" else 2),
        "total_impulse": quantity(result.total_impulse_ns, Quantity.IMPULSE, 2),
        "average_thrust": quantity(result.average_thrust_n, Quantity.FORCE, 2),
        "maximum_thrust": quantity(result.maximum_thrust_n, Quantity.FORCE, 2),
        "burn_time": f"{format_number(result.burn_time_s, 2)} s" if result.burn_time_s is not None else "—",
        "propellant_mass": quantity(meta.propellant_mass_g, Quantity.MASS, 1),
        "total_mass": quantity(meta.total_mass_g, Quantity.MASS, 1),
        "propellant_type": meta.propellant_type or "—",
        "delays": meta.delays or "—",
        "impulse_class": result.impulse_class or "—",
    }


# ----------------------------------------------------------------------
# Renderer
# ----------------------------------------------------------------------
class LabelRenderer:
    """Draw a label with a QPainter whose unit is set to millimetres."""

    def __init__(self, template: LabelTemplate, values: dict[str, str]) -> None:
        self.template = template
        self.values = values
        self._logo: Optional[QImage] = None
        if template.logo_path and Path(template.logo_path).is_file():
            image = QImage(template.logo_path)
            self._logo = image if not image.isNull() else None
            if self._logo is None:
                logger.warning("Cannot load logo %s", template.logo_path)

    # -- public ---------------------------------------------------------------
    def draw(self, painter: QPainter, x_mm: float, y_mm: float, px_per_mm: float) -> None:
        """Draw the label with its top-left corner at (x_mm, y_mm)."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.scale(px_per_mm, px_per_mm)
        painter.translate(x_mm, y_mm)
        self._device = painter.device()
        self._dpi = self._device.logicalDpiY() or 96
        self._draw_background(painter)
        text_rect = self._draw_logo(painter, self._inner_rect())
        self._draw_content(painter, text_rect)
        painter.restore()

    # -- geometry ------------------------------------------------------------
    def _outer_rect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.template.width_mm, self.template.height_mm)

    def _inner_rect(self) -> QRectF:
        margin = self.template.inner_margin_mm + self.template.border_width_mm
        return self._outer_rect().adjusted(margin, margin, -margin, -margin)

    def _font(self, size_pt: float, bold: bool = False) -> QFont:
        """Font whose height is ``size_pt`` points in millimetre coordinates."""
        font = QFont(self.template.font_family)
        font.setPointSizeF(max(0.5, size_pt * MM_PER_INCH / self._dpi))
        font.setBold(bold)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return font

    # -- drawing steps ---------------------------------------------------------
    def _draw_background(self, painter: QPainter) -> None:
        t = self.template
        half = t.border_width_mm / 2
        rect = self._outer_rect().adjusted(half, half, -half, -half)
        path = QPainterPath()
        path.addRoundedRect(rect, t.border_radius_mm, t.border_radius_mm)
        painter.fillPath(path, QBrush(QColor(t.background_color)))
        if t.layout == "banner":
            band = QPainterPath()
            band.addRect(QRectF(rect.left(), rect.top(), rect.width(), self._banner_height()))
            painter.fillPath(path.intersected(band), QBrush(QColor(t.accent_color)))
        if t.border_width_mm > 0:
            pen = QPen(QColor(t.border_color), t.border_width_mm)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _banner_height(self) -> float:
        return self.template.title_font_size * 0.3528 * 1.6 + self.template.inner_margin_mm

    def _logo_rect(self) -> Optional[QRectF]:
        if self._logo is None:
            return None
        t = self.template
        box = QRectF(t.logo_x_mm, t.logo_y_mm, t.logo_width_mm, t.logo_height_mm)
        ratio = self._logo.width() / max(1, self._logo.height())
        width, height = box.width(), box.width() / ratio
        if height > box.height():
            height, width = box.height(), box.height() * ratio
        return QRectF(box.left() + (box.width() - width) / 2, box.top() + (box.height() - height) / 2, width, height)

    def _draw_logo(self, painter: QPainter, text_rect: QRectF) -> QRectF:
        """Draw the logo and return the text area that avoids it."""
        rect = self._logo_rect()
        if rect is None:
            return text_rect
        painter.drawImage(rect, self._logo)
        if not rect.intersects(text_rect):
            return text_rect
        gap = 1.0
        if rect.center().x() >= text_rect.center().x():
            return QRectF(text_rect.left(), text_rect.top(), max(5.0, rect.left() - gap - text_rect.left()), text_rect.height())
        left = rect.right() + gap
        return QRectF(left, text_rect.top(), max(5.0, text_rect.right() - left), text_rect.height())

    def _lines(self) -> list[tuple[str, str]]:
        t = self.template
        return [(LABEL_FIELD_CAPTIONS.get(name, name), self.values.get(name, "—")) for name in t.fields]

    def _draw_content(self, painter: QPainter, area: QRectF) -> None:
        t = self.template
        title = self.values.get(t.title_field, "") if t.title_field else ""
        body_scale = 1.0
        for _attempt in range(25):  # shrink the text until everything fits
            if self._layout_fits(area, title, body_scale) or t.body_font_size * body_scale <= MIN_FONT_PT:
                break
            body_scale *= 0.92
        self._paint_text(painter, area, title, body_scale)

    def _blocks(self, title: str, scale: float) -> tuple[float, float, list[str]]:
        """Return (title height, line height, body lines) in mm."""
        t = self.template
        title_h = QFontMetricsF(self._font(t.title_font_size * scale, t.bold_title), self._device).height() if title else 0.0
        line_h = QFontMetricsF(self._font(t.body_font_size * scale), self._device).height()
        body = [f"{c}: {v}" if t.show_captions else v for c, v in self._lines()]
        if t.custom_text.strip():
            body.extend(t.custom_text.strip().splitlines())
        return title_h, line_h, body

    def _layout_fits(self, area: QRectF, title: str, scale: float) -> bool:
        title_h, line_h, body = self._blocks(title, scale)
        rows = math.ceil(len(body) / 2) if self.template.layout in ("two_columns", "banner") else len(body)
        top_reserved = self._banner_height() if self.template.layout == "banner" else title_h
        if top_reserved + rows * line_h > area.height() + 0.01:
            return False
        metrics = QFontMetricsF(self._font(self.template.body_font_size * scale), self._device)
        column_w = area.width() / (2 if self.template.layout in ("two_columns", "banner") else 1)
        return all(metrics.horizontalAdvance(line) <= column_w - 0.5 for line in body)

    def _alignment(self) -> Qt.AlignmentFlag:
        return {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight}[self.template.alignment]

    def _paint_text(self, painter: QPainter, area: QRectF, title: str, scale: float) -> None:
        t = self.template
        title_h, line_h, body = self._blocks(title, scale)
        align = self._alignment() | Qt.AlignmentFlag.AlignVCenter
        columns = 2 if t.layout in ("two_columns", "banner") else 1
        per_column = math.ceil(len(body) / columns) if body else 0
        top = area.top()
        if t.layout == "banner":
            free = area.bottom() - (self._banner_height() + 0.5) - per_column * line_h
        else:
            free = area.height() - title_h - per_column * line_h
        y = top + max(0.0, free) / 2  # centre the content vertically
        if title:
            painter.setFont(self._font(t.title_font_size * scale, t.bold_title))
            if t.layout == "banner":
                band = QRectF(area.left(), self._outer_rect().top(), area.width(), self._banner_height())
                painter.setPen(QColor(t.background_color))
                painter.drawText(band, align, title)
                y = band.bottom() + 0.5 + max(0.0, free) / 2
            else:
                painter.setPen(QColor(t.accent_color))
                painter.drawText(QRectF(area.left(), y, area.width(), title_h), align, title)
                y += title_h
        elif t.layout == "banner":
            y = self._banner_height() + 0.5 + max(0.0, free) / 2
        painter.setFont(self._font(t.body_font_size * scale))
        painter.setPen(QColor(t.text_color))
        column_w = area.width() / columns
        for index, line in enumerate(body):
            column, row = divmod(index, per_column) if per_column else (0, 0)
            rect = QRectF(area.left() + column * column_w, y + row * line_h, column_w - 0.5, line_h)
            painter.drawText(rect, align, line)


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class LabelService:
    """Template library, sheet layout and exports."""

    # -- templates --------------------------------------------------------------
    @staticmethod
    def builtin_templates() -> list[LabelTemplate]:
        """Predefined templates shipped in resources/templates."""
        templates = []
        for file in sorted(resource_path("resources", "templates").glob("*.json")):
            try:
                templates.append(LabelTemplate.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError) as exc:
                logger.warning("Invalid template %s: %s", file, exc)
        return templates or [LabelTemplate()]

    @staticmethod
    def user_templates(folder: Optional[Path] = None) -> list[LabelTemplate]:
        """Templates saved by the user."""
        templates = []
        for file in sorted((folder or user_templates_dir()).glob("*.json")):
            try:
                templates.append(LabelTemplate.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError) as exc:
                logger.warning("Invalid user template %s: %s", file, exc)
        return templates

    @staticmethod
    def _template_file(name: str, folder: Optional[Path]) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip()) or "template"
        return (folder or user_templates_dir()) / f"{safe}.json"

    def save_user_template(self, template: LabelTemplate, folder: Optional[Path] = None) -> Path:
        """Save a template in the user library and return its path."""
        if not template.name.strip():
            raise ValidationError("A template name is required.")
        path = self._template_file(template.name, folder)
        atomic_write_text(path, json.dumps(template.to_dict(), indent=2))
        return path

    def delete_user_template(self, name: str, folder: Optional[Path] = None) -> None:
        """Delete a user template."""
        path = self._template_file(name, folder)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise FileAccessError(f"Cannot delete template '{name}': {exc}") from exc

    # -- layout -------------------------------------------------------------------
    @staticmethod
    def sheet_layout(template: LabelTemplate) -> SheetLayout:
        """Compute the grid of labels on the selected paper format.

        Raises:
            ValidationError: If the label does not fit on the paper.
        """
        paper_w, paper_h = PAPER_FORMATS[template.paper_format]
        margin, spacing = template.page_margin_mm, template.label_spacing_mm
        usable_w, usable_h = paper_w - 2 * margin, paper_h - 2 * margin
        columns = int((usable_w + spacing) // (template.width_mm + spacing))
        rows = int((usable_h + spacing) // (template.height_mm + spacing))
        if columns < 1 or rows < 1:
            raise ValidationError(
                f"A {template.width_mm:g} x {template.height_mm:g} mm label does not fit on {template.paper_format} "
                f"paper with {margin:g} mm margins."
            )
        positions = tuple(
            (margin + c * (template.width_mm + spacing), margin + r * (template.height_mm + spacing))
            for r in range(rows) for c in range(columns)
        )
        return SheetLayout(paper_w, paper_h, columns, rows, positions)

    def label_count(self, template: LabelTemplate) -> int:
        """Number of labels to print (fill page or copies)."""
        if template.fill_page:
            return self.sheet_layout(template).per_page
        return max(1, template.copies)

    def render_sheets(self, device: QPagedPaintDevice, painter: QPainter, template: LabelTemplate,
                      values: dict[str, str]) -> int:
        """Render the labels on one or more pages of a paged device whose
        origin is the paper corner. Returns the number of pages."""
        layout = self.sheet_layout(template)
        px_per_mm = device.logicalDpiX() / MM_PER_INCH
        renderer = LabelRenderer(template, values)
        count = self.label_count(template)
        pages = math.ceil(count / layout.per_page)
        for index in range(count):
            slot = index % layout.per_page
            if index and slot == 0:
                device.newPage()
            x, y = layout.positions[slot]
            renderer.draw(painter, x, y, px_per_mm)
        return pages

    # -- exports ------------------------------------------------------------------
    def export_pdf(self, path: str, template: LabelTemplate, values: dict[str, str], resolution: int = 600) -> int:
        """Write a PDF sheet of labels; returns the page count."""
        layout = self.sheet_layout(template)
        writer = QPdfWriter(path)
        writer.setResolution(resolution)
        writer.setPageSize(QPageSize(QSizeF(layout.paper_width, layout.paper_height), QPageSize.Unit.Millimeter))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        writer.setTitle(f"Motor labels - {values.get('designation', '')}")
        writer.setCreator("Rocket Motor Manager")
        painter = QPainter()
        if not painter.begin(writer):
            raise FileAccessError(f"Cannot write PDF file: {path}")
        try:
            pages = self.render_sheets(writer, painter, template, values)
        finally:
            painter.end()
        logger.info("Label PDF exported: %s (%d page(s))", path, pages)
        return pages

    @staticmethod
    def render_image(template: LabelTemplate, values: dict[str, str], dpi: int, transparent: bool = False) -> QImage:
        """Render a single label to an image at the given resolution."""
        px_per_mm = dpi / MM_PER_INCH
        width = max(1, round(template.width_mm * px_per_mm))
        height = max(1, round(template.height_mm * px_per_mm))
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        dots_per_meter = round(dpi / 0.0254)
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)
        image.fill(Qt.GlobalColor.transparent if transparent else Qt.GlobalColor.white)
        painter = QPainter(image)
        try:
            LabelRenderer(template, values).draw(painter, 0.0, 0.0, px_per_mm)
        finally:
            painter.end()
        return image

    def export_image(self, path: str, template: LabelTemplate, values: dict[str, str], dpi: int = 300) -> None:
        """Export a single label as PNG or JPEG (format from extension)."""
        suffix = Path(path).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg"):
            raise ValidationError("Use a .png, .jpg or .jpeg file name.")
        image = self.render_image(template, values, dpi, transparent=False)
        if suffix != ".png":
            image = image.convertToFormat(QImage.Format.Format_RGB32)
        if not image.save(path, None, 95):
            raise FileAccessError(f"Cannot write image file: {path}")
        logger.info("Label image exported: %s (%d dpi)", path, dpi)

    @staticmethod
    def paint_preview(painter: QPainter, target: QRectF, template: LabelTemplate, values: dict[str, str]) -> float:
        """Draw a label scaled to fit ``target`` (screen preview). Returns
        the pixels-per-mm scale used."""
        scale = min(target.width() / template.width_mm, target.height() / template.height_mm)
        x = target.left() + (target.width() - template.width_mm * scale) / 2
        y = target.top() + (target.height() - template.height_mm * scale) / 2
        painter.save()
        painter.translate(QPointF(x, y))
        LabelRenderer(template, values).draw(painter, 0.0, 0.0, scale)
        painter.restore()
        return scale


def find_template(templates: Iterable[LabelTemplate], name: str) -> Optional[LabelTemplate]:
    """Return the template called ``name`` or None."""
    return next((t for t in templates if t.name == name), None)
