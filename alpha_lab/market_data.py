from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


COINGECKO_BTC_MARKETS_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&ids=bitcoin&price_change_percentage=24h,7d,14d"
)
COINGECKO_BTC_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90"


CRYPTO_FLOW_IDS = ["bitcoin", "ethereum", "solana", "chainlink", "avalanche-2", "render-token", "near"]
STOCK_FLOW_GROUPS = {
    "AI Stocks": ["NVDA", "AMD", "MSFT", "META", "AVGO", "PLTR", "SMCI", "ORCL"],
    "Semiconductors": ["NVDA", "AMD", "AVGO", "SMH", "TSM", "ASML", "ARM"],
    "Risk ETFs": ["SPY", "QQQ", "IWM", "ARKK", "SMH"],
    "Oil / Energy": ["USO", "XLE", "XOM", "CVX", "OXY", "SLB"],
}
OIL_SYMBOLS = STOCK_FLOW_GROUPS["Oil / Energy"]
TRENDING_STOCK_UNIVERSE = sorted({
    "NVDA", "AMD", "MSFT", "META", "AVGO", "PLTR", "SMCI", "ORCL",
    "TSLA", "COIN", "MSTR", "AAPL", "AMZN", "GOOGL", "TSM", "ASML",
    "ARM", "SPY", "QQQ", "IWM", "ARKK", "SMH",
    "USO", "XLE", "XOM", "CVX", "OXY", "SLB",
})

BUSINESS_BRIEFS: dict[str, dict[str, Any]] = {
    "AAPL": {
        "name": "Apple",
        "business": "Consumer hardware, software, and services ecosystem built around iPhone, Mac, iPad, wearables, App Store, payments, and subscriptions.",
        "drivers": ["iPhone cycle", "Services margin", "AI/device refresh expectations", "China demand"],
        "watch": "Watch product-cycle demand, gross margin, China exposure, and whether services growth offsets hardware cyclicality.",
    },
    "AMD": {
        "name": "Advanced Micro Devices",
        "business": "Designs CPUs, GPUs, adaptive chips, and data-center accelerators used in PCs, servers, gaming, embedded, and AI workloads.",
        "drivers": ["AI accelerator adoption", "Data-center CPU share", "PC cycle", "Gaming and embedded demand"],
        "watch": "Watch AI GPU traction versus NVIDIA, server share gains, margin expansion, and inventory cycles.",
    },
    "AMZN": {
        "name": "Amazon",
        "business": "E-commerce, logistics, cloud infrastructure through AWS, advertising, subscriptions, and digital media.",
        "drivers": ["AWS growth", "Retail margin", "Ad growth", "Consumer spending"],
        "watch": "Watch AWS reacceleration, retail operating leverage, ad monetization, and capex tied to AI/cloud infrastructure.",
    },
    "ARM": {
        "name": "Arm Holdings",
        "business": "Licenses CPU architecture and chip IP used across smartphones, embedded devices, servers, automotive, and edge AI designs.",
        "drivers": ["Royalty rates", "Cloud/AI server penetration", "Smartphone cycle", "Automotive and edge devices"],
        "watch": "Watch valuation sensitivity, royalty growth, adoption beyond mobile, and customer concentration around major chipmakers.",
    },
    "ASML": {
        "name": "ASML",
        "business": "Sells advanced lithography systems, especially EUV tools, that chipmakers need to manufacture leading-edge semiconductors.",
        "drivers": ["Semiconductor capex", "EUV/High-NA demand", "TSMC/Samsung/Intel spending", "AI chip capacity buildout"],
        "watch": "Watch order backlog, export restrictions, customer capex timing, and whether leading-edge AI demand supports new tool orders.",
    },
    "AVGO": {
        "name": "Broadcom",
        "business": "Semiconductor and infrastructure software company with networking, custom silicon, broadband, wireless, storage, and VMware assets.",
        "drivers": ["AI networking", "Custom ASIC demand", "VMware integration", "Enterprise infrastructure spend"],
        "watch": "Watch AI networking/custom silicon growth, software cash flow, debt reduction, and integration execution.",
    },
    "COIN": {
        "name": "Coinbase",
        "business": "Crypto exchange, custody, staking, stablecoin, and institutional platform business tied to digital-asset activity.",
        "drivers": ["Crypto trading volume", "Stablecoin revenue", "Institutional adoption", "Regulatory clarity"],
        "watch": "Watch crypto volumes, fee compression, regulatory changes, and dependence on crypto market risk appetite.",
    },
    "GOOGL": {
        "name": "Alphabet",
        "business": "Search, YouTube, Google Cloud, Android, ads technology, subscriptions, hardware, and AI research/products.",
        "drivers": ["Search ad growth", "YouTube monetization", "Cloud profitability", "AI product integration"],
        "watch": "Watch search share pressure from AI, ad-cycle sensitivity, cloud margins, and regulatory risk.",
    },
    "META": {
        "name": "Meta Platforms",
        "business": "Social apps and messaging across Facebook, Instagram, WhatsApp, and Messenger, plus ads, AI infrastructure, and Reality Labs.",
        "drivers": ["Ad pricing", "Reels/AI engagement", "Cost discipline", "Reality Labs spending"],
        "watch": "Watch ad demand, AI-driven engagement, capex intensity, regulatory pressure, and metaverse investment losses.",
    },
    "MSFT": {
        "name": "Microsoft",
        "business": "Enterprise software, cloud infrastructure, productivity apps, Windows, security, gaming, LinkedIn, and AI copilots.",
        "drivers": ["Azure growth", "AI monetization", "Office/Teams seat expansion", "Enterprise software budgets"],
        "watch": "Watch Azure AI demand, cloud margins, enterprise renewal strength, and capex needed for AI infrastructure.",
    },
    "MSTR": {
        "name": "MicroStrategy",
        "business": "Enterprise analytics software company that also holds a large Bitcoin treasury, making the stock highly sensitive to BTC.",
        "drivers": ["Bitcoin price", "Capital markets access", "BTC premium/discount", "Software cash flow"],
        "watch": "Watch leverage, dilution, BTC volatility, financing terms, and whether market cap trades far from underlying Bitcoin exposure.",
    },
    "NVDA": {
        "name": "NVIDIA",
        "business": "GPU, networking, software, and accelerated-computing platform supplier for AI data centers, gaming, visualization, robotics, and autos.",
        "drivers": ["AI data-center demand", "GPU supply", "Networking attach", "Gross margin"],
        "watch": "Watch hyperscaler capex, competition/custom silicon, supply constraints, China restrictions, and margin durability.",
    },
    "ORCL": {
        "name": "Oracle",
        "business": "Enterprise database, applications, cloud infrastructure, and SaaS provider with growing AI/cloud infrastructure exposure.",
        "drivers": ["OCI growth", "Database/cloud migrations", "AI infrastructure demand", "Enterprise apps"],
        "watch": "Watch cloud backlog conversion, capex needs, debt load, and whether OCI growth can keep outpacing legacy pressure.",
    },
    "PLTR": {
        "name": "Palantir",
        "business": "Data integration, analytics, and AI operating platforms for government and commercial customers.",
        "drivers": ["Commercial AIP adoption", "Government contracts", "Net retention", "Operating leverage"],
        "watch": "Watch valuation, commercial customer growth, government budget timing, and whether AI pilots convert into durable contracts.",
    },
    "SMCI": {
        "name": "Super Micro Computer",
        "business": "Builds high-performance servers and rack-scale systems used in AI, cloud, storage, and enterprise data centers.",
        "drivers": ["AI server demand", "GPU allocation", "Data-center buildouts", "Margin and working capital"],
        "watch": "Watch customer concentration, supply availability, accounting/governance concerns, and margin pressure in server hardware.",
    },
    "TSLA": {
        "name": "Tesla",
        "business": "Electric vehicles, energy storage, solar, charging, software, autonomy efforts, and robotics ambitions.",
        "drivers": ["EV deliveries", "Vehicle margins", "Energy storage growth", "Autonomy/FSD expectations"],
        "watch": "Watch price cuts, EV competition, margin compression, regulatory credits, and timing risk around autonomy claims.",
    },
    "TSM": {
        "name": "Taiwan Semiconductor Manufacturing",
        "business": "World-scale semiconductor foundry manufacturing advanced chips for fabless designers and major technology customers.",
        "drivers": ["Leading-edge node demand", "AI/HPC chips", "Apple cycle", "Foundry pricing and utilization"],
        "watch": "Watch geopolitical risk, capex intensity, customer concentration, and demand for advanced-node capacity.",
    },
    "SPY": {
        "name": "SPDR S&P 500 ETF",
        "business": "ETF tracking large-cap U.S. equities through the S&P 500; useful as a broad market risk proxy.",
        "drivers": ["Large-cap earnings", "Rates", "Index flows", "Risk appetite"],
        "watch": "Watch breadth, mega-cap concentration, rate expectations, and whether index flow confirms single-stock moves.",
    },
    "QQQ": {
        "name": "Invesco QQQ ETF",
        "business": "ETF tracking the Nasdaq-100, heavily exposed to large-cap technology and growth stocks.",
        "drivers": ["Mega-cap tech", "AI capex cycle", "Rates", "Growth-stock sentiment"],
        "watch": "Watch concentration in top holdings, rate sensitivity, and whether tech breadth supports headline strength.",
    },
    "IWM": {
        "name": "iShares Russell 2000 ETF",
        "business": "ETF tracking U.S. small-cap stocks; often used as a domestic cyclicals and rate-sensitivity proxy.",
        "drivers": ["Rate expectations", "Credit conditions", "Domestic growth", "Small-cap earnings"],
        "watch": "Watch financing conditions, breadth, regional-bank/credit stress, and whether small caps confirm risk-on moves.",
    },
    "ARKK": {
        "name": "ARK Innovation ETF",
        "business": "Actively managed ETF focused on high-growth innovation themes such as AI, automation, genomics, fintech, and crypto-linked equities.",
        "drivers": ["Speculative growth appetite", "Rates", "Top holding momentum", "Innovation theme flows"],
        "watch": "Watch rate sensitivity, concentration, drawdown risk, and whether liquidity flows reflect risk-on speculation or forced selling.",
    },
    "SMH": {
        "name": "VanEck Semiconductor ETF",
        "business": "ETF focused on semiconductor designers, equipment makers, and foundries; useful as a chip-sector liquidity proxy.",
        "drivers": ["AI chip demand", "Semiconductor capex", "Memory/foundry cycle", "NVIDIA/TSMC/ASML moves"],
        "watch": "Watch sector concentration, export controls, capex cycle turns, and whether equipment/foundry names confirm AI-chip leadership.",
    },
    "USO": {
        "name": "United States Oil Fund",
        "business": "ETF designed to track near-month WTI crude oil futures exposure, making it a liquid oil-price proxy rather than an operating company.",
        "drivers": ["WTI crude", "Futures curve/roll yield", "OPEC supply", "Demand shocks"],
        "watch": "Watch crude inventory data, OPEC headlines, futures curve contango/backwardation, and geopolitical supply risk.",
    },
    "XLE": {
        "name": "Energy Select Sector SPDR ETF",
        "business": "ETF tracking large U.S. energy equities, including integrated oil majors, exploration/production, and energy services exposure.",
        "drivers": ["Oil and gas prices", "Energy equity flows", "Free cash flow", "Dividend/buyback yields"],
        "watch": "Watch crude/natural gas trends, refining margins, capital returns, and whether energy equities confirm commodity moves.",
    },
    "XOM": {
        "name": "Exxon Mobil",
        "business": "Integrated oil and gas major with upstream production, refining, chemicals, LNG, and low-carbon projects.",
        "drivers": ["Brent/WTI prices", "Production volumes", "Refining margins", "Capital returns"],
        "watch": "Watch commodity price sensitivity, reserve replacement, buybacks/dividends, refining spreads, and project execution.",
    },
    "CVX": {
        "name": "Chevron",
        "business": "Integrated energy company with upstream oil/gas production, refining, chemicals, LNG, and shareholder-return focus.",
        "drivers": ["Oil and LNG prices", "Permian output", "Refining margins", "Dividend coverage"],
        "watch": "Watch production growth, acquisition integration, capex discipline, free cash flow, and commodity-cycle exposure.",
    },
    "OXY": {
        "name": "Occidental Petroleum",
        "business": "Oil and gas producer with Permian exposure, chemicals, midstream assets, and carbon-management projects.",
        "drivers": ["WTI prices", "Permian production", "Debt reduction", "Carbon capture optionality"],
        "watch": "Watch leverage, commodity beta, free cash flow, Berkshire-related market interest, and capex discipline.",
    },
    "SLB": {
        "name": "SLB",
        "business": "Oilfield services and technology provider supporting drilling, completions, reservoir, digital, and international energy projects.",
        "drivers": ["Global upstream capex", "International drilling", "Service pricing", "Offshore activity"],
        "watch": "Watch energy producer capex plans, international activity, margins, and whether service demand confirms oil-cycle strength.",
    },
}

FUNDAMENTAL_NOTES: dict[str, dict[str, Any]] = {
    "AAPL": {"model": "Premium hardware ecosystem plus high-margin services.", "key_metrics": ["iPhone revenue", "Services growth", "Gross margin", "China sales"], "risks": ["Hardware cycle", "Regulation", "China demand"]},
    "AMZN": {"model": "Retail scale with AWS/cloud and ads as major profit pools.", "key_metrics": ["AWS growth", "Operating margin", "Ad revenue", "Capex"], "risks": ["Cloud slowdown", "Consumer weakness", "AI infrastructure spend"]},
    "ORCL": {"model": "Enterprise software/database cash flow plus cloud infrastructure growth.", "key_metrics": ["OCI growth", "Remaining performance obligations", "Cloud margin", "Debt/capex"], "risks": ["Cloud execution", "High capex", "Legacy transition"]},
    "NVDA": {"model": "High-margin accelerator platform tied to AI data-center capex.", "key_metrics": ["Data-center revenue", "Gross margin", "Networking attach", "Customer concentration"], "risks": ["AI capex digestion", "Export limits", "Custom silicon competition"]},
    "AMD": {"model": "CPU/GPU designer trying to scale data-center AI accelerators.", "key_metrics": ["Data-center revenue", "AI GPU shipments", "Gross margin", "PC cycle"], "risks": ["NVIDIA competition", "Execution", "Inventory cycle"]},
    "MSFT": {"model": "Enterprise software and cloud subscription engine with AI monetization upside.", "key_metrics": ["Azure growth", "Commercial bookings", "Cloud margin", "AI capex"], "risks": ["Cloud growth deceleration", "Capex intensity", "Regulation"]},
    "META": {"model": "Advertising cash-flow engine funding AI infrastructure and Reality Labs.", "key_metrics": ["Ad impressions/pricing", "Operating margin", "Capex", "Reality Labs loss"], "risks": ["Ad cycle", "Regulation", "Metaverse losses"]},
    "GOOGL": {"model": "Search/YouTube ads plus cloud, with AI defending and extending search utility.", "key_metrics": ["Search revenue", "Cloud margin", "TAC", "AI capex"], "risks": ["Search disruption", "Antitrust", "Ad cycle"]},
    "PLTR": {"model": "Government and commercial AI/data platforms with high operating leverage if contracts scale.", "key_metrics": ["Commercial revenue", "Government revenue", "Customer count", "Remaining deal value"], "risks": ["Valuation", "Contract timing", "Pilot conversion"]},
    "ASML": {"model": "Near-monopoly lithography equipment supplier for leading-edge chipmaking.", "key_metrics": ["Bookings", "Backlog", "Gross margin", "Customer capex"], "risks": ["Export controls", "Semi capex cycle", "Customer concentration"]},
    "USO": {"model": "Commodity ETF proxy; performance can diverge from spot oil due to futures roll.", "key_metrics": ["WTI futures", "Roll yield", "Inventories", "OPEC supply"], "risks": ["Contango drag", "Headline risk", "Demand shocks"]},
    "XLE": {"model": "Energy equity basket tied to oil/gas prices and shareholder capital returns.", "key_metrics": ["Crude trend", "Energy earnings", "Free cash flow", "Buybacks/dividends"], "risks": ["Commodity reversal", "Policy risk", "Refining margin pressure"]},
    "XOM": {"model": "Integrated oil major balancing upstream commodity upside with refining/chemicals and capital returns.", "key_metrics": ["Production", "Realized prices", "Refining margins", "Free cash flow"], "risks": ["Oil drawdown", "Project execution", "Energy transition pressure"]},
    "CVX": {"model": "Integrated oil major with upstream cash generation and dividend discipline.", "key_metrics": ["Production", "Dividend coverage", "Permian/LNG output", "Free cash flow"], "risks": ["Commodity beta", "Acquisition integration", "Capex overruns"]},
    "OXY": {"model": "Levered oil producer with high WTI sensitivity and debt-paydown focus.", "key_metrics": ["WTI price", "Permian volumes", "Debt", "Free cash flow"], "risks": ["Leverage", "Commodity volatility", "Capex discipline"]},
    "SLB": {"model": "Oilfield services business tied to global upstream activity and service pricing.", "key_metrics": ["International revenue", "Margins", "Backlog/activity", "Producer capex"], "risks": ["Capex cuts", "Oil downturn", "Pricing pressure"]},
}

COINGECKO_CRYPTO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
ALPACA_STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_LATEST_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars/latest"


def get_business_profiles() -> dict[str, Any]:
    symbols = sorted(TRENDING_STOCK_UNIVERSE)
    return {
        "status": "ok",
        "source": "AlphaLab curated business/fundamental notes",
        "source_note": "Business descriptions and fundamental notes are curated qualitative profiles. They are not live financial statements, earnings estimates, or valuation feeds.",
        "profiles": [{"ticker": symbol, **get_business_brief(symbol)} for symbol in symbols],
    }


def get_liquidity_flows() -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    crypto = _crypto_liquidity_flows()
    stocks = _stock_liquidity_flows()
    groups = [crypto] + stocks
    return {
        "status": "ok" if any(group.get("status") == "ok" for group in groups) else "partial",
        "fetched_at": fetched_at,
        "source_note": "Liquidity flow is estimated from source-backed volume and dollar-volume proxies; it is not full exchange order-flow or fund-flow data.",
        "groups": groups,
    }


def _crypto_liquidity_flows() -> dict[str, Any]:
    params = urlencode({
        "vs_currency": "usd",
        "ids": ",".join(CRYPTO_FLOW_IDS),
        "price_change_percentage": "24h,7d",
        "order": "market_cap_desc",
    })
    try:
        rows = _fetch_json(f"{COINGECKO_CRYPTO_MARKETS_URL}?{params}")
    except Exception as exc:
        return {"name": "Crypto Majors", "status": "unavailable", "error": str(exc), "source": "CoinGecko /coins/markets"}
    assets = []
    total_volume = 0.0
    weighted_24h = 0.0
    for row in rows:
        volume = _num(row.get("total_volume")) or 0.0
        change = _num(row.get("price_change_percentage_24h_in_currency")) or 0.0
        total_volume += volume
        weighted_24h += change * volume
        assets.append({
            "symbol": str(row.get("symbol", "")).upper(),
            "name": row.get("name"),
            "price": _num(row.get("current_price")),
            "volume_24h": volume,
            "change_24h_pct": _num(row.get("price_change_percentage_24h_in_currency")),
            "change_7d_pct": _num(row.get("price_change_percentage_7d_in_currency")),
        })
    avg_24h = weighted_24h / total_volume if total_volume else None
    return {
        "name": "Crypto Majors",
        "status": "ok",
        "source": "CoinGecko /coins/markets",
        "metric": "24h spot volume",
        "dollar_volume": total_volume,
        "volume_read": _volume_read(avg_24h, None),
        "weighted_change_24h_pct": avg_24h,
        "assets": sorted(assets, key=lambda item: item.get("volume_24h") or 0, reverse=True),
        "note": "Crypto flow proxy uses reported 24h spot volume across selected large-cap crypto assets.",
    }


def _stock_liquidity_flows() -> list[dict[str, Any]]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        return [{"name": name, "status": "unavailable", "error": "Missing Alpaca API env vars", "source": "Alpaca Market Data API"} for name in STOCK_FLOW_GROUPS]

    symbols = sorted({symbol for group in STOCK_FLOW_GROUPS.values() for symbol in group})
    try:
        bars_by_symbol = _fetch_stock_bars(symbols, days=18)
        fallback_note = ""
    except Exception as exc:
        try:
            bars_by_symbol = _fetch_latest_stock_bars(symbols)
            fallback_note = f"Historical bars unavailable ({_safe_error(exc)}); using latest IEX bars only."
        except Exception as latest_exc:
            return [{"name": name, "status": "unavailable", "error": _safe_error(latest_exc), "source": "Alpaca /v2/stocks/bars"} for name in STOCK_FLOW_GROUPS]

    output = []
    for name, group_symbols in STOCK_FLOW_GROUPS.items():
        assets = []
        current_dollar_volume = 0.0
        prior_dollar_volumes: list[float] = []
        for symbol in group_symbols:
            bars = bars_by_symbol.get(symbol, [])
            if not bars:
                continue
            normalized = [_normalize_bar(bar) for bar in bars if _normalize_bar(bar)]
            if not normalized:
                continue
            latest = normalized[-1]
            prior = normalized[-6:-1]
            latest_dv = latest["close"] * latest["volume"]
            current_dollar_volume += latest_dv
            prior_avg = sum(item["close"] * item["volume"] for item in prior) / len(prior) if prior else None
            if prior_avg is not None:
                prior_dollar_volumes.append(prior_avg)
            assets.append({
                "symbol": symbol,
                "close": latest["close"],
                "volume": latest["volume"],
                "dollar_volume": latest_dv,
                "volume_vs_5d_avg_pct": _pct_distance(latest_dv, prior_avg),
                "timestamp": latest["timestamp"],
            })
        baseline = sum(prior_dollar_volumes) if prior_dollar_volumes else None
        flow_change = _pct_distance(current_dollar_volume, baseline)
        output.append({
            "name": name,
            "status": "ok" if assets else "unavailable",
            "source": "Alpaca /v2/stocks/bars feed=iex timeframe=1Day",
            "metric": "latest daily dollar volume vs prior 5-day average",
            "dollar_volume": current_dollar_volume if assets else None,
            "volume_vs_5d_avg_pct": flow_change,
            "volume_read": _volume_read(None, flow_change),
            "assets": sorted(assets, key=lambda item: item.get("dollar_volume") or 0, reverse=True),
            "note": (fallback_note + " " if fallback_note else "") + "Stock/ETF flow proxy uses latest daily close times volume versus prior 5-day average when historical bars are available. IEX data may be limited/delayed versus full SIP.",
        })
    return output



def _fetch_latest_stock_bars(symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise RuntimeError("Missing Alpaca API env vars")
    params = urlencode({"symbols": ",".join(symbols), "feed": "iex"})
    request = Request(
        f"{ALPACA_LATEST_BARS_URL}?{params}",
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    bars = payload.get("bars", {})
    return {symbol: [bar] for symbol, bar in bars.items() if bar}


def _fetch_stock_bars(symbols: list[str], days: int = 95) -> dict[str, list[dict[str, Any]]]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise RuntimeError("Missing Alpaca API env vars")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    params = urlencode({
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": (end + timedelta(days=1)).isoformat(),
        "adjustment": "split",
        "feed": "iex",
    })
    request = Request(
        f"{ALPACA_STOCK_BARS_URL}?{params}",
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("bars", {})


def _safe_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0][:500]
    for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
        value = os.getenv(name, "").strip()
        if value and len(value) >= 4:
            text = text.replace(value, f"<redacted:{name}>")
    return text[:220]


def _stock_bias(change_5d: float | None, change_20d: float | None, indicators: dict[str, Any], volume_vs_avg: float | None) -> str:
    setup_type = indicators.get("setup_type", "")
    if setup_type in {"pre_breakout", "trend_pullback_long"}:
        return "bullish"
    if setup_type == "breakdown_short":
        return "bearish"
    return "neutral"


def _trend_score(dollar_volume: float, volume_vs_avg: float | None, change_5d: float | None, indicators: dict[str, Any]) -> float:
    setup_type = indicators.get("setup_type", "watch")
    setup_bonus = {
        "pre_breakout": 90,
        "trend_pullback_long": 78,
        "breakdown_short": 76,
        "base_watch": 52,
        "oversold_watch": 38,
        "extended_or_correcting": 10,
    }.get(setup_type, 28)
    volume_component = min(max(volume_vs_avg or 0, -25), 90) * 0.32
    dollar_component = min(dollar_volume / 1_000_000_000, 20) * 2
    momentum_component = min(max(abs(change_5d or 0), 0), 12)
    rsi = indicators.get("rsi14")
    rsi_component = 0 if rsi is None else max(0, 60 - abs(52 - rsi)) / 6
    return setup_bonus + volume_component + dollar_component + momentum_component + rsi_component


def _classify_stock_setup(
    price: float,
    closes: list[float],
    indicators: dict[str, Any],
    volume_vs_avg: float | None,
    change_1d: float | None,
    change_5d: float | None,
    change_20d: float | None,
) -> dict[str, Any]:
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    rsi = indicators.get("rsi14")
    recent20 = closes[-20:] if len(closes) >= 20 else closes
    close_support = min(recent20) if recent20 else None
    close_resistance = max(recent20) if recent20 else None
    range_width = _pct_distance(close_resistance, close_support) if close_support and close_resistance else None
    distance_to_resistance = _pct_distance(price, close_resistance) if close_resistance else None
    distance_from_support = _pct_distance(price, close_support) if close_support else None
    price_vs_ema20 = indicators.get("price_vs_ema20_pct")
    price_vs_ema50 = indicators.get("price_vs_ema50_pct")
    vol = volume_vs_avg or 0
    one_day = change_1d or 0
    five_day = change_5d or 0
    twenty_day = change_20d or 0

    if (one_day <= -3 and vol >= 35) or (price_vs_ema20 is not None and price_vs_ema20 > 6) or (rsi is not None and rsi >= 70):
        return {
            "type": "extended_or_correcting",
            "label": "Already moved / correcting",
            "direction": "wait",
            "quality": 28,
            "reason": "Avoid chasing: price/volume action suggests the move may already be in progress or correcting.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    if (
        close_resistance
        and distance_to_resistance is not None
        and -4 <= distance_to_resistance <= -0.25
        and range_width is not None
        and range_width <= 14
        and rsi is not None
        and 42 <= rsi <= 64
        and vol >= -10
    ):
        return {
            "type": "pre_breakout",
            "label": "Pre-breakout base",
            "direction": "long",
            "quality": 88,
            "reason": f"Price is still below close resistance near {_money(close_resistance)} instead of already chasing above it.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    if (
        ema20
        and ema50
        and price > ema50
        and abs(price_vs_ema20 or 99) <= 3.5
        and twenty_day >= 2
        and -6 <= five_day <= 4
        and rsi is not None
        and 38 <= rsi <= 62
    ):
        return {
            "type": "trend_pullback_long",
            "label": "Trend pullback long",
            "direction": "long",
            "quality": 82,
            "reason": f"Trend is still above the 50D EMA while price is near the 20D EMA near {_money(ema20)}.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    if (
        ema20
        and ema50
        and price < ema20
        and price < ema50
        and five_day <= -2
        and twenty_day <= -4
        and vol >= 10
        and rsi is not None
        and 28 <= rsi <= 55
    ):
        return {
            "type": "breakdown_short",
            "label": "Breakdown short",
            "direction": "short",
            "quality": 80,
            "reason": "Price is below the 20D and 50D EMAs with downside momentum and elevated volume.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    if range_width is not None and range_width <= 12 and rsi is not None and 40 <= rsi <= 62:
        return {
            "type": "base_watch",
            "label": "Base watch",
            "direction": "wait",
            "quality": 55,
            "reason": "Compression is visible, but direction is not confirmed yet.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    if rsi is not None and rsi <= 32:
        return {
            "type": "oversold_watch",
            "label": "Oversold watch",
            "direction": "wait",
            "quality": 42,
            "reason": "Oversold can bounce, but this needs reclaim evidence before paper testing.",
            "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
        }

    return {
        "type": "unclear",
        "label": "No clear direction",
        "direction": "wait",
        "quality": 30,
        "reason": "Current close-price data does not show a clean pre-breakout, pullback, or breakdown setup.",
        "levels": {"support": close_support, "resistance": close_resistance, "range_width_pct": range_width},
    }


def _stock_scenario(symbol: str, price: float, bias: str, indicators: dict[str, Any], volume_vs_avg: float | None, change_5d: float | None) -> dict[str, str]:
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    rsi = indicators.get("rsi14")
    setup = indicators.get("setup") or {}
    setup_parts = [f"{symbol} latest close is {_money(price)}", f"setup: {setup.get('label', 'No clear direction')}"]
    if volume_vs_avg is not None:
        setup_parts.append(f"dollar volume is {volume_vs_avg:+.1f}% vs its prior 5-day average")
    if change_5d is not None:
        setup_parts.append(f"5D move is {change_5d:+.1f}%")
    if rsi is not None:
        setup_parts.append(f"RSI(14) is {rsi:.1f}")
    if ema20 and ema50:
        setup_parts.append(f"20D EMA {_money(ema20)} and 50D EMA {_money(ema50)}")
    setup_type = setup.get("type")
    levels = setup.get("levels", {})
    if setup_type == "pre_breakout":
        watch = f"Long paper test only on a clean push through close resistance near {_money(levels.get('resistance'))}; failed breakout goes back to watchlist."
    elif setup_type == "trend_pullback_long":
        watch = f"Long paper test can use 20D EMA area as a risk line; lose {_money(ema20)} and the setup weakens."
    elif setup_type == "breakdown_short":
        watch = f"Short paper test only; reclaiming the 20D EMA near {_money(ema20)} invalidates the breakdown thesis."
    elif setup_type == "extended_or_correcting":
        watch = "Skip for now: better to wait for a base, EMA reset, or clear breakdown than chase a stretched move."
    else:
        watch = "No clean directional setup yet; keep it on watch until price confirms around EMA or close-based levels."
    return {"name": f"{symbol} {setup.get('label', 'setup')}", "bias": bias, "setup": "; ".join(setup_parts) + f". {setup.get('reason', '')}", "watch": watch}


def _stock_strategy_candidate(symbol: str, price: float, bias: str, indicators: dict[str, Any], volume_vs_avg: float | None, change_5d: float | None) -> dict[str, Any]:
    ema20 = indicators.get("ema20")
    rsi = indicators.get("rsi14")
    setup = indicators.get("setup") or {}
    setup_type = setup.get("type", "unclear")
    levels = setup.get("levels", {})
    strategies = [setup.get("label", "setup watch"), "risk-defined paper test"]
    if (volume_vs_avg or 0) >= 25:
        strategies.append("unusual volume")
    confidence = min(0.94, 0.55 + (setup.get("quality", 30) / 100 * 0.34))

    if setup_type == "pre_breakout":
        return {
            "name": f"{symbol} pre-breakout long paper test",
            "bias": "bullish",
            "actionable": True,
            "setup_type": setup_type,
            "confidence": round(confidence, 2),
            "timeframe": "swing",
            "strategies": strategies + ["pre-breakout"],
            "reason": f"{symbol} has not broken out yet: close resistance {_money(levels.get('resistance'))}, range width {num_text(levels.get('range_width_pct'))}%, RSI {num_text(rsi)}, volume vs avg {signed_text(volume_vs_avg)}.",
            "trigger": f"Paper long only on a close/push through {_money(levels.get('resistance'))} with volume staying at/above average.",
            "invalidation": f"Lose close support near {_money(levels.get('support'))} or fail breakout and close back inside the range.",
        }
    if setup_type == "trend_pullback_long":
        return {
            "name": f"{symbol} trend-pullback long paper test",
            "bias": "bullish",
            "actionable": True,
            "setup_type": setup_type,
            "confidence": round(confidence, 2),
            "timeframe": "swing",
            "strategies": strategies + ["EMA pullback"],
            "reason": f"{symbol} is pulling back toward the 20D EMA without losing the broader 50D trend; 5D move {signed_text(change_5d)}, RSI {num_text(rsi)}.",
            "trigger": f"Paper long while price holds/reclaims 20D EMA near {_money(ema20)}.",
            "invalidation": f"Close below 20D EMA near {_money(ema20)} and no quick reclaim.",
        }
    if setup_type == "breakdown_short":
        return {
            "name": f"{symbol} breakdown short paper test",
            "bias": "bearish",
            "actionable": True,
            "setup_type": setup_type,
            "confidence": round(confidence, 2),
            "timeframe": "intraday",
            "strategies": strategies + ["breakdown short"],
            "reason": f"{symbol} is below the 20D/50D EMA with downside momentum; 5D move {signed_text(change_5d)}, volume vs avg {signed_text(volume_vs_avg)}, RSI {num_text(rsi)}.",
            "trigger": "Paper short only if weakness continues below the 20D/50D structure.",
            "invalidation": f"Reclaim 20D EMA near {_money(ema20)}.",
        }
    return {
        "name": f"{symbol} {setup.get('label', 'watchlist')} - no paper entry",
        "bias": bias,
        "actionable": False,
        "setup_type": setup_type,
        "confidence": round(min(confidence, 0.72), 2),
        "timeframe": "swing",
        "strategies": strategies,
        "reason": f"{symbol} is classified as {setup.get('label', 'unclear')}: {setup.get('reason', 'No clean direction yet')}",
        "trigger": "Wait for a pre-breakout base, trend pullback, or confirmed breakdown before paper testing.",
        "invalidation": "N/A",
    }


def get_business_brief(symbol: str) -> dict[str, Any]:
    normalized = symbol.upper().replace("/USD", "")
    brief = BUSINESS_BRIEFS.get(normalized, {
        "name": normalized,
        "business": "No curated business brief is available yet for this ticker.",
        "drivers": [],
        "watch": "Use source-backed filings, earnings reports, and company news before forming a fundamental view.",
    })
    fundamentals = FUNDAMENTAL_NOTES.get(normalized, {
        "model": "No curated fundamental model note is available yet.",
        "key_metrics": [],
        "risks": ["Needs live filings/earnings data before forming a fundamental view"],
    })
    return {**brief, "fundamentals": fundamentals}


def _stock_group_name(symbol: str) -> str:
    matches = [name for name, symbols in STOCK_FLOW_GROUPS.items() if symbol in symbols]
    return ", ".join(matches) if matches else "Trending Stocks"


def signed_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def num_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _normalize_bar(bar: dict[str, Any]) -> dict[str, Any] | None:
    close = _num(bar.get("c"))
    volume = _num(bar.get("v"))
    if close is None or volume is None:
        return None
    return {"close": close, "volume": volume, "timestamp": bar.get("t")}


def _volume_read(weighted_change_24h: float | None, volume_vs_avg: float | None) -> str:
    if volume_vs_avg is not None:
        if volume_vs_avg >= 40:
            return "heavy inflow/attention proxy"
        if volume_vs_avg <= -25:
            return "liquidity drying up proxy"
        return "normal-to-mixed liquidity proxy"
    if weighted_change_24h is not None:
        if weighted_change_24h >= 3:
            return "risk-on crypto flow proxy"
        if weighted_change_24h <= -3:
            return "risk-off crypto flow proxy"
        return "mixed crypto flow proxy"
    return "flow read unavailable"


def get_oil_market() -> dict[str, Any]:
    payload = get_trending_stocks(limit=80)
    if payload.get("status") != "ok":
        return {
            "status": "data_limited",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": payload.get("source", "AlphaLab oil/energy proxy"),
            "source_note": "Oil/energy is available as a curated watchlist and fundamental theme, but live Alpaca market-data bars are currently unavailable. No oil paper setups are generated without live bars.",
            "error": payload.get("error"),
            "symbols": OIL_SYMBOLS,
            "stocks": [_data_limited_oil_row(symbol) for symbol in OIL_SYMBOLS],
        }
    rows = [row for row in payload.get("stocks", []) if row.get("ticker") in OIL_SYMBOLS]
    return {
        "status": "ok" if rows else "data_limited",
        "fetched_at": payload.get("fetched_at"),
        "source": "Alpaca /v2/stocks/bars feed=iex timeframe=1Day",
        "source_note": "Oil insight uses USO, XLE, XOM, CVX, OXY, and SLB as oil/energy proxies. It does not pull direct crude futures or inventory data yet.",
        "symbols": OIL_SYMBOLS,
        "stocks": rows or [_data_limited_oil_row(symbol) for symbol in OIL_SYMBOLS],
    }


def _data_limited_oil_row(symbol: str) -> dict[str, Any]:
    return {
        "ticker": symbol,
        "business_brief": get_business_brief(symbol),
        "price": None,
        "bias": "neutral",
        "score": 0,
        "dollar_volume": None,
        "volume_vs_5d_avg_pct": None,
        "change_1d_pct": None,
        "change_5d_pct": None,
        "change_20d_pct": None,
        "indicators": {"setup_label": "Data-limited oil watch", "setup_type": "data_limited", "setup": {"label": "Data-limited oil watch", "type": "data_limited", "levels": {}}},
        "scenario": {"name": f"{symbol} oil/energy watch", "bias": "neutral", "setup": "Live oil/energy bars are unavailable, so this is a business/fundamental watch card only.", "watch": "Connect a commodity/energy market-data source before paper testing oil setups."},
        "strategy_candidate": {"name": f"{symbol} oil data-limited watch", "bias": "neutral", "actionable": False, "confidence": 0.0, "reason": "Live bars unavailable; no oil paper setup generated.", "trigger": "N/A", "invalidation": "N/A"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_trending_stocks(limit: int = 12) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        bars_by_symbol = _fetch_stock_bars(TRENDING_STOCK_UNIVERSE, days=95)
        data_limit_note = ""
    except Exception as exc:
        try:
            bars_by_symbol = _fetch_latest_stock_bars(TRENDING_STOCK_UNIVERSE)
            data_limit_note = f"Historical bars unavailable ({_safe_error(exc)}); latest bars only, so EMA/RSI/setup classification may be unavailable."
        except Exception as latest_exc:
            return {
                "status": "unavailable",
                "source": "Alpaca /v2/stocks/bars feed=iex timeframe=1Day",
                "error": _safe_error(latest_exc),
                "fetched_at": fetched_at,
            }

    rows = []
    for symbol in TRENDING_STOCK_UNIVERSE:
        bars = [_normalize_bar(bar) for bar in bars_by_symbol.get(symbol, [])]
        bars = [bar for bar in bars if bar]
        if len(bars) < 15:
            latest_only = bars[-1] if bars else None
            if latest_only:
                rows.append({
                    "ticker": symbol,
                    "business_brief": get_business_brief(symbol),
                    "price": latest_only["close"],
                    "bias": "neutral",
                    "score": latest_only["close"] * latest_only["volume"] / 1_000_000_000,
                    "dollar_volume": latest_only["close"] * latest_only["volume"],
                    "volume_vs_5d_avg_pct": None,
                    "change_1d_pct": None,
                    "change_5d_pct": None,
                    "change_20d_pct": None,
                    "indicators": {"setup_label": "Latest bar only", "setup_type": "data_limited", "setup": {"label": "Latest bar only", "type": "data_limited", "levels": {}}},
                    "scenario": {"name": f"{symbol} latest bar only", "bias": "neutral", "setup": "Historical bars are unavailable, so AlphaLab is showing the latest IEX bar without EMA/RSI classification.", "watch": "Wait for historical bars before paper testing."},
                    "strategy_candidate": {"name": f"{symbol} data-limited watch", "bias": "neutral", "actionable": False, "confidence": 0.0, "reason": "Historical bars unavailable; no paper setup generated.", "trigger": "N/A", "invalidation": "N/A"},
                    "timestamp": latest_only["timestamp"],
                })
            continue
        latest = bars[-1]
        closes = [bar["close"] for bar in bars]
        prior = bars[-6:-1]
        latest_dv = latest["close"] * latest["volume"]
        prior_avg_dv = sum(item["close"] * item["volume"] for item in prior) / len(prior) if prior else None
        change_1d = _pct_distance(closes[-1], closes[-2]) if len(closes) >= 2 else None
        change_5d = _pct_distance(closes[-1], closes[-6]) if len(closes) >= 6 else None
        change_20d = _pct_distance(closes[-1], closes[-21]) if len(closes) >= 21 else None
        indicators = _indicator_snapshot(latest["close"], closes)
        volume_vs_avg = _pct_distance(latest_dv, prior_avg_dv)
        setup = _classify_stock_setup(latest["close"], closes, indicators, volume_vs_avg, change_1d, change_5d, change_20d)
        indicators = {**indicators, "setup": setup, "setup_type": setup.get("type"), "setup_label": setup.get("label")}
        bias = _stock_bias(change_5d, change_20d, indicators, volume_vs_avg)
        score = _trend_score(latest_dv, volume_vs_avg, change_5d, indicators)
        rows.append({
            "ticker": symbol,
            "business_brief": get_business_brief(symbol),
            "price": latest["close"],
            "bias": bias,
            "score": score,
            "dollar_volume": latest_dv,
            "volume_vs_5d_avg_pct": volume_vs_avg,
            "change_1d_pct": change_1d,
            "change_5d_pct": change_5d,
            "change_20d_pct": change_20d,
            "indicators": indicators,
            "scenario": _stock_scenario(symbol, latest["close"], bias, indicators, volume_vs_avg, change_5d),
            "strategy_candidate": _stock_strategy_candidate(symbol, latest["close"], bias, indicators, volume_vs_avg, change_5d),
            "timestamp": latest["timestamp"],
        })

    ranked = sorted(rows, key=lambda row: row["score"], reverse=True)
    return {
        "status": "ok" if ranked else "unavailable",
        "fetched_at": fetched_at,
        "source": "Alpaca /v2/stocks/bars feed=iex timeframe=1Day",
        "source_note": (data_limit_note + " " if data_limit_note else "") + "Rank favors cleaner pre-breakout, trend-pullback, and breakdown setups over already-extended liquidity spikes. Uses close-price EMA/RSI and close-based support/resistance from Alpaca IEX daily bars when available; IEX data may be limited/delayed versus full SIP.",
        "universe": TRENDING_STOCK_UNIVERSE,
        "stocks": ranked[:limit],
    }


def build_trending_stock_signals(limit: int = 5) -> list[dict[str, Any]]:
    payload = get_trending_stocks(limit=limit * 2)
    if payload.get("status") != "ok":
        return []
    signals = []
    for row in payload.get("stocks", []):
        candidate = row.get("strategy_candidate") or {}
        if not candidate.get("actionable"):
            continue
        if candidate.get("bias") not in {"bullish", "bearish"}:
            continue
        if candidate.get("confidence", 0) < 0.75:
            continue
        signals.append({
            "ticker": row["ticker"],
            "bias": candidate["bias"],
            "confidence": candidate["confidence"],
            "timeframe": candidate.get("timeframe", "intraday"),
            "reason": candidate.get("reason") or row.get("scenario", {}).get("setup", "Trending liquidity candidate."),
            "source": "alphalab_trending_liquidity",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_tags": candidate.get("strategies", ["risk-defined paper test"]),
            "theme": candidate.get("setup_type", "Trending liquidity"),
            "sector": _stock_group_name(row["ticker"]),
            "catalyst": candidate.get("trigger", "Source-backed liquidity and indicator setup."),
        })
        if len(signals) >= limit:
            break
    return signals



def get_bitcoin_market() -> dict[str, Any]:
    row = _fetch_json(COINGECKO_BTC_MARKETS_URL)[0]
    closes = _daily_closes(_fetch_json(COINGECKO_BTC_CHART_URL).get("prices", []))

    change_24h = _num(row.get("price_change_percentage_24h_in_currency"))
    change_7d = _num(row.get("price_change_percentage_7d_in_currency"))
    change_14d = _num(row.get("price_change_percentage_14d_in_currency"))
    price = _num(row.get("current_price"))
    indicators = _indicator_snapshot(price, closes)
    bias = _bias(change_7d, change_14d, indicators)
    scenarios = _btc_scenarios(price, bias, indicators)
    strategy_candidates = _strategy_candidates(price, bias, indicators, change_7d, change_14d)

    return {
        "status": "ok",
        "ticker": "BTC/USD",
        "price": price,
        "change_24h_pct": change_24h,
        "change_7d_pct": change_7d,
        "change_14d_pct": change_14d,
        "market_cap": _num(row.get("market_cap")),
        "volume_24h": _num(row.get("total_volume")),
        "last_updated": row.get("last_updated"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "CoinGecko /coins/markets + /coins/bitcoin/market_chart",
        "bias": bias,
        "summary": _summary(bias, change_24h, change_7d, change_14d),
        "indicators": indicators,
        "scenarios": scenarios,
        "strategy_candidates": strategy_candidates,
        "data_limits": [
            "EMA and RSI use CoinGecko close-price history from /market_chart.",
            "No EMA bounce claims are made from this data because high/low candle data is not included.",
        ],
    }


# Short-lived in-process cache for external JSON GETs (CoinGecko). A single
# dashboard refresh fans out to the same CoinGecko endpoints several times
# (bitcoin markets/chart are needed by both the bitcoin and after-hours views,
# and crypto markets by both liquidity and after-hours), and CoinGecko's free
# tier rate-limits aggressively. Caching by URL collapses those duplicate calls
# and, on failure (e.g. HTTP 429), serves the last good payload instead of
# blanking the UI.
_HTTP_CACHE: dict[str, tuple[float, Any]] = {}
_HTTP_CACHE_TTL_SECONDS = 90.0


def _fetch_json(url: str) -> Any:
    now = time.monotonic()
    cached = _HTTP_CACHE.get(url)
    if cached is not None and (now - cached[0]) < _HTTP_CACHE_TTL_SECONDS:
        return cached[1]
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "AlphaLab/0.1 local research app"})
    try:
        with urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        if cached is not None:
            return cached[1]
        raise
    _HTTP_CACHE[url] = (now, data)
    return data


def _daily_closes(prices: list[list[float]]) -> list[float]:
    by_day: dict[str, float] = {}
    for ts_ms, price in prices:
        day = datetime.fromtimestamp(ts_ms / 1000, timezone.utc).date().isoformat()
        by_day[day] = float(price)
    return [by_day[day] for day in sorted(by_day)]


def _indicator_snapshot(price: float | None, closes: list[float]) -> dict[str, Any]:
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    recent = closes[-14:] if len(closes) >= 14 else closes
    support = min(recent) if recent else None
    resistance = max(recent) if recent else None
    return {
        "close_count": len(closes),
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": rsi14,
        "rsi_state": _rsi_state(rsi14),
        "support_14d_close": support,
        "resistance_14d_close": resistance,
        "price_vs_ema20_pct": _pct_distance(price, ema20),
        "price_vs_ema50_pct": _pct_distance(price, ema50),
        "ema_read": _ema_read(price, ema20, ema50),
    }


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        diff = values[idx] - values[idx - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for idx in range(period + 1, len(values)):
        diff = values[idx] - values[idx - 1]
        gain = max(diff, 0)
        loss = abs(min(diff, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _rsi_state(rsi: float | None) -> str:
    if rsi is None:
        return "unavailable"
    if rsi <= 20:
        return "deeply oversold"
    if rsi <= 30:
        return "oversold"
    if rsi >= 80:
        return "deeply overbought"
    if rsi >= 70:
        return "overbought"
    return "neutral"


def _ema_read(price: float | None, ema20: float | None, ema50: float | None) -> str:
    if price is None or ema20 is None or ema50 is None:
        return "EMA read unavailable"
    if price < ema20 < ema50:
        return "Price is below the 20D and 50D EMA; trend pressure remains bearish."
    if price > ema20 > ema50:
        return "Price is above the 20D and 50D EMA; trend structure is improving."
    if price > ema20 and price < ema50:
        return "Price reclaimed the 20D EMA but remains below the 50D EMA; rebound is not confirmed."
    if price < ema20 and price > ema50:
        return "Price is below the 20D EMA but above the 50D EMA; short-term momentum is weakening."
    return "EMA structure is mixed."


def _btc_scenarios(price: float | None, bias: str, indicators: dict[str, Any]) -> list[dict[str, str]]:
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    rsi = indicators.get("rsi14")
    support = indicators.get("support_14d_close")
    resistance = indicators.get("resistance_14d_close")
    scenarios: list[dict[str, str]] = []

    if price is None:
        return [{"name": "No trade", "setup": "BTC price is unavailable.", "watch": "Wait for current data."}]

    if ema20 and price < ema20:
        scenarios.append({
            "name": "Bearish continuation",
            "setup": f"BTC remains below the 20D EMA near {_money(ema20)}.",
            "watch": f"Failure to reclaim the 20D EMA keeps pressure on; a close back above {_money(ema20)} weakens the bear case.",
        })
    elif ema20:
        scenarios.append({
            "name": "20D EMA reclaim watch",
            "setup": f"BTC is above the 20D EMA near {_money(ema20)}.",
            "watch": "Look for follow-through rather than assuming one close means a durable reversal.",
        })

    if rsi is not None and rsi <= 30:
        scenarios.append({
            "name": "Oversold bounce watch",
            "setup": f"RSI(14) is {rsi:.1f}, which is {indicators.get('rsi_state')}.",
            "watch": "Oversold can stay oversold in downtrends; require reclaim levels or bullish divergence before treating it as reversal evidence.",
        })
    elif rsi is not None:
        scenarios.append({
            "name": "Momentum read",
            "setup": f"RSI(14) is {rsi:.1f}, currently {indicators.get('rsi_state')}.",
            "watch": "A move below 30 would mark oversold pressure; a move back over 50 would show improving momentum.",
        })

    if support and resistance:
        scenarios.append({
            "name": "Range levels",
            "setup": f"Recent 14D close support is near {_money(support)} and close resistance is near {_money(resistance)}.",
            "watch": "Breaks of close-based levels need confirmation because this feed does not include intraday high/low wicks.",
        })

    return scenarios


def _strategy_candidates(
    price: float | None,
    bias: str,
    indicators: dict[str, Any],
    change_7d: float | None,
    change_14d: float | None,
) -> list[dict[str, str]]:
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    rsi = indicators.get("rsi14")
    candidates: list[dict[str, str]] = []
    if price is None:
        return candidates

    if bias == "bearish" and ema20 and price < ema20:
        candidates.append({
            "name": "BTC breakdown continuation dry-run",
            "direction": "bearish",
            "why": f"BTC is weak on 7D/14D performance and still below the 20D EMA near {_money(ema20)}.",
            "trigger": f"Dry-run only if BTC rejects or closes below {_money(ema20)} again.",
            "invalidation": f"Close and hold above the 20D EMA near {_money(ema20)}; stronger invalidation above 50D EMA near {_money(ema50)}." if ema50 else "Close back above the 20D EMA.",
        })

    if rsi is not None and rsi <= 30:
        candidates.append({
            "name": "Oversold mean-reversion watch",
            "direction": "bullish watch, not confirmed",
            "why": f"RSI(14) is {rsi:.1f}, but trend context still matters.",
            "trigger": "Only test after a reclaim of 20D EMA or a higher-low setup; do not buy solely because RSI is low.",
            "invalidation": "Fresh lower close after failed reclaim.",
        })

    if ema20 and ema50 and price > ema20 and price < ema50:
        candidates.append({
            "name": "Relief rally into 50D EMA",
            "direction": "neutral-to-bullish tactical",
            "why": "BTC reclaimed the 20D EMA but remains below the 50D EMA, so the setup is a tactical bounce, not a confirmed trend flip.",
            "trigger": f"Hold above 20D EMA near {_money(ema20)} with improving RSI.",
            "invalidation": f"Lose 20D EMA near {_money(ema20)}.",
        })

    if not candidates:
        candidates.append({
            "name": "No clean BTC strategy",
            "direction": "wait",
            "why": "Current indicators do not create a clean risk-defined setup.",
            "trigger": "Wait for EMA reclaim/rejection, RSI extreme, or a close-based support/resistance break.",
            "invalidation": "N/A",
        })
    return candidates


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_distance(price: float | None, level: float | None) -> float | None:
    if price is None or level in (None, 0):
        return None
    return ((price - level) / level) * 100


def _bias(change_7d: float | None, change_14d: float | None, indicators: dict[str, Any] | None = None) -> str:
    if change_7d is None and change_14d is None:
        return "unknown"
    seven = change_7d or 0
    fourteen = change_14d or 0
    ema_read = (indicators or {}).get("ema_read", "")
    if seven <= -3 or fourteen <= -6 or "below the 20D and 50D" in ema_read:
        return "bearish"
    if seven >= 3 and fourteen >= 4 and "above the 20D and 50D" in ema_read:
        return "bullish"
    return "neutral"


def _summary(bias: str, change_24h: float | None, change_7d: float | None, change_14d: float | None) -> str:
    parts = []
    if change_24h is not None:
        parts.append(f"24h {change_24h:+.2f}%")
    if change_7d is not None:
        parts.append(f"7d {change_7d:+.2f}%")
    if change_14d is not None:
        parts.append(f"14d {change_14d:+.2f}%")
    if not parts:
        return "Bitcoin market data is unavailable; no directional read."
    if bias == "bearish":
        return "Bitcoin is under pressure on recent performance: " + ", ".join(parts) + "."
    if bias == "bullish":
        return "Bitcoin is showing positive recent momentum: " + ", ".join(parts) + "."
    return "Bitcoin is mixed or not clearly directional: " + ", ".join(parts) + "."


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return "$" + f"{value:,.0f}"
