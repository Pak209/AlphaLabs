"""Golden-VALUE characterization of the rejection waterfall (Phase 2 PR1).

Seeds a fully deterministic DB with raw SQL (no network, no scoring, no
service orchestration) covering every aggregation path: structured traces
(accepted, enforced rejection with a near-miss, advisory alpha failure,
submitted paper order), a legacy free-text rejection, a scanner-run summary,
and a paper trade. The COMPLETE report dict (minus the generated_at
timestamp) is compared against an embedded golden.

Purpose: make the service.py → alpha_lab/waterfall.py extraction
verbatim-or-fail, and guard the later internal decomposition (Phase 2 PR2).
Update the golden only for a deliberate, human-approved output-contract
change, in the same commit, with a handoff entry.
"""
from __future__ import annotations

import json
from pathlib import Path

from alpha_lab.database import connect, init_db
from alpha_lab.service import AlphaLabService


def seed_waterfall_db(db_path: str) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        for ticker in ("NVDA", "MSFT", "AMD"):
            conn.execute(
                "INSERT INTO alpha_ideas (ticker, bias, confidence, timeframe, thesis, source, timestamp)"
                " VALUES (?, 'bullish', 0.8, 'intraday', 'golden seed', 'test', '2026-07-01T14:00:00Z')",
                (ticker,),
            )
        conn.execute(
            "INSERT INTO trades (ticker, side, status, dry_run) VALUES ('NVDA', 'buy', 'paper_open', 0)"
        )
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json) VALUES ('catalyst_radar', 'poll_live', ?)",
            (json.dumps({
                "candidates_found": 40,
                "top_rejection_reasons": [
                    {"reason": "not trade candidate", "count": 30},
                    {"reason": "duplicate ticker/catalyst", "count": 5},
                ],
            }),),
        )

        def audit(idea_id, ticker, status, reason, payload, created_at):
            conn.execute(
                "INSERT INTO execution_audit (idea_id, ticker, status, rejection_reason,"
                " payload_json, response_json, dry_run, created_at) VALUES (?, ?, ?, ?, ?, '{}', 1, ?)",
                (idea_id, ticker, status, reason, json.dumps(payload), created_at),
            )

        passed = {"stage": "risk_engine", "gate": "confidence", "passed": True,
                  "observed": 0.82, "threshold": 0.75, "comparator": ">=", "detail": "ok"}
        alpha_pass = {"stage": "paper_eligibility", "gate": "alpha_composite_tier", "passed": True,
                      "observed": 74.0, "threshold": 70.0, "comparator": ">=", "detail": "ok"}
        # 1. accepted dry-run with a passing alpha gate
        audit(1, "NVDA", "dry_run", "",
              {"_gates": [passed, alpha_pass], "_first_failed_gate": None},
              "2026-07-01 14:05:00")
        # 2. structured rejection: confidence near-miss (0.72 vs 0.75)
        audit(2, "MSFT", "reject", "confidence 0.72 below threshold 0.75",
              {"_gates": [{**passed, "passed": False, "observed": 0.72,
                           "detail": "confidence 0.72 below threshold 0.75"}],
               "_first_failed_gate": "confidence"},
              "2026-07-01 14:06:00")
        # 3. accepted dry-run whose alpha gate failed ADVISORY (enforced False)
        audit(3, "AMD", "dry_run", "",
              {"_gates": [passed, {**alpha_pass, "passed": False, "observed": 61.0,
                                   "enforced": False, "detail": "advisory: composite 61 < 70"}],
               "_first_failed_gate": None},
              "2026-07-01 14:07:00")
        # 4. legacy free-text rejection (pre-telemetry row, two clauses one gate + one other)
        audit(1, "NVDA", "reject",
              "alpha_tier must be high_conviction or tradeable before Alpaca paper execution; "
              "alpha_composite must be >= 70 before Alpaca paper execution (got 40.6); "
              "market is closed",
              {}, "2026-07-01 14:08:00")
        # 5. submitted paper order (structured)
        audit(1, "NVDA", "submitted", "",
              {"_gates": [passed, alpha_pass], "_first_failed_gate": None},
              "2026-07-01 14:09:00")
        conn.commit()


def build_report(tmp_path: Path) -> dict:
    db_path = str(tmp_path / "golden.sqlite3")
    seed_waterfall_db(db_path)
    lab = AlphaLabService(db_path=db_path,
                          risk_config_path="alpha_lab/config.example.json",
                          audit_log_path=str(tmp_path / "audit.jsonl"))
    report = lab.rejection_waterfall(limit=5000)
    report.pop("generated_at")
    return report


def test_rejection_waterfall_golden_value(tmp_path: Path):
    assert build_report(tmp_path) == GOLDEN


GOLDEN: dict = json.loads(r"""
{
  "first_failed_gates": [
    {
      "count": 1,
      "gate": "alpha_composite_tier"
    },
    {
      "count": 1,
      "gate": "confidence"
    }
  ],
  "gate_failures": [
    {
      "advisory_failures": 1,
      "enforced_failures": 1,
      "evaluated": 3,
      "example": "alpha_tier must be high_conviction or tradeable before Alpaca paper execution",
      "failures": 2,
      "gate": "alpha_composite_tier",
      "legacy_failures": 1,
      "near_misses": 0,
      "observed_stats": {
        "count": 3,
        "max": 74.0,
        "min": 61.0,
        "p25": 61.0,
        "p50": 74.0,
        "p75": 74.0
      },
      "share_of_attempts": 0.4
    },
    {
      "advisory_failures": 0,
      "enforced_failures": 1,
      "evaluated": 4,
      "example": "confidence 0.72 below threshold 0.75",
      "failures": 1,
      "gate": "confidence",
      "legacy_failures": 0,
      "near_misses": 1,
      "observed_stats": {
        "count": 4,
        "max": 0.82,
        "min": 0.72,
        "p25": 0.82,
        "p50": 0.82,
        "p75": 0.82
      },
      "share_of_attempts": 0.2
    },
    {
      "advisory_failures": 0,
      "enforced_failures": 1,
      "evaluated": 0,
      "example": "market is closed",
      "failures": 1,
      "gate": "market_open",
      "legacy_failures": 1,
      "near_misses": 0,
      "observed_stats": null,
      "share_of_attempts": 0.2
    }
  ],
  "pre_idea_skips": [
    {
      "count": 30,
      "reason": "not trade candidate"
    },
    {
      "count": 5,
      "reason": "duplicate ticker/catalyst"
    }
  ],
  "stage_funnel": [
    {
      "basis": "scanner_runs (last 1 runs)",
      "count": 40,
      "pct_of_previous": null,
      "stage": "candidates_scanned"
    },
    {
      "basis": "alpha_ideas (all time)",
      "count": 3,
      "pct_of_previous": 0.075,
      "stage": "ideas_created"
    },
    {
      "basis": "execution_audit (last 5 of 5; ideas can be attempted more than once)",
      "count": 5,
      "pct_of_previous": 1.6667,
      "stage": "decision_attempts"
    },
    {
      "basis": "risk-engine accepted (dry_run or submitted)",
      "count": 3,
      "pct_of_previous": 0.6,
      "stage": "accepted_decisions"
    },
    {
      "basis": "structured traces only (3 accepted attempts carried the alpha gate)",
      "count": 2,
      "pct_of_previous": 0.6667,
      "stage": "alpha_gate_passed"
    },
    {
      "basis": "execution_audit status=submitted",
      "count": 1,
      "pct_of_previous": 0.3333,
      "stage": "paper_orders_submitted"
    },
    {
      "basis": "trades with dry_run=0 (all time)",
      "count": 1,
      "pct_of_previous": 1.0,
      "stage": "paper_trades"
    }
  ],
  "status": "ok",
  "threshold_impact": [
    {
      "advisory_failures": 0,
      "enforced_failures": 1,
      "example": "confidence 0.72 below threshold 0.75",
      "gate": "confidence",
      "near_misses": 1
    },
    {
      "advisory_failures": 1,
      "enforced_failures": 1,
      "example": "alpha_tier must be high_conviction or tradeable before Alpaca paper execution",
      "gate": "alpha_composite_tier",
      "near_misses": 0
    },
    {
      "advisory_failures": 0,
      "enforced_failures": 1,
      "example": "market is closed",
      "gate": "market_open",
      "near_misses": 0
    }
  ],
  "window": {
    "audit_rows_analyzed": 5,
    "audit_rows_total": 5,
    "legacy_rows": 1,
    "scanner_runs_analyzed": 1,
    "structured_rows": 4
  }
}
""")
