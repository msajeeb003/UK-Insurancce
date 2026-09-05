"""Digital-vs-scanned routing and PDF validation guards."""

import pytest

from app.core.errors import InvalidDocumentError
from app.extraction.detector import PdfKind, classify_pdf, open_pdf
from tests.conftest import DIGITAL_PAGE, make_pdf


def test_text_rich_pdf_is_digital(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        assert classify_pdf(doc) is PdfKind.DIGITAL
    finally:
        doc.close()


def test_sparse_pdf_is_scanned(sparse_pdf):
    doc = open_pdf(sparse_pdf)
    try:
        assert classify_pdf(doc) is PdfKind.SCANNED
    finally:
        doc.close()


def test_mixed_pdf_routes_by_ratio():
    # 1 sparse page out of 4 (25%) is below the 40% threshold -> digital.
    doc = open_pdf(make_pdf([DIGITAL_PAGE, DIGITAL_PAGE, DIGITAL_PAGE, ["stamp"]]))
    try:
        assert classify_pdf(doc) is PdfKind.DIGITAL
    finally:
        doc.close()


def test_garbage_bytes_rejected():
    with pytest.raises(InvalidDocumentError):
        open_pdf(b"this is not a pdf")


def test_page_limit_enforced(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.get_settings(), "max_pdf_pages", 2)
    with pytest.raises(InvalidDocumentError, match="limit is 2"):
        open_pdf(make_pdf([DIGITAL_PAGE] * 3))
