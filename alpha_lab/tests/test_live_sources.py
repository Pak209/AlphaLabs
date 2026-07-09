"""Phase 1 test frontier: live_sources vendor parsers and feed contracts.

Two contracts locked here, with zero network:

1. Disabled-when-unconfigured — every feed returns the standard disabled
   envelope (status/reason/empty catalysts) when its key is absent, and
   fetch_live_catalysts reports no_live_providers without touching the net.
2. Parser normalization — recorded-shape vendor payloads (fixtures) normalize
   into the standard catalyst row (ticker/headline/summary/source/source_url/
   published_at), including the SEC dilution wording, material-form filter,
   watchlist filtering, and Benzinga RFC-822 time parsing.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import alpha_lab.live_sources as ls

ALL_KEYS = (
    "SEC_USER_AGENT", "POLYGON_API_KEY", "BENZINGA_API_KEY",
    "TIINGO_API_KEY", "NEWSFILTER_API_KEY", "YAHOO_NEWS_ENABLED",
)


@pytest.fixture()
def no_keys(monkeypatch):
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Any network attempt while unconfigured is a bug, not a fallback.
    monkeypatch.setattr(ls, "_fetch_json", _no_network)


def _no_network(*args, **kwargs):
    raise AssertionError("network call attempted while feeds are unconfigured")


# ─── 1. disabled contracts ────────────────────────────────────────────────────

@pytest.mark.parametrize("fetcher, name", [
    (ls._fetch_sec_filings, "SEC EDGAR"),
    (ls._fetch_polygon_news, "Polygon News"),
    (ls._fetch_benzinga_news, "Benzinga News/Press Releases"),
    (ls._fetch_benzinga_insiders, "Benzinga Insider Transactions"),
    (ls._fetch_tiingo_news, "Tiingo News"),
    (ls._fetch_newsfilter, "Newsfilter"),
    (ls._fetch_yahoo_news, "Yahoo Finance News"),
])
def test_feed_disabled_without_key(no_keys, fetcher, name):
    result = fetcher(["NVDA"])
    assert result["status"] == "disabled"
    assert result["name"] == name
    assert result["catalysts"] == [] and result["count"] == 0
    assert result["reason"]  # tells the operator which env var to set


def test_fetch_live_catalysts_reports_no_live_providers(no_keys):
    result = ls.fetch_live_catalysts(["NVDA"])
    assert result["status"] == "no_live_providers"
    assert result["catalysts"] == []
    assert all(p["status"] == "disabled" for p in result["providers"])


# ─── 2. parser fixtures ───────────────────────────────────────────────────────

def test_sec_parser_filters_forms_and_words_dilution(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "AlphaLab test test@example.com")
    today = datetime.now(timezone.utc).date().isoformat()

    def fake_fetch(url, **kwargs):
        if "company_tickers" in url:
            return {"0": {"ticker": "NVDA", "cik_str": 1045810}}
        assert "CIK0001045810" in url
        return {"filings": {"recent": {
            "form": ["8-K", "424B5", "SC 13G", "10-K"],
            "filingDate": [today, today, today, "2020-01-02"],
            "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003", "0001-24-000004"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
        }}}

    monkeypatch.setattr(ls, "_fetch_json", fake_fetch)
    result = ls._fetch_sec_filings(["NVDA"])
    assert result["status"] == "ok"
    forms = [row["headline"] for row in result["catalysts"]]
    assert len(forms) == 2                       # SC 13G immaterial; 10-K past cutoff
    assert forms[0] == "NVDA filed 8-K with the SEC"
    dilution = result["catalysts"][1]
    assert "offering prospectus" in dilution["headline"]
    assert "dilutive" in dilution["summary"]      # bearish read for the keyword scorer
    assert dilution["source_url"] == "https://www.sec.gov/Archives/edgar/data/1045810/000124000002/b.htm"
    assert dilution["published_at"].startswith(today)


def test_polygon_parser_normalizes_rows(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "k")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: {"results": [{
        "title": "NVIDIA wins massive AI contract",
        "description": "Details of the award.",
        "publisher": {"name": "Newswire"},
        "article_url": "https://example.com/a",
        "published_utc": "2026-07-08T12:00:00Z",
        "tickers": ["nvda", "smci"],
    }]})
    result = ls._fetch_polygon_news(["NVDA"])
    assert result["status"] == "ok" and result["count"] == 1
    row = result["catalysts"][0]
    assert row["ticker"] == "NVDA"
    assert row["headline"] == "NVIDIA wins massive AI contract"
    assert row["source"] == "Polygon News / Newswire"
    assert row["related_tickers"] == ["NVDA", "SMCI"]
    assert row["published_at"] == "2026-07-08T12:00:00Z"


def test_benzinga_news_parses_time_filters_watchlist_strips_html(monkeypatch):
    monkeypatch.setenv("BENZINGA_API_KEY", "k")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: [
        {"title": "NVDA raises guidance", "teaser": "",
         "body": "<p>Strong quarter</p><br />More detail",
         "created": "Wed, 08 Jul 2026 09:30:00 -0400",
         "stocks": [{"name": "NVDA"}], "url": "https://bz.example/1", "author": "Desk"},
        {"title": "Off-watchlist item", "teaser": "x", "created": None,
         "stocks": [{"name": "ZZZZ"}], "url": "", "author": "Desk"},
    ])
    result = ls._fetch_benzinga_news(["NVDA"])
    assert result["count"] == 1                   # ZZZZ filtered out
    row = result["catalysts"][0]
    assert row["source"] == "Benzinga / Desk"
    assert "Strong quarter" in row["summary"] and "<p>" not in row["summary"]
    assert row["published_at"] == "2026-07-08T13:30:00+00:00"   # RFC-822 → UTC


def test_benzinga_insiders_composes_headline(monkeypatch):
    monkeypatch.setenv("BENZINGA_API_KEY", "k")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: {"insider_transactions": [
        {"ticker": "NVDA", "owner_name": "J. Doe", "transaction_type": "P - Purchase",
         "filing_date": "2026-07-08"},
    ]})
    result = ls._fetch_benzinga_insiders(["NVDA"])
    row = result["catalysts"][0]
    assert row["headline"] == "NVDA insider P - Purchase: J. Doe"
    assert row["source"] == "Benzinga Insider Transactions"
    assert row["published_at"] == "2026-07-08"


def test_tiingo_and_newsfilter_parsers(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("NEWSFILTER_API_KEY", "k")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: [
        {"title": "T", "description": "d", "tickers": ["nvda"],
         "publishedDate": "2026-07-08T10:00:00Z", "url": "u", "source": "wire"},
    ])
    tiingo = ls._fetch_tiingo_news(["NVDA"])
    assert tiingo["catalysts"][0]["source"] == "Tiingo / wire"
    assert tiingo["catalysts"][0]["ticker"] == "NVDA"

    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: {"articles": [
        {"title": "N", "summary": "s", "symbols": ["NVDA"],
         "published_at": "2026-07-08T11:00:00Z", "url": "u", "source": "nf"},
    ]})
    newsfilter = ls._fetch_newsfilter(["NVDA"])
    assert newsfilter["catalysts"][0]["source"] == "Newsfilter / nf"
    assert newsfilter["catalysts"][0]["published_at"] == "2026-07-08T11:00:00Z"


def test_fetch_live_catalysts_dedupes_and_sorts(monkeypatch):
    item = {"ticker": "NVDA", "headline": "H", "summary": "", "source": "S",
            "source_url": "", "published_at": "2026-07-08T10:00:00Z",
            "security_type": "stock", "exchange": ""}
    newer = {**item, "headline": "H2", "published_at": "2026-07-08T12:00:00Z"}
    ok = {"name": "A", "status": "ok", "catalysts": [item, dict(item), newer], "count": 3}
    disabled = ls._disabled("B", "off")
    for fetcher in ("_fetch_sec_filings", "_fetch_polygon_news", "_fetch_benzinga_news",
                    "_fetch_benzinga_insiders", "_fetch_tiingo_news", "_fetch_yahoo_news"):
        monkeypatch.setattr(ls, fetcher, lambda symbols: disabled)
    monkeypatch.setattr(ls, "_fetch_newsfilter", lambda symbols: ok)
    result = ls.fetch_live_catalysts(["NVDA"])
    assert result["status"] == "ok"
    assert [c["headline"] for c in result["catalysts"]] == ["H2", "H"]   # deduped + desc


def test_error_envelope_redacts_secrets(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "supersecret123")

    def boom(url, **kwargs):
        raise RuntimeError("HTTP 401 at https://api.polygon.io/x?apiKey=supersecret123")

    monkeypatch.setattr(ls, "_fetch_json", boom)
    result = ls._fetch_polygon_news(["NVDA"])
    assert result["status"] == "error"
    assert "supersecret123" not in result["reason"]
    assert "redacted" in result["reason"]


def test_yahoo_news_parses_ticker_and_macro_feeds(monkeypatch):
    monkeypatch.setenv("YAHOO_NEWS_ENABLED", "true")
    monkeypatch.setenv("YAHOO_NEWS_MACRO_SYMBOLS", "^GSPC")

    def fake_rss(url):
        if "%5EGSPC" in url:      # quoted ^GSPC
            return [{"title": "Oil prices jump as US-Iran deal is 'over'",
                     "description": "Crude surges; bond yields climb.",
                     "link": "https://finance.yahoo.com/macro-1",
                     "pubDate": "Wed, 08 Jul 2026 13:08:00 +0000"}]
        return [{"title": "NVIDIA supplier expands capacity",
                 "description": "Supply chain read.",
                 "link": "https://finance.yahoo.com/nvda-1",
                 "pubDate": "Wed, 08 Jul 2026 12:00:00 +0000"}]

    monkeypatch.setattr(ls, "_fetch_rss", fake_rss)
    result = ls._fetch_yahoo_news(["NVDA"])
    assert result["status"] == "ok" and result["count"] == 2
    by_url = {row["source_url"]: row for row in result["catalysts"]}
    ticker_row = by_url["https://finance.yahoo.com/nvda-1"]
    assert ticker_row["ticker"] == "NVDA"
    assert ticker_row["source"] == "Yahoo Finance News"
    assert ticker_row["published_at"] == "2026-07-08T12:00:00+00:00"
    macro_row = by_url["https://finance.yahoo.com/macro-1"]
    assert macro_row["ticker"] == ""          # macro items carry no ticker


def test_yahoo_macro_headlines_classify_as_non_tradeable_context(monkeypatch):
    # End-to-end guarantee: a war/macro headline ingested via the macro feed
    # can never become a trade candidate — the classifier routes tickerless
    # broad-market language away from direct_company_catalyst.
    from alpha_lab.catalysts import classify_catalyst, score_catalyst

    row = {"ticker": "", "headline": "Bond yields jump as surging oil prices spark inflation fears",
           "summary": "Macro headline via Yahoo RSS", "source": "Yahoo Finance News",
           "published_at": "2026-07-08T13:08:00Z"}
    category, _ = classify_catalyst(row)
    assert category in {"broad_market_mention", "low_actionability"}
    scored = score_catalyst(row)
    assert scored["trade_candidate"] is False


def test_yahoo_respects_symbol_cap(monkeypatch):
    monkeypatch.setenv("YAHOO_NEWS_ENABLED", "true")
    monkeypatch.setenv("YAHOO_NEWS_MAX_SYMBOLS", "2")
    monkeypatch.setenv("YAHOO_NEWS_MACRO_SYMBOLS", "")
    calls = []
    monkeypatch.setattr(ls, "_fetch_rss", lambda url: calls.append(url) or [])
    ls._fetch_yahoo_news(["NVDA", "MSFT", "AMD", "TSLA"])
    assert len(calls) == 2                    # capped, no macro configured


def test_alpaca_intraday_parses_snapshot(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: {
        "latestTrade": {"p": 159.36},
        "dailyBar": {"c": 159.36, "v": 88711},
        "prevDailyBar": {"c": 155.0, "v": 152109},
    })
    snap = ls.fetch_alpaca_intraday("coin")
    assert snap["status"] == "ok" and snap["ticker"] == "COIN"
    assert round(snap["gap_pct"], 4) == round((159.36 - 155.0) / 155.0 * 100, 4)
    assert round(snap["relative_volume"], 6) == round(88711 / 152109, 6)


def test_alpaca_intraday_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(ls, "_fetch_json", _no_network)
    assert ls.fetch_alpaca_intraday("COIN")["status"] == "disabled"


def test_alpaca_intraday_handles_missing_bars(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setattr(ls, "_fetch_json", lambda url, **kw: {"latestTrade": {"p": 10.0}})
    snap = ls.fetch_alpaca_intraday("XYZ")
    assert snap["status"] == "ok"
    assert snap["gap_pct"] is None and snap["relative_volume"] is None   # neutral downstream
