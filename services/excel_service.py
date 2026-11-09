"""Excel import (.xlsx via OpenPyXL, .xls via xlrd), using Pandas.

OpenPyXL cannot read the legacy binary ``.xls`` format, so the engine is
chosen from the file extension.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd

from models.errors import FileAccessError, FileFormatError
from services.file_utils import PathLike
from services.tabular_data import TabularData, looks_like_header

logger = logging.getLogger(__name__)

ENGINES = {".xlsx": "openpyxl", ".xlsm": "openpyxl", ".xls": "xlrd"}
PREVIEW_ROW_LIMIT = 100000


class ExcelService:
    """List sheets and read cell grids from Excel workbooks."""

    @staticmethod
    def engine_for(path: PathLike) -> str:
        """Return the Pandas engine for the file extension.

        Raises:
            FileFormatError: If the extension is not supported.
        """
        suffix = Path(path).suffix.lower()
        if suffix not in ENGINES:
            raise FileFormatError(f"Unsupported Excel file type '{suffix}'. Use .xlsx or .xls.")
        return ENGINES[suffix]

    def list_sheets(self, path: PathLike) -> list[str]:
        """Return the worksheet names of a workbook."""
        engine = self.engine_for(path)
        try:
            with pd.ExcelFile(path, engine=engine) as workbook:
                return [str(name) for name in workbook.sheet_names]
        except FileNotFoundError as exc:
            raise FileAccessError(f"File not found: {path}") from exc
        except PermissionError as exc:
            raise FileAccessError(f"Permission denied (is the file open in Excel?): {path}") from exc
        except ImportError as exc:
            raise FileAccessError(f"Missing library to read this file: {exc}") from exc
        except Exception as exc:  # corrupted workbook: library-specific errors
            raise FileFormatError(f"Cannot open workbook '{path}': {exc}") from exc

    def read_sheet(self, path: PathLike, sheet: str, header: str = "auto") -> TabularData:
        """Read a worksheet as raw cells.

        Args:
            header: ``"auto"`` (detect), ``"yes"`` or ``"no"``.
        """
        engine = self.engine_for(path)
        try:
            frame = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object, engine=engine,
                                  nrows=PREVIEW_ROW_LIMIT)
        except FileNotFoundError as exc:
            raise FileAccessError(f"File not found: {path}") from exc
        except PermissionError as exc:
            raise FileAccessError(f"Permission denied (is the file open in Excel?): {path}") from exc
        except Exception as exc:
            raise FileFormatError(f"Cannot read sheet '{sheet}' of '{path}': {exc}") from exc
        rows = [[self._clean(value) for value in row] for row in frame.itertuples(index=False, name=None)]
        rows = self._trim(rows)
        logger.info("Read %d rows from sheet '%s' of %s", len(rows), sheet, path)
        table = TabularData()
        use_header = header == "yes" or (header == "auto" and rows and looks_like_header(rows[0]))
        if use_header and rows:
            table.headers = ["" if cell is None else str(cell) for cell in rows[0]]
            rows = rows[1:]
        table.rows = rows
        return table

    @staticmethod
    def _clean(value: Any) -> Any:
        """Normalise empty cells (NaN, NaT, empty strings) to None."""
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if value is pd.NaT:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if hasattr(value, "item"):  # numpy scalar
            return value.item()
        return value

    @staticmethod
    def _trim(rows: list[list[Any]]) -> list[list[Any]]:
        """Remove fully empty leading/trailing rows and trailing columns."""
        rows = [row for row in rows]
        while rows and all(cell is None for cell in rows[-1]):
            rows.pop()
        while rows and all(cell is None for cell in rows[0]):
            rows.pop(0)
        width = max((max((i + 1 for i, c in enumerate(row) if c is not None), default=0) for row in rows), default=0)
        return [row[:width] for row in rows]
