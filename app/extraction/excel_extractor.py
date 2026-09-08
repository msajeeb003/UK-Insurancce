"""
Excel extraction for credit-limit schedules (BRD 2.2 / 2.6).

Around 90% of buyer credit limits arrive as a separate schedule, and
insurers send BOTH Excel generations: modern `.xlsx` (zip-based, read with
openpyxl) and legacy `.xls` (OLE2 binary, read with xlrd) — a real Zurich
pre-check schedule from the pilot arrived as `.xls`. The format is decided
by MAGIC BYTES, not the filename, so a mislabeled file still routes to the
right reader.

Each worksheet becomes one "page" (1-based, workbook order) so the
source-link contract is identical to PDFs: a value's `page` is the
worksheet number it came from. Rows are rendered pipe-separated, keeping
the row/column structure explicit for the LLM the same way Azure's and
Docling's rebuilt grids do for scans.
"""

import io
import logging

import openpyxl
import xlrd

from app.core.errors import InvalidDocumentError
from app.extraction.base import PageText, clean_text

logger = logging.getLogger(__name__)

# Guard rails: schedules are small; anything bigger is almost certainly the
# wrong file, and unbounded sheets would blow up the LLM prompt.
MAX_SHEETS = 10
MAX_ROWS_PER_SHEET = 300
MAX_COLS = 30

_XLSX_MAGIC = b"PK\x03\x04"          # zip container (xlsx/xlsm)
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"     # OLE2 compound file (legacy xls)


def _cell_text(value) -> str:
    if value is None:
        return ""
    # Legacy .xls numbers arrive as floats; render 150000.0 as "150000".
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _pages_from_sheets(sheets: list[tuple[str, list[list[str]]]]) -> list[PageText]:
    """Shared assembly: (title, rows-of-cell-text) per sheet -> PageText."""
    if not sheets:
        raise InvalidDocumentError("Excel workbook contains no worksheets.")
    if len(sheets) > MAX_SHEETS:
        raise InvalidDocumentError(
            f"Excel workbook has {len(sheets)} worksheets — the limit is "
            f"{MAX_SHEETS}. Credit-limit schedules are small documents."
        )
    pages: list[PageText] = []
    for index, (title, rows) in enumerate(sheets, start=1):
        lines = [f"[WORKSHEET: {title}]"]
        truncated = False
        for row_no, cells in enumerate(rows, start=1):
            if row_no > MAX_ROWS_PER_SHEET:
                truncated = True
                break
            if any(cells):
                lines.append(" | ".join(cells).rstrip(" |"))
        if truncated:
            lines.append(f"[TRUNCATED after {MAX_ROWS_PER_SHEET} rows]")
        pages.append(PageText(page_number=index, text=clean_text("\n".join(lines))))
    return pages


def _extract_xlsx(xlsx_bytes: bytes) -> list[PageText]:
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(xlsx_bytes), read_only=True, data_only=True
        )
    except Exception as exc:
        logger.info("openpyxl open failed: %s", exc)
        raise InvalidDocumentError(
            "File could not be opened as an Excel (.xlsx) workbook."
        ) from exc
    try:
        sheets = [
            (
                sheet.title,
                [
                    [_cell_text(cell) for cell in row]
                    for row in sheet.iter_rows(max_col=MAX_COLS, values_only=True)
                ],
            )
            for sheet in workbook.worksheets
        ]
    finally:
        workbook.close()
    return _pages_from_sheets(sheets)


def _xls_cell(sheet, book, row: int, col: int) -> str:
    value = sheet.cell_value(row, col)
    cell_type = sheet.cell_type(row, col)
    if cell_type == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(value, book.datemode).date().isoformat()
        except Exception:
            return _cell_text(value)
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if value else "FALSE"
    if cell_type == xlrd.XL_CELL_ERROR:
        return ""
    return _cell_text(value)


def _extract_xls(xls_bytes: bytes) -> list[PageText]:
    """Legacy OLE2 .xls via xlrd — real insurer schedules still arrive this way."""
    try:
        book = xlrd.open_workbook(file_contents=xls_bytes)
    except Exception as exc:
        logger.info("xlrd open failed: %s", exc)
        raise InvalidDocumentError(
            "File could not be opened as a legacy Excel (.xls) workbook — it "
            "may be corrupt, password-protected, or not a real Excel file."
        ) from exc
    sheets = []
    for sheet in book.sheets():
        rows = [
            [_xls_cell(sheet, book, r, c) for c in range(min(sheet.ncols, MAX_COLS))]
            for r in range(sheet.nrows)
        ]
        sheets.append((sheet.name, rows))
    return _pages_from_sheets(sheets)


def extract_pages_excel(excel_bytes: bytes) -> list[PageText]:
    """
    Extract every worksheet of an Excel workbook (modern or legacy) as one
    PageText each. Format is sniffed from magic bytes, never the filename.
    """
    if excel_bytes.startswith(_XLS_MAGIC):
        pages = _extract_xls(excel_bytes)
        logger.info("Excel (legacy .xls) extracted %d worksheet(s)", len(pages))
        return pages
    if excel_bytes.startswith(_XLSX_MAGIC):
        pages = _extract_xlsx(excel_bytes)
        logger.info("Excel (.xlsx) extracted %d worksheet(s)", len(pages))
        return pages
    raise InvalidDocumentError(
        "File is not a recognisable Excel workbook (neither .xlsx nor legacy "
        ".xls). If the insurer exported an HTML or CSV table with an .xls "
        "name, re-save it as .xlsx and upload again."
    )
