"""
Open-source OCR extraction with IBM Docling (BRD 2.2 scanned-PDF route).

Used for scanned PDFs when Azure Document Intelligence is NOT configured —
Azure remains the preferred engine when its keys exist, and this module is
the zero-cloud-cost fallback so the pilot can process scans today. Chosen
over Tesseract/EasyOCR/PaddleOCR because Docling is the only pip-only
option that reconstructs TABLE STRUCTURE, which buyer credit-limit
schedules depend on.

Output is the same `list[PageText]` shape as every other extractor: per
page, the recognized text in reading order, then each table on that page
rebuilt as a markdown grid — so the LLM step is engine-agnostic and the
source-link contract (1-based pages) is identical.

Docling is an OPTIONAL heavy dependency (it pulls PyTorch). Install with:
    pip install -r requirements-ocr.txt
The first conversion downloads layout/OCR models (~a few hundred MB) and
runs noticeably slower than later ones. Everything is imported lazily so
the app runs fine without Docling installed.
"""

import io
import logging
from collections import defaultdict
from functools import lru_cache

from app.core.errors import ConfigurationError, InvalidDocumentError
from app.extraction.base import PageText, clean_text

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
    """Version-tolerant table -> markdown (the doc argument arrived in 2.x)."""
    try:
        return table.export_to_markdown(doc=document)
    except TypeError:
        return table.export_to_markdown()


def _item_page(item) -> int | None:
    prov = getattr(item, "prov", None)
    if prov:
        return prov[0].page_no
    return None


def extract_pages_docling(pdf_bytes: bytes) -> list[PageText]:
    """
    OCR a scanned PDF with Docling and return per-page text + table grids.

    Blocking, CPU-heavy call — the pipeline runs it in a worker thread.
    """
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

    # ── Text items per page, in Docling's reading order ──────────────────
    lines_by_page: dict[int, list[str]] = defaultdict(list)
    for item in document.texts:
        page_no = _item_page(item)
        text = (item.text or "").strip()
        if page_no and text:
            lines_by_page[page_no].append(text)

    # ── Tables per page, as markdown grids ───────────────────────────────
    tables_by_page: dict[int, list[str]] = defaultdict(list)
    for table in document.tables:
        page_no = _item_page(table)
        if page_no:
            tables_by_page[page_no].append(_table_markdown(table, document))

    pages: list[PageText] = []
    for page_no in sorted(set(lines_by_page) | set(tables_by_page)):
        sections = ["\n".join(lines_by_page.get(page_no, []))]
        for i, table_md in enumerate(tables_by_page.get(page_no, []), start=1):
            sections.append(f"[TABLE {i} ON THIS PAGE]\n{table_md}")
        pages.append(
            PageText(page_number=page_no, text=clean_text("\n\n".join(sections)))
        )

    logger.info(
        "Docling extracted %d pages, %d tables",
        len(pages), len(document.tables),
    )
    return pages
