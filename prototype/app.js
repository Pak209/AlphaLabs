// AlphaLabs PM Approval Prototype — view logic.
// Data source: live is the DEFAULT (a single read-only GET to /api/review/briefing
// drives Screen A; window.REVIEW_MOCK is the review.v1 fallback dataset). Mock is an
// explicit dev override via a query flag (?review_data=mock or #/review?data=mock),
// and is also the automatic fallback whenever the live fetch or schema validation
// fails (a visible warning is shown). It never mutates. Decision buttons remain
// inert: they console.log the endpoint they WOULD call and show a local toast, but
// never POST or hit the network. Screens B/C have no live wiring and show honest
// placeholders in live mode rather than mixing mock data with live briefing counts.
(function () {
  const R = window.REVIEW_MOCK;
  // Active Screen-A briefing. Defaults to the mock contract; in live mode it is
  // swapped for a validated payload from GET /api/review/briefing. Any failure
  // falls back to this mock, so the UI is never blank and never fabricated.
  let B = R.briefing;                   // GET /api/review/briefing
  let dataMode = "mock";                // "mock" | "live" — drives the UI badge
  let dataWarning = "";                 // set when a live fetch falls back to mock
  const detail = (id) => R.get_opportunity(id); // GET /api/review/opportunity/{id}
  const app = document.getElementById("app");

  const state = {
    screen: "brief",                    // brief | detail | queue
    currentOppId: R.order[0],
    queueIndex: 0,
    queueOrder: R.order.slice(),
    sheet: { open: false, tab: "ai", oppId: R.order[0] },
    detailPlaceholder: false,           // true when a live card has no mock detail
  };

  /* ---------------- small helpers ---------------- */
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  // Logo tile background is a pure presentation concern (not part of the API
  // contract), so the color lives client-side keyed by ticker.
  const LOGO_COLORS = { ORCL: "#e8442a", NVDA: "#76b900", MU: "#0a4d8c", ASML: "#1f6fb2", AMD: "#231f20" };

  // Accepts any object exposing { ticker, logo_domain }.
  function logo(o, cls = "") {
    const ticker = o.ticker;
    const initials = ticker.slice(0, 2);
    const bg = LOGO_COLORS[ticker] || "#334155";
    const src = o.logo_domain ? `https://logo.clearbit.com/${o.logo_domain}?size=128` : "";
    return `<div class="tkr-logo ${cls}" style="background:${bg}">
      <span class="tkr-init">${initials}</span>
      ${src ? `<img class="tkr-img" src="${src}" alt="${ticker}" loading="lazy" onerror="this.remove()" />` : ""}
    </div>`;
  }

  function stars(value) {
    let out = "";
    for (let i = 1; i <= 5; i++) {
      if (value >= i) out += "★";
      else if (value >= i - 0.5) out += '<span style="position:relative"><span class="s-empty">★</span><span style="position:absolute;left:0;width:50%;overflow:hidden">★</span></span>';
      else out += '<span class="s-empty">★</span>';
    }
    return `<span class="stars">${out}</span>`;
  }

  function evColor(v) { return v >= 80 ? "var(--green)" : v >= 68 ? "var(--green)" : "var(--amber)"; }
  function sparkColor(dir) { return dir === "down" ? "#ef4455" : dir === "flat" ? "#f5b53d" : "#22c55e"; }

  // SVG circular conviction gauge
  function gauge(score, size = 92, cap = "AI Conviction") {
    const r = size / 2 - 7, c = 2 * Math.PI * r, off = c * (1 - score / 100);
    return `
      <div class="regime-gauge" style="text-align:center">
        <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
          <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#1b2331" stroke-width="7"/>
          <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#22c55e" stroke-width="7"
            stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"
            transform="rotate(-90 ${size/2} ${size/2})"/>
          <text x="50%" y="48%" text-anchor="middle" fill="#eef3f9" font-size="${size*0.26}" font-weight="800">${score}</text>
          <text x="50%" y="66%" text-anchor="middle" fill="#8a97a8" font-size="${size*0.12}" font-weight="600">/100</text>
        </svg>
        ${cap ? `<div class="score-cap">${cap}</div>` : ""}
      </div>`;
  }

  function regimeIcon() {
    return `<svg width="56" height="56" viewBox="0 0 56 56" fill="none">
      <circle cx="28" cy="28" r="26" stroke="#22c55e" stroke-width="2" opacity=".5"/>
      <path d="M18 34c2-6 6-9 10-9s8 3 10 9" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
      <path d="M16 22l3 3M40 22l-3 3" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="23" cy="29" r="1.8" fill="#22c55e"/><circle cx="33" cy="29" r="1.8" fill="#22c55e"/>
    </svg>`;
  }

  function lineChart(data, labels, w = 360, hgt = 150) {
    const pad = 26, max = 100, min = 0;
    const innerW = w - pad * 2, innerH = hgt - 34;
    const pts = data.map((v, i) => {
      const x = pad + (innerW * i) / (data.length - 1);
      const y = 8 + innerH * (1 - (v - min) / (max - min));
      return [x, y];
    });
    const path = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const area = `M${pts[0][0]} ${8 + innerH} ` + pts.map((p) => `L${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ") + ` L${pts[pts.length-1][0]} ${8 + innerH} Z`;
    const grid = [0, 25, 50, 75, 100].map((g) => {
      const y = 8 + innerH * (1 - g / 100);
      return `<line x1="${pad}" y1="${y}" x2="${w-6}" y2="${y}" stroke="#1a2230" stroke-width="1"/>
              <text x="6" y="${y+3}" fill="#5e6b7d" font-size="9">${g}</text>`;
    }).join("");
    const xlabels = labels.map((l, i) => {
      const x = pad + (innerW * i) / (labels.length - 1);
      return `<text x="${x}" y="${hgt-4}" fill="#8a97a8" font-size="9.5" text-anchor="middle">${l}</text>`;
    }).join("");
    const last = pts[pts.length - 1];
    return `<svg width="100%" viewBox="0 0 ${w} ${hgt}" preserveAspectRatio="none" style="display:block">
      ${grid}
      <defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#22c55e" stop-opacity=".28"/>
        <stop offset="1" stop-color="#22c55e" stop-opacity="0"/></linearGradient></defs>
      <path d="${area}" fill="url(#lg)"/>
      <path d="${path}" fill="none" stroke="#22c55e" stroke-width="2.4" stroke-linejoin="round"/>
      ${pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="2.6" fill="#22c55e"/>`).join("")}
      <circle cx="${last[0]}" cy="${last[1]}" r="4.5" fill="#22c55e" stroke="#0c1b12" stroke-width="2"/>
      ${xlabels}
    </svg>`;
  }

  function sparkline(data, color = "#22c55e", w = 54, hgt = 22) {
    const max = Math.max(...data), min = Math.min(...data);
    const pts = data.map((v, i) => {
      const x = (w * i) / (data.length - 1);
      const y = 3 + (hgt - 6) * (1 - (v - min) / (max - min || 1));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg width="${w}" height="${hgt}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }

  function donut(segments, size = 78) {
    const r = size / 2 - 8, c = 2 * Math.PI * r;
    let acc = 0;
    const segs = segments.map((d) => {
      const len = (c * d.pct) / 100;
      const seg = `<circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${d.color}" stroke-width="9"
        stroke-dasharray="${len} ${c - len}" stroke-dashoffset="${-acc}"
        transform="rotate(-90 ${size/2} ${size/2})"/>`;
      acc += len;
      return seg;
    }).join("");
    return `<svg width="${size}" height="${size}">${segs}</svg>`;
  }

  const ICN = {
    bell: '<svg width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M6 8a6 6 0 1112 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 003.4 0" stroke-linecap="round"/></svg>',
    refresh: '<svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M21 2v6h-6M3 12a9 9 0 0115-6.7L21 8M3 22v-6h6M21 12a9 9 0 01-15 6.7L3 16" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    menu: '<svg width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M3 6h18M3 12h18M3 18h18" stroke-linecap="round"/></svg>',
    star: '<svg width="20" height="20" fill="#f5b53d" viewBox="0 0 24 24"><path d="M12 2l3 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.9 21l1.2-6.8-5-4.9 6.9-1z"/></svg>',
    dots: '<svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
    check: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    x: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/></svg>',
    starline: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z" stroke-linejoin="round"/></svg>',
    explain: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 015 .3c0 1.7-2.5 2-2.5 3.7M12 17h.01" stroke-linecap="round"/></svg>',
    info: '<svg width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01" stroke-linecap="round"/></svg>',
    filter: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M3 5h18l-7 8v6l-4-2v-4z" stroke-linejoin="round"/></svg>',
    send: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" stroke-linejoin="round"/></svg>',
    nav: {
      brief: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 13h6V4H4zM14 20h6V4h-6zM4 20h6v-4H4z" stroke-linejoin="round"/></svg>',
      opp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/></svg>',
      watch: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z" stroke-linejoin="round"/></svg>',
      port: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 7h18v13H3zM8 7V4h8v3" stroke-linejoin="round"/></svg>',
      more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 7h16M4 12h16M4 17h16" stroke-linecap="round"/></svg>',
    },
  };

  function tabbar(active) {
    const items = [
      ["brief", "Brief"], ["opp", "Opportunities"], ["watch", "Watchlist"], ["port", "Portfolio"], ["more", "More"],
    ];
    return `<nav class="tabbar">${items.map(([k, label]) =>
      `<button class="tab ${active === k ? "active" : ""}" data-tab="${k}">${ICN.nav[k]}<span>${label}</span></button>`
    ).join("")}</nav>`;
  }

  // Renders the meta envelope (data_freshness + safety_status) as compact chips.
  function metaChips(m) {
    const f = m.data_freshness, s = m.safety_status;
    return `<div class="meta-chips">
      <span class="meta-chip ${f.is_stale ? "stale" : ""}">${esc(f.label)}</span>
      <span class="meta-chip safety">${esc(s.label)}</span>
    </div>`;
  }

  // "Mock Data" / "Live Data" indicator shown in the Screen-A date row.
  function dataBadge() {
    const live = dataMode === "live";
    return `<span class="data-badge ${live ? "live" : "mock"}">${live ? "Live Data" : "Mock Data"}</span>`;
  }

  // Visible warning banner shown only when a live fetch failed and we fell back.
  function dataWarningBanner() {
    return dataWarning ? `<div class="data-warning">⚠ ${esc(dataWarning)}</div>` : "";
  }

  /* ---------------- live data wiring (read-only) ---------------- */
  // Feature flag: live mode is the DEFAULT (the /review route attempts the
  // read-only GET /api/review/briefing). Mock is an explicit dev override via
  // query string (?review_data=mock) or hash query (#/review?data=mock). Any
  // live failure still falls back to mock data with a visible warning.
  function parseDataMode() {
    try {
      const qs = new URLSearchParams(location.search);
      if (qs.get("review_data") === "mock") return "mock";
      const h = location.hash || "";
      const qi = h.indexOf("?");
      if (qi >= 0) {
        const hp = new URLSearchParams(h.slice(qi + 1));
        if (hp.get("data") === "mock" || hp.get("review_data") === "mock") return "mock";
      }
    } catch (_) { /* malformed URL -> fall through to live (mock is the fallback) */ }
    return "live";
  }

  // Structural validation: confirm the payload is review.v1 and carries the
  // sections Screen A needs. Returns "" when valid, else a human-readable reason.
  function validateBriefing(p) {
    if (!p || typeof p !== "object") return "response was not a JSON object";
    const m = p.meta;
    if (!m || typeof m !== "object") return "response is missing meta envelope";
    if (m.schema_version !== "review.v1") return "unexpected schema_version (need review.v1)";
    if (!m.data_freshness || !m.safety_status) return "meta is missing freshness/safety status";
    if (!p.market_regime || typeof p.market_regime !== "object") return "missing market_regime";
    if (!p.lex_summary || typeof p.lex_summary !== "object") return "missing lex_summary";
    if (!Array.isArray(p.top_opportunities)) return "missing top_opportunities";
    if (!Array.isArray(p.market_risks)) return "missing market_risks";
    if (!p.watchlist_changes || typeof p.watchlist_changes !== "object") return "missing watchlist_changes";
    if (!p.portfolio_exposure || typeof p.portfolio_exposure !== "object") return "missing portfolio_exposure";
    if (!p.pending_approvals || typeof p.pending_approvals !== "object") return "missing pending_approvals";
    return "";
  }

  // Read-only GET. Never sends a body, never mutates, never POSTs.
  async function loadLiveBriefing() {
    const res = await fetch("/api/review/briefing", { method: "GET", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  /* ---------------- Screen A: Morning Brief ---------------- */
  function renderBrief() {
    const r = B.market_regime;
    const best = B.best_opportunity;
    const top = B.top_opportunities;
    const wl = B.watchlist_changes, hs = B.highest_conviction_short, hl = B.highest_conviction_long;
    const pa = B.pending_approvals;
    const exp = B.portfolio_exposure;

    return `
      <header class="app-header">
        <button class="icon-btn">${ICN.menu}</button>
        <div class="brand"><span class="logo">A</span>AlphaLabs</div>
        <span class="spacer"></span>
        <button class="icon-btn bell-wrap">${ICN.bell}<span class="bell-badge">2</span></button>
        <button class="icon-btn">${ICN.refresh}</button>
      </header>
      <div class="date-row">Thu, Jun 25, 2026 · 6:42 AM PT ${dataBadge()} ${metaChips(B.meta)}</div>
      <div class="content">
        ${dataWarningBanner()}

        <section class="panel">
          <div class="panel-head"><span class="section-num">1</span><span class="panel-eyebrow">Market Regime</span></div>
          <div class="regime-top">
            <div class="regime-gauge">${regimeIcon()}</div>
            <div class="regime-meta">
              <div class="regime-label">${esc(r.label)}</div>
              <div class="regime-conf">${esc(r.confidence_text)}${r.confidence != null ? ` · ${r.confidence}%` : ""}</div>
            </div>
            <div class="futures">
              ${(r.futures || []).map((f) => `<div class="fut-row"><span class="fn">${esc(f.name)}</span><span class="fv ${f.direction}">${esc(f.value_text)}</span></div>`).join("")}
            </div>
          </div>
          <div class="lex">
            <div class="lex-title">💬 Lex Summary</div>
            <div class="lex-body">${esc(B.lex_summary.text || B.lex_summary.note || "No market summary available.")}</div>
          </div>
        </section>

        ${best ? `
        <section class="panel hero" data-open-detail="${best.idea_id}">
          <div class="panel-head"><span class="section-num">2</span><span class="panel-eyebrow">Today's Best Opportunity</span></div>
          <div class="hero-top">
            ${logo(best, "lg")}
            <div class="hero-mid">
              ${stars(best.star_rating)}
              <div class="tkr-name-lg">${esc(best.ticker)}</div>
              <div class="tkr-sub">${esc(best.name)}</div>
              <div class="pill-row">${[best.strategy, best.expected_move_text, best.hold_period_text].filter(Boolean).map(esc).join(" · ")}</div>
            </div>
            <div class="hero-score">
              <div class="score-big">${best.conviction_score != null ? best.conviction_score : "—"}<span class="den">/100</span></div>
              <div class="score-cap">AI Conviction</div>
            </div>
          </div>
        </section>` : `
        <section class="panel"><div class="panel-head"><span class="section-num">2</span><span class="panel-eyebrow">Today's Best Opportunity</span></div>
          <div class="empty-note">No opportunities in today's review queue.</div></section>`}

        <section class="panel">
          <div class="panel-head"><span class="section-num">3</span><span class="panel-eyebrow">Top 5 Opportunities</span><span class="view-all">View All</span></div>
          ${top.map((o, i) => `
            <div class="opp-row" data-open-detail="${o.idea_id}">
              <span class="opp-rank">${i + 1}</span>
              ${logo(o, "sm")}
              <div class="opp-id">
                <div>
                  <div class="opp-tkr">${esc(o.ticker)}</div>
                  <div class="opp-name">${esc(o.name)}</div>
                </div>
              </div>
              <div class="opp-right">
                ${stars(o.star_rating)}
                <span class="opp-score">${o.conviction_score != null ? o.conviction_score : "—"}</span>
                ${o.trend_spark && o.trend_spark.length ? sparkline(o.trend_spark, sparkColor(o.trend_direction)) : ""}
              </div>
            </div>
            ${i < top.length - 1 ? '<div class="divline"></div>' : ""}
          `).join("")}
        </section>

        <div class="mini-grid">
          <section class="panel mini">
            <span class="panel-eyebrow"><span class="section-num">4</span> Watchlist Changes</span>
            ${(wl.added != null || wl.removed != null)
              ? `<div class="wl-line"><span class="up">↑</span> ${wl.added} Added</div>
                 <div class="wl-line"><span class="down">↓</span> ${wl.removed} Removed</div>`
              : `<div class="empty-note" style="margin-top:8px">${esc(wl.note || "Not available yet.")}</div>`}
          </section>
          <section class="panel mini">
            <span class="panel-eyebrow"><span class="section-num">5</span> Highest Conviction Short</span>
            ${hs ? `
              <div style="font-weight:800;margin:6px 0 2px">🔻 ${esc(hs.ticker)}</div>
              ${stars(hs.star_rating)} <span style="font-weight:800">${hs.conviction_score != null ? hs.conviction_score : "—"}</span>
              ${hs.expected_move_text ? `<div class="down" style="font-weight:700;margin-top:4px">${esc(hs.expected_move_text)}</div>` : ""}`
            : `<div class="empty-note" style="margin-top:8px">No high-conviction short today.</div>`}
          </section>
          <section class="panel mini">
            <span class="panel-eyebrow"><span class="section-num">6</span> Highest Conviction Long</span>
            ${hl ? `
              <div style="font-weight:800;margin:6px 0 2px">🔺 ${esc(hl.ticker)}</div>
              ${stars(hl.star_rating)} <span style="font-weight:800">${hl.conviction_score != null ? hl.conviction_score : "—"}</span>
              ${hl.expected_move_text ? `<div class="up" style="font-weight:700;margin-top:4px">${esc(hl.expected_move_text)}</div>` : ""}`
            : `<div class="empty-note" style="margin-top:8px">No high-conviction long today.</div>`}
          </section>
        </div>

        <div class="mini-grid">
          <section class="panel mini">
            <span class="panel-eyebrow"><span class="section-num">7</span> Market Risks</span>
            <ul class="risk-list">${B.market_risks.map((x) => `<li><span class="sev sev-${x.severity}"></span>${esc(x.label)}</li>`).join("")}</ul>
          </section>
          <section class="panel mini">
            <span class="panel-eyebrow"><span class="section-num">8</span> Portfolio Exposure ${exp.freshness && exp.freshness.is_stale ? `<span class="meta-chip stale">${esc(exp.freshness.label)}</span>` : ""}</span>
            ${exp.segments && exp.segments.length
              ? `<div style="display:flex;gap:8px;align-items:center;margin-top:4px">
                  ${donut(exp.segments)}
                  <div style="flex:1">
                    ${exp.segments.map((e) => `<div class="exposure-row"><span class="dot" style="background:${e.color}"></span>${esc(e.label)}<span class="exp-pct">${e.pct}%</span></div>`).join("")}
                  </div>
                </div>`
              : `<div class="empty-note" style="margin-top:8px">${esc(exp.note || "Not available yet.")}</div>`}
          </section>
          <section class="panel mini" data-goto-queue>
            <span class="panel-eyebrow"><span class="section-num">9</span> Pending Approvals</span>
            <div class="mini-big">${pa.total}</div>
            <div class="kv"><span>High Conviction</span><b style="color:var(--green)">${pa.high_conviction}</b></div>
            <div class="kv"><span>Needs Review</span><b>${pa.needs_review}</b></div>
          </section>
        </div>

      </div>
      ${tabbar("brief")}
    `;
  }

  /* ---------------- Screen B: Opportunity Detail ---------------- */
  function confidenceRows(sources) {
    return sources.map((s) => {
      const unavailable = s.score === null;
      const fillStyle = unavailable
        ? "width:100%;background:#222a36"
        : `width:${s.score}%;background:${evColor(s.score)}`;
      return `
        <div class="ev-row ${unavailable ? "ev-unavailable" : ""}">
          <span class="ev-label">${esc(s.label)}</span>
          <span class="ev-bar"><span class="ev-fill" style="${fillStyle}"></span></span>
          <span class="ev-pct">${esc(s.score_text)}</span>
        </div>
        ${unavailable && s.note ? `<div class="ev-note">${esc(s.note)}</div>` : ""}`;
    }).join("");
  }

  function historicalBlock(hs) {
    if (!hs || hs.status === "not_available") {
      return `<div class="empty-note">Historical similarity matching isn't available yet for this setup.</div>`;
    }
    return `
      ${hs.summary_text ? `<p class="why-body" style="margin-bottom:10px">${esc(hs.summary_text)}</p>` : ""}
      <div class="hist-grid">${hs.setups.map((h) => `
        <div class="hist-card">
          <div class="hist-label">${esc(h.label)}</div>
          ${sparkline([3,5,4,7,6,9,12], h.positive ? "#22c55e" : "#ef4455", 64, 24)}
          <div class="hist-ret ${h.positive ? "up" : "down"}">${esc(h.return_text)}</div>
        </div>`).join("")}</div>`;
  }

  function renderDetail() {
    // Screen B is NOT wired to live data. When the opportunity came from a live
    // Screen-A card that has no mock counterpart, show an honest placeholder
    // rather than faking detail data.
    if (state.detailPlaceholder) {
      return `
        <header class="detail-head">
          <button class="back-btn" data-goto="brief">‹ Back</button>
          <span class="spacer"></span><span class="detail-title">Opportunity</span><span class="spacer"></span>
        </header>
        <div class="content"><div class="empty-note" style="margin-top:60px">
          Live detail endpoint not implemented yet. Opportunity detail is only available in mock mode.
        </div></div>${tabbar("opp")}`;
    }
    const d = detail(state.currentOppId);
    if (!d) return `<div class="content"><div class="empty-note" style="margin-top:60px">Opportunity not found.</div></div>${tabbar("opp")}`;
    const hd = d.header, c = d.conviction, t = d.thesis, ai = d.ai_explanation;

    return `
      <header class="detail-head">
        <button class="back-btn" data-goto="brief">‹ Back</button>
        <span class="spacer"></span>
        <span class="detail-title">${esc(hd.ticker)}</span>
        <span class="spacer"></span>
        <button class="icon-btn">${ICN.star}</button>
        <button class="icon-btn">${ICN.dots}</button>
      </header>
      <div class="content" style="padding-bottom:24px">

        <div class="det-id-row">
          ${logo(hd, "")}
          <div class="det-id-meta">
            <div class="det-name">${esc(hd.name)}</div>
            <div class="det-chips">${esc(hd.ticker)} · ${hd.chips.map(esc).join(" · ")}</div>
            <div class="dir-row">Direction: <span class="badge-dir ${hd.direction === "LONG" ? "long" : "short"}">${hd.direction} ${hd.direction === "LONG" ? "↑" : "↓"}</span> &nbsp; <span class="chip">${esc(hd.strategy)}</span></div>
          </div>
          ${gauge(c.score, 78)}
        </div>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Conviction Trend (7 Days)</span><span class="view-all" style="cursor:default">${esc(c.trend_text)} ${c.trend_direction === "up" ? "↗" : c.trend_direction === "down" ? "↘" : "→"}</span></div>
          ${lineChart(c.trend_series, c.trend_labels)}
        </section>

        <section class="panel" style="padding:0">
          <div class="metrics-row">
            <div class="metric"><div class="ml">Expected Move</div><div class="mv up">${esc(c.expected_move_text)}</div></div>
            <div class="metric"><div class="ml">Risk Level</div><div class="mv" style="color:var(--amber)">${esc(c.risk_level)}</div></div>
            <div class="metric"><div class="ml">Hold Period</div><div class="mv">${esc(c.hold_period_text)}</div></div>
            <div class="metric"><div class="ml">Win Prob</div><div class="mv">${c.win_probability}%</div></div>
          </div>
        </section>

        <section class="panel">
          <div class="bullbear">
            <div class="bb-col bull"><h4>Bull Case</h4><ul class="bb-list bull">${t.bull_case.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
            <div class="bb-col bear"><h4>Bear Case</h4><ul class="bb-list bear">${t.bear_case.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Why This Matters</span></div>
          <div class="why-body">${esc(t.why_this_matters)}</div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Confidence Breakdown</span></div>
          <div class="evidence-list">${confidenceRows(d.confidence_breakdown)}</div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Supporting Evidence</span></div>
          <div class="chips-wrap">${d.supporting_evidence.map((s) => `<span class="chip">${esc(s.label)}</span>`).join("")}</div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Historical Similar Setups</span></div>
          ${historicalBlock(d.historical_setups)}
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">AI Explanation</span></div>
          <ul class="ai-list">${ai.bullets.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          <div class="prob-line">Estimated probability of success: <b>${ai.probability}%</b></div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Key Risks</span></div>
          <ul class="risk-list">${d.key_risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        </section>

        ${d.source_refs && d.source_refs.length ? `
        <section class="panel">
          <div class="panel-head"><span class="panel-eyebrow">Sources</span></div>
          <div class="chips-wrap">${d.source_refs.map((s) => `<span class="chip src">${esc(s.label)}</span>`).join("")}</div>
        </section>` : ""}

      </div>
    `;
  }

  /* ---------------- Screen C: Approval Queue ---------------- */
  function renderQueue() {
    // Screen C is NOT wired to live data. In live mode, show an honest
    // placeholder instead of mixing the mock approval cards with the live
    // pending counts from Screen A.
    if (dataMode === "live") {
      return `
        ${queueHeader(0, B.pending_approvals.total, 0)}
        <div class="queue-done">
          <div class="big">🚧</div>
          <h3>Approval queue unavailable in live mode</h3>
          <p>Live approval queue is not implemented yet. Screen A is using live briefing data only.</p>
          <button class="btn btn-explain" data-goto="brief" style="display:inline-flex;margin-top:10px">Back to Brief</button>
        </div>
        <div class="bottom-spacer"></div>
        ${tabbar("watch")}`;
    }
    const total = B.pending_approvals.total;
    const reviewed = state.queueIndex;
    const pct = Math.round((reviewed / total) * 100);
    const order = state.queueOrder;
    const idx = state.queueIndex;

    if (idx >= order.length) {
      return `
        ${queueHeader(reviewed, total, pct)}
        <div class="queue-done">
          <div class="big">🎉</div>
          <h3>Queue cleared for this batch</h3>
          <p>You reviewed ${order.length} candidates. ${total - order.length} lower-priority items remain in Needs Review.</p>
          <button class="btn btn-explain" data-goto="brief" style="display:inline-flex;margin-top:10px">Back to Brief</button>
        </div>
        <div class="bottom-spacer"></div>
        ${tabbar("watch")}`;
    }

    const cards = order.slice(idx, idx + 3).map((id, i) => {
      const d = detail(id);
      const c = d.conviction, hd = d.header;
      const find = (k) => d.confidence_breakdown.find((s) => s.key === k);
      const cls = i === 0 ? "front" : i === 1 ? "behind-1" : "behind-2";
      return `
        <div class="q-card ${cls}" data-card-idx="${i}" ${i === 0 ? `data-open-detail="${id}"` : ""}>
          <div class="q-top">
            <span class="q-dir ${hd.direction === "LONG" ? "up" : "down"}">${hd.direction}</span>
            <span class="score-big" style="font-size:20px">${c.score}<span class="den">/100</span></span>
          </div>
          <div class="q-id">${logo(hd, "")}<div><div class="q-name">${esc(hd.ticker)}</div><div class="q-sub">${esc(hd.name)}</div></div></div>
          <div>${stars(c.star_rating)}</div>
          <div class="q-metrics">
            <div class="q-metric"><div class="ml">Expected Move</div><div class="mv up">${esc(c.expected_move_text)}</div></div>
            <div class="q-metric"><div class="ml">Win Probability</div><div class="mv">${c.win_probability}%</div></div>
          </div>
          ${sparkline(c.trend_series, "#22c55e", 320, 46)}
          <div class="q-chips"><span class="chip">${esc(hd.strategy)}</span><span class="chip">${esc(c.hold_period_text)}</span></div>
          <div>
            <div class="q-reasons-title">Top Reasons</div>
            ${d.thesis.bull_case.slice(0, 3).map((rs) => `<div class="q-reason">✅ ${esc(rs)}</div>`).join("")}
          </div>
          <div class="q-mini-ev">
            <span>News <b>${find("news").score_text}</b></span>
            <span>SEC <b>${find("sec").score_text}</b></span>
            <span>Hist <b>${find("historical_similarity").score_text}</b></span>
          </div>
        </div>`;
    }).reverse().join("");

    const nextId = order[idx + 1];
    const next = nextId ? detail(nextId) : null;
    // Drive the swipe buttons from the front card's action metadata.
    const frontActions = detail(order[idx]).actions;
    const act = (name) => frontActions.find((a) => a.action === name) || { enabled: false };

    return `
      <div class="queue-screen">
        ${queueHeader(reviewed, total, pct)}
        <div class="swipe-area"><div class="swipe-stack">${cards}</div></div>
        <div class="swipe-actions">
          ${swipeBtn("reject", "Reject", "sc-reject", ICN.x, act("reject"))}
          ${swipeBtn("watchlist", "Watchlist", "sc-watch", ICN.starline, act("watchlist"))}
          ${swipeBtn("approve", "Approve", "sc-approve", ICN.check, act("approve"))}
        </div>
        ${next ? `<div class="next-up">NEXT: <b>${esc(next.header.ticker)}</b> ${esc(next.header.name)} <span class="spacer" style="flex:1"></span> ${next.conviction.score}/100</div>` : ""}
      </div>
      ${tabbar("watch")}
    `;
  }

  function swipeBtn(action, label, circleCls, icon, meta) {
    const disabled = !meta.enabled;
    return `<button class="swipe-btn ${disabled ? "disabled" : ""}" data-swipe="${action}"
      data-enabled="${meta.enabled}" data-endpoint="${meta.endpoint || ""}"
      ${meta.unavailable_reason ? `title="${esc(meta.unavailable_reason)}"` : ""}>
      <span class="swipe-circle ${circleCls}">${icon}</span>${label}</button>`;
  }

  function queueHeader(reviewed, total, pct) {
    return `
      <div class="queue-head">
        <button class="back-btn" data-goto="brief">‹</button>
        <span class="queue-title">Approval Queue ${ICN.info}</span>
        <span class="spacer"></span>
        <button class="icon-btn">${ICN.filter}</button>
      </div>
      <div class="queue-progress">
        <div class="qp-top"><span><b>${reviewed}</b> / ${total} Reviewed</span><span>${pct}%</span></div>
        <div class="qp-bar"><div class="qp-fill" style="width:${pct}%"></div></div>
      </div>`;
  }

  /* ---------------- Screen D: Explain sheet ---------------- */
  // Static illustrative talking points per source (the API note carries the
  // honest availability message; these bullets are presentation flavor).
  const SOURCE_POINTS = {
    news: ["Analyst upgrades and positive coverage in last 48h", "Partnership/contract headlines driving sentiment", "Elevated news volume vs. 30-day baseline"],
    sec: ["Recent 8-K disclosures reviewed", "No adverse insider-selling clusters detected", "Backlog/guidance language constructive"],
    options: ["Call/put ratio skewed bullish", "Unusual call sweeps near-dated", "Rising open interest at higher strikes"],
    technicals: ["Above rising 20/50-day moving averages", "Relative strength vs. sector positive", "Approaching prior resistance — watch for breakout"],
    macro: ["Regime supportive (risk-on)", "Rate path neutral-to-dovish", "Liquidity conditions stable"],
  };

  function explainSheet() {
    const d = detail(state.sheet.oppId);
    const tabs = [["ai", "AI Explanation"], ["news", "News"], ["sec", "SEC"], ["options", "Options"], ["technicals", "Techs"], ["macro", "Macro"]];
    const body = explainTabBody(d, state.sheet.tab);
    return `
      <div class="sheet-backdrop ${state.sheet.open ? "open" : ""}" data-sheet-backdrop>
        <div class="sheet" data-stop>
          <div class="sheet-grab"></div>
          <div class="sheet-head">
            ${logo(d.header, "")}
            <div style="flex:1"><div style="font-weight:800;font-size:16px">${esc(d.header.ticker)}</div><div class="tkr-sub">${esc(d.header.name)}</div></div>
            ${gauge(d.conviction.score, 64, "")}
          </div>
          <div class="tabs">
            ${tabs.map(([k, l]) => `<button class="tab-btn ${state.sheet.tab === k ? "active" : ""}" data-sheet-tab="${k}">${l}</button>`).join("")}
          </div>
          <div class="sheet-scroll">${body}</div>
          <button class="sheet-close" data-sheet-close>Close</button>
        </div>
      </div>`;
  }

  function explainTabBody(d, tab) {
    const ai = d.ai_explanation;
    if (tab === "ai") {
      return `
        <div class="sheet-section-title">AI Explanation</div>
        <p class="why-body">${esc(d.header.name)} has one of today's highest conviction scores because multiple independent signals align:</p>
        <ul class="ai-list">${ai.bullets.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <div class="prob-line">Estimated probability of success: <b>${ai.probability}%</b></div>
        <div class="sheet-section-title">Historical Insight</div>
        ${historicalBlock(d.historical_setups)}
        <div class="sheet-section-title">Follow-up Question</div>
        <div class="follow-up">
          <input placeholder="Ask AlphaLabs for more detail about this opportunity…" />
          <button class="fu-send">${ICN.send}</button>
        </div>
        <div class="disclaimer">${esc(ai.disclaimer)}</div>`;
    }
    const src = d.confidence_breakdown.find((s) => s.key === tab);
    const points = SOURCE_POINTS[tab] || [];
    const unavailable = src.score === null;
    return `
      <div class="sheet-section-title">${esc(src.label)} — ${unavailable ? "unavailable" : src.score + "% confidence"}</div>
      ${unavailable
        ? `<div class="empty-note" style="margin-bottom:14px">${esc(src.note || "Not available for this symbol.")}</div>`
        : `<div class="ev-row" style="grid-template-columns:1fr 50px;margin-bottom:14px">
            <span class="ev-bar"><span class="ev-fill" style="width:${src.score}%;background:${evColor(src.score)}"></span></span>
            <span class="ev-pct">${src.score}%</span>
          </div>
          <ul class="ai-list">${points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`}
      <div class="disclaimer">AlphaLabs AI may make mistakes. Verify before acting.</div>`;
  }

  /* ---------------- render root ---------------- */
  function render() {
    let screenHTML = "";
    if (state.screen === "brief") screenHTML = renderBrief();
    else if (state.screen === "detail") screenHTML = renderDetail();
    else if (state.screen === "queue") screenHTML = renderQueue();
    app.innerHTML = screenHTML + explainSheet() + `<div class="toast" id="toast"></div>`;
    syncProtoTabs();
  }

  function syncProtoTabs() {
    const map = { brief: "brief", detail: "detail", queue: "queue" };
    document.querySelectorAll(".proto-tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.goto === (state.sheet.open ? "explain" : map[state.screen]));
    });
  }

  let toastTimer;
  function toast(msg, kind = "") {
    const t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg; t.className = "toast show " + kind;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.className = "toast " + kind), 1500);
  }

  /* ---------------- actions (INERT — no network, no mutation) ---------------- */
  function openDetail(id) {
    state.currentOppId = id;
    state.screen = "detail";
    // In live mode, only mock idea_ids have detail data; everything else gets the
    // honest "not implemented" placeholder instead of faked detail.
    state.detailPlaceholder = dataMode === "live" && !R.get_opportunity(id);
    render();
    app.scrollTop = 0;
  }
  function openSheet(id) { state.sheet.oppId = id; state.sheet.open = true; state.sheet.tab = "ai"; render(); }
  function closeSheet() { state.sheet.open = false; render(); }

  // Logs the endpoint the real app WOULD call; performs no request.
  function decide(action, id, endpoint) {
    const d = detail(id);
    const tkr = d ? d.header.ticker : id;
    // eslint-disable-next-line no-console
    console.log(`[review.v1 mock] ${action} ${tkr} → would POST ${endpoint || "(no endpoint)"} (inert: no request sent)`);
    const labels = { approve: ["✓ Approved " + tkr + " (mock)", ""], reject: ["✗ Rejected " + tkr + " (mock)", "reject"], watchlist: ["☆ Watchlist " + tkr + " (mock)", "watch"] };
    const [msg, kind] = labels[action] || ["", ""];
    toast(msg, kind);
  }

  function advanceQueue(action, endpoint) {
    const id = state.queueOrder[state.queueIndex];
    const front = app.querySelector(".q-card.front");
    if (front) front.classList.add(action === "reject" ? "leaving-left" : action === "watchlist" ? "leaving-up" : "leaving-right");
    decide(action, id, endpoint);
    setTimeout(() => { state.queueIndex++; render(); }, 320);
  }

  /* ---------------- events ---------------- */
  document.addEventListener("click", (e) => {
    // prototype top switcher
    const proto = e.target.closest(".proto-tab");
    if (proto) {
      const g = proto.dataset.goto;
      if (g === "explain") { state.screen = "detail"; openSheet(state.currentOppId); }
      else { state.sheet.open = false; state.screen = g === "detail" ? "detail" : g === "queue" ? "queue" : "brief"; render(); app.scrollTop = 0; }
      return;
    }

    // sheet interactions
    if (e.target.closest("[data-sheet-close]")) return closeSheet();
    const sheetTab = e.target.closest("[data-sheet-tab]");
    if (sheetTab) { state.sheet.tab = sheetTab.dataset.sheetTab; render(); return; }
    if (e.target.closest("[data-sheet-backdrop]") && !e.target.closest("[data-stop]")) return closeSheet();

    // swipe buttons (Approval screen) — read action metadata, stay inert
    const sw = e.target.closest("[data-swipe]");
    if (sw) {
      const enabled = sw.dataset.enabled === "true";
      const action = sw.dataset.swipe;
      if (!enabled) {
        // eslint-disable-next-line no-console
        console.warn(`[review.v1 mock] ${action} is disabled (action.enabled=false) — no endpoint yet`);
        toast(action + " unavailable", "");
        return;
      }
      advanceQueue(action, sw.dataset.endpoint);
      return;
    }

    // nav: bottom tabbar
    const tab = e.target.closest("[data-tab]");
    if (tab) {
      const k = tab.dataset.tab;
      if (k === "brief") { state.screen = "brief"; render(); app.scrollTop = 0; }
      else if (k === "watch") { state.screen = "queue"; render(); app.scrollTop = 0; }
      else if (k === "opp") { openDetail(state.currentOppId); }
      else toast("'" + k + "' not in prototype");
      return;
    }

    // goto handlers
    const goto = e.target.closest("[data-goto]");
    if (goto) { state.screen = goto.dataset.goto; render(); app.scrollTop = 0; return; }
    if (e.target.closest("[data-goto-queue]")) { state.screen = "queue"; render(); app.scrollTop = 0; return; }

    // open detail (cards / rows)
    const od = e.target.closest("[data-open-detail]");
    if (od && !e.target.closest("[data-stop]")) { openDetail(Number(od.dataset.openDetail)); return; }
  });

  // Bootstrap: mock by default. In live mode, paint mock immediately (never a
  // blank screen), then attempt the read-only GET and swap in validated live
  // data — or fall back to mock with a visible warning on any failure.
  async function boot() {
    if (parseDataMode() !== "live") { dataMode = "mock"; B = R.briefing; render(); return; }
    render(); // immediate mock paint while the fetch is in flight
    try {
      const payload = await loadLiveBriefing();
      const problem = validateBriefing(payload);
      if (problem) throw new Error(problem);
      B = payload; dataMode = "live"; dataWarning = "";
    } catch (err) {
      B = R.briefing; dataMode = "mock";
      dataWarning = "Live data unavailable (" + (err && err.message ? err.message : "fetch failed") + ") — showing mock data.";
    }
    render();
  }
  boot();
})();
