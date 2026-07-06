# AlphaLabs backtesting architecture (design)

Written 2026-07-04. Design only — no live behavior changes. Completes the
diagnostics stack: telemetry (waterfall) → replay → attribution → outcomes →
portfolio snapshot → **backtesting**, the layer that tests strategies,
signals, portfolio logic, exits, sizing, and risk controls over historical
periods before anything touches paper trading.

## 0. Design principles

1. **Reuse the live code path, never reimplement it.** The decision engine is
   already a pure function over an abstract `BrokerState`; the scoring engine
   already takes scenario overrides with live-identical defaults (replay
   framework). The backtester drives *those exact functions* with a simulated
   broker and historical events. A backtest that passes through
   `evaluate_signal` emits the same structured gate traces as production — so
   the waterfall, outcome, and attribution reports run unchanged on backtest
   output. One vocabulary everywhere.
2. **Point-in-time or it didn't happen.** Every input a strategy sees must
   carry an as-of timestamp, and lookahead is a build error, not a code-review
   hope (enforced by the timeline API — see §3).
3. **Fingerprints and experiment tracking.** Every run records its dataset
   fingerprint, config hash, and scenario — the replay framework's
   comparability discipline, extended to full simulations.
4. **Safety isolation.** The backtester writes only to its own store, never
   imports the Alpaca client, and nothing it produces changes live behavior.
   Promotion of any finding goes through the calibration protocol
   (shadow → evidence pack → human approval).

## 1. Architecture (layers)

```
┌────────────────────────────────────────────────────────────────────┐
│ L6 Reports: equity/drawdown, funnel (waterfall vocab), outcome     │
│    tables, walk-forward aggregation, experiment comparison         │
├────────────────────────────────────────────────────────────────────┤
│ L5 Experiment tracker: backtest_runs (config hash, fingerprint,    │
│    window, metrics), artifacts in alpha_lab/data/backtests/        │
├────────────────────────────────────────────────────────────────────┤
│ L4 Walk-forward runner: rolling train/test splits, frozen configs, │
│    multiple-testing ledger                                         │
├────────────────────────────────────────────────────────────────────┤
│ L3 Portfolio simulator: BacktestBroker (BrokerState), fill model,  │
│    exit-policy engine, equity marking                              │
├────────────────────────────────────────────────────────────────────┤
│ L2 Decision & risk: paper_trader.evaluate_signal — UNCHANGED,      │
│    same RiskConfig, same gates, same gate traces                   │
├────────────────────────────────────────────────────────────────────┤
│ L1 Strategy interface: on_event(event, ctx) -> [SignalIntent];     │
│    ctx = as-of data + scoring engine with scenario overrides       │
├────────────────────────────────────────────────────────────────────┤
│ L0 Historical data: bar cache, catalyst events (already stored),   │
│    briefings/futures snapshots (already stored), config snapshots  │
└────────────────────────────────────────────────────────────────────┘
```

## 2. Data model

New tables live in a **separate SQLite file** (`alpha_lab/data/backtest.sqlite3`);
the production DB is opened read-only as an event source. Production tables
are never written by the backtester.

```sql
-- L0: market data cache (ingested by a throttled read-only job)
CREATE TABLE bars_daily (
  ticker TEXT NOT NULL, session_date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT NOT NULL,               -- polygon | yahoo | alpaca_iex
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (ticker, session_date)
);

-- L0: point-in-time config snapshots (the anti-drift fix for TICKER_THEME,
-- THEME_PHASE, keyword tables, risk config — today these are "current only")
CREATE TABLE config_snapshots (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                 -- ticker_theme | theme_phase | risk_config | keywords
  valid_from TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  content_hash TEXT NOT NULL
);

-- L5: experiment tracking
CREATE TABLE backtest_runs (
  id INTEGER PRIMARY KEY,
  run_uuid TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  strategy TEXT NOT NULL,
  scenario_json TEXT NOT NULL,        -- ReplayScenario-compatible overrides
  risk_config_json TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL,
  dataset_fingerprint TEXT NOT NULL,  -- events + bars hashes
  code_version TEXT NOT NULL,         -- git rev at run time
  purpose TEXT NOT NULL,              -- exploration | train | oos_test | evidence_pack
  metrics_json TEXT NOT NULL,
  artifact_path TEXT
);

CREATE TABLE backtest_trades (        -- simulated fills, same shape vocabulary
  run_uuid TEXT NOT NULL,             -- as live trades for report reuse
  ticker TEXT, side TEXT, entry_ts TEXT, exit_ts TEXT,
  entry_price REAL, exit_price REAL, notional REAL, realized_pl REAL,
  exit_reason TEXT,                   -- stop | target | time_stop | eod | signal
  alpha_json TEXT, gates_json TEXT    -- full gate trace, waterfall-compatible
);
```

Existing production tables already provide the event history:
`catalyst_events` (with `discovered_at`!), `market_briefings`,
`futures_session_snapshots`, `signal_evaluations` (labels for train windows).

## 3. Event timeline

A backtest is a single merge-sorted stream of typed, timestamped events:

```
ClockEvent(session open/close)          from the calendar
BarEvent(ticker, ohlcv, ts)             from bars_daily (bar CLOSE time)
CatalystEvent(row, ts=discovered_at)    from catalyst_events
BriefingEvent(payload, ts)              from market_briefings
FuturesPulseEvent(snapshot, ts)         from futures_session_snapshots
```

**Lookahead discipline (the core rule):**
- Catalysts are emitted at `discovered_at`, not `published_at` — the platform
  cannot act before it *saw* the item, and the gap between the two is the
  measured detection latency, honestly simulated.
- Bars are emitted at close; a signal raised on bar *t* fills no earlier than
  bar *t+1*'s open (fill model, §4).
- The context object exposes only data at or before the current event's
  timestamp. There is no "give me the bars table" escape hatch: every
  accessor takes the implicit as-of from the timeline cursor. Lookahead is
  thereby an API impossibility rather than a convention.
- Config lookups (themes, phases, keyword tables, risk config) resolve
  through `config_snapshots` as-of the cursor; until snapshots accumulate,
  runs are labeled `config_as_of=latest` so early results are marked as
  drift-prone.

## 4. Strategy interface and portfolio simulation

```python
class BacktestStrategy(Protocol):
    name: str
    def on_event(self, event: Event, ctx: BacktestContext) -> list[SignalIntent]: ...

class BacktestContext:
    def bars(self, ticker, lookback_days) -> list[Bar]         # as-of cursor
    def catalysts(self, ticker=None, lookback_days=30) -> list # as-of cursor
    def latest_briefing(self) -> Briefing | None
    def score(self, idea_like: dict) -> AlphaScore             # scoring engine
                                                               # + scenario overrides
@dataclass
class SignalIntent:      # exactly the live signal payload shape
    ticker: str; bias: str; confidence: float; timeframe: str
    reason: str; source: str; asset_type: str = "equity"

class ExitPolicy(Protocol):
    def check(self, position, bar, ctx) -> ExitDecision | None
    # stock policies: StopTarget(flat % — today's live behavior),
    # TimeStop(n sessions), TrailingStop(pct), BracketSim
```

Existing generators become strategies via thin adapters: the catalyst radar's
`score_catalyst` over historical `catalyst_events`, the trending-stock setup
classifier over cached bars, futures-pulse over stored snapshots. The adapters
contain no new logic — they re-route inputs from live fetchers to `ctx`.

**Portfolio simulation loop:**

```
for event in timeline:
    intents = strategy.on_event(event, ctx)
    for intent in intents:
        decision = evaluate_signal(intent.as_signal(), risk_config,
                                   backtest_broker, audit_log)   # LIVE code
        if decision.accepted:
            backtest_broker.fill(decision, fill_model)           # next-bar open
    if isinstance(event, BarEvent):
        exit_engine.apply(positions, event, exit_policies)       # stops/targets/time
        backtest_broker.mark_to_market(event)                    # equity curve
```

- `BacktestBroker` implements `BrokerState` (account, positions, clock,
  last price) — the live gates (max positions, dup, drawdown, trades/day)
  work unmodified and emit their normal gate traces.
- **Fill model v1:** next-bar open ± slippage bps (config), stops/targets
  evaluated intrabar against high/low with worst-case tie-breaking (if a bar
  spans both stop and target, the stop fills — conservative by construction).
  Options v1: entry at recorded mid + half-spread, no early exercise; flagged
  as approximate until real chains are cached.
- Portfolio logic under test (sizing variants B1/Kelly, heat caps B2, theme
  caps B3, batch selection B4 from the portfolio audit) plugs in as
  simulator-level policies — testable here long before any approval request.

## 5. Walk-forward validation workflow

```
[W1 train][W1 test][gap]
      [W2 train][W2 test][gap]
            [W3 train][W3 test][gap]     default: 13w train / 4w test / 1w gap
```

1. **Train window:** attribution + replay scenario search over train data
   only → candidate config (weights, thresholds, exit/sizing policies).
2. **Freeze:** config hashed and recorded (`purpose=train`).
3. **Test window:** frozen config runs once on unseen data
   (`purpose=oos_test`). No peeking, no re-runs; re-running a test window
   with a tweaked config demotes the run to `exploration` automatically
   (enforced by the tracker: same window + same strategy + different config
   hash after an oos_test exists ⇒ flagged).
4. **Multiple-testing ledger:** the tracker counts exploration runs per
   window; every OOS report displays "N configurations were tried against
   this train window" so a lucky survivor cannot masquerade as skill. Rule of
   thumb recorded with each report: OOS edge should survive N-aware shrinkage
   (report both raw and 1/√N-shrunk edge).
5. **Aggregation:** OOS segments concatenate into the walk-forward equity
   curve — the only curve quoted in evidence packs.
6. **Promotion:** OOS evidence pack → calibration protocol (shadow on live
   dry-runs → single approved change). Backtests never promote themselves.

## 6. Metrics and reports

Per run (all on OOS segments for walk-forward):
- **Trade-level:** n, hit rate, avg win/loss, payoff ratio, expectancy — the
  outcome-report vocabulary, computed by the same `_outcome_stats` helpers.
- **Portfolio-level:** equity curve, max drawdown & duration, exposure and
  heat over time (portfolio-snapshot vocabulary), turnover, slot utilization,
  theme concentration over time.
- **Funnel:** gate-trace waterfall over simulated attempts — which safety
  gates bound the strategy in-sample (reuses the live waterfall aggregation).
- **Comparison:** run-vs-run diff keyed by config hash, same-fingerprint
  discipline as replay's `compare_to_baseline`.
- Deliberately absent v1: Sharpe on daily marks (noise at this trade count);
  added when OOS trade counts clear the calibration plan's sample floors.

## 7. Implementation roadmap (all diagnostics-only until promotion)

| Phase | Scope | Depends on |
|---|---|---|
| **M0** | Bar cache: `bars_daily` ingestion for the approved book (throttled, free sources); `config_snapshots` writer stamping current tables daily | nothing — buildable now |
| **M1** | Event timeline + `BacktestBroker` + fill model v1; end-to-end catalyst-strategy backtest over stored `catalyst_events`; gate traces + waterfall on backtest output | M0 |
| **M2** | Exit-policy engine (StopTarget, TimeStop, Trailing) + portfolio metrics (equity, drawdown, heat) | M1 |
| **M3** | Experiment tracker (`backtest_runs`, ledger rules) + run comparison report | M1 |
| **M4** | Walk-forward runner + OOS aggregation + multiple-testing reporting | M2, M3 |
| **M5** | Strategy adapters for trending-stocks and futures-pulse; portfolio-policy plugins (conviction sizing, heat cap, theme cap, batch selection) as simulator options | M2 |

Rough sizing: M0 and M1 are each a session; M2–M4 a session each; M5
incremental per adapter. Every phase lands with tests and its own handoff
entry; nothing in any phase modifies live scoring, gates, approvals, or paper
mode.

## 8. Risks and mitigations

- **Silent lookahead** — mitigated structurally (as-of-only context API,
  `discovered_at` anchoring, next-bar fills) and by a lookahead test suite
  (a strategy that tries to read future bars must fail).
- **Config drift vs history** — `config_snapshots` from M0 onward; runs
  before snapshot coverage are labeled drift-prone in every report.
- **Overfitting via replay+backtest iteration** — the multiple-testing ledger
  plus OOS-only quoting; the calibration protocol remains the only promotion
  path.
- **Fill-model optimism** — conservative tie-breaking (stop before target),
  slippage configurable, options flagged approximate; fills validated against
  actual paper executions as those accumulate (paper-vs-sim drift report).
- **Small history** — the platform is weeks old; early backtests inform
  *mechanics* (exits, sizing, competition), not catalyst-type edge, until the
  event archive grows. Reports must carry the same n-floor warnings as the
  other diagnostic layers.
```
