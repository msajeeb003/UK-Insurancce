"""
Shared types for the text-extraction layer.

Both extractors (PyMuPDF and Azure) produce the same intermediate shape —
a list of `PageText` — so the LLM step is completely agnostic about which
engine ran. Page numbers are 1-based throughout the pipeline, matching what
a broker sees in a PDF viewer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based
    text: str


def to_tagged_document(pages: list[PageText]) -> str:
    """
    Join page texts into a single LLM input string with explicit page markers.

    The markers are the ONLY way the LLM can know page numbers, which is what
    makes the source-linking rule (page per field) reliable.
    """
    parts = []
    for page in pages:
        parts.append(f"=== PAGE {page.page_number} ===")
        parts.append(page.text.strip())
    return "\n".join(parts)
