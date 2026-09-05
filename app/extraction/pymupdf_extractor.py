"""
Digital-PDF text extraction with PyMuPDF.

Uses `get_text("blocks")`, which returns text blocks with their page
positions (x0, y0, x1, y1). Blocks are sorted top-to-bottom then
left-to-right so multi-column quote layouts read in a sane order, which
matters a lot for label/value pairing ("Indemnity ..... 90%").
"""

import logging

import pymupdf

from app.extraction.base import PageText

logger = logging.getLogger(__name__)


def extract_pages_pymupdf(doc: pymupdf.Document) -> list[PageText]:
    """Extract position-ordered text for every page of a digital PDF."""
    pages: list[PageText] = []

    for page_index, page in enumerate(doc):
        # blocks: (x0, y0, x1, y1, text, block_no, block_type)
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0]  # 0 = text, 1 = image
        # Sort by vertical position, then horizontal — natural reading order.
        text_blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))

        page_text = "\n".join(b[4].strip() for b in text_blocks if b[4].strip())
        pages.append(PageText(page_number=page_index + 1, text=page_text))

    logger.info("PyMuPDF extracted %d pages", len(pages))
    return pages
