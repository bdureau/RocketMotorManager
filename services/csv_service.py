"""CSV import (with separator / decimal / encoding detection) and export."""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

from models.motor import Motor
from models.units import from_reference
from services.file_utils import PathLike, atomic_write_text, decode_text, format_number, read_bytes
from services.tabular_data import TabularData, looks_like_header

logger = logging.getLogger(__name__)

#: Candidate field separators, in priority order. ``" "`` means "any run
#: of whitespace".
SEPARATORS: tuple[str, ...] = ("\t", ";", ",", "|", " ")
SEPARATOR_NAMES: dict[str, str] = {
    "\t": "Tab", ";": "Semicolon (;)", ",": "Comma (,)", "|": "Pipe (|)", " ": "Space / whitespace",
}
ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16")
COMMENT_PREFIX = "#"
_NUMBER_WITH_COMMA = re.compile(r"^-?\d+,\d+$")
_NUMBER_WITH_DOT = re.compile(r"^-?\d*\.\d+$")


@dataclass
class CsvDialect:
    """Detected or user-selected CSV reading options."""

    separator: str = ","
    decimal_separator: str = "."
    encoding: str = "utf-8"
    has_header: bool = True


@dataclass
class CsvExportOptions:
    """Options of the CSV exporter."""

    separator: str = ","
    decimal_separator: str = "."
    encoding: str = "utf-8"
    time_unit: str = "s"
    thrust_unit: str = "N"
    include_metadata: bool = True
    max_decimals: int = 6


class CsvService:
    """Read and write thrust data as CSV."""

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def load_text(self, path: PathLike, encoding: Optional[str] = None) -> tuple[str, str]:
        """Read a CSV file and return ``(text, encoding)``."""
        data = read_bytes(path)
        if encoding:
            return data.decode(encoding, errors="replace"), encoding
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16"), "utf-16"
        return decode_text(data)

    def detect_dialect(self, text: str, encoding: str = "utf-8") -> CsvDialect:
        """Detect separator, decimal separator and header presence."""
        lines = self._data_lines(text)[:50]
        separator = self._detect_separator(lines)
        rows = [self._split(line, separator) for line in lines]
        decimal = self._detect_decimal(rows, separator)
        has_header = bool(rows) and looks_like_header(rows[0], decimal)
        return CsvDialect(separator, decimal, encoding, has_header)

    @staticmethod
    def _data_lines(text: str) -> list[str]:
        """Non-empty lines that are not ``#`` comments."""
        return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(COMMENT_PREFIX)]

    @staticmethod
    def _detect_separator(lines: Sequence[str]) -> str:
        """Choose the separator giving the most consistent column count."""
        best, best_score = " ", 0.0
        for candidate in SEPARATORS[:-1]:
            counts = [line.count(candidate) for line in lines]
            if not counts or max(counts) == 0:
                continue
            mode, frequency = Counter(counts).most_common(1)[0]
            if mode == 0:
                continue
            score = frequency / len(counts) + 0.01 * mode
            if score > best_score:
                best, best_score = candidate, score
        return best

    @staticmethod
    def _detect_decimal(rows: Sequence[Sequence[str]], separator: str) -> str:
        """Return ``,`` when numeric cells use a decimal comma."""
        if separator == ",":
            return "."
        comma = dot = 0
        for row in rows:
            for cell in row:
                cell = cell.strip()
                if _NUMBER_WITH_COMMA.match(cell):
                    comma += 1
                elif _NUMBER_WITH_DOT.match(cell):
                    dot += 1
        return "," if comma > dot else "."

    @staticmethod
    def _split(line: str, separator: str) -> list[str]:
        if separator == " ":
            return line.split()
        return next(csv.reader([line], delimiter=separator))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def parse(self, text: str, dialect: CsvDialect) -> TabularData:
        """Parse CSV text into a raw :class:`TabularData`."""
        lines = self._data_lines(text)
        if dialect.separator == " ":
            rows = [line.split() for line in lines]
        else:
            rows = [row for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=dialect.separator)]
        rows = [[cell.strip() for cell in row] for row in rows]
        table = TabularData()
        if dialect.has_header and rows:
            table.headers = rows[0]
            rows = rows[1:]
        table.rows = rows
        return table

    def read_file(self, path: PathLike, dialect: Optional[CsvDialect] = None) -> tuple[TabularData, CsvDialect]:
        """Read and parse a CSV file, detecting the dialect if not given."""
        text, encoding = self.load_text(path, dialect.encoding if dialect else None)
        if dialect is None:
            dialect = self.detect_dialect(text, encoding)
        logger.info("Reading CSV %s with %s", path, dialect)
        return self.parse(text, dialect), dialect

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def generate(self, motor: Motor, options: CsvExportOptions) -> str:
        """Generate CSV text for the motor thrust curve."""
        if options.separator == options.decimal_separator:
            raise ValueError("The field separator and the decimal separator must differ.")
        buffer = io.StringIO()
        if options.include_metadata:
            for line in self._metadata_lines(motor):
                buffer.write(f"{COMMENT_PREFIX} {line}\n")
        writer = csv.writer(buffer, delimiter=options.separator, lineterminator="\n")
        writer.writerow([f"Time ({options.time_unit})", f"Thrust ({options.thrust_unit})"])
        for point in motor.points:
            writer.writerow(
                [
                    self._format(from_reference(point.time_s, options.time_unit), options),
                    self._format(from_reference(point.thrust_n, options.thrust_unit), options),
                ]
            )
        return buffer.getvalue()

    def write_file(self, path: PathLike, motor: Motor, options: CsvExportOptions) -> None:
        """Generate and atomically write the CSV file."""
        atomic_write_text(path, self.generate(motor, options), encoding=options.encoding, newline="\r\n")
        logger.info("CSV file written: %s", path)

    @staticmethod
    def _format(value: float, options: CsvExportOptions) -> str:
        text = format_number(value, options.max_decimals)
        return text.replace(".", options.decimal_separator)

    @staticmethod
    def _metadata_lines(motor: Motor) -> list[str]:
        meta = motor.metadata

        def fmt(value: Optional[float], unit: str) -> str:
            return f"{format_number(value, 4)} {unit}" if value is not None else ""

        return [
            f"Motor name: {meta.name}",
            f"Manufacturer: {meta.manufacturer}",
            f"Designation: {meta.designation}",
            f"Diameter: {fmt(meta.diameter_mm, 'mm')}",
            f"Length: {fmt(meta.length_mm, 'mm')}",
            f"Delays: {meta.delays}",
            f"Propellant mass: {fmt(meta.propellant_mass_g, 'g')}",
            f"Total mass: {fmt(meta.total_mass_g, 'g')}",
            f"Propellant type: {meta.propellant_type}",
        ]
