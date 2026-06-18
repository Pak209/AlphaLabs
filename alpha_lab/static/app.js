let state = {
  dashboard: null,
  ideas: [],
  trades: [],
  stats: [],
  bitcoin: null,
  afterHoursBtc: null,
  liquidity: null,
  trendingStocks: null,
  oil: null,
  futuresPulse: null,
  businessProfiles: null,
  catalysts: null,
  catalystIntelligence: null,
  dailyBrief: null,
  briefings: [],
  executionAudit: [],
  performanceReport: null,
  approvalQueue: [],
  approvalsLoading: false,
  approvalsError: "",
};
let activeRoute = "overview";

function getApiToken() {
  return localStorage.getItem("alphalab_api_token") || "";
}

function setApiToken(value) {
  const token = String(value || "").trim();
  if (token) localStorage.setItem("alphalab_api_token", token);
  else localStorage.removeItem("alphalab_api_token");
  renderTokenStatus();
}

function promptForApiToken() {
  const entered = window.prompt("This AlphaLab server requires an API token for actions (approvals, chat, tests). Paste it to continue:");
  if (entered && entered.trim()) {
    setApiToken(entered.trim());
    return true;
  }
  return false;
}

function renderTokenStatus() {
  const target = document.querySelector("#token-status");
  if (!target) return;
  const token = getApiToken();
  if (token) {
    const masked = token.length > 8 ? `${token.slice(0, 4)}…${token.slice(-4)}` : "set";
    target.className = "token-status set";
    target.innerHTML = `<strong>Token saved on this device</strong> <span class="muted">(${masked})</span>`;
  } else {
    target.className = "token-status unset";
    target.innerHTML = `<strong>No token saved.</strong> <span class="muted">Actions will prompt for one if the server requires it.</span>`;
  }
}

async function testApiToken() {
  // A token-less write returns 401 only when the server has a token configured.
  // We probe with a harmless POST and report what the gate did.
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify({ probe: true }) });
    showToast("Action token accepted — remote approvals will work from this device.");
  } catch (err) {
    showToast(`Token test failed: ${cleanErrorMessage(err.message || String(err))}`);
  }
}

async function api(path, options = {}, retrying = false) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = getApiToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && !retrying) {
    // Token missing/invalid for a mutating call — prompt once and retry.
    if (promptForApiToken()) return api(path, options, true);
  }
  if (!res.ok) {
    let message = await res.text();
    try {
      const parsed = JSON.parse(message);
      message = parsed.detail || parsed.message || message;
    } catch (_) {}
    throw new Error(cleanErrorMessage(message));
  }
  return res.json();
}

function cleanErrorMessage(message) {
  const text = String(message || "Unknown error");
  if (text.includes("paper-api.alpaca.markets") && text.toLowerCase().includes("blocked")) {
    return "Alpaca paper endpoint is blocked by the current network policy; no paper order was placed.";
  }
  return text.split("\n")[0].slice(0, 240);
}

async function load() {
  const refresh = document.querySelector("#refresh");
  if (refresh) refresh.textContent = "Refreshing...";
  const [dashboard, ideas, trades, stats, bitcoin, afterHoursBtc, liquidity, trendingStocks, oil, futuresPulse, businessProfiles, catalysts, catalystIntelligence, dailyBrief, briefings, executionAudit, performanceReport, approvalResult] = await Promise.all([
    api("/api/dashboard"),
    api("/api/ideas"),
    api("/api/trades"),
    api("/api/stats/strategies"),
    api("/api/market/bitcoin"),
    api("/api/after-hours/btc"),
    api("/api/market/liquidity"),
    api("/api/market/trending-stocks"),
    api("/api/market/oil"),
    api("/api/futures/pulse"),
    api("/api/business-profiles"),
    api("/api/catalysts/radar"),
    api("/api/catalysts/intelligence"),
    api("/api/brief/daily"),
    api("/api/briefings"),
    api("/api/execution-audit"),
    api("/api/performance/report"),
    loadApprovalQueueResult(),
  ]);
  state = {
    dashboard,
    ideas,
    trades,
    stats,
    bitcoin,
    afterHoursBtc,
    liquidity,
    trendingStocks,
    oil,
    futuresPulse,
    businessProfiles,
    catalysts,
    catalystIntelligence,
    dailyBrief,
    briefings,
    executionAudit,
    performanceReport,
    approvalQueue: approvalResult.data,
    approvalsLoading: false,
    approvalsError: approvalResult.error,
  };
  render();
  if (refresh) refresh.textContent = `Refreshed ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
}

async function loadApprovalQueueResult() {
  try {
    return { data: await api("/api/ideas/pending-approval"), error: "" };
  } catch (err) {
    return { data: [], error: cleanErrorMessage(err.message || err) };
  }
}

function render() {
  renderOverview();
  renderIdeas();
  renderStats();
  renderInboxSnapshot();
  renderBitcoinInsight();
  renderAfterHoursBtc();
  renderStrategyCandidates();
  renderLiquidityFlows();
  renderTrendingStocks();
  renderTrendingTokens();
  renderOilInsight();
  renderFuturesPulse();
  renderBusinessProfiles();
  renderCatalystRadar();
  renderDailyBrief();
  renderApprovalQueue();
  renderExecutionAudit();
  renderPerformance();
  renderSavedBriefings();
  renderNav();
  renderPage();
}

// ---- Overview / Alpha Command Center ----------------------------------------
// The Overview is a strategic dashboard, not a transaction log. Every figure
// below is real (from the performance report, daily brief, futures pulse,
// liquidity feed, and dashboard health) — nothing is mocked. When a data source
// has no signal yet, the card renders an honest "accumulating/unknown" state.
function renderOverview() {
  renderOverviewIQ();
  renderOverviewRegime();
  renderOverviewOpportunities();
  renderOverviewSources();
  renderOverviewStatus();
}

// Color band for a 0-100 score: green strong, amber middling, red weak.
function scoreTone(score) {
  if (score === null || score === undefined) return "tone-none";
  if (score >= 70) return "tone-good";
  if (score >= 40) return "tone-mid";
  return "tone-bad";
}

// SVG donut gauge for the AlphaLabs IQ score (0-100).
function iqGaugeSvg(score) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pctFill = score === null || score === undefined ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const dash = `${(pctFill * c).toFixed(1)} ${c.toFixed(1)}`;
  const tone = scoreTone(score);
  const label = score === null || score === undefined ? "—" : score;
  return `
    <svg class="iq-gauge ${tone}" viewBox="0 0 120 120" role="img" aria-label="AlphaLabs IQ ${label} of 100">
      <circle class="iq-gauge-track" cx="60" cy="60" r="${r}" fill="none" stroke-width="10" />
      <circle class="iq-gauge-fill" cx="60" cy="60" r="${r}" fill="none" stroke-width="10"
              stroke-dasharray="${dash}" stroke-linecap="round" transform="rotate(-90 60 60)" />
      <text class="iq-gauge-score" x="60" y="58" text-anchor="middle">${label}</text>
      <text class="iq-gauge-sub" x="60" y="76" text-anchor="middle">/ 100</text>
    </svg>`;
}

function renderOverviewIQ() {
  const target = document.querySelector("#overview-iq");
  if (!target) return;
  const report = state.performanceReport || {};
  const iq = report.alpha_iq || {};
  const card = report.report_card || {};
  const graded = (report.source_leaderboard || []).filter((g) => g.score !== null && g.score !== undefined);
  const best = graded.length ? graded.reduce((a, b) => (b.score > a.score ? b : a)) : null;
  const worst = graded.length ? graded.reduce((a, b) => (b.score < a.score ? b : a)) : null;
  const stats = [
    ["Signals", card.total_signals ?? 0],
    ["Win rate", card.executed_signals ? pct(card.win_rate) : "—"],
    ["Avg move", card.executed_signals ? signedPct(card.avg_return) : "—"],
  ];
  target.innerHTML = `
    <div class="panel-head"><h2>AlphaLabs IQ</h2><span class="badge ${scoreTone(iq.score)}">${iq.label || "Accumulating"}</span></div>
    <div class="iq-hero">
      <div class="iq-gauge-wrap">${iqGaugeSvg(iq.score)}</div>
      <div class="iq-hero-stats">
        ${stats.map(([k, v]) => `<div class="iq-stat"><span>${k}</span><strong>${v}</strong></div>`).join("")}
      </div>
    </div>
    <div class="iq-sources">
      <div class="iq-source-pill good">
        <span>Best source</span>
        <strong>${best ? best.name : "—"}</strong>
        <em>${best ? `${best.grade} · ${num(best.score)}` : "accumulating"}</em>
      </div>
      <div class="iq-source-pill bad">
        <span>Worst source</span>
        <strong>${worst ? worst.name : "—"}</strong>
        <em>${worst ? `${worst.grade} · ${num(worst.score)}` : "accumulating"}</em>
      </div>
    </div>`;
}

// Map the daily-brief posture / futures regime to a RISK ON / OFF / MIXED banner.
function riskBanner(posture, futuresRegime) {
  const p = String(posture || "").toLowerCase();
  if (p.includes("risk-on") || p.includes("risk on")) return { label: "RISK ON", tone: "tone-good" };
  if (p.includes("defensive") || p.includes("risk-off") || p.includes("risk off")) return { label: "RISK OFF", tone: "tone-bad" };
  if (p.includes("mixed")) return { label: "MIXED", tone: "tone-mid" };
  const fr = String(futuresRegime || "").toLowerCase();
  if (fr.includes("risk_on")) return { label: "RISK ON", tone: "tone-good" };
  if (fr.includes("risk_off") || fr.includes("safe_haven")) return { label: "RISK OFF", tone: "tone-bad" };
  return { label: "UNKNOWN", tone: "tone-none" };
}

function renderOverviewRegime() {
  const target = document.querySelector("#overview-regime");
  if (!target) return;
  const brief = state.dailyBrief || {};
  const regime = brief.regime || {};
  const fut = (state.futuresPulse || {}).regime || {};
  const liqGroups = (state.liquidity || {}).groups || [];
  const okGroups = liqGroups.filter((g) => g.status === "ok");
  const positiveFlow = okGroups.filter((g) => {
    const v = g.weighted_change_24h_pct ?? g.volume_vs_5d_avg_pct;
    return typeof v === "number" && v > 0;
  }).length;
  let liquidityRead = "Unknown";
  if (okGroups.length) {
    const ratio = positiveFlow / okGroups.length;
    liquidityRead = ratio >= 0.6 ? "Expanding" : ratio <= 0.34 ? "Contracting" : "Mixed";
  }
  const banner = riskBanner(regime.posture, fut.regime);
  const futConf = Number(fut.confidence || 0);
  const rows = [
    ["Posture", regime.posture || "unknown", regimeTone(regime.posture)],
    ["Overnight Futures", fut.label ? `${fut.label}${futConf ? ` · ${futConf.toFixed(0)}` : ""}` : "no read", regimeTone(fut.regime)],
    ["BTC Bias", regime.btc_bias || "unknown", biasTone(regime.btc_bias)],
    ["Liquidity", okGroups.length ? `${liquidityRead} (${positiveFlow}/${okGroups.length})` : "unknown", liquidityRead === "Expanding" ? "tone-good" : liquidityRead === "Contracting" ? "tone-bad" : "tone-mid"],
    ["Setups", `${regime.bullish_setups ?? 0} bull / ${regime.bearish_setups ?? 0} bear`, ""],
  ];
  target.innerHTML = `
    <div class="panel-head"><h2>Market Regime</h2><span class="muted">${brief.status === "ok" ? "live" : "accumulating"}</span></div>
    <div class="regime-banner ${banner.tone}">
      <strong>${banner.label}</strong>
      <span>Risk level</span>
    </div>
    <div class="regime-rows">
      ${rows.map(([k, v, tone]) => `<div class="regime-row"><span>${k}</span><strong class="${tone || ""}">${v}</strong></div>`).join("")}
    </div>`;
}

function regimeTone(value) {
  const v = String(value || "").toLowerCase();
  if (v.includes("risk-on") || v.includes("risk_on")) return "tone-good";
  if (v.includes("defensive") || v.includes("risk_off") || v.includes("safe_haven")) return "tone-bad";
  return "tone-mid";
}

function biasTone(value) {
  const v = String(value || "").toLowerCase();
  if (v === "bullish") return "tone-good";
  if (v === "bearish") return "tone-bad";
  return "tone-mid";
}

// Confidence (0-1) -> presentational grade for the opportunity rank.
function confidenceGrade(confidence) {
  const c = Number(confidence);
  if (!Number.isFinite(c)) return "—";
  if (c >= 0.8) return "A";
  if (c >= 0.65) return "B";
  if (c >= 0.5) return "C";
  if (c >= 0.35) return "D";
  return "F";
}

function renderOverviewOpportunities() {
  const target = document.querySelector("#overview-opportunities");
  if (!target) return;
  const ideas = (state.ideas || [])
    .filter((idea) => idea.status !== "rejected")
    .slice()
    .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))
    .slice(0, 5);
  if (!ideas.length) {
    target.innerHTML = `<div class="row">No open opportunities. Run a scan or add an idea to populate this feed.</div>`;
    return;
  }
  target.innerHTML = ideas.map((idea, i) => {
    const grade = confidenceGrade(idea.confidence);
    const tags = (idea.strategies || []).slice(0, 3).map((t) => `<span class="chip">${t}</span>`).join("");
    const conf = Math.round(Number(idea.confidence || 0) * 100);
    return `
      <div class="opp-row">
        <span class="opp-rank">${i + 1}</span>
        <div class="opp-main">
          <div class="opp-head">
            <strong>${idea.ticker}</strong>
            <span class="${idea.bias}">${idea.bias}</span>
          </div>
          <div class="opp-tags">${tags || `<span class="chip">${idea.theme || idea.source || "untagged"}</span>`}</div>
        </div>
        <div class="opp-meta">
          <span class="muted" title="Confidence (0-100)">Conf ${conf}</span>
          <span class="grade-badge sm ${gradeClass(grade)}" title="Confidence grade">${grade}</span>
        </div>
      </div>`;
  }).join("");
}

function renderOverviewSources() {
  const target = document.querySelector("#overview-sources");
  if (!target) return;
  const board = (state.performanceReport || {}).source_leaderboard || [];
  const graded = board.filter((g) => g.score !== null && g.score !== undefined).sort((a, b) => b.score - a.score);
  const groups = (graded.length ? graded : board).slice(0, 5);
  renderLeaderboard(target, groups, "No graded sources yet — accumulating as paper trades resolve.");
}

function renderOverviewStatus() {
  const target = document.querySelector("#overview-status");
  if (!target) return;
  const dash = state.dashboard || {};
  const dataLive = (state.bitcoin || {}).status === "ok"
    || ((state.liquidity || {}).groups || []).some((g) => g.status === "ok");
  const items = [
    ["Server", dash.counts || dash.mode ? "Online" : "Unknown", dash.counts || dash.mode ? "ok" : "warn"],
    ["Account", dash.account_error ? "Error" : "Connected", dash.account_error ? "bad" : "ok"],
    ["Paper Mode", "Active", "ok"],
    ["Dry Run", "Default", "ok"],
    ["Data Feed", dataLive ? "Live" : "Degraded", dataLive ? "ok" : "warn"],
  ];
  target.innerHTML = items.map(([k, v, s]) => `
    <div class="status-pill status-${s}">
      <span class="status-dot"></span>
      <div><span>${k}</span><strong>${v}</strong></div>
    </div>`).join("");
}

function renderIdeas() {
  const filter = document.querySelector("#filter").value.toLowerCase();
  const ideas = state.ideas.filter((idea) => JSON.stringify(idea).toLowerCase().includes(filter));
  document.querySelector("#ideas").innerHTML = ideas.map((idea) => `
    <tr>
      <td><strong>${idea.ticker}</strong><div>${idea.theme || idea.sector || ""}</div></td>
      <td class="${idea.bias}">${idea.bias}</td>
      <td>${Number(idea.confidence).toFixed(2)}</td>
      <td>${(idea.strategies || []).map((s) => `<span class="badge">${s}</span>`).join("")}</td>
      <td class="status-${idea.status}">${ideaStatusLabel(idea.status)}</td>
      <td>${idea.thesis}${businessBriefHtml(idea.business_brief)}<div class="muted">${idea.rejection_reason || ""}</div></td>
      <td><div class="actions">
        <button class="secondary" onclick="decision(${idea.id})">Decision</button>
        <button onclick="dryRun(${idea.id})">Dry Run</button>
        <button class="paper" onclick="paperTrade(${idea.id}, '${idea.ticker}')">Paper</button>
        <button class="danger" onclick="rejectIdea(${idea.id})">Reject</button>
      </div></td>
    </tr>
  `).join("");
}

function renderBitcoinInsight() {
  const target = document.querySelector("#bitcoin-insight");
  const btc = state.bitcoin || {};
  if (btc.status !== "ok") {
    target.innerHTML = `<div class="row">Live Bitcoin data unavailable. Source: ${btc.source || "CoinGecko"}. ${btc.error || "No error detail returned."}</div>`;
    return;
  }
  target.innerHTML = `
    <div class="btc-symbol"><strong>BTC/USD</strong><span class="${btc.bias}">${btc.bias}</span><span>${money(btc.price)}</span></div>
    <div class="btc-metrics">
      <span>24h ${signedPct(btc.change_24h_pct)}</span>
      <span>7d ${signedPct(btc.change_7d_pct)}</span>
      <span>14d ${signedPct(btc.change_14d_pct)}</span>
      <span>RSI(14) ${num(btc.indicators?.rsi14)}</span>
      <span>20D EMA ${money(btc.indicators?.ema20)}</span>
      <span>50D EMA ${money(btc.indicators?.ema50)}</span>
      <span>Vol ${moneyCompact(btc.volume_24h)}</span>
    </div>
    <p>${btc.summary}</p>
    <p>${btc.indicators?.ema_read || "EMA read unavailable."}</p>
    <div class="scenario-list">${(btc.scenarios || []).map((s) => `<div class="scenario"><strong>${s.name}</strong><span>${s.setup}</span><span class="muted">${s.watch}</span></div>`).join("")}</div>
    <div class="muted">Source: ${btc.source} · last updated ${formatTime(btc.last_updated)} · fetched ${formatTime(btc.fetched_at)}</div>
    <div class="muted">${(btc.data_limits || []).join(" ")}</div>
  `;
}

function renderAfterHoursBtc() {
  const target = document.querySelector("#after-hours-btc");
  if (!target) return;
  const payload = state.afterHoursBtc || {};
  const btc = payload.current_btc_thesis || {};
  if (payload.status !== "ok" || btc.status !== "ok") {
    target.innerHTML = `<div class="row">After-hours BTC data unavailable. ${payload.error || btc.error || "No details returned."}</div>`;
    return;
  }
  const risk = payload.risk_status || {};
  const approvals = payload.approval_status || {};
  const flow = payload.crypto_flow || {};
  target.innerHTML = `
    <div class="stock-head">
      <strong>BTC/USD</strong>
      <span class="${btc.bias}">${btc.bias}</span>
      <span>${money(btc.price)}</span>
      <button class="secondary" id="generate-btc-idea">Generate BTC Idea</button>
    </div>
    <p>${btc.summary}</p>
    <div class="btc-metrics">
      <span>24h ${signedPct(btc.change_24h_pct)}</span>
      <span>7d ${signedPct(btc.change_7d_pct)}</span>
      <span>Vol ${moneyCompact(btc.volume_24h)}</span>
      <span>RSI ${num(btc.indicators?.rsi14)}</span>
      <span>Support ${money(btc.indicators?.support_14d_close)}</span>
      <span>Resistance ${money(btc.indicators?.resistance_14d_close)}</span>
    </div>
    <div class="scenario-list">${(btc.scenarios || []).slice(0, 3).map((s) => `<div class="scenario"><strong>${s.name}</strong><span>${s.setup}</span><span class="muted">${s.watch}</span></div>`).join("")}</div>
    <div class="approval-section"><strong>Pending BTC/Crypto Ideas</strong><div class="driver-list">${(payload.pending_crypto_ideas || []).slice(0, 8).map((idea) => `<span>${idea.ticker} ${idea.status}</span>`).join("") || "<span>none</span>"}</div></div>
    <div class="btc-metrics">
      <span>Approval pending ${approvals.pending || 0}</span>
      <span>Approved ${approvals.approved || 0}</span>
      <span>Crypto max/day ${risk.max_trades_per_day || "n/a"}</span>
      <span>Max size ${money(risk.max_position_size_usd)}</span>
      <span>Max DD ${pct(risk.max_daily_drawdown_pct || 0)}</span>
    </div>
    <div class="muted">${payload.market_hours_note}</div>
    <div class="muted">Crypto flow: ${flow.volume_read || "n/a"} · ${flow.source || "source unavailable"}</div>
  `;
  const button = document.querySelector("#generate-btc-idea");
  if (button) button.addEventListener("click", () => generateBtcIdea().catch(showError));
}

function ideaStatusLabel(status) {
  if (status === "tested") return "dry-run tested";
  if (status === "traded") return "paper traded";
  return status || "unknown";
}

function renderLiquidityFlows() {
  const target = document.querySelector("#liquidity-flows");
  const payload = state.liquidity || {};
  const groups = payload.groups || [];
  if (!groups.length) {
    target.innerHTML = `<div class="row">Liquidity flow data unavailable. ${payload.error || "No details returned."}</div>`;
    return;
  }
  target.innerHTML = groups.map((group) => {
    const why = liquidityExplain(group);
    return `
    <div class="flow-card ${group.status !== "ok" ? "flow-unavailable" : ""}">
      <div><strong>${group.name}</strong><span class="badge">${group.status}</span></div>
      <div class="flow-read">${group.volume_read || group.error || "No read"}</div>
      <div class="btc-metrics">
        <span>Dollar vol ${moneyCompact(group.dollar_volume)}</span>
        <span>Vs avg ${signedPct(group.volume_vs_5d_avg_pct)}</span>
        <span>24h basket ${signedPct(group.weighted_change_24h_pct)}</span>
      </div>
      <div class="mini-assets">${(group.assets || []).slice(0, 4).map((asset) => `<span>${asset.symbol}: ${moneyCompact(asset.dollar_volume || asset.volume_24h)} ${asset.volume_vs_5d_avg_pct !== undefined ? signedPct(asset.volume_vs_5d_avg_pct) : signedPct(asset.change_24h_pct)}</span>`).join("")}</div>
      ${why ? `<div class="flow-why">${why}</div>` : ""}
      <div class="muted flow-source">${shortSource(group.source) || group.error || ""}</div>
    </div>
  `;
  }).join("");
}

// Build a concise, data-derived read of what is driving a liquidity group's
// flow from the assets we already have (no extra API calls). Stock groups are
// summarized by volume-vs-average breadth and standouts; crypto by 24h move.
function liquidityExplain(group) {
  const assets = (group && group.assets) || [];
  if (!assets.length) return "";
  const byMoney = [...assets].sort((a, b) => (b.dollar_volume || b.volume_24h || 0) - (a.dollar_volume || a.volume_24h || 0));
  const heaviest = byMoney[0];
  const withVol = assets.filter((a) => a.volume_vs_5d_avg_pct !== undefined && a.volume_vs_5d_avg_pct !== null);
  if (withVol.length) {
    const ranked = [...withVol].sort((a, b) => b.volume_vs_5d_avg_pct - a.volume_vs_5d_avg_pct);
    const up = withVol.filter((a) => a.volume_vs_5d_avg_pct > 0).length;
    const top = ranked[0];
    const bottom = ranked[ranked.length - 1];
    const parts = [`${up}/${withVol.length} names trading heavier than their 5-day norm`];
    if (top) parts.push(`${top.symbol} most active (${signedPct(top.volume_vs_5d_avg_pct)})`);
    if (bottom && bottom !== top) parts.push(`${bottom.symbol} quietest (${signedPct(bottom.volume_vs_5d_avg_pct)})`);
    if (heaviest) parts.push(`heaviest: ${heaviest.symbol} ${moneyCompact(heaviest.dollar_volume)}`);
    return parts.join(" · ");
  }
  const withChg = assets.filter((a) => a.change_24h_pct !== undefined && a.change_24h_pct !== null);
  if (withChg.length) {
    const ranked = [...withChg].sort((a, b) => b.change_24h_pct - a.change_24h_pct);
    const leader = ranked[0];
    const laggard = ranked[ranked.length - 1];
    const parts = [];
    if (leader) parts.push(`${leader.symbol} leads 24h (${signedPct(leader.change_24h_pct)})`);
    if (laggard && laggard !== leader) parts.push(`${laggard.symbol} lags (${signedPct(laggard.change_24h_pct)})`);
    if (heaviest) parts.push(`most traded: ${heaviest.symbol} ${moneyCompact(heaviest.volume_24h)}`);
    return parts.join(" · ");
  }
  return "";
}

// Compact provenance label instead of the verbose upstream source string.
function shortSource(source) {
  if (!source) return "";
  if (source.includes("Alpaca")) return "via Alpaca IEX daily bars";
  if (source.includes("CoinGecko")) return "via CoinGecko";
  return source;
}


function renderTrendingStocks() {
  const target = document.querySelector("#trending-stocks");
  const payload = state.trendingStocks || {};
  const stocks = payload.stocks || [];
  if (!stocks.length) {
    target.innerHTML = `<div class="row">Trending stock liquidity is unavailable. ${payload.error || "No details returned."}</div>`;
    return;
  }
  target.innerHTML = stocks.map((stock) => {
    const candidate = stock.strategy_candidate || {};
    const scenario = stock.scenario || {};
    return `
      <div class="stock-card">
        <div class="stock-head"><strong>${stock.ticker}</strong><span class="${stock.bias}">${stock.bias}</span><span>${money(stock.price)}</span></div>
        <div class="setup-line ${candidate.actionable ? "actionable" : "watch"}">${stock.indicators?.setup_label || "No clear setup"}${candidate.actionable ? " · paper-test candidate" : " · watch only"}</div>
        <div class="btc-metrics">
          <span>Setup score ${Number(stock.score || 0).toFixed(1)}</span>
          <span>Dollar vol ${moneyCompact(stock.dollar_volume)}</span>
          <span>Vs avg ${signedPct(stock.volume_vs_5d_avg_pct)}</span>
          <span>5D ${signedPct(stock.change_5d_pct)}</span>
          <span>RSI ${num(stock.indicators?.rsi14)}</span>
          <span>20D EMA ${money(stock.indicators?.ema20)}</span>
          <span>Support ${money(stock.indicators?.setup?.levels?.support)}</span>
          <span>Resistance ${money(stock.indicators?.setup?.levels?.resistance)}</span>
        </div>
        <p>${scenario.setup || "No scenario detail."}</p>
        ${businessBriefHtml(stock.business_brief)}
        <div class="muted">${scenario.watch || "Watch for confirmation before testing."}</div>
        <div class="strategy-mini"><strong>${candidate.name || "No clean strategy"}</strong><span>${candidate.reason || "Candidate did not meet strategy thresholds."}</span><span class="muted">Trigger: ${candidate.trigger || "n/a"}</span><span class="muted">Invalidation: ${candidate.invalidation || "n/a"}</span></div>
      </div>
    `;
  }).join("");
  const source = document.querySelector("#trending-source");
  if (source) source.textContent = `${payload.source || "unknown source"} · fetched ${formatTime(payload.fetched_at)} · ${payload.source_note || ""}`;
}


function businessBriefHtml(brief) {
  if (!brief || !brief.business) return "";
  const drivers = (brief.drivers || []).map((driver) => `<span>${driver}</span>`).join("");
  const fundamentals = brief.fundamentals || {};
  const metrics = (fundamentals.key_metrics || []).map((metric) => `<span>${metric}</span>`).join("");
  return `
    <div class="business-brief">
      <strong>${brief.name || "Business brief"}</strong>
      <p>${brief.business}</p>
      ${drivers ? `<div class="driver-list">${drivers}</div>` : ""}
      ${fundamentals.model ? `<div class="muted"><strong>Fundamentals:</strong> ${fundamentals.model}</div>` : ""}
      ${metrics ? `<div class="driver-list">${metrics}</div>` : ""}
      <div class="muted">${brief.watch || ""}</div>
    </div>
  `;
}

async function testTrendingStrategies(dryRun) {
  const label = dryRun ? "dry-run test" : "Alpaca PAPER trade test";
  if (!dryRun) {
    const ok = confirm("Send top trending strategy candidates to Alpaca PAPER trading? This will use the paper endpoint only and still obey risk rules.");
    if (!ok) return;
  }
  const button = document.querySelector(dryRun ? "#test-trending-dry" : "#test-trending-paper");
  button.textContent = dryRun ? "Dry-running..." : "Paper testing...";
  const result = await api("/api/strategies/test-trending", { method: "POST", body: JSON.stringify({ dry_run: dryRun, limit: 3 }) });
  button.textContent = dryRun ? "Dry-Run Trending Strategies" : "Paper-Test Trending Strategies";
  showToast(`${label}: ${result.signals_created || 0} candidates created. Check inbox/trades for decisions.`);
  await load();
}


function renderTrendingTokens() {
  const target = document.querySelector("#trending-tokens");
  const crypto = (state.liquidity?.groups || []).find((group) => group.name === "Crypto Majors");
  const assets = crypto?.assets || [];
  if (!assets.length) {
    target.innerHTML = `<div class="row">Token liquidity data unavailable.</div>`;
    return;
  }
  target.innerHTML = assets.slice(0, 8).map((asset) => `
    <div class="token-card">
      <div class="stock-head"><strong>${asset.symbol}</strong><span>${asset.name || ""}</span></div>
      <div class="btc-metrics">
        <span>Price ${money(asset.price)}</span>
        <span>24h ${signedPct(asset.change_24h_pct)}</span>
        <span>7d ${signedPct(asset.change_7d_pct)}</span>
        <span>Vol ${moneyCompact(asset.volume_24h)}</span>
      </div>
    </div>
  `).join("");
}

const PAGE_META = {
  overview: ["Overview", "Alpha command center: system IQ, market regime, top opportunities, and source effectiveness at a glance."],
  liquidity: ["Liquidity", "Sector, crypto, Bitcoin, and oil/energy liquidity proxies without full order-flow claims."],
  futures: ["Futures Pulse", "Overnight Futures Pulse — premarket macro regime read from overnight futures. Read-only research."],
  catalysts: ["Catalyst Radar", "FoxRunner-style news catalyst scanning: source, keywords, score, then risk-checked paper tests."],
  trending: ["Trending Stocks/Tokens", "Live watchlists for where attention and dollar volume are showing up."],
  business: ["Business/Fundamentals", "What each company or ETF does, what drives it, and what fundamental metrics matter."],
  strategies: ["Strategies", "Hypotheses, indicator scenarios, and paper-trade performance tracking."],
  approvals: ["Approvals", "Human review queue for LLM-assisted ideas before Alpaca paper execution."],
  performance: ["Performance", "Alpha Report Card: signal quality, source effectiveness, and regime performance — paper-trading research only."],
  briefings: ["Briefings", "Saved daily market research briefings and generated context."],
  paper: ["Paper / Dry-Run Log", "Dry-run tests, Alpaca paper actions, rejections, and blocked moves."],
  inbox: ["Scanner Inbox", "Incoming automation ideas plus manual alpha entry."],
  chat: ["Analyst Chat", "Discuss market events, catalysts, ideas, and strategies. Advisory only — no trade execution."],
  settings: ["Settings", "Configure this device for remote actions over Tailscale."],
};

function setRoute(route, updateHash = true) {
  activeRoute = PAGE_META[route] ? route : "overview";
  if (updateHash && window.location.hash !== `#${activeRoute}`) {
    history.replaceState(null, "", `#${activeRoute}`);
  }
  renderPage();
}

// ---- Sidebar navigation (data-driven) ---------------------------------------
// Navigation is defined as data so new scanners/agents can be added without
// touching the rendering logic below. Each section is a collapsible group; the
// `Approvals` item only appears (with a count badge on its group) while there
// are pending approvals waiting for review.
const NAV_SECTIONS = [
  {
    id: "research",
    title: "Research",
    defaultCollapsed: false,
    items: [
      { route: "overview", label: "Overview" },
      { route: "inbox", label: "Scanner Inbox" },
      { route: "chat", label: "Analyst Chat" },
    ],
  },
  {
    id: "market",
    title: "Market Intelligence",
    defaultCollapsed: false,
    items: [
      { route: "liquidity", label: "Liquidity" },
      { route: "futures", label: "Futures Pulse" },
      { route: "catalysts", label: "Catalyst Radar" },
      { route: "trending", label: "Trending Stocks/Tokens" },
      { route: "business", label: "Business/Fundamentals" },
    ],
  },
  {
    id: "trading",
    title: "Trading",
    defaultCollapsed: false,
    badge: "approvals",
    items: [
      { route: "strategies", label: "Strategies" },
      { route: "paper", label: "Paper / Dry-Run Log" },
      { route: "performance", label: "Performance" },
      { route: "approvals", label: "Approvals", conditional: "approvals" },
    ],
  },
  {
    id: "system",
    title: "System",
    defaultCollapsed: true,
    items: [
      { route: "briefings", label: "Briefings" },
      { route: "settings", label: "Settings" },
    ],
  },
];

const NAV_COLLAPSE_KEY = "alphalab_nav_collapsed";

function isMobileViewport() {
  return window.matchMedia("(max-width: 1080px)").matches;
}

function pendingApprovalCount() {
  return Array.isArray(state.approvalQueue) ? state.approvalQueue.length : 0;
}

function getNavCollapsed() {
  try {
    return JSON.parse(localStorage.getItem(NAV_COLLAPSE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveNavCollapsed(map) {
  localStorage.setItem(NAV_COLLAPSE_KEY, JSON.stringify(map));
}

function isSectionCollapsed(section, collapsed = getNavCollapsed()) {
  return section.id in collapsed ? Boolean(collapsed[section.id]) : section.defaultCollapsed;
}

function toggleNavSection(id) {
  const section = NAV_SECTIONS.find((s) => s.id === id);
  if (!section) return;
  const collapsed = getNavCollapsed();
  const willCollapse = !isSectionCollapsed(section, collapsed);
  // On mobile, keep only one group open at a time.
  if (!willCollapse && isMobileViewport()) {
    NAV_SECTIONS.forEach((s) => { if (s.id !== id) collapsed[s.id] = true; });
  }
  collapsed[id] = willCollapse;
  saveNavCollapsed(collapsed);
  renderNav();
}

function renderNav() {
  const nav = document.querySelector("#nav-links");
  if (!nav) return;
  const pending = pendingApprovalCount();
  const collapsed = getNavCollapsed();
  nav.innerHTML = NAV_SECTIONS.map((section) => {
    const items = section.items.filter((item) => item.conditional !== "approvals" || pending > 0);
    if (!items.length) return "";
    const isCollapsed = isSectionCollapsed(section, collapsed);
    const badge = section.badge === "approvals" && pending > 0
      ? `<span class="nav-group-badge">${pending}</span>`
      : "";
    const links = items.map((item) => {
      const itemBadge = item.conditional === "approvals" && pending > 0
        ? `<span class="nav-link-badge">${pending}</span>`
        : "";
      return `<a class="nav-link${item.route === activeRoute ? " active" : ""}" data-route="${item.route}" href="#${item.route}">${item.label}${itemBadge}</a>`;
    }).join("");
    return `
      <div class="nav-group${isCollapsed ? " collapsed" : ""}" data-section="${section.id}">
        <button type="button" class="nav-group-head" data-section-toggle="${section.id}" aria-expanded="${!isCollapsed}">
          <span class="nav-group-title">${section.title}${badge}</span>
          <span class="nav-group-caret" aria-hidden="true">▾</span>
        </button>
        <div class="nav-group-items">${links}</div>
      </div>`;
  }).join("");
}

function renderApprovalQueue() {
  const target = document.querySelector("#approval-queue");
  const overview = document.querySelector("#overview-approvals");
  const summaryHtml = approvalSummaryHtml();
  if (overview) overview.innerHTML = summaryHtml;
  if (!target) return;
  if (state.approvalsLoading) {
    target.innerHTML = `<div class="row">Loading approval queue...</div>`;
    return;
  }
  if (state.approvalsError) {
    target.innerHTML = `<div class="row error-state"><strong>Approval queue unavailable</strong><br>${state.approvalsError}</div>`;
    return;
  }
  if (!state.approvalQueue.length) {
    target.innerHTML = `<div class="row">No LLM-assisted ideas are waiting for review.</div>`;
    return;
  }
  target.innerHTML = state.approvalQueue.map(approvalCard).join("");
}

function approvalSummaryHtml() {
  if (state.approvalsError) {
    return `<div class="row">Approval queue unavailable: ${state.approvalsError}</div>`;
  }
  if (state.approvalsLoading) return `<div class="row">Loading approval queue...</div>`;
  if (!state.approvalQueue.length) return `<div class="row">No ideas need review.</div>`;
  return state.approvalQueue.slice(0, 3).map((item) => {
    const explanation = item.trade_explanation?.explanation || {};
    return `<div class="row"><strong>${item.ticker}</strong><br>${explanation.setup_type || item.thesis}<br><span class="muted">${item.status} · ${Number(explanation.confidence_score ?? item.confidence ?? 0).toFixed(2)}</span></div>`;
  }).join("");
}

function approvalCard(item) {
  const explanation = item.trade_explanation?.explanation || {};
  const refs = explanation.source_refs || item.trade_explanation?.source_refs || [];
  const risks = Array.isArray(explanation.risk_factors) ? explanation.risk_factors : [explanation.risk_factors].filter(Boolean);
  return `
    <article class="approval-card" data-idea-id="${item.idea_id}">
      <div class="approval-head">
        <div>
          <div class="stock-head">
            <strong>${item.ticker}</strong>
            <span class="${item.bias}">${item.bias}</span>
            <span class="badge">${item.status || item.idea_status || "needs_review"}</span>
            <span class="badge">${explanation.time_horizon || item.timeframe || "timeframe n/a"}</span>
          </div>
          <h3>${explanation.setup_type || "LLM-assisted setup"}</h3>
        </div>
        <div class="approval-score">
          <span>Confidence</span>
          <strong>${Number(explanation.confidence_score ?? item.confidence ?? 0).toFixed(2)}</strong>
        </div>
      </div>

      <div class="approval-grid">
        ${approvalField("Thesis", explanation.thesis_summary || item.thesis)}
        ${approvalField("Catalyst", explanation.catalyst || item.catalyst)}
        ${approvalField("Why It Matters", explanation.why_this_matters)}
        ${approvalField("Market Context", explanation.market_context)}
        ${approvalField("Entry Zone", explanation.suggested_entry_zone)}
        ${approvalField("Stop Loss", explanation.suggested_stop_loss)}
        ${approvalField("Take Profit", explanation.suggested_take_profit)}
        ${approvalField("Invalidation", explanation.invalidation_level_or_condition)}
      </div>

      <div class="approval-section">
        <strong>Risk Factors</strong>
        <div class="driver-list">${risks.map((risk) => `<span>${risk}</span>`).join("") || "<span>No risk factors returned.</span>"}</div>
      </div>

      <div class="approval-section">
        <strong>Source Refs</strong>
        <div class="source-list">${sourceRefsHtml(refs)}</div>
      </div>

      <div class="approval-actions actions">
        <button class="paper" onclick="approveAndPaperTrade(${item.idea_id}, '${item.ticker}')">Approve + Paper Trade</button>
        <button class="secondary" onclick="refreshTradeLevels(${item.idea_id}, '${item.ticker}')">Refresh Levels</button>
        <button onclick="approvalAction(${item.idea_id}, 'approve')">Approve only</button>
        <button class="danger" onclick="approvalAction(${item.idea_id}, 'reject')">Reject</button>
        <button class="secondary" onclick="approvalAction(${item.idea_id}, 'expire')">Expire</button>
      </div>
    </article>
  `;
}

function approvalField(label, value) {
  return `<div class="approval-field"><span>${label}</span><p>${value || "n/a"}</p></div>`;
}

function sourceRefsHtml(refs) {
  if (!refs || !refs.length) return `<span class="muted">No source refs returned.</span>`;
  return refs.map((ref) => {
    if (typeof ref === "object" && ref !== null) {
      const label = ref.label || ref.source || ref.url || "source";
      const suffix = ref.timestamp ? ` · ${formatTime(ref.timestamp)}` : "";
      if (ref.url) {
        return `<a href="${ref.url}" target="_blank" rel="noreferrer">${label}${suffix}</a>`;
      }
      return `<span>${label}${suffix}</span>`;
    }
    const text = String(ref || "");
    if (/^https?:\/\//.test(text)) {
      return `<a href="${text}" target="_blank" rel="noreferrer">${text}</a>`;
    }
    return `<span>${text}</span>`;
  }).join("");
}

async function refreshApprovalQueue() {
  state.approvalsLoading = true;
  state.approvalsError = "";
  renderApprovalQueue();
  const result = await loadApprovalQueueResult();
  state.approvalQueue = result.data;
  state.approvalsError = result.error;
  state.approvalsLoading = false;
  renderApprovalQueue();
  renderOverview();
}

async function refreshTradeLevels(ideaId, ticker) {
  // Regenerate the stored analyst explanation against a fresh live price so
  // entry/stop/take-profit show real numbers. Used for ideas created before
  // price-grounding (or before a price source was reachable).
  showToast(`Refreshing trade levels for ${ticker}...`);
  try {
    await api(`/api/ideas/${ideaId}/explanation/regenerate`, { method: "POST" });
    await refreshApprovalQueue();
    showToast(`Trade levels refreshed for ${ticker}. If still no numbers, no live price was available.`);
  } catch (err) {
    showToast(`Could not refresh levels for ${ticker}: ${cleanErrorMessage(err.message || String(err))}`);
  }
}

async function approvalAction(ideaId, action) {
  const defaultNotes = {
    approve: "approved for paper risk validation",
    reject: "rejected by reviewer",
    expire: "expired before review",
  };
  const note = defaultNotes[action] || "";
  state.approvalQueue = state.approvalQueue.filter((item) => Number(item.idea_id) !== Number(ideaId));
  renderApprovalQueue();
  await api(`/api/ideas/${ideaId}/approval/${action}`, { method: "POST", body: JSON.stringify({ note }) });
  showToast(`Idea ${ideaId} ${action === "approve" ? "approved" : action === "reject" ? "rejected" : "expired"}. Paper execution still requires existing risk validation.`);
  await refreshApprovalQueue();
  state.dashboard = await api("/api/dashboard");
  state.ideas = await api("/api/ideas");
  renderOverview();
  renderIdeas();
  renderInboxSnapshot();
}

async function approveAndPaperTrade(ideaId, ticker) {
  // Phone-friendly one-tap loop: approve the idea for execution, then place the
  // Alpaca PAPER order. Server-side gates (approval required, paper-only,
  // risk/alpha checks) still apply — this only chains the two existing calls.
  const ok = confirm(`Approve ${ticker} AND place an Alpaca PAPER trade now?\n\nThis approves the idea for execution and immediately sends a paper order to Alpaca's paper endpoint. Paper only — no real money.`);
  if (!ok) return;
  try {
    await api(`/api/ideas/${ideaId}/approval/approve`, {
      method: "POST",
      body: JSON.stringify({ note: "approved from phone for paper execution" }),
    });
  } catch (err) {
    showToast(`Approval failed for ${ticker}: ${cleanErrorMessage(err.message || String(err))}`);
    return;
  }
  try {
    const result = await api(`/api/ideas/${ideaId}/paper-trade`, { method: "POST" });
    const reasons = (result.reasons || []).join("; ") || result.order_response?.message || "No detail returned.";
    if (result.accepted && result.order_response && result.order_response.id) {
      showToast(`Paper order submitted for ${ticker}: ${result.order_response.id}`);
    } else {
      showToast(`Approved ${ticker}, but no paper order was placed: ${reasons}`);
    }
  } catch (err) {
    showToast(`Approved ${ticker}, but paper trade failed: ${cleanErrorMessage(err.message || String(err))}`);
  }
  await refreshApprovalQueue();
  state.dashboard = await api("/api/dashboard");
  state.ideas = await api("/api/ideas");
  renderOverview();
  renderIdeas();
  renderInboxSnapshot();
}

function renderExecutionAudit() {
  const target = document.querySelector("#execution-audit");
  if (!target) return;
  const rows = state.executionAudit || [];
  if (!rows.length) {
    target.innerHTML = `<div class="row">No execution attempts recorded yet.</div>`;
    return;
  }
  target.innerHTML = rows.map((row) => `
    <div class="audit-row">
      <div><strong>${row.ticker}</strong> ${row.side || ""}<br><span class="muted">Idea ${row.idea_id || "n/a"} · ${formatTime(row.created_at)}</span></div>
      <div><span class="badge">${row.status}</span><span class="badge">${row.dry_run ? "dry-run" : "paper"}</span></div>
      <div class="muted">Qty ${row.quantity ?? "n/a"} · ${row.order_type || "order n/a"} · requested ${row.requested_entry || "n/a"} · submitted ${money(row.submitted_price)}</div>
      <div class="muted">${row.alpaca_order_id ? `Alpaca order ${row.alpaca_order_id}` : row.rejection_reason || "No rejection reason."}</div>
    </div>
  `).join("");
}

function renderPerformance() {
  const report = state.performanceReport || {};
  renderAlphaReportCard(report.report_card || {});
  renderAlphaIQ(report.alpha_iq || {});
  renderLeaderboard(document.querySelector("#source-leaderboard"), report.source_leaderboard || [], "No graded sources yet.");
  renderLeaderboard(document.querySelector("#regime-dashboard"), report.regime_dashboard || [], "No regime data yet.");
  renderRecentSignals(report.recent_signals || []);
}

// Letter grade -> CSS modifier so A/B are green, D/F red, C neutral.
function gradeClass(grade) {
  if (grade === "A" || grade === "B") return "grade-good";
  if (grade === "D" || grade === "F") return "grade-bad";
  if (grade === "C") return "grade-mid";
  return "grade-none";
}

function renderAlphaReportCard(card) {
  const gradeTarget = document.querySelector("#report-grade");
  const statsTarget = document.querySelector("#report-card");
  if (!gradeTarget || !statsTarget) return;
  const grade = card.overall_grade;
  gradeTarget.innerHTML = `
    <div class="grade-badge ${gradeClass(grade)}">${grade || "—"}</div>
    <span class="muted">${grade ? `Score ${num(card.overall_score)}/100` : "Accumulating"}</span>
  `;
  const stats = [
    ["Total signals", card.total_signals ?? 0],
    ["Executed", card.executed_signals ?? 0],
    ["Win rate", pct(card.win_rate)],
    ["Avg return", signedPct(card.avg_return)],
    ["Best", signedPct(card.best_trade)],
    ["Worst", signedPct(card.worst_trade)],
  ];
  statsTarget.innerHTML = stats.map(([k, v]) => `<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join("");
}

function renderAlphaIQ(iq) {
  const target = document.querySelector("#alpha-iq");
  if (!target) return;
  const score = iq.score;
  const components = iq.components || {};
  const rows = [
    ["Signal accuracy", components.signal_accuracy],
    ["Signal consistency", components.signal_consistency],
    ["Source reliability", components.source_reliability],
    ["Regime awareness", components.regime_awareness],
  ];
  target.innerHTML = `
    <div class="iq-headline">
      <div class="iq-score">${score === null || score === undefined ? "—" : score}</div>
      <div>
        <strong>${iq.label || "Accumulating"}</strong>
        <p class="muted">AlphaLabs IQ (0-100)</p>
      </div>
    </div>
    <div class="iq-components">
      ${rows.map(([label, value]) => `
        <div class="iq-component">
          <div class="iq-component-head"><span>${label}</span><strong>${value === null || value === undefined ? "—" : num(value)}</strong></div>
          <div class="iq-bar"><div class="iq-bar-fill" style="width:${value === null || value === undefined ? 0 : Math.max(0, Math.min(100, value))}%"></div></div>
        </div>
      `).join("")}
    </div>
  `;
}

// Keyed cache of the leaderboard groups so the click-through popup can look up
// the full breakdown by (target id, row index) without re-fetching.
const gradeDetailGroups = {};

function renderLeaderboard(target, groups, emptyMsg) {
  if (!target) return;
  if (!groups.length) {
    target.innerHTML = `<div class="row">${emptyMsg}</div>`;
    return;
  }
  gradeDetailGroups[target.id] = groups;
  const kind = target.id === "regime-dashboard" ? "Regime" : "Source";
  target.innerHTML = groups.map((group, i) => `
    <div class="leaderboard-row clickable" onclick="showGroupDetail('${target.id}', ${i})" title="Tap for grade breakdown">
      <div class="grade-badge sm ${gradeClass(group.grade)}">${group.grade || "—"}</div>
      <div class="leaderboard-main">
        <strong>${group.name}</strong>
        <div class="leaderboard-stats">
          <span>${group.executed}/${group.signals} executed</span>
          <span>Win ${pct(group.win_rate)}</span>
          <span>Avg ${signedPct(group.avg_return)}</span>
          <span>Best ${signedPct(group.best)}</span>
          <span>Worst ${signedPct(group.worst)}</span>
        </div>
      </div>
      <span class="why-hint">${kind} · why?</span>
    </div>
  `).join("");
}

function renderRecentSignals(rows) {
  const target = document.querySelector("#recent-signals");
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = `<div class="row">No signals yet.</div>`;
    return;
  }
  target.innerHTML = rows.map((row, i) => `
    <div class="performance-card clickable" onclick="showSignalDetail(${i})" title="Tap for grade breakdown">
      <div class="stock-head">
        <div class="grade-badge sm ${gradeClass(row.grade)}">${row.grade || "—"}</div>
        <strong>${row.ticker}</strong>
        <span class="${row.bias}">${row.bias}</span>
        <span class="badge">${row.trade_status || row.status}</span>
        <span class="badge">${row.market_regime}</span>
      </div>
      <p>${row.thesis_summary || ""}</p>
      <div class="btc-metrics">
        <span>Source ${row.source}</span>
        <span>Return ${row.executed ? signedPct(row.percent_return) : "not executed"}</span>
      </div>
      <div class="source-list">${(row.source_tags || []).map((tag) => `<span class="chip">${tag}</span>`).join("")}</div>
      <div class="muted">Opened ${formatTime(row.opened_at) === "unknown" ? formatTime(row.created_at) : formatTime(row.opened_at)}</div>
    </div>
  `).join("");
}

// ---- Grade-explanation popup -------------------------------------------------
// A lightweight, layout-neutral overlay: click the backdrop, the close button,
// or press Esc to dismiss. Rendered into a single #app-modal node on demand.
function showModal(title, bodyHtml) {
  let root = document.querySelector("#app-modal");
  if (!root) {
    root = document.createElement("div");
    root.id = "app-modal";
    document.body.appendChild(root);
  }
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal-card" role="dialog" aria-modal="true">
        <div class="modal-head">
          <strong>${title}</strong>
          <button class="modal-close" type="button" aria-label="Close">×</button>
        </div>
        <div class="modal-body">${bodyHtml}</div>
      </div>
    </div>`;
  const close = () => {
    root.innerHTML = "";
    document.removeEventListener("keydown", onKey);
  };
  function onKey(e) { if (e.key === "Escape") close(); }
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) close();
  });
  root.querySelector(".modal-close").addEventListener("click", close);
  document.addEventListener("keydown", onKey);
}

function contributionsList(contributions) {
  if (!contributions || !contributions.length) return `<p class="muted">No signals recorded.</p>`;
  const executed = contributions.filter((c) => c.executed);
  const pending = contributions.filter((c) => !c.executed);
  const rowHtml = (c) => `
    <div class="detail-signal">
      <div class="grade-badge sm ${gradeClass(c.grade)}">${c.grade || "—"}</div>
      <strong>${c.ticker || "—"}</strong>
      <span>${c.executed ? signedPct(c.percent_return) : "not executed"}</span>
    </div>`;
  let html = "";
  if (executed.length) {
    html += `<p class="detail-subhead">Executed signals (these set the grade)</p>` + executed.map(rowHtml).join("");
  }
  if (pending.length) {
    html += `<p class="detail-subhead">Not yet executed (no realized return — ungraded)</p>` + pending.map(rowHtml).join("");
  }
  return html;
}

function showGroupDetail(kind, idx) {
  const groups = gradeDetailGroups[kind] || [];
  const group = groups[idx];
  if (!group) return;
  const m = group.score_math || {};
  let math;
  if (group.score === null || group.score === undefined) {
    math = `<p class="muted">No executed signals yet, so there is nothing to grade. A source/regime earns a score once at least one of its signals opens a paper trade with a realized return.</p>`;
  } else {
    math = `
      <div class="detail-math">
        <div><span>Win rate</span><strong>${pct(group.win_rate)} (${group.wins}/${group.executed})</strong></div>
        <div><span>Win component (×60%)</span><strong>${num(m.win_component)}</strong></div>
        <div><span>Avg return</span><strong>${signedPct(group.avg_return)}</strong></div>
        <div><span>Return factor (50 + avg×5, clamped 0–100)</span><strong>${num(m.return_factor)}</strong></div>
        <div><span>Return component (×40%)</span><strong>${num(m.return_component)}</strong></div>
        <div class="detail-total"><span>Score = win + return components</span><strong>${num(group.score)}/100 → ${group.grade}</strong></div>
      </div>
      <p class="muted detail-band">Grade bands: A ≥ 85 · B ≥ 70 · C ≥ 55 · D ≥ 40 · else F. Scores are backward-looking realized paper-trade performance only.</p>`;
  }
  showModal(
    `${kind === "regime-dashboard" ? "Regime" : "Source"}: ${group.name}`,
    `<div class="grade-badge ${gradeClass(group.grade)}" style="margin-bottom:.6rem">${group.grade || "—"}</div>
     ${math}
     <hr class="detail-rule" />
     ${contributionsList(group.contributions)}`
  );
}

function showSignalDetail(idx) {
  const rows = (state.performanceReport || {}).recent_signals || [];
  const row = rows[idx];
  if (!row) return;
  let body;
  if (!row.executed) {
    body = `<p class="muted">This signal has not opened a paper trade yet, so it has no realized return and stays ungraded. A grade is assigned only after execution.</p>`;
  } else {
    body = `
      <div class="detail-math">
        <div><span>Realized return</span><strong>${signedPct(row.percent_return)}</strong></div>
        <div class="detail-total"><span>Grade</span><strong>${row.grade}</strong></div>
      </div>
      <p class="muted detail-band">Per-signal bands: A ≥ +5% · B ≥ +2% · C > −2% · D > −5% · F ≤ −5%. Based solely on realized paper-trade return.</p>`;
  }
  showModal(
    `${row.ticker} · ${row.source}`,
    `<div class="grade-badge ${gradeClass(row.grade)}" style="margin-bottom:.6rem">${row.grade || "—"}</div>
     <p>${row.thesis_summary || ""}</p>
     ${body}`
  );
}

function renderSavedBriefings() {
  const target = document.querySelector("#saved-briefings");
  if (!target) return;
  const rows = state.briefings || [];
  if (!rows.length) {
    target.innerHTML = `<div class="row">No saved briefings yet.</div>`;
    return;
  }
  target.innerHTML = rows.map((row) => {
    const payload = row.payload || {};
    return `
      <article class="briefing-card">
        <div class="stock-head"><strong>${payload.broad_market_tone || "Market briefing"}</strong><span class="badge">${formatTime(payload.generated_at || row.generated_at)}</span></div>
        <div class="btc-metrics">
          <span>Candidates ${(payload.candidate_tickers_to_monitor || []).length}</span>
          <span>Catalysts ${(payload.strongest_catalysts_found || []).length}</span>
          <span>Themes ${(payload.themes || []).join(", ") || "n/a"}</span>
        </div>
        <div class="approval-section"><strong>Tickers to monitor</strong><div class="driver-list">${(payload.candidate_tickers_to_monitor || []).map((ticker) => `<span>${ticker}</span>`).join("") || "<span>none</span>"}</div></div>
        <div class="approval-section"><strong>Top catalysts</strong>${(payload.strongest_catalysts_found || []).slice(0, 4).map((item) => `<p>${item.ticker || ""}: ${item.headline || item.summary || "Catalyst"}</p>`).join("") || "<p>No catalysts saved.</p>"}</div>
        <div class="approval-section"><strong>Macro risks</strong><div class="driver-list">${(payload.macro_risks || []).map((risk) => `<span>${risk}</span>`).join("") || "<span>n/a</span>"}</div></div>
      </article>
    `;
  }).join("");
}

async function generateBriefing() {
  const button = document.querySelector("#generate-briefing");
  button.textContent = "Generating...";
  await api("/api/briefings/daily/generate", { method: "POST", body: JSON.stringify({ live_catalysts: true }) });
  state.briefings = await api("/api/briefings");
  button.textContent = "Generate New Briefing";
  renderSavedBriefings();
  showToast("New market briefing generated and saved.");
}

async function generateBtcIdea() {
  const button = document.querySelector("#generate-btc-idea");
  if (button) button.textContent = "Generating...";
  const result = await api("/api/after-hours/btc/generate", { method: "POST", body: JSON.stringify({}) });
  state.afterHoursBtc = await api("/api/after-hours/btc");
  state.ideas = await api("/api/ideas");
  const approvalResult = await loadApprovalQueueResult();
  state.approvalQueue = approvalResult.data;
  state.approvalsError = approvalResult.error;
  renderAfterHoursBtc();
  renderIdeas();
  renderApprovalQueue();
  showToast(`BTC idea created for ${result.idea?.ticker || "BTC/USD"} and sent to review.`);
}

function renderPage() {
  const [title, subtitle] = PAGE_META[activeRoute] || PAGE_META.overview;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.dataset.page === activeRoute));
  renderNav();
  if (activeRoute === "settings") renderTokenStatus();
  closeMenu();
}

function openMenu() {
  document.body.classList.add("nav-open");
  document.querySelector("#menu-toggle").setAttribute("aria-expanded", "true");
}

function closeMenu() {
  document.body.classList.remove("nav-open");
  document.querySelector("#menu-toggle").setAttribute("aria-expanded", "false");
}

function toggleMenu() {
  if (document.body.classList.contains("nav-open")) closeMenu();
  else openMenu();
}


function renderOilInsight() {
  const target = document.querySelector("#oil-insight");
  const payload = state.oil || {};
  const rows = payload.stocks || [];
  if (!rows.length) {
    target.innerHTML = `<div class="row">Oil/energy proxy data unavailable. ${payload.error || "No details returned."}</div>`;
    return;
  }
  target.innerHTML = rows.map((stock) => {
    const candidate = stock.strategy_candidate || {};
    return `
      <div class="stock-card">
        <div class="stock-head"><strong>${stock.ticker}</strong><span class="${stock.bias}">${stock.bias}</span><span>${money(stock.price)}</span></div>
        <div class="setup-line ${candidate.actionable ? "actionable" : "watch"}">${stock.indicators?.setup_label || "No clear setup"}${candidate.actionable ? " · paper-test candidate" : " · watch only"}</div>
        <div class="btc-metrics">
          <span>5D ${signedPct(stock.change_5d_pct)}</span>
          <span>20D ${signedPct(stock.change_20d_pct)}</span>
          <span>Vs avg ${signedPct(stock.volume_vs_5d_avg_pct)}</span>
          <span>RSI ${num(stock.indicators?.rsi14)}</span>
          <span>Support ${money(stock.indicators?.setup?.levels?.support)}</span>
          <span>Resistance ${money(stock.indicators?.setup?.levels?.resistance)}</span>
        </div>
        ${businessBriefHtml(stock.business_brief)}
        <div class="strategy-mini"><strong>${candidate.name || "No clean strategy"}</strong><span>${candidate.reason || "Watch only."}</span><span class="muted">Trigger: ${candidate.trigger || "n/a"}</span></div>
      </div>
    `;
  }).join("");
}

const FUTURES_CARD_SYMBOLS = ["ES", "NQ", "CL", "GC", "VX"];

function futuresPulseHtml(payload, { detailed = false } = {}) {
  if (!payload || (payload.status !== "ok" && payload.status !== "no_data")) {
    return `<div class="row">Overnight Futures Pulse unavailable. ${payload?.error || "No details returned."}</div>`;
  }
  const regime = payload.regime || {};
  const moves = payload.moves || [];
  const bySymbol = Object.fromEntries(moves.map((m) => [m.symbol, m]));
  const chips = (detailed ? moves.filter((m) => m.has_data) : FUTURES_CARD_SYMBOLS.map((s) => bySymbol[s]).filter(Boolean))
    .map((m) => {
      if (!m || !m.has_data) {
        return `<span class="futures-chip flat"><strong>${m?.symbol || "—"}</strong><span class="muted">n/a</span></span>`;
      }
      const cls = m.direction === "up" ? "bullish" : m.direction === "down" ? "bearish" : "flat";
      const star = m.unusual ? " ⚡" : "";
      return `<span class="futures-chip ${cls}"><strong>${m.symbol}</strong><span>${signedPct(m.net_move_pct)}${star}</span></span>`;
    }).join("");

  const watch = (payload.watchlist || []).slice(0, detailed ? 20 : 6)
    .map((w) => `<span class="badge ${w.bias}" title="${(w.rationale || "").replace(/"/g, "&#34;")}">${w.ticker} · ${w.bias}</span>`)
    .join("");

  const conf = Number(regime.confidence || 0);
  const regimeCls = (regime.regime || "neutral").replace(/[^a-z_]/gi, "");
  let html = `
    <div class="futures-regime regime-${regimeCls}">
      <span class="regime-label">${regime.label || "Neutral"}</span>
      <span class="regime-confidence">confidence ${conf.toFixed(0)}</span>
    </div>
    <div class="futures-chips">${chips}</div>
    <p class="futures-summary">${payload.summary || ""}</p>
    <div class="futures-watchlist"><strong>Suggested watchlist</strong><div class="badge-row">${watch || "<span class=\"muted\">No directional watchlist for this regime.</span>"}</div></div>
  `;

  if (detailed) {
    const drivers = (regime.drivers || []).map((d) => `<li>${d}</li>`).join("");
    const preview = (payload.strategy_scoring_preview || []).slice(0, 12)
      .map((s) => `<div class="row"><span><strong>${s.ticker}</strong> <span class="${s.bias}">${s.bias}</span></span><span class="muted">${s.error ? s.error : `score ${num(s.composite_score)} · ${s.tier}`}</span></div>`)
      .join("");
    const rows = moves.filter((m) => m.has_data).map((m) => `
      <tr>
        <td><strong>${m.symbol}</strong><div class="muted">${m.name}</div></td>
        <td class="${m.direction === "up" ? "bullish" : m.direction === "down" ? "bearish" : ""}">${signedPct(m.net_move_pct)}</td>
        <td>${signedPct(m.range_pct)}</td>
        <td>${m.move_vs_avg != null ? `${m.move_vs_avg}x${m.unusual ? " ⚡" : ""}` : "n/a"}</td>
        <td>${m.catalyst_move_pct != null ? signedPct(m.catalyst_move_pct) : "—"}</td>
        <td class="muted">${m.moved_at ? formatTime(m.moved_at) : "—"}</td>
      </tr>`).join("");
    html += `
      <div class="futures-detail-grid">
        <div>
          <h3>Regime drivers</h3>
          <ul class="driver-ul">${drivers || "<li class=\"muted\">No dominant overnight theme.</li>"}</ul>
        </div>
        <div>
          <h3>Strategy scoring preview <span class="muted">(read-only)</span></h3>
          <div class="stat-list">${preview || "<div class=\"row muted\">No directional candidates.</div>"}</div>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Contract</th><th>O/N move</th><th>Range</th><th>vs 20d avg</th><th>Since catalyst</th><th>When</th></tr></thead>
          <tbody>${rows || "<tr><td colspan=\"6\" class=\"muted\">No overnight futures data. Set POLYGON_API_KEY to enable the live read.</td></tr>"}</tbody>
        </table>
      </div>`;
  }
  html += `<div class="muted futures-notes">${(payload.notes || []).join(" ")}</div>`;
  return html;
}

function renderFuturesPulse() {
  const payload = state.futuresPulse || {};
  const card = document.querySelector("#futures-pulse-card");
  if (card) card.innerHTML = futuresPulseHtml(payload, { detailed: false });
  const detail = document.querySelector("#futures-pulse-detail");
  if (detail) detail.innerHTML = futuresPulseHtml(payload, { detailed: true });
}

async function refreshFuturesPulse(button) {
  const original = button ? button.textContent : "";
  if (button) button.textContent = "Refreshing...";
  try {
    state.futuresPulse = await api("/api/futures/pulse");
    renderFuturesPulse();
    showToast("Overnight Futures Pulse refreshed.");
  } catch (err) {
    showError(err);
  } finally {
    if (button) button.textContent = original;
  }
}

function renderBusinessProfiles() {
  const target = document.querySelector("#business-profiles");
  const payload = state.businessProfiles || {};
  const filter = (document.querySelector("#business-filter")?.value || "").toLowerCase();
  const profiles = (payload.profiles || []).filter((profile) => JSON.stringify(profile).toLowerCase().includes(filter));
  if (!profiles.length) {
    target.innerHTML = `<div class="row">No business profiles match this filter.</div>`;
    return;
  }
  target.innerHTML = profiles.map((profile) => businessProfileCard(profile)).join("");
  const source = document.querySelector("#business-source");
  if (source) source.textContent = `${payload.source || "AlphaLab curated profiles"} · ${payload.source_note || ""}`;
}

function renderCatalystRadar() {
  const target = document.querySelector("#catalyst-radar");
  if (!target) return;
  const payload = state.catalysts || {};
  renderCatalystIntelligence();
  const providerTarget = document.querySelector("#catalyst-providers");
  const providers = payload.live_status?.providers || [];
  if (providerTarget) {
    providerTarget.innerHTML = providers.map((provider) => `
      <div class="provider-card provider-${provider.status}">
        <strong>${provider.name}</strong>
        <span class="badge">${provider.status}</span>
        <div class="muted">${provider.count || 0} items</div>
        <div class="muted">${provider.reason || ""}</div>
      </div>
    `).join("") || `<div class="row">Provider status unavailable.</div>`;
  }
  const catalysts = payload.catalysts || [];
  if (!catalysts.length) {
    target.innerHTML = `<div class="row">No catalyst items yet.</div>`;
    return;
  }
  const categories = payload.categories || {};
  const categoryDefs = [
    ["direct_company_catalysts", "Direct Company Catalysts", "Company-specific filings, press releases, contracts, offerings, approvals, or guidance changes."],
    ["broad_market_mentions", "Broad Market Mentions", "Macro, index, ETF, and market-wide context that should not create a trade by itself."],
    ["sympathy_sector_reads", "Sympathy / Sector Reads", "Peer, supplier, sector, or theme read-throughs that need separate confirmation."],
    ["low_actionability_articles", "Low-Actionability Articles", "Opinion, recap, broad commentary, or weak catalyst articles kept as context only."],
  ];
  const hasCategories = Object.values(categories).some((items) => Array.isArray(items) && items.length);
  target.innerHTML = hasCategories
    ? categoryDefs.map(([key, title, note]) => {
      const items = categories[key] || [];
      return `
        <section class="catalyst-category">
          <div class="category-head">
            <div>
              <h3>${title}</h3>
              <p class="muted">${note}</p>
            </div>
            <span class="badge">${items.length}</span>
          </div>
          <div class="catalyst-grid">${items.slice(0, 12).map(catalystCard).join("") || `<div class="row">No items in this bucket.</div>`}</div>
        </section>
      `;
    }).join("")
    : catalysts.map(catalystCard).join("");
  const source = document.querySelector("#catalyst-source");
  if (source) source.textContent = `${payload.mode || "sample"} · ${payload.source_note || ""}`;
}

function renderCatalystIntelligence() {
  const target = document.querySelector("#catalyst-intelligence");
  if (!target) return;
  const payload = state.catalystIntelligence?.dashboard || state.dashboard?.catalyst_intelligence || {};
  const top = payload.top_catalysts || [];
  const recent = payload.recent_catalysts || [];
  const strategies = payload.strategy_performance || [];
  const sectors = payload.sector_breakdown || [];
  const leaders = payload.leaderboard || [];
  if (!top.length && !recent.length) {
    target.innerHTML = `<div class="row">No persisted Catalyst Intelligence events yet. Refresh live sources or score a catalyst to start building the dataset.</div>`;
    return;
  }
  target.innerHTML = `
    <section class="ci-band">
      <div>
        <h3>Top Catalysts</h3>
        <div class="ci-list">${top.slice(0, 5).map(ciMiniCard).join("") || `<div class="row">No top catalysts yet.</div>`}</div>
      </div>
      <div>
        <h3>Recent Catalysts</h3>
        <div class="ci-list">${recent.slice(0, 5).map(ciMiniCard).join("") || `<div class="row">No recent catalysts yet.</div>`}</div>
      </div>
    </section>
    <section class="ci-band">
      <div>
        <h3>Strategy Performance</h3>
        <div class="ci-table">${strategies.slice(0, 8).map((row) => `
          <div class="row">
            <strong>${row.strategy}</strong>
            <span class="muted">${row.catalysts} catalysts · ${row.tested} tested · win ${pct(row.win_rate)}</span>
          </div>`).join("") || `<div class="row">No strategy results yet.</div>`}</div>
      </div>
      <div>
        <h3>Sector Breakdown</h3>
        <div class="driver-list">${sectors.slice(0, 10).map((row) => `<span>${row.sector}: ${row.catalysts} · top ${row.top_score}</span>`).join("") || "<span>No sector clusters yet.</span>"}</div>
      </div>
    </section>
    <section class="ci-band single">
      <div>
        <h3>Catalyst Leaderboard</h3>
        <div class="ci-list">${leaders.slice(0, 6).map((row) => `
          <div class="ci-card">
            <div><strong>${row.ticker}</strong> <span class="badge">${row.catalyst_type}</span> <span class="badge">score ${row.catalyst_score}</span></div>
            <p>${row.headline}</p>
            <div class="muted">Impact ${signedPct(row.realized_return)} · ${row.strategy_label} · ${formatTime(row.published_at)}</div>
          </div>`).join("") || `<div class="row">No tested catalyst impact yet.</div>`}</div>
      </div>
    </section>
  `;
}

function ciMiniCard(item) {
  const why = (item.explanation || []).slice(1, 4).join(" · ");
  return `
    <div class="ci-card">
      <div class="stock-head"><strong>${item.ticker}</strong><span class="${item.direction || item.bias || "neutral"}">${item.direction || item.bias || "neutral"}</span><span class="badge">${item.catalyst_score}/100</span></div>
      <p>${item.headline}</p>
      <div class="muted">${item.catalyst_type} · ${item.strategy_label} · ${formatTime(item.published_at)}</div>
      ${why ? `<div class="muted">${why}</div>` : ""}
    </div>
  `;
}

// ─── Signal breakdown (audit panel) ──────────────────────────────────────────
// Renders the full why-did-the-system-like-this view: the final alpha score and
// tier, every component score, the hard-gate status, and whether the options /
// dark-pool modifiers were included or excluded. Display only — no execution.

function fmtScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(1);
}

function safeParseJson(value) {
  if (!value) return null;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function scoreRow(label, value, extra = "") {
  return `<div class="sb-row"><span class="sb-label">${label}</span><span class="sb-value">${value}</span><span class="sb-extra">${extra}</span></div>`;
}

// mod: { score, included, hasData, bias, raw, reason }
function modifierRow(label, mod) {
  if (!mod || !mod.hasData) {
    return scoreRow(label, "—", `<span class="sb-flag sb-nodata">no provider data</span>`);
  }
  const value = mod.score === null || mod.score === undefined ? "—" : fmtScore(mod.score);
  const status = mod.included
    ? `<span class="sb-flag sb-included">included</span>`
    : `<span class="sb-flag sb-excluded">excluded${mod.reason ? ` · ${mod.reason}` : ""}</span>`;
  const bias = mod.bias && mod.bias !== "neutral" ? `<span class="sb-bias ${mod.bias}">${mod.bias}</span>` : "";
  const raw = mod.raw === null || mod.raw === undefined ? "" : `<span class="sb-raw">${mod.raw >= 0 ? "+" : ""}${mod.raw} pts</span>`;
  return scoreRow(label, value, `${status}${bias}${raw}`);
}

function signalBreakdown(b) {
  if (!b) return "";
  const tier = String(b.tier || "ignore");
  const gateClass = b.gateApplied ? "gate-capped" : b.confirmed ? "gate-ok" : "gate-neutral";
  const gateLabel = b.gateApplied
    ? "GATED · capped at watchlist"
    : b.confirmed
      ? "CONFIRMED"
      : "unconfirmed";
  const floors = (b.floors || []).filter(Boolean);
  const gateReason = b.gateApplied
    ? `<div class="sb-note sb-warn">Capped at watchlist: catalyst weak or price/volume confirmation absent — options &amp; institutional modifiers were excluded from the score.</div>`
    : "";
  const floorNote = floors.length
    ? `<div class="sb-note">Floors applied: ${floors.map((f) => String(f).replace(/_/g, " ")).join(", ")}</div>`
    : "";
  const expl = b.explanation ? `<div class="sb-note muted">${String(b.explanation)}</div>` : "";
  return `
    <div class="signal-breakdown">
      <div class="sb-head">
        <span class="alpha-tier tier-${tier}">${tier.replace(/_/g, " ")}</span>
        <span class="sb-final">Alpha ${fmtScore(b.composite)}</span>
        <span class="sb-gate ${gateClass}">${gateLabel}</span>
      </div>
      <div class="sb-grid">
        ${scoreRow("Catalyst", fmtScore(b.catalyst))}
        ${scoreRow("Price / Volume", fmtScore(b.priceVolume))}
        ${scoreRow("Narrative", fmtScore(b.narrative))}
        ${modifierRow("Options Flow", b.options)}
        ${modifierRow("Institutional / Dark Pool", b.institutional)}
        ${scoreRow("Macro", fmtScore(b.macro))}
      </div>
      ${gateReason}${floorNote}${expl}
    </div>`;
}

// Adapter: AlphaScore object (catalyst cards / scored ideas). When the engine
// gates an idea it hides the modifier scores, so excluded-with-data vs no-data is
// inferred from gate_applied (the gate only fires when modifier data is present).
function alphaToBreakdown(alpha) {
  if (!alpha) return null;
  const gateApplied = Boolean(alpha.gate_applied);
  const optionsIncluded = alpha.options_score !== null && alpha.options_score !== undefined;
  const instIncluded = alpha.institutional_score !== null && alpha.institutional_score !== undefined;
  return {
    composite: alpha.composite_score,
    tier: alpha.tier,
    catalyst: alpha.catalyst_score,
    priceVolume: alpha.price_volume_score,
    narrative: alpha.narrative_score,
    macro: alpha.macro_score,
    confirmed: Boolean(alpha.confirmed),
    gateApplied,
    floors: alpha.floors_applied || [],
    explanation: alpha.composite_explanation,
    options: {
      score: optionsIncluded ? alpha.options_score : null,
      included: optionsIncluded,
      hasData: optionsIncluded || gateApplied,
      bias: alpha.options_bias,
      raw: null,
      reason: gateApplied ? "gate" : "",
    },
    institutional: {
      score: instIncluded ? alpha.institutional_score : null,
      included: instIncluded,
      hasData: instIncluded || gateApplied,
      bias: alpha.institutional_bias,
      raw: null,
      reason: gateApplied ? "gate" : "",
    },
  };
}

// Adapter: a logged trade row (flat signal columns + *_json blobs). Richer than
// the alpha object — the stored JSON tells us precisely whether each provider had
// data, so no-data and excluded states are distinguished exactly.
function tradeToBreakdown(t) {
  if (!t || t.alpha_composite === null || t.alpha_composite === undefined) return null;
  const flow = safeParseJson(t.options_flow_json);
  const inst = safeParseJson(t.institutional_json);
  const gateApplied = Boolean(t.gate_applied);
  const confirmed = Boolean(t.confirmed);
  const optionsHasData = flow ? Boolean(flow.has_data) : t.options_component !== null && t.options_component !== undefined;
  const instHasData = inst ? Boolean(inst.has_data) : t.institutional_component !== null && t.institutional_component !== undefined;
  const optionsIncluded = confirmed && optionsHasData;
  const instIncluded = confirmed && instHasData;
  return {
    composite: t.alpha_composite,
    tier: t.alpha_tier,
    catalyst: t.catalyst_score,
    priceVolume: t.price_volume_score,
    narrative: t.narrative_score,
    macro: t.macro_score,
    confirmed,
    gateApplied,
    floors: gateApplied ? ["confirmation_gate"] : [],
    explanation: null,
    options: {
      score: t.options_component,
      included: optionsIncluded,
      hasData: optionsHasData,
      bias: t.options_bias,
      raw: t.options_score,
      reason: gateApplied ? "gate" : optionsIncluded ? "" : "not confirmed",
    },
    institutional: {
      score: t.institutional_component,
      included: instIncluded,
      hasData: instHasData,
      bias: t.institutional_bias,
      raw: t.institutional_score,
      reason: gateApplied ? "gate" : instIncluded ? "" : "not confirmed",
    },
  };
}

function alphaBox(alpha) {
  if (!alpha) return "";
  return signalBreakdown(alphaToBreakdown(alpha));
}

function catalystCard(item) {
  return `
    <div class="catalyst-card ${item.trade_candidate ? "candidate" : "watch"}">
      <div class="stock-head">
        <strong>${item.ticker}</strong>
        <span class="${item.bias}">${item.bias}</span>
        <span class="badge">score ${Number(item.catalyst_score || 0).toFixed(0)}/100</span>
        <span class="badge">${item.trade_candidate ? "candidate" : "watch"}</span>
        ${item.catalyst_type ? `<span class="badge">${item.catalyst_type}</span>` : ""}
      </div>
      <h3>${item.headline}</h3>
      <p>${item.summary || item.read}</p>
      <div class="driver-list">${(item.explanation || []).slice(1, 6).map((line) => `<span>${line.replace(/^\+ /, "")}</span>`).join("")}</div>
      <div class="driver-list">${(item.matched_keywords || []).map((match) => `<span>${match.keyword} ${match.weight > 0 ? "+" : ""}${match.weight}</span>`).join("") || "<span>no keyword match</span>"}</div>
      ${alphaBox(item.alpha)}
      ${item.category_reason ? `<div class="muted">Bucket: ${item.category_reason}</div>` : ""}
      <div class="muted">${item.read}</div>
      <div class="muted">${item.next_check}</div>
      <div class="muted">Source: ${item.source} · ${formatTime(item.published_at)}${item.source_url ? ` · ${item.source_url}` : ""}</div>
    </div>
  `;
}

function renderDailyBrief() {
  const target = document.querySelector("#daily-brief");
  if (!target) return;
  const brief = state.dailyBrief || {};
  if (brief.status !== "ok") {
    target.innerHTML = `<div class="row">Daily brief unavailable. ${brief.error || "No detail returned."}</div>`;
    return;
  }
  const regime = brief.regime || {};
  const signals = brief.signals || [];
  target.innerHTML = `
    <div class="brief-summary">
      <div><strong>${brief.headline || "Daily market brief"}</strong><span class="badge">${regime.posture || "unknown"}</span></div>
      <div class="btc-metrics">
        <span>BTC ${regime.btc_bias || "unknown"}</span>
        <span>Bullish setups ${regime.bullish_setups ?? 0}</span>
        <span>Bearish setups ${regime.bearish_setups ?? 0}</span>
        <span>Signals ${signals.length}</span>
      </div>
      <div class="brief-signals">${signals.map((signal) => `<span>${signal.ticker} ${signal.bias} ${Number(signal.confidence || 0).toFixed(2)}</span>`).join("") || "<span>No clean signals</span>"}</div>
      <div class="muted">${brief.source_note || ""}</div>
      <div class="muted">${(regime.data_limits || []).join(" · ")}</div>
    </div>
  `;
}

async function testCatalystCandidates() {
  const button = document.querySelector("#test-catalysts-dry");
  if (button) button.textContent = "Dry-running...";
  try {
    const result = await api("/api/catalysts/poll", { method: "POST", body: JSON.stringify({ dry_run: true }) });
    const count = result.signals ? result.signals.length : 0;
    showToast(`Catalyst Radar created ${count} signal candidate${count === 1 ? "" : "s"}. Check inbox for decisions.`);
    await load();
  } finally {
    if (button) button.textContent = "Dry-Run Catalyst Candidates";
  }
}

async function refreshDailyBrief() {
  const button = document.querySelector("#refresh-brief");
  button.textContent = "Refreshing...";
  state.dailyBrief = await api("/api/brief/daily");
  button.textContent = "Refresh Brief";
  renderDailyBrief();
  showToast(`Daily brief refreshed: ${(state.dailyBrief.signals || []).length} signal candidate${(state.dailyBrief.signals || []).length === 1 ? "" : "s"}.`);
}

async function feedDailyBrief() {
  const button = document.querySelector("#feed-brief");
  button.textContent = "Feeding...";
  const result = await api("/api/brief/daily/import-and-test", { method: "POST", body: JSON.stringify({ dry_run: true, live_catalysts: true }) });
  button.textContent = "Feed Dry-Run Agent";
  const count = result.signals ? result.signals.length : 0;
  showToast(`Daily brief fed ${count} new signal candidate${count === 1 ? "" : "s"} into dry-run testing.`);
  await load();
}

async function refreshCatalysts() {
  const button = document.querySelector("#refresh-catalysts");
  if (button) button.textContent = "Refreshing...";
  try {
    state.catalystIntelligence = await api("/api/catalysts/intelligence", {
      method: "POST",
      body: JSON.stringify({ live: true, persist: true, generate_ideas: false }),
    });
    state.catalysts = state.catalystIntelligence;
    renderCatalystRadar();
    showToast(`Catalyst sources refreshed: ${state.catalysts.mode || "unknown mode"}.`);
  } finally {
    if (button) button.textContent = "Refresh Live Sources";
  }
}

async function scoreManualCatalyst(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.published_at = new Date().toISOString();
  const result = await api("/api/catalysts/intelligence", {
    method: "POST",
    body: JSON.stringify({ persist: true, generate_ideas: true, dry_run: true, catalysts: [data] }),
  });
  const count = result.signals ? result.signals.length : 0;
  showToast(count ? "Catalyst scored and added to the inbox." : "Catalyst scored as watch only; no trade signal created.");
  event.target.reset();
  await load();
}

function businessProfileCard(profile) {
  const fundamentals = profile.fundamentals || {};
  const metrics = (fundamentals.key_metrics || []).map((metric) => `<span>${metric}</span>`).join("");
  const risks = (fundamentals.risks || []).map((risk) => `<span>${risk}</span>`).join("");
  const drivers = (profile.drivers || []).map((driver) => `<span>${driver}</span>`).join("");
  return `
    <div class="business-card">
      <div class="stock-head"><strong>${profile.ticker}</strong><span>${profile.name || ""}</span></div>
      <p>${profile.business || "No business profile available."}</p>
      <div class="fundamental-block"><strong>Business drivers</strong><div class="driver-list">${drivers || "<span>n/a</span>"}</div></div>
      <div class="fundamental-block"><strong>Fundamental model</strong><p>${fundamentals.model || "No fundamental model note available."}</p></div>
      <div class="fundamental-block"><strong>Key metrics to watch</strong><div class="driver-list">${metrics || "<span>n/a</span>"}</div></div>
      <div class="fundamental-block"><strong>Risks</strong><div class="driver-list">${risks || "<span>n/a</span>"}</div></div>
      <div class="muted">${profile.watch || ""}</div>
    </div>
  `;
}

function renderStrategyCandidates() {
  const target = document.querySelector("#strategy-candidates");
  const btc = state.bitcoin || {};
  if (btc.status !== "ok") {
    target.innerHTML = `<div class="row">Strategy candidates unavailable because live market data is unavailable.</div>`;
    return;
  }
  target.innerHTML = (btc.strategy_candidates || []).map((candidate) => `
    <div class="strategy-card">
      <div><strong>${candidate.name}</strong><span class="badge">${candidate.direction}</span></div>
      <p>${candidate.why}</p>
      <div class="muted"><strong>Trigger:</strong> ${candidate.trigger}</div>
      <div class="muted"><strong>Invalidation:</strong> ${candidate.invalidation}</div>
    </div>
  `).join("") || `<div class="row">No clean strategy candidates from current conditions.</div>`;
}

function renderInboxSnapshot() {
  const snapshot = document.querySelector("#inbox-snapshot");
  const ideas = state.ideas.slice(0, 6);
  snapshot.innerHTML = ideas.map((idea) => `
    <div class="snapshot-card">
      <div><strong>${idea.ticker}</strong> <span class="${idea.bias}">${idea.bias}</span></div>
      <div class="muted">${idea.status} · ${Number(idea.confidence).toFixed(2)} · ${(idea.strategies || []).slice(0, 2).join(", ") || "untagged"}</div>
      <div>${idea.thesis}</div>
    </div>
  `).join("") || `<div class="row">No inbox ideas yet.</div>`;
}

async function testNewIdeas() {
  const button = document.querySelector("#test-new");
  button.textContent = "Testing...";
  await api("/api/ideas/test-new", { method: "POST", body: JSON.stringify({ dry_run: true }) });
  button.textContent = "Dry-Run Test New Ideas";
  await load();
}

function renderStats() {
  const strategyTarget = document.querySelector("#strategies");
  const strategyRows = (state.stats || []).filter((s) => Number(s.trades || 0) > 0);
  const dryOnly = strategyRows.length && strategyRows.every((s) => Number(s.paper_trades || 0) === 0);
  const missingLinkedTrades = (state.trades || []).filter((trade) => {
    const idea = (state.ideas || []).find((item) => item.id === trade.idea_id);
    return !idea || !(idea.strategies || []).length;
  }).length;
  if (!strategyRows.length) {
    const tradeCount = (state.trades || []).length;
    let message = "No trades have been placed or dry-run tested yet.";
    if (tradeCount > 0 && missingLinkedTrades > 0) {
      message = `${tradeCount} trade${tradeCount === 1 ? "" : "s"} exist, but ${missingLinkedTrades} are not linked to strategy labels yet.`;
    } else if (tradeCount > 0) {
      message = "Trades exist, but strategy metrics have not been computed yet.";
    }
    strategyTarget.innerHTML = `<div class="row">${message} AlphaLab is dry-run by default; Alpaca paper orders only occur from approved paper actions or paper-mode scheduler jobs.</div>`;
  } else {
    strategyDetailRows = strategyRows;
    strategyTarget.innerHTML = strategyRows.map((s, i) => {
      const recent = (s.recent_trades || []).slice(0, 3).map((t) => `${t.ticker} ${t.status}${t.dry_run ? " dry-run" : " paper"}`).join(" · ");
      return `
        <div class="row clickable" onclick="showStrategyDetail(${i})" title="Tap for the strategy idea and performance detail">
          <strong>${s.strategy}</strong> <span class="why-hint">idea · perf?</span><br>
          ${pct(s.win_rate)} win rate · ${s.trades} total · ${s.paper_trades || 0} paper · ${s.dry_run_trades || 0} dry-run<br>
          Open ${s.open_trades || 0} · Closed ${s.closed_trades || 0} · Realized ${money(s.realized_pl)} · Unrealized ${money(s.unrealized_pl)}
          <div class="muted">${recent || (dryOnly ? "Dry-run only so far; no Alpaca paper fills to score." : "No recent trades.")}</div>
        </div>
      `;
    }).join("");
  }

  const tradesHtml = state.trades.map((t) => {
    const isDryRun = Boolean(t.dry_run);
    const label = isDryRun ? "Dry-run test" : "Alpaca paper order";
    const note = isDryRun ? "No Alpaca order placed; equity and positions unchanged." : "Submitted to Alpaca paper endpoint.";
    return `
    <div class="row"><strong>${t.ticker}</strong> ${t.side} · ${label}<br>${money(t.notional)} · ${note}${signalBreakdown(tradeToBreakdown(t))}</div>
  `;
  }).join("") || `<div class="row">No paper orders or dry-run tests yet.</div>`;
  const tradesTarget = document.querySelector("#trades");
  if (tradesTarget) tradesTarget.innerHTML = tradesHtml;

  const rejected = state.ideas.filter((i) => i.status === "rejected");
  const rejectionHtml = rejected.map((i) => `
    <div class="row"><strong>${i.ticker}</strong><br>${i.rejection_reason || "No reason saved"}</div>
  `).join("") || `<div class="row">No rejections yet.</div>`;
  const rejectionsTarget = document.querySelector("#rejections");
  if (rejectionsTarget) rejectionsTarget.innerHTML = rejectionHtml;
}

// ---- Strategy detail popup ---------------------------------------------------
// Cached filtered strategy rows so the click-through popup can look up the full
// breakdown by index without re-fetching. Mirrors the leaderboard popup pattern.
let strategyDetailRows = [];

function strategyLinkedIdeas(name) {
  return (state.ideas || []).filter((idea) => (idea.strategies || []).includes(name));
}

function showStrategyDetail(idx) {
  const s = strategyDetailRows[idx];
  if (!s) return;
  const ideas = strategyLinkedIdeas(s.strategy);
  const ideaIds = new Set(ideas.map((idea) => idea.id));
  const linkedTrades = (state.trades || []).filter((t) => ideaIds.has(t.idea_id));
  const invested = linkedTrades.reduce((sum, t) => sum + Number(t.notional || 0), 0);
  const netPl = Number(s.realized_pl || 0) + Number(s.unrealized_pl || 0);

  const ranked = ideas.slice().sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
  const ideaHtml = ranked.length
    ? ranked.slice(0, 4).map((it) => `
        <div class="detail-idea">
          <div><strong>${it.ticker}</strong> <span class="${it.bias}">${it.bias}</span> · ${Number(it.confidence || 0).toFixed(2)} conf · ${it.status}</div>
          <p>${it.thesis || "No thesis recorded."}</p>
          ${it.catalyst ? `<p class="muted">Catalyst: ${it.catalyst}</p>` : ""}
        </div>`).join("")
    : `<p class="muted">No linked ideas carry a written thesis yet. A strategy is a label applied to ideas as they are tested.</p>`;

  const recent = (s.recent_trades || []).length
    ? s.recent_trades.map((t) => `
        <div class="detail-signal">
          <strong>${t.ticker}</strong>
          <span>${t.status}${t.dry_run ? " · dry-run" : " · paper"}</span>
          <span>${money(t.notional)}</span>
          <span>${money(Number(t.realized_pl || 0) + Number(t.unrealized_pl || 0))}</span>
        </div>`).join("")
    : `<p class="muted">No trades recorded for this strategy yet.</p>`;

  showModal(
    `Strategy: ${s.strategy}`,
    `<p class="detail-subhead">Idea / hypothesis</p>
     ${ideaHtml}
     <hr class="detail-rule" />
     <p class="detail-subhead">Performance so far</p>
     <div class="detail-math">
       <div><span>Win rate</span><strong>${pct(s.win_rate)} (${s.wins || 0}/${s.trades})</strong></div>
       <div><span>Trades</span><strong>${s.trades} · ${s.paper_trades || 0} paper · ${s.dry_run_trades || 0} dry-run</strong></div>
       <div><span>Open / Closed</span><strong>${s.open_trades || 0} open · ${s.closed_trades || 0} closed</strong></div>
       <div><span>Amount invested (notional)</span><strong>${money(invested)}</strong></div>
       <div><span>Realized PnL</span><strong>${money(s.realized_pl)}</strong></div>
       <div><span>Unrealized PnL</span><strong>${money(s.unrealized_pl)}</strong></div>
       <div><span>Avg PnL / trade</span><strong>${money(s.avg_pl)}</strong></div>
       <div><span>Avg confidence</span><strong>${Number(s.avg_confidence || 0).toFixed(2)}</strong></div>
       <div class="detail-total"><span>Net PnL (realized + unrealized)</span><strong>${money(netPl)}</strong></div>
     </div>
     <p class="muted detail-band">PnL is paper/dry-run only. Realized comes from closed trades; unrealized marks open positions to market.</p>
     <hr class="detail-rule" />
     <p class="detail-subhead">Recent trades</p>
     ${recent}`
  );
}

async function decision(id) {
  await api(`/api/ideas/${id}/decision`, { method: "POST" });
  await load();
}

async function dryRun(id) {
  await api(`/api/ideas/${id}/dry-run-trade`, { method: "POST" });
  await load();
}

async function paperTrade(id, ticker) {
  const ok = confirm(`Place an Alpaca PAPER trade for ${ticker}? This is paper trading only, but it will send an order to Alpaca's paper endpoint.`);
  if (!ok) return;
  try {
    const result = await api(`/api/ideas/${id}/paper-trade`, { method: "POST" });
    const reasons = (result.reasons || []).join("; ") || result.order_response?.message || "No detail returned.";
    if (result.accepted && result.order_response && result.order_response.id) {
      showToast(`Paper order submitted for ${ticker}: ${result.order_response.id}`);
      alert(`Paper order submitted for ${ticker}.\nOrder id: ${result.order_response.id}`);
    } else {
      showToast(`No paper order placed for ${ticker}: ${reasons}`);
      alert(`No paper order was placed for ${ticker}.\n\nReason: ${reasons}`);
    }
  } catch (err) {
    const message = cleanErrorMessage(err.message);
    showToast(`No paper order placed for ${ticker}: ${message}`);
    alert(`No paper order was placed for ${ticker}.\n\nReason: ${message}`);
  }
  await load();
}

async function rejectIdea(id) {
  const reason = prompt("Rejection reason", "manual rejection");
  if (!reason) return;
  await api(`/api/ideas/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
  await load();
}

function money(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  const n = Number(value);
  if (Number.isNaN(n)) return "n/a";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function pct(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function signedPct(value) {
  if (value === null || value === undefined) return "n/a";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function num(value) {
  if (value === null || value === undefined) return "n/a";
  return Number(value).toFixed(1);
}

function moneyCompact(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  const n = Number(value);
  if (Number.isNaN(n)) return "n/a";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 });
}

function formatTime(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

window.approvalAction = approvalAction;
window.approveAndPaperTrade = approveAndPaperTrade;
window.decision = decision;
window.dryRun = dryRun;
window.paperTrade = paperTrade;
window.rejectIdea = rejectIdea;

// Null-safe event binding so relocating/removing panels never throws.
function bind(selector, event, handler) {
  const el = document.querySelector(selector);
  if (el) el.addEventListener(event, handler);
}

document.querySelector("#refresh").addEventListener("click", () => load().catch(showError));
bind("#overview-view-opps", "click", () => setRoute("inbox"));
bind("#overview-view-sources", "click", () => setRoute("performance"));
document.querySelector("#menu-toggle").addEventListener("click", toggleMenu);
document.querySelector("#nav-backdrop").addEventListener("click", closeMenu);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
document.querySelector("#nav-links").addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-section-toggle]");
  if (toggle) {
    toggleNavSection(toggle.dataset.sectionToggle);
    return;
  }
  const link = event.target.closest(".nav-link");
  if (link) setRoute(link.dataset.route);
});
window.addEventListener("hashchange", () => setRoute(window.location.hash.replace("#", "") || "overview", false));
bind("#test-new", "click", () => testNewIdeas().catch(showError));
document.querySelector("#test-trending-dry").addEventListener("click", () => testTrendingStrategies(true).catch(showError));
document.querySelector("#test-trending-paper").addEventListener("click", () => testTrendingStrategies(false).catch(showError));
document.querySelector("#test-catalysts-dry").addEventListener("click", () => testCatalystCandidates().catch(showError));
document.querySelector("#refresh-catalysts").addEventListener("click", () => refreshCatalysts().catch(showError));
bind("#refresh-brief", "click", () => refreshDailyBrief().catch(showError));
document.querySelector("#refresh-approvals").addEventListener("click", () => refreshApprovalQueue().catch(showError));
bind("#refresh-futures-pulse", "click", function () { refreshFuturesPulse(this).catch(showError); });
bind("#refresh-futures-detail", "click", function () { refreshFuturesPulse(this).catch(showError); });
bind("#feed-brief", "click", () => feedDailyBrief().catch(showError));
document.querySelector("#generate-briefing").addEventListener("click", () => generateBriefing().catch(showError));
document.querySelector("#filter").addEventListener("input", renderIdeas);
document.querySelector("#business-filter").addEventListener("input", renderBusinessProfiles);
document.querySelector("#catalyst-form").addEventListener("submit", (event) => scoreManualCatalyst(event).catch(showError));
document.querySelector("#idea-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.confidence = Number(data.confidence);
  data.source = "manual_form";
  data.timestamp = new Date().toISOString();
  data.strategies = String(data.strategies || "").split(",").map((s) => s.trim()).filter(Boolean);
  await api("/api/ideas", { method: "POST", body: JSON.stringify(data) });
  event.target.reset();
  await load();
});

let chatHistory = [];

function appendChatMessage(role, text) {
  const log = document.querySelector("#chat-log");
  if (!log) return;
  const row = document.createElement("div");
  row.className = `chat-msg chat-${role}`;
  row.textContent = text;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

async function sendChat(event) {
  event.preventDefault();
  const input = document.querySelector("#chat-input");
  const sendBtn = document.querySelector("#chat-send");
  const message = String(input.value || "").trim();
  if (!message) return;
  input.value = "";
  appendChatMessage("user", message);
  sendBtn.disabled = true;
  const pending = appendChatMessage("assistant", "…");
  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history: chatHistory.slice(-8) }),
    });
    pending.textContent = res.reply || "(no reply)";
    chatHistory.push({ role: "user", content: message });
    chatHistory.push({ role: "assistant", content: res.reply || "" });
  } catch (err) {
    pending.textContent = `⚠ ${cleanErrorMessage(err.message || String(err))}`;
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

document.querySelector("#chat-form").addEventListener("submit", (event) => sendChat(event));
document.querySelector("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    sendChat(event);
  }
});

document.querySelector("#token-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#token-input");
  setApiToken(input.value);
  input.value = "";
  showToast(getApiToken() ? "Token saved on this device." : "Token cleared.");
});
document.querySelector("#token-clear").addEventListener("click", () => {
  setApiToken("");
  document.querySelector("#token-input").value = "";
  showToast("Token cleared from this device.");
});
document.querySelector("#token-test").addEventListener("click", () => testApiToken());

function showToast(message) {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 4200);
}

function showError(err) {
  const message = err.message || String(err);
  showToast(message);
  document.querySelectorAll(".runtime-error").forEach((node) => node.remove());
  document.body.insertAdjacentHTML("afterbegin", `<pre class="panel runtime-error">${message}</pre>`);
}

activeRoute = window.location.hash.replace("#", "") || "overview";
renderNav();
renderPage();
load().catch(showError);
