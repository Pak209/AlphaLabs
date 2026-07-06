# AlphaLabs portfolio intelligence audit

Written 2026-07-04. Companion to `docs/ALPHA_GENERATION_AUDIT.md` (signal side)
and `docs/CALIBRATION_PLAN.md` (change protocol). No live behavior changes;
all existing safeguards preserved. The diagnostics snapshot shipped with this
audit (`scripts/portfolio_report.py`) is the measurable "before" picture every
proposal below must be judged against.

## 1. Current portfolio architecture

Portfolio decisions today are made **per trade, at entry, with flat rules**:

| Mechanism | Where | Behavior |
|---|---|---|
| Position sizing | `decision_engine.evaluate_signal` | `min(max_position_size_usd, equity × max_equity_pct_per_trade)` — flat $1,900 / 2% regardless of conviction, volatility, or crowding |
| Options sizing | same | exactly 1 ATM contract, must fit the per-trade budget |
| Position limit | same | `max_open_positions` (count 20), duplicate-ticker check |
| Turnover limit | same | `max_trades_per_day` (10), crypto profile separate (3/day, $250) |
| Loss brake | same | `max_daily_drawdown_pct` 3% (account-level, day-scale) |
| Stops/targets | config | flat 4% stop / 8% target; bracket orders off |
| Signal competition | poll loop | strictly first-come-first-served within and across cycles |
| Position state | `positions` table | Alpaca paper sync (qty, market value, unrealized P/L) |
| Conviction data | `trades.alpha_composite` | stored at entry, **never used for sizing** |
| Exits | — | none (audit finding; slots free only via manual close) |

What does NOT exist: aggregate notional/gross-exposure cap, theme or sector
concentration limit, correlation awareness, volatility-adjusted anything,
portfolio heat accounting, conviction-weighted allocation, within-cycle
ranking, Kelly or any outcome-informed sizing.

## 2. Gap analysis (by focus area)

1. **Position sizing** — flat caps are a fine *ceiling* but a poor *allocator*:
   a composite-95 idea and a composite-70 idea get identical capital. Fix
   direction: conviction scales **below** the existing cap (cap intact).
2. **Exposure management** — 20 slots × $1,900 permits ~$38k gross with no
   aggregate cap; count is the only brake. Need gross/net notional visibility
   first (now in the snapshot), a cap later.
3. **Sector concentration** — the approved book is heavily AI/mega-tech; the
   platform's own theme map (`TICKER_THEME`) shows the cluster but nothing
   limits it. Snapshot reports top-theme share + clustered exposure.
4. **Correlation** — nothing measures it. Realistic path: theme-overlap proxy
   now (shipped), pairwise return correlation from daily bars later; a
   correlation *limit* is a distant, approval-gated step.
5. **Volatility targeting** — flat 4% stops mean a fixed heat-per-dollar but
   wildly unequal real risk (SMCI ≠ MSFT daily range). First step is
   measurement (ATR per name), not new stops.
6. **Capital allocation** — static; no rebalancing concept. Acceptable at
   paper scale; revisit after conviction sizing.
7. **Kelly-style sizing** — requires win-rate/payoff estimates per band from
   the outcome layer; with < 30 outcomes any Kelly fraction is noise. Design:
   fractional Kelly (≤ ¼), computed from `outcome_report` bands, always capped
   by the existing per-trade limit. Diagnostics can compute and *display* the
   suggested fraction long before anything uses it.
8. **Portfolio heat** — now measured (Σ |mv| × stop%). No heat cap exists;
   one belongs in the roadmap as a *new safety control* (additive, not a
   loosening).
9. **Diversification** — dup-ticker check + slot count only. Effective-position
   count (1/HHI) is now reported; a theme-cap proposal follows evidence.
10. **Simultaneous signal competition** — FCFS means slot allocation is
    arrival-order, not quality. The 3-minute poll cadence makes this real:
    a mediocre 09:33 idea can consume the slot a strong 09:36 idea needed.
    Diagnostics first: record per-cycle composite ranks and measure "slot
    steals" before proposing batch selection.
11. **Conviction-weighted allocation** — all inputs exist (`alpha_composite`
    at entry). The snapshot's what-if reallocates the same pool by composite
    so the shift is visible today; the behavior change is small and fully
    replayable when approved.
12. **Risk-adjusted expected return** — needs expected move per band (outcome
    layer) ÷ per-name volatility (not yet measured). Sequenced after vol
    measurement and ≥ 30-outcome samples.

## 3. Roadmap

### Shipped with this audit (diagnostics-only)
- `alpha_lab/portfolio.py` + `scripts/portfolio_report.py`: gross exposure,
  HHI/effective positions, theme exposure + clustered share (correlation
  proxy), portfolio heat under configured stops, cap utilization, and the
  flat-vs-conviction sizing what-if on real stored composites.

### Next diagnostics (no approval needed)
- **P1. Per-cycle signal-competition recorder** — rank candidates per poll
  cycle, measure slot-steal frequency and the composite gap between taken
  and blocked ideas.
- **P2. Volatility measurement** — ATR/daily-range per approved ticker from
  existing bar sources; report risk-per-dollar dispersion under flat stops.
- **P3. Kelly preview** — fractional-Kelly suggested sizes per composite band
  from `outcome_report` data, displayed alongside actual flat sizes; becomes
  meaningful as outcomes pass 30.
- **P4. Return-correlation matrix** — pairwise daily-return correlation for
  the approved book (needs bar history cache; free sources suffice).

### Behavior changes (approval required, one at a time, replay/what-if evidence attached)
- **B1. Conviction-weighted sizing under the existing cap** — notional =
  cap × f(composite), f ≤ 1. Never exceeds today's per-trade cap; strictly a
  reallocation. Evidence: snapshot what-if + replay selection overlap.
- **B2. Portfolio heat cap** (new safety control, additive) — block new
  entries when Σ risk-to-stop exceeds X% of equity.
- **B3. Theme concentration cap** (additive safety) — block entries pushing
  top-theme share beyond Y% of gross.
- **B4. Batch selection per cycle** — rank a cycle's candidates by composite
  before consuming slots (replaces FCFS *within* a cycle only).
- **B5. Volatility-aware stops/sizing** — after P2 shows dispersion; changes
  order payloads, so it is late in the queue.
- **B6. Exit management** — carried from prior audits; biggest slot unblocker.

Sequencing rationale: B1 and B4 spend no new risk budget (same caps, same
capital) and directly use data already stored; B2/B3 *add* controls; B5/B6
touch order mechanics and need the most evidence.

## 4. Safety posture

Nothing in this roadmap loosens an existing control. B2 and B3 add controls.
B1/B4 reallocate within current caps. Every behavior change goes through the
calibration protocol (shadow → evidence pack → single approved change →
rollback criteria), and the portfolio snapshot provides the before/after
comparison for each.
