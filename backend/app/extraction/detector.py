"""
Digital-vs-scanned routing.

Strategy: open the PDF with PyMuPDF and count extractable characters per
page. Scanned pages (pure images) yield little or no text; digital pages
yield plenty. If enough pages look scanned, the whole document is routed to
Azure AI Document Intelligence for OCR. This is cheap (milliseconds) and
runs on every upload before any paid API is called.
"""

import logging
from enum import Enum

import pymupdf

from app.core.config import get_settings
from app.core.errors import InvalidDocumentError

logger = logging.getLogger(__name__)


class PdfKind(str, Enum):
    DIGITAL = "digital"
    SCANNED = "scanned"


def open_pdf(pdf_bytes: bytes) -> pymupdf.Document:
    """Open PDF bytes with PyMuPDF, raising InvalidDocumentError on bad input."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pymupdf raises generic exceptions on bad input
        logger.info("PDF open failed: %s", exc)
        raise InvalidDocumentError("File could not be opened as a PDF.") from exc

    settings = get_settings()
    if doc.page_count == 0:
        doc.close()
        raise InvalidDocumentError("PDF contains no pages.")
    if doc.needs_pass:
        doc.close()
        raise InvalidDocumentError("PDF is password-protected and cannot be processed.")
    if doc.page_count > settings.max_pdf_pages:
        pages = doc.page_count
        doc.close()
        raise InvalidDocumentError(
            f"PDF has {pages} pages — the limit is {settings.max_pdf_pages}. "
            "Insurer quotes are short documents; please upload the quote only."
        )
    return doc


def classify_pdf(doc: pymupdf.Document) -> PdfKind:
    """
    Classify an open PDF as DIGITAL (usable text layer) or SCANNED
    (needs OCR via Azure).
    """
    settings = get_settings()

    scanned_pages = 0
    for page in doc:
        char_count = len(page.get_text("text").strip())
        if char_count < settings.digital_min_chars_per_page:
            scanned_pages += 1

    ratio = scanned_pages / doc.page_count
    kind = PdfKind.SCANNED if ratio >= settings.scanned_page_ratio else PdfKind.DIGITAL
    logger.info(
        "PDF classification: %d/%d low-text pages (ratio %.2f) -> %s",
        scanned_pages, doc.page_count, ratio, kind.value,
    )
    return kind
