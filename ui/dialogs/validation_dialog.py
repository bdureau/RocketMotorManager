"""Data validation report dialog."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from models.validation import Severity, ValidationReport
from ui.common import icon

_ICONS = {Severity.ERROR: "delete_point", Severity.WARNING: "info", Severity.INFO: "info"}


class ValidationDialog(QDialog):
    """List validation issues; double-click goes to the related point."""

    row_requested = pyqtSignal(int)

    def __init__(self, report: ValidationReport, title: str = "", confirm_text: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or self.tr("Data Validation"))
        self.resize(560, 380)
        summary = QLabel()
        if report.is_valid and not report.warnings:
            summary.setText(self.tr("✔ No problem detected. The data is valid."))
            summary.setStyleSheet("color: #2E8B57; font-weight: bold;")
        else:
            summary.setText(self.tr("%1 error(s), %2 warning(s). Double-click an item to go to the point.")
                            .replace("%1", str(len(report.errors))).replace("%2", str(len(report.warnings))))
        self.list = QListWidget()
        for issue in report.issues:
            where = self.tr(" (row %1)").replace("%1", str(issue.row + 1)) if issue.row is not None else ""
            item = QListWidgetItem(icon(_ICONS[issue.severity]), f"[{issue.severity.value.upper()}] {issue.message}{where}")
            item.setData(256, issue.row)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(self._go_to)
        if confirm_text:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText(confirm_text)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(report.is_valid)
            buttons.accepted.connect(self.accept)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def _go_to(self, item: QListWidgetItem) -> None:
        row = item.data(256)
        if row is not None:
            self.row_requested.emit(int(row))
