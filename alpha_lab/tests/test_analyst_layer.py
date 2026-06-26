import json
from pathlib import Path

from alpha_lab import analyst
from alpha_lab.service import AlphaLabService
from paper_trader.simulated_broker import SimulatedPaperBroker


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "analyst.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def idea_payload():
    return {
        "ticker": "NVDA",
        "bias": "bullish",
        "confidence": 0.86,
        "timeframe": "intraday",
        "thesis": "NVDA catalyst momentum with paper-testable liquidity.",
        "catalyst": "AI infrastructure order headline.",
        "source": "unit_test",
        "timestamp": "2026-06-09T13:00:00Z",
        "strategy_tags": ["news catalyst"],
    }


class _Dump:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self) -> dict:
        return self.payload


def force_tradeable_alpha(lab: AlphaLabService, monkeypatch):
    monkeypatch.setattr(
        lab,
        "_score_idea",
        lambda idea: (
            _Dump({
                "tier": "tradeable",
                "composite_score": 72.0,
                "confirmed": True,
                "gate_applied": False,
                "catalyst_score": 80.0,
                "price_volume_score": 72.0,
                "narrative_score": 75.0,
                "macro_score": 62.2,
            }),
            _Dump({"options_score": 0, "component_score": 50.0, "bias": "neutral"}),
            _Dump({"institutional_score": 0, "component_score": 50.0, "bias": "neutral"}),
        ),
    )


def assisted_explanation(signal, context):
    payload = analyst.build_trade_explanation(signal, context)
    payload["analyst_mode"] = "anthropic"
    payload["analyst_assisted"] = True
    return payload


def test_mock_analyst_output_without_key_does_not_crash(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")
    explanation = analyst.build_trade_explanation(idea_payload(), {})
    assert explanation["analyst_mode"] == "mock"
    assert explanation["analyst_assisted"] is False
    assert "thesis_summary" in explanation
    assert isinstance(explanation["risk_factors"], list)


def test_analyst_layer_works_with_mocked_llm_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            content = {
                "thesis_summary": "Mocked LLM thesis",
                "catalyst": "Mock catalyst",
                "why_this_matters": "It may move attention.",
                "market_context": "Mixed tape.",
                "setup_type": "news catalyst",
                "confidence_score": 0.81,
                "risk_factors": ["stale catalyst"],
                "invalidation_level_or_condition": "headline contradicted",
                "suggested_entry_zone": "confirmation zone",
                "suggested_stop_loss": "configured stop",
                "suggested_take_profit": "configured target",
                "time_horizon": "intraday",
                "source_refs": ["unit_test"],
            }
            return json.dumps({"content": [{"type": "text", "text": json.dumps(content)}]}).encode("utf-8")

    monkeypatch.setattr("alpha_lab.analyst.urlopen", lambda request, timeout=30: FakeResponse())
    explanation = analyst.build_trade_explanation(idea_payload(), {})
    assert explanation["analyst_mode"] == "anthropic"
    assert explanation["analyst_assisted"] is True
    assert explanation["thesis_summary"] == "Mocked LLM thesis"


def test_reference_price_produces_numeric_trade_levels(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")
    explanation = analyst.build_trade_explanation(idea_payload(), {"reference_price": 100.0})
    # Bullish: stop 3% below, target at 2:1 reward-to-risk.
    assert explanation["suggested_entry_zone"].startswith("$")
    assert "$97.00" in explanation["suggested_stop_loss"]
    assert "$106.00" in explanation["suggested_take_profit"]
    assert explanation["trade_levels"]["stop"] == 97.0
    assert explanation["trade_levels"]["target"] == 106.0


def test_bearish_levels_flip_direction(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")
    explanation = analyst.build_trade_explanation({**idea_payload(), "bias": "bearish"}, {"reference_price": 100.0})
    assert "$103.00" in explanation["suggested_stop_loss"]
    assert "$94.00" in explanation["suggested_take_profit"]


def test_no_reference_price_keeps_qualitative_text(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")
    explanation = analyst.build_trade_explanation(idea_payload(), {})
    assert "trade_levels" not in explanation
    assert "$" not in explanation["suggested_entry_zone"]


def test_provider_order_prefers_anthropic_then_openai(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.delenv("LLM_PRIMARY", raising=False)
    assert analyst._llm_providers() == ["anthropic", "openai"]
    monkeypatch.setenv("LLM_PRIMARY", "openai")
    assert analyst._llm_providers() == ["openai", "anthropic"]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PRIMARY", "anthropic")
    assert analyst._llm_providers() == ["openai"]


def test_explanation_falls_back_to_openai_when_anthropic_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")

    def boom(signal, context):
        raise RuntimeError("Anthropic request failed: 529 overloaded")

    monkeypatch.setattr(analyst, "_anthropic_explanation", boom)
    monkeypatch.setattr(
        analyst,
        "_openai_explanation",
        lambda signal, context: {"thesis_summary": "OpenAI fallback thesis", "confidence_score": 0.7},
    )
    explanation = analyst.build_trade_explanation(idea_payload(), {})
    assert explanation["analyst_mode"] == "openai"
    assert explanation["analyst_assisted"] is True
    assert explanation["thesis_summary"] == "OpenAI fallback thesis"


def test_chat_uses_openai_when_only_openai_key_present(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_ANALYST_ENABLED", "true")
    monkeypatch.setattr(analyst, "_openai_chat", lambda message, context, history: "openai says hi")
    result = analyst.chat_reply("hello", {}, [])
    assert result["analyst_mode"] == "openai"
    assert result["reply"] == "openai says hi"


def test_llm_assisted_idea_requires_approval_before_paper_execution(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is False
    assert result["action"] == "needs_human_approval"
    assert lab.list_trades() == []


def test_paper_automation_can_skip_approval_when_enabled(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker())
    force_tradeable_alpha(lab, monkeypatch)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is True
    assert result["order_response"]["paper_simulated"] is True
    assert lab.list_trades()[0]["dry_run"] == 0


def test_crypto_idea_requires_approval_when_flag_enabled(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "true")
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker(market_open=False))
    idea = lab.create_idea({**idea_payload(), "ticker": "BTC/USD", "asset_type": "crypto", "strategy_tags": ["Bitcoin breakout"]})
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is False
    assert result["action"] == "needs_human_approval"
    assert "Crypto signal requires human approval" in result["reasons"][0]
    assert lab.list_trades() == []


def test_crypto_idea_skips_approval_when_flag_disabled(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker(market_open=False))
    force_tradeable_alpha(lab, monkeypatch)
    idea = lab.create_idea({**idea_payload(), "ticker": "BTC/USD", "asset_type": "crypto", "strategy_tags": ["Bitcoin breakout"]})
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is True
    assert result["order_response"]["paper_simulated"] is True
    assert lab.list_trades()[0]["dry_run"] == 0


def test_approved_idea_still_runs_risk_validation(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker())
    force_tradeable_alpha(lab, monkeypatch)
    idea = lab.create_idea(idea_payload())
    lab.approve_idea_for_execution(idea["id"], "approved for paper test")
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is True
    assert result["order_response"]["paper_simulated"] is True
    assert lab.list_trades()[0]["dry_run"] == 0


def test_rejected_idea_never_executes(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr("alpha_lab.service.build_trade_explanation", assisted_explanation)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker())
    idea = lab.create_idea(idea_payload())
    lab.reject_idea_for_execution(idea["id"], "do not trade")
    result = lab.place_trade(idea["id"], dry_run=False)
    assert result["accepted"] is False
    assert result["action"] == "approval_rejected"
    assert lab.list_trades() == []


def test_daily_briefing_can_be_generated_and_saved(tmp_path, monkeypatch):
    lab = service(tmp_path)
    monkeypatch.setattr(
        lab,
        "build_daily_brief",
        lambda live_catalysts=True: {
            "brief_type": "daily_market_brief",
            "generated_at": "2026-06-09T13:00:00Z",
            "regime": {"posture": "mixed"},
            "sections": {"catalysts": {"catalysts": []}, "trending_stocks": {"stocks": []}, "liquidity": {"groups": []}},
            "signals": [idea_payload()],
        },
    )
    saved = lab.generate_and_save_market_briefing()
    assert saved["payload"]["broad_market_tone"] == "mixed"
    assert lab.list_market_briefings()[0]["id"] == saved["id"]
