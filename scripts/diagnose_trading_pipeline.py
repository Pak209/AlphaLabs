#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.database import connect, resolve_db_path
from alpha_lab.service import AlphaLabService
from paper_trader.alpaca_client import AlpacaClient, AlpacaSafetyError, load_credentials_from_env, redact_secrets


def status(label: str, level: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"{level}: {label}{suffix}")


def load_local_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


def rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    # Resolve at call time (after load_local_env) so this reads the SAME env-pinned
    # DB the service uses, not the bare relative default.
    with connect(resolve_db_path()) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def alpaca_mode() -> str:
    base_url = os.getenv("ALPACA_PAPER_BASE_URL", "").strip()
    if base_url == "https://paper-api.alpaca.markets":
        return "paper"
    if "api.alpaca.markets" in base_url:
        return "live"
    return "unknown"


def scheduler_dry_run_status() -> str:
    mode = os.getenv("ALPHALAB_SCHEDULER_MODE", "dry_run").strip().lower()
    automation = os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").strip().lower() == "true"
    manual = os.getenv("ALPHALAB_ALLOW_MANUAL_PAPER_TRADES", "true").strip().lower() != "false"
    return f"scheduler_mode={mode or 'dry_run'}, automation_paper_enabled={automation}, manual_paper_enabled={manual}"


def alpaca_connectivity() -> tuple[str, str]:
    try:
        credentials = load_credentials_from_env()
        account = AlpacaClient(credentials).get_account()
        return "PASS", f"reachable paper_endpoint={credentials.base_url == 'https://paper-api.alpaca.markets'} account_status={account.get('status', 'unknown')}"
    except AlpacaSafetyError as exc:
        return "WARN", str(exc)
    except Exception as exc:
        return "WARN", redact_secrets(str(exc).splitlines()[0][:220])


def print_rejection_waterfall(service: AlphaLabService) -> None:
    """ASCII rejection waterfall: stage funnel with pass-through percentages,
    per-gate failure counts (structured traces + legacy reason parsing),
    first-failed-gate histogram, and threshold near-miss impact."""
    report = service.rejection_waterfall()
    window = report["window"]
    print("\nRejection waterfall")
    print(f"  window: {window['audit_rows_analyzed']} audit rows analyzed "
          f"({window['structured_rows']} structured, {window['legacy_rows']} legacy) "
          f"of {window['audit_rows_total']} total")

    print("\n  Stage funnel")
    bar_scale = max((row["count"] for row in report["stage_funnel"]), default=1) or 1
    for row in report["stage_funnel"]:
        pct = f"{row['pct_of_previous'] * 100:6.1f}%" if row["pct_of_previous"] is not None else "      -"
        bar = "#" * max(1, round(30 * row["count"] / bar_scale)) if row["count"] else ""
        print(f"    {row['stage']:24s} {row['count']:6d}  {pct} of prev  {bar}")
        print(f"    {'':24s} basis: {row['basis']}")

    print("\n  Gate failures (most frequent first)")
    for b in report["gate_failures"][:15]:
        advisory = f", advisory {b['advisory_failures']}" if b["advisory_failures"] else ""
        near = f", near-miss {b['near_misses']}" if b["near_misses"] else ""
        print(f"    {b['failures']:5d}  {b['gate']:26s} enforced {b['enforced_failures']}{advisory}{near}")
        if b["example"]:
            print(f"           e.g. {b['example']}")

    if report["first_failed_gates"]:
        print("\n  First gate that rejected (per attempt)")
        for item in report["first_failed_gates"][:10]:
            print(f"    {item['count']:5d}  {item['gate']}")

    if report["pre_idea_skips"]:
        print("\n  Skipped before idea creation (scanner accounting)")
        for item in report["pre_idea_skips"][:10]:
            print(f"    {item['count']:5d}  {item['reason'][:120]}")

    print("\n  Idea funnel by source x status")
    for row in rows(
        """
        SELECT source, status, COUNT(*) AS n FROM alpha_ideas
        GROUP BY source, status ORDER BY source, n DESC
        """
    ):
        print(f"  {row['n']:5d}  {str(row['source'])[:60]:60s} {row['status']}")


def main() -> None:
    load_local_env()
    print("AlphaLab Trading Pipeline Diagnostic")
    print("=" * 40)
    mode = alpaca_mode()
    mode_level = "PASS" if mode == "paper" else "FAIL" if mode == "live" else "WARN"
    status("Alpaca mode", mode_level, mode)
    status("Dry-run status", "PASS" if "scheduler_mode=paper" not in scheduler_dry_run_status() else "WARN", scheduler_dry_run_status())
    level, detail = alpaca_connectivity()
    status("Alpaca connectivity", level, detail)

    # The paper-execution alpha gate REQUIRES price/volume confirmation, which
    # only a live intraday source (Polygon) can supply. Without it every idea
    # stays unconfirmed/neutral and the >= 70 composite gate can never pass, so
    # surface presence (never values) of the load-bearing provider keys.
    polygon_set = bool(os.getenv("POLYGON_API_KEY", "").strip())
    status(
        "Price/volume confirmation source (POLYGON_API_KEY)",
        "PASS" if polygon_set else "WARN",
        "configured" if polygon_set else "missing: ideas cannot be confirmed, alpha gate blocks all paper orders",
    )

    db_path = resolve_db_path()
    if not Path(db_path).exists():
        status("Database", "FAIL", f"missing {db_path}")
        return

    service = AlphaLabService()
    diagnostics = service.strategy_diagnostics()
    stats = service.strategy_stats()

    recent_attempts = rows(
        """
        SELECT id, idea_id, ticker, status, alpaca_order_id, dry_run, created_at
        FROM execution_audit
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 8
        """
    )
    successful_ids = [row["alpaca_order_id"] for row in recent_attempts if row.get("alpaca_order_id")]
    recent_trades = rows(
        """
        SELECT id, idea_id, ticker, status, dry_run, realized_pl, unrealized_pl, opened_at
        FROM trades
        ORDER BY datetime(opened_at) DESC, id DESC
        LIMIT 8
        """
    )

    status("Recent order attempts", "PASS" if recent_attempts else "WARN", f"{len(recent_attempts)} found")
    print(json.dumps(recent_attempts, indent=2, default=str))
    status("Recent successful Alpaca order ids", "PASS" if successful_ids else "WARN", ", ".join(successful_ids) or "none")
    status("Recent trades in DB", "PASS" if recent_trades else "WARN", f"{len(recent_trades)} found")
    print(json.dumps(recent_trades, indent=2, default=str))
    status("Strategies found", "PASS" if stats else "WARN", str(len(stats)))
    status(
        "Trades missing strategy labels",
        "PASS" if diagnostics["trades_missing_strategy_labels"] == 0 else "WARN",
        str(diagnostics["trades_missing_strategy_labels"]),
    )

    client = TestClient(create_app(service))
    response = client.get("/api/stats/strategies")
    if response.status_code == 200 and isinstance(response.json(), list):
        with_trades = [row for row in response.json() if row.get("trades")]
        status("Strategies page API", "PASS" if with_trades else "WARN", f"{len(with_trades)} strategy rows with trades")
    else:
        status("Strategies page API", "FAIL", f"HTTP {response.status_code}")

    print_rejection_waterfall(service)

    print("\nSummary")
    if mode == "live":
        status("Safety", "FAIL", "ALPACA_PAPER_BASE_URL appears to target a live endpoint")
    elif successful_ids:
        status("Pipeline", "PASS", "Alpaca paper order ids are present in execution_audit")
    elif recent_trades:
        status("Pipeline", "WARN", "trades exist, but no recent Alpaca order ids were found")
    else:
        status("Pipeline", "WARN", "no trades found; run a dry-run strategy test first")

    maybe_run_paper_test_order()


def maybe_run_paper_test_order() -> None:
    if os.getenv("ALPHALABS_ALLOW_PAPER_TEST_ORDER", "").strip() != "1":
        status("Optional paper test order", "PASS", "skipped; set ALPHALABS_ALLOW_PAPER_TEST_ORDER=1 to enable")
        return
    if alpaca_mode() != "paper":
        status("Optional paper test order", "FAIL", "refusing because Alpaca mode is not paper")
        return
    risk_config = Path("/private/tmp/alphalab-diagnostic-risk.json")
    risk_config.write_text(
        json.dumps(
            {
                "min_confidence": 0.75,
                "max_position_size_usd": 5,
                "max_equity_pct_per_trade": 0.0001,
                "max_trades_per_day": 20,
                "max_open_positions": 20,
                "approved_tickers": ["NVDA"],
                "stop_loss_pct": 0.04,
                "take_profit_pct": 0.08,
                "max_daily_drawdown_pct": 0.03,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    service = AlphaLabService(risk_config_path=str(risk_config))
    idea = service.create_idea(
        {
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.8,
            "timeframe": "intraday",
            "thesis": "Diagnostic Alpaca PAPER test order. Tiny notional, paper-only.",
            "source": "diagnose_trading_pipeline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_tags": ["diagnostic paper test"],
        }
    )
    result = service.place_trade(idea["id"], dry_run=False)
    if result.get("order_response", {}).get("id"):
        status("Optional paper test order", "PASS", f"paper order id {result['order_response']['id']}")
    else:
        status("Optional paper test order", "WARN", "; ".join(result.get("reasons") or ["no order id returned"]))


if __name__ == "__main__":
    main()
