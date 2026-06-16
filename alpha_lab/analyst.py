from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXPLANATION_FIELDS = [
    "thesis_summary",
    "catalyst",
    "why_this_matters",
    "market_context",
    "setup_type",
    "confidence_score",
    "risk_factors",
    "invalidation_level_or_condition",
    "suggested_entry_zone",
    "suggested_stop_loss",
    "suggested_take_profit",
    "time_horizon",
    "source_refs",
]


def analyst_enabled() -> bool:
    return os.getenv("LLM_ANALYST_ENABLED", "false").strip().lower() == "true"


def _llm_providers() -> list[str]:
    """Ordered list of LLM providers to try, based on configured API keys.

    Anthropic (Claude) is primary; OpenAI (ChatGPT) is the automatic fallback
    used when Claude is unconfigured or unreachable. Set ``LLM_PRIMARY=openai``
    to flip the order (e.g. if Claude is rate-limited or down).
    """
    have = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "openai": bool(os.getenv("OPENAI_API_KEY", "").strip()),
    }
    if os.getenv("LLM_PRIMARY", "anthropic").strip().lower() == "openai":
        order = ["openai", "anthropic"]
    else:
        order = ["anthropic", "openai"]
    return [provider for provider in order if have[provider]]


def _redact_secrets(text: str) -> str:
    redacted = text
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(name, "").strip()
        if value and len(value) >= 4:
            redacted = redacted.replace(value, f"<redacted:{name}>")
    return redacted


def build_trade_explanation(signal: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    # Compute numeric trade levels from the live reference price so the entry /
    # stop / take-profit fields show real dollar values instead of vague prose.
    # When no price is available (offline, market closed, no data) levels is None
    # and we fall back to the LLM/mock qualitative guidance.
    levels = _compute_trade_levels(context.get("reference_price"), signal.get("bias"))
    # Give the LLM the price and computed levels so its prose (thesis,
    # invalidation, etc.) is grounded in the same numbers.
    prompt_context = {**context, "computed_trade_levels": levels} if levels else context
    providers = _llm_providers() if analyst_enabled() else []
    last_error = ""
    for provider in providers:
        try:
            explanation = (
                _anthropic_explanation(signal, prompt_context)
                if provider == "anthropic"
                else _openai_explanation(signal, prompt_context)
            )
            return _normalize_explanation(explanation, signal, analyst_mode=provider, analyst_assisted=True, levels=levels)
        except Exception as exc:
            last_error = _redact_secrets(str(exc).splitlines()[0])[:240]
            continue
    fallback = _mock_explanation(signal, context)
    if last_error:
        fallback["analyst_error"] = last_error
    mode = "mock_fallback" if providers else "mock"
    return _normalize_explanation(fallback, signal, analyst_mode=mode, analyst_assisted=False, levels=levels)


def build_market_briefing(base_brief: dict[str, Any]) -> dict[str, Any]:
    sections = base_brief.get("sections", {})
    catalysts = sections.get("catalysts", {}).get("catalysts", [])
    trending = sections.get("trending_stocks", {}).get("stocks", [])
    liquidity = sections.get("liquidity", {}).get("groups", [])
    btc = sections.get("bitcoin", {})
    oil = sections.get("oil_energy", {})
    return {
        "briefing_type": "daily_market_research",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "broad_market_tone": base_brief.get("regime", {}).get("posture", "mixed"),
        "major_indexes_sector_movement": _sector_summary(liquidity),
        "strongest_catalysts_found": [item for item in catalysts[:5]],
        "tickers_with_unusual_news_filings": sorted({item.get("ticker", "") for item in catalysts if item.get("ticker")})[:12],
        "themes": _themes(trending, catalysts),
        "macro_risks": [
            "Check jobs reports, CPI, Fed commentary, Treasury yields, and oil shocks before treating any setup as clean.",
            "AlphaLab only uses configured data sources; unavailable feeds should be treated as blind spots.",
        ],
        "candidate_tickers_to_monitor": [signal.get("ticker") for signal in base_brief.get("signals", []) if signal.get("ticker")],
        "crypto_context": {
            "btc_bias": btc.get("bias", "unknown"),
            "btc_context": btc.get("summary") or btc.get("read") or "",
        },
        "energy_context": oil,
        "source_refs": _source_refs(base_brief),
        "raw_brief": base_brief,
    }


CHAT_SYSTEM_PROMPT = (
    "You are AlphaLab's research analyst assistant. You discuss market events, "
    "the user's catalysts, scored ideas, and possible strategies in a paper-"
    "trading research context. Ground every answer in the provided AlphaLab "
    "CONTEXT (catalysts, brief, ideas) and say plainly when the data doesn't "
    "cover something rather than inventing it. You are ADVISORY ONLY: you never "
    "place, approve, or execute trades, and you never claim certainty or give "
    "financial advice. Be concise and specific."
)


def chat_reply(message: str, context: dict[str, Any] | None = None, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Answer a free-form markets question, grounded in live AlphaLab context.

    Read-only / advisory: this function only reads context and returns text. It
    has no path to place or approve a trade. Falls back to a safe canned reply
    when the LLM analyst is disabled or unconfigured, so the chat UI always works.
    """
    context = context or {}
    history = history or []
    providers = _llm_providers() if analyst_enabled() else []
    if not providers:
        return {
            "reply": (
                "The LLM analyst is not enabled, so I can't chat live right now. "
                "Set LLM_ANALYST_ENABLED=true and either ANTHROPIC_API_KEY (Claude) "
                "or OPENAI_API_KEY (ChatGPT fallback) to turn this on. Meanwhile, the "
                "dashboard's catalyst radar, scored ideas, and daily brief have the "
                "underlying data."
            ),
            "analyst_mode": "disabled",
            "analyst_assisted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    last_error = ""
    for provider in providers:
        try:
            reply = (
                _anthropic_chat(message, context, history)
                if provider == "anthropic"
                else _openai_chat(message, context, history)
            )
            return {
                "reply": reply,
                "analyst_mode": provider,
                "analyst_assisted": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            last_error = _redact_secrets(str(exc).splitlines()[0])[:160]
            continue
    return {
        "reply": f"Analyst chat is temporarily unavailable ({last_error}). The dashboard data is still current.",
        "analyst_mode": "error",
        "analyst_assisted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _anthropic_chat(message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str:
    model = os.getenv("LLM_MODEL", "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest"
    max_tokens = int(os.getenv("LLM_CHAT_MAX_TOKENS", "1200") or 1200)
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2") or 0.2)

    messages: list[dict[str, str]] = []
    # Keep only the recent turns to bound the request size; roles are sanitized.
    for turn in history[-8:]:
        role = "assistant" if str(turn.get("role")) == "assistant" else "user"
        text = str(turn.get("content", "")).strip()
        if text:
            messages.append({"role": role, "content": text})
    grounded = f"AlphaLab CONTEXT (read-only):\n{json.dumps(context)[:12000]}\n\nQUESTION:\n{message}"
    messages.append({"role": "user", "content": grounded})

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": CHAT_SYSTEM_PROMPT,
        "messages": messages,
    }
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _redact_secrets(exc.read().decode("utf-8", errors="replace")[:180])
        raise RuntimeError(f"Anthropic request failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Anthropic network error: {exc}") from exc
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _openai_chat(message: str, context: dict[str, Any], history: list[dict[str, str]]) -> str:
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    max_tokens = int(os.getenv("LLM_CHAT_MAX_TOKENS", "1200") or 1200)
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2") or 0.2)

    messages: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in history[-8:]:
        role = "assistant" if str(turn.get("role")) == "assistant" else "user"
        text = str(turn.get("content", "")).strip()
        if text:
            messages.append({"role": role, "content": text})
    grounded = f"AlphaLab CONTEXT (read-only):\n{json.dumps(context)[:12000]}\n\nQUESTION:\n{message}"
    messages.append({"role": "user", "content": grounded})

    payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": messages}
    return _openai_request(payload)


def _openai_explanation(signal: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000") or 2000)
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2") or 0.2)
    prompt = {
        "instruction": (
            "You are an analyst for a paper-trading research app. Convert the input into a structured thesis. "
            "Do not recommend live trading. Do not claim certainty. Return JSON only with the requested fields."
        ),
        "required_fields": EXPLANATION_FIELDS,
        "signal": signal,
        "context": context,
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return only valid JSON containing the requested fields."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }
    return json.loads(_openai_request(payload))


def _openai_request(payload: dict[str, Any]) -> str:
    request = Request(
        OPENAI_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '').strip()}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _redact_secrets(exc.read().decode("utf-8", errors="replace")[:180])
        raise RuntimeError(f"OpenAI request failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI network error: {exc}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI returned no choices")
    return (choices[0].get("message", {}).get("content") or "").strip()


def _anthropic_explanation(signal: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    model = os.getenv("LLM_MODEL", "claude-3-5-sonnet-latest").strip() or "claude-3-5-sonnet-latest"
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000") or 2000)
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2") or 0.2)
    prompt = {
        "instruction": (
            "You are an analyst for a paper-trading research app. Convert the input into a structured thesis. "
            "Do not recommend live trading. Do not claim certainty. Return JSON only with the requested fields."
        ),
        "required_fields": EXPLANATION_FIELDS,
        "signal": signal,
        "context": context,
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": json.dumps(prompt)}],
    }
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _redact_secrets(exc.read().decode("utf-8", errors="replace")[:180])
        raise RuntimeError(f"Anthropic request failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Anthropic network error: {exc}") from exc
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return json.loads(text)


def _mock_explanation(signal: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    ticker = str(signal.get("ticker", "")).upper()
    bias = str(signal.get("bias", "neutral")).lower()
    catalyst = str(signal.get("catalyst") or signal.get("reason") or "No catalyst text supplied.")
    confidence = float(signal.get("confidence", 0) or 0)
    setup = ", ".join(signal.get("strategies") or signal.get("strategy_tags") or []) or "watchlist setup"
    return {
        "thesis_summary": f"{ticker} is a {bias} paper-research candidate based on the current normalized signal.",
        "catalyst": catalyst,
        "why_this_matters": "The catalyst may change attention, liquidity, or positioning, but it still needs price, volume, and risk validation.",
        "market_context": str(context.get("market_context") or context.get("headline") or "Use current market brief, sector flow, and catalyst radar context before acting."),
        "setup_type": setup,
        "confidence_score": confidence,
        "risk_factors": [
            "Signal may be stale or already priced in.",
            "Spread, liquidity, float, and market regime may make the setup unsuitable.",
            "Paper execution can differ from real fills and is not financial advice.",
        ],
        "invalidation_level_or_condition": "Invalidate if the catalyst is contradicted, volume fades, or price rejects the planned setup level.",
        "suggested_entry_zone": "Wait for confirmation near the planned trigger; avoid chasing extended moves.",
        "suggested_stop_loss": "Use the configured risk stop or the level that invalidates the thesis.",
        "suggested_take_profit": "Scale or exit into the configured take-profit area or when momentum fades.",
        "time_horizon": str(signal.get("timeframe") or "intraday"),
        "source_refs": _source_refs({"signal": signal, "context": context}),
    }


def _normalize_explanation(explanation: dict[str, Any], signal: dict[str, Any], analyst_mode: str, analyst_assisted: bool, levels: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {field: explanation.get(field, "" if field != "risk_factors" and field != "source_refs" else []) for field in EXPLANATION_FIELDS}
    normalized["confidence_score"] = float(normalized.get("confidence_score") or signal.get("confidence") or 0)
    if isinstance(normalized["risk_factors"], str):
        normalized["risk_factors"] = [normalized["risk_factors"]]
    if isinstance(normalized["source_refs"], str):
        normalized["source_refs"] = [normalized["source_refs"]]
    # When a live reference price produced numeric levels, those dollar values
    # are authoritative for the entry / stop / take-profit fields, overriding the
    # qualitative LLM/mock text so the approval card shows real numbers.
    if levels:
        normalized["suggested_entry_zone"] = levels["entry_zone_text"]
        normalized["suggested_stop_loss"] = levels["stop_loss_text"]
        normalized["suggested_take_profit"] = levels["take_profit_text"]
        normalized["trade_levels"] = levels
    normalized["analyst_mode"] = analyst_mode
    normalized["analyst_assisted"] = analyst_assisted
    normalized["created_at"] = datetime.now(timezone.utc).isoformat()
    if explanation.get("analyst_error"):
        normalized["analyst_error"] = explanation["analyst_error"]
    return normalized


def _sector_summary(groups: list[dict[str, Any]]) -> list[str]:
    summaries = []
    for group in groups[:6]:
        name = group.get("name", "Unknown")
        change = group.get("weighted_change_24h_pct") or group.get("volume_vs_5d_avg_pct")
        summaries.append(f"{name}: {change if change is not None else 'data unavailable'}")
    return summaries


def _themes(trending: list[dict[str, Any]], catalysts: list[dict[str, Any]]) -> list[str]:
    text = " ".join(
        [str(item.get("theme", "")) + " " + str(item.get("headline", "")) + " " + str(item.get("summary", "")) for item in trending + catalysts]
    ).lower()
    themes = []
    for key in ["ai", "datacenter", "semiconductor", "energy", "financing", "partnership"]:
        if key in text or (key == "datacenter" and "data-center" in text):
            themes.append(key)
    return themes or ["mixed"]


def _compute_trade_levels(reference_price: Any, bias: Any) -> dict[str, Any] | None:
    """Derive numeric entry / stop / take-profit levels from the live price.

    Returns ``None`` when no usable price is available so callers fall back to
    qualitative guidance. Levels are on the underlying and use a percentage stop
    plus a reward-to-risk multiple (both env-configurable). Bias direction flips
    the stop/target geometry; an unclear bias is treated as long.
    """
    try:
        price = float(reference_price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    stop_pct = float(os.getenv("ANALYST_STOP_PCT", "0.03") or 0.03)
    reward_risk = float(os.getenv("ANALYST_REWARD_RISK", "2.0") or 2.0)
    band_pct = float(os.getenv("ANALYST_ENTRY_BAND_PCT", "0.0025") or 0.0025)
    is_short = str(bias or "").strip().lower() == "bearish"

    entry_low = round(price * (1 - band_pct), 2)
    entry_high = round(price * (1 + band_pct), 2)
    if is_short:
        stop = round(price * (1 + stop_pct), 2)
        risk_per_share = round(stop - price, 2)
        target = round(price - risk_per_share * reward_risk, 2)
        stop_side = "above"
    else:
        stop = round(price * (1 - stop_pct), 2)
        risk_per_share = round(price - stop, 2)
        target = round(price + risk_per_share * reward_risk, 2)
        stop_side = "below"

    return {
        "reference_price": round(price, 2),
        "bias": "short" if is_short else "long",
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "target": target,
        "risk_per_share": risk_per_share,
        "stop_pct": stop_pct,
        "reward_risk": reward_risk,
        "entry_zone_text": f"${entry_low:.2f}–${entry_high:.2f} (near last trade ${price:.2f})",
        "stop_loss_text": f"${stop:.2f} ({stop_pct * 100:.1f}% {stop_side} entry)",
        "take_profit_text": f"${target:.2f} ({reward_risk:.1f}:1 reward-to-risk, ${risk_per_share:.2f}/share risk)",
    }


def _source_refs(payload: dict[str, Any]) -> list[str]:
    refs: list[Any] = []
    signal = payload.get("signal", payload)
    if isinstance(signal, dict):
        if isinstance(signal.get("source_refs"), list) and signal["source_refs"]:
            refs.extend(signal["source_refs"])
        source = signal.get("source")
        timestamp = signal.get("timestamp") or signal.get("published_at")
        source_url = signal.get("source_url")
        if source and not refs:
            if source_url:
                refs.append({"label": source, "url": source_url, "timestamp": timestamp or ""})
            else:
                refs.append(f"{source}{' @ ' + timestamp if timestamp else ''}")
    context = payload.get("context")
    if isinstance(context, dict) and context.get("source"):
        refs.append(str(context["source"]))
    return refs
