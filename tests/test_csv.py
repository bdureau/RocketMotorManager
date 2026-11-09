"""Tests of the CSV importer/exporter and of the column mapping."""

from __future__ import annotations

import pytest

from models.errors import ValidationError
from services.csv_service import CsvExportOptions, CsvService
from services.tabular_data import ColumnMapping, guess_columns, parse_number


def test_detect_semicolon_and_decimal_comma(data_dir):
    service = CsvService()
    text, encoding = service.load_text(data_dir / "comma_decimal.csv")
    dialect = service.detect_dialect(text, encoding)
    assert dialect.separator == ";"
    assert dialect.decimal_separator == ","
    assert dialect.has_header


def test_import_with_units_and_invalid_rows(data_dir):
    service = CsvService()
    table, dialect = service.read_file(data_dir / "comma_decimal.csv")
    assert table.column_names() == ["Time (ms)", "Thrust (N)"]
    mapping = ColumnMapping(0, 1, time_unit="ms", thrust_unit="N", decimal_separator=dialect.decimal_separator)
    result = mapping.convert(table, skip_invalid=True)
    assert [p.time_s for p in result.points] == pytest.approx([0, 0.1, 0.2, 0.3, 0.4])
    assert result.points[2].thrust_n == pytest.approx(12.25)
    assert len(result.invalid_rows) == 1 and result.invalid_rows[0][0] == 4
    with pytest.raises(ValidationError):
        mapping.convert(table, skip_invalid=False)


def test_comment_lines_skipped_and_comma_separator(data_dir):
    table, dialect = CsvService().read_file(data_dir / "simple.csv")
    assert dialect.separator == ","
    assert dialect.decimal_separator == "."
    assert table.headers == ["t", "F"]
    assert len(table.rows) == 5


def test_tab_without_header(data_dir):
    table, dialect = CsvService().read_file(data_dir / "tab_noheader.txt")
    assert dialect.separator == "\t"
    assert not dialect.has_header
    points = ColumnMapping().convert(table).points
    assert points[-1].time_s == 0.4


def test_whitespace_separator():
    service = CsvService()
    text = "0.1   2.5\n0.2  3.5\n0.3 0\n"
    dialect = service.detect_dialect(text)
    assert dialect.separator == " "
    assert len(service.parse(text, dialect).rows) == 3


def test_encoding_cp1252(tmp_path):
    path = tmp_path / "latin.csv"
    path.write_bytes("Temps (s);Poussée (N)\n0,1;5\n".encode("cp1252"))
    table, dialect = CsvService().read_file(path)
    assert dialect.encoding == "cp1252"
    assert table.headers[1] == "Poussée (N)"


def test_parse_number_variants():
    assert parse_number("1,5", ",") == 1.5
    assert parse_number("1.234,5", ",") == 1234.5
    assert parse_number(" 2.5 ") == 2.5
    assert parse_number("abc") is None
    assert parse_number("nan") is None
    assert parse_number(None) is None
    assert parse_number(3) == 3.0


def test_guess_columns():
    from services.tabular_data import TabularData

    table = TabularData(headers=["Index", "Time [s]", "Thrust [N]"], rows=[["1", "0", "0"]])
    assert guess_columns(table) == (1, 2)


def test_same_column_rejected():
    from services.tabular_data import TabularData

    with pytest.raises(ValidationError):
        ColumnMapping(0, 0).convert(TabularData(rows=[["1", "2"]]))


def test_export_roundtrip(triangle_motor, tmp_path):
    service = CsvService()
    options = CsvExportOptions(separator=";", decimal_separator=",", time_unit="ms", thrust_unit="lbf")
    path = tmp_path / "export.csv"
    service.write_file(path, triangle_motor, options)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Motor name: T10")
    assert "Time (ms);Thrust (lbf)" in text
    table, dialect = service.read_file(path)
    assert dialect.separator == ";" and dialect.decimal_separator == ","
    points = ColumnMapping(0, 1, "ms", "lbf", ",").convert(table).points
    for original, reread in zip(triangle_motor.points, points):
        assert reread.time_s == pytest.approx(original.time_s)
        assert reread.thrust_n == pytest.approx(original.thrust_n, abs=1e-5)


def test_export_rejects_identical_separators(triangle_motor):
    with pytest.raises(ValueError):
        CsvService().generate(triangle_motor, CsvExportOptions(separator=",", decimal_separator=","))
