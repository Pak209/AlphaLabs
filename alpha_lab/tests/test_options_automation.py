"""Options automation PR-B: shadow-mode routing telemetry (zero orders).

Contract: with ALPHALAB_OPTIONS_AUTOMATION=shadow (and, deliberately, =on —
arming requires its own future PR), accepted equity decisions gain an
enforced=False `option_routing` record describing what WOULD have happened;
the executed order remains the equity order in every mode.
"""
from __future__ import annotations

import json
from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.service import AlphaLabService
from alpha_lab.tests.test_alpha_lab import force_alpha, idea_payload, service


def last_audit_gates(lab: AlphaLabService) -> list[dict]:
    with connect(lab.db_path) as conn:
        row = conn.execute("SELECT payload_json FROM execution_audit ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row["payload_json"]).get("_gates") or []


def routing_records(lab: AlphaLabService) -> list[dict]:
    return [g for g in last_audit_gates(lab) if g.get("gate") == "option_routing"]


def selection_stub(**overrides):
    contract = {"contract_symbol": "NVDA260821C00180000", "dte": 10,
                "estimated_cost_usd": 450.0, "spread_pct": 4.2}
    contract.update(overrides)
    return contract


def test_shadow_records_would_be_contract_and_keeps_equity_order(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_OPTIONS_AUTOMATION", "shadow")
    lab = service(tmp_path)
    force_alpha(lab, monkeypatch, tier="high_conviction", composite=84.0)
    monkeypatch.setattr(lab, "_select_option_contract", lambda idea: selection_stub())

    result = lab.place_trade(lab.create_idea(idea_payload())["id"], dry_run=True)

    assert result["accepted"] is True
    assert result["order_payload"]["symbol"] == "NVDA"        # equity order untouched
    assert "notional" in result["order_payload"]              # not an option payload
    records = routing_records(lab)
    assert len(records) == 1
    record = records[0]
    assert record["enforced"] is False and record["passed"] is True
    assert record["contract"]["contract_symbol"] == "NVDA260821C00180000"
    assert "would route" in record["detail"]


def test_shadow_notes_tier_below_high_conviction(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_OPTIONS_AUTOMATION", "shadow")
    lab = service(tmp_path)
    force_alpha(lab, monkeypatch, tier="tradeable", composite=74.0)

    result = lab.place_trade(lab.create_idea(idea_payload())["id"], dry_run=True)

    assert result["accepted"] is True
    record = routing_records(lab)[0]
    assert record["passed"] is False and record["enforced"] is False
    assert "below high_conviction" in record["detail"]


def test_off_mode_records_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ALPHALAB_OPTIONS_AUTOMATION", raising=False)
    lab = service(tmp_path)
    force_alpha(lab, monkeypatch, tier="high_conviction", composite=84.0)

    lab.place_trade(lab.create_idea(idea_payload())["id"], dry_run=True)

    assert routing_records(lab) == []


def test_on_mode_deliberately_behaves_as_shadow_until_armed(tmp_path: Path, monkeypatch):
    # Arming requires its own PR per docs/OPTIONS_AUTOMATION_PLAN.md — an env
    # edit alone must not be able to start routing real option orders.
    monkeypatch.setenv("ALPHALAB_OPTIONS_AUTOMATION", "on")
    lab = service(tmp_path)
    force_alpha(lab, monkeypatch, tier="high_conviction", composite=84.0)
    monkeypatch.setattr(lab, "_select_option_contract", lambda idea: selection_stub())

    result = lab.place_trade(lab.create_idea(idea_payload())["id"], dry_run=True)

    assert result["order_payload"]["symbol"] == "NVDA"        # still the equity order
    assert routing_records(lab)[0]["passed"] is True


def test_selection_failure_is_contained(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_OPTIONS_AUTOMATION", "shadow")
    lab = service(tmp_path)
    force_alpha(lab, monkeypatch, tier="high_conviction", composite=84.0)

    def boom(idea):
        raise RuntimeError("chain unavailable")

    monkeypatch.setattr(lab, "_select_option_contract", boom)
    result = lab.place_trade(lab.create_idea(idea_payload())["id"], dry_run=True)

    assert result["accepted"] is True                          # trade flow unaffected
    record = routing_records(lab)[0]
    assert record["passed"] is False
    assert "selection failed" in record["detail"]
