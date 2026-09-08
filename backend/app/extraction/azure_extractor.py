"""
Scanned-PDF OCR via Azure AI Document Intelligence (prebuilt-layout).

Preferred scanned engine when AZURE_ENDPOINT / AZURE_KEY are configured;
also forceable with ?engine=azure for digital PDFs whose tables PyMuPDF
flattens badly.
"""

import logging
from collections import defaultdict
from functools import lru_cache

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.extraction.base import PageText, build_ocr_pages

logger = logging.getLogger(__name__)


@lru_cache
def _get_client() -> DocumentIntelligenceClient:
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
    grid: list[list[str]] = [
        ["" for _ in range(table.column_count)] for _ in range(table.row_count)
    ]
    for cell in table.cells:
        content = (cell.content or "").replace("\n", " ").strip()
        if cell.row_index < table.row_count and cell.column_index < table.column_count:
            grid[cell.row_index][cell.column_index] = content

    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if len(lines) > 1:
        lines.insert(1, "|" + "---|" * table.column_count)
    return "\n".join(lines)


def extract_pages_azure(pdf_bytes: bytes) -> list[PageText]:
    """Blocking call (the poller waits for the Azure job) — the pipeline
    runs it in a worker thread."""
    client = _get_client()
    poller = client.begin_analyze_document(
        "prebuilt-layout", body=pdf_bytes, content_type="application/pdf",
    )
    result = poller.result()

    lines_by_page: dict[int, list[str]] = defaultdict(list)
    for di_page in result.pages or []:
        for line in di_page.lines or []:
            lines_by_page[di_page.page_number].append(line.content)

    tables_by_page: dict[int, list[str]] = defaultdict(list)
    for table in result.tables or []:
        if table.bounding_regions:
            page_no = table.bounding_regions[0].page_number
            tables_by_page[page_no].append(_table_to_markdown(table))

    pages = build_ocr_pages(lines_by_page, tables_by_page)
    logger.info("Azure DI extracted %d pages, %d tables",
                len(pages), len(result.tables or []))
    return pages
