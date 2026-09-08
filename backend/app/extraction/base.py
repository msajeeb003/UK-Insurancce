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


# Some PDFs carry a mojibake text layer (UTF-8 bytes decoded as Latin-1 by
# whatever produced the PDF): "£" arrives as "Â£", curly quotes as "â€™",
# and so on. Seen in a real insurer indication during the pilot. Cleaning at
# extraction time keeps the LLM input, the verification pass, and the
# broker-facing values consistent.
_MOJIBAKE_MAP = {
    "Â£": "£", "Â·": "·", "Â°": "°", "Â®": "®",
    "â€™": "'", "â€˜": "'", "â€œ": '"', "â€\x9d": '"',
    "â€“": "–", "â€”": "—", "â€¦": "…", "Ã©": "é",
}


def clean_text(text: str) -> str:
    """Undo common mojibake sequences in an extracted text layer."""
    for bad, good in _MOJIBAKE_MAP.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


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
