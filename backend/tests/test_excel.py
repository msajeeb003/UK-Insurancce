"""Excel credit-limit schedule extraction (BRD 2.2/2.6)."""

import pytest

from app.core.errors import InvalidDocumentError
from app.extraction.base import to_tagged_document
from app.extraction.excel_extractor import extract_pages_excel
from tests.conftest import make_xls, make_xlsx


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


def test_legacy_xls_extracts_like_a_zurich_precheck():
    """Modelled on the real .xls that failed in the pilot UI."""
    data = make_xls({
        "Tabelle1": [
            ["", "Applicant:", "DCS Networks Ltd"],
            ["Serial No.", "Customer", "Co. Reg. No.",
             "Requested Credit Limit", "Approved Credit Limit"],
            [1, "On Tower UK Ltd", "3196207", 1000, 1000],
            [2, "United Infrastructure Ltd", "8075989", 2000, 1500],
        ],
    })
    assert data.startswith(b"\xd0\xcf\x11\xe0")  # genuinely OLE2
    pages = extract_pages_excel(data)
    assert [p.page_number for p in pages] == [1]
    text = pages[0].text
    assert "[WORKSHEET: Tabelle1]" in text
    # Numbers render as integers, not "1000.0".
    assert "2 | United Infrastructure Ltd | 8075989 | 2000 | 1500" in text
    assert "1000.0" not in text


def test_format_is_sniffed_not_trusted_from_filename():
    """An .xlsx byte stream still parses even if someone names it .xls —
    the extractor never sees filenames, only magic bytes."""
    data = make_xlsx({"S": [["Buyer Name"], ["Example Ltd"]]})
    pages = extract_pages_excel(data)
    assert "Example Ltd" in pages[0].text


def test_garbage_bytes_rejected():
    with pytest.raises(InvalidDocumentError, match="not a recognisable Excel"):
        extract_pages_excel(b"this is not a workbook")


def test_corrupt_ole2_rejected_with_clear_message():
    with pytest.raises(InvalidDocumentError, match="legacy Excel"):
        extract_pages_excel(b"\xd0\xcf\x11\xe0" + b"\x00" * 64)


def test_row_cap_truncates_with_marker():
    data = make_xlsx({"Big": [["row", i] for i in range(400)]})
    pages = extract_pages_excel(data)
    assert "[TRUNCATED after 300 rows]" in pages[0].text
