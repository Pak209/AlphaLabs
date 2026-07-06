from __future__ import annotations

import json
import sqlite3
from typing import Any

from .models import DEFAULT_STRATEGIES


def _as_int_bool(value: Any) -> int | None:
    """Persist a bool/None as SQLite 1/0/NULL."""
    if value is None:
        return None
    return 1 if value else 0


class AlphaLabRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def seed_defaults(self) -> None:
        for name in DEFAULT_STRATEGIES:
            self.conn.execute("INSERT OR IGNORE INTO strategies (name) VALUES (?)", (name,))
        self.ensure_trade_strategy_links()
        self.normalize_dry_run_statuses()
        self.backfill_source_tags()
        self.backfill_signal_evaluations()
        self.conn.commit()

    def normalize_dry_run_statuses(self) -> None:
        self.conn.execute(
            """
            UPDATE alpha_ideas
            SET status = 'tested', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'traded'
              AND EXISTS (
                SELECT 1 FROM trades t
                WHERE t.idea_id = alpha_ideas.id AND t.dry_run = 1
              )
              AND NOT EXISTS (
                SELECT 1 FROM trades t
                WHERE t.idea_id = alpha_ideas.id AND t.dry_run = 0
              )
            """
        )

    def ensure_trade_strategy_links(self) -> int:
        """Backfill a safe strategy label for traded ideas that have no tag."""
        fallback_id = self.ensure_strategy("untagged")
        rows = self.conn.execute(
            """
            SELECT DISTINCT t.idea_id
            FROM trades t
            LEFT JOIN idea_strategies ix ON ix.idea_id = t.idea_id
            WHERE t.idea_id IS NOT NULL AND ix.strategy_id IS NULL
            """
        ).fetchall()
        for row in rows:
            self.conn.execute(
                "INSERT OR IGNORE INTO idea_strategies (idea_id, strategy_id) VALUES (?, ?)",
                (row["idea_id"], fallback_id),
            )
        self.conn.commit()
        return len(rows)

    def create_idea(self, idea: dict[str, Any]) -> dict[str, Any]:
        source_tags = idea.get("source_tags") or []
        cur = self.conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, asset_type, sector, theme, bias, confidence, timeframe, thesis, catalyst,
               catalyst_type, catalyst_score, catalyst_event_id, source, timestamp, source_tags, market_regime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea["ticker"],
                idea.get("asset_type", "equity"),
                idea["sector"],
                idea["theme"],
                idea["bias"],
                idea["confidence"],
                idea["timeframe"],
                idea["thesis"],
                idea["catalyst"],
                str(idea.get("catalyst_type") or ""),
                idea.get("catalyst_score"),
                idea.get("catalyst_event_id"),
                idea["source"],
                idea["timestamp"],
                json.dumps([str(tag) for tag in source_tags], default=str),
                str(idea.get("market_regime") or "unknown"),
            ),
        )
        idea_id = int(cur.lastrowid)
        for tag in idea.get("strategies", []):
            strategy_id = self.ensure_strategy(tag)
            self.conn.execute(
                "INSERT OR IGNORE INTO idea_strategies (idea_id, strategy_id) VALUES (?, ?)",
                (idea_id, strategy_id),
            )
        self._ensure_idea_source_tags(idea_id)
        self._ensure_signal_evaluation_for_idea(idea_id)
        self.conn.commit()
        return self.get_idea(idea_id)

    def upsert_catalyst_event(self, event: dict[str, Any]) -> dict[str, Any]:
        existing = self.conn.execute(
            """
            SELECT id FROM catalyst_events
            WHERE ticker = ? AND headline = ? AND source = ? AND published_at = ?
            LIMIT 1
            """,
            (event["ticker"], event["headline"], event["source"], event["published_at"]),
        ).fetchone()
        values = {
            "ticker": event["ticker"],
            "security_type": event.get("security_type") or "stock",
            "sector": event.get("sector") or "",
            "catalyst_type": event.get("catalyst_type") or "News Catalyst",
            "strategy_label": event.get("strategy_label") or event.get("catalyst_type") or "News Catalyst",
            "direction": event.get("direction") or event.get("bias") or "neutral",
            "headline": event["headline"],
            "summary": event.get("summary") or "",
            "source": event.get("source") or "unknown",
            "source_url": event.get("source_url") or "",
            "published_at": event["published_at"],
            "discovered_at": event.get("discovered_at") or event["published_at"],
            "novelty_score": float(event.get("novelty_score") or 0),
            "urgency_score": float(event.get("urgency_score") or 0),
            "historical_score": float(event.get("historical_score") or 0),
            "relevance_score": float(event.get("relevance_score") or 0),
            "market_impact_score": float(event.get("market_impact_score") or 0),
            "source_quality_score": float(event.get("source_quality_score") or 0),
            "keyword_score": float(event.get("keyword_score") or 0),
            "sector_score": float(event.get("sector_score") or 0),
            "catalyst_score": int(event.get("catalyst_score") or 0),
            "confidence": float(event.get("confidence") or 0),
            "market_regime": event.get("market_regime") or "unknown",
            "matched_keywords_json": json.dumps(event.get("matched_keywords") or [], default=str),
            "explanation_json": json.dumps(event.get("explanation") or [], default=str),
            "supporting_evidence_json": json.dumps(event.get("supporting_evidence") or [], default=str),
            "raw_payload_json": json.dumps(event.get("raw_payload") or event, default=str),
            "idea_id": event.get("idea_id"),
        }
        if existing:
            event_id = int(existing["id"])
            self.conn.execute(
                """
                UPDATE catalyst_events SET
                  security_type = :security_type,
                  sector = :sector,
                  catalyst_type = :catalyst_type,
                  strategy_label = :strategy_label,
                  direction = :direction,
                  summary = :summary,
                  source_url = :source_url,
                  discovered_at = :discovered_at,
                  novelty_score = :novelty_score,
                  urgency_score = :urgency_score,
                  historical_score = :historical_score,
                  relevance_score = :relevance_score,
                  market_impact_score = :market_impact_score,
                  source_quality_score = :source_quality_score,
                  keyword_score = :keyword_score,
                  sector_score = :sector_score,
                  catalyst_score = :catalyst_score,
                  confidence = :confidence,
                  market_regime = :market_regime,
                  matched_keywords_json = :matched_keywords_json,
                  explanation_json = :explanation_json,
                  supporting_evidence_json = :supporting_evidence_json,
                  raw_payload_json = :raw_payload_json,
                  idea_id = COALESCE(:idea_id, idea_id),
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {**values, "id": event_id},
            )
        else:
            cur = self.conn.execute(
                """
                INSERT INTO catalyst_events
                  (ticker, security_type, sector, catalyst_type, strategy_label, direction, headline,
                   summary, source, source_url, published_at, discovered_at, novelty_score,
                   urgency_score, historical_score, relevance_score, market_impact_score,
                   source_quality_score, keyword_score, sector_score, catalyst_score, confidence,
                   market_regime, matched_keywords_json, explanation_json, supporting_evidence_json,
                   raw_payload_json, idea_id)
                VALUES
                  (:ticker, :security_type, :sector, :catalyst_type, :strategy_label, :direction, :headline,
                   :summary, :source, :source_url, :published_at, :discovered_at, :novelty_score,
                   :urgency_score, :historical_score, :relevance_score, :market_impact_score,
                   :source_quality_score, :keyword_score, :sector_score, :catalyst_score, :confidence,
                   :market_regime, :matched_keywords_json, :explanation_json, :supporting_evidence_json,
                   :raw_payload_json, :idea_id)
                """,
                values,
            )
            event_id = int(cur.lastrowid)
        self.conn.commit()
        return self.get_catalyst_event(event_id)

    def link_catalyst_event_to_idea(self, event_id: int, idea_id: int) -> None:
        self.conn.execute(
            "UPDATE catalyst_events SET idea_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (idea_id, event_id),
        )
        self.conn.execute(
            "UPDATE alpha_ideas SET catalyst_event_id = ? WHERE id = ? AND catalyst_event_id IS NULL",
            (event_id, idea_id),
        )
        self.conn.commit()

    def get_catalyst_event(self, event_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM catalyst_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(f"catalyst event not found: {event_id}")
        return self._hydrate_catalyst_event(dict(row))

    def list_catalyst_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM catalyst_events
            ORDER BY datetime(published_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._hydrate_catalyst_event(dict(row)) for row in rows]

    def catalyst_intelligence_dashboard(self, limit: int = 25) -> dict[str, Any]:
        top_rows = self.conn.execute(
            """
            SELECT * FROM catalyst_events
            ORDER BY catalyst_score DESC, datetime(published_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        recent = self.list_catalyst_events(limit)
        strategy = self.conn.execute(
            """
            SELECT ce.strategy_label AS strategy,
                   COUNT(*) AS catalysts,
                   SUM(CASE WHEN COALESCE(t.realized_pl, t.unrealized_pl, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN t.id IS NOT NULL THEN 1 ELSE 0 END) AS tested,
                   AVG(ce.catalyst_score) AS avg_score,
                   AVG(COALESCE(t.realized_pl, t.unrealized_pl, 0)) AS avg_pl
            FROM catalyst_events ce
            LEFT JOIN trades t ON t.idea_id = ce.idea_id
            GROUP BY ce.strategy_label
            ORDER BY tested DESC, catalysts DESC, avg_score DESC
            LIMIT 20
            """
        ).fetchall()
        sectors = self.conn.execute(
            """
            SELECT COALESCE(NULLIF(sector, ''), 'Unknown') AS sector,
                   COUNT(*) AS catalysts,
                   AVG(catalyst_score) AS avg_score,
                   MAX(catalyst_score) AS top_score
            FROM catalyst_events
            GROUP BY COALESCE(NULLIF(sector, ''), 'Unknown')
            ORDER BY catalysts DESC, top_score DESC
            LIMIT 20
            """
        ).fetchall()
        leaderboard = self.conn.execute(
            """
            SELECT ce.*, COALESCE(t.realized_pl, t.unrealized_pl, 0) AS realized_pl,
                   CASE
                     WHEN t.entry_price IS NOT NULL AND t.entry_price != 0 AND t.exit_price IS NOT NULL
                       THEN ((t.exit_price - t.entry_price) / t.entry_price) * CASE WHEN t.side = 'sell' THEN -100 ELSE 100 END
                     WHEN t.notional IS NOT NULL AND t.notional != 0
                       THEN (COALESCE(t.realized_pl, t.unrealized_pl, 0) / t.notional) * 100
                     ELSE 0
                   END AS realized_return
            FROM catalyst_events ce
            LEFT JOIN trades t ON t.idea_id = ce.idea_id
            ORDER BY ABS(realized_return) DESC, ce.catalyst_score DESC, datetime(ce.published_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {
            "top_catalysts": [self._hydrate_catalyst_event(dict(row)) for row in top_rows],
            "recent_catalysts": recent,
            "strategy_performance": [
                {
                    "strategy": row["strategy"],
                    "catalysts": int(row["catalysts"] or 0),
                    "tested": int(row["tested"] or 0),
                    "wins": int(row["wins"] or 0),
                    "win_rate": round(float(row["wins"] or 0) / float(row["tested"] or 1), 4) if row["tested"] else 0,
                    "avg_score": round(float(row["avg_score"] or 0), 1),
                    "avg_pl": round(float(row["avg_pl"] or 0), 2),
                }
                for row in strategy
            ],
            "sector_breakdown": [
                {
                    "sector": row["sector"],
                    "catalysts": int(row["catalysts"] or 0),
                    "avg_score": round(float(row["avg_score"] or 0), 1),
                    "top_score": int(row["top_score"] or 0),
                }
                for row in sectors
            ],
            "leaderboard": [
                {
                    **self._hydrate_catalyst_event(dict(row)),
                    "realized_pl": float(row["realized_pl"] or 0),
                    "realized_return": round(float(row["realized_return"] or 0), 2),
                }
                for row in leaderboard
            ],
        }

    def backfill_source_tags(self) -> int:
        rows = self.conn.execute(
            """
            SELECT id FROM alpha_ideas
            WHERE source_tags IS NULL OR source_tags = '' OR source_tags = '[]'
            """
        ).fetchall()
        for row in rows:
            self._ensure_idea_source_tags(int(row["id"]))
        self.conn.commit()
        return len(rows)

    def backfill_signal_evaluations(self) -> int:
        rows = self.conn.execute(
            """
            SELECT i.id
            FROM alpha_ideas i
            LEFT JOIN signal_evaluations se ON se.idea_id = i.id
            WHERE se.id IS NULL
            """
        ).fetchall()
        for row in rows:
            self._ensure_signal_evaluation_for_idea(int(row["id"]))
        self.conn.commit()
        return len(rows)

    def _ensure_idea_source_tags(self, idea_id: int) -> None:
        row = self.conn.execute("SELECT source, source_tags FROM alpha_ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            return
        tags = self._parse_tags(row["source_tags"])
        if not tags:
            tags = [str(row["source"] or "manual")]
            tags.extend(self._strategies_for_idea(idea_id))
            tags = list(dict.fromkeys(tag for tag in tags if tag))
            self.conn.execute(
                "UPDATE alpha_ideas SET source_tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(tags, default=str), idea_id),
            )

    def _ensure_signal_evaluation_for_idea(self, idea_id: int) -> None:
        exists = self.conn.execute("SELECT id FROM signal_evaluations WHERE idea_id = ?", (idea_id,)).fetchone()
        if exists:
            return
        idea = self.conn.execute("SELECT * FROM alpha_ideas WHERE id = ?", (idea_id,)).fetchone()
        if idea is None:
            return
        idea_dict = dict(idea)
        source_tags = self._parse_tags(idea_dict.get("source_tags"))
        if not source_tags:
            source_tags = [str(idea_dict.get("source") or "manual")]
        self.conn.execute(
            """
            INSERT OR IGNORE INTO signal_evaluations
              (idea_id, ticker, source, source_tags, generated_at, horizon, direction,
               confidence, market_regime, catalyst, provisional_grade, status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'provisional', ?)
            """,
            (
                idea_id,
                str(idea_dict.get("ticker") or "").upper(),
                idea_dict.get("source") or "manual",
                json.dumps(source_tags, default=str),
                idea_dict.get("timestamp") or idea_dict.get("created_at"),
                idea_dict.get("timeframe") or "intraday",
                idea_dict.get("bias") or "",
                idea_dict.get("confidence"),
                idea_dict.get("market_regime") or "unknown",
                idea_dict.get("catalyst") or "",
                self._provisional_grade(idea_dict.get("confidence"), idea_dict.get("catalyst")),
                json.dumps({"created_by": "repository_default", "benchmark_status": "unavailable"}, default=str),
            ),
        )

    def log_scanner_run(self, source: str, run_type: str, payload: dict[str, Any]) -> int:
        safe_payload = {
            key: payload.get(key)
            for key in (
                "status",
                "enabled",
                "requests_attempted",
                "responses_received",
                "raw_items",
                "candidates_found",
                "candidates_filtered",
                "ideas_persisted",
                "rejected",
                "skipped",
                "top_rejection_reasons",
                "source_problems",
                "note",
                "dry_run",
                "started_at",
                "finished_at",
                "duration_ms",
                "items_created",
                "error_message",
                "crypto_signal_logs",
                "safety_gates",
                "allowlist",
                "cooldown_minutes",
                "max_simulated_crypto_ideas_per_day",
            )
            if key in payload
        }
        cur = self.conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json) VALUES (?, ?, ?)",
            (source, run_type, json.dumps(safe_payload, default=str)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_scanner_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM scanner_runs ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            output.append(item)
        return output

    def _parse_tags(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(tag) for tag in value if str(tag).strip()]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                parsed = [value]
            if isinstance(parsed, list):
                return [str(tag) for tag in parsed if str(tag).strip()]
        return []

    def _provisional_grade(self, confidence: Any, catalyst: Any) -> str:
        try:
            value = float(confidence or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value >= 0.85 and str(catalyst or "").strip():
            return "B"
        if value >= 0.7:
            return "C"
        if value >= 0.55:
            return "D"
        return "F"

    def upsert_signal_evaluation(self, idea_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        idea = self.get_idea(idea_id)
        source_tags = updates.get("source_tags", idea.get("source_tags") or [])
        if isinstance(source_tags, str):
            source_tags_json = source_tags
        else:
            source_tags_json = json.dumps([str(tag) for tag in source_tags], default=str)
        payload = updates.get("payload", {})
        payload_json = updates.get("payload_json") or json.dumps(payload, default=str)
        values = {
            "idea_id": idea_id,
            "ticker": str(updates.get("ticker") or idea.get("ticker") or "").upper(),
            "source": updates.get("source") or idea.get("source") or "manual",
            "source_tags": source_tags_json,
            "generated_at": updates.get("generated_at") or idea.get("timestamp") or idea.get("created_at"),
            "evaluated_at": updates.get("evaluated_at"),
            "horizon": updates.get("horizon") or idea.get("timeframe") or "intraday",
            "direction": updates.get("direction") or idea.get("bias") or "",
            "confidence": updates.get("confidence", idea.get("confidence")),
            "market_regime": updates.get("market_regime") or idea.get("market_regime") or "unknown",
            "catalyst": updates.get("catalyst") or idea.get("catalyst") or "",
            "alert_price": updates.get("alert_price"),
            "price_after": updates.get("price_after"),
            "move_after_pct": updates.get("move_after_pct"),
            "benchmark_move_pct": updates.get("benchmark_move_pct"),
            "early_detection_score": updates.get("early_detection_score"),
            "provisional_grade": updates.get("provisional_grade"),
            "final_grade": updates.get("final_grade"),
            "status": updates.get("status") or "provisional",
            "payload_json": payload_json,
        }
        self.conn.execute(
            """
            INSERT INTO signal_evaluations
              (idea_id, ticker, source, source_tags, generated_at, evaluated_at, horizon,
               direction, confidence, market_regime, catalyst, alert_price, price_after,
               move_after_pct, benchmark_move_pct, early_detection_score, provisional_grade,
               final_grade, status, payload_json)
            VALUES
              (:idea_id, :ticker, :source, :source_tags, :generated_at, :evaluated_at, :horizon,
               :direction, :confidence, :market_regime, :catalyst, :alert_price, :price_after,
               :move_after_pct, :benchmark_move_pct, :early_detection_score, :provisional_grade,
               :final_grade, :status, :payload_json)
            ON CONFLICT(idea_id) DO UPDATE SET
              ticker = excluded.ticker,
              source = excluded.source,
              source_tags = excluded.source_tags,
              generated_at = excluded.generated_at,
              evaluated_at = COALESCE(excluded.evaluated_at, signal_evaluations.evaluated_at),
              horizon = excluded.horizon,
              direction = excluded.direction,
              confidence = excluded.confidence,
              market_regime = excluded.market_regime,
              catalyst = excluded.catalyst,
              alert_price = COALESCE(excluded.alert_price, signal_evaluations.alert_price),
              price_after = COALESCE(excluded.price_after, signal_evaluations.price_after),
              move_after_pct = COALESCE(excluded.move_after_pct, signal_evaluations.move_after_pct),
              benchmark_move_pct = COALESCE(excluded.benchmark_move_pct, signal_evaluations.benchmark_move_pct),
              early_detection_score = COALESCE(excluded.early_detection_score, signal_evaluations.early_detection_score),
              provisional_grade = COALESCE(excluded.provisional_grade, signal_evaluations.provisional_grade),
              final_grade = COALESCE(excluded.final_grade, signal_evaluations.final_grade),
              status = excluded.status,
              payload_json = excluded.payload_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            values,
        )
        self.conn.commit()
        return self.get_signal_evaluation(idea_id)

    def get_signal_evaluation(self, idea_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM signal_evaluations WHERE idea_id = ?", (idea_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"signal evaluation not found: {idea_id}")
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        item["source_tags"] = json.loads(item.get("source_tags") or "[]")
        return item

    def list_signal_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM signal_evaluations
            ORDER BY datetime(COALESCE(evaluated_at, generated_at, created_at)) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["source_tags"] = json.loads(item.get("source_tags") or "[]")
            output.append(item)
        return output

    def create_trade_explanation(self, idea_id: int, explanation: dict[str, Any], prompt_context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt_context = prompt_context or {}
        analyst_assisted = 1 if explanation.get("analyst_assisted") else 0
        self.conn.execute(
            """
            INSERT INTO analyst_theses (idea_id, analyst_mode, model, prompt_context_json, thesis_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                explanation.get("analyst_mode", "mock"),
                explanation.get("model", ""),
                json.dumps(prompt_context, default=str),
                json.dumps(explanation, default=str),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO trade_explanations
              (idea_id, explanation_json, source_refs_json, analyst_assisted)
            VALUES (?, ?, ?, ?)
            """,
            (
                idea_id,
                json.dumps(explanation, default=str),
                json.dumps(explanation.get("source_refs", []), default=str),
                analyst_assisted,
            ),
        )
        if analyst_assisted:
            self.conn.execute(
                """
                INSERT INTO approval_queue (idea_id, status)
                VALUES (?, 'needs_review')
                ON CONFLICT(idea_id) DO UPDATE SET status = 'needs_review', reviewer_note = '', reviewed_at = NULL
                """,
                (idea_id,),
            )
            self.conn.execute(
                "UPDATE alpha_ideas SET status = 'needs_review', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (idea_id,),
            )
        self.conn.commit()
        return self.get_trade_explanation(idea_id)

    def get_trade_explanation(self, idea_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM trade_explanations
            WHERE idea_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
            """,
            (idea_id,),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["explanation"] = json.loads(payload.pop("explanation_json"))
        payload["source_refs"] = json.loads(payload.pop("source_refs_json") or "[]")
        return payload

    def list_pending_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT q.*, i.ticker, i.bias, i.confidence, i.timeframe, i.thesis, i.catalyst, i.source, i.status AS idea_status
            FROM approval_queue q
            JOIN alpha_ideas i ON i.id = q.idea_id
            WHERE q.status = 'needs_review' AND i.status = 'needs_review'
            ORDER BY datetime(q.created_at) ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["trade_explanation"] = self.get_trade_explanation(int(item["idea_id"]))
            output.append(item)
        return output

    def set_approval_status(self, idea_id: int, status: str, note: str = "") -> dict[str, Any]:
        if status not in {"approved", "rejected", "expired"}:
            raise ValueError("approval status must be approved, rejected, or expired")
        if status == "approved":
            state = self.conn.execute(
                """
                SELECT i.status AS idea_status, q.status AS approval_status
                FROM alpha_ideas i
                LEFT JOIN approval_queue q ON q.idea_id = i.id
                WHERE i.id = ?
                """,
                (idea_id,),
            ).fetchone()
            if state is None:
                raise KeyError(f"idea not found: {idea_id}")
            if state["idea_status"] != "needs_review" or state["approval_status"] != "needs_review":
                raise ValueError(
                    f"idea {idea_id} is not eligible for approval: "
                    f"idea_status={state['idea_status']} "
                    f"approval_status={state['approval_status'] or 'missing'}"
                )
        idea_status = status
        self.conn.execute(
            """
            INSERT INTO approval_queue (idea_id, status, reviewer_note, reviewed_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(idea_id) DO UPDATE SET status = excluded.status, reviewer_note = excluded.reviewer_note, reviewed_at = CURRENT_TIMESTAMP
            """,
            (idea_id, status, note),
        )
        self.conn.execute(
            "UPDATE alpha_ideas SET status = ?, rejection_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (idea_status, note if status == "rejected" else "", idea_id),
        )
        self.conn.commit()
        return self.get_idea(idea_id)

    def approval_status_for_idea(self, idea_id: int) -> str:
        row = self.conn.execute("SELECT status FROM approval_queue WHERE idea_id = ?", (idea_id,)).fetchone()
        return str(row["status"]) if row else ""

    def save_market_briefing(self, payload: dict[str, Any]) -> dict[str, Any]:
        cur = self.conn.execute(
            """
            INSERT INTO market_briefings (briefing_type, payload_json, generated_at)
            VALUES (?, ?, ?)
            """,
            (
                payload.get("briefing_type", "daily"),
                json.dumps(payload, default=str),
                payload.get("generated_at", ""),
            ),
        )
        self.conn.commit()
        return self.get_market_briefing(int(cur.lastrowid))

    def get_market_briefing(self, briefing_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM market_briefings WHERE id = ?", (briefing_id,)).fetchone()
        if row is None:
            raise KeyError(f"briefing not found: {briefing_id}")
        payload = dict(row)
        payload["payload"] = json.loads(payload.pop("payload_json"))
        return payload

    def list_market_briefings(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM market_briefings ORDER BY datetime(created_at) DESC LIMIT ?", (limit,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            output.append(item)
        return output

    def save_futures_pulse(self, report: dict[str, Any]) -> int:
        """Persist a futures pulse run: the snapshot row, every per-contract move,
        and any catalyst->reaction links. Returns the snapshot id."""
        regime = report.get("regime", {}) or {}
        cur = self.conn.execute(
            """
            INSERT INTO futures_snapshots
              (session_date, generated_at, regime, regime_label, confidence,
               catalyst_timestamp, summary, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.get("session_date", ""),
                report.get("generated_at", ""),
                str(regime.get("regime", "neutral")),
                str(regime.get("label", "")),
                float(regime.get("confidence", 0) or 0),
                str(report.get("catalyst_timestamp") or ""),
                str(report.get("summary", "")),
                json.dumps(report, default=str),
            ),
        )
        snapshot_id = int(cur.lastrowid)
        session_date = report.get("session_date", "")
        catalyst_ts = report.get("catalyst_timestamp")
        for move in report.get("moves", []):
            if not move.get("has_data"):
                continue
            self.conn.execute(
                """
                INSERT INTO futures_moves
                  (snapshot_id, session_date, symbol, category, last_price, prior_close,
                   net_move_pct, overnight_high, overnight_low, range_pct,
                   avg_overnight_move_pct_20d, move_vs_avg, unusual, direction,
                   moved_at, catalyst_move_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id, session_date, move.get("symbol", ""), move.get("category", ""),
                    move.get("last_price"), move.get("prior_close"),
                    float(move.get("net_move_pct", 0) or 0), move.get("overnight_high"),
                    move.get("overnight_low"), float(move.get("range_pct", 0) or 0),
                    move.get("avg_overnight_move_pct_20d"), move.get("move_vs_avg"),
                    _as_int_bool(move.get("unusual")) or 0, str(move.get("direction", "flat")),
                    str(move.get("moved_at") or ""), move.get("catalyst_move_pct"),
                ),
            )
            if catalyst_ts and move.get("catalyst_move_pct") is not None:
                self.conn.execute(
                    """
                    INSERT INTO catalyst_futures_reactions
                      (snapshot_id, session_date, catalyst_timestamp, symbol, category,
                       net_move_pct, catalyst_move_pct, regime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id, session_date, str(catalyst_ts), move.get("symbol", ""),
                        move.get("category", ""), float(move.get("net_move_pct", 0) or 0),
                        move.get("catalyst_move_pct"), str(regime.get("regime", "neutral")),
                    ),
                )
        self.conn.commit()
        return snapshot_id

    def list_futures_snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM futures_snapshots ORDER BY datetime(created_at) DESC LIMIT ?", (limit,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            output.append(item)
        return output

    def list_futures_moves(self, session_date: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if session_date:
            rows = self.conn.execute(
                "SELECT * FROM futures_moves WHERE session_date = ? ORDER BY datetime(created_at) DESC LIMIT ?",
                (session_date, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM futures_moves ORDER BY datetime(created_at) DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_strategy(self, name: str) -> int:
        self.conn.execute("INSERT OR IGNORE INTO strategies (name) VALUES (?)", (name,))
        row = self.conn.execute("SELECT id FROM strategies WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def list_ideas(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM alpha_ideas ORDER BY datetime(created_at) DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._idea_with_strategies(dict(row)) for row in rows]

    def get_idea(self, idea_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM alpha_ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise KeyError(f"idea not found: {idea_id}")
        return self._idea_with_strategies(dict(row))

    def update_idea_status(self, idea_id: int, status: str, reason: str = "") -> dict[str, Any]:
        self.conn.execute(
            "UPDATE alpha_ideas SET status = ?, rejection_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, reason, idea_id),
        )
        self.conn.commit()
        return self.get_idea(idea_id)

    def log_decision(self, idea_id: int, action: str, reasons: list[str], decision: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO decision_logs (idea_id, action, reasons_json, decision_json) VALUES (?, ?, ?, ?)",
            (idea_id, action, json.dumps(reasons), json.dumps(decision, default=str)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def create_trade(self, trade: dict[str, Any]) -> int:
        if trade.get("idea_id"):
            self._ensure_idea_has_strategy(int(trade["idea_id"]))
        option = trade.get("option") or {}
        alpha = trade.get("alpha") or {}
        flow = trade.get("options_flow") or {}
        inst = trade.get("institutional") or {}
        cur = self.conn.execute(
            """
            INSERT INTO trades
              (idea_id, ticker, side, quantity, notional, entry_price, realized_pl, unrealized_pl,
               status, dry_run, asset_type, decision_log_id, underlying, contract_symbol, option_type,
               strike, expiry, dte, contracts, entry_underlying_price, entry_bid, entry_ask, entry_mid,
               entry_spread_pct, entry_iv, entry_delta, entry_open_interest, entry_volume,
               alpha_composite, alpha_tier, confirmed, gate_applied, catalyst_score, price_volume_score,
               narrative_score, macro_score, options_score, options_component, call_volume, put_volume,
               call_put_ratio, open_interest_change, options_bias, options_flow_json,
               institutional_score, institutional_component, dark_pool_notional, block_count,
               institutional_bias, institutional_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("idea_id"),
                trade["ticker"],
                trade["side"],
                trade.get("quantity"),
                trade.get("notional"),
                trade.get("entry_price"),
                float(trade.get("realized_pl", 0) or 0),
                float(trade.get("unrealized_pl", 0) or 0),
                trade["status"],
                1 if trade.get("dry_run", True) else 0,
                trade.get("asset_type", "equity"),
                trade.get("decision_log_id"),
                option.get("underlying"),
                option.get("contract_symbol"),
                option.get("option_type"),
                option.get("strike"),
                option.get("expiry"),
                option.get("dte"),
                trade.get("contracts"),
                option.get("underlying_price"),
                option.get("bid"),
                option.get("ask"),
                option.get("mid"),
                option.get("spread_pct"),
                option.get("implied_volatility"),
                option.get("delta"),
                option.get("open_interest"),
                option.get("volume"),
                alpha.get("composite_score"),
                alpha.get("tier"),
                _as_int_bool(alpha.get("confirmed")),
                _as_int_bool(alpha.get("gate_applied")),
                alpha.get("catalyst_score"),
                alpha.get("price_volume_score"),
                alpha.get("narrative_score"),
                alpha.get("macro_score"),
                flow.get("options_score"),
                flow.get("component_score"),
                flow.get("call_volume"),
                flow.get("put_volume"),
                flow.get("call_put_ratio"),
                flow.get("open_interest_change"),
                flow.get("bias"),
                json.dumps(flow, default=str) if flow else None,
                inst.get("institutional_score"),
                inst.get("component_score"),
                inst.get("dark_pool_notional"),
                inst.get("block_count"),
                inst.get("bias"),
                json.dumps(inst, default=str) if inst else None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def log_execution_attempt(self, attempt: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO execution_audit
              (idea_id, ticker, side, quantity, order_type, requested_entry, submitted_price,
               status, rejection_reason, alpaca_order_id, payload_json, response_json, dry_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.get("idea_id"),
                str(attempt.get("ticker", "")).upper(),
                attempt.get("side", ""),
                attempt.get("quantity"),
                attempt.get("order_type", ""),
                attempt.get("requested_entry", ""),
                attempt.get("submitted_price"),
                attempt.get("status", ""),
                attempt.get("rejection_reason", ""),
                attempt.get("alpaca_order_id", ""),
                json.dumps(attempt.get("payload", {}), default=str),
                json.dumps(attempt.get("response", {}), default=str),
                1 if attempt.get("dry_run", True) else 0,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_execution_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM execution_audit ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["response"] = json.loads(item.pop("response_json") or "{}")
            item["timestamp"] = item["created_at"]
            output.append(item)
        return output

    def create_order(self, order: dict[str, Any]) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO orders
              (trade_id, alpaca_order_id, ticker, side, payload_json, response_json, status, dry_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.get("trade_id"),
                order.get("alpaca_order_id"),
                order["ticker"],
                order["side"],
                json.dumps(order["payload"]),
                json.dumps(order.get("response", {}), default=str),
                order["status"],
                1 if order.get("dry_run", True) else 0,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def entry_order_id_for_trade(self, trade_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT alpaca_order_id FROM orders WHERE trade_id = ? ORDER BY id ASC LIMIT 1",
            (trade_id,),
        ).fetchone()
        return str(row["alpaca_order_id"]) if row and row["alpaca_order_id"] else None

    def list_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM trades ORDER BY datetime(opened_at) DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_trade(self, trade_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            raise KeyError(f"trade not found: {trade_id}")
        return dict(row)

    def record_fill(self, trade_id: int, entry_price: float | None, status: str = "paper_open") -> None:
        self.conn.execute(
            "UPDATE trades SET entry_price = COALESCE(?, entry_price), status = ? WHERE id = ?",
            (entry_price, status, trade_id),
        )
        self.conn.commit()

    def close_trade(
        self,
        trade_id: int,
        exit_price: float | None,
        realized_pl: float,
        status: str = "closed",
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, realized_pl = ?, unrealized_pl = 0,
                status = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (exit_price, float(realized_pl), status, trade_id),
        )
        self.conn.commit()
        return self.get_trade(trade_id)

    def list_idea_performance(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
              i.*,
              t.id AS trade_id,
              t.side,
              t.quantity,
              t.notional,
              t.entry_price,
              t.exit_price,
              t.realized_pl,
              t.unrealized_pl,
              t.status AS trade_status,
              t.dry_run,
              t.opened_at,
              t.closed_at,
              se.alert_price AS signal_alert_price,
              se.price_after AS signal_price_after,
              se.move_after_pct AS signal_move_after_pct,
              se.benchmark_move_pct AS signal_benchmark_move_pct,
              se.early_detection_score,
              se.provisional_grade,
              se.final_grade,
              se.status AS evaluation_status,
              se.evaluated_at AS signal_evaluated_at
            FROM alpha_ideas i
            LEFT JOIN trades t ON t.idea_id = i.id
            LEFT JOIN signal_evaluations se ON se.idea_id = i.id
            ORDER BY datetime(COALESCE(t.opened_at, i.created_at)) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["strategies"] = self._strategies_for_idea(int(item["id"]))
            explanation = self.get_trade_explanation(int(item["id"]))
            item["trade_explanation"] = explanation["explanation"] if explanation else {}
            output.append(item)
        return output

    def strategy_scoreboard(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.list_idea_performance(1000)
        return {
            "by_setup_type": self._scoreboard(rows, lambda row: row.get("trade_explanation", {}).get("setup_type") or "Unknown setup"),
            "by_catalyst_type": self._scoreboard(rows, lambda row: row.get("theme") or row.get("source") or "Unknown catalyst"),
            "by_ticker": self._scoreboard(rows, lambda row: row.get("ticker") or "Unknown ticker"),
            "by_confidence_bucket": self._scoreboard(rows, lambda row: self._confidence_bucket(row.get("confidence"))),
            "by_time_horizon": self._scoreboard(rows, lambda row: row.get("timeframe") or row.get("trade_explanation", {}).get("time_horizon") or "Unknown horizon"),
        }

    def sync_positions(self, positions: list[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM positions")
        for pos in positions:
            self.conn.execute(
                """
                INSERT INTO positions (ticker, qty, market_value, unrealized_pl)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(pos.get("symbol", "")).upper(),
                    float(pos.get("qty", 0) or 0),
                    float(pos.get("market_value", 0) or 0),
                    float(pos.get("unrealized_pl", 0) or 0),
                ),
            )
        self.conn.commit()

    def create_journal(self, payload: dict[str, Any]) -> dict[str, Any]:
        cur = self.conn.execute(
            """
            INSERT INTO journal_entries
              (idea_id, trade_id, original_thesis, entry_reason, exit_reason, what_happened,
               thesis_correct, lesson_learned, strategy_rating, mistake_tag, follow_up_reminder, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("idea_id"),
                payload.get("trade_id"),
                payload.get("original_thesis", ""),
                payload.get("entry_reason", ""),
                payload.get("exit_reason", ""),
                payload.get("what_happened", ""),
                payload.get("thesis_correct"),
                payload.get("lesson_learned", ""),
                payload.get("strategy_rating"),
                payload.get("mistake_tag", ""),
                payload.get("follow_up_reminder", ""),
                payload.get("notes", ""),
            ),
        )
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM journal_entries WHERE id = ?", (cur.lastrowid,)).fetchone())

    def strategy_stats(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT s.id AS strategy_id,
                   s.name AS strategy,
                   COUNT(t.id) AS trades,
                   SUM(CASE WHEN t.id IS NOT NULL AND COALESCE(t.dry_run, 1) = 0 THEN 1 ELSE 0 END) AS paper_trades,
                   SUM(CASE WHEN t.id IS NOT NULL AND COALESCE(t.dry_run, 1) = 1 THEN 1 ELSE 0 END) AS dry_run_trades,
                   SUM(CASE WHEN t.id IS NOT NULL AND t.status IN ('paper_open', 'submitted') THEN 1 ELSE 0 END) AS open_trades,
                   SUM(CASE WHEN t.id IS NOT NULL AND t.status = 'closed' THEN 1 ELSE 0 END) AS closed_trades,
                   SUM(CASE WHEN t.id IS NOT NULL AND COALESCE(t.realized_pl, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(COALESCE(t.realized_pl, 0)) AS realized_pl,
                   SUM(COALESCE(t.unrealized_pl, 0)) AS unrealized_pl,
                   AVG(COALESCE(t.realized_pl, 0)) AS avg_pl,
                   AVG(i.confidence) AS avg_confidence
            FROM strategies s
            LEFT JOIN idea_strategies ix ON ix.strategy_id = s.id
            LEFT JOIN alpha_ideas i ON i.id = ix.idea_id
            LEFT JOIN trades t ON t.idea_id = ix.idea_id
            GROUP BY s.id
            ORDER BY trades DESC, strategy ASC
            """
        ).fetchall()
        stats = []
        for row in rows:
            trades = int(row["trades"] or 0)
            wins = int(row["wins"] or 0)
            strategy_id = int(row["strategy_id"])
            stats.append(
                {
                    "strategy_id": strategy_id,
                    "strategy": row["strategy"],
                    "trades": trades,
                    "paper_trades": int(row["paper_trades"] or 0),
                    "dry_run_trades": int(row["dry_run_trades"] or 0),
                    "open_trades": int(row["open_trades"] or 0),
                    "closed_trades": int(row["closed_trades"] or 0),
                    "wins": wins,
                    "win_rate": round(wins / trades, 4) if trades else 0,
                    "avg_pl": float(row["avg_pl"] or 0),
                    "realized_pl": float(row["realized_pl"] or 0),
                    "unrealized_pl": float(row["unrealized_pl"] or 0),
                    "avg_confidence": float(row["avg_confidence"] or 0),
                    "recent_trades": self._recent_trades_for_strategy(strategy_id),
                }
            )
        return stats

    def strategy_diagnostics(self) -> dict[str, Any]:
        trade_count = self._count_all("trades")
        strategy_count = self._count_all("strategies")
        missing = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM trades t
            LEFT JOIN idea_strategies ix ON ix.idea_id = t.idea_id
            WHERE ix.strategy_id IS NULL
            """
        ).fetchone()["count"]
        return {
            "trade_count": int(trade_count),
            "strategy_count": int(strategy_count),
            "trades_missing_strategy_labels": int(missing or 0),
            "has_strategy_stats": any(row["trades"] for row in self.strategy_stats()),
        }

    def _scoreboard(self, rows: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(str(key_fn(row) or "Unknown"), []).append(row)
        output = []
        for key, items in groups.items():
            executed = [item for item in items if item.get("trade_id") and not int(item.get("dry_run") or 0)]
            approved = [item for item in items if item.get("status") in {"approved", "traded"}]
            returns = [self._return_pct(item) for item in executed if self._return_pct(item) is not None]
            wins = [value for value in returns if value > 0]
            output.append(
                {
                    "group": key,
                    "total_ideas": len({item["id"] for item in items}),
                    "approved_ideas": len({item["id"] for item in approved}),
                    "executed_ideas": len({item["id"] for item in executed}),
                    "win_rate": round(len(wins) / len(returns), 4) if returns else 0,
                    "average_return": round(sum(returns) / len(returns), 4) if returns else 0,
                    "best_trade": round(max(returns), 4) if returns else 0,
                    "worst_trade": round(min(returns), 4) if returns else 0,
                    "average_hold_time": self._average_hold_time(executed),
                }
            )
        output.sort(key=lambda row: (row["executed_ideas"], row["total_ideas"]), reverse=True)
        return output

    def _return_pct(self, row: dict[str, Any]) -> float | None:
        entry = row.get("entry_price")
        if not entry:
            notional = float(row.get("notional") or 0)
            pl = float(row.get("realized_pl") or row.get("unrealized_pl") or 0)
            return (pl / notional * 100) if notional else None
        exit_or_mark = row.get("exit_price") or row.get("current_price") or entry
        side = row.get("side")
        value = ((float(exit_or_mark) - float(entry)) / float(entry)) * 100
        return -value if side == "sell" else value

    def _average_hold_time(self, rows: list[dict[str, Any]]) -> str:
        return "n/a"

    def _confidence_bucket(self, confidence: Any) -> str:
        value = float(confidence or 0)
        if value >= 0.9:
            return "0.90-1.00"
        if value >= 0.8:
            return "0.80-0.89"
        if value >= 0.7:
            return "0.70-0.79"
        return "<0.70"

    def dashboard_counts(self) -> dict[str, Any]:
        return {
            "total_ideas": self._count_all("alpha_ideas"),
            "ideas_today": self._count_today("alpha_ideas", "created_at"),
            "trades_today": self._count_today("trades", "opened_at"),
            "paper_orders_today": self._count_today_where("trades", "opened_at", "dry_run = 0"),
            "dry_run_tests_today": self._count_today_where("trades", "opened_at", "dry_run = 1"),
            "total_rejected": self._count_where("alpha_ideas", "status = 'rejected'"),
            "rejected_today": self._count_today_where("alpha_ideas", "created_at", "status = 'rejected'"),
        }

    def _idea_with_strategies(self, idea: dict[str, Any]) -> dict[str, Any]:
        idea["strategies"] = self._strategies_for_idea(int(idea["id"]))
        explanation = self.get_trade_explanation(int(idea["id"]))
        if explanation:
            idea["trade_explanation"] = explanation["explanation"]
            idea["analyst_assisted"] = bool(explanation["analyst_assisted"])
        return idea

    def _hydrate_catalyst_event(self, event: dict[str, Any]) -> dict[str, Any]:
        for source_key, target_key in (
            ("matched_keywords_json", "matched_keywords"),
            ("explanation_json", "explanation"),
            ("supporting_evidence_json", "supporting_evidence"),
            ("raw_payload_json", "raw_payload"),
        ):
            value = event.pop(source_key, None)
            try:
                event[target_key] = json.loads(value or "[]" if source_key != "raw_payload_json" else value or "{}")
            except (TypeError, ValueError):
                event[target_key] = {} if source_key == "raw_payload_json" else []
        return event

    def _strategies_for_idea(self, idea_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT s.name FROM strategies s
            JOIN idea_strategies ix ON ix.strategy_id = s.id
            WHERE ix.idea_id = ?
            ORDER BY s.name
            """,
            (idea_id,),
        ).fetchall()
        return [row["name"] for row in rows]

    def _ensure_idea_has_strategy(self, idea_id: int) -> None:
        if self.conn.execute("SELECT 1 FROM idea_strategies WHERE idea_id = ? LIMIT 1", (idea_id,)).fetchone():
            return
        idea = self.conn.execute("SELECT theme, source FROM alpha_ideas WHERE id = ?", (idea_id,)).fetchone()
        if idea is None:
            return
        label = str(idea["theme"] or idea["source"] or "untagged").strip() or "untagged"
        strategy_id = self.ensure_strategy(label)
        self.conn.execute(
            "INSERT OR IGNORE INTO idea_strategies (idea_id, strategy_id) VALUES (?, ?)",
            (idea_id, strategy_id),
        )
        self.conn.commit()

    def _recent_trades_for_strategy(self, strategy_id: int, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT t.id, t.idea_id, t.ticker, t.side, t.quantity, t.notional,
                   t.status, t.dry_run, t.realized_pl, t.unrealized_pl,
                   t.opened_at, t.closed_at, i.confidence, i.timeframe, i.theme
            FROM trades t
            JOIN idea_strategies ix ON ix.idea_id = t.idea_id
            LEFT JOIN alpha_ideas i ON i.id = t.idea_id
            WHERE ix.strategy_id = ?
            ORDER BY datetime(t.opened_at) DESC, t.id DESC
            LIMIT ?
            """,
            (strategy_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


    def _count_all(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])

    def _count_where(self, table: str, where: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}").fetchone()["count"])

    def _count_today(self, table: str, date_col: str) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE date({date_col}, 'localtime') = date('now', 'localtime')"
            ).fetchone()["count"]
        )

    def _count_today_where(self, table: str, date_col: str, where: str) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE date({date_col}, 'localtime') = date('now', 'localtime') AND {where}"
            ).fetchone()["count"]
        )
