# Futures & Options Pulse — Build Handoff (2026-06-15)

> Living handoff for the **Overnight Futures Pulse** agent and the **live Options
> Flow provider**. Supersedes the pre-build proposal in
> [`futures-integration-plan.md`](./futures-integration-plan.md) (which is now
> historical context only).
>
> **No secret values appear here** — only env-var *names*. Both features are
> **read-only**: they generate signals/context and persist for backtesting. They
> never create an idea or place/approve a trade.

---

## 1. What this is

A premarket, read-only macro read built from **overnight futures aggregates**:
detect overnight movement across a 12-contract board, classify a market regime,
generate a watchlist, run a **read-only** strategy-scoring preview on the implied
equity/crypto tickers, persist everything to SQLite for next-day backtesting, and
surface a dashboard card. A parallel **live options-flow provider** derives
call/put volume signals from the same free Polygon/Massive tier.

Why it exists: AlphaLab is catalyst-first on equities/crypto and **cannot paper-
trade futures** (Alpaca paper has no CME path). So futures/options are **context
and confirmation inputs**, not tradeable objects — consistent with the catalyst-
first hard gate.

---

## 2. Data vendor & entitlement (free tier, probed empirically)

Same `POLYGON_API_KEY` (Polygon, now branded **Massive**) on the **free** tier.
Both the Futures and Options APIs share the same ceiling:

| API | ✅ Entitled (free) | ❌ Not entitled (403 `NOT_AUTHORIZED`) |
| --- | --- | --- |
| **Futures Basic** | `/futures/v1/aggs/{ticker}` EOD/delayed aggregates, full overnight coverage; reference/products | snapshot, quotes, trades |
| **Options Basic** | `/v3/reference/options/contracts`; `/v2/aggs/ticker/{contract}/range/.../day` EOD aggregates (volume) | `/v3/snapshot/options/{underlying}` (the only source of **open interest** + per-side premium) |

Other constraints (both): **5 requests/minute**, 2 years history, EOD/delayed
(no real-time). Grouped daily aggregates are **not** offered for the options
market. `/futures/v1/contracts` returns placeholder junk (e.g. `ESH0`) on free —
so front-month tickers are **constructed deterministically**, never fetched.

Consequence baked into both providers: **graceful degradation** — missing key,
403/429, bad ticker, network error, or empty result all return `None`
("no data" → neutral), never an exception that breaks the premarket read.

---

## 3. Files & roles

| File | Role |
| --- | --- |
| `alpha_lab/futures_pulse.py` | Core agent: `TRACKED_CONTRACTS` board, `FuturesContractSpec`, front-month/roll logic, `PolygonFuturesProvider` (throttled, read-only aggregates), regime classifier, `build_pulse_report`, `report_to_strategy_signals` |
| `alpha_lab/options_flow.py` | Conviction-modifier scorer (`score_options_flow`, pure) **+ new** `PolygonOptionsFlowProvider` (live near-the-money EOD volume) |
| `alpha_lab/service.py` | `futures_pulse(...)` (orchestrates build + read-only scoring preview + persist); `run_overnight_futures_pull(...)` (throttled nightly fill); `run_options_flow_preview(...)` (read-only options context + scanner accounting) |
| `alpha_lab/scheduler.py` | Nightly futures pull job @ 6:05am PT (mon-fri); options-flow preview @ 6:12am PT (mon-fri); `.env` loaded inside `start()` only |
| `alpha_lab/api.py` | `GET /api/futures/pulse`, `GET /api/futures/snapshots`, `GET /api/options/flow-preview` (read-only) |
| `alpha_lab/repository.py` / `database.py` | SQLite tables `futures_snapshots`, `futures_moves`, `catalyst_futures_reactions` |
| `alpha_lab/static/` | Dashboard "Overnight Futures" card (`index.html`, `app.js`, `styles.css`) |
| `alpha_lab/env.py` | Dependency-free `.env` loader (loaded at entry points only) |
| `.env.example` | `POLYGON_FUTURES_*` + `POLYGON_OPTIONS_*` config (names below) |
| Tests | `tests/test_futures_pulse.py`, `tests/test_scheduler.py`, `tests/test_env.py`, `tests/test_signal_sources.py` |

**The board (12 contracts):** ES, NQ, RTY (equity_index) · CL, NG (energy) ·
GC, SI (metals) · ZN, ZB, ZT (rates) · BTC (crypto) · VX (vol). Each spec carries
`reaction_tickers` (the equity/crypto ETFs/megacaps the move implies).

---

## 4. This session's changes

### 4a. Per-product roll buffers (futures front-month)
**Problem:** a contract's *delivery*-month code is not its last-trade date. Energy
(CL/NG) expire ~a month **before** the delivery month, so the calendar-month code
is already dead by the time that month arrives — `CLM5` was already expired and
returned no data on a June session.

**Fix** (`futures_pulse.py`): expiry-estimate model replacing the naive
month-after-ref selection.
- `_EXPIRY_RULE_BY_SYMBOL = {"CL": (-1, 20), "NG": (-1, 25)}` — `(month_offset, day)`
  for estimated last-trade date, deliberately a touch **early** so we never hold an
  expired contract.
- `_EXPIRY_RULE_BY_CATEGORY` defaults: equity_index `(0,18)`, rates `(0,21)`,
  metals `(0,27)`, energy `(-1,22)`, crypto `(0,24)`, vol `(0,17)`.
- `_contract_expiry(spec, delivery_month, year)` wraps months/years for the offset.
- `front_month_ticker(...)` now walks listed delivery months across this year and
  next, returning the first whose estimated expiry is still ≥ the reference date.
- Listing cycles unchanged: GC `[2,4,6,8,10,12]`, SI `[3,5,7,9,12]`,
  equity/rates quarterly `[3,6,9,12]`, energy/metals/crypto/vol monthly.

**Verified live** (throttled, session 2025-06-12): `CL` flipped no-data → **DATA**
(`CLM5`→`CLN5`, the live July front month), lifting board coverage **6/12 → 7/12**.
ES/NQ resolve to the same tickers as before, so their remaining gaps are feed
coverage/symbology — **not** roll-related. Remaining no-data on that session:
ES, NQ, NG, BTC, VX (feed/symbology, separate from roll buffers).

### 4b. Live Options Flow provider
New `PolygonOptionsFlowProvider` in `options_flow.py`, implementing the existing
`OptionsFlowProvider` protocol (`fetch(ticker) -> Optional[OptionsFlowInputs]`),
drop-in alongside `StubOptionsFlowProvider`. The pure scorer
(`score_options_flow`) is **unchanged**.

How it works (free-tier honest):
1. `_spot(ticker)` — underlying close **on the session date** (range agg, *not*
   `/prev`), so historical pulls center strikes on the price *then*.
2. `_near_money_contracts(...)` — nearest expiration ≥ session, strikes within
   `strike_band_pct` (±5%) of spot, closest-to-spot capped at
   `max_contracts_per_side` (8).
3. `_session_and_baseline_volume(contract)` — **one** `/range/1/day/{from}/{to}`
   call yields both the session-day volume **and** the trailing baseline (mean of
   prior-day volume), so the call-volume multiple costs **no extra requests**.
4. Aggregate call/put volume; set `avg_call_volume` = summed call baseline.
   `open_interest` / premium fields stay **0** (snapshot not entitled) → the
   scorer's OI and put-buying buckets correctly contribute 0 points.

Throttled (`POLYGON_OPTIONS_MIN_INTERVAL_SEC`, default 0; set ~13 for live) under
the 5/min cap — built for the **offline overnight pull on a small watchlist**, not
interactive per-request use.

**Bug found & fixed during live testing:** `_spot` originally used `/prev` (today's
price) — for a historical session that selected zero-volume deep-OTM strikes and
returned `None`. Now uses the session-date close.

**Verified live** (throttled, SPY 2025-06-11): ~1.0M call / ~1.2M put EOD volume,
~37.7k baseline → 26.6× call-volume multiple → bullish (+6). OI/premium correctly 0.

> Known refinement (not a blocker): near-expiry contracts have a short trailing
> history, so the call-volume **multiple can be inflated** when the baseline window
> only spans a few recently-listed days. The scorer caps the bucket at +6 anyway.

---

## 5. Env config (names only)

```
# Futures (shared POLYGON_API_KEY)
POLYGON_FUTURES_BASE_URL=https://api.polygon.io
POLYGON_FUTURES_AGGS_PATH=/futures/v1/aggs/{ticker}
POLYGON_FUTURES_MIN_INTERVAL_SEC=0      # set ~13 live: full 12-board ~2.5 min/run, under 5/min

# Options (same POLYGON_API_KEY, free "Options Basic")
POLYGON_OPTIONS_BASE_URL=https://api.polygon.io
POLYGON_OPTIONS_MIN_INTERVAL_SEC=0      # set ~13 live; offline overnight use
```

`.env` is loaded **only at entry points** — `main.py` (module top) and
`scheduler.py` *inside* `start()`. **Never** at package/module import: doing so
leaks live keys into pytest collection, which flips stub providers to live and
makes the hermetic suite hit the network (this regression was hit twice and fixed).

---

## 6. Scheduling & persistence

- **Nightly futures pull:** `scheduler.py` registers
  `service.run_overnight_futures_pull()` at **6:05am PT (9:05am ET), mon-fri** —
  after most of the overnight session (6pm→9:30am ET) has landed and before the
  6:30am PT cash open. Uses a throttled `PolygonFuturesProvider` (default 13s) and
  persists into the three SQLite tables. No-op when `POLYGON_API_KEY` is unset.
  Total scheduler job count is now **18** including the DB heartbeat job
  (asserted in `test_scheduler.py`).
- **Persistence verified** end-to-end (session 2025-06-12): `futures_snapshots`=1,
  `futures_moves`=6, `catalyst_futures_reactions`=0, regime=`risk_off`.
- **Options-flow preview:** `scheduler.py` registers
  `service.run_options_flow_preview()` at **6:12am PT, mon-fri**. It uses a tiny
  `POLYGON_OPTIONS_WATCHLIST` (default `SPY,QQQ,NVDA`), throttles through
  `POLYGON_OPTIONS_MIN_INTERVAL_SEC`, writes one `scanner_runs` accounting row,
  and never creates ideas/trades/orders.

---

## 7. Tests & how to run

```
cd ~/AlphaLab && .venv/bin/python -m pytest alpha_lab/tests -q
```
Full suite: **157 passed**, ~3s, hermetic (no network, no key leak).

Key coverage:
- `test_futures_pulse.py` — roll buffers: `test_front_month_equity_index_quarterly`,
  `test_front_month_rolls_to_next_year` (ES 2026-12-20 → `ESH7` after Dec expiry),
  `test_front_month_energy_roll_buffer` (CL 2026-04-10 → `CLK6`; CL 2025-06-12 →
  `CLN5`; NG 2025-06-12 → `NGN5`).
- `test_signal_sources.py` — live options provider with **HTTP mocked** (no
  network): protocol conformance, chain volume aggregation + baseline math,
  no-key → None, empty-chain → None.
- `test_scheduler.py` — 18-job count, heartbeat, overnight pull, and options preview are scheduled jobs.
- `test_env.py` — `.env` parse/load (real env wins, override, missing-file no-op).

**Live smoke (throttled; ~2.5 min each, needs real key):**
```
# Futures coverage on a historical session
.venv/bin/python -c "from alpha_lab.env import load_dotenv; load_dotenv(); \
from datetime import datetime; from alpha_lab.futures_pulse import TRACKED_CONTRACTS, front_month_ticker, PolygonFuturesProvider; \
p=PolygonFuturesProvider(min_interval_sec=13); [print(s.symbol, front_month_ticker(s, ref_date=datetime(2025,6,12)), p.fetch_overnight(s, session_date='2025-06-12') is not None) for s in TRACKED_CONTRACTS]"

# Options provider on a historical session
.venv/bin/python -c "from alpha_lab.env import load_dotenv; load_dotenv(); \
from alpha_lab.options_flow import PolygonOptionsFlowProvider, score_options_flow; \
p=PolygonOptionsFlowProvider(min_interval_sec=13, session_date='2025-06-11', max_contracts_per_side=4); \
i=p.fetch('SPY'); print(i and i.model_dump()); print(score_options_flow(i,'SPY').summary)"
```

---

## 8. Open TODOs / decisions

- **Options preview is now wired read-only.** Remaining decision: whether to
  persist per-ticker options-flow samples beyond `scanner_runs` summaries for
  longer-horizon source reliability analysis.
- **Board coverage gaps** on the free feed: ES/NQ/NG/BTC/VX returned no data on the
  2025-06-12 probe. ES/NQ are unchanged tickers (not roll-related) — likely
  symbology (e-mini vs micro root) or intraday availability for older sessions.
  Worth a per-symbol probe to confirm the correct futures root for each.
- **Options multiple inflation** from short near-expiry baselines (§4b) — consider
  a longer/blended baseline or a minimum-history guard if the signal is used to
  drive anything beyond context.
- Real-time/OI would require a **paid** Polygon tier (snapshot endpoint); current
  build is intentionally free-tier, EOD, read-only.

---

## 9. Guardrails (do not regress)

1. **Read-only forever.** Neither feature creates an idea or places/approves a
   trade. Keep it that way.
2. **`.env` loads at entry points only** — never at import time (breaks the
   hermetic test suite by leaking keys).
3. **Graceful degradation** is the contract: any failure → `None` → neutral, never
   a raised exception in the premarket path.
4. **Don't fetch `/futures/v1/contracts`** for front months — it's placeholder data
   on free; construct tickers deterministically.
5. **Throttle live pulls** (`*_MIN_INTERVAL_SEC` ~13) to stay under 5/min.
