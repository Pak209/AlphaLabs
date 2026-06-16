from __future__ import annotations

import os
import sqlite3
from pathlib import Path


# Repo-relative fallback used ONLY for local dev and hermetic tests (no env set).
# Production servers pin an absolute path via ALPHA_LAB_DB_PATH (see below).
DEFAULT_DB_PATH = "alpha_lab/data/alpha_lab.sqlite3"

# Canonical persistent path within the checkout. Deployments may pin the absolute
# form of this path via ALPHA_LAB_DB_PATH so dashboard, scheduler, and reports
# resolve the same file.
CANONICAL_SERVER_DB_PATH = DEFAULT_DB_PATH


def resolve_db_path(explicit: str | None = None) -> str:
    """Resolve the SQLite DB path with a clear precedence chain.

    explicit argument  >  ALPHA_LAB_DB_PATH env var  >  DEFAULT_DB_PATH.

    The env var is read at CALL time (never import time), so importing this
    module — or constructing a service in a hermetic test without setting the
    var — still falls back to the local-dev default, while production entry
    points that have loaded their .env automatically resolve to the configured
    path. Pass an explicit path (e.g. in tests) to override both. ``~`` is
    expanded so deployment env files can use user-relative absolute paths.
    """
    resolved = explicit or os.getenv("ALPHA_LAB_DB_PATH") or DEFAULT_DB_PATH
    return str(Path(resolved).expanduser())


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(alpha_ideas)").fetchall()}
    if "asset_type" not in columns:
        conn.execute("ALTER TABLE alpha_ideas ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'equity'")

    # Alpha Report Card columns. These are stamped on each idea AT CREATION so the
    # Performance page can grade signal quality by source and by the market regime
    # that was in force when the signal fired. Older rows leave these NULL/'' and
    # are bucketed as "unknown" — real coverage accumulates going forward.
    idea_report_columns = {
        "source_tags": "TEXT NOT NULL DEFAULT '[]'",
        "market_regime": "TEXT NOT NULL DEFAULT 'unknown'",
        "catalyst_type": "TEXT NOT NULL DEFAULT ''",
        "catalyst_score": "REAL",
        "catalyst_event_id": "INTEGER",
    }
    for name, ddl in idea_report_columns.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE alpha_ideas ADD COLUMN {name} {ddl}")

    # Option-trade columns + decision link on the trades table. Equity/crypto rows
    # leave these NULL; option rows populate them so the training_rows view can
    # join entry features to the realized outcome later.
    trade_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
    option_trade_columns = {
        "asset_type": "TEXT NOT NULL DEFAULT 'equity'",
        "underlying": "TEXT",
        "contract_symbol": "TEXT",
        "option_type": "TEXT",
        "strike": "REAL",
        "expiry": "TEXT",
        "dte": "INTEGER",
        "contracts": "INTEGER",
        "entry_underlying_price": "REAL",
        "entry_bid": "REAL",
        "entry_ask": "REAL",
        "entry_mid": "REAL",
        "entry_spread_pct": "REAL",
        "entry_iv": "REAL",
        "entry_delta": "REAL",
        "entry_open_interest": "INTEGER",
        "entry_volume": "INTEGER",
        "decision_log_id": "INTEGER",
    }
    for name, ddl in option_trade_columns.items():
        if name not in trade_columns:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")

    # Alpha-score + signal-source columns. These persist the full conviction
    # picture for every trade: the composite/tier, each component score, and the
    # options-flow / dark-pool metrics (raw points + a JSON snapshot for fidelity)
    # so the training_rows view can join entry conviction to the realized outcome.
    signal_columns = {
        "alpha_composite": "REAL",
        "alpha_tier": "TEXT",
        "confirmed": "INTEGER",
        "gate_applied": "INTEGER",
        "catalyst_score": "REAL",
        "price_volume_score": "REAL",
        "narrative_score": "REAL",
        "macro_score": "REAL",
        "options_score": "INTEGER",
        "options_component": "REAL",
        "call_volume": "INTEGER",
        "put_volume": "INTEGER",
        "call_put_ratio": "REAL",
        "open_interest_change": "INTEGER",
        "options_bias": "TEXT",
        "options_flow_json": "TEXT",
        "institutional_score": "INTEGER",
        "institutional_component": "REAL",
        "dark_pool_notional": "REAL",
        "block_count": "INTEGER",
        "institutional_bias": "TEXT",
        "institutional_json": "TEXT",
    }
    for name, ddl in signal_columns.items():
        if name not in trade_columns:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")

    # (Re)create the training-row view after the columns exist. Dropping first keeps
    # it in sync if the column set changes between releases.
    conn.execute("DROP VIEW IF EXISTS training_rows")
    conn.execute(TRAINING_ROWS_VIEW)
    conn.commit()


TRAINING_ROWS_VIEW = """
CREATE VIEW training_rows AS
SELECT
  t.id                     AS trade_id,
  t.idea_id                AS idea_id,
  COALESCE(t.underlying, i.ticker) AS underlying,
  i.bias                   AS bias,
  i.confidence             AS idea_confidence,
  i.timeframe              AS timeframe,
  i.theme                  AS theme,
  i.source                 AS source,
  i.market_regime          AS market_regime,
  i.catalyst_type          AS catalyst_type,
  i.catalyst_score         AS idea_catalyst_score,
  (
    SELECT GROUP_CONCAT(s.name, '|')
    FROM idea_strategies ix
    JOIN strategies s ON s.id = ix.strategy_id
    WHERE ix.idea_id = i.id
  )                        AS strategies,
  t.asset_type             AS asset_type,
  t.contract_symbol        AS contract_symbol,
  t.option_type            AS option_type,
  t.strike                 AS strike,
  t.expiry                 AS expiry,
  t.dte                    AS dte,
  t.contracts              AS contracts,
  t.entry_underlying_price AS entry_underlying_price,
  t.entry_bid              AS entry_bid,
  t.entry_ask              AS entry_ask,
  t.entry_mid              AS entry_mid,
  t.entry_spread_pct       AS entry_spread_pct,
  t.entry_iv               AS entry_iv,
  t.entry_delta            AS entry_delta,
  t.entry_open_interest    AS entry_open_interest,
  t.entry_volume           AS entry_volume,
  t.entry_price            AS entry_price,
  t.alpha_composite        AS alpha_composite,
  t.alpha_tier             AS alpha_tier,
  t.confirmed              AS confirmed,
  t.gate_applied           AS gate_applied,
  t.catalyst_score         AS catalyst_score,
  t.price_volume_score     AS price_volume_score,
  t.narrative_score        AS narrative_score,
  t.macro_score            AS macro_score,
  t.options_score          AS options_score,
  t.options_component      AS options_component,
  t.call_volume            AS call_volume,
  t.put_volume             AS put_volume,
  t.call_put_ratio         AS call_put_ratio,
  t.open_interest_change   AS open_interest_change,
  t.options_bias           AS options_bias,
  t.institutional_score    AS institutional_score,
  t.institutional_component AS institutional_component,
  t.dark_pool_notional     AS dark_pool_notional,
  t.block_count            AS block_count,
  t.institutional_bias     AS institutional_bias,
  t.exit_price             AS exit_price,
  CASE
    WHEN t.entry_price IS NOT NULL AND t.entry_price != 0 AND t.exit_price IS NOT NULL
      THEN ((t.exit_price - t.entry_price) / t.entry_price) * CASE WHEN t.side = 'sell' THEN -100 ELSE 100 END
    WHEN t.notional IS NOT NULL AND t.notional != 0
      THEN (COALESCE(t.realized_pl, t.unrealized_pl, 0) / t.notional) * 100
    ELSE NULL
  END                      AS realized_return,
  CASE
    WHEN t.opened_at IS NOT NULL AND t.closed_at IS NOT NULL
      THEN ROUND((julianday(t.closed_at) - julianday(t.opened_at)) * 24, 2)
    ELSE NULL
  END                      AS holding_period_hours,
  t.realized_pl            AS realized_pl,
  t.unrealized_pl          AS unrealized_pl,
  t.status                 AS trade_status,
  t.dry_run                AS dry_run,
  t.opened_at              AS opened_at,
  t.closed_at              AS closed_at,
  dl.action                AS decision_action,
  dl.decision_json         AS decision_json
FROM trades t
LEFT JOIN alpha_ideas i  ON i.id = t.idea_id
LEFT JOIN decision_logs dl ON dl.id = t.decision_log_id
"""


SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alpha_ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  asset_type TEXT NOT NULL DEFAULT 'equity',
  sector TEXT DEFAULT '',
  theme TEXT DEFAULT '',
  bias TEXT NOT NULL,
  confidence REAL NOT NULL,
  timeframe TEXT NOT NULL,
  thesis TEXT NOT NULL,
  catalyst TEXT DEFAULT '',
  catalyst_type TEXT NOT NULL DEFAULT '',
  catalyst_score REAL,
  catalyst_event_id INTEGER,
  source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  rejection_reason TEXT DEFAULT '',
  timestamp TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalyst_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  security_type TEXT NOT NULL DEFAULT 'stock',
  sector TEXT NOT NULL DEFAULT '',
  catalyst_type TEXT NOT NULL,
  strategy_label TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT 'neutral',
  headline TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  source_url TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  novelty_score REAL NOT NULL DEFAULT 0,
  urgency_score REAL NOT NULL DEFAULT 0,
  historical_score REAL NOT NULL DEFAULT 0,
  relevance_score REAL NOT NULL DEFAULT 0,
  market_impact_score REAL NOT NULL DEFAULT 0,
  source_quality_score REAL NOT NULL DEFAULT 0,
  keyword_score REAL NOT NULL DEFAULT 0,
  sector_score REAL NOT NULL DEFAULT 0,
  catalyst_score INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  market_regime TEXT NOT NULL DEFAULT 'unknown',
  matched_keywords_json TEXT NOT NULL DEFAULT '[]',
  explanation_json TEXT NOT NULL DEFAULT '[]',
  supporting_evidence_json TEXT NOT NULL DEFAULT '[]',
  raw_payload_json TEXT NOT NULL DEFAULT '{}',
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_catalyst_events_score ON catalyst_events(catalyst_score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_catalyst_events_ticker_time ON catalyst_events(ticker, published_at);
CREATE INDEX IF NOT EXISTS idx_catalyst_events_strategy ON catalyst_events(strategy_label);

CREATE TABLE IF NOT EXISTS idea_strategies (
  idea_id INTEGER NOT NULL REFERENCES alpha_ideas(id) ON DELETE CASCADE,
  strategy_id INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
  PRIMARY KEY (idea_id, strategy_id)
);

CREATE TABLE IF NOT EXISTS signal_evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL UNIQUE REFERENCES alpha_ideas(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  source TEXT NOT NULL,
  source_tags TEXT NOT NULL DEFAULT '[]',
  generated_at TEXT NOT NULL,
  evaluated_at TEXT,
  horizon TEXT NOT NULL DEFAULT 'intraday',
  direction TEXT NOT NULL DEFAULT '',
  confidence REAL,
  market_regime TEXT NOT NULL DEFAULT 'unknown',
  catalyst TEXT DEFAULT '',
  alert_price REAL,
  price_after REAL,
  move_after_pct REAL,
  benchmark_move_pct REAL,
  early_detection_score REAL,
  provisional_grade TEXT,
  final_grade TEXT,
  status TEXT NOT NULL DEFAULT 'provisional',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity REAL,
  notional REAL,
  entry_price REAL,
  exit_price REAL,
  realized_pl REAL DEFAULT 0,
  unrealized_pl REAL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'dry_run',
  dry_run INTEGER NOT NULL DEFAULT 1,
  opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS execution_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,
  side TEXT DEFAULT '',
  quantity REAL,
  order_type TEXT DEFAULT '',
  requested_entry TEXT DEFAULT '',
  submitted_price REAL,
  status TEXT NOT NULL,
  rejection_reason TEXT DEFAULT '',
  alpaca_order_id TEXT DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  dry_run INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER REFERENCES trades(id) ON DELETE SET NULL,
  alpaca_order_id TEXT,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  response_json TEXT DEFAULT '',
  status TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL UNIQUE,
  qty REAL NOT NULL DEFAULT 0,
  market_value REAL NOT NULL DEFAULT 0,
  unrealized_pl REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'alpaca_paper',
  synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE SET NULL,
  trade_id INTEGER REFERENCES trades(id) ON DELETE SET NULL,
  original_thesis TEXT DEFAULT '',
  entry_reason TEXT DEFAULT '',
  exit_reason TEXT DEFAULT '',
  what_happened TEXT DEFAULT '',
  thesis_correct INTEGER,
  lesson_learned TEXT DEFAULT '',
  strategy_rating INTEGER,
  mistake_tag TEXT DEFAULT '',
  follow_up_reminder TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scanner_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  run_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decision_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  decision_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_config (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyst_theses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER REFERENCES alpha_ideas(id) ON DELETE CASCADE,
  analyst_mode TEXT NOT NULL DEFAULT 'mock',
  model TEXT DEFAULT '',
  prompt_context_json TEXT NOT NULL DEFAULT '{}',
  thesis_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_explanations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL REFERENCES alpha_ideas(id) ON DELETE CASCADE,
  explanation_json TEXT NOT NULL,
  source_refs_json TEXT NOT NULL DEFAULT '[]',
  analyst_assisted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approval_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL UNIQUE REFERENCES alpha_ideas(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'needs_review',
  requested_by TEXT NOT NULL DEFAULT 'llm_analyst',
  reviewer_note TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS market_briefings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  briefing_type TEXT NOT NULL DEFAULT 'daily',
  payload_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Overnight Futures Pulse. One row per pulse run captures the board-level regime
-- read; futures_moves stores the per-contract overnight move for backtesting; and
-- catalyst_futures_reactions links a catalyst timestamp to the move that followed.
CREATE TABLE IF NOT EXISTS futures_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  regime TEXT NOT NULL,
  regime_label TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  catalyst_timestamp TEXT DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS futures_moves (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER REFERENCES futures_snapshots(id) ON DELETE CASCADE,
  session_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  last_price REAL,
  prior_close REAL,
  net_move_pct REAL NOT NULL DEFAULT 0,
  overnight_high REAL,
  overnight_low REAL,
  range_pct REAL NOT NULL DEFAULT 0,
  avg_overnight_move_pct_20d REAL,
  move_vs_avg REAL,
  unusual INTEGER NOT NULL DEFAULT 0,
  direction TEXT NOT NULL DEFAULT 'flat',
  moved_at TEXT DEFAULT '',
  catalyst_move_pct REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalyst_futures_reactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER REFERENCES futures_snapshots(id) ON DELETE CASCADE,
  session_date TEXT NOT NULL,
  catalyst_timestamp TEXT NOT NULL,
  symbol TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  net_move_pct REAL NOT NULL DEFAULT 0,
  catalyst_move_pct REAL,
  regime TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
