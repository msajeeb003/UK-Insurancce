"""The LLM contract: the Pydantic model must compile to a valid OpenAI
strict Structured Output schema with exactly the BRD 2.3 extracted fields."""

from openai.lib._pydantic import to_strict_json_schema

from app.models.schemas import CONFIRM_REQUIRED_FIELDS, QuoteExtraction

# BRD 2.3 definitive comparison list = insurer + these 13 extracted fields
# + 2 set fields (type of policy, debt collection support) that must NOT be
# in the extraction schema. document_type is identification (BRD 2.2), and
# buyer_credit_limits is the BRD 2.6 table.
EXPECTED_FIELDS = {
    "document_type",
    "insurer",
    "annual_turnover",
    "premium_rate",
    "estimated_annual_premium_exc_ipt",
    "minimum_annual_premium",
    "credit_limit_charges",
    "indemnity",
    "excess",
    "excess_type",
    "max_annual_liability",
    "discretionary_limit",
    "max_terms_of_payment",
    "max_extension_period",
    "additional_info",
    "buyer_credit_limits",
}


def test_strict_schema_compiles_with_expected_fields():
    schema = to_strict_json_schema(QuoteExtraction)
    assert set(schema["properties"]) == EXPECTED_FIELDS
    # Strict mode requires every property to be required.
    assert set(schema["required"]) == EXPECTED_FIELDS


def test_set_fields_are_absent_from_extraction_schema():
    """BRD 2.4: set fields must be impossible for the LLM to return."""
    schema = to_strict_json_schema(QuoteExtraction)
    assert "type_of_policy" not in schema["properties"]
    assert "debt_collection_support" not in schema["properties"]


def test_dropped_v1_fields_are_absent():
    """BRD v1.2 open item: not on the confirmed comparison slide."""
    schema = to_strict_json_schema(QuoteExtraction)
    assert "countries_covered" not in schema["properties"]
    assert "exclusions" not in schema["properties"]
    assert "special_conditions" not in schema["properties"]


def test_sourced_value_shape():
    schema = to_strict_json_schema(QuoteExtraction)
    sourced = schema["$defs"]["SourcedValue"]
    assert set(sourced["properties"]) == {"value", "page", "confidence"}


def test_confirm_gate_matches_brd():
    """BRD 2.5: the four values confirmed before export."""
    assert CONFIRM_REQUIRED_FIELDS == [
        "estimated_annual_premium_exc_ipt", "indemnity", "excess",
        "max_annual_liability",
    ]
