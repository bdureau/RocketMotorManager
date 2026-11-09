"""Application controller and motor document.

* :class:`MotorDocument` owns the motor being edited, its file path, its
  modification state and the undo/redo stack. Every change goes through
  :meth:`MotorDocument.modify`, which records an undoable snapshot and
  emits :attr:`MotorDocument.changed` so that every view (properties form,
  graph, table) stays synchronised.
* :class:`ApplicationController` coordinates the document, the preferences
  and the file services. It contains no widget code: the UI asks the user
  for paths/options and calls the controller.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterable, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from application.configuration import ConfigurationManager, Preferences
from models.motor import Motor, PlotSettings
from models.motor_calculations import MotorCharacteristics
from models.thrust_point import ThrustPoint
from models.validation import ValidationReport, validate_motor
from services.csv_service import CsvExportOptions, CsvService
from services.eng_service import EngReadResult, EngService
from services.excel_service import ExcelService
from services.thrust_analysis import ThrustAnalysisService
from services.xml_service import XmlLoadResult, XmlService

logger = logging.getLogger(__name__)

# Change kinds carried by MotorDocument.changed
CHANGE_ALL = "all"
CHANGE_POINTS = "points"
CHANGE_METADATA = "metadata"
CHANGE_PLOT = "plot"
CHANGE_LABEL = "label"


class SnapshotCommand(QUndoCommand):
    """Undoable change storing the motor state before and after."""

    def __init__(self, document: "MotorDocument", text: str, kind: str, before: Motor, after: Motor) -> None:
        super().__init__(text)
        self._document = document
        self._kind = kind
        self._before = before
        self._after = after
        self._first_redo = True

    def redo(self) -> None:  # noqa: D401 - Qt override
        """Apply the change (skipped on push: it is already applied)."""
        if self._first_redo:
            self._first_redo = False
            return
        self._document.restore(self._after, self._kind)

    def undo(self) -> None:  # noqa: D401 - Qt override
        """Revert to the state before the change."""
        self._document.restore(self._before, self._kind)


class MotorDocument(QObject):
    """The motor currently edited in the main window."""

    changed = pyqtSignal(str)
    file_path_changed = pyqtSignal(str)
    modified_changed = pyqtSignal(bool)

    def __init__(self, analysis_service: ThrustAnalysisService) -> None:
        super().__init__()
        self.motor = Motor()
        self.file_path: Optional[str] = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self._analysis_service = analysis_service
        self._characteristics: Optional[MotorCharacteristics] = None
        self._dirty = False

    def _on_clean_changed(self, clean: bool) -> None:
        """Relay the undo stack clean state as a modification state."""
        self.modified_changed.emit(not clean or self._dirty)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    def is_modified(self) -> bool:
        """True when there are unsaved changes."""
        return self._dirty or not self.undo_stack.isClean()

    def display_name(self) -> str:
        """Name shown in the window title."""
        if self.file_path:
            return Path(self.file_path).name
        return self.motor.metadata.designation or self.motor.metadata.name or "Untitled motor"

    def characteristics(self) -> MotorCharacteristics:
        """Cached analysis of the current motor."""
        if self._characteristics is None:
            self._characteristics = self._analysis_service.analyse(self.motor)
        return self._characteristics

    def set_analysis_service(self, service: ThrustAnalysisService) -> None:
        """Replace the analysis service (preferences changed)."""
        self._analysis_service = service
        self._characteristics = None
        self.changed.emit(CHANGE_ALL)

    # ------------------------------------------------------------------
    # Loading / saving state
    # ------------------------------------------------------------------
    def load(self, motor: Motor, file_path: Optional[str], modified: bool = False) -> None:
        """Replace the whole document (clears undo history)."""
        self.motor = motor
        self.file_path = file_path
        self.undo_stack.clear()
        self._dirty = modified
        self._characteristics = None
        self.file_path_changed.emit(file_path or "")
        self.modified_changed.emit(self.is_modified)
        self.changed.emit(CHANGE_ALL)

    def mark_saved(self, file_path: str) -> None:
        """Record a successful save."""
        self.file_path = file_path
        self._dirty = False
        self.undo_stack.setClean()
        self.file_path_changed.emit(file_path)
        self.modified_changed.emit(False)

    # ------------------------------------------------------------------
    # Modifications
    # ------------------------------------------------------------------
    def modify(self, text: str, kind: str, mutate: Callable[[Motor], None]) -> None:
        """Apply ``mutate`` to the motor as one undoable step."""
        before = self.motor.clone()
        mutate(self.motor)
        if self.motor == before:
            return
        after = self.motor.clone()
        self._characteristics = None
        self.undo_stack.push(SnapshotCommand(self, text, kind, before, after))
        self.changed.emit(kind)

    def restore(self, snapshot: Motor, kind: str) -> None:
        """Restore a snapshot (called by undo/redo)."""
        self.motor = snapshot.clone()
        self._characteristics = None
        self.changed.emit(kind)

    # Convenience operations used by the views ------------------------------
    def set_points(self, points: Iterable[ThrustPoint], text: str = "Replace thrust points") -> None:
        """Replace the thrust curve."""
        new_points = list(points)
        self.modify(text, CHANGE_POINTS, lambda motor: motor.set_points(new_points))

    def update_point(self, index: int, point: ThrustPoint) -> None:
        """Change one point."""
        self.modify("Edit thrust point", CHANGE_POINTS, lambda motor: motor.update_point(index, point))

    def add_point(self, point: ThrustPoint, index: Optional[int] = None) -> None:
        """Add a point (chronological position when index is None)."""
        self.modify("Add thrust point", CHANGE_POINTS, lambda motor: motor.add_point(point, index))

    def remove_points(self, indices: Iterable[int]) -> None:
        """Remove several points."""
        rows = list(indices)
        self.modify("Delete thrust point(s)", CHANGE_POINTS, lambda motor: motor.remove_points(rows))

    def duplicate_point(self, index: int) -> None:
        """Duplicate a point."""
        self.modify("Duplicate thrust point", CHANGE_POINTS, lambda motor: motor.duplicate_point(index))

    def sort_points(self) -> None:
        """Sort points chronologically."""
        self.modify("Sort thrust points", CHANGE_POINTS, lambda motor: motor.sort_points())

    def set_metadata_field(self, name: str, value: object) -> None:
        """Change one :class:`MotorMetadata` attribute."""
        if getattr(self.motor.metadata, name) == value:
            return
        caption = name.replace("_", " ")
        self.modify(f"Change {caption}", CHANGE_METADATA, lambda motor: setattr(motor.metadata, name, value))

    def set_plot_settings(self, settings: PlotSettings) -> None:
        """Change the graph settings (not part of the undo history)."""
        self.motor.plot_settings = settings
        self._dirty = True
        self.modified_changed.emit(True)
        self.changed.emit(CHANGE_PLOT)

    def set_label(self, template) -> None:
        """Store the label template in the project (undoable)."""
        self.modify("Change label", CHANGE_LABEL, lambda motor: setattr(motor, "label", template))


class ApplicationController(QObject):
    """Coordinates preferences, document and services."""

    preferences_changed = pyqtSignal()
    recent_files_changed = pyqtSignal()

    def __init__(self, configuration: Optional[ConfigurationManager] = None) -> None:
        super().__init__()
        self.configuration = configuration or ConfigurationManager()
        self.configuration.load()
        self.eng_service = EngService()
        self.csv_service = CsvService()
        self.excel_service = ExcelService()
        self.xml_service = XmlService()
        self.document = MotorDocument(self._make_analysis_service())
        self.new_motor()

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    @property
    def preferences(self) -> Preferences:
        """Current user preferences."""
        return self.configuration.preferences

    def _make_analysis_service(self) -> ThrustAnalysisService:
        prefs = self.configuration.preferences
        return ThrustAnalysisService(prefs.burn_time_method, prefs.unit_system)

    @property
    def analysis_service(self) -> ThrustAnalysisService:
        """Analysis service configured from the preferences."""
        return self._make_analysis_service()

    def apply_preferences(self, preferences: Preferences) -> None:
        """Store and persist new preferences, then notify the views."""
        self.configuration.preferences = preferences
        self.configuration.save()
        self.document.set_analysis_service(self._make_analysis_service())
        self.preferences_changed.emit()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def new_motor(self) -> None:
        """Start a new empty motor."""
        motor = Motor()
        prefs = self.configuration.preferences
        motor.plot_settings = PlotSettings(
            show_grid=prefs.show_grid, show_markers=prefs.plot_show_markers,
            line_color=prefs.plot_line_color, marker_color=prefs.plot_marker_color,
            fill_under_curve=prefs.plot_fill_under_curve,
        )
        self.document.load(motor, None)
        logger.info("New motor")

    def open_project(self, path: str) -> XmlLoadResult:
        """Open a native XML project."""
        result = self.xml_service.load(path)
        self.document.load(result.motor, str(path))
        self._remember(path)
        return result

    def save_project(self, path: str) -> None:
        """Save the document as a native XML project."""
        self.xml_service.save(path, self.document.motor, self.document.characteristics())
        self.document.mark_saved(str(path))
        self._remember(path)

    def read_eng(self, path: str) -> EngReadResult:
        """Read an ENG file (the UI chooses the motor if several)."""
        result = self.eng_service.read_file(path)
        self.configuration.preferences.import_dir = str(Path(path).parent)
        return result

    def load_imported_motor(self, motor: Motor) -> None:
        """Open an imported motor as a new, unsaved document."""
        motor.plot_settings = PlotSettings(**vars(self.document.motor.plot_settings))
        motor.plot_settings.x_min = motor.plot_settings.x_max = None
        motor.plot_settings.y_min = motor.plot_settings.y_max = None
        self.document.load(motor, None, modified=True)

    def validate(self) -> ValidationReport:
        """Validate the current motor."""
        return validate_motor(self.document.motor)

    def export_eng(self, path: str, allow_warnings: bool = True) -> None:
        """Export the current motor to an ENG file."""
        self.eng_service.write_file(path, [self.document.motor], allow_warnings)

    def export_csv(self, path: str, options: CsvExportOptions) -> None:
        """Export the thrust curve to CSV."""
        self.csv_service.write_file(path, self.document.motor, options)

    def replace_points(self, points: Iterable[ThrustPoint], source: str) -> None:
        """Replace the thrust curve with imported data (undoable)."""
        self.document.set_points(points, f"Import thrust data from {source}")

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------
    def _remember(self, path: str) -> None:
        self.configuration.add_recent_file(str(path))
        self.configuration.preferences.default_save_dir = str(Path(path).parent)
        self.configuration.save()
        self.recent_files_changed.emit()

    def forget_recent(self, path: str) -> None:
        """Remove a missing file from the recent list."""
        self.configuration.remove_recent_file(path)
        self.configuration.save()
        self.recent_files_changed.emit()

    def clear_recent(self) -> None:
        """Empty the recent files list."""
        self.configuration.preferences.recent_files = []
        self.configuration.save()
        self.recent_files_changed.emit()
