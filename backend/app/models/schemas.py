"""
Pydantic models — aligned to BRD v1.2.

Three groups:

1. LLM-facing models (`QuoteExtraction` + children) — passed to the OpenAI
   Responses API as the Structured Output schema. Strict mode is enforced by
   the SDK, so the model can ONLY return this exact shape. Every scalar field
   is a `SourcedValue`: the raw value as written in the document, the PDF
   page (or Excel sheet) it was found on, and a confidence flag. A missing
   value is `value=null, page=null, confidence=null` (BRD 2.2: blank, never
   guessed, never placeholder text).

   Insurer wording synonyms are NOT hardcoded here — they come from the
   terminology mapping library (config/terminology.json, BRD 2.3) and are
   injected into the extraction prompt at request time.

2. Rule-set fields (`SetFields`) — BRD 2.4: debt collection support is set
   by the insurer rule in config/insurers.json, never extracted. Type of
   policy is the other set field; it is broker-selected at project level in
   the UI, so it does not appear in this response at all.

3. API-facing models (`ExtractionResponse`) — what `/extract-quote` returns:
   processing metadata, a review summary (missing / uncertain fields and the
   BRD 2.5 confirmation gate list, computed server-side, never by the LLM),
   the rule-set fields, and the extraction itself.

The BRD 2.3 comparison list is definitive: 16 rows = insurer + 13 extracted
fields below + the 2 set fields. Countries covered and exclusions are NOT on
the confirmed slide (BRD open item) — material notes of that kind belong in
`additional_info` until the client confirms otherwise.
"""

from typing import Literal

from pydantic import BaseModel, Field

# "high"     -> the document states the value plainly.
# "uncertain"-> ambiguous wording, poor OCR, conflicting figures, or a value
#               inferred from context rather than an explicit label. The UI
#               highlights these for broker verification (BRD: the broker
#               reviews and corrects before anything is exported).
Confidence = Literal["high", "uncertain"]

DocumentType = Literal[
    "insurer_quote",          # a quotation / indication of terms
    "credit_limit_schedule",  # standalone buyer credit-limit schedule
    "policy_document",        # full policy wording (e.g. the expiring policy)
    "other",                  # anything else (e-mail print, letter, ...)
]

# BRD 2.5: the four values a broker must confirm before export is enabled.
CONFIRM_REQUIRED_FIELDS = [
    "estimated_annual_premium_exc_ipt",
    "indemnity",
    "excess",
    "max_annual_liability",
]

# ─────────────────────────────────────────────────────────────────────────
#  LLM-facing structured-output models
# ─────────────────────────────────────────────────────────────────────────

class SourcedValue(BaseModel):
    """A single extracted value, linked to the page it came from (BRD 2.2)."""

    value: str | None = Field(
        description=(
            "The value exactly as found in the document (verbatim, including "
            "currency symbols / % signs / units). null if not present in the "
            "document. NEVER invent, infer or use placeholder text — 'N/A' "
            "and 'Fixed' are broker entries, not extraction values, unless "
            "that exact text is printed in the document as the stated value."
        )
    )
    page: int | None = Field(
        description=(
            "1-based page number where this value was found, taken from the "
            "'=== PAGE n ===' markers in the input text. null if the value "
            "is null."
        )
    )
    confidence: Confidence | None = Field(
        description=(
            "'high' when the document states the value plainly under a clear "
            "label. 'uncertain' when the wording is ambiguous, the text looks "
            "OCR-garbled, several conflicting figures appear, or the value "
            "had to be read from context rather than an explicit label. "
            "null if (and only if) value is null."
        )
    )


class BuyerCreditLimit(BaseModel):
    """One row of a buyer / credit-limit schedule (BRD 2.6)."""

    buyer_name: str | None = Field(
        description="Buyer / customer company name as written. null if absent."
    )
    company_number: str | None = Field(
        description=(
            "Company registration number (e.g. UK Companies House number) as "
            "written. null if absent."
        )
    )
    limit_required: str | None = Field(
        description="Credit limit requested/required, verbatim. null if absent."
    )
    limit_offered: str | None = Field(
        description=(
            "Credit limit offered/approved/agreed by the insurer, verbatim. "
            "null if absent."
        )
    )
    page: int | None = Field(
        description="1-based page number this row was found on."
    )


class QuoteExtraction(BaseModel):
    """
    The extracted portion of the BRD 2.3 comparison list. Deliberately
    ABSENT (set, never extracted — BRD 2.4): type of policy, debt
    collection support.
    """

    document_type: DocumentType = Field(
        description=(
            "What this document is: 'insurer_quote' for a quotation or "
            "indication of terms; 'credit_limit_schedule' for a standalone "
            "buyer credit-limit schedule; 'policy_document' for full policy "
            "wording (e.g. the expiring policy); 'other' if none fit."
        )
    )
    insurer: SourcedValue = Field(
        description="Name of the insurance company issuing the document."
    )
    annual_turnover: SourcedValue = Field(
        description=(
            "Insurable/estimated annual turnover the quote is based on. If "
            "split (e.g. domestic and export), give the total with the split "
            "noted."
        )
    )
    premium_rate: SourcedValue = Field(
        description="Premium rate, usually a percentage of turnover."
    )
    estimated_annual_premium_exc_ipt: SourcedValue = Field(
        description=(
            "Estimated annual premium EXCLUDING Insurance Premium Tax. If a "
            "figure is explicitly inclusive of IPT and no exclusive figure "
            "is stated, return null rather than recomputing."
        )
    )
    minimum_annual_premium: SourcedValue = Field(
        description="Minimum annual premium."
    )
    credit_limit_charges: SourcedValue = Field(
        description="Charges for credit limit checks / decisions."
    )
    indemnity: SourcedValue = Field(
        description="Insured percentage of each loss."
    )
    excess: SourcedValue = Field(
        description="Excess / deductible AMOUNT."
    )
    excess_type: SourcedValue = Field(
        description=(
            "The insurer's ORIGINAL wording for the kind of excess/deductible. "
            "BRD 2.3 exception: DO NOT normalize this value — keep the "
            "insurer's exact terminology (e.g. 'Minimum Retention')."
        )
    )
    max_annual_liability: SourcedValue = Field(
        description="Insurer's maximum liability for the policy period."
    )
    discretionary_limit: SourcedValue = Field(
        description=(
            "Discretionary (credit) limit the policyholder may self-underwrite."
        )
    )
    max_terms_of_payment: SourcedValue = Field(
        description="Maximum terms of payment insured."
    )
    max_extension_period: SourcedValue = Field(
        description=(
            "Maximum extension period for overdue accounts. NOT a "
            "'Protracted Default' / claims waiting period — if only a "
            "waiting period is stated, return null here."
        )
    )
    additional_info: SourcedValue = Field(
        description=(
            "Free-format text: material notes a broker should see that fit "
            "no field above — e.g. no-claims bonus terms, and any material "
            "countries-covered, exclusions or special-conditions wording "
            "(those are not separate comparison rows). Concise plain text; "
            "null if nothing noteworthy."
        )
    )
    buyer_credit_limits: list[BuyerCreditLimit] = Field(
        description=(
            "All buyer credit-limit rows if the document contains a credit "
            "limit schedule / buyer list — whether a standalone schedule or "
            "an addendum inside the quote. Empty list if the document has "
            "no such table."
        )
    )


# ─────────────────────────────────────────────────────────────────────────
#  Rule-set fields (BRD 2.4 — set, never extracted)
# ─────────────────────────────────────────────────────────────────────────

class SetField(BaseModel):
    """A value set by configuration rule, not extracted. Editable in the UI."""

    value: str
    source: Literal["insurer_rule"]
    matched_insurer: str | None = Field(
        description=(
            "Standing-list insurer name the rule matched on, or null when "
            "the extracted insurer is not on the standing list (the rule "
            "then applies its default)."
        )
    )


class SetFields(BaseModel):
    """
    BRD 2.4 rule-set fields the server can compute. Type of policy is also a
    set field but is broker-selected at project level, so it never appears
    in an extraction response.
    """

    debt_collection_support: SetField


# ─────────────────────────────────────────────────────────────────────────
#  API-facing response models
# ─────────────────────────────────────────────────────────────────────────

class ProcessingMeta(BaseModel):
    """How the document was processed — pilot debugging across formats."""

    filename: str
    page_count: int = Field(
        description="PDF pages, or worksheet count for an Excel schedule."
    )
    document_id: str | None = Field(
        default=None,
        description=(
            "Id of the retained copy when the upload was made inside a "
            "project (BRD S4: documents retained; S5: source-page view)."
        ),
    )
    extraction_engine: Literal[
        "pymupdf", "azure_document_intelligence", "docling", "excel"
    ]
    llm_model: str


class ReviewSummary(BaseModel):
    """
    What a broker must look at before the comparison is presentation-ready.
    Computed deterministically by the server from the extraction — never by
    the LLM — so the UI and the export gate can rely on it.
    """

    missing_fields: list[str] = Field(
        description="Field names with no value found in the document."
    )
    uncertain_fields: list[str] = Field(
        description=(
            "Field names extracted with 'uncertain' confidence — verify "
            "against the source page."
        )
    )
    unverified_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Field names whose extracted value could not be found anywhere "
            "in the document text by the deterministic verification pass — "
            "possible hallucination; the value is kept but downgraded to "
            "'uncertain' and its page link cleared."
        ),
    )
    confirm_required: list[str] = Field(
        default=CONFIRM_REQUIRED_FIELDS,
        description=(
            "BRD 2.5: the fields a broker must confirm before export is "
            "enabled, regardless of extraction quality."
        ),
    )


class ExtractionResponse(BaseModel):
    """Response body of POST /extract-quote."""

    meta: ProcessingMeta
    review: ReviewSummary
    set_fields: SetFields
    data: QuoteExtraction


def sourced_items(extraction: QuoteExtraction) -> list[tuple[str, SourcedValue]]:
    """(field_name, SourcedValue) pairs of an extraction, in schema order."""
    return [
        (name, item)
        for name in QuoteExtraction.model_fields
        if isinstance(item := getattr(extraction, name), SourcedValue)
    ]
