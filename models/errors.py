"""Exception hierarchy used across the application.

Every error raised intentionally by the business layer derives from
:class:`RocketMotorError` so that the UI can catch a single base class and
display a clear message, while unexpected exceptions are routed to the
global error handler.
"""

from __future__ import annotations

from localization import _

from typing import Optional


class RocketMotorError(Exception):
    """Base class of all application-specific errors."""


class FileFormatError(RocketMotorError):
    """A file could not be parsed because its content is invalid.

    Attributes:
        file_path: Path of the offending file, when known.
        line_number: 1-based line number of the error, when known.
        line_content: Raw content of the offending line, when known.
    """

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        line_content: Optional[str] = None,
    ) -> None:
        self.file_path = file_path
        self.line_number = line_number
        self.line_content = line_content
        self.base_message = message
        super().__init__(self._compose())

    def _compose(self) -> str:
        parts = []
        if self.line_number is not None:
            parts.append(_("Line {line}: {message}").format(line=self.line_number, message=self.base_message))
        else:
            parts.append(self.base_message)
        if self.line_content is not None:
            parts.append(f'  -> "{self.line_content.strip()}"')
        return "\n".join(parts)


class FileAccessError(RocketMotorError):
    """A file could not be read or written (permissions, missing, locked)."""


class ValidationError(RocketMotorError):
    """Data does not satisfy the constraints required by an operation."""


class CalibrationError(RocketMotorError):
    """The digitizer calibration is missing or mathematically degenerate."""
