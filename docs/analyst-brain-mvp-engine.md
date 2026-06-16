# AlphaLab MVP Scoring Engine — Design

Reference: [analyst-brain-framework.md](analyst-brain-framework.md). This is a **design only**, scoped
so a solo developer can ship it in under a week. It deliberately collapses the framework's 8-dimension
catalyst and full liquidity engine into the smallest set of inputs that are (a) available from data you
already have and (b) actually predictive.

**Design principle:** every score is a weighted sum of 3–5 sub-signals, each on a fixed 0–100 sub-scale.
No ML, no optimization, no live transcript mining. Everything is a lookup or a simple arithmetic rule,
so every score is fully explainable and unit-testable.

---

## 1. Catalyst Score (0–100)

The framework uses 8 dimensions. For a 1-week build, collapse to the **4 that are scorable from a
catalyst payload without fundamental modeling.** The dropped dimensions (revenue/earnings impact
magnitude, competitive advantage) require financial modeling that isn't MVP-feasible — they get folded
into a coarse `materiality` proxy instead.

### Exact inputs

| Sub-signal | Range | Source of value |
|-----------|-------|-----------------|
| `catalyst_type_weight` | 0–100 | Static lookup table keyed on catalyst type |
| `novelty` | 0–100 | Computed: is this the first time this ticker+type fired in N days? |
| `surprise` | 0–100 | Computed: did price gap >X% on detection? (proxy for market surprise) |
| `materiality` | 0–100 | Static lookup: heuristic size of the event |

**`catalyst_type_weight` lookup table (the heart of the score):**

| Catalyst type | Weight |
|---------------|--------|
| M&A / acquisition target | 95 |
| Regulatory approval (FDA, etc.) | 90 |
| Major contract / customer win | 85 |
| Guidance raise / earnings beat | 80 |
| Partnership (tier-1 named) | 70 |
| Insider buying (cluster) | 60 |
| Product launch | 55 |
| Analyst upgrade | 45 |
| Financing / capital raise | 35 |
| Partnership (unnamed / vague) | 30 |
| Generic PR / news | 15 |

**`novelty`:** 100 if no catalyst of the same type on this ticker in the last 30 days; 50 if one prior;
20 if two or more (recycled news). Pure DB query against your catalyst history.

**`surprise`:** map the intraday price move at detection — `|gap %|` → score. `>=8% = 100`,
`5–8% = 80`, `3–5% = 60`, `1–3% = 40`, `<1% = 20`. Uses the market data feed you already have.

**`materiality`:** static keyword/size heuristic — e.g., contract with a stated $ value >10% of market
cap = 100; named Fortune-500 counterparty = 80; otherwise 50; vague/no specifics = 25.

### Exact formula

```
Catalyst Score =
  0.40 × catalyst_type_weight +
  0.25 × surprise +
  0.20 × novelty +
  0.15 × materiality
```

Output clamped to [0, 100].

### Required data sources

- Existing **Catalyst scanners** (type, counterparty, raw text) — for type_weight, materiality.
- Existing **catalyst history DB** — for novelty.
- Existing **market data feed** (intraday price at detection vs. prior close) — for surprise.

No new data source required.

### Thresholds

| Range | Meaning |
|-------|---------|
| 80–100 | Strong catalyst |
| 60–79 | Tradeable catalyst |
| 40–59 | Weak / watch |
| <40 | Noise — drop |

---

## 2. Narrative Score (0–100)

Direct simplification of framework Part 3 (Theme Score × Phase Multiplier). MVP version: a **theme tag
+ a phase tag + an ETF-flow direction.** All three are cheap.

### Exact inputs

| Sub-signal | Range | Source of value |
|-----------|-------|-----------------|
| `theme_strength` | 0–100 | Static lookup: ticker → theme → theme score |
| `phase_factor` | 0–100 | Manual/config tag per theme: discovery/expansion/peak/fading |
| `flow_direction` | 0–100 | Computed: theme ETF net flow over trailing 4 weeks |

**`theme_strength`:** maintain a hand-curated `ticker → theme` map plus a `theme → base score` table.
Themes and base scores straight from the framework:

| Theme | Base score |
|-------|-----------|
| AI (core infra / picks-and-shovels) | 100 |
| Semiconductors / Compute | 90 |
| Data Centers | 90 |
| Energy / Power | 80 |
| Defense | 75 |
| Robotics | 70 |
| Crypto | 65 |
| Emerging (space/quantum/nuclear) | 55 |
| No theme | 20 |

A ticker not in the map = "No theme" = 20.

**`phase_factor`:** one config value per theme, updated manually (weekly is fine):

| Phase | Factor |
|-------|--------|
| Expansion (1→2 transition) | 100 |
| Expansion | 85 |
| Peak | 50 |
| Fading | 20 |

**`flow_direction`:** for the ticker's theme ETF, compute trailing-4-week net flow. `Strong inflow =
100`, `mild inflow = 75`, `flat = 50`, `outflow = 25`, `strong outflow = 0`. Maintain a `theme →
representative ETF` map (e.g., AI→one liquid AI ETF, Semis→one semi ETF).

### Exact formula

```
Narrative Score =
  0.50 × theme_strength +
  0.30 × phase_factor +
  0.20 × flow_direction
```

Clamped to [0, 100].

### Required data sources

- **Static config files** (you maintain): `ticker→theme`, `theme→base_score`, `theme→phase`,
  `theme→ETF`. These are the only "new" artifacts and they're hand-editable text.
- **ETF flow data** for `flow_direction`. MVP-cheap proxy if a flow API is unavailable: use the ETF's
  4-week price return as a flow proxy (>+5% = inflow signal, < −5% = outflow). Document the proxy clearly.

### Thresholds

| Range | Meaning |
|-------|---------|
| 75–100 | Hot, expanding narrative |
| 55–74 | Live narrative |
| 35–54 | Weak / late-stage |
| <35 | No narrative tailwind |

---

## 3. Macro Score (0–100)

Framework Part 4 has 5 dimensions. For MVP, compute **once per day, shared across all tickers** (no
per-trade recompute). Keep 4 inputs, all from free public data.

### Exact inputs

| Sub-signal | Range | Source of value |
|-----------|-------|-----------------|
| `fed_rate_signal` | 0–100 | Trend of the policy rate / latest Fed action |
| `inflation_signal` | 0–100 | CPI direction (latest vs. prior 3 prints) |
| `risk_signal` | 0–100 | VIX level + S&P vs. 200-day MA |
| `liquidity_signal` | 0–100 | 10Y Treasury yield direction + DXY direction |

**`fed_rate_signal`:** cutting/dovish hold = 100; neutral hold = 60; hawkish hold = 40; hiking = 15.
One value, updated when the Fed acts.

**`inflation_signal`:** CPI YoY falling 2+ consecutive prints = 100; falling 1 = 80; flat = 60;
rising 1 = 35; rising 2+ = 10.

**`risk_signal`:** start at 50. `+25` if S&P above 200-day MA, `−25` if below. `+25` if VIX < 18,
`−25` if VIX > 25. Clamp [0,100]. This captures the framework's risk-on/risk-off modifier cheaply.

**`liquidity_signal`:** 10Y yield falling = +25, rising = −25 (from base 50); DXY falling = +25,
rising = −25. Clamp [0,100]. Falling yields + weak dollar = easing liquidity = high score.

### Exact formula

```
Macro Score =
  0.35 × fed_rate_signal +
  0.25 × inflation_signal +
  0.25 × risk_signal +
  0.15 × liquidity_signal
```

Clamped to [0, 100]. **Computed once daily**, stored with a `macro_timestamp`.

### Required data sources

- **FRED** (free API): Fed Funds rate, CPI, 10Y Treasury yield (`DGS10`), DXY proxy.
- **Market data feed** (existing): VIX level, S&P 500 level + 200-day MA.

All free or already-owned. No vendor needed.

### Thresholds

| Range | Meaning |
|-------|---------|
| 70–100 | Risk-on — full conviction |
| 50–69 | Neutral — normal sizing |
| 30–49 | Cautious — reduce sizing |
| <30 | Risk-off — macro override, suppress new longs |

---

## 4. Composite Alpha Score (0–100)

### Exact inputs

The three scores above: `catalyst_score`, `narrative_score`, `macro_score`.

### Exact formula

Since liquidity and technical are out of MVP, renormalize the framework's intent across the three
available components. Catalyst dominates (it's the source of alpha); macro and narrative modulate:

```
Base = 0.50 × catalyst_score + 0.25 × narrative_score + 0.25 × macro_score
```

Then apply **two override rules** from the framework (kept because they prevent the worst paper trades):

```
1. Macro floor:    if macro_score < 30   → Composite = min(Base, 50)
2. Catalyst floor: if catalyst_score < 40 → Composite = min(Base, 45)

Composite Alpha Score = result, clamped to [0, 100]
```

The floors are deliberately the only nonlinearity — they're trivially testable and they encode the rule
"no real catalyst or hostile macro = no trade, regardless of a hot narrative."

### Thresholds (drive paper-trade action)

| Range | Tier | Paper-trade action |
|-------|------|--------------------|
| 80–100 | High Conviction | Auto-submit to approval workflow, full unit size |
| 70–79 | Tradeable | Submit, half size |
| 60–69 | Watchlist | Log only, no trade, alert |
| <60 | Ignore | Drop |

These match the framework's tiers, with Exceptional (90+) folded into High Conviction for MVP simplicity.

---

## Why this is buildable in <1 week

| Day | Work |
|-----|------|
| 1 | Static config tables: catalyst_type_weights, theme maps, ETF maps. Schema for storing scores. |
| 2 | Catalyst Score module + unit tests (pure function over a catalyst payload). |
| 3 | Macro Score daily job (FRED + VIX/S&P) + unit tests. Runs once/day. |
| 4 | Narrative Score module + unit tests (config lookups + ETF flow proxy). |
| 5 | Composite + floors + thresholds + wiring into approval workflow. End-to-end test on historical catalysts. |

**Testability:** every score is a deterministic pure function of its inputs — feed a fixed catalyst
payload + a fixed macro snapshot, assert the exact number. No mocks of external state needed beyond a
frozen input fixture.

**Explainability:** every score ships with its sub-signal breakdown (e.g. `catalyst_score: 78 = type
85×.4 + surprise 80×.25 + novelty 100×.2 + materiality 50×.15`), so every paper trade has a
human-readable "why."

**Predictive usefulness first:** the heaviest weights sit on the two signals with the most edge —
catalyst *type* and *surprise* (price-confirmed) — so the engine biases toward catalysts the market is
already reacting to inside a live narrative and a supportive macro tape.
