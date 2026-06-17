"""
alpha_lab/source_smoke_test.py — read-only connectivity probe for the live data
sources AlphaLabs depends on: Polygon news/catalysts, SEC EDGAR, Polygon futures
aggregates, and Polygon options flow.

Run it on the production (old) Mac after a deploy to confirm each source is
reachable and entitled BEFORE trusting the scheduled captures:

    python -m alpha_lab.source_smoke_test

It is strictly READ-ONLY: it makes a handful of GET requests, persists nothing,
creates no ideas, places no trades, and never prints secret values — only
whether each key/user-agent is present. Errors are passed through ``_safe_error``
so URLs and key values are redacted out of any message.

Exit code is 0 unless ``--strict`` is passed, in which case any source that is
neither a clear success nor merely "key missing" makes the command exit 1 (handy
for wiring into a verification script).
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .env import load_dotenv
from .live_sources import (
    POLYGON_NEWS_URL,
    SEC_SUBMISSIONS_URL,
    SEC_TICKERS_URL,
    _fetch_sec_filings,
    _safe_error,
    _sec_cik_map,
    _watchlist,
)


def _present(value: str | None) -> bool:
    return bool((value or "").strip())


def _http_get_json(url: str, headers: dict[str, str] | None = None) -> tuple[str, Any, str | None]:
    """GET a JSON endpoint and classify the outcome.

    Returns (status, payload_or_None, error_or_None) where status is one of
    success / unauthorized / rate_limited / error. Secrets are kept out of the
    error string via ``_safe_error``.
    """
    request = Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=12) as response:
            return "success", json.loads(response.read().decode("utf-8")), None
    except HTTPError as exc:
        if exc.code in (401, 403):
            return "unauthorized", None, f"HTTP {exc.code}"
        if exc.code == 429:
            return "rate_limited", None, f"HTTP {exc.code}"
        return "error", None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — network/parse errors all collapse to "error"
        return "error", None, _safe_error(exc)


# --------------------------------------------------------------------------- #
# Alpaca paper account + market data
# --------------------------------------------------------------------------- #
def _alpaca_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", "").strip(),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", "").strip(),
        "Accept": "application/json",
    }


def probe_alpaca_paper() -> dict[str, Any]:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    base_url = os.getenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets").strip()
    result: dict[str, Any] = {
        "api_key_present": _present(api_key),
        "secret_key_present": _present(secret_key),
        "paper_base_url_present": _present(base_url),
        "paper_base_url_valid": urlparse(base_url).netloc.lower() == "paper-api.alpaca.markets",
        "account_status": "not_checked",
        "market_data_status": "not_checked",
        "status": "no_credentials",
    }
    if not api_key or not secret_key:
        result["action"] = "Set ALPACA_API_KEY and ALPACA_SECRET_KEY for the paper account."
        return result
    if not result["paper_base_url_valid"]:
        result["status"] = "invalid_paper_base_url"
        result["action"] = "Set ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets."
        return result

    account_status, account_data, account_error = _http_get_json(
        base_url.rstrip("/") + "/v2/account",
        headers=_alpaca_headers(),
    )
    result["account_status"] = account_status
    if account_error:
        result["account_error"] = account_error
    if isinstance(account_data, dict):
        result["trading_blocked"] = bool(account_data.get("trading_blocked") or account_data.get("account_blocked"))

    market_status, market_data, market_error = _http_get_json(
        "https://data.alpaca.markets/v2/stocks/SPY/quotes/latest",
        headers=_alpaca_headers(),
    )
    result["market_data_status"] = market_status
    if market_error:
        result["market_data_error"] = market_error
    if isinstance(market_data, dict):
        result["market_data_has_quote"] = bool(market_data.get("quote"))

    if account_status == "success" and market_status in {"success", "no_data"}:
        result["status"] = "success"
    elif account_status in {"unauthorized", "rate_limited"} or market_status in {"unauthorized", "rate_limited"}:
        result["status"] = account_status if account_status != "success" else market_status
        result["action"] = "Check Alpaca paper credentials and market-data entitlement."
    else:
        result["status"] = "error"
        result["action"] = "Check network access to paper-api.alpaca.markets and data.alpaca.markets."
    return result


# --------------------------------------------------------------------------- #
# Polygon news / catalysts
# --------------------------------------------------------------------------- #
def probe_polygon(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("POLYGON_API_KEY", "").strip()
    result: dict[str, Any] = {
        "key_present": _present(key),
        "endpoint": POLYGON_NEWS_URL,
        "status": "no_key",
        "raw_items": 0,
        "parsed_candidates": 0,
    }
    if not key:
        return result
    ticker = symbols[0] if symbols else "AAPL"
    url = POLYGON_NEWS_URL + "?" + urlencode(
        {"ticker": ticker, "limit": 5, "order": "desc", "sort": "published_utc", "apiKey": key}
    )
    status, data, error = _http_get_json(url)
    results = (data or {}).get("results", []) if isinstance(data, dict) else []
    result["raw_items"] = len(results)
    result["parsed_candidates"] = sum(1 for item in results if item.get("title"))
    if status == "success" and not results:
        status = "no_data"
    result["status"] = status
    if error:
        result["error"] = error
    return result


# --------------------------------------------------------------------------- #
# SEC EDGAR
# --------------------------------------------------------------------------- #
def probe_sec(symbols: list[str], max_symbols: int = 5) -> dict[str, Any]:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    result: dict[str, Any] = {
        "user_agent_present": _present(user_agent),
        "endpoint": SEC_SUBMISSIONS_URL,
        "status": "no_user_agent",
        "filings_count": 0,
        "mapped_ticker_count": 0,
        "candidate_count": 0,
    }
    if not user_agent:
        return result
    # A small slice keeps the probe fast (one submissions GET per mapped ticker).
    probe_symbols = symbols[:max_symbols]
    try:
        cik_map = _sec_cik_map(user_agent)
        result["mapped_ticker_count"] = sum(1 for sym in probe_symbols if cik_map.get(sym))
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = _safe_error(exc)
        result["endpoint"] = SEC_TICKERS_URL
        return result

    feed = _fetch_sec_filings(probe_symbols)
    status = feed.get("status", "error")
    # Normalize to the smoke-test vocabulary: ok -> success/no_data.
    if status == "ok":
        status = "success" if feed.get("count", 0) else "no_data"
    elif status == "disabled":
        status = "no_user_agent"
    result["status"] = status
    result["filings_count"] = int(feed.get("count", 0))
    result["candidate_count"] = int(feed.get("count", 0))
    if feed.get("reason"):
        result["error"] = feed["reason"]
    return result


# --------------------------------------------------------------------------- #
# Polygon futures aggregates
# --------------------------------------------------------------------------- #
def probe_futures(limit: int = 3) -> dict[str, Any]:
    # Imported lazily so a missing/slow futures module can't break the other
    # probes, and so module import never reaches out to the network.
    from .futures_pulse import (
        TRACKED_CONTRACTS,
        PolygonFuturesProvider,
        session_date_for,
    )

    key = os.getenv("POLYGON_API_KEY", "").strip()
    result: dict[str, Any] = {
        "key_present": _present(key),
        "contracts_checked": 0,
        "contracts_with_data": 0,
        "contracts_without_data": 0,
    }
    if not key:
        result["status"] = "no_key"
        return result
    # min_interval_sec=0: a smoke test should be fast; the throttled full-board
    # pull is the scheduler's job, not this probe.
    provider = PolygonFuturesProvider(min_interval_sec=0.0)
    session = session_date_for()
    specs = TRACKED_CONTRACTS[: max(1, limit)]
    with_data = 0
    for spec in specs:
        try:
            series = provider.fetch_overnight(spec, session)
        except Exception:  # noqa: BLE001
            series = None
        if series is not None and getattr(series, "bars", None):
            with_data += 1
    result["contracts_checked"] = len(specs)
    result["contracts_with_data"] = with_data
    result["contracts_without_data"] = len(specs) - with_data
    result["session_date"] = session
    result["status"] = "success" if with_data else "no_data"
    return result


# --------------------------------------------------------------------------- #
# Polygon options flow
# --------------------------------------------------------------------------- #
def probe_options() -> dict[str, Any]:
    from .options_flow import PolygonOptionsFlowProvider

    key = os.getenv("POLYGON_API_KEY", "").strip()
    raw = os.getenv("POLYGON_OPTIONS_WATCHLIST", "").strip()
    watchlist = [s.strip().upper() for s in raw.split(",") if s.strip()] if raw else ["SPY", "QQQ", "NVDA"]
    preview_limit = int(os.getenv("POLYGON_OPTIONS_PREVIEW_LIMIT", "3") or 3)
    watchlist = watchlist[: max(1, preview_limit)]
    result: dict[str, Any] = {
        "key_present": _present(key),
        "watchlist_checked": 0,
        "symbols_with_data": 0,
        "symbols_without_data": 0,
        "watchlist": watchlist,
    }
    if not key:
        result["status"] = "no_key"
        return result
    provider = PolygonOptionsFlowProvider(
        min_interval_sec=0.0,
        max_contracts_per_side=int(os.getenv("POLYGON_OPTIONS_MAX_CONTRACTS_PER_SIDE", "4") or 4),
    )
    with_data = 0
    for symbol in watchlist:
        try:
            inputs = provider.fetch(symbol)
        except Exception:  # noqa: BLE001
            inputs = None
        if inputs is not None:
            with_data += 1
    result["watchlist_checked"] = len(watchlist)
    result["symbols_with_data"] = with_data
    result["symbols_without_data"] = len(watchlist) - with_data
    result["status"] = "success" if with_data else "no_data"
    return result


def run_smoke_test(futures_limit: int = 3, sec_max_symbols: int = 5) -> dict[str, Any]:
    symbols = _watchlist(None)
    return {
        "polygon": probe_polygon(symbols),
        "sec_edgar": probe_sec(symbols, max_symbols=sec_max_symbols),
        "alpaca_paper": probe_alpaca_paper(),
        "futures": probe_futures(limit=futures_limit),
        "options": probe_options(),
    }


def _print_human(report: dict[str, Any]) -> None:
    poly = report["polygon"]
    sec = report["sec_edgar"]
    alpaca = report["alpaca_paper"]
    fut = report["futures"]
    opt = report["options"]

    print("AlphaLabs source smoke test (read-only — no ideas, no trades, no secrets logged)")
    print("")
    print("Polygon (news/catalysts):")
    print(f"  key present:        {'yes' if poly['key_present'] else 'no'}")
    print(f"  endpoint attempted: {poly['endpoint']}")
    print(f"  status:             {poly['status']}")
    print(f"  raw items:          {poly['raw_items']}")
    print(f"  parsed candidates:  {poly['parsed_candidates']}")

    print("")
    print("SEC EDGAR:")
    print(f"  user agent present: {'yes' if sec['user_agent_present'] else 'no'}")
    print(f"  endpoint attempted: {sec['endpoint']}")
    print(f"  status:             {sec['status']}")
    print(f"  filings count:      {sec['filings_count']}")
    print(f"  mapped tickers:     {sec['mapped_ticker_count']}")
    print(f"  candidate count:    {sec['candidate_count']}")

    print("")
    print("Alpaca paper:")
    print(f"  API key present:      {'yes' if alpaca['api_key_present'] else 'no'}")
    print(f"  secret key present:   {'yes' if alpaca['secret_key_present'] else 'no'}")
    print(f"  paper base URL valid: {'yes' if alpaca['paper_base_url_valid'] else 'no'}")
    print(f"  account status:       {alpaca['account_status']}")
    print(f"  market data status:   {alpaca['market_data_status']}")
    print(f"  overall status:       {alpaca['status']}")
    if alpaca.get("action"):
        print(f"  action:               {alpaca['action']}")

    print("")
    print("Futures (Polygon aggregates):")
    print(f"  key present:          {'yes' if fut['key_present'] else 'no'}")
    print(f"  contracts checked:    {fut['contracts_checked']}")
    print(f"  contracts with data:  {fut['contracts_with_data']}")
    print(f"  contracts no data:    {fut['contracts_without_data']}")

    print("")
    print("Options (Polygon flow):")
    print(f"  key present:          {'yes' if opt['key_present'] else 'no'}")
    print(f"  watchlist checked:    {opt['watchlist_checked']}")
    print(f"  symbols with data:    {opt['symbols_with_data']}")
    print(f"  symbols no data:      {opt['symbols_without_data']}")


# A source is "healthy enough" for --strict if it succeeded, returned no data
# (entitled but quiet, e.g. market closed), or is simply not configured.
_OK_STATUSES = {"success", "no_data", "no_key", "no_user_agent", "no_credentials"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only smoke test for AlphaLabs live data sources.")
    parser.add_argument("--json", action="store_true", help="Emit the raw JSON report instead of the human summary.")
    parser.add_argument("--futures-limit", type=int, default=3, help="How many futures contracts to probe (default 3).")
    parser.add_argument("--sec-max-symbols", type=int, default=5, help="How many watchlist symbols to probe on SEC (default 5).")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any source errors / is unauthorized / rate-limited.")
    args = parser.parse_args(argv)

    load_dotenv()
    report = run_smoke_test(futures_limit=args.futures_limit, sec_max_symbols=args.sec_max_symbols)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)

    if args.strict:
        bad = [name for name, section in report.items() if section.get("status") not in _OK_STATUSES]
        if bad:
            print(f"\n[strict] sources needing attention: {', '.join(sorted(bad))}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
