"""
Request models for POST /generate-presentation (BRD 2.8).

The frontend sends the reviewed project state — columns, values (extracted
or broker-edited), credit-limit rows, the recommendation, notes and
reasons — and the server renders the presentation. The BRD 2.5 export gate
is enforced HERE, server-side: the four key values must be confirmed or
generation is refused, so no client can bypass it.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# The 16-row comparison list (BRD 2.3): "Insurer" is the column heading;
# these are the rows, in slide order. 'type' and 'debt' are the set fields.
PRESENTATION_ROWS: list[tuple[str, str]] = [
    ("type", "Type of policy"),
    ("annual_turnover", "Annual turnover"),
    ("premium_rate", "Premium rate"),
    ("estimated_annual_premium_exc_ipt", "Estimated annual premium (exc IPT)"),
    ("minimum_annual_premium", "Minimum annual premium"),
    ("credit_limit_charges", "Credit limit charges"),
    ("debt", "Debt collection support"),
    ("indemnity", "Indemnity"),
    ("excess", "Excess"),
    ("excess_type", "Excess type"),
    ("max_annual_liability", "Max annual liability"),
    ("discretionary_limit", "Discretionary limit"),
    ("max_terms_of_payment", "Max terms of payment"),
    ("max_extension_period", "Max extension period"),
    ("additional_info", "Additional info"),
]


class PresentationColumn(BaseModel):
    """One insurer column of the comparison, as reviewed by the broker."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    values: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Row key -> display value, exactly as reviewed. Missing keys and "
            "empty strings both render blank (BRD 2.2: blank, never guessed)."
        ),
    )

    @field_validator("values")
    @classmethod
    def _cap_values(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 40:
            raise ValueError("too many value entries (max 40 per column)")
        for key, value in values.items():
            if len(key) > 64 or len(value) > 800:
                raise ValueError("value entry too long (key<=64, value<=800 chars)")
        return values


class CreditLimitRow(BaseModel):
    """One buyer row of the credit-limit table (BRD 2.6)."""

    buyer: str = Field(default="", max_length=200)
    company_number: str = Field(default="", max_length=40)
    required: str = Field(default="", max_length=80)
    offers: dict[str, str] = Field(
        default_factory=dict, description="Column id -> offered limit."
    )

    @field_validator("offers")
    @classmethod
    def _cap_offers(cls, offers: dict[str, str]) -> dict[str, str]:
        if len(offers) > 12:
            raise ValueError("too many offer entries (max 12 per buyer row)")
        for key, value in offers.items():
            if len(key) > 64 or len(value) > 120:
                raise ValueError("offer entry too long (key<=64, value<=120 chars)")
        return offers


class PresentationRequest(BaseModel):
    """Everything needed to render the BRD 2.8 presentation."""

    client_name: str = Field(min_length=1, max_length=200)
    reference: str = Field(default="", max_length=60)
    project_type: Literal["new", "renewal"]
    # BRD layout rule: one to six insurer columns.
    columns: list[PresentationColumn] = Field(min_length=1, max_length=6)
    recommended_id: str | None = None
    approached_insurers: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Standing-list names the broker ticked at setup; insurers with "
            "no matching column are auto-named as declined (BRD 2.1/S8)."
        ),
    )
    credit_limits: list[CreditLimitRow] = Field(default_factory=list, max_length=300)
    notes: str = Field(default="", max_length=4000)
    reasons: str = Field(default="", max_length=4000)
    confirmed_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Field names the broker confirmed on the review screen. All of "
            "BRD 2.5's four key values must be present or generation is "
            "refused."
        ),
    )
