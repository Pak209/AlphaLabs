# AlphaLab Analyst Brain: Complete Research Framework

The Analyst Brain sits between raw market data and trade recommendations. It converts
raw catalysts into high-conviction, scored trade ideas. This document is the design
specification — not an implementation. A future AI agent will implement it.

---

## Part 1: Catalyst Quality Score (0–100)

The Catalyst Quality Score answers one question: **Does this event fundamentally change
the economic reality of this business?** Not every headline is a catalyst. Most are noise.
The scoring system below separates signal from noise with institutional precision.

### Scoring Architecture

Total Weight: 100 points across 8 dimensions.

### Dimension 1: Novelty (Weight: 15 points)

**Why it matters:** Markets price in expectations. Alpha is generated at the delta between
expectation and reality. A catalyst that surprises the market creates a repricing event.
One that was widely anticipated creates nothing — the move already happened.

| Score | Condition |
|-------|-----------|
| 13–15 | Completely unexpected. No analyst coverage, no whisper numbers, no prior signals. The market had zero probability assigned. |
| 10–12 | Partially anticipated. Some speculation existed but magnitude or timing was a surprise. Consensus was materially wrong. |
| 7–9 | Expected directionally but execution details exceeded expectations meaningfully. |
| 4–6 | Widely expected. The event occurred but offered no incremental information beyond consensus. |
| 1–3 | Pre-telegraphed. Management guided explicitly. Options market priced it. Already in the stock. |
| 0 | Confirmed recycled news. Restatement of prior announcement. |

**Key distinction:** Novelty is not about whether the event is *good*. It's about whether the
market was *wrong before the event*. A mildly positive surprise on an under-followed small cap
scores higher than a spectacular beat on a heavily covered mega-cap priced for perfection.

### Dimension 2: Revenue Impact (Weight: 15 points)

**Why it matters:** Revenue is the engine. Every valuation model eventually traces back to
future revenue. A catalyst that structurally expands the revenue opportunity creates a
permanent upward revision cycle.

| Score | Condition |
|-------|-----------|
| 13–15 | Materially expands TAM or secures revenue representing >10% of current annual revenue. Multi-year, recurring. |
| 10–12 | Adds meaningful revenue (5–10% of current run rate). Contract wins, product launches with clear uptake signals. |
| 7–9 | Moderate revenue contribution (2–5%). Directionally positive but limited in scale. |
| 4–6 | Marginal revenue impact. One-time or difficult to model. |
| 1–3 | Indirect revenue implication. Requires multiple steps of logic to connect to revenue. |
| 0 | No revenue impact. Brand or PR event only. |

**Analyst note:** Always adjust for revenue quality. High-margin SaaS recurring revenue scores
higher than equivalent one-time hardware revenue. Contractual revenue scores higher than pipeline.

### Dimension 3: Earnings Impact (Weight: 15 points)

**Why it matters:** The market is ultimately an earnings discounting machine. EPS revisions drive
institutional positioning. A catalyst that forces upward earnings revisions triggers a mechanical
buy cycle: analysts revise, targets increase, funds underweight the name must add exposure.

| Score | Condition |
|-------|-----------|
| 13–15 | Forces meaningful consensus EPS revision (>5% to forward estimates). Gross margin expansion embedded. |
| 10–12 | Modest but clear EPS revision likely (2–5%). Positive operating leverage visible. |
| 7–9 | Earnings impact is real but modest (<2% revision) or delayed by several quarters. |
| 4–6 | Earnings neutral to slightly positive. Cost offsets reduce flow-through. |
| 1–3 | Dilutive or earnings-negative short-term with speculative long-term benefit. |
| 0 | No earnings impact. Pure sentiment or narrative event. |

**Analyst note:** Watch for non-GAAP adjustments that obscure real earnings improvement. A catalyst
that genuinely improves free cash flow conversion matters more than one that flatters GAAP numbers.

### Dimension 4: Competitive Advantage (Weight: 10 points)

**Why it matters:** Temporary wins create temporary stock moves. Structural moat expansion creates
re-rating events. The question is whether this catalyst makes it harder for competitors to displace
this company. Durable advantages justify multiple expansion, not just near-term earnings.

| Score | Condition |
|-------|-----------|
| 9–10 | Creates or significantly deepens a structural moat. Exclusive technology, IP, regulatory approval, exclusive partnership. Competitors cannot easily replicate. |
| 7–8 | Strengthens existing competitive position. Replicable but requires 12–24 months and significant capital. |
| 5–6 | Modest competitive benefit. Industry-wide tailwind that benefits all players equally. |
| 3–4 | Neutral competitive impact. Market share stable. |
| 1–2 | Temporary advantage. Competitors will match within quarters. |
| 0 | Competitively harmful. Signals market share loss or pricing pressure ahead. |

### Dimension 5: Strategic Importance (Weight: 10 points)

**Why it matters:** Some catalysts are isolated events. Others are inflection points in a larger
strategic narrative. A drug approval in a single indication matters less than a platform approval
that opens 12 indications. A partnership with a tier-2 customer matters less than one with the
dominant platform in a sector.

| Score | Condition |
|-------|-----------|
| 9–10 | Pivotal strategic event. Validates business model, opens new strategic optionality, or positions the company as a critical node in a large ecosystem. |
| 7–8 | High strategic relevance. Meaningful step in an established roadmap with visible follow-on opportunities. |
| 5–6 | Moderate strategic value. Fits the strategy but doesn't dramatically accelerate it. |
| 3–4 | Tactical win. Operationally useful but not strategically significant. |
| 1–2 | Isolated or one-off. Hard to connect to long-term direction. |
| 0 | Distracting or contradicts stated strategy. |

### Dimension 6: Market Surprise Factor (Weight: 15 points)

**Why it matters:** Surprise is the single fastest variable in short-term price movement. But the
right measure isn't surprise in isolation — it's *directional surprise relative to positioning*.
A negative result when the market was crowded long creates a violent unwind. A positive result when
crowded short creates a violent squeeze. Both are tradeable. The sizing of the move depends on how
wrong the crowd was.

| Score | Condition |
|-------|-----------|
| 13–15 | Crowd was heavily positioned the wrong way. High short interest + positive catalyst, or crowded long + negative catalyst. Forced position unwind creates mechanical price movement independent of fundamentals. |
| 10–12 | Moderate positioning imbalance. The surprise exists but position unwind is partial, not forced. |
| 7–9 | Market was roughly neutral. Surprise is genuine but no significant positioning unwind to amplify the move. |
| 4–6 | Market was directionally correct, surprise only in magnitude. |
| 1–3 | Market was largely right. Catalyst confirms prevailing narrative. |
| 0 | In-line with consensus. No surprise. |

### Dimension 7: Duration of Impact (Weight: 10 points)

**Why it matters:** A catalyst that creates one quarter of upside is a trade. One that creates three
years of upside is an investment. Both matter — but they require different position sizing, holding
periods, and risk management. Duration drives the quality of the alpha.

| Score | Condition |
|-------|-----------|
| 9–10 | Multi-year impact. Structural change that compounds forward. Investors must continuously revalue. |
| 7–8 | 12–24 month impact. Clear earnings revision cycle. Likely to sustain institutional interest through multiple quarters. |
| 5–6 | 6–12 month impact. Visible earnings benefit for 2–3 quarters. |
| 3–4 | 1–2 quarter impact. Meaningful but temporary improvement. |
| 1–2 | Days to weeks. Event-driven with no fundamental staying power. |
| 0 | One-day event. Noise. |

### Dimension 8: Probability of Follow-Through (Weight: 10 points)

**Why it matters:** An announced deal that closes is worth more than one subject to regulatory
approval. A pilot that converts to full deployment is more valuable than one that may never scale.
The analyst must discount catalyst quality by execution risk.

| Score | Condition |
|-------|-----------|
| 9–10 | Already closed, implemented, or operationally confirmed. Zero execution risk remaining. |
| 7–8 | High probability of execution. Management track record strong. Limited regulatory or operational hurdles. |
| 5–6 | Moderate probability. Some execution risk remains. Regulatory, customer adoption, or capital allocation uncertainty. |
| 3–4 | Conditional on multiple things going right. Material execution risk. |
| 1–2 | Highly uncertain. Early stage, exploratory, or dependent on external parties with misaligned incentives. |
| 0 | Speculative announcement. No evidence of serious progress. |

### Catalyst Quality Score: Final Calculation

```
Catalyst Quality Score =
  (Novelty × 0.15) +
  (Revenue Impact × 0.15) +
  (Earnings Impact × 0.15) +
  (Market Surprise × 0.15) +
  (Competitive Advantage × 0.10) +
  (Strategic Importance × 0.10) +
  (Duration of Impact × 0.10) +
  (Probability of Follow-Through × 0.10)

Normalized to 0–100
```

---

## Part 2: Liquidity & Flow Score (0–100)

Answers: **Can this stock actually move, and can smart money actually participate?** A perfect
catalyst on an uninvestable stock is worthless. An adequate catalyst on a perfectly liquid,
institutionally owned, heavily optioned stock can generate enormous alpha.

### What Creates Explosive Moves

Explosive price moves require three simultaneous conditions:
1. **Supply shock** — float is constrained relative to demand
2. **Demand acceleration** — new buyers appear at higher prices (momentum)
3. **Forced covering** — short sellers must exit, adding to buy pressure

The liquidity framework scores the *structural preconditions* for explosive moves, not the catalyst.

### What Attracts Institutional Capital

Institutions are primarily constrained by:
- **Minimum liquidity thresholds** — they cannot own what they cannot exit
- **Benchmark relevance** — index inclusion creates forced ownership
- **Options market** — institutions hedge, express views, and generate income through options
- **Analyst coverage** — institutions rarely initiate without at least one sell-side note

### Dimension 1: Average Daily Volume (Weight: 20 points)

| Score | Condition |
|-------|-----------|
| 18–20 | >5M shares/day. Institutions can build meaningful positions without impacting price. |
| 14–17 | 1M–5M shares/day. Accessible to mid-size institutions. Sufficient for most strategies. |
| 10–13 | 250K–1M shares/day. Accessible to small institutions and aggressive retail. |
| 6–9 | 50K–250K shares/day. Thinly traded. Large orders move the stock. |
| 2–5 | <50K shares/day. Illiquid. Only appropriate for very small position sizes. |
| 0 | Essentially untradeable. OTC, deregistered, or suspended. |

### Dimension 2: Relative Volume (Weight: 20 points)

The single most important real-time liquidity signal — current volume vs. 20-day average at the
same time of day. Indicates whether something is happening *right now* drawing new participants.

| Score | Condition |
|-------|-----------|
| 18–20 | >5x relative volume. Unusual institutional or algorithmic interest. |
| 14–17 | 3–5x. Elevated interest. Event-driven flow visible. |
| 10–13 | 2–3x. Noticeable pickup. Bears watching. |
| 6–9 | 1.5–2x. Mild elevation. |
| 2–5 | <1.5x. Normal or below-normal volume. |
| 0 | Volume declining. Fading interest. |

### Dimension 3: Float Size (Weight: 15 points)

Float is the supply side. Smaller float = less supply = same demand creates bigger moves.

| Score | Condition |
|-------|-----------|
| 13–15 | Float <20M shares. Micro-float. Any institutional buying creates massive price pressure. High squeeze potential. |
| 10–12 | Float 20M–100M shares. Small float. Meaningful moves on moderate buying. |
| 7–9 | Float 100M–500M shares. Mid-cap range. Normal price dynamics. |
| 4–6 | Float 500M–2B shares. Large cap. Requires heavy capital to move. |
| 1–3 | Float >2B shares. Mega-cap. Moves driven by macro flows, not individual catalysts. |
| 0 | Effectively infinite float (e.g., government dilution, ATM programs in progress). |

**Critical adjustment:** Subtract 3 points if short interest exceeds 20% of float — this creates
squeeze potential that amplifies moves (can be treated as a separate signal).

### Dimension 4: Institutional Ownership (Weight: 15 points)

Signals credibility and creates structured demand, but excessive crowding creates fragility.

| Score | Condition |
|-------|-----------|
| 13–15 | 30–60% institutional ownership. The sweet spot. Enough validation to attract more, not crowded. |
| 10–12 | 15–30% or 60–75%. Either early discovery phase (underowned) or well-established but not extreme. |
| 7–9 | <15% or 75–85%. Either undiscovered (execution risk) or well-owned (crowding risk). |
| 4–6 | <5% or 85–95%. Either pre-institutional or dangerously crowded. |
| 1–3 | >95% institutional. Any selling creates violent downside. No retail cushion. |
| 0 | Entirely retail-owned with no institutional interest. Pure speculation. |

### Dimension 5: Options Market Activity (Weight: 15 points)

The most forward-looking liquidity signal. Unusual options activity often precedes price moves by
24–72 hours. Heavy open interest creates dealer hedging flows that amplify directional moves (gamma).

| Score | Condition |
|-------|-----------|
| 13–15 | Active options market with >10x normal call volume. Dealer gamma creates mechanical buying as price rises. Strike clustering and unusual sweeps confirmed. |
| 10–12 | Moderately active. Normal to elevated call/put ratio. Some gamma exposure. |
| 7–9 | Basic options market. Liquid enough to hedge. No unusual activity. |
| 4–6 | Thin options market. Wide spreads. Limited dealer gamma. |
| 1–3 | Almost no options activity. Limited ability to hedge or leverage. |
| 0 | No options available. Purely directional equity play. |

### Dimension 6: ETF Exposure (Weight: 10 points)

Creates systematic forced buying and selling. When a stock rallies and is in a heavily-traded ETF,
authorized participants must rebalance, creating additional mechanical demand.

| Score | Condition |
|-------|-----------|
| 9–10 | Top 10 holding in a high-AUM, liquid ETF directly tied to the catalyst theme. ETF flows amplify the individual move. |
| 7–8 | Meaningful exposure across 3+ relevant thematic ETFs. |
| 5–6 | Moderate exposure. Included in sector ETFs but not thematic ones. |
| 3–4 | Light exposure. Mostly broad market ETFs where weight is negligible. |
| 1–2 | Minimal exposure. Idiosyncratic story not captured in ETFs. |
| 0 | No ETF exposure. |

### Dimension 7: Retail Attention (Weight: 5 points)

A high-volatility, low-duration signal. Creates explosive short-term moves but not sustainable trends.
Matters primarily for timing entries and understanding the initial price reaction.

| Score | Condition |
|-------|-----------|
| 5 | Viral retail interest. Top trending on financial social platforms. Clear FOMO narrative forming. |
| 4 | Elevated retail interest. Discussed broadly but not viral. |
| 3 | Moderate engagement. Known to retail but not trending. |
| 2 | Low attention. Primarily institutional story. |
| 1 | Minimal awareness. Under-the-radar. |
| 0 | Complete retail obscurity. |

**Analyst note:** Retail attention above 4 is double-edged — it accelerates initial moves but creates
fragile positioning. Weight it accordingly in time horizon analysis.

---

## Part 3: Narrative Strength Score (0–100)

Answers: **Is this stock in the right place at the right time in capital markets history?** Markets
are narrative-driven. Capital flows toward stories. The analyst must know which stories are active,
which are accelerating, and which are dying.

### The Anatomy of a Narrative Cycle

1. **Discovery:** Forward-looking investors identify the theme. Stocks are cheap. Coverage is thin.
2. **Expansion:** Institutional awareness. New ETFs launch. Sell-side initiates. Multiples expand rapidly.
3. **Peak:** On every magazine cover. Valuations extreme. Marginal buyer is unsophisticated. Earnings must justify multiples.
4. **Fade:** Reality fails to meet promise. Capital rotates to the next theme. Only genuine winners survive.

**The highest Alpha scores come from Phase 1–2 transitions, not Phase 3.**

### Component 1: Active Theme Score (0–70)

For each relevant theme, score the stock's exposure:

- **Artificial Intelligence (max 20 if primary):** 18–20 core infrastructure enabler / picks-and-shovels with real AI revenue today; 14–17 strong beneficiary with clear AI revenue line; 10–13 meaningful but secondary; 5–9 indirect; 1–4 label only; 0 no legitimate connection.
- **Data Centers / Infrastructure (max 15):** direct revenue from hyperscaler buildout, power/cooling, networking hardware, construction/real estate exposure.
- **Semiconductors / Compute (max 15):** semiconductor content in AI/HPC, leading-edge process exposure, IP moat, supply chain positioning.
- **Energy / Power (max 12):** generation, transmission, grid modernization. Direct beneficiary of electrification and data center power demand.
- **Defense / Aerospace (max 12):** NATO spending cycle, domestic budget expansion, next-gen weapons, drone/autonomous systems.
- **Robotics / Automation (max 10):** industrial automation, humanoid robotics, autonomous systems software/hardware.
- **Crypto / Digital Assets (max 10):** direct BTC/crypto holdings, blockchain infrastructure, custody, exchange exposure.
- **Emerging themes (max 8):** space, longevity biotech, quantum, nuclear — score on capital flow evidence, not theoretical exposure.

**Rules:** A stock can score across multiple themes; take the highest primary score and add 50% of
secondary theme score. Maximum total from themes: 70 points.

### Component 2: Narrative Phase Multiplier (0–30)

| Score | Condition |
|-------|-----------|
| 27–30 | Phase 1–2 transition. Institutional money clearly moving in. New ETF launches, rising coverage, expanding targets. Capital actively flowing in. |
| 22–26 | Phase 2. Established and expanding. Strong institutional participation. High momentum. |
| 16–21 | Phase 2–3 transition. Well-known but still attracting capital. Valuation stretched but revision cycle continues. |
| 10–15 | Phase 3. Fully priced. Mainstream recognition. Now dependent entirely on execution. |
| 4–9 | Phase 3–4 transition. Fading. Capital rotating out. Underperforming despite reasonable fundamentals. |
| 0–3 | Phase 4. Dead or dying. Avoid. |

### Capital Flow Confirmation

**+5 bonus** if any confirmed: thematic ETF net inflows 4+ consecutive weeks; largest theme fund
increased its top-10 holding in the stock; sell-side sector initiation or major thematic upgrade within 30 days.

**−5 penalty** if: narrative under regulatory attack (antitrust, national security); the dominant
company in the theme issued guidance disappointment; thematic ETF outflows 3+ consecutive weeks.

---

## Part 4: Macro Alignment Score (0–100)

Answers: **Is the macroeconomic environment a tailwind or headwind for this specific type of trade?**
Macro doesn't create alpha — it multiplies or divides it.

### The Macro Matrix

| Quadrant | Growth | Inflation | Best Assets |
|----------|--------|-----------|-------------|
| **Goldilocks** | Rising | Falling | Growth, Tech, Small Cap, Crypto |
| **Overheating** | Rising | Rising | Commodities, Energy, Real Assets, Value |
| **Stagflation** | Falling | Rising | Commodities, Defensive, Short Duration |
| **Recession** | Falling | Falling | Bonds, Defensives, Cash, Quality |

### Dimension 1: Fed Policy & Rate Environment (Weight: 30 points)

| Score | Condition |
|-------|-----------|
| 27–30 | Active cutting cycle. Terminal rate expectations falling. Conditions easing. Optimal for growth/long-duration. |
| 22–26 | On hold, dovish tilt. Cuts priced in forward curve. Liquidity stable. Favorable for equities. |
| 16–21 | On hold, neutral. Neither easing nor tightening. Mixed signal. |
| 10–15 | On hold, hawkish tilt. Hikes possible. Headwind for growth. |
| 4–9 | Active hiking cycle. Conditions tightening. Direct headwind for multiples. |
| 0–3 | Emergency tightening or extreme rate volatility. High uncertainty discount. |

**Application:** For long-duration growth and speculative names, weight this dimension higher.

### Dimension 2: Inflation Signals (CPI/PPI) (Weight: 20 points)

| Score | Condition |
|-------|-----------|
| 18–20 | Inflation clearly falling toward target. CPI and PPI trending down. Confirms Fed pause/cut. |
| 14–17 | Decelerating. Progress evident. No re-acceleration concerns. |
| 10–13 | Stable near target. Neither problem nor tailwind. |
| 6–9 | Sticky above target. Re-acceleration risk present. |
| 2–5 | Rising or re-accelerating. Delays Fed easing. Compression risk for growth names. |
| 0–1 | Inflation surge. Forces hawkish response. Structural headwind. |

### Dimension 3: Labor Market & Growth (Weight: 20 points)

| Score | Condition |
|-------|-----------|
| 18–20 | Goldilocks labor market. Employment stable, wage growth moderate. GDP at/above trend. No recession signal. |
| 14–17 | Softening gradually. Unemployment rising slowly. GDP near trend. Soft landing. |
| 10–13 | Mixed signals. Some softening. GDP slightly below trend but positive. |
| 6–9 | Deteriorating. Initial claims rising. Risk-off signals emerging. |
| 2–5 | Significant deterioration. Recession indicators flashing. |
| 0–1 | Recession confirmed or imminent. Protect capital. |

### Dimension 4: Dollar & Credit Conditions (DXY + Spreads) (Weight: 15 points)

| Score | Condition |
|-------|-----------|
| 13–15 | Dollar weakening. Spreads tight and stable. EM rallying. Global risk appetite high. |
| 10–12 | Dollar stable to slightly weak. Spreads comfortable. Normal risk environment. |
| 7–9 | Dollar neutral. Spreads beginning to widen slightly. Some caution. |
| 4–6 | Dollar strengthening. Spreads widening. Some credit stress. Risk-off tilt. |
| 1–3 | Dollar surging. Spreads widening meaningfully. Cross-asset stress. |
| 0 | Flight-to-safety mode. Credit crisis signals. Systemic risk. |

### Dimension 5: Liquidity Conditions (Yields + TGA + RRP) (Weight: 15 points)

**Why it matters:** The actual quantity of dollars in the system drives risk assets more than any
other variable over 3–12 month horizons.

| Score | Condition |
|-------|-----------|
| 13–15 | System liquidity expanding. RRP draining, TGA drawdown. Net liquidity increasing. Rocket fuel for risk assets. |
| 10–12 | Stable to slightly expanding. No significant drain. |
| 7–9 | Neutral. Treasury issuance roughly matched by Fed accommodation. |
| 4–6 | Tightening. Net issuance above absorption. RRP refilling. Quiet headwind. |
| 1–3 | Contraction. QT continuing, heavy issuance, conditions tightening passively. |
| 0 | Acute liquidity crisis. System stress. |

### Macro Context Modifiers

**Risk-On Confirmation (+5):** VIX < 18 AND S&P 500 above 200-day MA AND credit spreads below 12-month average.

**Risk-Off Warning (−10):** VIX > 25 OR S&P 500 below 200-day MA OR IG spreads >50bps above 12-month average.
Reduce position sizing regardless of catalyst quality. Macro headwinds override individual stock alpha.

---

## Part 5: Technical Confirmation Score (0–100)

Answers: **Is price action confirming or contradicting the fundamental thesis?** This is a
confirmation layer, not a trade-idea generator. A strong catalyst with weak technicals deserves
smaller sizing and a wider stop.

### The Fundamental Principle

If the thesis is correct but price disagrees, one of three things is true:
1. The market hasn't digested the information yet (opportunity)
2. The market knows something the analyst doesn't (danger)
3. The timing is wrong (patience required)

### Dimension 1: Trend Structure (Weight: 25 points)

| Score | Condition |
|-------|-----------|
| 23–25 | Clear uptrend on multiple timeframes. Higher highs/lows confirmed. Price above all major MAs (20/50/200), properly stacked. |
| 18–22 | Uptrend on primary timeframe. Minor pullback but trend intact. Above 50-day and 200-day. |
| 13–17 | Neutral. Sideways consolidation. Range-bound. Trend unclear. |
| 8–12 | Weakening. Recent breakdown of short-term structure. Below 20/50-day but above 200-day. |
| 3–7 | Downtrend on primary timeframe. Lower highs/lows. Below key MAs. |
| 0–2 | Severe downtrend. Extended breakdown. Far below all MAs. |

### Dimension 2: Volume Confirmation (Weight: 20 points)

Volume is the only technical indicator that cannot be faked.

| Score | Condition |
|-------|-----------|
| 18–20 | Advancing on above-average volume, declining on below-average volume. Classic accumulation. |
| 14–17 | Generally constructive. Buying days outnumber selling days by volume. |
| 10–13 | Mixed signals. Neither clear accumulation nor distribution. |
| 6–9 | Mild distribution. Rising on light volume or falling on heavy volume. |
| 2–5 | Clear distribution. Heavy selling volume on down days. Institutions exiting. |
| 0–1 | Capitulation selling OR climactic buying (both reversal signals requiring caution). |

### Dimension 3: Key Level Analysis (Support/Resistance) (Weight: 25 points)

| Score | Condition |
|-------|-----------|
| 23–25 | Breaking out above major resistance on volume. Former resistance becomes support. Clear air above. Maximum asymmetry. |
| 18–22 | Testing or recently cleared a key level. Clean structure. Defined support below. |
| 13–17 | Mid-range. Neither at key support nor major resistance. Neutral. |
| 8–12 | Approaching major resistance. Overhead supply. Risk/reward compressed. |
| 3–7 | At or below major support. Downward momentum. Multiple failed attempts to hold. |
| 0–2 | Freefall through multiple support levels. No base established. |

### Dimension 4: Relative Strength (Weight: 20 points)

| Score | Condition |
|-------|-----------|
| 18–20 | New highs while sector/market flat or down. Institutional accumulation against macro headwinds. |
| 14–17 | Outperforming sector by >5% over 20 days. Money flowing into this name specifically. |
| 10–13 | In line with sector. No outperformance, no underperformance. |
| 6–9 | Lagging sector by 3–5%. Money may be rotating away. |
| 2–5 | Significantly underperforming. Capital clearly exiting. Warning signal. |
| 0–1 | Crashing in a rising market. Catastrophic relative weakness. Fundamental/fraud risk. |

### Dimension 5: Setup Quality (Consolidation Pattern) (Weight: 10 points)

| Score | Condition |
|-------|-----------|
| 9–10 | Textbook consolidation/flag. Digested a prior move cleanly. Low-volatility tightening before catalyst. Highest-probability entry. |
| 7–8 | Good consolidation. Range contracting. |
| 5–6 | Acceptable. Range wide but directional bias clear. |
| 3–4 | Messy. Wide swings. Entry requires wider stop. |
| 1–2 | Post-spike volatility. Price discovery phase. Wait for stabilization. |
| 0 | Gap-up entry with no pullback. Chasing. Highest technical risk. |

---

## Part 6: Bottleneck Intelligence Framework

AlphaLab's proprietary edge. Answers the question generalist analysts miss: **In a complex system,
what is the single component everything else is waiting on — and who owns it?**

### The Fundamental Law of Bottleneck Investing

**In any constrained system, the entity that controls the bottleneck captures disproportionate
margin, pricing power, and capital.** When the bottleneck shifts, the prior holder's margin
compresses and the new holder's margin expands.

This is what happened in the AI cycle:
- 2020–2022: Software/cloud was the bottleneck → high multiples
- 2023–2024: Compute/GPUs became the bottleneck → explosive margin/multiple expansion
- 2024–2025: Power and data center capacity became the bottleneck → energy/infrastructure expansion
- 2025–?: Network interconnects, memory bandwidth, or software orchestration may be next

### The Bottleneck Stack

```
Layer 7: Applications & End-User Software
Layer 6: AI Models & Inference
Layer 5: Orchestration & MLOps
Layer 4: Networking & Interconnects
Layer 3: Memory & Storage
Layer 2: Compute (GPUs/TPUs/Custom Silicon)
Layer 1: Data Centers & Physical Infrastructure
Layer 0: Power (Generation, Transmission, Distribution)
```

**The bottleneck is always the layer that:** has the longest lead time; has the fewest viable
suppliers; commands the highest and most rapidly expanding gross margins; is cited most frequently
in competitor earnings calls as a constraint.

### Bottleneck Identification Protocol

1. **Lead Time Analysis** — Track which layer hyperscalers and enterprise buyers complain about or
   plan around furthest in advance. *Signal: CapEx guidance shifting allocation toward a layer = that layer is becoming the bottleneck.*
2. **Gross Margin Expansion Scan** — Screen for margin expansion at each layer. *Signal: 300bps+ QoQ gross margin expansion = approaching or at bottleneck status.*
3. **Competitor Complaint Mining** — Analyze transcripts for "supply constraints," "lead times," "availability," "capacity." *Signal: 5+ Fortune 500 companies citing the same component as a constraint in one earnings cycle confirms the bottleneck.*
4. **CapEx Forward Curve** — When capital floods toward solving a bottleneck, it's in late Phase 2. The current holder's pricing power persists 12–24 months while the solution is built; the next bottleneck emerges at an adjacent layer. *Signal: When everyone is investing massively in power/data centers, the next bottleneck is likely networking or memory.*

### The Four Bottleneck Questions

- **Q1: What is today's bottleneck?** Identify the constrained layer, who controls it, pricing power evidence, and how long the constraint persists given current investment.
- **Q2: What is tomorrow's bottleneck?** Model where the constraint migrates once current investments relieve today's bottleneck. The best trades are companies that *become* the bottleneck before the market recognizes the transition.
- **Q3: Who benefits if this bottleneck persists?** Map companies that benefit from the constraint remaining — usually direct owners of the constrained asset. Score for duration and magnitude of pricing power.
- **Q4: Who benefits if this bottleneck is solved?** Map companies currently *held back* by the constraint. When resolved, their economics improve dramatically. Often mis-priced because the market discounts their future unconstrained earnings power.

### Per-Layer Scoring (each 0–20, higher = more bottlenecked = more pricing power now)

- **Power (L0):** generation/transmission lead time; who controls scarcest assets.
- **Data Centers (L1):** hyperscaler pre-leasing; land, permits, power availability, construction capacity.
- **Compute (L2):** GPU allocation timelines; TSMC capacity, advanced packaging, HBM attachment.
- **Memory (L3):** HBM supply vs. demand; SK Hynix, Samsung, Micron capacity.
- **Networking (L4):** InfiniBand vs. Ethernet for AI clusters; optical interconnects, switch silicon.
- **Orchestration (L5):** MLOps, inference optimization; bottleneck is talent/IP, not physical capacity.
- **Models (L6):** foundation model providers; training compute, alignment, multimodal gaps.
- **Applications (L7):** enterprise adoption rates; model capability gaps, security/compliance, change management.

### Bottleneck Score Calculation

```
Bottleneck Intelligence Score =
  (Primary Layer Bottleneck Score × 0.40) +
  (Forward Bottleneck Positioning Score × 0.35) +
  (Bottleneck Duration Score × 0.25)

Normalized to 0–100
```

### Early Bottleneck Detection Signals

1. **Patent filing spikes** in a technology area — companies solving a problem they expect to become valuable.
2. **M&A activity** targeting small companies at specific layers — acquirers pay premiums for solutions to their bottlenecks.
3. **Talent migration patterns** — engineers moving between layers signals where the hard problems and capital are moving.
4. **University/agency research funding** — DARPA contracts, NSF grants, hyperscaler research partnerships precede commercial bottlenecks by 18–36 months.
5. **Component lead time surveys** — distributor lead times are the most real-time measure of physical supply constraints.

---

## Part 7: Composite Alpha Score (0–100)

Not a simple average. A conviction-weighted composite reflecting the actual hierarchy of importance.

### Weighting Rationale

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Catalyst Quality | 30% | The source of alpha. Without a real catalyst, nothing else matters. |
| Liquidity & Flow | 20% | The mechanism of alpha. Can't trade what can't move. |
| Narrative Strength | 15% | The multiplier of alpha. Amplifies or dampens catalyst response. |
| Macro Alignment | 15% | The environment of alpha. Overrides individual analysis in extremes. |
| Technical Confirmation | 10% | The timing of alpha. Confirms or refines entry. |
| Bottleneck Intelligence | 10% | The structural alpha. Identifies durable advantage. |

### Alpha Score Formula

```
Alpha Score =
  (Catalyst Quality Score × 0.30) +
  (Liquidity & Flow Score × 0.20) +
  (Narrative Strength Score × 0.15) +
  (Macro Alignment Score × 0.15) +
  (Technical Confirmation Score × 0.10) +
  (Bottleneck Intelligence Score × 0.10)
```

### Score Thresholds and Action Protocol

**90–100: Exceptional — Maximum Conviction.** Near-perfect alignment across every dimension.
*Frequency: 2–5/quarter. Sizing: max allowed (3–5%). Action: enter at market, don't wait. Return potential: 20–50%.*

**80–89: High Conviction — Full Position.** Strong alignment with one or two minor weaknesses.
*Frequency: 10–20/quarter. Sizing: 2–3%. Action: enter on first confirmation, add on constructive pullback. Return potential: 15–30%.*

**70–79: Tradeable — Standard Position.** Legitimate edge; one or two components meaningfully weak.
*Frequency: 20–40/quarter. Sizing: 1–2%. Action: wait for technical confirmation, don't chase. Return potential: 10–20%.*

**60–69: Watchlist — Monitor Only.** Interesting but not ready. Timing or macro wrong, or technicals broken.
*Sizing: 0. Action: monitor for upgrade to 70+. Set alerts on key inflection points.*

**Below 60: Ignore.** Combination of weaknesses too severe. Passing is a position; capital preservation
enables the next high-conviction trade.

### Override Conditions

**Hard No — score irrelevant, do not trade:** active SEC investigation or DOJ inquiry; auditor
resignation or going-concern opinion; credible documented fraud allegation; VIX > 35; stock halted
for regulatory review; dilutive capital raise in progress at below-market pricing.

**Score Floor Adjustments:**
- Macro Alignment < 30 → cap Alpha Score at 75.
- Liquidity < 20 → cap Alpha Score at 65.
- Catalyst Quality < 30 → cap Alpha Score at 60.

---

## Part 8: Final Analyst Output — JSON Structure

Canonical output the Analyst Brain produces for every idea scoring 60+. Every field is required.

```json
{
  "metadata": {
    "analysis_id": "unique identifier for this analysis instance",
    "generated_at": "ISO 8601 timestamp",
    "analyst_version": "version of the analyst framework used",
    "data_freshness": {
      "catalyst_source_timestamp": "when the catalyst was first detected",
      "price_data_timestamp": "when market data was last updated",
      "macro_data_timestamp": "when macro indicators were last refreshed"
    }
  },
  "identity": {
    "ticker": "equity ticker symbol",
    "company_name": "full legal company name",
    "sector": "GICS sector classification",
    "industry": "GICS industry classification",
    "market_cap": "current market capitalization in USD",
    "float_shares": "publicly available float in shares",
    "exchange": "primary listing exchange"
  },
  "catalyst": {
    "headline": "one-sentence description of the catalyst event",
    "type": "earnings | partnership | contract | product_launch | regulatory_approval | insider_activity | macro_event | technical_breakout | analyst_action | m_and_a | financing | restructuring",
    "source": "where the catalyst was detected (SEC filing, press release, news wire, etc.)",
    "source_url": "direct link to original catalyst document",
    "announced_at": "timestamp of original announcement",
    "detected_at": "timestamp AlphaLab first identified the catalyst",
    "detection_lag_minutes": "time between announcement and detection",
    "raw_text": "verbatim excerpt of the most important section of the catalyst"
  },
  "thesis": {
    "core_argument": "2-3 sentences: (1) what happened, (2) why the market is mispricing it, (3) what the correct reaction should be",
    "fundamental_change": "what specifically changed about the business economics",
    "variant_perception": "what AlphaLab believes that consensus does not — the source of edge",
    "expected_mechanism": "earnings revision cycle | multiple expansion | short squeeze | narrative momentum | institutional accumulation",
    "key_assumption": "the single most important assumption that must hold",
    "thesis_invalidation": "the specific event or data point that would prove the thesis wrong"
  },
  "scores": {
    "alpha_score": {
      "value": "0-100 composite score",
      "tier": "exceptional | high_conviction | tradeable | watchlist | ignore",
      "confidence": "0-100 confidence in the score itself (data quality and completeness)"
    },
    "catalyst_score": "0-100",
    "liquidity_score": "0-100",
    "narrative_score": "0-100",
    "macro_score": "0-100",
    "technical_score": "0-100",
    "bottleneck_score": "0-100",
    "component_detail": {
      "catalyst_quality": {
        "novelty": {"score": "0-15", "rationale": "string"},
        "revenue_impact": {"score": "0-15", "rationale": "string"},
        "earnings_impact": {"score": "0-15", "rationale": "string"},
        "market_surprise": {"score": "0-15", "rationale": "string"},
        "competitive_advantage": {"score": "0-10", "rationale": "string"},
        "strategic_importance": {"score": "0-10", "rationale": "string"},
        "duration_of_impact": {"score": "0-10", "rationale": "string"},
        "probability_of_follow_through": {"score": "0-10", "rationale": "string"}
      },
      "narrative": {
        "primary_theme": "string",
        "secondary_theme": "string",
        "narrative_phase": "discovery | expansion | peak | fading",
        "capital_flow_direction": "strongly_in | in | neutral | out | strongly_out"
      },
      "macro": {
        "current_quadrant": "goldilocks | overheating | stagflation | recession",
        "risk_environment": "risk_on | neutral | risk_off",
        "macro_override_active": "boolean"
      },
      "technical": {
        "confirms_thesis": "boolean",
        "technical_risk_note": "if confirms_thesis is false, explain the contradiction"
      },
      "bottleneck": {
        "primary_layer": "which stack layer this company primarily operates in",
        "is_current_bottleneck": "boolean",
        "is_next_bottleneck": "boolean",
        "benefits_if_persists": "string",
        "benefits_if_solved": "string"
      }
    }
  },
  "risks": [
    {
      "risk_type": "execution | regulatory | competitive | macro | valuation | technical | liquidity | binary_event",
      "description": "specific risk description",
      "probability": "low | moderate | high",
      "impact_if_realized": "minor | moderate | severe | catastrophic",
      "mitigation": "how this risk is mitigated in the trade structure"
    }
  ],
  "invalidation": {
    "primary_invalidation": "the single condition that would immediately close the trade",
    "secondary_invalidations": ["additional conditions that would reduce conviction"],
    "time_based_invalidation": "if thesis hasn't begun playing out by this date, reassess"
  },
  "trade_structure": {
    "direction": "long | short",
    "instrument": "equity | calls | puts | spread | synthetic",
    "entry": {
      "price_target": "specific price or range",
      "entry_condition": "exact trigger (e.g., 'break and hold above $X on >1.5x volume')",
      "urgency": "immediate | within_session | within_48h | patient_accumulation",
      "max_acceptable_entry": "highest price where risk/reward still justifies entry"
    },
    "stop": {
      "stop_price": "exact stop-loss price",
      "stop_type": "hard_stop | closing_stop | mental_stop",
      "stop_rationale": "why this level (below key support, below MA, etc.)",
      "stop_distance_percent": "percentage loss from entry to stop"
    },
    "target": {
      "target_1": {"price": "string", "rationale": "string", "action": "take partial | tighten stop | hold"},
      "target_2": {"price": "string", "rationale": "string", "action": "string"},
      "target_3": {"price": "string", "rationale": "bull case scenario", "probability": "string"}
    },
    "reward_risk_ratio": "distance to target_1 vs. distance to stop",
    "sizing": {
      "recommended_portfolio_weight": "percentage of total portfolio",
      "scaling_plan": "how to scale in if applicable",
      "max_position_size": "hard cap regardless of conviction"
    },
    "time_horizon": {
      "primary": "intraday | swing (2-10d) | momentum (2-6w) | catalyst (through event) | position (3-12m)",
      "expected_duration": "specific timeframe estimate",
      "catalyst_timing": "known upcoming catalyst (earnings, FDA date, etc.)"
    }
  },
  "portfolio_fit": {
    "fit_summary": "how this trade fits with existing open positions",
    "correlation_risk": "what existing positions this correlates with",
    "sector_concentration": "does adding this create excessive sector concentration",
    "factor_exposure": "growth | momentum | value | quality | small_cap | etc.",
    "hedging_utility": "can this serve as a hedge against other positions",
    "regime_fit": "does this trade type perform well in the current regime"
  },
  "supporting_evidence": {
    "fundamental_evidence": [
      {"type": "earnings_data | revenue_data | guidance | analyst_estimate_revision | insider_transaction | institutional_13f | sec_filing", "description": "string", "source": "string", "date": "string", "significance": "string"}
    ],
    "technical_evidence": [
      {"type": "price_pattern | volume_signal | moving_average | relative_strength | options_flow", "description": "string", "timeframe": "string", "significance": "string"}
    ],
    "macro_evidence": [
      {"indicator": "string", "current_reading": "string", "trend": "string", "relevance": "string"}
    ],
    "bottleneck_evidence": [
      {"source": "earnings call | industry report | patent filing | etc.", "company": "string", "date": "string", "quote_or_observation": "string"}
    ],
    "contra_evidence": [
      {"description": "evidence against the thesis", "weight": "minor | moderate | significant", "rebuttal": "how it is addressed"}
    ]
  },
  "approval_workflow": {
    "recommended_action": "approve_immediate | approve_conditional | approve_reduced_size | escalate_for_review | reject",
    "conditions_for_approval": "if conditional, what must be met",
    "escalation_reason": "if escalate, why human review is required",
    "auto_approve_eligible": "boolean",
    "risk_engine_flags": ["flags raised by the risk engine that must be acknowledged"]
  }
}
```

---

## Framework Integration Summary

```
Raw Catalyst
     -> Catalyst Quality Score    (Is this event real and significant?)
     -> Liquidity & Flow Score    (Can this trade be executed profitably?)
     -> Narrative Strength Score  (Is capital flowing toward this story?)
     -> Macro Alignment Score     (Is the environment a tailwind or headwind?)
     -> Technical Confirmation    (Does price action confirm the thesis?)
     -> Bottleneck Intelligence   (Is there structural, durable edge?)
     -> Composite Alpha Score     (Single number: how hard to fight for this trade?)
     -> Final Analyst Output JSON (Everything the execution layer needs to act)
```

Core philosophy: **alpha is the intersection of genuine information asymmetry, structural market
mechanics, and correct timing.** No single factor is sufficient. The highest-conviction trades are
those where a novel, high-quality catalyst hits a liquid, momentum-carrying stock inside an expanding
narrative, in a constructive macro environment, confirmed by price action, in a company that controls
an active structural bottleneck. When all six vectors align, AlphaLab has identified a trade that most
of Wall Street will not fully understand until it has already moved.
