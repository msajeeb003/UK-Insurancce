"""
LLM extraction step — OpenAI Responses API with Structured Outputs.

`client.responses.parse(..., text_format=QuoteExtraction)` compiles the
Pydantic model into a strict JSON schema, so the model is physically unable
to return anything but the fixed structure. The prompt then carries the
business rules the schema alone cannot express:

  Rule 1  never guess       -> nulls for anything not in the document
  Rule 2  source linking    -> page numbers from the === PAGE n === markers
  Rule 3  normalization     -> map insurer synonyms to standard fields,
                               EXCEPT excess_type (verbatim wording)
  Rule 4  ignored fields    -> policy type / debt collection never extracted
                               (they are not in the schema either)

API key comes from `.env` (OPENAI_API_KEY); model from OPENAI_MODEL.
"""

import logging

from openai import OpenAI

from app.config import get_settings
from app.schemas import QuoteExtraction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a meticulous data-extraction engine for a UK credit insurance
brokerage. You receive the full text of ONE insurer quote document or
credit limit schedule. Page boundaries are marked with lines of the form
`=== PAGE n ===`.

Extract the requested fields following these STRICT rules:

1. NEVER GUESS. Only return a value that is explicitly written in the
   document. If a field is not present, set its `value` to null and its
   `page` to null. Do not compute, infer, estimate or use placeholders
   like "N/A" or "TBC" unless that exact text appears in the document as
   the stated value.

2. SOURCE LINKING. For every non-null value, set `page` to the page number
   from the nearest preceding `=== PAGE n ===` marker above where the
   value appears.

3. TERMINOLOGY NORMALIZATION. Different insurers use different labels
   (e.g. "Deductible" / "Minimum Retention" / "Excess" all describe the
   excess amount; "MAL" / "Maximum Aggregate Liability" describe maximum
   annual liability). Map such synonyms onto the standard fields, but copy
   each VALUE verbatim as written (keep currency symbols, % signs, units).
   EXCEPTION — `excess_type`: report the insurer's ORIGINAL wording for
   the type of excess exactly as printed; do not translate or normalize it.

4. DO NOT extract "type of policy" or "debt collection support". They are
   set by broker rules and are intentionally absent from the schema.

5. Buyer credit limits: if the document contains a buyer / credit limit
   schedule, return one entry per buyer row with any of buyer name,
   company number, limit required, limit offered that the row contains
   (null for the ones it lacks), plus the row's page number. If there is
   no such schedule, return an empty list.

6. `additional_info`: brief free-format text for material conditions,
   exclusions, warranties or special terms a broker should review. Only
   summarize what is actually in the document; null if nothing noteworthy.

7. If a monetary figure is ambiguous between including and excluding IPT,
   only fill `estimated_annual_premium_exc_ipt` when the document makes
   clear the figure excludes IPT (or IPT is stated separately); otherwise
   leave it null.
"""


def extract_quote_fields(tagged_document_text: str) -> QuoteExtraction:
    """
    Send page-tagged document text to OpenAI and get back a validated
    `QuoteExtraction` instance.

    Blocking call — the pipeline runs it in a worker thread.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured — set it in .env.")

    client = OpenAI(api_key=settings.openai_api_key)

    response = client.responses.parse(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": (
                    "Extract the structured quote data from the following "
                    "document text:\n\n" + tagged_document_text
                ),
            }
        ],
        text_format=QuoteExtraction,  # <- strict Structured Output schema
        temperature=0,                # deterministic extraction
    )

    if response.output_parsed is None:
        # Happens if the model refused or output was incomplete.
        raise RuntimeError(
            "OpenAI returned no parsed output "
            f"(status={response.status!r}). Raw text: {response.output_text[:500]!r}"
        )

    logger.info("OpenAI extraction complete (model=%s)", settings.openai_model)
    return response.output_parsed
