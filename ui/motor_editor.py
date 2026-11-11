"""Zone 1 - Motor properties form and quick characteristics summary."""

from __future__ import annotations

from localization import N_, _

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from application.application_controller import CHANGE_ALL, CHANGE_METADATA, CHANGE_POINTS, MotorDocument
from models.motor_metadata import PROPELLANT_TYPES
from services.thrust_analysis import ThrustAnalysisService
from ui.common import CommitTextEdit, OptionalNumberEdit


class MotorEditorWidget(QScrollArea):
    """Form editing :class:`MotorMetadata` through the document (undoable)."""

    TEXT_FIELDS = (
        ("name", N_("Motor name"), N_("Short motor code written in the ENG file, e.g. 'C6'. Required; spaces become '_'.")),
        ("manufacturer", N_("Manufacturer"), N_("Manufacturer name or abbreviation (e.g. 'Estes'). Required by the ENG format.")),
        ("designation", N_("Motor designation"), N_("Full commercial designation including the delay, e.g. 'C6-5'.")),
        ("delays", N_("Ejection delays"), N_("Available ejection delays in seconds separated by '-' (e.g. '3-5-7'). "
                                      "'P' = plugged (no ejection charge), '0' = none.")),
    )
    NUMBER_FIELDS = (
        ("diameter_mm", N_("Motor diameter (mm)"), "mm", N_("Outside diameter of the motor casing in millimetres (> 0). Required for ENG export.")),
        ("length_mm", N_("Motor length (mm)"), "mm", N_("Overall length of the motor in millimetres (> 0). Required for ENG export.")),
        ("propellant_mass_g", N_("Propellant mass (g)"), "g", N_("Mass of propellant in grams (> 0). Written in kg in ENG files.")),
        ("casing_mass_g", N_("Casing mass (g)"), "g", N_("Empty casing mass in grams (optional). When given, the total mass is computed.")),
        ("nozzle_closure_mass_g", N_("Nozzle and closure mass (g)"), "g", N_("Mass of the nozzle and closures in grams (optional).")),
    )

    def __init__(self, document: MotorDocument, analysis: ThrustAnalysisService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._document = document
        self._analysis = analysis
        self._text_edits: dict[str, QLineEdit] = {}
        self._number_edits: dict[str, OptionalNumberEdit] = {}
        self._summary_labels: dict[str, QLabel] = {}
        self._build_ui()
        document.changed.connect(self._on_changed)
        self.refresh()

    def set_analysis_service(self, analysis: ThrustAnalysisService) -> None:
        """Use another analysis service (preferences changed)."""
        self._analysis = analysis
        self.refresh()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self._build_identity_group())
        layout.addWidget(self._build_physical_group())
        layout.addWidget(self._build_text_group())
        layout.addWidget(self._build_summary_group())
        layout.addStretch(1)
        self.setWidget(container)
        self.setWidgetResizable(True)
        self.setMinimumWidth(300)

    def _build_identity_group(self) -> QGroupBox:
        group = QGroupBox(_("Identification"))
        form = QFormLayout(group)
        for name, caption, tip in self.TEXT_FIELDS:
            edit = QLineEdit()
            edit.setToolTip(_(tip))
            edit.editingFinished.connect(lambda n=name, e=edit: self._document.set_metadata_field(n, e.text().strip()))
            self._text_edits[name] = edit
            form.addRow(self._label(caption, tip), edit)
        self.propellant_type = QComboBox()
        self.propellant_type.setEditable(True)
        self.propellant_type.addItems([""] + list(PROPELLANT_TYPES))
        tip = N_("Propellant family (choose from the list or type your own).")
        self.propellant_type.setToolTip(_(tip))
        self.propellant_type.lineEdit().editingFinished.connect(self._commit_propellant_type)
        self.propellant_type.activated.connect(lambda _i: self._commit_propellant_type())
        form.addRow(self._label(N_("Propellant type"), tip), self.propellant_type)
        return group

    def _build_physical_group(self) -> QGroupBox:
        group = QGroupBox(_("Dimensions and masses"))
        form = QFormLayout(group)
        for name, caption, unit, tip in self.NUMBER_FIELDS:
            edit = OptionalNumberEdit(unit)
            edit.setToolTip(_(tip))
            edit.value_committed.connect(lambda value, n=name: self._document.set_metadata_field(n, value))
            self._number_edits[name] = edit
            form.addRow(self._label(caption, tip), edit)
        self.total_mass = OptionalNumberEdit("g")
        self.total_mass.value_committed.connect(lambda v: self._document.set_metadata_field("declared_total_mass_g", v))
        form.addRow(self._label(N_("Total motor mass (g)"), N_("Loaded motor mass in grams.")), self.total_mass)
        self.total_mass_hint = QLabel()
        self.total_mass_hint.setWordWrap(True)
        self.total_mass_hint.setStyleSheet("color: gray; font-size: 8pt;")
        form.addRow("", self.total_mass_hint)
        return group

    def _build_text_group(self) -> QGroupBox:
        group = QGroupBox(_("Description"))
        form = QFormLayout(group)
        self.description = CommitTextEdit()
        self.description.setToolTip(_("Free description of the motor (saved in the project file, not in ENG)."))
        self.description.setFixedHeight(60)
        self.description.committed.connect(lambda text: self._document.set_metadata_field("description", text))
        self.comments = CommitTextEdit()
        self.comments.setToolTip(_("Personal comments (saved in the project file, not in ENG)."))
        self.comments.setFixedHeight(60)
        self.comments.committed.connect(lambda text: self._document.set_metadata_field("comments", text))
        form.addRow(self._label(N_("Motor description"), N_("Free description.")), self.description)
        form.addRow(self._label(N_("Comments"), N_("Personal comments.")), self.comments)
        return group

    def _build_summary_group(self) -> QGroupBox:
        group = QGroupBox(_("Characteristics (computed)"))
        group.setToolTip(_("Values computed from the thrust curve. Open Tools > Thrust Analysis for details."))
        form = QFormLayout(group)
        for key, caption in (
            ("total_impulse_ns", N_("Total impulse")), ("average_thrust_n", N_("Average thrust")),
            ("maximum_thrust_n", N_("Maximum thrust")), ("burn_time_s", N_("Burn time")),
            ("specific_impulse_s", N_("Specific impulse")), ("class", N_("Impulse class")),
        ):
            value = QLabel("n/a")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._summary_labels[key] = value
            form.addRow(_(caption), value)
        return group

    def _label(self, caption: str, tip: str) -> QLabel:
        label = QLabel(_(caption))
        label.setToolTip(_(tip))
        return label

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------
    def _commit_propellant_type(self) -> None:
        self._document.set_metadata_field("propellant_type", self.propellant_type.currentText().strip())

    def _on_changed(self, kind: str) -> None:
        if kind in (CHANGE_ALL, CHANGE_METADATA, CHANGE_POINTS):
            self.refresh()

    def refresh(self) -> None:
        """Reload every field from the document."""
        meta = self._document.motor.metadata
        for name, edit in self._text_edits.items():
            if not edit.hasFocus() or edit.text() != getattr(meta, name):
                edit.setText(getattr(meta, name))
        for name, edit in self._number_edits.items():
            edit.set_value(getattr(meta, name))
        if self.propellant_type.currentText() != meta.propellant_type:
            self.propellant_type.setEditText(meta.propellant_type)
        self._refresh_total_mass()
        for edit, text in ((self.description, meta.description), (self.comments, meta.comments)):
            if edit.toPlainText() != text:
                edit.setPlainText(text)
        self._refresh_summary()

    def _refresh_total_mass(self) -> None:
        meta = self._document.motor.metadata
        computed = meta.has_component_masses()
        self.total_mass.set_value(meta.total_mass_g)
        self.total_mass.setReadOnly(computed)
        if computed:
            self.total_mass.setToolTip(_("Computed automatically: propellant + casing + nozzle/closure masses."))
            self.total_mass_hint.setText(_("Computed from the component masses."))
        else:
            self.total_mass.setToolTip(_("Total loaded mass in grams. Enter the casing and nozzle masses to compute it automatically."))
            self.total_mass_hint.setText(_("Declared value (enter casing/nozzle masses to compute it)."))

    def _refresh_summary(self) -> None:
        result = self._document.characteristics()
        rows = {row.key: row for row in self._analysis.display_rows(result)}
        for key, label in self._summary_labels.items():
            if key == "class":
                if result.impulse_class:
                    label.setText(f"{result.impulse_class} ({result.class_percent:.0f} %)  →  {result.suggested_designation or ''}")
                else:
                    label.setText("n/a")
                continue
            row = rows[key]
            label.setText(f"{row.text} {row.unit}" if row.value is not None else "n/a")
            label.setToolTip(row.reason)
