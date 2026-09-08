"""
Pipeline orchestrator: document bytes -> page-tagged text -> LLM ->
sanitized, verified, rule-annotated `ExtractionResponse` (BRD 2.2).

Routing: .pdf -> PyMuPDF, or OCR when scanned (Azure if configured, else
Docling); .xlsx/.xls -> worksheet extractor. FastAPI-free so it can be
unit-tested or reused by a batch worker.
"""

import asyncio
import logging
from typing import Literal

from app.core.config import get_settings
from app.core.errors import InvalidDocumentError
from app.extraction.azure_extractor import extract_pages_azure
from app.extraction.base import PageText, to_tagged_document
from app.extraction.detector import PdfKind, classify_pdf, open_pdf
from app.extraction.docling_extractor import extract_pages_docling
from app.extraction.excel_extractor import extract_pages_excel
from app.extraction.pymupdf_extractor import extract_pages_pymupdf
from app.llm.router import active_model_label, extract_quote_fields
from app.models.schemas import (
    ExtractionResponse,
    ProcessingMeta,
    QuoteExtraction,
    ReviewSummary,
    SetField,
    SetFields,
    sourced_items,
)
from app.services.library import debt_collection_rule
from app.services.verification import verify_extraction

logger = logging.getLogger(__name__)

EngineOverride = Literal["auto", "digital", "azure", "docling"]
FileKind = Literal["pdf", "excel"]


def _sanitize(extraction: QuoteExtraction, page_count: int) -> QuoteExtraction:
    """
    Defensive pass over the LLM output: out-of-range page cites cleared
    (values kept), null values carry no page/confidence, unflagged values
    default to 'high'. Keeps source links and review flags trustworthy.
    """
    for field_name, item in sourced_items(extraction):
        if item.value is None:
            item.page = None
            item.confidence = None
            continue
        if item.page is not None and not (1 <= item.page <= page_count):
            logger.warning("Field %r cited out-of-range page %s — clearing link",
                           field_name, item.page)
            item.page = None
        if item.confidence is None:
            item.confidence = "high"

    for row in extraction.buyer_credit_limits:
        if row.page is not None and not (1 <= row.page <= page_count):
            row.page = None

    return extraction


def _build_review(extraction: QuoteExtraction, unverified: list[str]) -> ReviewSummary:
    """Deterministic review summary — computed server-side, never by the LLM."""
    return ReviewSummary(
        missing_fields=[n for n, i in sourced_items(extraction) if i.value is None],
        uncertain_fields=[n for n, i in sourced_items(extraction)
                          if i.confidence == "uncertain"],
        unverified_fields=unverified,
    )


def _build_set_fields(extraction: QuoteExtraction) -> SetFields:
    """BRD 2.4: debt collection support is SET by the insurer rule
    (backend/config/insurers.json), never extracted."""
    value, matched = debt_collection_rule(extraction.insurer.value)
    return SetFields(
        debt_collection_support=SetField(
            value=value, source="insurer_rule", matched_insurer=matched,
        )
    )


def _scanned_engine(override: EngineOverride) -> str:
    """Scanned routing: explicit override wins; else Azure when configured,
    else the open-source Docling engine."""
    if override in ("azure", "docling"):
        return override
    settings = get_settings()
    if settings.azure_endpoint and settings.azure_key.get_secret_value():
        return "azure"
    return "docling"


async def _extract_pdf_pages(
    pdf_bytes: bytes, engine: EngineOverride
) -> tuple[list[PageText], int, str]:
    doc = open_pdf(pdf_bytes)
    try:
        page_count = doc.page_count
        if engine == "auto":
            scanned = classify_pdf(doc) is PdfKind.SCANNED
        else:
            scanned = engine in ("azure", "docling")

        if not scanned:
            return extract_pages_pymupdf(doc), page_count, "pymupdf"
    finally:
        doc.close()

    # Blocking OCR calls -> worker thread keeps the event loop free.
    if _scanned_engine(engine) == "azure":
        pages = await asyncio.to_thread(extract_pages_azure, pdf_bytes)
        return pages, page_count, "azure_document_intelligence"
    pages = await asyncio.to_thread(extract_pages_docling, pdf_bytes)
    return pages, page_count, "docling"


async def run_extraction_pipeline(
    file_bytes: bytes,
    filename: str,
    engine: EngineOverride = "auto",
    file_kind: FileKind = "pdf",
) -> ExtractionResponse:
    """Full extraction flow for one uploaded document. Raises
    `PipelineError` subclasses; the API layer maps them to HTTP."""
    if file_kind == "excel":
        pages = await asyncio.to_thread(extract_pages_excel, file_bytes)
        page_count, engine_used = len(pages), "excel"
    else:
        pages, page_count, engine_used = await _extract_pdf_pages(file_bytes, engine)

    if not any(page.text.strip() for page in pages):
        raise InvalidDocumentError(
            f"No text could be extracted from this document with the "
            f"'{engine_used}' engine."
        )

    extraction = await asyncio.to_thread(
        extract_quote_fields, to_tagged_document(pages)
    )

    extraction = _sanitize(extraction, page_count)
    unverified = verify_extraction(extraction, pages)

    return ExtractionResponse(
        meta=ProcessingMeta(
            filename=filename,
            page_count=page_count,
            extraction_engine=engine_used,
            llm_model=active_model_label(),
        ),
        review=_build_review(extraction, unverified),
        set_fields=_build_set_fields(extraction),
        data=extraction,
    )
