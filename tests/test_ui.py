"""Offscreen smoke tests of the user interface and of the document model
(synchronisation graph/table/properties, undo/redo, windows)."""

from __future__ import annotations

import numpy as np
import pytest

from application.application_controller import ApplicationController
from application.configuration import ConfigurationManager
from models.label_template import LabelTemplate
from models.thrust_point import ThrustPoint
from widgets.thrust_table import parse_clipboard_rows


@pytest.fixture
def controller(qapp, tmp_path):
    return ApplicationController(ConfigurationManager(tmp_path / "prefs.json"))


@pytest.fixture
def window(controller):
    from ui.main_window import MainWindow

    win = MainWindow(controller)
    yield win
    controller.document.undo_stack.clear()
    controller.document.mark_saved("")
    win.close()


def test_document_undo_redo(controller, triangle_motor):
    document = controller.document
    document.load(triangle_motor, None)
    assert not document.is_modified
    document.update_point(1, ThrustPoint(1.0, 20.0))
    assert document.is_modified
    assert document.characteristics().total_impulse_ns == pytest.approx(20.0)
    document.undo_stack.undo()
    assert document.motor.points[1].thrust_n == 10.0
    assert document.characteristics().total_impulse_ns == pytest.approx(10.0)
    document.undo_stack.redo()
    assert document.motor.points[1].thrust_n == 20.0
    document.set_metadata_field("name", "NEW")
    document.undo_stack.undo()
    assert document.motor.metadata.name == "T10"


def test_no_op_change_is_not_recorded(controller, triangle_motor):
    controller.document.load(triangle_motor, None)
    controller.document.set_metadata_field("name", "T10")
    assert controller.document.undo_stack.count() == 0


def test_table_and_plot_synchronised(window, controller, data_dir):
    motor = controller.read_eng(str(data_dir / "sample_C6.eng")).motors[0]
    controller.load_imported_motor(motor)
    table = window.thrust_editor.table
    plot = window.thrust_editor.plot
    assert table.model.rowCount() == 24
    assert len(plot._points) == 24
    # edit through the table model -> document -> plot
    index = table.model.index(3, 1)
    assert table.model.setData(index, "20,5")
    assert controller.document.motor.points[3].thrust_n == 20.5
    assert plot._points[3].thrust_n == 20.5
    # graphical move -> document -> table
    plot.point_moved.emit(5, ThrustPoint(0.231, 9.0))
    assert table.model.data(table.model.index(5, 1)) == "9"
    # deletion and undo
    table.select_row(0)
    table.delete_selected()
    assert table.model.rowCount() == 23
    controller.document.undo_stack.undo()
    assert table.model.rowCount() == 24
    # properties panel follows
    assert window.motor_editor._text_edits["name"].text() == "C6"
    assert "N.s" in window.motor_editor._summary_labels["total_impulse_ns"].text()


def test_invalid_rows_highlighted(window, controller):
    controller.document.set_points([ThrustPoint(0.1, 1), ThrustPoint(0.05, 2), ThrustPoint(0.2, 0)])
    model = window.thrust_editor.table.model
    assert model.data(model.index(1, 0), 8) is not None  # BackgroundRole


def test_add_and_duplicate_points(window, controller):
    table = window.thrust_editor.table
    table.add_point()
    assert controller.document.motor.points == [ThrustPoint(0.0, 0.0)]
    controller.document.set_points([ThrustPoint(0.0, 0.0), ThrustPoint(1.0, 10.0)])
    table.select_row(0)
    table.add_point()
    assert controller.document.motor.points[1] == ThrustPoint(0.5, 5.0)
    table.select_row(1)
    table.duplicate_point()
    assert controller.document.motor.point_count() == 4


def test_paste_rows_from_excel(window, controller, qapp):
    from PyQt6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText("Time\tThrust\n0,1\t5,5\n0,2\t7\n0,3\t0\n")
    window.thrust_editor.table.paste()
    assert controller.document.motor.points == [ThrustPoint(0.1, 5.5), ThrustPoint(0.2, 7.0), ThrustPoint(0.3, 0.0)]


def test_parse_clipboard_variants():
    assert parse_clipboard_rows("0.1;2\n0.2;3") == [ThrustPoint(0.1, 2), ThrustPoint(0.2, 3)]
    assert parse_clipboard_rows("0.1 2\nfoo bar\n") == [ThrustPoint(0.1, 2)]
    assert parse_clipboard_rows("0.1,2\n") == [ThrustPoint(0.1, 2)]


def test_save_and_reopen_project(window, controller, triangle_motor, tmp_path):
    controller.document.load(triangle_motor, None, modified=True)
    path = str(tmp_path / "proj.rmm.xml")
    assert window._save_to(path)
    assert not controller.document.is_modified
    assert controller.preferences.recent_files[0].endswith("proj.rmm.xml")
    controller.new_motor()
    assert window.open_path(path)
    assert controller.document.motor.points == triangle_motor.points


def test_grid_toggle_saved_in_project(window, controller):
    window.toggle_grid(False)
    assert controller.document.motor.plot_settings.show_grid is False
    assert controller.document.is_modified


def test_label_designer_and_exports(window, controller, triangle_motor, tmp_path):
    from services.label_service import LabelService

    controller.document.load(triangle_motor, None)
    window.show_label_designer()
    editor = window._label_editor
    editor.width_mm.setValue(70)
    assert editor.template.width_mm == 70
    editor._store()
    assert controller.document.motor.label.width_mm == 70
    template, values = window._current_label()
    assert values["total_impulse"] == "10 N.s"
    service = LabelService()
    png = tmp_path / "label.png"
    service.export_image(str(png), template, values, dpi=300)
    from PyQt6.QtGui import QImage

    image = QImage(str(png))
    assert image.width() == round(70 / 25.4 * 300)
    pdf = tmp_path / "labels.pdf"
    template.copies = 40
    pages = service.export_pdf(str(pdf), template, values)
    assert pdf.read_bytes().startswith(b"%PDF") and pages >= 1
    editor.close()


def test_label_layout_validation():
    from models.errors import ValidationError
    from services.label_service import LabelService

    with pytest.raises(ValidationError):
        LabelService.sheet_layout(LabelTemplate(width_mm=400))
    layout = LabelService.sheet_layout(LabelTemplate(width_mm=90, height_mm=30, page_margin_mm=10, label_spacing_mm=3))
    assert layout.columns == 2 and layout.rows == 8


def test_user_template_library(tmp_path):
    from services.label_service import LabelService

    service = LabelService()
    template = LabelTemplate(name="My label/1", width_mm=55)
    service.save_user_template(template, tmp_path)
    loaded = service.user_templates(tmp_path)
    assert loaded[0].name == "My label/1" and loaded[0].width_mm == 55
    service.delete_user_template("My label/1", tmp_path)
    assert service.user_templates(tmp_path) == []
    assert len(service.builtin_templates()) >= 5


def test_digitizer_window_pipeline(window, controller):
    import cv2

    from services.image_digitizer import CalibrationPoint

    image = np.full((300, 400, 3), 255, np.uint8)
    pts = np.array([[50 + x, int(250 - 150 * np.exp(-((x - 100) / 40) ** 2))] for x in range(0, 300)], np.int32)
    cv2.polylines(image, [pts], False, (0, 0, 255), 2)
    window.show_digitizer()
    digitizer = window._digitizer
    digitizer.load_array(image)
    digitizer.calibration.set_point(CalibrationPoint(50, 250, 0.0, 0.0, "Origin"))
    digitizer.calibration.set_point(CalibrationPoint(350, 250, 3.0, 0.0, "Time max"))
    digitizer.calibration.set_point(CalibrationPoint(50, 100, 0.0, 15.0, "Thrust max"))
    digitizer._refresh_calibration()
    digitizer._auto_color()
    from services import image_digitizer as dig

    result = dig.digitize(digitizer._display, digitizer.calibration, digitizer._collect_settings())
    digitizer._on_extracted(result)
    assert 50 <= len(digitizer.points()) <= 101
    assert max(p.thrust_n for p in digitizer.points()) == pytest.approx(15.0, abs=0.5)  # resampled to 100 points
    controller.document.set_points([])
    digitizer._transfer()
    assert controller.document.motor.point_count() == len(digitizer.points())
    digitizer.close()


def test_preferences_window_roundtrip(window, controller):
    from ui.preferences_window import PreferencesWindow

    dialog = PreferencesWindow(controller.preferences, window)
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog.unit_system.setCurrentIndex(dialog.unit_system.findData("imperial"))
    dialog._accept()
    prefs = dialog.result_preferences()
    assert prefs.theme == "dark" and prefs.unit_system == "imperial"
    controller.apply_preferences(prefs)
    assert controller.configuration.path.exists()
    reloaded = ConfigurationManager(controller.configuration.path).load()
    assert reloaded.theme == "dark"
    dialog._restore_defaults()
    assert dialog.theme.currentData() == "light"


def test_dialogs_build(window, controller, data_dir, triangle_motor):
    from ui.dialogs.analysis_dialog import AnalysisDialog
    from ui.dialogs.tabular_import_dialog import TabularImportDialog
    from ui.dialogs.validation_dialog import ValidationDialog

    dialog = TabularImportDialog(str(data_dir / "comma_decimal.csv"), "csv", controller.csv_service, controller.excel_service)
    assert dialog.time_unit.currentText() == "ms"
    dialog.skip_invalid.setChecked(True)
    dialog._accept()
    assert len(dialog.points) == 5 and dialog.points[1].time_s == pytest.approx(0.1)
    analysis = AnalysisDialog(triangle_motor, "curve", "metric")
    assert analysis.table.item(0, 1).text() == "10"
    ValidationDialog(controller.validate())


def test_corrupted_preferences_fall_back_to_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{ not json")
    prefs = ConfigurationManager(path).load()
    assert prefs.theme == "light"
    path.write_text('{"theme": 5, "print_dpi": "high", "show_grid": false}')
    prefs = ConfigurationManager(path).load()
    assert prefs.theme == "light" and prefs.print_dpi == 300 and prefs.show_grid is False
