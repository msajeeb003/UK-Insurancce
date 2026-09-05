"""Pipeline internals: text extraction shape and the source-link sanitizer."""

from app.extraction.base import to_tagged_document
from app.extraction.detector import open_pdf
from app.extraction.pymupdf_extractor import extract_pages_pymupdf
from app.services.pipeline import _build_review, _sanitize


def test_pymupdf_extraction_and_page_tags(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        pages = extract_pages_pymupdf(doc)
    finally:
        doc.close()

    assert [p.page_number for p in pages] == [1, 2]
    assert "Insurable Turnover" in pages[0].text

    tagged = to_tagged_document(pages)
    assert "=== PAGE 1 ===" in tagged
    assert "=== PAGE 2 ===" in tagged
    # Page markers must precede their page's content.
    assert tagged.index("=== PAGE 1 ===") < tagged.index("Insurable Turnover")


def test_sanitize_clears_bad_page_links(sample_extraction):
    out = _sanitize(sample_extraction, page_count=2)

    # A null value must not carry a page (or confidence).
    assert out.estimated_annual_premium_exc_ipt.page is None
    assert out.estimated_annual_premium_exc_ipt.confidence is None
    # An out-of-range citation loses the page but keeps the value.
    assert out.indemnity.value == "90%"
    assert out.indemnity.page is None
    # Valid citations are untouched.
    assert out.excess.page == 2
    assert out.insurer.page == 1
    # A non-null value with no confidence flag defaults to 'high'.
    assert out.excess.confidence == "high"
    # An explicit 'uncertain' flag survives sanitization.
    assert out.discretionary_limit.confidence == "uncertain"
    # Buyer rows get the same treatment.
    assert out.buyer_credit_limits[0].page is None
    assert out.buyer_credit_limits[0].limit_offered == "GBP 200,000"


def test_review_summary_lists_missing_and_uncertain(sample_extraction):
    out = _sanitize(sample_extraction, page_count=2)
    review = _build_review(out)

    assert "estimated_annual_premium_exc_ipt" in review.missing_fields
    assert "special_conditions" in review.missing_fields
    assert "insurer" not in review.missing_fields

    assert set(review.uncertain_fields) == {"discretionary_limit", "exclusions"}
