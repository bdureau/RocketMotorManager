"""Thrust analysis dialog: every characteristic with units and reasons."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QBrush, QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from application.error_handler import reporter
from models.motor import Motor
from models.motor_calculations import BURN_TIME_METHODS
from services.file_utils import atomic_write_text
from services.thrust_analysis import ThrustAnalysisService


class AnalysisDialog(QDialog):
    """Show the full analysis; the burn time method can be changed live."""

    def __init__(self, motor: Motor, burn_time_method: str, unit_system: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._motor = motor
        self._unit_system = unit_system
        self.setWindowTitle(self.tr("Thrust Analysis"))
        self.resize(640, 560)
        self.method = QComboBox()
        for key, caption in BURN_TIME_METHODS.items():
            self.method.addItem(self.tr(caption), key)
        self.method.setCurrentIndex(max(0, self.method.findData(burn_time_method)))
        self.method.setToolTip(self.tr("Definition of the burn time used for the average thrust:\n"
                                       "- Full powered curve: from ignition to burnout.\n"
                                       "- 5 % of maximum thrust: NAR/NFPA convention."))
        self.method.currentIndexChanged.connect(self._update)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([self.tr("Characteristic"), self.tr("Value"), self.tr("Unit")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.extra = QLabel()
        self.extra.setWordWrap(True)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #B9770E;")
        copy_button = QPushButton(self.tr("Copy report"))
        copy_button.setToolTip(self.tr("Copy the analysis as text to the clipboard."))
        copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._report()))
        save_button = QPushButton(self.tr("Save report..."))
        save_button.setToolTip(self.tr("Save the analysis report as a text file."))
        save_button.clicked.connect(self._save)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow(self.tr("Burn time definition"), self.method)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.extra)
        layout.addWidget(self.warnings)
        layout.addWidget(buttons)
        self._update()

    def _service(self) -> ThrustAnalysisService:
        return ThrustAnalysisService(self.method.currentData(), self._unit_system)

    def _update(self) -> None:
        service = self._service()
        result = service.analyse(self._motor)
        rows = service.display_rows(result)
        self.table.setRowCount(len(rows))
        grey = QBrush(QColor("#888888"))
        for index, row in enumerate(rows):
            caption = QTableWidgetItem(self.tr(row.caption))
            value = QTableWidgetItem(row.text)
            unit = QTableWidgetItem(row.unit)
            if row.value is None:
                for item in (caption, value, unit):
                    item.setForeground(grey)
                    item.setToolTip(row.reason or self.tr("Not available"))
            self.table.setItem(index, 0, caption)
            self.table.setItem(index, 1, value)
            self.table.setItem(index, 2, unit)
        details = []
        if result.impulse_class:
            details.append(self.tr("Impulse class: %1 (%2 % of class)").replace("%1", result.impulse_class).replace(
                "%2", f"{result.class_percent:.0f}"))
        if result.suggested_designation:
            details.append(self.tr("Suggested designation: %1").replace("%1", result.suggested_designation))
        if result.burn_start_s is not None:
            details.append(self.tr("Burn window: %1 s to %2 s").replace("%1", f"{result.burn_start_s:.4f}").replace(
                "%2", f"{result.burn_end_s:.4f}"))
        details.append(self.tr("Total impulse computed by trapezoidal integration (implicit origin at 0 s, 0 N)."))
        self.extra.setText("\n".join(details))
        self.warnings.setText("\n".join("⚠ " + w for w in result.warnings))

    def _report(self) -> str:
        service = self._service()
        return service.report_text(self._motor, service.analyse(self._motor))

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save analysis report"), "analysis.txt", self.tr("Text files (*.txt)"))
        if not path:
            return
        try:
            atomic_write_text(path, self._report())
        except Exception as exc:  # reported to the user
            reporter().error(self, exc)
