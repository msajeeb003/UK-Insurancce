"""
Excel extraction for credit-limit schedules (BRD 2.2 / 2.6).

Around 90% of buyer credit limits arrive as a separate schedule, and some
insurers send Excel rather than PDF. Each worksheet becomes one "page"
(1-based, in workbook order) so the source-link contract is identical to
PDFs: a value's `page` is the worksheet number it came from.

Rows are rendered pipe-separated in sheet order, which keeps the row/column
structure explicit for the LLM the same way Azure's rebuilt markdown grids
do for scanned tables.
"""

import io
import logging

import openpyxl

from app.core.errors import InvalidDocumentError
from app.extraction.base import PageText

logger = logging.getLogger(__name__)

# Guard rails: schedules are small; anything bigger is almost certainly the
# wrong file, and unbounded sheets would blow up the LLM prompt.
MAX_SHEETS = 10
MAX_ROWS_PER_SHEET = 300
MAX_COLS = 30


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_pages_excel(xlsx_bytes: bytes) -> list[PageText]:
    """Extract every worksheet of an .xlsx workbook as one PageText each."""
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(xlsx_bytes), read_only=True, data_only=True
        )
    except Exception as exc:
        logger.info("Excel open failed: %s", exc)
        raise InvalidDocumentError(
            "File could not be opened as an Excel (.xlsx) workbook."
        ) from exc

    try:
        sheets = workbook.worksheets
        if not sheets:
            raise InvalidDocumentError("Excel workbook contains no worksheets.")
        if len(sheets) > MAX_SHEETS:
            raise InvalidDocumentError(
                f"Excel workbook has {len(sheets)} worksheets — the limit is "
                f"{MAX_SHEETS}. Credit-limit schedules are small documents."
            )

        pages: list[PageText] = []
        for index, sheet in enumerate(sheets, start=1):
            lines = [f"[WORKSHEET: {sheet.title}]"]
            truncated = False
            for row_no, row in enumerate(
                sheet.iter_rows(max_col=MAX_COLS, values_only=True), start=1
            ):
                if row_no > MAX_ROWS_PER_SHEET:
                    truncated = True
                    break
                cells = [_cell_text(c) for c in row]
                if any(cells):
                    lines.append(" | ".join(cells).rstrip(" |"))
            if truncated:
                lines.append(
                    f"[TRUNCATED after {MAX_ROWS_PER_SHEET} rows]"
                )
            pages.append(PageText(page_number=index, text="\n".join(lines)))

        logger.info("Excel extracted %d worksheet(s)", len(pages))
        return pages
    finally:
        workbook.close()
