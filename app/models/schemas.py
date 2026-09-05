"""
Pydantic models.

Two groups:

1. LLM-facing models (`QuoteExtraction` + children) — passed to the OpenAI
   Responses API as the Structured Output schema. Strict mode is enforced by
   the SDK, so the model can ONLY return this exact shape. Every scalar field
   is a `SourcedValue`: the raw value as written in the document, the PDF
   page number it was found on, and a confidence flag. A missing value is
   `value=null, page=null, confidence=null` — the schema itself makes
   "guess a placeholder" impossible to distinguish from real data, so the
   prompt + nullable types together enforce Rule 1.

2. API-facing models (`ExtractionResponse`) — what `/extract-quote` returns:
   processing metadata, a review summary (missing / uncertain fields,
   computed server-side, never by the LLM), and the extraction itself.

Deliberately ABSENT fields (Rule 4 — set by broker rules, never extracted):
  - Type of policy
  - Debt collection support
"""

from typing import Literal

from pydantic import BaseModel, Field

# "high"     -> the document states the value plainly.
# "uncertain"-> ambiguous wording, poor OCR, conflicting figures, or a value
#               inferred from context rather than an explicit label. The UI
#               highlights these for broker verification before export.
Confidence = Literal["high", "uncertain"]

DocumentType = Literal[
    "insurer_quote",          # a quotation / indication of terms
    "credit_limit_schedule",  # standalone buyer credit-limit schedule
    "policy_document",        # full policy wording / expiring policy
    "other",                  # anything else (e-mail print, letter, ...)
]

# ─────────────────────────────────────────────────────────────────────────
#  LLM-facing structured-output models
# ─────────────────────────────────────────────────────────────────────────

class SourcedValue(BaseModel):
    """A single extracted value, linked to the page it came from (Rule 2)."""

    value: str | None = Field(
        description=(
            "The value exactly as found in the document (verbatim, including "
            "currency symbols / % signs / units). null if not present in the "
            "document. NEVER invent, infer or use placeholder text."
        )
    )
    page: int | None = Field(
        description=(
            "1-based PDF page number where this value was found, taken from "
            "the '=== PAGE n ===' markers in the input text. null if the "
            "value is null."
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
    """One row of a buyer / credit-limit schedule, if present in the PDF."""

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
            "Credit limit offered/approved/granted by the insurer, verbatim. "
            "null if absent."
        )
    )
    page: int | None = Field(
        description="1-based PDF page number this row was found on."
    )


class QuoteExtraction(BaseModel):
    """The fixed JSON structure every insurer document is normalized into."""

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
            "Insurable/estimated annual turnover the quote is based on. "
            "Normalize from terms like 'Insurable Turnover', 'Estimated "
            "Annual Sales', 'Declared Turnover'."
        )
    )
    premium_rate: SourcedValue = Field(
        description=(
            "Premium rate, usually a % of turnover. Normalize from 'Rate', "
            "'Premium Rate', 'Rate per £100', 'Turnover Rate'."
        )
    )
    estimated_annual_premium_exc_ipt: SourcedValue = Field(
        description=(
            "Estimated annual premium EXCLUDING Insurance Premium Tax. "
            "Normalize from 'Annual Premium', 'Estimated Premium', 'Deposit "
            "Premium'. If a figure is explicitly inclusive of IPT and no "
            "exclusive figure is stated, return null rather than recomputing."
        )
    )
    minimum_annual_premium: SourcedValue = Field(
        description=(
            "Minimum annual premium. Normalize from 'Minimum Premium', 'MAP', "
            "'Minimum and Deposit Premium'."
        )
    )
    credit_limit_charges: SourcedValue = Field(
        description=(
            "Charges for credit limit checks/decisions. Normalize from "
            "'Credit Limit Fee', 'Buyer Underwriting Charges', 'Limit "
            "Assessment Fee', 'Credit Opinion Charges'."
        )
    )
    indemnity: SourcedValue = Field(
        description=(
            "Insured percentage of each loss. Normalize from 'Indemnity', "
            "'Insured Percentage', 'Cover Level', '% of Cover'."
        )
    )
    excess: SourcedValue = Field(
        description=(
            "Excess / deductible AMOUNT. Normalize from 'Deductible', "
            "'Minimum Retention', 'Excess', 'Each and Every Loss Deductible', "
            "'Aggregate First Loss'."
        )
    )
    excess_type: SourcedValue = Field(
        description=(
            "The insurer's ORIGINAL wording for the kind of excess/deductible "
            "(e.g. 'Each and Every Loss', 'Aggregate First Loss', 'Non "
            "Qualifying Loss', 'Minimum Retention'). Rule 3 exception: DO NOT "
            "normalize this field — keep the insurer's exact terminology."
        )
    )
    max_annual_liability: SourcedValue = Field(
        description=(
            "Insurer's maximum liability for the policy period. Normalize "
            "from 'Maximum Liability', 'Maximum Aggregate Liability', 'MAL', "
            "'Maximum Payable', 'Insurer's Maximum Liability'."
        )
    )
    discretionary_limit: SourcedValue = Field(
        description=(
            "Discretionary (credit) limit the policyholder may self-underwrite. "
            "Normalize from 'Discretionary Limit', 'DL', 'Discretionary Credit "
            "Limit', 'Self-Underwriting Limit'."
        )
    )
    max_terms_of_payment: SourcedValue = Field(
        description=(
            "Maximum terms of payment insured. Normalize from 'Maximum Terms "
            "of Payment', 'MTP', 'Maximum Credit Terms', 'Terms of Payment'."
        )
    )
    max_extension_period: SourcedValue = Field(
        description=(
            "Maximum extension period for overdue accounts. Normalize from "
            "'Maximum Extension Period', 'MEP', 'Grace Period'."
        )
    )
    countries_covered: SourcedValue = Field(
        description=(
            "Countries / territories the cover applies to, as a comma-"
            "separated list verbatim from the document. Normalize from "
            "'Countries Covered', 'Territorial Scope', 'Insured Countries', "
            "'Country Schedule', 'Whole World excluding ...' (keep the "
            "exclusion wording)."
        )
    )
    exclusions: SourcedValue = Field(
        description=(
            "What the policy explicitly does NOT cover: excluded buyers, "
            "sectors, countries or debt types. Concise summary using the "
            "document's own wording. Normalize from 'Exclusions', 'Excluded "
            "Risks', 'Not Covered', 'Excluded Buyers/Sectors'."
        )
    )
    special_conditions: SourcedValue = Field(
        description=(
            "Conditions the insured must meet for cover to apply: warranties, "
            "subjectivities, conditions precedent, reporting obligations "
            "specific to this quote. Concise summary using the document's own "
            "wording. Normalize from 'Special Conditions', 'Warranties', "
            "'Subjectivities', 'Conditions Precedent'."
        )
    )
    additional_info: SourcedValue = Field(
        description=(
            "Free-format text: any other material notes a broker should see "
            "that fit none of the fields above (e.g. no-claims bonus, "
            "premium payment schedule). Concise plain text; null if nothing "
            "noteworthy. Do NOT repeat exclusions or special conditions here."
        )
    )
    buyer_credit_limits: list[BuyerCreditLimit] = Field(
        description=(
            "All buyer credit-limit rows if the document contains a credit "
            "limit schedule / buyer list. Empty list if the document has no "
            "such table."
        )
    )


# ─────────────────────────────────────────────────────────────────────────
#  API-facing response models
# ─────────────────────────────────────────────────────────────────────────

class ProcessingMeta(BaseModel):
    """How the PDF was processed — useful for pilot debugging across formats."""

    filename: str
    page_count: int
    extraction_engine: Literal["pymupdf", "azure_document_intelligence"]
    llm_model: str


class ReviewSummary(BaseModel):
    """
    What a broker must look at before the comparison is presentation-ready.
    Computed deterministically by the server from the extraction — never by
    the LLM — so the UI can rely on it.
    """

    missing_fields: list[str] = Field(
        description="Field names with no value found in the document."
    )
    uncertain_fields: list[str] = Field(
        description="Field names extracted with 'uncertain' confidence — verify against the source page."
    )


class ExtractionResponse(BaseModel):
    """Response body of POST /extract-quote."""

    meta: ProcessingMeta
    review: ReviewSummary
    data: QuoteExtraction
