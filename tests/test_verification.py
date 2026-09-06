"""The deterministic verification pass — the anti-hallucination layer.

Every LLM value must be found in the document text or it is flagged;
wrong page citations are corrected; dropped ones are recovered."""

from app.extraction.base import PageText
from app.models.schemas import SourcedValue
from app.services.verification import verify_extraction


def make_extraction(sample_extraction, **field_overrides):
    for name, value in field_overrides.items():
        setattr(sample_extraction, name, value)
    return sample_extraction


PAGES = [
    PageText(1, "Quotation from ACME Credit Insurance plc.\n"
                "Insurable Turnover: GBP 12,000,000"),
    PageText(2, "Premium Payable: £12,600.00 per annum\n"
                "Deductible: £2,500 each and every loss"),
    PageText(3, "Discretionary Limit: £20,000\nMaximum Terms: 90 days"),
]


def sv(value, page, conf="high"):
    return SourcedValue(value=value, page=page, confidence=conf)


def test_verbatim_value_on_cited_page_passes(sample_extraction):
    ex = make_extraction(sample_extraction,
                         annual_turnover=sv("GBP 12,000,000", 1))
    unverified = verify_extraction(ex, PAGES)
    assert "annual_turnover" not in unverified
    assert ex.annual_turnover.page == 1
    assert ex.annual_turnover.confidence == "high"


def test_currency_format_difference_still_verifies(sample_extraction):
    # LLM reports "GBP 12,600"; the document printed "£12,600.00".
    ex = make_extraction(sample_extraction,
                         estimated_annual_premium_exc_ipt=sv("GBP 12,600", 2))
    unverified = verify_extraction(ex, PAGES)
    assert "estimated_annual_premium_exc_ipt" not in unverified
    assert ex.estimated_annual_premium_exc_ipt.page == 2


def test_wrong_page_citation_is_corrected(sample_extraction):
    ex = make_extraction(sample_extraction,
                         discretionary_limit=sv("£20,000", 1))  # actually page 3
    unverified = verify_extraction(ex, PAGES)
    assert "discretionary_limit" not in unverified
    assert ex.discretionary_limit.page == 3


def test_missing_page_link_is_recovered(sample_extraction):
    ex = make_extraction(sample_extraction, excess=sv("£2,500", None))
    verify_extraction(ex, PAGES)
    assert ex.excess.page == 2


def test_hallucinated_value_is_flagged_not_deleted(sample_extraction):
    ex = make_extraction(sample_extraction,
                         max_annual_liability=sv("£9,999,999", 2))
    unverified = verify_extraction(ex, PAGES)
    assert "max_annual_liability" in unverified
    # Kept (broker-editable), but never presented as certain or sourced.
    assert ex.max_annual_liability.value == "£9,999,999"
    assert ex.max_annual_liability.confidence == "uncertain"
    assert ex.max_annual_liability.page is None


def test_digits_of_one_figure_do_not_verify_inside_another(sample_extraction):
    # "£2,000" must NOT verify against "GBP 12,000,000" on page 1.
    ex = make_extraction(sample_extraction, excess=sv("£2,000", 1))
    unverified = verify_extraction(ex, PAGES)
    assert "excess" in unverified


def test_summary_fields_are_exempt(sample_extraction):
    ex = make_extraction(
        sample_extraction,
        additional_info=sv("No-claims bonus of 10% applies", 1),
    )
    unverified = verify_extraction(ex, PAGES)
    assert "additional_info" not in unverified
    assert ex.additional_info.confidence == "high"
