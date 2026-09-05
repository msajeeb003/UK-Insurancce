"""
Pydantic models.

Two groups:

1. LLM-facing models (`QuoteExtraction` + children) — passed to the OpenAI
   Responses API as the Structured Output schema. Strict mode is enforced by
   the SDK, so the model can ONLY return this exact shape. Every scalar field
   is a `SourcedValue`: the raw value as written in the document plus the PDF
   page number it was found on. A missing value is `value=null, page=null` —
   the schema itself makes "guess a placeholder" impossible to distinguish
   from real data, so the prompt + nullable types together enforce Rule 1.

2. API-facing models (`ExtractionResponse`) — what `/extract-quote` returns,
   wrapping the extraction with processing metadata.

Deliberately ABSENT fields (Rule 4 — set by broker rules, never extracted):
  - Type of policy
  - Debt collection support
"""

from typing import Literal

from pydantic import BaseModel, Field

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
    """The fixed JSON structure every insurer quote is normalized into."""

    insurer: SourcedValue = Field(
        description="Name of the insurance company issuing the quote."
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
    additional_info: SourcedValue = Field(
        description=(
            "Free-format text: any material conditions, warranties, "
            "exclusions, special terms or notes a broker should see that do "
            "not fit the fields above. Concise plain text; null if nothing "
            "noteworthy."
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


class ExtractionResponse(BaseModel):
    """Response body of POST /extract-quote."""

    meta: ProcessingMeta
    data: QuoteExtraction
