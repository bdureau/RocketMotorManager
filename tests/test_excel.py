"""Tests of the Excel importer (.xlsx and .xls)."""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from models.errors import FileAccessError, FileFormatError
from services.excel_service import ExcelService
from services.tabular_data import ColumnMapping


@pytest.fixture
def xlsx_file(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Notes"
    sheet["A1"] = "nothing here"
    data = workbook.create_sheet("Thrust")
    data.append(["Time (s)", "Thrust (N)", "Comment"])
    for row in ([0.0, 0.0, "start"], [0.1, 5.5, None], [0.2, 12.25, "peak"], [0.3, "oops", None], [0.4, 0, "end"]):
        data.append(row)
    path = tmp_path / "data.xlsx"
    workbook.save(path)
    return path


def test_list_sheets(xlsx_file):
    assert ExcelService().list_sheets(xlsx_file) == ["Notes", "Thrust"]


def test_read_sheet_with_header(xlsx_file):
    table = ExcelService().read_sheet(xlsx_file, "Thrust")
    assert table.headers == ["Time (s)", "Thrust (N)", "Comment"]
    result = ColumnMapping(0, 1).convert(table)
    assert [p.thrust_n for p in result.points] == [0.0, 5.5, 12.25, 0.0]
    assert result.invalid_rows == [(3, "thrust value 'oops' is missing or not numeric")]


def test_read_xls(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    for index, (t, f) in enumerate([("t", "F"), (0.0, 0.0), (0.5, 7.0), (1.0, 0.0)]):
        sheet.write(index, 0, t)
        sheet.write(index, 1, f)
    path = tmp_path / "legacy.xls"
    workbook.save(str(path))
    service = ExcelService()
    assert service.engine_for(path) == "xlrd"
    table = service.read_sheet(path, "Data")
    assert [p.thrust_n for p in ColumnMapping().convert(table).points] == [0.0, 7.0, 0.0]


def test_unsupported_extension(tmp_path):
    with pytest.raises(FileFormatError):
        ExcelService().list_sheets(tmp_path / "file.ods")


def test_missing_file(tmp_path):
    with pytest.raises(FileAccessError):
        ExcelService().list_sheets(tmp_path / "missing.xlsx")


def test_corrupted_file(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not a zip archive")
    with pytest.raises(FileFormatError):
        ExcelService().list_sheets(path)
