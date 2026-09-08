"""Mapping library + insurer rule (BRD 2.3/2.4) — configuration, not code."""

from app.llm.prompt import build_system_prompt
from app.services.library import debt_collection_rule, get_terminology, match_insurer


def test_debt_rule_included_insurers():
    """BRD 2.4: Allianz, Atradius and Coface default to Included."""
    for name in ["Allianz Trade", "Atradius", "Coface"]:
        value, matched = debt_collection_rule(name)
        assert value == "Included"
        assert matched == name


def test_debt_rule_other_insurers_outsourced():
    value, matched = debt_collection_rule("QBE")
    assert value == "Outsourced"
    assert matched == "QBE"


def test_debt_rule_matches_document_wording_via_aliases():
    """'QBE UK LIMITED' as printed in a real quotation must match QBE."""
    value, matched = debt_collection_rule("QBE UK LIMITED")
    assert value == "Outsourced"
    assert matched == "QBE"
    assert match_insurer("Euler Hermes")["id"] == "allianz"


def test_debt_rule_unknown_insurer_defaults_outsourced():
    value, matched = debt_collection_rule("ACME Credit Insurance plc")
    assert value == "Outsourced"
    assert matched is None
    assert debt_collection_rule(None) == ("Outsourced", None)


def test_terminology_covers_every_extracted_scalar():
    """Every normalized comparison row must have library wordings."""
    terminology = get_terminology()
    for field in [
        "annual_turnover", "premium_rate", "estimated_annual_premium_exc_ipt",
        "minimum_annual_premium", "credit_limit_charges", "indemnity",
        "excess", "excess_type", "max_annual_liability", "discretionary_limit",
        "max_terms_of_payment", "max_extension_period",
    ]:
        assert terminology.get(field), f"no mapping-library entry for {field}"


def test_prompt_is_built_from_the_library():
    prompt = build_system_prompt()
    # A Nexus wording from the client's terminology sheet must reach the LLM.
    assert "Uninsured Amount" in prompt
    # The standing insurer list aids identification.
    assert "Tokio Marine HCC" in prompt
    # Set fields stay excluded.
    assert 'DO NOT extract "type of policy"' in prompt
