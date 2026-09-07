"""
OCR extraction with Azure AI Document Intelligence (prebuilt-layout model).

Used when the detector classifies a PDF as scanned, or when the caller
forces `engine=azure` (useful for digital PDFs whose tables PyMuPDF
flattens badly — e.g. dense credit-limit schedules).

Credentials come from `.env`:
    AZURE_ENDPOINT  -> resource endpoint URL
    AZURE_KEY       -> resource API key

Output is the same `list[PageText]` shape as the PyMuPDF extractor:
per page, the recognized lines in reading order, followed by every table
on that page reconstructed as a markdown grid. Tables are re-rendered
explicitly (even though their cell text also appears in the line stream)
because a clean row/column grid is far more reliable for the LLM when
pulling buyer credit-limit schedules.
"""

import logging
from collections import defaultdict
from functools import lru_cache

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.extraction.base import PageText, clean_text

logger = logging.getLogger(__name__)


@lru_cache
def _get_client() -> DocumentIntelligenceClient:
    """One client per process — the SDK's connection pool is reused."""
    settings = get_settings()
    if not settings.azure_endpoint or not settings.azure_key.get_secret_value():
        raise ConfigurationError(
            "Azure Document Intelligence is not configured — scanned PDFs "
            "cannot be processed. Set AZURE_ENDPOINT and AZURE_KEY."
        )
    return DocumentIntelligenceClient(
        endpoint=settings.azure_endpoint,
        credential=AzureKeyCredential(settings.azure_key.get_secret_value()),
    )


def _table_to_markdown(table) -> str:
    """Rebuild a DI table object as a markdown grid."""
    grid: list[list[str]] = [
        ["" for _ in range(table.column_count)] for _ in range(table.row_count)
    ]
    for cell in table.cells:
        content = (cell.content or "").replace("\n", " ").strip()
        # Guard against out-of-range indices on malformed spans.
        if cell.row_index < table.row_count and cell.column_index < table.column_count:
            grid[cell.row_index][cell.column_index] = content

    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if len(lines) > 1:
        # Insert a markdown header separator after the first row.
        separator = "|" + "---|" * table.column_count
        lines.insert(1, separator)
    return "\n".join(lines)


def extract_pages_azure(pdf_bytes: bytes) -> list[PageText]:
    """
    Run the prebuilt-layout analysis and return per-page text.

    NOTE: this is a blocking call (the poller waits for the Azure job);
    the pipeline runs it in a worker thread so the API event loop stays free.
    """
    client = _get_client()
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=pdf_bytes,
        content_type="application/pdf",
    )
    result = poller.result()

    # ── Lines per page, in the order DI returns them (reading order) ─────
    lines_by_page: dict[int, list[str]] = defaultdict(list)
    for di_page in result.pages or []:
        for line in di_page.lines or []:
            lines_by_page[di_page.page_number].append(line.content)

    # ── Tables per page, rebuilt as markdown grids ───────────────────────
    tables_by_page: dict[int, list[str]] = defaultdict(list)
    for table in result.tables or []:
        if table.bounding_regions:
            page_no = table.bounding_regions[0].page_number
            tables_by_page[page_no].append(_table_to_markdown(table))

    pages: list[PageText] = []
    all_page_numbers = sorted(set(lines_by_page) | set(tables_by_page))
    for page_no in all_page_numbers:
        sections = ["\n".join(lines_by_page.get(page_no, []))]
        for i, table_md in enumerate(tables_by_page.get(page_no, []), start=1):
            sections.append(f"[TABLE {i} ON THIS PAGE]\n{table_md}")
        pages.append(PageText(page_number=page_no, text=clean_text("\n\n".join(sections))))

    logger.info(
        "Azure DI extracted %d pages, %d tables",
        len(pages), len(result.tables or []),
    )
    return pages
