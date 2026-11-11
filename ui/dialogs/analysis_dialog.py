"""Thrust analysis dialog: every characteristic with units and reasons."""

from __future__ import annotations

from localization import _

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
        self.setWindowTitle(_("Thrust Analysis"))
        self.resize(640, 560)
        self.method = QComboBox()
        for key, caption in BURN_TIME_METHODS.items():
            self.method.addItem(_(caption), key)
        self.method.setCurrentIndex(max(0, self.method.findData(burn_time_method)))
        self.method.setToolTip(_("Definition of the burn time used for the average thrust:\n"
                                       "- Full powered curve: from ignition to burnout.\n"
                                       "- 5 % of maximum thrust: NAR/NFPA convention."))
        self.method.currentIndexChanged.connect(self._update)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([_("Characteristic"), _("Value"), _("Unit")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.extra = QLabel()
        self.extra.setWordWrap(True)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #B9770E;")
        copy_button = QPushButton(_("Copy report"))
        copy_button.setToolTip(_("Copy the analysis as text to the clipboard."))
        copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._report()))
        save_button = QPushButton(_("Save report..."))
        save_button.setToolTip(_("Save the analysis report as a text file."))
        save_button.clicked.connect(self._save)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow(_("Burn time definition"), self.method)
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
            caption = QTableWidgetItem(_(row.caption))
            value = QTableWidgetItem(row.text)
            unit = QTableWidgetItem(row.unit)
            if row.value is None:
                for item in (caption, value, unit):
                    item.setForeground(grey)
                    item.setToolTip(row.reason or _("Not available"))
            self.table.setItem(index, 0, caption)
            self.table.setItem(index, 1, value)
            self.table.setItem(index, 2, unit)
        details = []
        if result.impulse_class:
            details.append(_("Impulse class: {impulse_class} ({percent} % of class)").format(impulse_class=result.impulse_class, percent=f"{result.class_percent:.0f}"))
        if result.suggested_designation:
            details.append(_("Suggested designation: {designation}").format(designation=result.suggested_designation))
        if result.burn_start_s is not None:
            details.append(_("Burn window: {start} s to {end} s").format(start=f"{result.burn_start_s:.4f}", end=f"{result.burn_end_s:.4f}"))
        details.append(_("Total impulse computed by trapezoidal integration (implicit origin at 0 s, 0 N)."))
        self.extra.setText("\n".join(details))
        self.warnings.setText("\n".join("⚠ " + w for w in result.warnings))

    def _report(self) -> str:
        service = self._service()
        return service.report_text(self._motor, service.analyse(self._motor))

    def _save(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(self, _("Save analysis report"), "analysis.txt", _("Text files (*.txt)"))
        if not path:
            return
        try:
            atomic_write_text(path, self._report())
        except Exception as exc:  # reported to the user
            reporter().error(self, exc)
