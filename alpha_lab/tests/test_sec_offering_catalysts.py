"""
tests/test_sec_offering_catalysts.py — SEC EDGAR offering/shelf filings should read
as bearish dilution catalysts, while routine filings (10-K/10-Q) stay neutral and
non-actionable. Pure deterministic scoring; no network.
"""
from datetime import datetime, timezone

from alpha_lab.catalysts import score_catalyst
from alpha_lab.live_sources import _sec_filing_text


def _sec_item(ticker: str, form: str) -> dict:
    headline, summary = _sec_filing_text(ticker, form)
    return {
        "ticker": ticker,
        "headline": headline,
        "summary": summary,
        "source": "SEC EDGAR submissions",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "security_type": "stock",
    }


def test_sec_filing_text_enriches_offering_and_shelf_forms():
    h5, s5 = _sec_filing_text("NVDA", "424B5")
    assert h5 == "NVDA filed 424B5 offering prospectus with the SEC"
    assert "offering" in s5.lower() and "dilut" in s5.lower()

    h3, s3 = _sec_filing_text("NVDA", "424B3")
    assert h3 == "NVDA filed 424B3 offering prospectus with the SEC"
    assert "offering" in s3.lower()

    hs, ss = _sec_filing_text("AMZN", "S-3")
    assert hs == "AMZN filed S-3 shelf registration with the SEC"
    assert "shelf registration" in hs.lower()

    # Routine forms keep the original neutral wording untouched.
    hk, sk = _sec_filing_text("NVDA", "10-K")
    assert hk == "NVDA filed 10-K with the SEC"
    assert sk == "SEC filing detected: 10-K. Review the filing before treating this as directional."


def test_424b5_is_bearish_direct_company_catalyst():
    scored = score_catalyst(_sec_item("NVDA", "424B5"))
    assert scored["bias"] == "bearish"
    assert scored["category"] == "direct_company_catalyst"
    # Offering language makes it actionable enough to clear the pre-score gate.
    assert scored["actionability_score"] >= 3.5


def test_s3_is_bearish_shelf_registration():
    scored = score_catalyst(_sec_item("AMZN", "S-3"))
    assert scored["bias"] == "bearish"
    assert scored["category"] == "direct_company_catalyst"
    assert any(m["keyword"] == "s-3" for m in scored["matched_keywords"])


def test_routine_filings_stay_neutral_and_non_actionable():
    for form in ("10-K", "10-Q"):
        scored = score_catalyst(_sec_item("NVDA", form))
        assert scored["bias"] == "neutral", form
        assert scored["trade_candidate"] is False, form


def test_polygon_bullish_catalyst_unbroken():
    item = {
        "ticker": "NVDA",
        "headline": "NVDA announces AI partnership agreement with major cloud provider",
        "summary": "Company signs a commercial agreement expanding AI infrastructure.",
        "source": "Polygon News / The Motley Fool",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "security_type": "stock",
    }
    scored = score_catalyst(item)
    assert scored["bias"] == "bullish"
    assert scored["category"] == "direct_company_catalyst"


def test_trade_candidate_confidence_clears_decision_engine_gate():
    """The radar's emitted candidates must carry a confidence that can clear the
    decision engine's default min_confidence (0.75) — one formula, one gate.
    Previously trade_candidate used a different confidence formula than the one
    stored on the signal, so candidates were created and then always rejected."""
    item = {
        "ticker": "NVDA",
        "headline": "NVIDIA partner signs AI infrastructure contract",
        "summary": "Source-backed contract catalyst for AI infrastructure demand.",
        "source": "unit_test_news",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "security_type": "stock",
    }
    scored = score_catalyst(item)
    assert scored["trade_candidate"] is True
    assert scored["confidence"] >= 0.75
