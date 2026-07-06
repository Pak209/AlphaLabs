from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.portfolio import build_portfolio_snapshot
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "portfolio.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def seed_positions(lab: AlphaLabService):
    with connect(lab.db_path) as conn:
        AlphaLabRepository(conn).sync_positions([
            {"symbol": "NVDA", "qty": 10, "market_value": 6000, "unrealized_pl": 120},
            {"symbol": "MSFT", "qty": 5, "market_value": 3000, "unrealized_pl": -40},
            {"symbol": "XOM", "qty": 8, "market_value": 1000, "unrealized_pl": 10},
        ])


def seed_scored_trades(lab: AlphaLabService):
    with connect(lab.db_path) as conn:
        repo = AlphaLabRepository(conn)
        for ticker, composite in (("NVDA", 80.0), ("MSFT", 60.0)):
            idea = repo.create_idea({
                "ticker": ticker, "bias": "bullish", "confidence": 0.8,
                "timeframe": "intraday", "thesis": "t", "source": "test",
                "timestamp": "2026-06-22T14:00:00Z", "sector": "", "theme": "",
                "catalyst": "c", "strategies": ["manual"], "source_tags": ["manual"],
                "market_regime": "unknown",
            })
            repo.create_trade({
                "idea_id": idea["id"], "ticker": ticker, "side": "buy",
                "quantity": 1, "notional": 500.0, "entry_price": 100.0,
                "status": "dry_run", "dry_run": True, "asset_type": "equity",
                "alpha": {"composite_score": composite, "tier": "tradeable"},
            })


def test_snapshot_measures_concentration_theme_and_heat(tmp_path: Path):
    lab = service(tmp_path)
    seed_positions(lab)
    report = build_portfolio_snapshot(lab.db_path)

    conc = report["concentration"]
    assert conc["gross_exposure_usd"] == 10000.0
    assert conc["largest_position_share"] == 0.6
    # HHI = 0.6^2 + 0.3^2 + 0.1^2 = 0.46
    assert conc["hhi"] == 0.46
    assert conc["effective_positions"] == 2.17

    themes = report["theme_exposure"]
    shares = {row["theme"]: row["share"] for row in themes["breakdown"]}
    assert shares["ai"] == 0.9                     # NVDA + MSFT cluster
    assert themes["top_theme_share"] == 0.9
    assert themes["clustered_exposure_share"] == 0.9   # XOM ('none') is alone

    heat = report["portfolio_heat"]
    assert heat["stop_loss_pct"] == 0.04
    assert heat["total_heat_usd"] == 400.0         # 10000 * 4%
    assert heat["heat_share_of_gross"] == 0.04

    caps = report["cap_utilization"]
    assert caps["open_positions"] == 3 and caps["max_open_positions"] == 20


def test_conviction_whatif_reallocates_same_pool(tmp_path: Path):
    lab = service(tmp_path)
    seed_scored_trades(lab)
    report = build_portfolio_snapshot(lab.db_path)
    whatif = report["conviction_sizing_whatif"]
    assert whatif["cohort"] == "recent_dry_run_trades"
    assert whatif["n_scored"] == 2
    assert whatif["reallocated_pool_usd"] == 1000.0
    rows = {r["ticker"]: r for r in whatif["rows"]}
    # 80/(80+60) and 60/(80+60) of the same $1000 pool
    assert rows["NVDA"]["conviction_notional_usd"] == 571.43
    assert rows["MSFT"]["conviction_notional_usd"] == 428.57
    assert rows["NVDA"]["delta_usd"] == 71.43
    assert round(sum(r["conviction_notional_usd"] for r in whatif["rows"]), 2) == 1000.0


def test_empty_portfolio_and_read_only(tmp_path: Path):
    lab = service(tmp_path)
    report = build_portfolio_snapshot(lab.db_path)
    assert report["n_positions"] == 0
    assert report["concentration"]["gross_exposure_usd"] == 0.0
    assert report["concentration"]["hhi"] is None
    assert report["portfolio_heat"]["total_heat_usd"] == 0.0
    assert report["conviction_sizing_whatif"]["rows"] == []

    seed_positions(lab)
    with connect(lab.db_path) as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("positions", "trades", "orders", "execution_audit")}
    first = build_portfolio_snapshot(lab.db_path)
    second = build_portfolio_snapshot(lab.db_path)
    assert first == second
    with connect(lab.db_path) as conn:
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("positions", "trades", "orders", "execution_audit")}
    assert after == before


def test_cli_prints_and_writes(tmp_path: Path, capsys):
    from scripts.portfolio_report import print_report, write_report

    lab = service(tmp_path)
    seed_positions(lab)
    seed_scored_trades(lab)
    report = build_portfolio_snapshot(lab.db_path)
    path = write_report(report, tmp_path / "reports")
    assert path.exists()
    print_report(report)
    output = capsys.readouterr().out
    assert "theme exposure" in output
    assert "conviction-sizing what-if" in output
