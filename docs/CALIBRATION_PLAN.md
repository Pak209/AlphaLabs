# AlphaLabs calibration plan

Status: **collection phase — no threshold changes authorized.**
Written 2026-07-04, after the pipeline audit (see `.ai/LEX_REVIEW_HANDOFF.md`
entries of 2026-07-04) and the rejection-waterfall telemetry landing. All
trading behavior is frozen; this document defines what evidence must exist
before any gate is tuned, which gates may never be tuned without explicit
human approval, and how to collect and read the evidence.

Telemetry sources referenced throughout:

- `GET /api/diagnostics/rejection-waterfall` (or `AlphaLabService.rejection_waterfall()`)
- `python3 scripts/waterfall_snapshot.py` — one timestamped JSON sample per session + delta vs previous
- `python3 scripts/diagnose_trading_pipeline.py` — full health + ASCII waterfall
- `execution_audit.payload_json._gates` — per-candidate structured gate traces (new rows only)

---

## 1. Calibration decision matrix

Historical counts are first-failed-gate figures from the 976 legacy attempts
(pre-telemetry). "Fresh data needed" = minimum structured sample before any
proposal touching that gate.

| Gate | Threshold today | Class | Hist. first-fail | Expected in new data | Tunable? | Fresh data needed |
|---|---|---|---|---|---|---|
| `crypto_long_only` | broker constraint | **Bug/noise reducer** (fixed at source: bearish crypto skipped pre-idea) | 308 | ~0 | Never — physical broker constraint | None; watch it stay ~0 |
| `market_open` | RTH only | **Noise reducer** (fixed: equity signals deferred while closed) | 230 | ~0 | Never — market reality | None; watch it stay ~0 |
| `duplicate_position` | 1 position per ticker | **True risk control** (no averaging in) | 123 | Lower once exits exist | Not a tuning target; fix exit management instead | n/a |
| `max_open_positions` | 20 (alpha_lab config) | **True risk control**; inflated by missing exit management | 107 | Lower once exits exist | **Never loosen without approval** | n/a |
| `alpha_composite_tier` | composite ≥ 70 + tier | **Quality gate** — inputs were broken (constant 40.6), now fixed | 79 (100% of paper attempts) | Real distribution appears; advisory failures on dry-runs now measurable | Threshold: evidence-based candidate **later**; the confirmation-rule structure itself: never without approval | ≥ 5 sessions, ≥ 30 accepted dry-run decisions carrying the advisory record |
| `confidence` | ≥ 0.75 at execution | **Quality gate** — formula recalibrated 2026-07-04 | 5 | More traffic (radar candidates now clear emission consistently) | Formula coefficients: candidate later; the 0.75 execution bar: **never without approval** | ≥ 5 sessions, ≥ 200 structured evaluations |
| `short_sizing_price` | live price > 0 | **Data-availability noise** (quote feed miss, not a decision) | 10 | Sporadic | Fix is a price-fallback change (behavior — needs approval), not a threshold | n/a |
| `human_approval` | approved or not required | **Safety control** | 3 | Unchanged | **Never** programmatically | n/a |
| `watchlist` | ~31 approved tickers | **Safety scope control** | 2 | Unchanged | Additions only by explicit human edit of the config | n/a |
| `max_trades_per_day` | 10 | **Hard safety** | 0 | 0 unless volume grows | **Never loosen without approval** | n/a |
| `daily_drawdown` | 3% | **Hard safety** | 0 | 0 | **Never loosen without approval** | n/a |
| Sizing caps | $1,900 / 2% equity | **Hard safety** | 0 | 0 | **Never loosen without approval** | n/a |
| Option spread cap | ≤ 15% | **Liquidity protection** | 1 | Sporadic | Candidate later, only with fill-quality data | ≥ 20 option attempts |
| Radar `trade_candidate` | direct catalyst + score ≥ 68 + actionability ≥ 3.5 + conf ≥ 0.75 | **Quality gate** — largest reducer in the pipeline (94,523 pre-idea "not trade candidate" skips) | n/a (pre-idea) | Shifts with the new unified confidence formula | Score floor / actionability: evidence-based candidates later | ≥ 5 sessions of scanner accounting under the new formula |
| PV confirmation inputs | gap deadband 0.25%, rel-vol ≥ 1.0 neutral, PV ≥ 55 | **CRITICAL-RULE inputs** | inside alpha gate | First real distributions (requires `POLYGON_API_KEY` on runner) | Inputs: candidates later; the rule (no confirmation → no trade) — **never without approval** | ≥ 5 sessions **with Polygon configured** |

### Never-loosen list (explicit human approval required, one change per decision)

`max_daily_drawdown_pct` · `max_trades_per_day` · `max_open_positions` ·
`max_position_size_usd` / `max_equity_pct_per_trade` · `approved_tickers`
scope · human-approval flow · paper-endpoint-only enforcement ·
`crypto_long_only` / `allow_short` guards · `min_confidence` 0.75 at
execution · alpha composite ≥ 70 paper gate · the CRITICAL RULE structure
(catalyst ≥ 40 AND price/volume ≥ 55 for confirmation; modifiers excluded and
watchlist ceiling applied when unconfirmed; catalyst/macro floors).

### Evidence-based candidates (later, with the protocol in §2)

1. Radar candidate floor (`catalyst_score ≥ 68`) and `actionability ≥ 3.5`
2. Confidence formula coefficients (`0.40 + score·0.0045 + source_quality·0.00075`)
3. PV gap deadband (0.25%) and sub-1.0 relative-volume neutrality
4. Catalyst-type weight table (95/90/85/…) — backtest vs `catalyst_futures_reactions` and forward returns
5. Composite component weights (0.35/0.20/0.15/0.15/0.10/0.05)
6. Option spread cap (15%) — with realized fill-quality data
7. Dedupe windows (crypto ticker+bias 6h; 250-idea thesis window)

---

## 2. Safe tuning protocol

1. **Freeze.** Scheduler stays `ALPHALAB_SCHEDULER_MODE=dry_run` with the
   automation guard disarmed. No threshold edits during collection.
2. **Collect ≥ 5 trading sessions** of structured traces (one
   `waterfall_snapshot.py` sample after each close). Minimum samples before
   analyzing a gate: ≥ 50 structured evaluations of that gate and ≥ 10
   failures; for outcome-linked analysis, ≥ 30 accepted dry-run decisions.
3. **Evidence pack per proposed change** (one gate at a time):
   - `observed_stats` quantiles for the gate (where does the threshold sit in
     the candidate population?),
   - near-miss count and share (failures within 10% of threshold),
   - **regret analysis**: forward outcome of the near-miss band vs the
     accepted band, using `signal_evaluations` (rejected ideas keep their
     evaluations, so this is already recorded),
   - simulated pass-rate at the proposed threshold, computed offline from the
     recorded observed values — never by editing the live threshold.
4. **Shadow first.** Before moving any live threshold, add the proposed
   threshold as an *advisory* gate record (`enforced: false`, same mechanism
   as the dry-run alpha gate) — a diagnostics-only change — and run ≥ 3
   sessions comparing advisory vs live outcomes.
5. **Approve and change.** One threshold per change, explicit human approval,
   handoff entry with the evidence pack, tests updated in the same change.
6. **Rollback criteria.** Revert immediately if: acceptance rate leaves the
   target band (§4), any never-loosen gate fires more often, any drawdown
   event occurs, or paper order volume exceeds `max_trades_per_day` pressure.
7. Re-arming paper mode (`ALPHALAB_SCHEDULER_MODE=paper` +
   `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true`) remains a separate,
   explicit human decision — never part of a calibration change.

---

## 3. Comparing legacy data vs structured traces

- Both populations map to the **same canonical gate names**; legacy rows are
  flagged (`legacy_failures`, window counts in `window.legacy_rows` /
  `window.structured_rows`). Never mix raw counts across the boundary —
  compare **rates per 100 attempts** within each population.
- The comparable statistic is the **first-failed-gate distribution**: legacy
  first clause = first failed gate (clauses were appended in gate order), so
  it aligns with structured `_first_failed_gate`.
- Legacy rows have **no observed values** — `observed_stats` and near-miss
  counts exist only for structured rows. Any distributional claim uses
  structured data only.
- **Expected structural breaks** from the 2026-07-04 fixes (do not misread as
  drift): `crypto_long_only` ~308 → ~0 (skipped pre-idea);
  `market_open` ~230 → ~0 (deferred); `duplicate_position` for crypto down
  (6h ticker+bias dedupe); `alpha_composite_tier` changes from a constant
  40.6 wall to a real distribution; radar signal volume shifts with the
  unified confidence formula.

## 4. "Too strict" vs "correctly selective" — decision metrics

1. **Threshold-step test (primary).** Bucket candidates by the gated value
   (confidence deciles, composite bands) and compare forward outcomes
   (`signal_evaluations` early-detection score / target-before-stop). A
   well-placed threshold shows a visible step in outcomes at the cutoff. If
   outcomes are flat across it, the threshold is arbitrary at that value; if
   the near-miss band performs like the accepted band, it is too strict.
2. **Regret rate.** Share of rejected near-misses whose forward move would
   have hit target before stop. Persistently high regret at one gate =
   calibration candidate; low regret = correctly selective.
3. **Volume adequacy band.** Target 5–15 accepted dry-run decisions per week.
   Below → too strict somewhere (waterfall says where); above → tighten or
   accept more manual review load.
4. **Advisory alpha-gate stop rate** on accepted dry-runs (now recorded):
   what fraction of otherwise-accepted trades would the paper gate stop, and
   at what composite scores?
5. **Precision proxy** on the trades that do execute: dry-run/paper
   target-before-stop rate by tier and by source (Performance page already
   groups by confidence bucket).

---

## 5. Collection commands (all read-only or dry-run)

```bash
cd ~/AlphaLab
set -a; source .env; set +a          # human step; agents do not touch .env

# 0) Confirm freeze posture (must show dry_run + guard disarmed)
curl -s http://127.0.0.1:8787/api/safety-status | python3 -m json.tool

# 1) Full health + ASCII waterfall (also verifies POLYGON_API_KEY presence —
#    required for price/volume confirmation to ever be measurable)
python3 scripts/diagnose_trading_pipeline.py

# 2) Once per session, after the close (~14:15 PT, after the 13:50 PT
#    signal-evaluation job): timestamped sample + delta vs previous session
python3 scripts/waterfall_snapshot.py

# 3) Ad-hoc inspection any time
curl -s "http://127.0.0.1:8787/api/diagnostics/rejection-waterfall?limit=5000" | python3 -m json.tool

# 4) Optional manual dry-run collection pass outside scheduler cadence
#    (creates ideas + decisions, places NO orders)
python3 - <<'PY'
from alpha_lab.service import AlphaLabService
lab = AlphaLabService()
result = lab.poll_live_catalysts(dry_run=True)
print(result.get("test_result", {}).get("note") or f"{len(result.get('signals', []))} signals tested")
PY
```

The scheduler's existing dry-run cadence (catalyst poll every 3 minutes
05:00–14:00 PT, five daily-brief slots, weekend crypto) is the collection
engine; no scheduler changes are needed or authorized.

---

## 6. Prioritized next changes

Diagnostics-only (may be implemented without a calibration decision):

1. **Shadow-threshold advisory records** (§2 step 4) — evaluate proposed
   thresholds as `enforced: false` gate records alongside the live ones.
2. **Regret-analysis report** — join rejected near-miss ideas to their
   `signal_evaluations` outcomes; add to the waterfall payload or a sibling
   endpoint.
3. **Per-source funnel splits** in the waterfall (catalyst_radar vs
   daily_market_brief vs crypto) so per-source strictness is visible.

Behavior changes — **not to be implemented without explicit approval**, listed
by expected impact:

4. **Equity exit management** (brackets or a scheduled stop/close job) —
   biggest unblocker; duplicate-position and max-open-positions pressure is
   mostly un-exited inventory, not signal quality.
5. **`POLYGON_API_KEY` on the runner** (config, human-applied) — without it,
   price/volume confirmation is unsatisfiable and the paper gate can never
   pass; also unlocks PV-input calibration data.
6. **`prior_count_30d` wiring** from `catalyst_events` so novelty
   discriminates recycled news.
7. **Macro inputs from the latest saved briefing** via the existing
   `macro_inputs_from_briefing` adapter (currently defaults at decision time).
8. **Options-flow / dark-pool live providers** to activate the conviction
   modifiers (currently permanent stubs).
