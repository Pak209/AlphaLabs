"""Synthetic telemetry fixture — fabricated data on the real production schema.

Builds a database via alpha_lab.database.init_db and populates it with a
deterministic population designed to exercise every analysis in the battery:

- 36 ideas over 6 sessions, confidence values spanning the below / near-miss /
  above bands around the 0.75 execution bar (10% margin → 0.675).
- Every idea has a filled signal_evaluation whose direction-signed excess move
  encodes a known hit pattern per band.
- 18 structured execution_audit attempts (7 accepted, 6 rejected as
  confidence near-misses, 5 rejected far below) plus 1 legacy free-text row
  that loaders must skip.

Never point anything in this module at the production database.
"""
from __future__ import annotations

import json
from typing import Any

from alpha_lab.database import connect, init_db

SESSIONS = ["2026-06-22", "2026-06-23", "2026-06-24",
            "2026-06-25", "2026-06-26", "2026-06-29"]
CONFIDENCE_CYCLE = [0.55, 0.65, 0.70, 0.72, 0.78, 0.85,
                    0.92, 0.60, 0.74, 0.80, 0.68, 0.88]
THRESHOLD, MARGIN = 0.75, 0.075
BENCHMARK = 0.3  # % market move over the same window, sign follows direction


def band_for(confidence: float) -> str:
    if confidence >= THRESHOLD:
        return "above"
    if confidence >= THRESHOLD - MARGIN:
        return "near_miss"
    return "below"


def hit_for(index: int, band: str) -> bool:
    if band == "above":
        return index % 5 != 0
    if band == "near_miss":
        return index % 2 == 0
    return index % 3 == 0


def build_fixture_db(db_path: str) -> dict[str, Any]:
    """Create and populate the fixture DB; return the expected population."""
    init_db(db_path)
    expected: dict[str, Any] = {"ideas": [], "accepted": [], "near": [], "far": []}

    with connect(db_path) as conn:
        for i in range(36):
            session = SESSIONS[i % len(SESSIONS)]
            confidence = CONFIDENCE_CYCLE[i % len(CONFIDENCE_CYCLE)]
            band = band_for(confidence)
            hit = hit_for(i, band)
            direction = "bullish" if i % 2 == 0 else "bearish"
            sign = 1.0 if direction == "bullish" else -1.0
            move = sign * (2.0 if hit else -1.5)
            timestamp = f"{session}T14:30:00+00:00"

            cursor = conn.execute(
                """
                INSERT INTO alpha_ideas (ticker, asset_type, bias, confidence, timeframe,
                                         thesis, source, status, timestamp)
                VALUES (?, 'equity', ?, ?, 'swing', ?, 'catalyst_radar', 'new', ?)
                """,
                (f"TST{i:02d}", direction, confidence, f"synthetic thesis {i}", timestamp),
            )
            idea_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO signal_evaluations (idea_id, ticker, source, generated_at,
                                                evaluated_at, direction, confidence,
                                                alert_price, price_after, move_after_pct,
                                                benchmark_move_pct, early_detection_score,
                                                provisional_grade, status)
                VALUES (?, ?, 'catalyst_radar', ?, ?, ?, ?, 100.0, ?, ?, ?, ?, 'B', 'final')
                """,
                (idea_id, f"TST{i:02d}", timestamp, timestamp, direction, confidence,
                 100.0 + move, move, sign * BENCHMARK, 50.0 + (10 if hit else -10)),
            )
            expected["ideas"].append({
                "idea_id": idea_id, "index": i, "confidence": confidence,
                "band": band, "hit": hit, "session": session, "direction": direction,
            })

        # Structured decision attempts for the first 18 ideas.
        for idea in expected["ideas"][:18]:
            confidence = idea["confidence"]
            passed = confidence >= THRESHOLD
            gates = [
                {"stage": "risk_engine", "gate": "confidence", "passed": passed,
                 "observed": confidence, "threshold": THRESHOLD, "comparator": ">=",
                 "detail": "" if passed else f"confidence {confidence:.2f} below threshold {THRESHOLD:.2f}"},
                {"stage": "risk_engine", "gate": "market_open", "passed": True,
                 "observed": True, "threshold": True, "comparator": "==", "detail": "ok"},
            ]
            if passed:
                gates.append({"stage": "paper_gate", "gate": "alpha_composite_tier",
                              "passed": idea["index"] % 2 == 0, "enforced": False,
                              "observed": 72.0, "threshold": 70.0, "comparator": ">=",
                              "detail": "advisory"})
            payload = {"_gates": gates,
                       "_first_failed_gate": None if passed else "confidence",
                       "gate_context": {"open_positions": 3}}
            conn.execute(
                """
                INSERT INTO execution_audit (idea_id, ticker, status, rejection_reason,
                                             payload_json, dry_run, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (idea["idea_id"], f"TST{idea['index']:02d}",
                 "dry_run" if passed else "rejected",
                 "" if passed else f"confidence {confidence:.2f} below threshold {THRESHOLD:.2f}",
                 json.dumps(payload), f"{idea['session']}T15:00:00+00:00"),
            )
            key = ("accepted" if passed
                   else "near" if idea["band"] == "near_miss" else "far")
            expected[key].append(idea)

        # Legacy row (no structured telemetry) — loaders must skip it.
        conn.execute(
            """
            INSERT INTO execution_audit (idea_id, ticker, status, rejection_reason,
                                         payload_json, dry_run, created_at)
            VALUES (NULL, 'LEGACY', 'rejected',
                    'confidence 0.60 below threshold 0.75', '{}', 1,
                    '2026-06-20T15:00:00+00:00')
            """
        )
        conn.commit()
    return expected
