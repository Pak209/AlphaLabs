// AlphaLabs PM Approval Prototype — MOCK DATA shaped to the review.v1 API contract.
// MOCK ONLY: no API wiring, no mutations, no backend. These payloads are fabricated
// to validate the proposed read endpoints through the existing prototype UI:
//   GET /api/review/briefing                 -> REVIEW_MOCK.briefing
//   GET /api/review/opportunity/{idea_id}    -> REVIEW_MOCK.opportunities[idea_id]
//
// Convention: snake_case everywhere (matches the Python backend + existing /api/* routes).
//
// ---------------------------------------------------------------------------
// review.v1 schema reference (JSDoc typedefs — vanilla JS friendly, no TS build)
// ---------------------------------------------------------------------------
/**
 * @typedef {Object} DataFreshness
 * @property {"fresh"|"recent"|"stale"|"unknown"} level
 * @property {string|null} as_of            ISO-8601 UTC
 * @property {number|null} age_seconds
 * @property {string} label                 human-readable, e.g. "Updated 12 min ago"
 * @property {boolean} is_stale
 *
 * @typedef {Object} SafetyStatus
 * @property {"dry_run"|"paper"|"live"|"unknown"} posture
 * @property {boolean} armed
 * @property {boolean} reviewable
 * @property {string} label
 *
 * @typedef {Object} ResponseMeta
 * @property {string} generated_at          ISO-8601 UTC
 * @property {string} schema_version        "review.v1"
 * @property {DataFreshness} data_freshness
 * @property {SafetyStatus} safety_status
 *
 * @typedef {Object} ActionMeta
 * @property {"approve"|"reject"|"watchlist"|"explain"} action
 * @property {string} label
 * @property {"POST"|"GET"} method
 * @property {string} endpoint              fully-formed path incl. idea_id
 * @property {boolean} enabled
 * @property {"primary"|"danger"|"neutral"|"ghost"} style
 * @property {("not_implemented"|"not_reviewable"|"already_decided")=} unavailable_reason
 *
 * @typedef {Object} OpportunityCard
 * @property {number} idea_id
 * @property {string} ticker
 * @property {string} name
 * @property {string|null} logo_domain
 * @property {"LONG"|"SHORT"} direction
 * @property {number} conviction_score      0-100 integer
 * @property {number} star_rating           1-5, half-steps allowed
 * @property {string} star_display          "★★★★½"
 * @property {string} expected_move_text
 * @property {string} hold_period_text
 * @property {"Day Trade"|"Swing"|"LEAPS"} strategy
 * @property {number[]} trend_spark
 * @property {"up"|"down"|"flat"} trend_direction
 * @property {"high_conviction"|"tradeable"|"watchlist"|"ignore"} tier
 * @property {ActionMeta[]} actions
 *
 * @typedef {Object} ConfidenceSource
 * @property {"news"|"sec"|"historical_similarity"|"options"|"technicals"|"macro"} key
 * @property {string} label
 * @property {number|null} score            0-100, or null if unavailable
 * @property {string} score_text            "70%" or "—"
 * @property {"available"|"no_entitlement"|"not_implemented"|"insufficient_data"} availability
 * @property {string|null} note
 */

window.REVIEW_MOCK = (function () {
  const SCHEMA = "review.v1";
  const TREND_LABELS = ["Thu", "Fri", "Mon", "Tue", "Wed", "Thu", "Today"];

  // Shared response envelope. In a real endpoint each response is stamped fresh;
  // here the values are fixed so the prototype renders deterministically.
  function meta(genIso) {
    return {
      generated_at: genIso,
      schema_version: SCHEMA,
      data_freshness: {
        level: "recent",
        as_of: "2026-06-25T13:30:00Z",
        age_seconds: 720,
        label: "Updated 12 min ago",
        is_stale: false,
      },
      safety_status: {
        posture: "paper",
        armed: false,
        reviewable: true,
        label: "Paper · disarmed",
      },
    };
  }

  // Read endpoints never mutate. They only describe which buttons to show and
  // which OTHER endpoint the UI would call. watchlist has no endpoint yet, so it
  // is returned disabled + not_implemented rather than faked.
  function actions(ideaId) {
    return [
      { action: "approve",   label: "Approve",   method: "POST", endpoint: `/api/ideas/${ideaId}/approval/approve`, enabled: true,  style: "primary" },
      { action: "reject",    label: "Reject",    method: "POST", endpoint: `/api/ideas/${ideaId}/approval/reject`,  enabled: true,  style: "danger" },
      { action: "watchlist", label: "Watchlist", method: "POST", endpoint: `/api/ideas/${ideaId}/watchlist`,        enabled: false, style: "neutral", unavailable_reason: "not_implemented" },
      { action: "explain",   label: "Explain",   method: "GET",  endpoint: `/api/ideas/${ideaId}/explanation`,      enabled: true,  style: "ghost" },
    ];
  }

  // ---- Opportunity detail objects (GET /api/review/opportunity/{idea_id}) ----
  // Each is a full review.v1 OpportunityDetailResponse. The briefing cards below
  // are derived from these so the mock stays internally consistent.
  const DETAILS = {
    4821: {
      meta: meta("2026-06-25T13:42:10Z"),
      header: { idea_id: 4821, ticker: "ORCL", name: "Oracle Corporation", logo_domain: "oracle.com", chips: ["AI Infrastructure", "Mega Cap"], direction: "LONG", strategy: "Swing" },
      conviction: {
        score: 92, tier: "high_conviction", tier_text: "High Conviction",
        star_rating: 5, star_display: "★★★★★",
        trend_series: [25, 44, 56, 54, 72, 84, 92], trend_labels: TREND_LABELS,
        trend_direction: "up", trend_text: "Improving",
        expected_move_text: "+3–5%", risk_level: "Medium", hold_period_text: "2–7 Days",
        win_probability: 68, snapshotted_at: "2026-06-25T13:30:00Z",
      },
      thesis: {
        why_this_matters:
          "Oracle is positioned at the center of enterprise AI adoption. New cloud " +
          "contracts and AI partnerships are driving strong revenue visibility and " +
          "accelerating data center demand.",
        bull_case: ["AI demand accelerating", "Cloud backlog expanding", "Positive options positioning", "Institutional accumulation"],
        bear_case: ["Near technical resistance", "Valuation premium", "Earnings in 3 weeks"],
      },
      confidence_breakdown: [
        { key: "news", label: "News", score: 92, score_text: "92%", availability: "available", note: null },
        { key: "sec", label: "SEC Filings", score: null, score_text: "—", availability: "not_implemented", note: "Filing analysis not yet available" },
        { key: "historical_similarity", label: "Historical Similarity", score: 90, score_text: "90%", availability: "available", note: null },
        { key: "options", label: "Options Activity", score: null, score_text: "—", availability: "no_entitlement", note: "No options entitlement for this symbol" },
        { key: "technicals", label: "Technicals", score: 67, score_text: "67%", availability: "available", note: null },
        { key: "macro", label: "Macro Environment", score: 81, score_text: "81%", availability: "available", note: null },
      ],
      supporting_evidence: [
        { label: "Multi-year OCI capacity deal", kind: "news" },
        { label: "Backlog +29% YoY", kind: "filing" },
        { label: "3 analyst upgrades (7d)", kind: "analyst" },
        { label: "Call/put ratio 2.4", kind: "flow" },
      ],
      historical_setups: {
        status: "available",
        summary_text: "When similar catalysts occurred in comparable conditions, returns were positive in 7 of 10 instances.",
        setups: [
          { label: "2024 NVDA AI Partnership", return_text: "+8.2%", positive: true },
          { label: "2025 AVGO Cloud Expansion", return_text: "+5.9%", positive: true },
          { label: "2023 SMCI AI Order Surge", return_text: "+11.4%", positive: true },
        ],
      },
      ai_explanation: {
        bullets: [
          "Strong AI partnership announcements",
          "Rapid cloud backlog and data center expansion",
          "Positive news sentiment and analyst upgrades",
          "Institutional accumulation detected",
          "Similar historical setups produced avg +7.2%",
        ],
        probability: 68,
        disclaimer: "AlphaLabs AI may make mistakes. Verify before acting.",
        generated_at: "2026-06-25T13:31:00Z", source: "cached",
      },
      key_risks: ["Broad tech drawdown on rate surprise", "Resistance rejection near prior high", "Earnings volatility in ~3 weeks"],
      source_refs: [
        { id: "cat_9912", kind: "catalyst", label: "OCI deal · 2026-06-24", url: "/api/catalysts/9912" },
        { id: "trade_5510", kind: "trade", label: "Score snapshot", url: null },
      ],
      actions: actions(4821),
    },

    4822: {
      meta: meta("2026-06-25T13:42:11Z"),
      header: { idea_id: 4822, ticker: "NVDA", name: "NVIDIA Corporation", logo_domain: "nvidia.com", chips: ["Semiconductors", "Mega Cap"], direction: "LONG", strategy: "Swing" },
      conviction: {
        score: 88, tier: "high_conviction", tier_text: "High Conviction",
        star_rating: 4.5, star_display: "★★★★½",
        trend_series: [40, 52, 50, 61, 70, 80, 88], trend_labels: TREND_LABELS,
        trend_direction: "up", trend_text: "Improving",
        expected_move_text: "+4–7%", risk_level: "Medium", hold_period_text: "3–7 Days",
        win_probability: 65, snapshotted_at: "2026-06-25T13:30:00Z",
      },
      thesis: {
        why_this_matters:
          "NVIDIA remains the core AI compute supplier. Channel checks point to " +
          "sustained datacenter GPU demand with improving supply throughput.",
        bull_case: ["Datacenter demand surging", "Supply easing", "Strong relative strength", "Options skew bullish"],
        bear_case: ["Crowded long", "High beta to macro", "Valuation extended"],
      },
      confidence_breakdown: [
        { key: "news", label: "News", score: 88, score_text: "88%", availability: "available", note: null },
        { key: "sec", label: "SEC Filings", score: null, score_text: "—", availability: "not_implemented", note: "Filing analysis not yet available" },
        { key: "historical_similarity", label: "Historical Similarity", score: 84, score_text: "84%", availability: "available", note: null },
        { key: "options", label: "Options Activity", score: 79, score_text: "79%", availability: "available", note: null },
        { key: "technicals", label: "Technicals", score: 74, score_text: "74%", availability: "available", note: null },
        { key: "macro", label: "Macro Environment", score: 78, score_text: "78%", availability: "available", note: null },
      ],
      supporting_evidence: [
        { label: "Hyperscaler capex guides up", kind: "news" },
        { label: "Blackwell ramp on track", kind: "news" },
        { label: "Unusual call sweeps", kind: "flow" },
      ],
      historical_setups: {
        status: "available",
        summary_text: "Comparable AI-demand catalysts produced positive 7-day returns in 6 of 9 instances.",
        setups: [
          { label: "2024 AVGO AI Ramp", return_text: "+6.1%", positive: true },
          { label: "2023 AMD MI300 Launch", return_text: "+9.3%", positive: true },
          { label: "2025 MU HBM Surge", return_text: "+7.7%", positive: true },
        ],
      },
      ai_explanation: {
        bullets: [
          "Datacenter GPU demand remains supply-constrained",
          "Hyperscaler capex revised higher",
          "Positive options flow and dealer positioning",
          "Strong relative strength vs. semis",
        ],
        probability: 65,
        disclaimer: "AlphaLabs AI may make mistakes. Verify before acting.",
        generated_at: "2026-06-25T13:31:00Z", source: "cached",
      },
      key_risks: ["Crowded positioning unwind", "Macro risk-off", "Headline supply-chain shocks"],
      source_refs: [
        { id: "cat_9881", kind: "catalyst", label: "Capex guide · 2026-06-23", url: "/api/catalysts/9881" },
      ],
      actions: actions(4822),
    },

    4823: {
      meta: meta("2026-06-25T13:42:12Z"),
      header: { idea_id: 4823, ticker: "MU", name: "Micron Technology", logo_domain: "micron.com", chips: ["Semiconductors", "Large Cap"], direction: "LONG", strategy: "Swing" },
      conviction: {
        score: 85, tier: "high_conviction", tier_text: "High Conviction",
        star_rating: 4, star_display: "★★★★",
        trend_series: [30, 38, 48, 55, 66, 74, 85], trend_labels: TREND_LABELS,
        trend_direction: "up", trend_text: "Improving",
        expected_move_text: "+5–8%", risk_level: "High", hold_period_text: "3–10 Days",
        win_probability: 61, snapshotted_at: "2026-06-25T13:30:00Z",
      },
      thesis: {
        why_this_matters:
          "Micron benefits directly from AI memory demand. HBM is sold out through " +
          "next year and pricing momentum is strengthening across DRAM.",
        bull_case: ["HBM pricing power", "Memory cycle turning", "AI mix improving", "Capacity sold out"],
        bear_case: ["Cyclical sensitivity", "Inventory risk", "China exposure"],
      },
      confidence_breakdown: [
        { key: "news", label: "News", score: 84, score_text: "84%", availability: "available", note: null },
        { key: "sec", label: "SEC Filings", score: null, score_text: "—", availability: "not_implemented", note: "Filing analysis not yet available" },
        { key: "historical_similarity", label: "Historical Similarity", score: 80, score_text: "80%", availability: "available", note: null },
        { key: "options", label: "Options Activity", score: 66, score_text: "66%", availability: "available", note: null },
        { key: "technicals", label: "Technicals", score: 71, score_text: "71%", availability: "available", note: null },
        { key: "macro", label: "Macro Environment", score: 75, score_text: "75%", availability: "available", note: null },
      ],
      supporting_evidence: [
        { label: "HBM sold out FY", kind: "news" },
        { label: "DRAM ASPs rising", kind: "news" },
        { label: "Positive preannounce", kind: "filing" },
      ],
      historical_setups: {
        status: "available",
        summary_text: "Memory up-cycle catalysts delivered positive returns in 6 of 10 comparable setups.",
        setups: [
          { label: "2017 DRAM Up-cycle", return_text: "+10.5%", positive: true },
          { label: "2024 SK Hynix HBM", return_text: "+6.8%", positive: true },
          { label: "2023 WDC Recovery", return_text: "+4.2%", positive: true },
        ],
      },
      ai_explanation: {
        bullets: [
          "AI memory demand outstripping supply",
          "HBM capacity pre-sold",
          "DRAM pricing inflecting higher",
          "Improving gross-margin trajectory",
        ],
        probability: 61,
        disclaimer: "AlphaLabs AI may make mistakes. Verify before acting.",
        generated_at: "2026-06-25T13:31:00Z", source: "cached",
      },
      key_risks: ["Cyclical reversal", "Inventory correction", "Geopolitical/China headlines"],
      source_refs: [
        { id: "cat_9850", kind: "catalyst", label: "HBM preannounce · 2026-06-22", url: "/api/catalysts/9850" },
      ],
      actions: actions(4823),
    },

    4824: {
      meta: meta("2026-06-25T13:42:13Z"),
      header: { idea_id: 4824, ticker: "ASML", name: "ASML Holding", logo_domain: "asml.com", chips: ["Semiconductors", "Mega Cap"], direction: "LONG", strategy: "Swing" },
      conviction: {
        score: 81, tier: "high_conviction", tier_text: "High Conviction",
        star_rating: 4, star_display: "★★★★",
        trend_series: [44, 48, 52, 58, 64, 72, 81], trend_labels: TREND_LABELS,
        trend_direction: "up", trend_text: "Improving",
        expected_move_text: "+3–6%", risk_level: "Medium", hold_period_text: "5–10 Days",
        win_probability: 60, snapshotted_at: "2026-06-25T13:30:00Z",
      },
      thesis: {
        why_this_matters:
          "ASML is the sole supplier of EUV lithography, the bottleneck for leading-edge " +
          "AI chips. Bookings are recovering as foundries expand capacity.",
        bull_case: ["EUV monopoly", "Order book recovery", "Leading-edge capex", "Service revenue sticky"],
        bear_case: ["Export controls", "Lumpy bookings", "EU macro drag"],
      },
      confidence_breakdown: [
        { key: "news", label: "News", score: 79, score_text: "79%", availability: "available", note: null },
        { key: "sec", label: "SEC Filings", score: null, score_text: "—", availability: "not_implemented", note: "Filing analysis not yet available" },
        { key: "historical_similarity", label: "Historical Similarity", score: 78, score_text: "78%", availability: "available", note: null },
        { key: "options", label: "Options Activity", score: null, score_text: "—", availability: "no_entitlement", note: "No options entitlement for this symbol" },
        { key: "technicals", label: "Technicals", score: 69, score_text: "69%", availability: "available", note: null },
        { key: "macro", label: "Macro Environment", score: 72, score_text: "72%", availability: "available", note: null },
      ],
      supporting_evidence: [
        { label: "Bookings rebound", kind: "filing" },
        { label: "High-NA shipments", kind: "news" },
        { label: "Foundry capex up", kind: "news" },
      ],
      historical_setups: {
        status: "available",
        summary_text: "Bookings-recovery catalysts produced positive returns in 6 of 10 instances.",
        setups: [
          { label: "2023 Foundry Capex", return_text: "+5.2%", positive: true },
          { label: "2024 High-NA Ship", return_text: "+4.6%", positive: true },
          { label: "2021 EUV Demand", return_text: "+8.9%", positive: true },
        ],
      },
      ai_explanation: {
        bullets: [
          "Sole EUV supplier for leading-edge nodes",
          "Order book inflecting positively",
          "Foundry capacity expansion underway",
          "Sticky high-margin service revenue",
        ],
        probability: 60,
        disclaimer: "AlphaLabs AI may make mistakes. Verify before acting.",
        generated_at: "2026-06-25T13:31:00Z", source: "cached",
      },
      key_risks: ["New export-control rules", "Bookings timing", "European macro weakness"],
      source_refs: [
        { id: "cat_9799", kind: "catalyst", label: "Bookings update · 2026-06-20", url: "/api/catalysts/9799" },
      ],
      actions: actions(4824),
    },

    4825: {
      meta: meta("2026-06-25T13:42:14Z"),
      header: { idea_id: 4825, ticker: "AMD", name: "Advanced Micro Devices", logo_domain: "amd.com", chips: ["Semiconductors", "Large Cap"], direction: "LONG", strategy: "Day Trade" },
      conviction: {
        score: 69, tier: "watchlist", tier_text: "Watchlist",
        star_rating: 3.5, star_display: "★★★½",
        trend_series: [60, 56, 58, 52, 55, 62, 69], trend_labels: TREND_LABELS,
        trend_direction: "flat", trend_text: "Flat",
        expected_move_text: "+2–4%", risk_level: "High", hold_period_text: "1–3 Days",
        win_probability: 54, snapshotted_at: "2026-06-25T13:30:00Z",
      },
      thesis: {
        why_this_matters:
          "AMD is the credible #2 in AI accelerators. MI300 traction could drive share " +
          "gains, but execution and competitive intensity keep conviction moderate.",
        bull_case: ["MI300 momentum", "Share gains", "AI TAM expansion"],
        bear_case: ["Execution risk", "NVDA dominance", "Margin pressure", "Choppy tape"],
      },
      confidence_breakdown: [
        { key: "news", label: "News", score: 70, score_text: "70%", availability: "available", note: null },
        { key: "sec", label: "SEC Filings", score: null, score_text: "—", availability: "not_implemented", note: "Filing analysis not yet available" },
        // Demonstrates a numeric source that is genuinely thin, not a faked 0.
        { key: "historical_similarity", label: "Historical Similarity", score: null, score_text: "—", availability: "insufficient_data", note: "Too few comparable setups to score" },
        { key: "options", label: "Options Activity", score: 58, score_text: "58%", availability: "available", note: null },
        { key: "technicals", label: "Technicals", score: 55, score_text: "55%", availability: "available", note: null },
        { key: "macro", label: "Macro Environment", score: 71, score_text: "71%", availability: "available", note: null },
      ],
      supporting_evidence: [
        { label: "MI300 design wins", kind: "news" },
        { label: "Cloud adoption", kind: "news" },
        { label: "Improving software stack", kind: "analyst" },
      ],
      // Demonstrates the not_available empty state (similarity engine not built yet).
      historical_setups: { status: "not_available", summary_text: null, setups: [] },
      ai_explanation: {
        bullets: [
          "MI300 gaining design-win traction",
          "Potential accelerator share gains",
          "Software ecosystem maturing",
          "Moderate conviction — watch execution",
        ],
        probability: 54,
        disclaimer: "AlphaLabs AI may make mistakes. Verify before acting.",
        generated_at: "2026-06-25T13:31:00Z", source: "cached",
      },
      key_risks: ["Execution slippage", "NVDA competitive moat", "Gross-margin pressure"],
      source_refs: [
        { id: "cat_9740", kind: "catalyst", label: "MI300 win · 2026-06-19", url: "/api/catalysts/9740" },
      ],
      actions: actions(4825),
    },
  };

  // Derive a briefing OpportunityCard from a full detail object (keeps mock DRY
  // while the emitted briefing payload stays literal review.v1 shape).
  function cardFrom(d) {
    return {
      idea_id: d.header.idea_id,
      ticker: d.header.ticker,
      name: d.header.name,
      logo_domain: d.header.logo_domain,
      direction: d.header.direction,
      conviction_score: d.conviction.score,
      star_rating: d.conviction.star_rating,
      star_display: d.conviction.star_display,
      expected_move_text: d.conviction.expected_move_text,
      hold_period_text: d.conviction.hold_period_text,
      strategy: d.header.strategy,
      trend_spark: d.conviction.trend_series,
      trend_direction: d.conviction.trend_direction,
      tier: d.conviction.tier,
      actions: d.actions,
    };
  }

  const order = [4821, 4822, 4823, 4824, 4825];
  const cards = order.map((id) => cardFrom(DETAILS[id]));

  // ---- Briefing payload (GET /api/review/briefing) ----
  const briefing = {
    meta: meta("2026-06-25T13:42:00Z"),
    market_regime: {
      label: "BULLISH", direction: "bullish", confidence: 84, confidence_text: "High confidence",
      futures: [
        { name: "S&P Futures", value_text: "+0.68%", change_pct: 0.68, direction: "up" },
        { name: "NASDAQ Futures", value_text: "+1.02%", change_pct: 1.02, direction: "up" },
        { name: "VIX", value_text: "-4.1%", change_pct: -4.1, direction: "down" },
        { name: "BTCUSD", value_text: "+2.7%", change_pct: 2.7, direction: "up" },
      ],
      freshness: { level: "fresh", as_of: "2026-06-25T13:30:00Z", age_seconds: 720, label: "12 min ago", is_stale: false },
    },
    lex_summary: {
      text:
        "The market remains constructive. AI infrastructure continues leading. " +
        "Highest conviction today is Oracle. No high-conviction short setup.",
      generated_at: "2026-06-25T13:31:00Z", source: "cached",
    },
    best_opportunity: cards[0],
    top_opportunities: cards,
    // null demonstrates the graceful "no high-conviction short" empty state.
    highest_conviction_short: null,
    highest_conviction_long: cards[0],
    watchlist_changes: {
      added: 4, removed: 2,
      freshness: { level: "recent", as_of: "2026-06-25T13:00:00Z", age_seconds: 2520, label: "42 min ago", is_stale: false },
    },
    market_risks: [
      { label: "Inflation Data Tomorrow", severity: "high" },
      { label: "Earnings Season", severity: "medium" },
      { label: "Bond Auction", severity: "low" },
      { label: "Geopolitical Tension", severity: "medium" },
    ],
    portfolio_exposure: {
      segments: [
        { label: "AI", pct: 42, color: "#22c55e" },
        { label: "Semiconductors", pct: 28, color: "#3b82f6" },
        { label: "Software", pct: 16, color: "#a855f7" },
        { label: "Crypto", pct: 8, color: "#f59e0b" },
        { label: "Cash", pct: 6, color: "#64748b" },
      ],
      // Demonstrates a stale section badge (positions synced hours ago).
      freshness: { level: "stale", as_of: "2026-06-25T09:05:00Z", age_seconds: 16620, label: "Synced 4.6 hrs ago", is_stale: true },
    },
    pending_approvals: { total: 38, high_conviction: 7, needs_review: 31 },
  };

  return {
    schema_version: SCHEMA,
    briefing,
    opportunities: DETAILS,
    order,
    get_opportunity: (id) => DETAILS[id] || null,
  };
})();
