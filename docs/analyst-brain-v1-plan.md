# Analyst Brain v1 — Minimum Viable Implementation Plan

This is the implementation plan for the **first shippable version** of the Analyst Brain.
The complete design lives in [analyst-brain-framework.md](analyst-brain-framework.md). This plan
deliberately narrows scope to what delivers decision-useful output fastest, while leaving clean
seams for the deferred components.

**Status: planning only. Do not implement application code yet.**

---

## Scope Decision

### In scope for v1

| Component | Weight in v1 | Why it's in v1 |
|-----------|-------------|----------------|
| Catalyst Quality Score | 35% | The core reason a trade exists. Without it there is no idea to score. |
| Narrative Strength Score | 20% | Cheap to approximate from theme tags + ETF flow; high signal. |
| Macro Alignment Score | 20% | One shared daily reading applies to every idea — compute once, reuse everywhere. |
| Technical Confirmation Score | 15% | Confirms/contradicts the catalyst; derivable from existing market data feeds. |
| Composite Alpha Score | n/a | The orchestrator that combines the above into one 0–100 number + tier. |

### Bonus / overlay in v1 (not the full system)

| Component | v1 treatment |
|-----------|--------------|
| Bottleneck Intelligence | Implemented as a lightweight **overlay**, not the full 8-layer stack engine. v1 ships a static `bottleneck_layer` tag per ticker plus a manual `is_current_bottleneck` flag, producing a small **+0 to +8 bonus** on the composite. No live lead-time/margin/transcript mining yet. |

### Deferred to v2+

- **Liquidity & Flow Score** — full 7-dimension version (options flow, ETF rebalancing, retail attention feeds). v1 uses a simple binary tradeability gate (see below) instead of a full 0–100 score.
- **Full Bottleneck stack engine** — per-layer scoring, CapEx forward curve, transcript complaint mining, patent/talent/lead-time detection signals.
- **Full Part 8 JSON** — v1 emits a reduced subset (see Output below).

---

## v1 Composite Formula

Because Liquidity is deferred, weights are renormalized across the four scored components:

```
Base Alpha (v1) =
  (Catalyst Quality  × 0.35) +
  (Narrative Strength × 0.20) +
  (Macro Alignment    × 0.20) +
  (Technical Confirm  × 0.15)
  -> renormalize the four weights to sum to 1.0 (currently 0.90, so divide by 0.90)

Alpha Score (v1) = Base Alpha + Bottleneck Overlay Bonus (0 to +8, capped at 100)
```

**Liquidity gate (replaces full liquidity score in v1):** before scoring, reject any ticker failing a
hard minimum — e.g. ADV < 100K shares OR no options OR halted. Failing the gate = `tier: ignore`,
regardless of other scores. This preserves the *intent* of Part 2 without building the full engine.

**Thresholds unchanged from framework:** 90–100 Exceptional, 80–89 High Conviction, 70–79 Tradeable,
60–69 Watchlist, <60 Ignore. Override conditions (Hard No list, macro/catalyst floor caps) still apply.

---

## Build Order (milestones)

1. **M1 — Macro daily snapshot.** One scheduled job computes the shared Macro Alignment Score (Fed/CPI/PPI/labor/DXY/liquidity) once per day. Output cached and stamped with `macro_data_timestamp`. Every idea reads this; no per-idea recompute.
2. **M2 — Catalyst Quality scorer.** LLM-assisted scoring of the 8 dimensions against the catalyst payload from existing scanners. Returns per-dimension score + rationale.
3. **M3 — Narrative scorer.** Theme tagging (AI, datacenters, energy, semis, robotics, defense, crypto, emerging) + phase estimate + ETF-flow-based capital-flow direction.
4. **M4 — Technical confirmation.** From existing market data feeds: trend structure, volume confirmation, key levels, relative strength. Outputs `confirms_thesis` boolean + score.
5. **M5 — Liquidity gate + Bottleneck overlay.** Implement the binary tradeability gate and the static bottleneck tag/bonus.
6. **M6 — Composite + output.** Combine, apply floors/overrides, assign tier, emit the reduced JSON, hand off to the existing approval workflow.

---

## v1 Output (reduced JSON subset)

v1 emits these fields from the full Part 8 schema (rest deferred):

```
ticker, catalyst (headline/type/source), thesis (core_argument/variant_perception/thesis_invalidation),
alpha_score, catalyst_score, narrative_score, macro_score, technical_score, bottleneck_score (overlay),
confidence, risks[], invalidation (primary), entry, stop, target (target_1 + target_2),
time_horizon, portfolio_fit (summary only), supporting_evidence (fundamental + technical),
approval_workflow.recommended_action
```

Deferred fields (`liquidity_score` full breakdown, target_3 bull case, full component_detail for every
score, full supporting_evidence categories) ship in v2.

---

## Integration Points (existing platform)

- **Input:** catalyst payloads from the existing Catalyst scanners (SEC filings, news, partnerships, financing, insider).
- **Market data:** existing market data feeds power M4 technicals and the liquidity gate.
- **Output:** reduced JSON flows into the existing approval workflow, then paper trading execution, gated by the existing risk engine. The Analyst Brain produces recommendations only; it does not place trades.

---

## Explicit Non-Goals for v1

- No full Liquidity & Flow scoring engine.
- No live bottleneck detection (patents, transcripts, lead-time surveys, CapEx curve).
- No options-flow or retail-attention ingestion.
- No autonomous execution — recommendation layer only.
