"""
alpha_lab/futures_pulse.py — the Overnight Futures Pulse Agent.

Detects overnight futures movement driven by macro / geopolitical catalysts and
converts it into a premarket regime read + a suggested equity watchlist BEFORE
the cash open. It is strictly READ-ONLY: it never places, approves, or sizes a
trade. Its output can be fed into the existing AlphaLabs strategy scoring as
candidate signals[], but those still go through the normal idea/approval path.

Three layers, mirroring the options-flow / dark-pool agents:

  1. A provider interface (FuturesDataProvider) that returns an OvernightSeries
     (1m/5m aggregates for the 6pm-9:30am ET overnight session) for a futures
     ticker, plus:
        - PolygonFuturesProvider: live read from Polygon/Massive Futures v1
          aggregates (graceful degradation on no key / bad ticker / network).
        - StubFuturesDataProvider: always None ("no data").
  2. A deterministic move calculator (compute_move) that turns an OvernightSeries
     into a FuturesMove: net move vs prior close, overnight high/low, range, how
     unusual the move is vs a 20-day overnight average, when it moved, and the
     move since a provided catalyst timestamp.
  3. A deterministic regime classifier (classify_regime) that scores the whole
     board of moves into one of: risk_on, risk_off, oil_shock, inflation_rates_shock,
     safe_haven_unwind, volatility_compression (or neutral / mixed), with a
     0-100 confidence, then maps the regime to reacting sectors/tickers.

Everything except the network provider is a pure function, so the scoring and
classification are fully unit-testable with fixed inputs.
"""
from __future__ import annotations

import os
import time as _time_module
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

from pydantic import BaseModel

try:  # zoneinfo is stdlib on 3.9+; the project already uses it in service.py
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - fallback if tz database is missing
    _ET = timezone(timedelta(hours=-5))


# ─── Tracked futures universe ─────────────────────────────────────────────────

class FuturesContractSpec(BaseModel):
    """One tracked futures contract and how an equity desk reacts to it."""
    symbol: str                 # short root, e.g. "ES"
    polygon_ticker: str         # provider ticker, e.g. "ES" / continuous front month
    name: str
    category: str               # equity_index | energy | metals | rates | crypto | vol
    # When this contract moves, these cash-equity sectors/tickers tend to react.
    reaction_tickers: list[str] = []


# The default board. polygon_ticker uses the continuous front-month convention
# (overridable via env if a deployment uses a different symbology). Rates and VIX
# futures are tracked when the data provider returns them; absence is neutral.
TRACKED_CONTRACTS: list[FuturesContractSpec] = [
    FuturesContractSpec(symbol="ES", polygon_ticker="ES", name="E-mini S&P 500", category="equity_index",
                        reaction_tickers=["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]),
    FuturesContractSpec(symbol="NQ", polygon_ticker="NQ", name="E-mini Nasdaq 100", category="equity_index",
                        reaction_tickers=["QQQ", "NVDA", "AMD", "META", "SMH"]),
    FuturesContractSpec(symbol="RTY", polygon_ticker="RTY", name="E-mini Russell 2000", category="equity_index",
                        reaction_tickers=["IWM", "ARKK"]),
    FuturesContractSpec(symbol="CL", polygon_ticker="CL", name="WTI Crude Oil", category="energy",
                        reaction_tickers=["USO", "XLE", "XOM", "CVX", "OXY", "SLB"]),
    FuturesContractSpec(symbol="NG", polygon_ticker="NG", name="Henry Hub Natural Gas", category="energy",
                        reaction_tickers=["BOIL", "LNG", "XLE"]),
    FuturesContractSpec(symbol="GC", polygon_ticker="GC", name="Gold", category="metals",
                        reaction_tickers=["GLD", "GDX", "NEM"]),
    FuturesContractSpec(symbol="SI", polygon_ticker="SI", name="Silver", category="metals",
                        reaction_tickers=["SLV", "PAAS"]),
    FuturesContractSpec(symbol="ZN", polygon_ticker="ZN", name="10-Year T-Note", category="rates",
                        reaction_tickers=["TLT", "IEF", "XLF"]),
    FuturesContractSpec(symbol="ZB", polygon_ticker="ZB", name="30-Year T-Bond", category="rates",
                        reaction_tickers=["TLT", "EDV"]),
    FuturesContractSpec(symbol="ZT", polygon_ticker="ZT", name="2-Year T-Note", category="rates",
                        reaction_tickers=["SHY", "XLF"]),
    FuturesContractSpec(symbol="BTC", polygon_ticker="BTC", name="Bitcoin Futures", category="crypto",
                        reaction_tickers=["COIN", "MSTR", "MARA", "BITO"]),
    FuturesContractSpec(symbol="VX", polygon_ticker="VX", name="VIX Futures", category="vol",
                        reaction_tickers=["UVXY", "VIXY", "SPY"]),
]

CONTRACTS_BY_SYMBOL: dict[str, FuturesContractSpec] = {c.symbol: c for c in TRACKED_CONTRACTS}


# ─── Data models ──────────────────────────────────────────────────────────────

class OvernightBar(BaseModel):
    """A single 1m/5m aggregate bar within the overnight session."""
    ts: str                     # ISO-8601 timestamp (ET) for the bar open
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class OvernightSeries(BaseModel):
    """The provider's overnight read for one contract (6pm ET -> 9:30am ET)."""
    symbol: str
    bars: list[OvernightBar] = []
    prior_close: float                                   # prior RTH/settlement close
    avg_overnight_move_pct_20d: Optional[float] = None   # trailing 20-day avg |overnight move %|


class FuturesMove(BaseModel):
    """Deterministic per-contract overnight move read. The public agent JSON."""
    symbol: str
    name: str
    category: str
    has_data: bool
    last_price: Optional[float] = None
    prior_close: Optional[float] = None
    net_move_pct: float = 0.0           # signed % vs prior close (the headline move)
    overnight_high: Optional[float] = None
    overnight_low: Optional[float] = None
    range_pct: float = 0.0              # (high-low)/prior_close * 100
    avg_overnight_move_pct_20d: Optional[float] = None
    move_vs_avg: Optional[float] = None  # |net_move_pct| / 20d avg (×; >1 = above normal)
    unusual: bool = False               # move_vs_avg >= UNUSUAL_MULTIPLE
    direction: str = "flat"             # up | down | flat
    moved_at: Optional[str] = None      # ts of the largest single-bar move ("when")
    catalyst_move_pct: Optional[float] = None  # move since the catalyst timestamp


class RegimeClassification(BaseModel):
    """The board-level overnight regime read."""
    regime: str                 # risk_on | risk_off | oil_shock | inflation_rates_shock | safe_haven_unwind | volatility_compression | neutral | mixed
    label: str                  # human-readable
    confidence: float           # 0-100
    drivers: list[str] = []     # which contracts/legs drove the call
    scores: dict[str, float] = {}  # per-regime raw scores (audit)


class WatchlistEntry(BaseModel):
    ticker: str
    bias: str                   # bullish | bearish | neutral
    rationale: str


class FuturesPulseReport(BaseModel):
    """Full premarket Overnight Futures Pulse output."""
    status: str                 # ok | no_data | unavailable
    session_date: str           # the cash-session date this overnight precedes (ET, YYYY-MM-DD)
    generated_at: str
    catalyst_timestamp: Optional[str] = None
    moves: list[FuturesMove] = []
    regime: RegimeClassification
    summary: str
    watchlist: list[WatchlistEntry] = []
    notes: list[str] = []
    provider_status: dict[str, str] = {}


# ─── Move calculator (pure) ───────────────────────────────────────────────────

UNUSUAL_MULTIPLE = 1.5          # a move >= 1.5x its 20d overnight average is "unusual"
_FLAT_DEADBAND_PCT = 0.10       # |move| below this is treated as flat (noise)


def _direction(net_move_pct: float) -> str:
    if net_move_pct > _FLAT_DEADBAND_PCT:
        return "up"
    if net_move_pct < -_FLAT_DEADBAND_PCT:
        return "down"
    return "flat"


def compute_move(spec: FuturesContractSpec,
                 series: Optional[OvernightSeries],
                 catalyst_ts: Optional[str] = None) -> FuturesMove:
    """Turn an OvernightSeries into a FuturesMove. No data -> has_data=False."""
    if series is None or not series.bars or not series.prior_close:
        return FuturesMove(symbol=spec.symbol, name=spec.name, category=spec.category,
                           has_data=False)

    prior_close = float(series.prior_close)
    bars = series.bars
    last_price = float(bars[-1].close)
    overnight_high = max(float(b.high) for b in bars)
    overnight_low = min(float(b.low) for b in bars)
    net_move_pct = round((last_price - prior_close) / prior_close * 100, 4)
    range_pct = round((overnight_high - overnight_low) / prior_close * 100, 4)

    avg = series.avg_overnight_move_pct_20d
    move_vs_avg = None
    unusual = False
    if avg and avg > 0:
        move_vs_avg = round(abs(net_move_pct) / avg, 2)
        unusual = move_vs_avg >= UNUSUAL_MULTIPLE

    # "When it moved": timestamp of the bar with the largest absolute bar return.
    moved_at = None
    largest = 0.0
    for b in bars:
        if b.open:
            bar_ret = abs((float(b.close) - float(b.open)) / float(b.open))
            if bar_ret > largest:
                largest = bar_ret
                moved_at = b.ts

    # Move since the catalyst timestamp (close of the first bar at/after it).
    catalyst_move_pct = None
    if catalyst_ts:
        anchor = _bar_close_at_or_after(bars, catalyst_ts)
        if anchor is not None and anchor:
            catalyst_move_pct = round((last_price - anchor) / anchor * 100, 4)

    return FuturesMove(
        symbol=spec.symbol, name=spec.name, category=spec.category, has_data=True,
        last_price=last_price, prior_close=prior_close, net_move_pct=net_move_pct,
        overnight_high=overnight_high, overnight_low=overnight_low, range_pct=range_pct,
        avg_overnight_move_pct_20d=avg, move_vs_avg=move_vs_avg, unusual=unusual,
        direction=_direction(net_move_pct), moved_at=moved_at,
        catalyst_move_pct=catalyst_move_pct,
    )


def _bar_close_at_or_after(bars: list[OvernightBar], ts: str) -> Optional[float]:
    target = _parse_ts(ts)
    if target is None:
        return None
    for b in bars:
        bt = _parse_ts(b.ts)
        if bt is not None and bt >= target:
            return float(b.close)
    return None


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        cleaned = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_ET)
        return dt
    except Exception:
        return None


# ─── Regime classifier (pure) ─────────────────────────────────────────────────

REGIME_LABELS = {
    "risk_on": "Risk-On",
    "risk_off": "Risk-Off",
    "oil_shock": "Oil Shock",
    "inflation_rates_shock": "Inflation / Rates Shock",
    "safe_haven_unwind": "Safe-Haven Unwind",
    "volatility_compression": "Volatility Compression",
    "neutral": "Neutral / Quiet",
    "mixed": "Mixed / Crosscurrents",
}

# A move (in %) at or above this is "big" for the shock detectors.
_BIG_EQUITY_PCT = 0.6
_BIG_OIL_PCT = 2.5
_BIG_RATES_PCT = 0.5
_BIG_METAL_PCT = 1.0
_BIG_VOL_PCT = 5.0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _category_moves(moves: list[FuturesMove], category: str) -> list[FuturesMove]:
    return [m for m in moves if m.has_data and m.category == category]


def classify_regime(moves: list[FuturesMove]) -> RegimeClassification:
    """Deterministically score the overnight board into one macro regime.

    Each regime accrues points from corroborating legs and move magnitude. The
    highest-scoring regime wins; confidence scales with the winning margin and
    the number of aligned legs. With no usable data we return ``neutral``.
    """
    usable = [m for m in moves if m.has_data]
    if not usable:
        return RegimeClassification(regime="neutral", label=REGIME_LABELS["neutral"],
                                    confidence=0.0, drivers=["no overnight data"], scores={})

    eq = _category_moves(moves, "equity_index")
    energy = _category_moves(moves, "energy")
    metals = _category_moves(moves, "metals")
    rates = _category_moves(moves, "rates")
    crypto = _category_moves(moves, "crypto")
    vol = _category_moves(moves, "vol")

    eq_avg = _avg([m.net_move_pct for m in eq])
    oil = next((m for m in energy if m.symbol == "CL"), None)
    gold = next((m for m in metals if m.symbol == "GC"), None)
    rates_avg = _avg([m.net_move_pct for m in rates])      # +ve = bond price up = yields down
    vix = next((m for m in vol if m.symbol == "VX"), None)
    btc = next((m for m in crypto if m.symbol == "BTC"), None)

    scores: dict[str, float] = {k: 0.0 for k in REGIME_LABELS if k not in ("neutral", "mixed")}
    drivers: dict[str, list[str]] = {k: [] for k in scores}

    def add(regime: str, pts: float, why: str):
        scores[regime] += pts
        if pts > 0:
            drivers[regime].append(why)

    # — Risk-on: equities up, VIX down, crypto up, gold flat/down —
    if eq_avg >= 0.2:
        add("risk_on", min(eq_avg / 0.6, 3.0), f"equity futures avg {eq_avg:+.2f}%")
    if vix and vix.net_move_pct <= -2.0:
        add("risk_on", min(abs(vix.net_move_pct) / 5.0, 2.0), f"VIX futures {vix.net_move_pct:+.2f}%")
    if btc and btc.net_move_pct >= 1.0:
        add("risk_on", min(btc.net_move_pct / 3.0, 1.5), f"BTC {btc.net_move_pct:+.2f}%")

    # — Risk-off: equities down, VIX up, gold up, bonds bid (rates_avg up) —
    if eq_avg <= -0.2:
        add("risk_off", min(abs(eq_avg) / 0.6, 3.0), f"equity futures avg {eq_avg:+.2f}%")
    if vix and vix.net_move_pct >= 2.0:
        add("risk_off", min(vix.net_move_pct / 5.0, 2.5), f"VIX futures {vix.net_move_pct:+.2f}%")
    if gold and gold.net_move_pct >= 0.4:
        add("risk_off", min(gold.net_move_pct / 1.0, 1.5), f"gold {gold.net_move_pct:+.2f}% (haven bid)")
    if rates_avg >= 0.2:
        add("risk_off", min(rates_avg / 0.5, 1.5), f"bonds bid (rates futures {rates_avg:+.2f}%)")

    # — Oil shock: crude move dominates, energy is the driver —
    if oil and (abs(oil.net_move_pct) >= _BIG_OIL_PCT or (oil.unusual and abs(oil.net_move_pct) >= 1.5)):
        magnitude = min(abs(oil.net_move_pct) / _BIG_OIL_PCT, 3.0)
        add("oil_shock", 2.0 + magnitude, f"crude {oil.net_move_pct:+.2f}%")
        # An oil spike with equities heavy reinforces a supply-shock read.
        if oil.net_move_pct > 0 and eq_avg < 0:
            add("oil_shock", 1.0, "crude up while equities soften")

    # — Inflation / rates shock: yields spike (bonds sold hard), equities pressured —
    if rates and rates_avg <= -_BIG_RATES_PCT:
        magnitude = min(abs(rates_avg) / _BIG_RATES_PCT, 3.0)
        add("inflation_rates_shock", 2.0 + magnitude, f"bonds sold (rates futures {rates_avg:+.2f}%, yields up)")
        if eq_avg < 0:
            add("inflation_rates_shock", 1.0, "equities pressured by higher yields")

    # — Safe-haven unwind: gold sold AND bonds sold (yields up) WITH equities up —
    if gold and gold.net_move_pct <= -0.4 and rates_avg < 0 and eq_avg > 0:
        add("safe_haven_unwind", 2.0 + min(abs(gold.net_move_pct) / 1.0, 2.0),
            f"gold {gold.net_move_pct:+.2f}% + bonds sold while equities firm")

    # — Volatility compression: everything quiet, ranges tight, VIX soft —
    quiet_legs = [m for m in usable if abs(m.net_move_pct) < 0.3 and not m.unusual]
    if len(quiet_legs) >= max(3, int(len(usable) * 0.7)):
        add("volatility_compression", 2.5, f"{len(quiet_legs)}/{len(usable)} contracts quiet")
        if vix and vix.net_move_pct <= 0:
            add("volatility_compression", 1.0, f"VIX futures {vix.net_move_pct:+.2f}%")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_regime, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score <= 0:
        return RegimeClassification(regime="neutral", label=REGIME_LABELS["neutral"],
                                    confidence=20.0, drivers=["no dominant overnight theme"],
                                    scores={k: round(v, 2) for k, v in scores.items()})

    # Confidence: magnitude of the winner plus separation from the runner-up.
    margin = top_score - second_score
    confidence = round(min(100.0, 35.0 + top_score * 9.0 + margin * 6.0), 1)

    # Crosscurrents: a strong runner-up means the board disagrees -> flag mixed.
    regime = top_regime
    label = REGIME_LABELS[top_regime]
    if second_score >= top_score * 0.8 and top_score >= 2.0:
        regime = "mixed"
        label = f"{REGIME_LABELS['mixed']} ({REGIME_LABELS[top_regime]} vs {REGIME_LABELS[ranked[1][0]]})"
        confidence = round(min(confidence, 55.0), 1)

    return RegimeClassification(
        regime=regime, label=label, confidence=confidence,
        drivers=drivers.get(top_regime, []) or ["overnight move"],
        scores={k: round(v, 2) for k, v in scores.items()},
    )


# ─── Watchlist + summary (pure) ───────────────────────────────────────────────

# Per-regime sector/ticker reaction map. Bias is the premarket lean for cash
# equities GIVEN the regime; it is a hypothesis to monitor, not a trade.
REGIME_WATCHLIST: dict[str, list[tuple[str, str, str]]] = {
    "risk_on": [
        ("QQQ", "bullish", "Risk-on overnight; high-beta tech tends to lead the bounce."),
        ("NVDA", "bullish", "Semis/AI lead in risk-on tape."),
        ("SMH", "bullish", "Semiconductor basket benefits from risk appetite."),
        ("IWM", "bullish", "Small caps catch a bid when risk is on."),
        ("UVXY", "bearish", "Vol products bleed as VIX futures fall."),
    ],
    "risk_off": [
        ("SPY", "bearish", "Broad risk-off; index pressured premarket."),
        ("QQQ", "bearish", "High-beta tech leads the downside in risk-off."),
        ("GLD", "bullish", "Gold catches the safe-haven bid."),
        ("TLT", "bullish", "Long bonds rally as money rotates to safety."),
        ("UVXY", "bullish", "Vol expands with the risk-off move."),
    ],
    "oil_shock": [
        ("XLE", "bullish", "Energy sector reprices to the crude move."),
        ("XOM", "bullish", "Integrated majors track crude."),
        ("OXY", "bullish", "E&P leverage to crude price."),
        ("USO", "bullish", "Direct crude proxy."),
        ("DAL", "bearish", "Airlines/transports pressured by higher fuel costs."),
    ],
    "inflation_rates_shock": [
        ("TLT", "bearish", "Long-duration bonds sell off as yields spike."),
        ("XLF", "bullish", "Banks can benefit from higher yields."),
        ("QQQ", "bearish", "Long-duration growth de-rates on higher yields."),
        ("XLU", "bearish", "Rate-sensitive utilities pressured."),
        ("GLD", "bearish", "Real-yield jump weighs on gold."),
    ],
    "safe_haven_unwind": [
        ("GLD", "bearish", "Haven assets sold as fear unwinds."),
        ("TLT", "bearish", "Bonds sold alongside gold."),
        ("SPY", "bullish", "Equities firm as the haven bid unwinds."),
        ("GDX", "bearish", "Gold miners track bullion lower."),
    ],
    "volatility_compression": [
        ("SVXY", "bullish", "Short-vol benefits from compression."),
        ("SPY", "neutral", "Tight overnight range; fade extremes, await catalyst."),
        ("UVXY", "bearish", "Vol products decay in a quiet tape."),
    ],
    "neutral": [
        ("SPY", "neutral", "No dominant overnight theme; wait for the cash open."),
    ],
    "mixed": [
        ("SPY", "neutral", "Crosscurrents overnight; reduce conviction until one theme wins."),
        ("GLD", "neutral", "Conflicting macro legs; monitor for resolution."),
    ],
}


def build_watchlist(regime: RegimeClassification, moves: list[FuturesMove]) -> list[WatchlistEntry]:
    """Suggested cash-equity watchlist for the regime, enriched by the contracts
    that actually moved unusually (their mapped reaction tickers get surfaced)."""
    entries: list[WatchlistEntry] = []
    seen: set[str] = set()
    for ticker, bias, rationale in REGIME_WATCHLIST.get(regime.regime, REGIME_WATCHLIST["neutral"]):
        if ticker not in seen:
            entries.append(WatchlistEntry(ticker=ticker, bias=bias, rationale=rationale))
            seen.add(ticker)

    # Surface reaction tickers for any contract that moved unusually overnight.
    for m in moves:
        if not (m.has_data and m.unusual):
            continue
        spec = CONTRACTS_BY_SYMBOL.get(m.symbol)
        if not spec:
            continue
        bias = "bullish" if m.direction == "up" else "bearish" if m.direction == "down" else "neutral"
        for rt in spec.reaction_tickers[:2]:
            if rt not in seen:
                entries.append(WatchlistEntry(
                    ticker=rt, bias=bias,
                    rationale=f"{spec.name} {m.net_move_pct:+.2f}% overnight ({m.move_vs_avg}x avg).",
                ))
                seen.add(rt)
    return entries


def likely_catalyst(regime: RegimeClassification, moves: list[FuturesMove]) -> str:
    """A plain-English best-guess catalyst label from the regime + biggest mover."""
    biggest = max((m for m in moves if m.has_data), key=lambda m: abs(m.net_move_pct), default=None)
    base = {
        "oil_shock": "Energy supply/geopolitical catalyst (crude-led)",
        "inflation_rates_shock": "Hot inflation print or hawkish rates repricing",
        "risk_off": "Macro/geopolitical risk-off catalyst",
        "risk_on": "Risk-on catalyst (dovish data or easing tension)",
        "safe_haven_unwind": "De-escalation / haven unwind",
        "volatility_compression": "No major overnight catalyst (pre-event drift)",
        "neutral": "No dominant overnight catalyst",
        "mixed": "Competing macro catalysts overnight",
    }.get(regime.regime, "Overnight macro move")
    if biggest is not None and biggest.unusual:
        return f"{base}; biggest mover {biggest.name} {biggest.net_move_pct:+.2f}%."
    return base + "."


def build_summary(regime: RegimeClassification, moves: list[FuturesMove],
                  catalyst_ts: Optional[str]) -> str:
    """Premarket narrative: what moved, when, likely catalyst, confidence."""
    movers = sorted((m for m in moves if m.has_data), key=lambda m: abs(m.net_move_pct), reverse=True)
    top = movers[:4]
    what = ", ".join(f"{m.symbol} {m.net_move_pct:+.2f}%" for m in top) or "no contracts with data"
    when = ""
    moved_times = [m.moved_at for m in top if m.moved_at]
    if moved_times:
        when = f" Largest moves clustered around {moved_times[0]}."
    cat = likely_catalyst(regime, moves)
    cat_window = ""
    if catalyst_ts:
        cm = [m for m in top if m.catalyst_move_pct is not None]
        if cm:
            cat_window = " Since catalyst: " + ", ".join(
                f"{m.symbol} {m.catalyst_move_pct:+.2f}%" for m in cm) + "."
    return (f"Overnight regime: {regime.label} (confidence {regime.confidence:.0f}). "
            f"What moved: {what}.{when} Likely catalyst: {cat}{cat_window}")


# ─── Provider interface ───────────────────────────────────────────────────────

@runtime_checkable
class FuturesDataProvider(Protocol):
    """Returns the overnight 1m/5m series for a contract, or None if no data."""
    def fetch_overnight(self, spec: FuturesContractSpec, session_date: str,
                        timespan: str = "minute", multiplier: int = 5) -> Optional[OvernightSeries]: ...


class StubFuturesDataProvider:
    """Default provider: always 'no data'. Inject a live feed to activate."""
    def fetch_overnight(self, spec: FuturesContractSpec, session_date: str,  # noqa: ARG002
                        timespan: str = "minute", multiplier: int = 5) -> Optional[OvernightSeries]:
        return None


# Polygon/Massive Futures v1 aggregates. Base URL + path are env-overridable so a
# deployment can point at the exact futures product/symbology it has access to.
# The real Futures v1 aggregates endpoint is query-param based and addresses a
# specific *contract* ticker (e.g. ESM6), not a product root — window bounds are
# nanosecond epochs on `window_start`, and `resolution` is "<n>_<unit>".
POLYGON_FUTURES_BASE = os.getenv("POLYGON_FUTURES_BASE_URL", "https://api.polygon.io").rstrip("/")
POLYGON_FUTURES_AGGS_PATH = os.getenv("POLYGON_FUTURES_AGGS_PATH", "/futures/v1/aggs/{ticker}")
# Free "Futures Basic" allows ~5 requests/minute; set a per-request floor so a
# full board (12 contracts) throttles itself instead of getting 429'd. Seconds.
POLYGON_FUTURES_MIN_INTERVAL_SEC = float(os.getenv("POLYGON_FUTURES_MIN_INTERVAL_SEC", "0") or 0)


# CME-style month codes and per-product listing cycles, used to build the
# front-month *contract* ticker deterministically — so we never need a per-symbol
# /futures/v1/contracts lookup (which also returns placeholder data on the free
# plan). One aggregates call per contract; the agent degrades gracefully if the
# constructed front month happens to have no data.
_MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_ALL_MONTHS = list(range(1, 13))
_QUARTERLY = [3, 6, 9, 12]
# By contract symbol; falls back to the category default below when absent.
_LISTING_MONTHS_BY_SYMBOL: dict[str, list[int]] = {
    "GC": [2, 4, 6, 8, 10, 12],
    "SI": [3, 5, 7, 9, 12],
}
_LISTING_MONTHS_BY_CATEGORY: dict[str, list[int]] = {
    "equity_index": _QUARTERLY,
    "rates": _QUARTERLY,
    "energy": _ALL_MONTHS,
    "metals": _ALL_MONTHS,
    "crypto": _ALL_MONTHS,
    "vol": _ALL_MONTHS,
}


def _listing_months(spec: FuturesContractSpec) -> list[int]:
    return (_LISTING_MONTHS_BY_SYMBOL.get(spec.symbol)
            or _LISTING_MONTHS_BY_CATEGORY.get(spec.category, _QUARTERLY))


# Per-product roll buffers. A contract's *delivery* month code is not when it stops
# trading: energy (CL/NG) expire ~a month BEFORE delivery, so the calendar-month
# code is already dead by the time the delivery month arrives. Each rule is
# (month_offset, day) — an estimated last-trade DATE = day-of (delivery_month +
# month_offset). Dates are picked deliberately a touch EARLY so we roll forward
# before a contract actually expires and never construct a dead ticker. These are
# approximations (good enough to land on the active front month for a daily/EOD
# read), not exchange-exact expiry calendars.
_EXPIRY_RULE_BY_SYMBOL: dict[str, tuple[int, int]] = {
    "CL": (-1, 20),   # crude: ~3 business days before the 25th of the prior month
    "NG": (-1, 25),   # nat gas: ~3 business days before the 1st of delivery month
}
_EXPIRY_RULE_BY_CATEGORY: dict[str, tuple[int, int]] = {
    "equity_index": (0, 18),  # quarterly, 3rd Friday of delivery month
    "rates": (0, 21),         # quarterly, ~3rd week of delivery month
    "metals": (0, 27),        # delivery-month, late in the month
    "energy": (-1, 22),       # default energy roll: month before delivery
    "crypto": (0, 24),        # CME bitcoin: last Friday of delivery month
    "vol": (0, 17),           # VX: ~3rd week of delivery month
}


def _expiry_rule(spec: FuturesContractSpec) -> tuple[int, int]:
    return (_EXPIRY_RULE_BY_SYMBOL.get(spec.symbol)
            or _EXPIRY_RULE_BY_CATEGORY.get(spec.category, (0, 18)))


def _contract_expiry(spec: FuturesContractSpec, delivery_month: int, year: int) -> date:
    """Estimated last-trade date for the contract with this delivery month/year."""
    offset, day = _expiry_rule(spec)
    # Apply the (possibly negative) month offset, wrapping the year if needed.
    m0 = delivery_month - 1 + offset
    y = year + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, day)


def front_month_ticker(spec: FuturesContractSpec, ref_date: Optional[datetime] = None) -> str:
    """Construct the active (unexpired) front-month contract ticker, e.g. ``ESM6``.

    Walks the product's listed delivery months across this year and next, and
    returns the first contract whose estimated last-trade date is on or after the
    reference date. The ticker month CODE always reflects the delivery month; the
    roll buffer only governs *which* delivery month is still live. ``ref_date``
    defaults to now (ET). The root comes from ``spec.polygon_ticker``.
    """
    ref = ref_date or datetime.now(_ET)
    ref_day = ref.date()
    months = _listing_months(spec)
    for y in (ref.year, ref.year + 1):
        for m in months:
            if _contract_expiry(spec, m, y) >= ref_day:
                return f"{spec.polygon_ticker}{_MONTH_CODES[m]}{y % 10}"
    # Unreachable for sane calendars; fall back to first listed month next year.
    return f"{spec.polygon_ticker}{_MONTH_CODES[months[0]]}{(ref.year + 1) % 10}"


class PolygonFuturesProvider:
    """Live overnight aggregates from Polygon/Massive Futures v1.

    Graceful degradation: missing key, bad ticker, network issues, or a 429 rate
    limit all return None so the agent treats that contract as 'no data' (neutral)
    instead of failing the whole premarket read. Read-only — it only GETs
    aggregates. Note: the free plan is EOD/delayed, so the *current* overnight
    session's intraday bars may not be available until later; historical sessions
    backfill fine for the SQLite-backed backtests.
    """

    def __init__(self, api_key: Optional[str] = None,
                 min_interval_sec: Optional[float] = None):
        self.api_key = (api_key or os.getenv("POLYGON_API_KEY", "")).strip()
        self.min_interval_sec = (POLYGON_FUTURES_MIN_INTERVAL_SEC
                                 if min_interval_sec is None else min_interval_sec)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        if self.min_interval_sec <= 0:
            return
        wait = self.min_interval_sec - (_time_module.monotonic() - self._last_request_at)
        if wait > 0:
            _time_module.sleep(wait)

    def fetch_overnight(self, spec: FuturesContractSpec, session_date: str,
                        timespan: str = "minute", multiplier: int = 5) -> Optional[OvernightSeries]:
        if not self.api_key:
            return None
        ref = datetime.fromisoformat(session_date).replace(tzinfo=_ET) if session_date else None
        ticker = front_month_ticker(spec, ref_date=ref)
        start_utc, end_utc = overnight_window_utc(session_date)
        query = urlencode({
            "resolution": f"{multiplier}_{timespan}",
            "window_start.gte": _to_ns(start_utc),
            "window_start.lt": _to_ns(end_utc),
            "order": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        })
        url = POLYGON_FUTURES_BASE + POLYGON_FUTURES_AGGS_PATH.format(ticker=ticker) + "?" + query
        self._throttle()
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        finally:
            self._last_request_at = _time_module.monotonic()
        results = data.get("results") or []
        if not results:
            return None
        # The API may return bars newest-first regardless of the `order` param, so
        # sort chronologically — compute_move relies on bars[0] being the earliest
        # (its open is the prior-close proxy) and bars[-1] being the latest.
        results = sorted(
            (r for r in results if r.get("open") is not None and r.get("window_start") is not None),
            key=lambda r: int(r["window_start"]),
        )
        bars = [
            OvernightBar(
                ts=datetime.fromtimestamp(int(r["window_start"]) / 1e9, tz=timezone.utc).astimezone(_ET).isoformat(),
                open=float(r.get("open", 0)), high=float(r.get("high", 0)),
                low=float(r.get("low", 0)), close=float(r.get("close", 0)),
                volume=float(r.get("volume", 0) or 0),
            )
            for r in results
        ]
        if not bars:
            return None
        # Prior close: the open of the first overnight bar is the best free proxy
        # for the prior settlement when a dedicated prior-close endpoint isn't wired.
        prior_close = float(bars[0].open)
        return OvernightSeries(symbol=spec.symbol, bars=bars, prior_close=prior_close)


# ─── Session windows ──────────────────────────────────────────────────────────

def session_date_for(now_et: Optional[datetime] = None) -> str:
    """The cash-session date (ET, YYYY-MM-DD) that the current overnight precedes.

    Between 6pm and midnight ET the overnight belongs to the NEXT calendar day's
    session; from midnight to 9:30am it belongs to today's session.
    """
    now = now_et or datetime.now(_ET)
    d = now.date()
    if now.time() >= time(18, 0):
        d = d + timedelta(days=1)
    return d.isoformat()


def overnight_window_utc(session_date: str) -> tuple[datetime, datetime]:
    """UTC [start, end] for the 6pm-ET-prior-day -> 9:30am-ET overnight window."""
    d = datetime.fromisoformat(session_date).date()
    start_et = datetime.combine(d - timedelta(days=1), time(18, 0), tzinfo=_ET)
    end_et = datetime.combine(d, time(9, 30), tzinfo=_ET)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _to_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


# ─── Top-level build (orchestration, still no I/O of its own) ──────────────────

def build_pulse_report(provider: FuturesDataProvider,
                       session_date: Optional[str] = None,
                       catalyst_ts: Optional[str] = None,
                       timespan: str = "minute",
                       multiplier: int = 5) -> FuturesPulseReport:
    """Fetch each contract's overnight series via the provider, compute moves,
    classify the regime, and assemble the premarket report. Read-only."""
    session_date = session_date or session_date_for()
    moves: list[FuturesMove] = []
    provider_status: dict[str, str] = {}
    for spec in TRACKED_CONTRACTS:
        try:
            series = provider.fetch_overnight(spec, session_date, timespan=timespan, multiplier=multiplier)
        except Exception:
            series = None
            provider_status[spec.symbol] = "error"
        move = compute_move(spec, series, catalyst_ts=catalyst_ts)
        provider_status.setdefault(spec.symbol, "ok" if move.has_data else "no_data")
        moves.append(move)

    regime = classify_regime(moves)
    watchlist = build_watchlist(regime, moves)
    summary = build_summary(regime, moves, catalyst_ts)
    has_any = any(m.has_data for m in moves)

    notes = [
        "Read-only premarket research. No trades are placed from futures data.",
        "Overnight window: 6:00pm ET prior day to 9:30am ET.",
    ]
    if not has_any:
        notes.append("No futures provider data available — set POLYGON_API_KEY and "
                     "POLYGON_FUTURES_* to enable the live Polygon/Massive Futures v1 read.")

    return FuturesPulseReport(
        status="ok" if has_any else "no_data",
        session_date=session_date,
        generated_at=datetime.now(timezone.utc).isoformat(),
        catalyst_timestamp=catalyst_ts,
        moves=moves,
        regime=regime,
        summary=summary,
        watchlist=watchlist,
        notes=notes,
        provider_status=provider_status,
    )


def report_to_strategy_signals(report: FuturesPulseReport) -> list[dict]:
    """Convert the pulse watchlist into AlphaLabs idea/signal payloads.

    These mirror the daily-brief signals[] shape so they can be fed into the
    existing scoring/import path. They are candidates only — nothing here places
    or approves a trade.
    """
    signals: list[dict] = []
    if report.status != "ok":
        return signals
    for entry in report.watchlist:
        if entry.bias not in ("bullish", "bearish"):
            continue
        signals.append({
            "ticker": entry.ticker,
            "asset_type": "equity",
            "bias": entry.bias,
            "confidence": round(min(0.85, 0.55 + report.regime.confidence / 250.0), 2),
            "timeframe": "intraday",
            "thesis": (f"Overnight Futures Pulse — {report.regime.label}: {entry.rationale} "
                       f"{report.summary}"),
            "reason": f"Overnight Futures Pulse {report.regime.label}: {entry.rationale}",
            "catalyst": likely_catalyst(report.regime, report.moves),
            "source": "futures_pulse",
            "timestamp": report.generated_at,
            "theme": f"Overnight Futures Pulse: {report.regime.label}",
            "strategy_tags": ["overnight futures pulse", report.regime.regime],
        })
    return signals
