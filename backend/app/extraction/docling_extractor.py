"""
Open-source scanned-PDF OCR via IBM Docling (BRD 2.2) — the zero-cloud-cost
fallback when Azure is not configured. Chosen over Tesseract/EasyOCR/
PaddleOCR because it is the only pip-only option that reconstructs TABLE
STRUCTURE, which buyer credit-limit schedules depend on.

Docling is an OPTIONAL heavy dependency (PyTorch):
    pip install -r requirements-ocr.txt
Imports are lazy so the app runs fine without it; the first conversion
downloads models and is slow.
"""

import io
import logging
from collections import defaultdict
from functools import lru_cache

from app.core.errors import ConfigurationError, InvalidDocumentError
from app.extraction.base import PageText, build_ocr_pages

logger = logging.getLogger(__name__)


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache
def _get_converter():
    """One converter per process — model loading is expensive."""
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ConfigurationError(
            "Scanned-PDF OCR needs either Azure keys (AZURE_ENDPOINT/AZURE_KEY) "
            "or the open-source engine: pip install -r requirements-ocr.txt"
        ) from exc

    options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _table_markdown(table, document) -> str:
    """Version-tolerant table export (the doc argument arrived in 2.x)."""
    try:
        return table.export_to_markdown(doc=document)
    except TypeError:
        return table.export_to_markdown()


def _item_page(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


def extract_pages_docling(pdf_bytes: bytes) -> list[PageText]:
    """Blocking, CPU-heavy call — the pipeline runs it in a worker thread."""
    from docling.datamodel.base_models import DocumentStream

    converter = _get_converter()
    try:
        result = converter.convert(
            DocumentStream(name="upload.pdf", stream=io.BytesIO(pdf_bytes))
        )
        document = result.document
    except Exception as exc:
        logger.exception("Docling conversion failed")
        raise InvalidDocumentError(
            "The scanned PDF could not be OCR-processed. Try re-scanning at "
            "higher quality, or configure Azure Document Intelligence."
        ) from exc

    lines_by_page: dict[int, list[str]] = defaultdict(list)
    for item in document.texts:
        page_no = _item_page(item)
        text = (item.text or "").strip()
        if page_no and text:
            lines_by_page[page_no].append(text)

    tables_by_page: dict[int, list[str]] = defaultdict(list)
    for table in document.tables:
        page_no = _item_page(table)
        if page_no:
            tables_by_page[page_no].append(_table_markdown(table, document))

    pages = build_ocr_pages(lines_by_page, tables_by_page)
    logger.info("Docling extracted %d pages, %d tables",
                len(pages), len(document.tables))
    return pages
