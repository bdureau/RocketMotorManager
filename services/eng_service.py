"""Reader and writer for the RASP ``.eng`` thrust curve format.

Format (as used by OpenRocket, RockSim and thrustcurve.org)::

    ; comment lines start with a semicolon
    C6 18 70 3-5-7 0.0108 0.0231 Estes
       0.031 0.946
       ...
       1.860 0.000

Header tokens, separated by whitespace:

1. motor name (no spaces)
2. diameter in millimetres
3. length in millimetres
4. ejection delays separated by ``-`` (``P`` = plugged, ``0`` = none)
5. propellant mass in kilograms
6. total loaded mass in kilograms
7. manufacturer (no spaces)

Then one ``time thrust`` pair per line (s, N), in strictly increasing time
order, the curve ending with a zero thrust point. The point (0, 0) is
implicit. A file may contain several motors one after another.
"""

from __future__ import annotations

import logging
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from models.errors import FileFormatError, ValidationError
from models.motor import Motor
from models.motor_metadata import MotorMetadata
from models.thrust_point import ThrustPoint
from models.validation import ValidationReport, validate_motor
from services.file_utils import PathLike, atomic_write_text, format_number, read_text

logger = logging.getLogger(__name__)

HEADER_TOKEN_COUNT = 7
ENG_LINE_ENDING = "\r\n"


@dataclass
class EngReadResult:
    """Result of reading an ENG file: one or more motors and the
    non-fatal problems found while reading."""

    motors: list[Motor] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class EngService:
    """Parse and generate ENG files."""

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def read_file(self, path: PathLike) -> EngReadResult:
        """Read an ENG file from disk.

        Raises:
            FileAccessError: If the file cannot be read.
            FileFormatError: With the exact line number when invalid.
        """
        text, encoding = read_text(path)
        logger.info("Reading ENG file %s (encoding %s)", path, encoding)
        try:
            result = self.parse(text)
        except FileFormatError as exc:
            exc.file_path = str(path)
            raise
        for motor in result.motors:
            motor.metadata.source_file = str(path)
        return result

    def parse(self, text: str) -> EngReadResult:
        """Parse ENG content (one or several motors)."""
        result = EngReadResult()
        pending_comments: list[str] = []
        current: Optional[Motor] = None
        for number, raw in enumerate(text.splitlines(), start=1):
            content, comment = self._split_comment(raw)
            if comment is not None and not content:
                target = pending_comments if current is None or current.points else current.metadata.eng_comments
                target.append(comment)
                continue
            if not content:
                continue
            tokens = content.split()
            if self._is_header(tokens):
                if current is not None:
                    self._finish_motor(current, result, number)
                current = self._parse_header(tokens, number, raw)
                current.metadata.eng_comments = pending_comments
                pending_comments = []
                continue
            if current is None:
                raise FileFormatError("Data found before the motor header line.", line_number=number, line_content=raw)
            current.points.append(self._parse_point(tokens, number, raw))
        if current is None:
            raise FileFormatError("No motor header found: this is not a valid ENG file.")
        current.metadata.eng_comments.extend(pending_comments)  # trailing comments are kept
        self._finish_motor(current, result, None)
        return result

    @staticmethod
    def _split_comment(raw: str) -> tuple[str, Optional[str]]:
        """Split a line into its content and its ``;`` comment."""
        if ";" not in raw:
            return raw.strip(), None
        content, comment = raw.split(";", 1)
        return content.strip(), comment.strip()

    @staticmethod
    def _is_header(tokens: Sequence[str]) -> bool:
        """A header has at least 7 tokens and does not start with a number."""
        if len(tokens) < HEADER_TOKEN_COUNT:
            return False
        try:
            float(tokens[0])
            return False
        except ValueError:
            return True

    def _parse_header(self, tokens: Sequence[str], number: int, raw: str) -> Motor:
        """Build a :class:`Motor` from the header tokens."""
        name, diameter, length, delays, prop_kg, total_kg = tokens[:6]
        manufacturer = " ".join(tokens[6:])
        meta = MotorMetadata(
            name=name,
            manufacturer=manufacturer,
            designation=name,
            diameter_mm=self._header_number(diameter, "diameter", number, raw),
            length_mm=self._header_number(length, "length", number, raw),
            delays=delays,
            propellant_mass_g=self._header_number(prop_kg, "propellant mass", number, raw) * 1000.0,
            declared_total_mass_g=self._header_number(total_kg, "total mass", number, raw) * 1000.0,
        )
        return Motor(metadata=meta)

    @staticmethod
    def _header_number(token: str, caption: str, number: int, raw: str) -> float:
        try:
            value = float(token)
        except ValueError as exc:
            raise FileFormatError(f"Invalid {caption} '{token}' in header.", line_number=number, line_content=raw) from exc
        if not math.isfinite(value) or value < 0:
            raise FileFormatError(f"Invalid {caption} '{token}' in header.", line_number=number, line_content=raw)
        return value

    @staticmethod
    def _parse_point(tokens: Sequence[str], number: int, raw: str) -> ThrustPoint:
        """Parse a ``time thrust`` line."""
        if len(tokens) != 2:
            raise FileFormatError(
                f"Expected two values (time thrust), found {len(tokens)}.", line_number=number, line_content=raw
            )
        try:
            time_s, thrust_n = float(tokens[0]), float(tokens[1])
        except ValueError as exc:
            raise FileFormatError("Non-numeric thrust data.", line_number=number, line_content=raw) from exc
        if not (math.isfinite(time_s) and math.isfinite(thrust_n)):
            raise FileFormatError("Non-finite thrust data.", line_number=number, line_content=raw)
        if time_s < 0:
            raise FileFormatError("Negative time value.", line_number=number, line_content=raw)
        return ThrustPoint(time_s, thrust_n)

    @staticmethod
    def _finish_motor(motor: Motor, result: EngReadResult, next_line: Optional[int]) -> None:
        """Validate a completed motor block and add it to the result."""
        name = motor.metadata.name
        if not motor.points:
            where = f" before line {next_line}" if next_line else ""
            raise FileFormatError(f"Motor '{name}' has no thrust data{where}.")
        if not motor.is_chronological():
            result.warnings.append(f"Motor '{name}': thrust points are not in increasing time order.")
        if motor.points[-1].thrust_n != 0.0:
            result.warnings.append(f"Motor '{name}': the curve does not end with a zero thrust point.")
        result.motors.append(motor)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def validate_for_export(self, motor: Motor) -> ValidationReport:
        """Return the validation report used before export."""
        return validate_motor(motor)

    def generate(self, motors: Iterable[Motor], allow_warnings: bool = True, header_comment: str = "") -> str:
        """Generate ENG text for one or several motors.

        Raises:
            ValidationError: If a motor has blocking errors, or warnings
                while ``allow_warnings`` is False.
        """
        blocks: list[str] = []
        for motor in motors:
            report = self.validate_for_export(motor)
            if not report.is_valid:
                raise ValidationError(
                    f"Motor '{motor.metadata.name or '?'}' cannot be exported to ENG:\n{report.summary()}"
                )
            if report.warnings and not allow_warnings:
                raise ValidationError(f"Export cancelled because of warnings:\n{report.summary()}")
            blocks.append(self._motor_block(motor, header_comment))
        if not blocks:
            raise ValidationError("No motor to export.")
        return ENG_LINE_ENDING.join(blocks) + ENG_LINE_ENDING

    def write_file(self, path: PathLike, motors: Iterable[Motor], allow_warnings: bool = True, header_comment: str = "") -> None:
        """Generate and atomically write an ENG file (ASCII, CRLF)."""
        text = self.generate(motors, allow_warnings, header_comment)
        atomic_write_text(path, text, encoding="ascii", newline="\n")
        logger.info("ENG file written: %s", path)

    def _motor_block(self, motor: Motor, header_comment: str) -> str:
        meta = motor.metadata
        lines = [f"; {_ascii(comment)}" if comment else ";" for comment in meta.eng_comments]
        if header_comment:
            lines.append(f"; {_ascii(header_comment)}")
        header = " ".join(
            [
                _token(meta.name),
                format_number(meta.diameter_mm or 0.0, 3),
                format_number(meta.length_mm or 0.0, 3),
                _token(meta.delays.strip() or "0"),
                format_number((meta.propellant_mass_g or 0.0) / 1000.0, 6),
                format_number((meta.total_mass_g or 0.0) / 1000.0, 6),
                _token(meta.manufacturer),
            ]
        )
        lines.append(header)
        for index, point in enumerate(motor.points):
            if index == 0 and point.time_s == 0.0 and point.thrust_n == 0.0:
                continue  # (0, 0) is implicit in the ENG format
            lines.append(f"   {format_number(point.time_s, 6)} {format_number(point.thrust_n, 6)}")
        return ENG_LINE_ENDING.join(lines)


def _ascii(text: str) -> str:
    """Transliterate text to printable ASCII (ENG files are ASCII)."""
    normalized = unicodedata.normalize("NFKD", text)
    cleaned = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch if ch.isprintable() else " " for ch in cleaned)


def _token(text: str) -> str:
    """Make a single whitespace-free ASCII token for the header."""
    token = "_".join(_ascii(text).split())
    return token.replace(";", "_") or "Unknown"
