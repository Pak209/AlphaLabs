# Futures Integration Plan

> **Superseded — this is now historical context.** The Overnight Futures Pulse and
> a live Options Flow provider were since built on Polygon's **free** tier. For the
> current state see [`FUTURES_OPTIONS_PULSE_HANDOFF.md`](./FUTURES_OPTIONS_PULSE_HANDOFF.md).
>
> Status (original): **proposal / decision doc** — nothing built yet. Written
> 2026-06-14 in response to "can we track futures so we can ride moves like the
> weekend US–Iran event, and can Polygon do it?"

## TL;DR

- **Yes, Polygon can do futures** — but **not on your current plan**. Polygon
  (now branded **Massive**) sells a **separate Futures API product**, distinct
  from the Stocks plan AlphaLab uses today for news + the new intraday
  price/volume snapshot. It covers CME / CBOT / NYMEX / COMEX (so **ES** = S&P
  500 and **NQ** = Nasdaq‑100 e‑minis), with REST snapshot / aggregates /
  trades + WebSocket + flat files, and ~10 years of history.
- So this is **a vendor add‑on + a real feature build**, not a config toggle.
- The honest payoff question: futures would give AlphaLab a **pre‑market /
  overnight / weekend macro read** it has no way to see today. But AlphaLab is a
  *catalyst‑first equity/crypto* system, and **Alpaca paper can't trade futures**
  — so futures would be a **signal/context input**, not something you'd place
  paper orders on. That distinction drives the whole scope below.

## Why futures don't "just fit" the current pipeline

AlphaLab today thinks in: catalyst → price/volume confirm → modifiers → risk →
**paper trade on an equity/crypto ticker via Alpaca**. Futures break three of
those assumptions:

1. **No paper execution path.** Alpaca's paper broker does equities/options (and
   you trade crypto ideas through it too). It does **not** do CME futures. So an
   ES/NQ "idea" can't become a paper trade the way an AAPL idea does. Futures
   are therefore a **context/confirmation signal**, feeding the *equity* ideas
   they imply (e.g. "ES gapping +2% overnight on the Iran deal" → boosts
   confidence on SPY/QQQ/megacap longs the next session).
2. **Different symbology + roll handling.** Futures use contract codes
   (`ESU6`, `NQU6`…) that **expire and roll quarterly**. You need either a
   continuous‑contract abstraction or front‑month resolution logic — there's no
   equivalent in the current equity/crypto code.
3. **They move when equities are dark.** That's the *point* (overnight, Sunday
   globex), but it means the consumer has to be the weekend/pre‑market jobs, not
   the mon‑fri equity loop.

## What I'd build (phased — stop after any phase)

### Phase 1 — Futures as a *macro context* signal (recommended first step)
- New `alpha_lab/futures_source.py`: `fetch_futures_snapshot(["ES","NQ"])` hitting
  the Massive Futures snapshot endpoint, front‑month auto‑resolved. Mirrors the
  pattern of the `fetch_polygon_intraday` helper just added — stdlib `urllib`,
  env‑gated on a new `POLYGON_FUTURES_API_KEY` (separate product = separate key),
  graceful disabled/error fallback.
- Surface it in the **daily brief** + a small **dashboard panel** ("Overnight
  Futures": ES/NQ %, session high/low). Read‑only. No scoring change.
- Wire it into the **weekend crypto job + the 5:45/9:25 pre‑market briefings** so
  a weekend/overnight macro move is *visible* and timestamped — which is exactly
  what was missing this past weekend.
- **This alone fixes the "we couldn't even see it" gap** with the least risk.

### Phase 2 — Futures as a confirmation modifier on equity ideas
- Add an optional `futures_context` to the composite: when an equity idea's bias
  aligns with a strong overnight futures move in the matching index, treat it as
  *supporting* price/volume confirmation (a modifier, like options/dark‑pool —
  **never** a standalone trigger, consistent with the catalyst‑first rule).
- Requires a mapping (megacap/ETF → ES/NQ) and a weight decision (re‑tune
  alongside the existing 15%/10% modifier weights). New tests for the gate.

### Phase 3 (optional, later) — direct futures research objects
- First‑class `asset_type="future"` ideas with roll handling, **research/alerts
  only**, clearly marked "no paper execution" until/unless a futures‑capable
  paper broker is added. Largest effort; defer unless you want it.

## Cost / vendor decision (needs your input)

- Massive (Polygon) Futures is a **paid add‑on** beyond your current Stocks plan.
  Exact tier/price isn't reliably scrapeable — **you'd need to check the live
  pricing page / your account** for the current Futures plan cost.
- Alternatives if the add‑on is pricey: **Databento** (futures, usage‑based),
  **CME via a broker feed**, or **Tradovate/IBKR** APIs. Polygon is the
  lowest‑integration‑effort choice since we already speak its REST dialect.

## Open decisions for you

1. **Scope:** start at **Phase 1 (context‑only)**? That's the cheap, safe win
   that addresses the weekend‑blindness directly.
2. **Vendor:** confirm Polygon/Massive Futures add‑on, or evaluate Databento?
3. **Budget:** is a second monthly data subscription acceptable for this?

## Sources
- [Polygon/Massive Futures REST API overview](https://massive.com/docs/rest/futures)
- [Polygon Futures product page](https://polygon.io/futures)
- [11 APIs For Futures Data (Nordic APIs)](https://nordicapis.com/11-apis-for-futures-data/)
