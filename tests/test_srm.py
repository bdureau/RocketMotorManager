"""Tests of the Richard Nakka SRM workbook importer on the reference
workbooks SRM 1.3 and SRM 2023 (example motors shipped with SRM)."""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from models.errors import FileFormatError
from models.motor_calculations import MotorCalculator, total_impulse
from services.eng_service import EngService
from services.srm_service import CurveSource, SrmService, find_label, value_right_of
from services.xml_service import XmlService

# version, title, class, Dc, Lc, grain mass (g), It (N.s), Favg (N), Fmax (N), nozzle length
REFERENCES = {
    "SRM_1.3.xls": ("SRM 1.3", "Example Rocket Motor", "K", 70.0, 420.0, 1951.69086, 2480.50439, 1422.60822, 1586.01903, None),
    "SRM_2023.xls": ("SRM 2023", "Example Rocket Motor (L-Class)", "L", 75.0, 470.0, 2812.44595, 3501.53430, 1728.93810,
                     1968.11560, 113.7896),
}


@pytest.fixture(scope="module")
def workbooks(request):
    from pathlib import Path

    folder = Path(__file__).resolve().parent / "data"
    service = SrmService()
    return {name: service.read(folder / name) for name in REFERENCES}


@pytest.mark.parametrize("name", list(REFERENCES))
def test_detection(data_dir, name):
    assert SrmService().is_srm_workbook(data_dir / name)


def test_plain_workbook_is_not_srm(tmp_path):
    path = tmp_path / "plain.xlsx"
    workbook = Workbook()
    workbook.active.append(["t", "F"])
    workbook.save(path)
    assert not SrmService().is_srm_workbook(path)
    with pytest.raises(FileFormatError):
        SrmService().read(path)


@pytest.mark.parametrize("name", list(REFERENCES))
def test_motor_data(workbooks, name):
    version, title, motor_class, dc, lc, grain, impulse, average, peak, nozzle = REFERENCES[name]
    wb = workbooks[name]
    assert wb.version == version
    assert wb.title == title
    assert wb.subtitle == "utilizing KNDX propellant."
    assert wb.propellant == "KNDX"
    assert wb.propellant_description().startswith("KNDX")
    assert wb.chamber_diameter_mm == dc and wb.chamber_length_mm == lc
    assert wb.grain_mass_g == pytest.approx(grain, abs=1e-3)
    assert wb.nozzle_length_mm == (pytest.approx(nozzle, abs=1e-3) if nozzle else None)
    s = wb.summary
    assert s.motor_class == motor_class
    assert s.total_impulse_ns == pytest.approx(impulse, abs=1e-3)
    assert s.average_thrust_n == pytest.approx(average, abs=1e-3)
    assert s.maximum_thrust_n == pytest.approx(peak, abs=1e-3)
    assert s.max_pressure_mpa > 5
    assert wb.details["grain_segments"] == "4"
    assert "throat_diameter" in wb.details


@pytest.mark.parametrize("name", list(REFERENCES))
def test_curves_match_workbook_results(workbooks, name):
    wb = workbooks[name]
    impulse, peak = REFERENCES[name][6], REFERENCES[name][8]
    full = wb.curve(CurveSource.PERFORMANCE_FULL)
    assert len(full) > 800
    assert total_impulse(full) == pytest.approx(impulse, rel=1e-6)  # exactly the SRM result
    assert max(p.thrust_n for p in full) == pytest.approx(wb.summary.maximum_thrust_n, rel=1e-12)
    assert wb.summary.maximum_thrust_n == pytest.approx(peak, abs=1e-3)
    assert full[0].time_s == 0.0 and full[-1].thrust_n == 0.0
    assert all(b.time_s > a.time_s for a, b in zip(full, full[1:]))
    simplified = wb.curve(CurveSource.PERFORMANCE_SIMPLIFIED, 0.005)
    assert 15 < len(simplified) < 60
    assert total_impulse(simplified) == pytest.approx(impulse, rel=0.003)
    assert max(p.thrust_n for p in simplified) == pytest.approx(wb.summary.maximum_thrust_n, rel=1e-12)  # peak kept
    resampled = wb.curve(CurveSource.PERFORMANCE_RESAMPLED, points=150)
    assert len(resampled) == 150
    output = wb.curve(CurveSource.OUTPUT_TABLE)
    assert len(output) == 23
    assert total_impulse(output) == pytest.approx(impulse, rel=0.025)
    assert not any("integrates" in w for w in wb.warnings)


@pytest.mark.parametrize("name", list(REFERENCES))
def test_motor_conversion_and_eng_roundtrip(workbooks, name, tmp_path):
    wb = workbooks[name]
    motor = wb.to_motor(wb.curve(CurveSource.PERFORMANCE_SIMPLIFIED), manufacturer="Amateur",
                        diameter_mm=wb.chamber_diameter_mm + 6, length_mm=550.0, casing_mass_g=900.0,
                        nozzle_mass_g=300.0, source_file=name)
    meta = motor.metadata
    assert meta.name == wb.suggested_name() and meta.name[0] == REFERENCES[name][2]
    assert meta.designation == f"{meta.name}-P"
    assert meta.total_mass_g == pytest.approx(wb.grain_mass_g + 1200.0)
    assert meta.extra["srm_workbook_version"] == wb.version
    result = MotorCalculator().analyse(motor)
    assert result.impulse_class == REFERENCES[name][2]
    assert result.specific_impulse_s == pytest.approx(wb.summary.specific_impulse_s, rel=0.005)
    eng = tmp_path / "srm.eng"
    EngService().write_file(eng, [motor])
    reread = EngService().read_file(eng).motors[0]
    written = motor.points[1:]  # (0, 0) is implicit in ENG files; values are written with 6 decimals
    assert len(reread.points) == len(written)
    for a, b in zip(reread.points, written):
        assert a.time_s == pytest.approx(b.time_s, abs=1e-6) and a.thrust_n == pytest.approx(b.thrust_n, abs=1e-6)
    assert reread.metadata.propellant_mass_g == pytest.approx(wb.grain_mass_g, rel=1e-6)
    project = tmp_path / "srm.rmm.xml"
    XmlService().save(project, motor)
    assert XmlService().load(project).motor.metadata.extra == meta.extra


def test_label_lookup_is_case_sensitive():
    grid = [["Do", 62.0], ["do", 20.0], [" Kn max: ", 300.0]]
    assert value_right_of(grid, ["do"]) == 20.0
    assert value_right_of(grid, ["Do"]) == 62.0
    assert value_right_of(grid, ["Kn max"]) == 300.0
    assert find_label(grid, ["missing"]) is None


def test_srm_dialog(qapp, workbooks, data_dir):
    from ui.dialogs.srm_import_dialog import SrmImportDialog

    wb = workbooks["SRM_2023.xls"]
    dialog = SrmImportDialog(wb, str(data_dir / "SRM_2023.xls"))
    assert dialog.length.value() == pytest.approx(583.8)  # chamber + nozzle
    dialog.manufacturer.setText("Club")
    dialog.source.setCurrentIndex(dialog.source.findData(CurveSource.OUTPUT_TABLE))
    assert len(dialog._curve) == 23
    dialog.source.setCurrentIndex(dialog.source.findData(CurveSource.PERFORMANCE_SIMPLIFIED))
    dialog._accept()
    assert dialog.motor.metadata.manufacturer == "Club"
    assert dialog.motor.metadata.extra["srm_curve_source"] == "performance_simplified"
    assert dialog.comparison.item(0, 1).text().startswith("3501.53")
