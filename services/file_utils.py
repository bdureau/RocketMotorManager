"""Low-level file helpers shared by every service.

* Text reading with automatic encoding detection.
* Atomic writes (temporary file + rename) so that an interrupted save
  never corrupts an existing file.
* Translation of OS errors into :class:`FileAccessError`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, Union

from models.errors import FileAccessError

PathLike = Union[str, os.PathLike]

#: Encodings tried in order when reading text files.
COMMON_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def read_bytes(path: PathLike) -> bytes:
    """Read a whole file as bytes, mapping OS errors to FileAccessError."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError as exc:
        raise FileAccessError(f"File not found: {path}") from exc
    except PermissionError as exc:
        raise FileAccessError(f"Permission denied while reading: {path}") from exc
    except OSError as exc:
        raise FileAccessError(f"Cannot read '{path}': {exc.strerror or exc}") from exc


def decode_text(data: bytes, encodings: Iterable[str] = COMMON_ENCODINGS) -> tuple[str, str]:
    """Decode bytes trying several encodings.

    Returns:
        ``(text, encoding_used)``. ``latin-1`` never fails, so a result is
        always produced.
    """
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


def read_text(path: PathLike, encoding: str | None = None) -> tuple[str, str]:
    """Read a text file; detect the encoding unless one is forced."""
    data = read_bytes(path)
    if encoding:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError) as exc:
            raise FileAccessError(f"Cannot decode '{path}' as {encoding}: {exc}") from exc
    return decode_text(data)


def atomic_write_bytes(path: PathLike, data: bytes) -> None:
    """Write bytes atomically: temporary file in the same folder, then
    ``os.replace``. The original file is untouched if anything fails."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise
    except PermissionError as exc:
        raise FileAccessError(f"Permission denied while writing: {target}") from exc
    except OSError as exc:
        raise FileAccessError(f"Cannot write '{target}': {exc.strerror or exc}") from exc


def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Write text atomically with explicit encoding and line endings."""
    if newline != "\n":
        text = text.replace("\r\n", "\n").replace("\n", newline)
    try:
        data = text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise FileAccessError(f"Some characters cannot be encoded as {encoding}: {exc}") from exc
    atomic_write_bytes(path, data)


def format_number(value: float, max_decimals: int = 6) -> str:
    """Format a float in plain decimal notation (never scientific), with at
    most ``max_decimals`` decimals and no superfluous trailing zeros."""
    text = f"{value:.{max_decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text
