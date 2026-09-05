"""
Pipeline orchestrator: PDF bytes -> classified -> text w/ page tags -> LLM
-> validated `ExtractionResponse`.

Kept free of FastAPI imports so it can be unit-tested (and later reused by
a batch worker) without spinning up the web layer.
"""

import asyncio
import logging
from typing import Literal

from app.core.config import get_settings
from app.core.errors import InvalidDocumentError
from app.extraction.azure_extractor import extract_pages_azure
from app.extraction.base import PageText, to_tagged_document
from app.extraction.detector import PdfKind, classify_pdf, open_pdf
from app.extraction.pymupdf_extractor import extract_pages_pymupdf
from app.llm.openai_extractor import extract_quote_fields
from app.models.schemas import (
    ExtractionResponse,
    ProcessingMeta,
    QuoteExtraction,
    ReviewSummary,
    SourcedValue,
)

logger = logging.getLogger(__name__)

EngineOverride = Literal["auto", "digital", "azure"]


def _sourced_fields(extraction: QuoteExtraction) -> list[tuple[str, SourcedValue]]:
    """(field_name, SourcedValue) pairs, in schema order."""
    return [
        (name, item)
        for name in type(extraction).model_fields
        if isinstance(item := getattr(extraction, name), SourcedValue)
    ]


def _sanitize(extraction: QuoteExtraction, page_count: int) -> QuoteExtraction:
    """
    Defensive pass over the LLM output:
    - a cited page outside the document's range is nulled (value kept);
    - a null value must not carry a page or a confidence;
    - a non-null value with no confidence defaults to 'high' (unflagged).
    Structured Outputs makes schema violations impossible, but semantic
    slips (hallucinated pages, inconsistent confidence) are still possible —
    this keeps source links and review flags trustworthy for the broker UI.
    """
    for field_name, item in _sourced_fields(extraction):
        if item.value is None:
            item.page = None
            item.confidence = None
            continue
        if item.page is not None and not (1 <= item.page <= page_count):
            logger.warning(
                "Field %r cited out-of-range page %s (doc has %d pages) — "
                "clearing page link", field_name, item.page, page_count,
            )
            item.page = None
        if item.confidence is None:
            item.confidence = "high"

    for row in extraction.buyer_credit_limits:
        if row.page is not None and not (1 <= row.page <= page_count):
            row.page = None

    return extraction


def _build_review(extraction: QuoteExtraction) -> ReviewSummary:
    """
    Deterministic review summary for the UI / presentation gate — computed
    from the sanitized extraction, never asked of the LLM.
    """
    missing = [name for name, item in _sourced_fields(extraction) if item.value is None]
    uncertain = [
        name for name, item in _sourced_fields(extraction)
        if item.confidence == "uncertain"
    ]
    return ReviewSummary(missing_fields=missing, uncertain_fields=uncertain)


async def run_extraction_pipeline(
    pdf_bytes: bytes,
    filename: str,
    engine: EngineOverride = "auto",
) -> ExtractionResponse:
    """
    Full extraction flow for one uploaded PDF.

    `engine`:
      - "auto"    detect digital vs scanned (default)
      - "digital" force PyMuPDF
      - "azure"   force Azure DI (e.g. digital PDFs with brutal tables)

    Raises `PipelineError` subclasses; the API layer maps them to HTTP.
    """
    settings = get_settings()

    # ── 1. Open + route ──────────────────────────────────────────────────
    doc = open_pdf(pdf_bytes)  # raises InvalidDocumentError on bad input
    try:
        page_count = doc.page_count

        if engine == "auto":
            use_azure = classify_pdf(doc) is PdfKind.SCANNED
        else:
            use_azure = engine == "azure"

        # ── 2. Extract page-tagged text ──────────────────────────────────
        if use_azure:
            # Blocking Azure poller -> worker thread keeps the event loop free.
            pages: list[PageText] = await asyncio.to_thread(
                extract_pages_azure, pdf_bytes
            )
            engine_used = "azure_document_intelligence"
        else:
            pages = extract_pages_pymupdf(doc)
            engine_used = "pymupdf"
    finally:
        doc.close()

    if not any(page.text.strip() for page in pages):
        raise InvalidDocumentError(
            f"No text could be extracted from this PDF with the "
            f"'{engine_used}' engine."
        )
    tagged_text = to_tagged_document(pages)

    # ── 3. LLM structured extraction (blocking SDK call -> thread) ───────
    extraction = await asyncio.to_thread(extract_quote_fields, tagged_text)

    # ── 4. Defensive validation + review summary ─────────────────────────
    extraction = _sanitize(extraction, page_count)

    return ExtractionResponse(
        meta=ProcessingMeta(
            filename=filename,
            page_count=page_count,
            extraction_engine=engine_used,
            llm_model=settings.openai_model,
        ),
        review=_build_review(extraction),
        data=extraction,
    )
