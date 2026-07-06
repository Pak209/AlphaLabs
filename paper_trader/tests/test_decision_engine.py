from pathlib import Path

from paper_trader.audit_log import AuditLog
from paper_trader.decision_engine import evaluate_signal, serialize_decision
from paper_trader.models import RiskConfig, Signal


class FakeBroker:
    def __init__(self, positions=None, market_open=True, account=None, price=100):
        self.positions = positions or []
        self.market_open = market_open
        self.account = account or {"equity": "100000", "cash": "100000", "last_equity": "100000"}
        self.price = price

    def get_account(self):
        return self.account

    def get_positions(self):
        return self.positions

    def get_clock(self):
        return {"is_open": self.market_open}

    def get_latest_trade_price(self, symbol):
        return self.price


def config():
    return RiskConfig(
        min_confidence=0.75,
        max_position_size_usd=500,
        max_equity_pct_per_trade=0.02,
        max_trades_per_day=5,
        max_open_positions=3,
        approved_tickers={"NVDA"},
        stop_loss_pct=0.04,
        take_profit_pct=0.08,
        max_daily_drawdown_pct=0.03,
    )


def crypto_config(**overrides):
    base = {
        "min_confidence": 0.75,
        "max_position_size_usd": 250,
        "max_equity_pct_per_trade": 0.01,
        "max_trades_per_day": 3,
        "max_open_positions": 2,
        "approved_tickers": {"BTC/USD", "ETH/USD", "SOL/USD"},
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.06,
        "max_daily_drawdown_pct": 0.02,
        "allow_short": True,
    }
    base.update(overrides)
    return RiskConfig(**base)


def signal(**overrides):
    payload = {
        "ticker": "NVDA",
        "bias": "bullish",
        "confidence": 0.8,
        "timeframe": "intraday",
        "reason": "relative strength",
        "source": "market_scan_bot",
        "timestamp": "2026-06-04T13:00:00Z",
    }
    payload.update(overrides)
    return Signal.from_dict(payload)


def test_accepts_valid_dry_run(tmp_path: Path):
    decision = evaluate_signal(signal(), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"), dry_run=True)
    assert decision.accepted is True
    assert decision.action == "dry_run"
    assert decision.order_payload["symbol"] == "NVDA"
    assert decision.order_payload["notional"] == 500


def test_alpha_rides_through_decision(tmp_path: Path):
    alpha = {"composite_score": 82.5, "tier": "high_conviction"}
    decision = evaluate_signal(
        signal(), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"),
        dry_run=True, alpha=alpha,
    )
    assert decision.alpha == alpha
    assert serialize_decision(decision)["alpha"] == alpha


def test_alpha_defaults_to_none(tmp_path: Path):
    decision = evaluate_signal(signal(), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"))
    assert decision.alpha is None
    assert serialize_decision(decision)["alpha"] is None


def test_rejects_low_confidence(tmp_path: Path):
    decision = evaluate_signal(signal(confidence=0.5), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"))
    assert decision.accepted is False
    assert "confidence" in decision.reasons[0]


def test_rejects_duplicate_position(tmp_path: Path):
    broker = FakeBroker(positions=[{"symbol": "NVDA"}])
    decision = evaluate_signal(signal(), config(), broker, AuditLog(tmp_path / "log.jsonl"))
    assert decision.accepted is False
    assert "duplicate position already open" in decision.reasons


def test_rejects_closed_market(tmp_path: Path):
    decision = evaluate_signal(signal(), config(), FakeBroker(market_open=False), AuditLog(tmp_path / "log.jsonl"))
    assert decision.accepted is False
    assert "market is closed" in decision.reasons


def test_allows_crypto_when_market_is_closed(tmp_path: Path):
    decision = evaluate_signal(
        signal(ticker="BTC/USD", asset_type="crypto"),
        crypto_config(),
        FakeBroker(market_open=False),
        AuditLog(tmp_path / "log.jsonl"),
        dry_run=True,
    )
    assert decision.accepted is True
    assert decision.order_payload["symbol"] == "BTC/USD"


def test_crypto_risk_limits_still_apply_when_market_is_closed(tmp_path: Path):
    decision = evaluate_signal(
        signal(ticker="BTC/USD", asset_type="crypto"),
        crypto_config(max_open_positions=1),
        FakeBroker(market_open=False, positions=[{"symbol": "ETH/USD"}]),
        AuditLog(tmp_path / "log.jsonl"),
        dry_run=True,
    )
    assert decision.accepted is False
    assert "max open positions reached" in decision.reasons


def test_crypto_duplicate_position_normalizes_slash_symbols(tmp_path: Path):
    decision = evaluate_signal(
        signal(ticker="BTC/USD", asset_type="crypto"),
        crypto_config(),
        FakeBroker(market_open=False, positions=[{"symbol": "BTCUSD"}]),
        AuditLog(tmp_path / "log.jsonl"),
        dry_run=True,
    )
    assert decision.accepted is False
    assert "duplicate position already open" in decision.reasons


def test_rejects_daily_drawdown(tmp_path: Path):
    broker = FakeBroker(account={"equity": "96000", "last_equity": "100000"})
    decision = evaluate_signal(signal(), config(), broker, AuditLog(tmp_path / "log.jsonl"))
    assert decision.accepted is False
    assert "max daily drawdown reached" in decision.reasons


# ─── Gate-trace telemetry (observability only; decisions must be unchanged) ───

def test_accepted_decision_records_all_gates_passed(tmp_path: Path):
    decision = evaluate_signal(signal(), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"), dry_run=True)
    assert decision.accepted is True
    assert decision.gate_results is not None
    assert all(record["passed"] for record in decision.gate_results)
    gate_names = [record["gate"] for record in decision.gate_results]
    assert "confidence" in gate_names
    assert "watchlist" in gate_names
    assert "market_open" in gate_names
    # Bullish equity signal: short-guards do not apply and must not be recorded.
    assert "short_allowed" not in gate_names
    assert "crypto_long_only" not in gate_names
    assert serialize_decision(decision)["first_failed_gate"] is None


def test_rejected_confidence_records_observed_vs_threshold(tmp_path: Path):
    decision = evaluate_signal(signal(confidence=0.5), config(), FakeBroker(), AuditLog(tmp_path / "log.jsonl"))
    assert decision.accepted is False
    assert decision.reasons == ["confidence 0.50 below threshold 0.75"]
    record = next(r for r in decision.gate_results if r["gate"] == "confidence")
    assert record["passed"] is False
    assert record["observed"] == 0.5
    assert record["threshold"] == 0.75
    assert record["comparator"] == ">="
    assert record["detail"] == "confidence 0.50 below threshold 0.75"
    assert serialize_decision(decision)["first_failed_gate"] == "confidence"


def test_gate_trace_records_first_failure_in_gate_order(tmp_path: Path):
    # Low confidence AND closed market: both recorded, confidence fails first.
    decision = evaluate_signal(
        signal(confidence=0.5), config(), FakeBroker(market_open=False), AuditLog(tmp_path / "log.jsonl")
    )
    failed = [r["gate"] for r in decision.gate_results if not r["passed"]]
    assert failed == ["confidence", "market_open"]
    assert serialize_decision(decision)["first_failed_gate"] == "confidence"


def test_bearish_crypto_records_long_only_gate(tmp_path: Path):
    decision = evaluate_signal(
        signal(ticker="BTC/USD", asset_type="crypto", bias="bearish"),
        crypto_config(),
        FakeBroker(market_open=False),
        AuditLog(tmp_path / "log.jsonl"),
    )
    assert decision.accepted is False
    record = next(r for r in decision.gate_results if r["gate"] == "crypto_long_only")
    assert record["passed"] is False
    # Crypto never evaluates the equity market-open gate.
    assert "market_open" not in [r["gate"] for r in decision.gate_results]


def test_gate_context_captures_broker_state_inputs(tmp_path: Path):
    broker = FakeBroker(positions=[{"symbol": "NVDA"}], account={"equity": "96000", "last_equity": "100000"})
    decision = evaluate_signal(signal(), config(), broker, AuditLog(tmp_path / "log.jsonl"))
    context = decision.gate_context
    assert context["open_positions"] == 1
    assert context["position_tickers"] == ["NVDA"]
    assert context["has_position_in_ticker"] is True
    assert context["equity"] == 96000.0
    assert context["last_equity"] == 100000.0
    assert context["drawdown_pct"] == 0.04
    assert context["config"]["min_confidence"] == 0.75
    # Behavior unchanged: same rejection reasons as before instrumentation.
    assert "duplicate position already open" in decision.reasons
    assert "max daily drawdown reached" in decision.reasons
