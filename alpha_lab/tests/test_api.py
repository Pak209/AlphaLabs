import json
from pathlib import Path

from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.catalysts import get_catalyst_radar
from alpha_lab.service import AlphaLabService


def test_health_and_idea_flow(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    client = TestClient(create_app(lab))

    assert client.get("/api/health").json()["status"] == "ok"
    response = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.82,
            "timeframe": "intraday",
            "thesis": "AI infrastructure momentum with relative strength.",
            "source": "test",
            "timestamp": "2026-06-04T13:00:00Z",
            "strategy_tags": ["AI bottleneck"],
        },
    )
    assert response.status_code == 200
    idea_id = response.json()["id"]

    decision = client.post(f"/api/ideas/{idea_id}/dry-run-trade")
    assert decision.status_code == 200
    assert decision.json()["accepted"] is True

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["counts"]["ideas_today"] >= 1
    assert dashboard["counts"]["dry_run_tests_today"] == 1
    assert dashboard["counts"]["paper_orders_today"] == 0


def test_import_and_test_endpoint(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_import.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_import.jsonl"),
    )
    client = TestClient(create_app(lab))
    response = client.post(
        "/api/ideas/import-and-test",
        json={"signals": [{
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.82,
            "timeframe": "intraday",
            "thesis": "AI infrastructure momentum with relative strength.",
            "source": "automation_test",
            "timestamp": "2026-06-04T13:00:00Z",
            "strategy_tags": ["AI bottleneck"],
        }]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["results"][0]["test_result"]["accepted"] is True


def test_string_false_dry_run_is_not_treated_as_true(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_bool.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_bool.jsonl"),
    )
    client = TestClient(create_app(lab))
    monkeypatch.delenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", raising=False)

    response = client.post("/api/ideas/test-new", json={"dry_run": "false"})

    assert response.status_code == 400
    assert "paper testing is disabled" in response.json()["detail"]


def test_trending_strategy_endpoint_uses_guardrails(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_trending.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_trending.jsonl"),
    )
    client = TestClient(create_app(lab))
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: __import__("paper_trader.simulated_broker", fromlist=["SimulatedPaperBroker"]).SimulatedPaperBroker(market_open=True))

    monkeypatch.setattr(
        "alpha_lab.service.build_trending_stock_signals",
        lambda limit=3: [{
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.88,
            "timeframe": "intraday",
            "reason": "NVDA high-volume EMA hold candidate.",
            "source": "test_trending_liquidity",
            "timestamp": "2026-06-04T13:00:00Z",
            "strategy_tags": ["liquidity momentum"],
            "theme": "Trending liquidity",
        }],
    )

    response = client.post("/api/strategies/test-trending", json={"dry_run": True, "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["signals_created"] == 1
    assert body["results"][0]["test_result"]["accepted"] is True


def test_trending_scanner_switches_to_btc_when_market_closed(tmp_path: Path, monkeypatch):
    from paper_trader.simulated_broker import SimulatedPaperBroker

    lab = AlphaLabService(
        db_path=str(tmp_path / "api_after_hours_switch.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_after_hours_switch.jsonl"),
    )
    client = TestClient(create_app(lab))
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker(market_open=False))
    monkeypatch.setattr(
        "alpha_lab.service.get_bitcoin_market",
        lambda: {
            "status": "ok",
            "ticker": "BTC/USD",
            "price": 65000,
            "change_24h_pct": 1.2,
            "change_7d_pct": 3.4,
            "change_14d_pct": 5.6,
            "volume_24h": 41000000000,
            "last_updated": "2026-06-09T13:00:00Z",
            "fetched_at": "2026-06-09T13:01:00Z",
            "source": "unit_test_coingecko",
            "bias": "bullish",
            "summary": "BTC is bid while equities are closed.",
            "indicators": {"ema20": 64000, "ema50": 62000, "rsi14": 58, "support_14d_close": 61000, "resistance_14d_close": 67000, "ema_read": "Price is above the 20D and 50D EMA."},
            "scenarios": [],
        },
    )
    response = client.post("/api/strategies/test-trending", json={"dry_run": True, "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "after_hours_btc"
    assert body["results"][0]["idea"]["asset_type"] == "crypto"


def test_catalyst_radar_scores_and_imports_candidates(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_catalyst.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_catalyst.jsonl"),
    )
    client = TestClient(create_app(lab))

    radar = client.post(
        "/api/catalysts/score",
        json={
            "catalysts": [{
                "ticker": "NVDA",
                "headline": "NVIDIA partner signs AI infrastructure contract",
                "summary": "Source-backed contract catalyst for AI infrastructure demand.",
                "source": "unit_test_news",
                "published_at": "2026-06-08T13:00:00Z",
            }]
        },
    )
    assert radar.status_code == 200
    assert radar.json()["signals"][0]["ticker"] == "NVDA"

    imported = client.post(
        "/api/catalysts/import-and-test",
        json={
            "execution_mode": "dry_run",
            "catalysts": [{
                "ticker": "NVDA",
                "headline": "NVIDIA partner signs AI infrastructure contract",
                "summary": "Source-backed contract catalyst for AI infrastructure demand.",
                "source": "unit_test_news",
                "published_at": "2026-06-08T13:00:00Z",
            }],
        },
    )
    assert imported.status_code == 200
    body = imported.json()
    assert len(body["signals"]) == 1
    assert body["test_result"]["dry_run"] is True


def test_catalyst_intelligence_persists_scores_and_dashboard(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_catalyst_intel.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_catalyst_intel.jsonl"),
    )
    client = TestClient(create_app(lab))

    response = client.post(
        "/api/catalysts/intelligence",
        json={
            "persist": True,
            "generate_ideas": True,
            "dry_run": True,
            "catalysts": [{
                "ticker": "PLTR",
                "sector": "AI software",
                "headline": "Palantir awarded government contract for artificial intelligence platform",
                "summary": "Government contract expands AI platform deployment and includes source-backed award language.",
                "source": "SEC EDGAR / Business Wire",
                "source_url": "https://example.com/pltr-contract",
                "published_at": "2026-06-16T13:00:00Z",
            }],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["catalysts"][0]["catalyst_score"] >= 68
    assert body["catalysts"][0]["strategy_label"] in {"AI Catalyst", "Government Contract"}
    assert body["signals"][0]["catalyst_event_id"]
    assert body["test_result"]["dry_run"] is True

    dashboard = client.get("/api/catalysts/intelligence").json()["dashboard"]
    assert dashboard["top_catalysts"][0]["ticker"] == "PLTR"
    assert dashboard["top_catalysts"][0]["explanation"]
    assert dashboard["strategy_performance"]


def test_live_catalyst_poll_handles_disabled_providers(tmp_path: Path, monkeypatch):
    for key in ["SEC_USER_AGENT", "POLYGON_API_KEY", "BENZINGA_API_KEY", "TIINGO_API_KEY", "NEWSFILTER_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_live_catalyst.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_live_catalyst.jsonl"),
    )
    client = TestClient(create_app(lab))

    radar = client.get("/api/catalysts/radar?live=true")
    assert radar.status_code == 200
    body = radar.json()
    assert body["mode"] == "sample_fallback"
    assert all(provider["status"] == "disabled" for provider in body["live_status"]["providers"])

    poll = client.post("/api/catalysts/poll", json={"dry_run": True})
    assert poll.status_code == 200
    assert poll.json()["test_result"]["dry_run"] is True


def test_daily_brief_builds_strict_signals_and_dry_runs(tmp_path: Path, monkeypatch):
    for key in ["SEC_USER_AGENT", "POLYGON_API_KEY", "BENZINGA_API_KEY", "TIINGO_API_KEY", "NEWSFILTER_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_daily_brief.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_daily_brief.jsonl"),
    )
    client = TestClient(create_app(lab))

    brief = client.get("/api/brief/daily?live_catalysts=true")
    assert brief.status_code == 200
    body = brief.json()
    assert body["brief_type"] == "daily_market_brief"
    assert isinstance(body["signals"], list)
    for signal in body["signals"]:
        assert {"ticker", "bias", "confidence", "timeframe", "reason", "source", "timestamp"}.issubset(signal)

    fed = client.post("/api/brief/daily/import-and-test", json={"dry_run": True, "live_catalysts": True})
    assert fed.status_code == 200
    assert fed.json()["test_result"]["dry_run"] is True


def test_catalyst_radar_separates_news_categories():
    radar = get_catalyst_radar(
        {
            "catalysts": [
                {
                    "ticker": "SMCI",
                    "headline": "Super Micro announces registered direct offering",
                    "summary": "Company announces registered direct offering.",
                    "source": "Polygon News / GlobeNewswire Inc.",
                    "published_at": "2026-06-09T13:00:00Z",
                    "related_tickers": ["SMCI"],
                },
                {
                    "ticker": "AAPL",
                    "headline": "Market Indexes Retreat Tuesday as the Tech Sell-Off Returns",
                    "summary": "Nasdaq and S&P 500 fell as tech stocks broadly declined.",
                    "source": "Polygon News / The Motley Fool",
                    "published_at": "2026-06-09T14:00:00Z",
                    "related_tickers": ["AAPL", "NVDA", "MSFT"],
                },
                {
                    "ticker": "NVDA",
                    "headline": "Defense stocks on watch after geopolitical headlines",
                    "summary": "Sector ETFs and suppliers may see read-through.",
                    "source": "Polygon News / Benzinga",
                    "published_at": "2026-06-09T15:00:00Z",
                    "related_tickers": ["NVDA", "PLTR", "AVGO"],
                },
                {
                    "ticker": "AMZN",
                    "headline": "Should You Buy Amazon on the Dip?",
                    "summary": "Opinion article discussing billionaire favorite stocks.",
                    "source": "Polygon News / The Motley Fool",
                    "published_at": "2026-06-09T16:00:00Z",
                    "related_tickers": ["AMZN"],
                },
                {
                    "ticker": "NVDA",
                    "headline": "AI stocks rally as Nasdaq rebounds before Fed decision",
                    "summary": "The article mentions Nvidia and semiconductor momentum, but it is market-wide context rather than a company announcement.",
                    "source": "Polygon News / Market Commentary",
                    "published_at": "2026-06-09T17:00:00Z",
                    "related_tickers": ["NVDA", "AMD", "AVGO"],
                },
                {
                    "ticker": "TSLA",
                    "headline": "Tesla supplier wins battery materials contract",
                    "summary": "Supplier news may matter for the EV chain, but this is a read-through instead of a direct Tesla catalyst.",
                    "source": "Polygon News / Business Wire",
                    "published_at": "2026-06-09T18:00:00Z",
                    "related_tickers": ["TSLA", "QS", "ALB"],
                },
            ]
        }
    )
    categories = radar["categories"]
    assert categories["direct_company_catalysts"][0]["ticker"] == "SMCI"
    assert [item["ticker"] for item in categories["broad_market_mentions"]] == ["NVDA", "AAPL"]
    assert [item["ticker"] for item in categories["sympathy_sector_reads"]] == ["TSLA", "NVDA"]
    assert categories["low_actionability_articles"][0]["ticker"] == "AMZN"
    assert [signal["ticker"] for signal in radar["signals"]] == ["SMCI"]
    # Every scored catalyst carries a deterministic MVP Analyst Brain score.
    smci = categories["direct_company_catalysts"][0]
    assert smci["alpha"]["tier"] in {"high_conviction", "tradeable", "watchlist", "ignore"}
    assert 0 <= smci["alpha"]["composite_score"] <= 100
    assert "composite_explanation" in smci["alpha"]
    assert radar["signals"][0]["alpha"] is not None


def test_approval_dashboard_endpoint_flow(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_approvals.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_approvals.jsonl"),
    )
    client = TestClient(create_app(lab))

    def assisted_explanation(signal, context):
        return {
            "thesis_summary": "NVDA direct catalyst thesis",
            "catalyst": "New AI infrastructure contract",
            "why_this_matters": "Could affect liquidity and attention.",
            "market_context": "Mixed risk tape.",
            "setup_type": "direct company catalyst",
            "confidence_score": 0.86,
            "risk_factors": ["headline may be priced in", "market may be closed"],
            "invalidation_level_or_condition": "Fails to hold catalyst reaction level",
            "suggested_entry_zone": "confirmation above trigger",
            "suggested_stop_loss": "configured stop",
            "suggested_take_profit": "configured take profit",
            "time_horizon": "intraday",
            "source_refs": ["unit_test_news @ 2026-06-09T13:00:00Z"],
            "analyst_mode": "anthropic",
            "analyst_assisted": True,
        }

    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    response = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.86,
            "timeframe": "intraday",
            "thesis": "NVDA direct catalyst thesis.",
            "catalyst": "New AI infrastructure contract",
            "source": "unit_test_news",
            "timestamp": "2026-06-09T13:00:00Z",
            "strategy_tags": ["news catalyst"],
        },
    )
    assert response.status_code == 200
    idea_id = response.json()["id"]

    pending = client.get("/api/ideas/pending-approval")
    assert pending.status_code == 200
    queue = pending.json()
    assert len(queue) == 1
    assert queue[0]["ticker"] == "NVDA"
    assert queue[0]["status"] == "needs_review"
    explanation = queue[0]["trade_explanation"]["explanation"]
    assert explanation["setup_type"] == "direct company catalyst"
    assert explanation["suggested_entry_zone"] == "confirmation above trigger"
    assert explanation["risk_factors"][0] == "headline may be priced in"

    detail = client.get(f"/api/ideas/{idea_id}/explanation")
    assert detail.status_code == 200
    assert detail.json()["explanation"]["thesis_summary"] == "NVDA direct catalyst thesis"

    approved = client.post(f"/api/ideas/{idea_id}/approval/approve", json={"note": "approved in dashboard"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.get("/api/ideas/pending-approval").json() == []


def test_rejected_approval_leaves_queue_and_does_not_execute(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_approval_reject.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_approval_reject.jsonl"),
    )
    client = TestClient(create_app(lab))

    def assisted_explanation(signal, context):
        return {
            "thesis_summary": "Rejected thesis",
            "catalyst": "Weak catalyst",
            "why_this_matters": "Needs review.",
            "market_context": "Mixed",
            "setup_type": "direct company catalyst",
            "confidence_score": 0.86,
            "risk_factors": ["weak source"],
            "invalidation_level_or_condition": "invalidated",
            "suggested_entry_zone": "n/a",
            "suggested_stop_loss": "n/a",
            "suggested_take_profit": "n/a",
            "time_horizon": "intraday",
            "source_refs": ["unit_test"],
            "analyst_mode": "anthropic",
            "analyst_assisted": True,
        }

    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    created = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.86,
            "timeframe": "intraday",
            "thesis": "Rejected thesis.",
            "source": "unit_test_news",
            "timestamp": "2026-06-09T13:00:00Z",
        },
    ).json()
    idea_id = created["id"]
    rejected = client.post(f"/api/ideas/{idea_id}/approval/reject", json={"note": "not clean enough"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get("/api/ideas/pending-approval").json() == []

    paper = client.post(f"/api/ideas/{idea_id}/paper-trade")
    assert paper.status_code == 200
    assert paper.json()["action"] == "approval_rejected"


def test_execution_audit_performance_and_scoreboard_endpoints(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_cockpit.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_cockpit.jsonl"),
    )
    client = TestClient(create_app(lab))

    created = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.86,
            "timeframe": "intraday",
            "thesis": "NVDA direct catalyst thesis.",
            "catalyst": "New AI infrastructure contract",
            "source": "unit_test_news",
            "source_url": "https://example.com/nvda",
            "timestamp": "2026-06-09T13:00:00Z",
            "strategy_tags": ["news catalyst"],
        },
    ).json()

    trade = client.post(f"/api/ideas/{created['id']}/dry-run-trade")
    assert trade.status_code == 200
    assert trade.json()["accepted"] is True

    audit = client.get("/api/execution-audit").json()
    assert audit[0]["idea_id"] == created["id"]
    assert audit[0]["ticker"] == "NVDA"
    assert audit[0]["status"] == "dry_run"
    assert audit[0]["timestamp"] == audit[0]["created_at"]

    performance = client.get("/api/performance/ideas").json()
    row = next(item for item in performance if item["id"] == created["id"])
    assert row["ticker"] == "NVDA"
    assert "current_price" in row
    assert "percent_return" in row
    assert row["trade_explanation"]["source_refs"][0]["url"] == "https://example.com/nvda"
    assert row["stop_target_status"] in {"open", "not executed", "closed", "stop watch", "target watch"}

    scoreboard = client.get("/api/performance/scoreboard").json()
    assert {"by_setup_type", "by_catalyst_type", "by_ticker", "by_confidence_bucket", "by_time_horizon"}.issubset(scoreboard)
    assert any(item["group"] == "NVDA" for item in scoreboard["by_ticker"])

    strategies = client.get("/api/stats/strategies").json()
    news = next(row for row in strategies if row["strategy"] == "news catalyst")
    assert news["dry_run_trades"] == 1
    assert news["paper_trades"] == 0
    assert news["recent_trades"][0]["ticker"] == "NVDA"

    diagnostics = client.get("/api/stats/strategies/diagnostics").json()
    assert diagnostics["trades_missing_strategy_labels"] == 0
    assert diagnostics["has_strategy_stats"] is True


def test_market_briefing_generate_and_list_endpoint(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_briefing_screen.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_briefing_screen.jsonl"),
    )
    client = TestClient(create_app(lab))
    monkeypatch.setattr(
        lab,
        "build_daily_brief",
        lambda live_catalysts=True: {
            "brief_type": "daily_market_brief",
            "generated_at": "2026-06-09T13:00:00Z",
            "regime": {"posture": "mixed"},
            "sections": {
                "catalysts": {"catalysts": [{"ticker": "NVDA", "headline": "NVIDIA signs AI contract"}]},
                "trending_stocks": {"stocks": []},
                "liquidity": {"groups": []},
            },
            "signals": [{"ticker": "NVDA"}],
        },
    )
    generated = client.post("/api/briefings/daily/generate", json={"live_catalysts": False})
    assert generated.status_code == 200
    payload = generated.json()["payload"]
    assert payload["broad_market_tone"] == "mixed"
    assert payload["strongest_catalysts_found"][0]["ticker"] == "NVDA"

    listed = client.get("/api/briefings").json()
    assert listed[0]["id"] == generated.json()["id"]


def test_after_hours_btc_generates_crypto_approval_idea(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_after_hours_btc.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_after_hours_btc.jsonl"),
    )
    client = TestClient(create_app(lab))
    btc_payload = {
        "status": "ok",
        "ticker": "BTC/USD",
        "price": 65000,
        "change_24h_pct": 2.1,
        "change_7d_pct": 4.2,
        "change_14d_pct": 8.4,
        "volume_24h": 42000000000,
        "last_updated": "2026-06-09T13:00:00Z",
        "fetched_at": "2026-06-09T13:01:00Z",
        "source": "unit_test_coingecko",
        "bias": "bullish",
        "summary": "BTC is reclaiming short-term momentum.",
        "indicators": {
            "ema20": 64000,
            "ema50": 62000,
            "rsi14": 58,
            "support_14d_close": 61000,
            "resistance_14d_close": 67000,
            "ema_read": "Price is above the 20D and 50D EMA.",
        },
        "scenarios": [],
    }
    monkeypatch.setattr("alpha_lab.service.get_bitcoin_market", lambda: btc_payload)
    monkeypatch.setattr("alpha_lab.service.get_liquidity_flows", lambda: {"groups": [{"name": "Crypto Majors", "status": "ok", "volume_read": "risk-on", "source": "unit_test"}]})

    panel = client.get("/api/after-hours/btc")
    assert panel.status_code == 200
    assert panel.json()["asset_type"] == "crypto"
    assert panel.json()["risk_status"]["max_position_size_usd"] == 250

    generated = client.post("/api/after-hours/btc/generate")
    assert generated.status_code == 200
    idea = generated.json()["idea"]
    assert idea["ticker"] == "BTC/USD"
    assert idea["asset_type"] == "crypto"
    assert "Entry" in idea["thesis"]
    assert "target" in idea["thesis"]

    pending = client.get("/api/ideas/pending-approval").json()
    assert pending[0]["ticker"] == "BTC/USD"


def test_trades_expose_signal_breakdown_fields(tmp_path: Path):
    """The dashboard's signal-breakdown panel renders straight off /api/trades rows.
    Guard the data contract: every field the panel reads must be present, and with
    the stub providers (no options/dark-pool feed) the modifiers report no data."""
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_breakdown.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_breakdown.jsonl"),
    )
    client = TestClient(create_app(lab))

    idea_id = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.82,
            "timeframe": "intraday",
            "thesis": "AI infrastructure momentum with relative strength.",
            "source": "test",
            "timestamp": "2026-06-04T13:00:00Z",
            "strategy_tags": ["AI bottleneck"],
        },
    ).json()["id"]
    assert client.post(f"/api/ideas/{idea_id}/dry-run-trade").status_code == 200

    trades = client.get("/api/trades").json()
    assert trades, "expected a logged dry-run trade"
    trade = trades[0]

    # Core score fields the panel reads directly.
    for field in (
        "alpha_composite", "alpha_tier", "confirmed", "gate_applied",
        "catalyst_score", "price_volume_score", "narrative_score", "macro_score",
        "options_component", "options_bias", "options_flow_json",
        "institutional_component", "institutional_bias", "institutional_json",
    ):
        assert field in trade, f"missing dashboard field: {field}"

    assert trade["alpha_composite"] is not None
    assert trade["alpha_tier"] in ("ignore", "watchlist", "tradeable", "high_conviction")

    # Stub providers return no data -> modifiers must surface has_data False so the
    # panel shows the "no provider data" indicator rather than a fake score.
    flow = json.loads(trade["options_flow_json"])
    inst = json.loads(trade["institutional_json"])
    assert flow["has_data"] is False
    assert inst["has_data"] is False
