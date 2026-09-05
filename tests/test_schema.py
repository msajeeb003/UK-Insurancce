"""The LLM contract: the Pydantic model must compile to a valid OpenAI
strict Structured Output schema with exactly the agreed fields."""

from openai.lib._pydantic import to_strict_json_schema

from app.models.schemas import QuoteExtraction

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
    "countries_covered",
    "exclusions",
    "special_conditions",
    "additional_info",
    "buyer_credit_limits",
}


def test_strict_schema_compiles_with_expected_fields():
    schema = to_strict_json_schema(QuoteExtraction)
    assert set(schema["properties"]) == EXPECTED_FIELDS
    # Strict mode requires every property to be required.
    assert set(schema["required"]) == EXPECTED_FIELDS


def test_ignored_fields_are_absent():
    schema = to_strict_json_schema(QuoteExtraction)
    assert "type_of_policy" not in schema["properties"]
    assert "debt_collection_support" not in schema["properties"]


def test_sourced_value_shape():
    schema = to_strict_json_schema(QuoteExtraction)
    sourced = schema["$defs"]["SourcedValue"]
    assert set(sourced["properties"]) == {"value", "page", "confidence"}
