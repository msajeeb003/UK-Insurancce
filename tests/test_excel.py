"""Excel credit-limit schedule extraction (BRD 2.2/2.6)."""

import pytest

from app.core.errors import InvalidDocumentError
from app.extraction.base import to_tagged_document
from app.extraction.excel_extractor import extract_pages_excel
from tests.conftest import make_xlsx


def test_worksheets_become_pages(limits_xlsx):
    pages = extract_pages_excel(limits_xlsx)
    assert [p.page_number for p in pages] == [1]
    text = pages[0].text
    assert "[WORKSHEET: Limits]" in text
    # Rows keep their column structure and header wordings.
    assert "Buyer Name | Company registration number | Application Amount | Amount Agreed" in text
    assert "Example Ltd | 01234567 | 250000 | 200000" in text


def test_multi_sheet_numbering_matches_source_links():
    data = make_xlsx({
        "Cover": [["Credit Limit Schedule"]],
        "Buyers": [["Buyer Name"], ["Example Ltd"]],
    })
    pages = extract_pages_excel(data)
    assert [p.page_number for p in pages] == [1, 2]
    tagged = to_tagged_document(pages)
    assert "=== PAGE 2 ===" in tagged
    assert tagged.index("=== PAGE 2 ===") < tagged.index("Example Ltd")


def test_garbage_bytes_rejected():
    with pytest.raises(InvalidDocumentError):
        extract_pages_excel(b"this is not a workbook")


def test_row_cap_truncates_with_marker():
    data = make_xlsx({"Big": [["row", i] for i in range(400)]})
    pages = extract_pages_excel(data)
    assert "[TRUNCATED after 300 rows]" in pages[0].text
