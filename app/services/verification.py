"""
Post-extraction verification: every value the LLM returns is checked
against the actual document text, deterministically.

Structured Outputs guarantees the SHAPE of the extraction; this pass
guards its TRUTHFULNESS — the two failure modes that survive a strict
schema are a hallucinated value and a wrong page citation. For each
extracted value (which the prompt requires to be verbatim):

  1. Confirm the value appears on its cited page — first as normalized
     text, then by significant digit runs, so "GBP 12,600" still matches
     a document that printed "£12,600".
  2. If it is not on the cited page but appears on exactly ONE other
     page, the page link is corrected (and logged).
  3. If it appears nowhere in the document, the value is downgraded to
     'uncertain', its page link is cleared, and the field is reported in
     `review.unverified_fields` — the broker sees an amber flag instead
     of a plausible-looking wrong number (BRD: "a wrong number that
     looks plausible survives proofreading").
  4. A value with no page cite that appears on exactly one page gains
     that page link — recovering source links the sanitizer had to drop.

Summary-style fields (`additional_info`) are exempt: they paraphrase by
design, so verbatim matching would false-flag them.
"""

import logging
import re

from app.extraction.base import PageText
from app.models.schemas import QuoteExtraction, SourcedValue

logger = logging.getLogger(__name__)

# Fields whose values are summaries, not verbatim quotes.
SUMMARY_FIELDS = {"additional_info"}


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace — tolerant of layout differences."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _digit_runs(text: str) -> list[str]:
    """
    Significant digit sequences with separators stripped: "£1,250,000.50"
    -> ["125000050"]. Two-digit runs count so "90" (as in 90%) verifies.
    """
    runs = re.findall(r"\d[\d,.\s]*\d|\d{2,}", text)
    cleaned = [re.sub(r"[^\d]", "", run) for run in runs]
    return [run for run in cleaned if len(run) >= 2]


class _PageIndex:
    """Pre-normalized page text for repeated lookups."""

    def __init__(self, pages: list[PageText]):
        self.norm: dict[int, str] = {p.page_number: _normalize(p.text) for p in pages}
        # Each number on the page becomes its own separator-stripped run —
        # never concatenated, so digits of one figure can't falsely verify
        # inside a different figure.
        self.digit_runs: dict[int, set[str]] = {
            p.page_number: set(_digit_runs(p.text)) for p in pages
        }

    @staticmethod
    def _run_matches(run: str, page_runs: set[str]) -> bool:
        # Exact figure, or the page shows pennies ("12,600.00" for £12,600).
        return run in page_runs or (run + "00") in page_runs

    def value_on_page(self, value: str, page_number: int) -> bool:
        page_text = self.norm.get(page_number)
        if page_text is None:
            return False
        needle = _normalize(value)
        if len(needle) >= 3 and needle in page_text:
            return True
        runs = _digit_runs(value)
        page_runs = self.digit_runs.get(page_number, set())
        return bool(runs) and all(self._run_matches(run, page_runs) for run in runs)

    def pages_containing(self, value: str) -> list[int]:
        return [n for n in self.norm if self.value_on_page(value, n)]


def verify_extraction(
    extraction: QuoteExtraction, pages: list[PageText]
) -> list[str]:
    """
    Verify every sourced value against the document. Mutates the
    extraction in place (page corrections, confidence downgrades) and
    returns the names of fields whose values could not be found anywhere.
    """
    index = _PageIndex(pages)
    unverified: list[str] = []

    for field_name in type(extraction).model_fields:
        item = getattr(extraction, field_name)
        if not isinstance(item, SourcedValue) or item.value is None:
            continue
        if field_name in SUMMARY_FIELDS:
            continue

        if item.page is not None and index.value_on_page(item.value, item.page):
            continue  # verified where cited

        found_on = index.pages_containing(item.value)
        if item.page is not None and found_on:
            if len(found_on) == 1:
                logger.info(
                    "Field %r: value not on cited page %s, found on page %s — "
                    "correcting source link", field_name, item.page, found_on[0],
                )
                item.page = found_on[0]
            # Multiple candidate pages: the cite is wrong but the true page
            # is ambiguous — keep the value, drop the unreliable link.
            else:
                logger.info(
                    "Field %r: value not on cited page %s, found on pages %s — "
                    "clearing ambiguous link", field_name, item.page, found_on,
                )
                item.page = None
            continue

        if item.page is None and found_on:
            if len(found_on) == 1:
                item.page = found_on[0]  # recovered source link
            continue

        # Nowhere in the document: possible hallucination. Flag, never delete
        # (every field stays broker-editable) — but never present as certain.
        logger.warning(
            "Field %r: value %r not found anywhere in the document — "
            "flagging unverified", field_name, item.value,
        )
        item.confidence = "uncertain"
        item.page = None
        unverified.append(field_name)

    return unverified
