"""Label output actions shared by the main window Print menu and the
label designer: print preview, printing, PDF and image exports."""

from __future__ import annotations

from localization import _

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QMarginsF, QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize, QPainter
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QWidget

from application.error_handler import reporter
from models.errors import RocketMotorError
from models.label_template import PAPER_FORMATS, LabelTemplate
from services.label_service import LabelService

_service = LabelService()


def _configured_printer(template: LabelTemplate) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    width, height = PAPER_FORMATS[template.paper_format]
    printer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Millimeter, template.paper_format))
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setFullPage(True)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    printer.setDocName("Motor labels")
    return printer


def _render(printer: QPrinter, template: LabelTemplate, values: dict[str, str]) -> None:
    painter = QPainter()
    if not painter.begin(printer):
        return
    try:
        _service.render_sheets(printer, painter, template, values)
    finally:
        painter.end()


def print_preview(parent: Optional[QWidget], template: LabelTemplate, values: dict[str, str]) -> None:
    """Open the Qt print preview of the label sheet."""
    try:
        _service.sheet_layout(template)
    except RocketMotorError as exc:
        reporter().error(parent, exc)
        return
    printer = _configured_printer(template)
    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(_("Print Preview - labels"))
    dialog.paintRequested.connect(lambda device: _render(device, template, values))
    dialog.resize(900, 1000)
    dialog.exec()


def print_labels(parent: Optional[QWidget], template: LabelTemplate, values: dict[str, str]) -> None:
    """Print the label sheet on a printer chosen by the user."""
    try:
        _service.sheet_layout(template)
    except RocketMotorError as exc:
        reporter().error(parent, exc)
        return
    printer = _configured_printer(template)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() == QPrintDialog.DialogCode.Accepted:
        _render(printer, template, values)


def export_pdf(parent: Optional[QWidget], template: LabelTemplate, values: dict[str, str], folder: str = "") -> Optional[str]:
    """Ask a file name and export the label sheet as PDF."""
    name = (values.get("designation") or "labels").replace("/", "_").replace("—", "labels")
    path, _selected_filter = QFileDialog.getSaveFileName(parent, _("Print labels to PDF"),
                                          str(Path(folder) / f"{name}_labels.pdf"), "PDF (*.pdf)")
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    try:
        pages = _service.export_pdf(path, template, values)
    except Exception as exc:  # reported to the user
        reporter().error(parent, exc)
        return None
    reporter().info(parent, "PDF", _("Label sheet exported ({pages} page(s)):\n{path}").format(pages=pages, path=path))
    return path


def export_image(parent: Optional[QWidget], template: LabelTemplate, values: dict[str, str], image_format: str,
                 dpi: Optional[int] = None, folder: str = "") -> Optional[str]:
    """Ask a file name (and resolution) and export one label as PNG/JPEG."""
    if dpi is None:
        dpi, ok = QInputDialog.getInt(parent, _("Resolution"), _("Image resolution (dpi):"), 300, 72, 2400, 50)
        if not ok:
            return None
    extension = "png" if image_format == "png" else "jpg"
    name = (values.get("designation") or "label").replace("/", "_").replace("—", "label")
    pattern = _("PNG image (*.png)") if extension == "png" else _("JPEG image (*.jpg *.jpeg)")
    path, _selected_filter = QFileDialog.getSaveFileName(parent, _("Export label"), str(Path(folder) / f"{name}_label.{extension}"), pattern)
    if not path:
        return None
    if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg"):
        path += f".{extension}"
    try:
        _service.export_image(path, template, values, dpi)
    except Exception as exc:  # reported to the user
        reporter().error(parent, exc)
        return None
    return path
