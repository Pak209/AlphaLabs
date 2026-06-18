from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
POLYGON_NEWS_URL = "https://api.polygon.io/v2/reference/news"
POLYGON_SNAPSHOT_URL = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"
BENZINGA_INSIDER_URL = "https://api.benzinga.com/api/v2.1/calendar/insider-transactions"
TIINGO_NEWS_URL = "https://api.tiingo.com/tiingo/news"
NEWSFILTER_SEARCH_URL = "https://api.newsfilter.io/search"

DEFAULT_WATCHLIST = [
    "AAPL", "AMZN", "AMD", "AVGO", "COIN", "GOOGL", "META", "MSFT", "MSTR",
    "NVDA", "ORCL", "PLTR", "SMCI", "TSLA",
]
MATERIAL_SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "S-1", "S-3", "424B5", "424B3", "4"}


def fetch_live_catalysts(watchlist: list[str] | None = None, limit: int = 40) -> dict[str, Any]:
    symbols = _watchlist(watchlist)
    providers = [
        _fetch_sec_filings(symbols),
        _fetch_polygon_news(symbols),
        _fetch_benzinga_news(symbols),
        _fetch_benzinga_insiders(symbols),
        _fetch_tiingo_news(symbols),
        _fetch_newsfilter(symbols),
    ]
    catalysts = []
    seen = set()
    for provider in providers:
        for item in provider.get("catalysts", []):
            key = (item.get("source"), item.get("ticker"), item.get("headline"), item.get("published_at"))
            if key in seen:
                continue
            seen.add(key)
            catalysts.append(item)
    catalysts.sort(key=lambda row: row.get("published_at", ""), reverse=True)
    return {
        "status": "ok" if catalysts else "configured_no_items" if any(p.get("status") == "ok" for p in providers) else "no_live_providers",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "watchlist": symbols,
        "providers": providers,
        "catalysts": catalysts[: max(1, min(limit, 100))],
    }


def _fetch_sec_filings(symbols: list[str]) -> dict[str, Any]:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        return _disabled("SEC EDGAR", "Set SEC_USER_AGENT to a descriptive contact string before polling sec.gov.")
    try:
        cik_by_symbol = _sec_cik_map(user_agent)
        catalysts = []
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=int(os.getenv("SEC_LOOKBACK_DAYS", "3")))
        for symbol in symbols[: int(os.getenv("SEC_MAX_SYMBOLS", "25"))]:
            cik = cik_by_symbol.get(symbol)
            if not cik:
                continue
            data = _fetch_json(SEC_SUBMISSIONS_URL.format(cik=cik), headers={"User-Agent": user_agent})
            recent = data.get("filings", {}).get("recent", {})
            for form, filing_date, accession, primary_doc in zip(
                recent.get("form", []),
                recent.get("filingDate", []),
                recent.get("accessionNumber", []),
                recent.get("primaryDocument", []),
            ):
                if form not in MATERIAL_SEC_FORMS:
                    continue
                try:
                    if datetime.fromisoformat(filing_date).date() < cutoff:
                        continue
                except ValueError:
                    pass
                headline, summary = _sec_filing_text(symbol, form)
                catalysts.append({
                    "ticker": symbol,
                    "headline": headline,
                    "summary": summary,
                    "source": "SEC EDGAR submissions",
                    "source_url": _sec_filing_url(cik, accession, primary_doc),
                    "published_at": f"{filing_date}T13:00:00Z",
                    "security_type": "stock",
                    "exchange": "",
                })
        return {"name": "SEC EDGAR", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("SEC EDGAR", exc)


def _sec_filing_text(symbol: str, form: str) -> tuple[str, str]:
    """Build the headline/summary for a SEC filing.

    Offering/shelf forms get directional language so the catalyst scorer can read
    them as dilution/bearish signals; all other forms keep the neutral wording.
    """
    form_u = form.upper()
    if form_u in {"424B5", "424B3"}:
        return (
            f"{symbol} filed {form} offering prospectus with the SEC",
            f"SEC {form} offering prospectus detected for {symbol} — a registered securities "
            "offering that is typically dilutive. Confirm price/volume before any paper test.",
        )
    if form_u == "S-3":
        return (
            f"{symbol} filed S-3 shelf registration with the SEC",
            f"SEC S-3 shelf registration detected for {symbol} — enables a future offering and is "
            "a potential dilution signal. Confirm price/volume before any paper test.",
        )
    return (
        f"{symbol} filed {form} with the SEC",
        f"SEC filing detected: {form}. Review the filing before treating this as directional.",
    )


def _fetch_polygon_news(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("POLYGON_API_KEY", "").strip()
    if not key:
        return _disabled("Polygon News", "Set POLYGON_API_KEY to enable Polygon ticker news.")
    try:
        catalysts = []
        for symbol in symbols[: int(os.getenv("POLYGON_MAX_SYMBOLS", "15"))]:
            params = urlencode({"ticker": symbol, "limit": 5, "order": "desc", "sort": "published_utc", "apiKey": key})
            data = _fetch_json(f"{POLYGON_NEWS_URL}?{params}")
            for item in data.get("results", []):
                related_tickers = [str(ticker).upper() for ticker in item.get("tickers", []) if ticker]
                catalysts.append({
                    "ticker": symbol,
                    "headline": item.get("title", ""),
                    "summary": item.get("description") or item.get("summary") or "",
                    "source": f"Polygon News / {item.get('publisher', {}).get('name', 'publisher')}",
                    "source_url": item.get("article_url", ""),
                    "published_at": item.get("published_utc") or datetime.now(timezone.utc).isoformat(),
                    "security_type": "stock",
                    "exchange": "",
                    "related_tickers": related_tickers,
                })
        return {"name": "Polygon News", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("Polygon News", exc)


def _fetch_benzinga_news(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("BENZINGA_API_KEY", "").strip()
    if not key:
        return _disabled("Benzinga News/Press Releases", "Set BENZINGA_API_KEY to enable Benzinga news and press releases.")
    try:
        params = urlencode({
            "token": key,
            "tickers": ",".join(symbols[:50]),
            "pageSize": int(os.getenv("BENZINGA_PAGE_SIZE", "50")),
            "displayOutput": "abstract",
            "sort": "created:desc",
        })
        data = _fetch_json(f"{BENZINGA_NEWS_URL}?{params}", headers={"accept": "application/json"})
        catalysts = []
        for item in data if isinstance(data, list) else []:
            stocks = item.get("stocks") or []
            tickers = [str(stock.get("name", "")).upper() for stock in stocks if stock.get("name")] or [""]
            for symbol in tickers:
                if symbol and symbol not in symbols:
                    continue
                catalysts.append({
                    "ticker": symbol or "UNKNOWN",
                    "headline": item.get("title", ""),
                    "summary": item.get("teaser") or _strip_html(item.get("body", ""))[:500],
                    "source": f"Benzinga / {item.get('author', 'News')}",
                    "source_url": item.get("url", ""),
                    "published_at": _parse_benzinga_time(item.get("created")),
                    "security_type": "stock",
                    "exchange": "",
                })
        return {"name": "Benzinga News/Press Releases", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("Benzinga News/Press Releases", exc)


def _fetch_benzinga_insiders(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("BENZINGA_API_KEY", "").strip()
    if not key:
        return _disabled("Benzinga Insider Transactions", "Set BENZINGA_API_KEY to enable insider transaction feed.")
    try:
        params = urlencode({"token": key, "tickers": ",".join(symbols[:50]), "pageSize": 50})
        data = _fetch_json(f"{BENZINGA_INSIDER_URL}?{params}", headers={"accept": "application/json"})
        rows = data if isinstance(data, list) else data.get("insider_transactions", []) if isinstance(data, dict) else []
        catalysts = []
        for item in rows:
            symbol = str(item.get("ticker") or item.get("symbol") or "").upper()
            if symbol and symbol not in symbols:
                continue
            owner = item.get("owner_name") or item.get("insider_name") or "insider"
            transaction = item.get("transaction_type") or item.get("transactionCode") or "transaction"
            catalysts.append({
                "ticker": symbol or "UNKNOWN",
                "headline": f"{symbol or 'Company'} insider {transaction}: {owner}",
                "summary": "Insider transaction feed item. Interpret Form 4 context carefully before treating as directional.",
                "source": "Benzinga Insider Transactions",
                "source_url": "",
                "published_at": item.get("filing_date") or item.get("date") or datetime.now(timezone.utc).isoformat(),
                "security_type": "stock",
                "exchange": "",
            })
        return {"name": "Benzinga Insider Transactions", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("Benzinga Insider Transactions", exc)


def _fetch_tiingo_news(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("TIINGO_API_KEY", "").strip()
    if not key:
        return _disabled("Tiingo News", "Set TIINGO_API_KEY to enable Tiingo news.")
    try:
        params = urlencode({"tickers": ",".join(symbols[:50]), "limit": int(os.getenv("TIINGO_LIMIT", "50"))})
        data = _fetch_json(f"{TIINGO_NEWS_URL}?{params}", headers={"Authorization": f"Token {key}"})
        catalysts = []
        for item in data if isinstance(data, list) else []:
            tickers = [str(t).upper() for t in item.get("tickers", [])] or [""]
            for symbol in tickers:
                if symbol and symbol not in symbols:
                    continue
                catalysts.append({
                    "ticker": symbol or "UNKNOWN",
                    "headline": item.get("title", ""),
                    "summary": item.get("description", ""),
                    "source": f"Tiingo / {item.get('source', 'news')}",
                    "source_url": item.get("url", ""),
                    "published_at": item.get("publishedDate") or item.get("crawlDate") or datetime.now(timezone.utc).isoformat(),
                    "security_type": "stock",
                    "exchange": "",
                })
        return {"name": "Tiingo News", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("Tiingo News", exc)


def _fetch_newsfilter(symbols: list[str]) -> dict[str, Any]:
    key = os.getenv("NEWSFILTER_API_KEY", "").strip()
    if not key:
        return _disabled("Newsfilter", "Set NEWSFILTER_API_KEY to enable Newsfilter query API.")
    try:
        body = json.dumps({
            "symbols": symbols[:50],
            "from": (datetime.now(timezone.utc) - timedelta(hours=int(os.getenv("NEWSFILTER_LOOKBACK_HOURS", "6")))).isoformat(),
            "size": int(os.getenv("NEWSFILTER_SIZE", "50")),
        }).encode("utf-8")
        data = _fetch_json(
            NEWSFILTER_SEARCH_URL,
            method="POST",
            body=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        rows = data.get("articles", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        catalysts = []
        for item in rows:
            symbol = str(item.get("symbol") or item.get("ticker") or (item.get("symbols") or [""])[0]).upper()
            if symbol and symbol not in symbols:
                continue
            catalysts.append({
                "ticker": symbol or "UNKNOWN",
                "headline": item.get("title") or item.get("headline") or "",
                "summary": item.get("summary") or item.get("description") or "",
                "source": f"Newsfilter / {item.get('source', 'news')}",
                "source_url": item.get("url", ""),
                "published_at": item.get("published_at") or item.get("publishedAt") or datetime.now(timezone.utc).isoformat(),
                "security_type": "stock",
                "exchange": "",
            })
        return {"name": "Newsfilter", "status": "ok", "catalysts": catalysts, "count": len(catalysts)}
    except Exception as exc:
        return _error("Newsfilter", exc)


def _watchlist(watchlist: list[str] | None) -> list[str]:
    raw = watchlist or [item.strip() for item in os.getenv("CATALYST_WATCHLIST", "").split(",") if item.strip()] or DEFAULT_WATCHLIST
    return [symbol.upper() for symbol in raw if "/" not in symbol and symbol.upper() not in {"SPY", "QQQ", "IWM"}]


def _sec_cik_map(user_agent: str) -> dict[str, str]:
    rows = _fetch_json(SEC_TICKERS_URL, headers={"User-Agent": user_agent})
    return {str(row["ticker"]).upper(): str(row["cik_str"]).zfill(10) for row in rows.values()}


def _sec_filing_url(cik: str, accession: str, primary_doc: str) -> str:
    accession_clean = accession.replace("-", "")
    cik_int = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{primary_doc}"


def _fetch_json(url: str, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    req = Request(url, data=body, method=method, headers={"Accept": "application/json", **(headers or {})})
    with urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_benzinga_time(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def _strip_html(value: str) -> str:
    return value.replace("<p>", " ").replace("</p>", " ").replace("<br>", " ").replace("<br />", " ").strip()


def fetch_polygon_intraday(ticker: str) -> dict[str, Any]:
    """Live intraday price/volume read for a single equity ticker from Polygon.

    Uses the stocks snapshot endpoint, which returns today's session
    (open/high/low/close/volume), the prior full day, and the latest trade in
    one call. We derive:

      - gap_pct: signed % change vs the prior close (Polygon's todaysChangePerc).
      - relative_volume: today's cumulative volume / prior full-day volume. This
        UNDERSTATES early in the session (cumulative-vs-full-day), so the caller
        treats sub-1.0 readings as "no confirmation" (neutral) rather than a
        penalty — real elevated volume can only help confirm, never wrongly
        suppress a fresh 9:35am catalyst.

    Returns {"status": "ok", ...} on success, or a disabled/error envelope
    (no key, bad ticker, network) so callers fall back to neutral scoring.
    """
    key = os.getenv("POLYGON_API_KEY", "").strip()
    if not key:
        return {"status": "disabled", "reason": "Set POLYGON_API_KEY to enable live price/volume confirmation."}
    try:
        url = POLYGON_SNAPSHOT_URL.format(ticker=ticker.upper()) + "?" + urlencode({"apiKey": key})
        data = _fetch_json(url)
        snap = data.get("ticker") or {}
        day = snap.get("day") or {}
        prev = snap.get("prevDay") or {}
        last = snap.get("lastTrade") or {}
        day_vol = float(day.get("v") or 0)
        prev_vol = float(prev.get("v") or 0)
        last_price = float(last.get("p") or day.get("c") or 0)
        gap_pct = snap.get("todaysChangePerc")
        gap_pct = float(gap_pct) if gap_pct is not None else None
        relative_volume = (day_vol / prev_vol) if prev_vol > 0 and day_vol > 0 else None
        return {
            "status": "ok",
            "source": "Polygon snapshot",
            "ticker": ticker.upper(),
            "last_price": last_price,
            "gap_pct": gap_pct,
            "relative_volume": relative_volume,
            "day_volume": day_vol,
            "prev_day_volume": prev_vol,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"status": "error", "reason": _safe_error(exc)}


def fetch_yahoo_price(ticker: str) -> dict[str, Any]:
    """Keyless last-price read from Yahoo Finance's public chart endpoint.

    Used as a fallback when Polygon has no key and Alpaca is unreachable (e.g.
    restrictive networks that block the broker API). Yahoo requires a browser-ish
    User-Agent or it returns 429, so we send one. Returns an {"status": "ok",
    "last_price": ...} envelope or a disabled/error envelope so callers can fall
    back to neutral handling.
    """
    if os.getenv("YAHOO_PRICE_ENABLED", "true").strip().lower() != "true":
        return {"status": "disabled", "reason": "Set YAHOO_PRICE_ENABLED=true to allow Yahoo Finance price fallback."}
    try:
        url = YAHOO_CHART_URL.format(ticker=ticker.upper()) + "?" + urlencode({"interval": "1d", "range": "1d"})
        data = _fetch_json(url, headers={"User-Agent": "Mozilla/5.0 (AlphaLab paper-research)"})
        result = ((data.get("chart") or {}).get("result") or [{}])[0]
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        last_price = float(price) if price is not None else 0.0
        if last_price <= 0:
            return {"status": "error", "reason": "Yahoo returned no usable price."}
        return {
            "status": "ok",
            "source": "Yahoo Finance chart",
            "ticker": ticker.upper(),
            "last_price": last_price,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"status": "error", "reason": _safe_error(exc)}


def _disabled(name: str, reason: str) -> dict[str, Any]:
    return {"name": name, "status": "disabled", "reason": reason, "catalysts": [], "count": 0}


def _error(name: str, exc: Exception) -> dict[str, Any]:
    return {"name": name, "status": "error", "reason": _safe_error(exc), "catalysts": [], "count": 0}


def _safe_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0][:500]
    text = re.sub(r"([?&](?:apiKey|token)=)[^&\\s]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    for name in ("POLYGON_API_KEY", "BENZINGA_API_KEY", "TIINGO_API_KEY", "NEWSFILTER_API_KEY"):
        value = os.getenv(name, "").strip()
        if value and len(value) >= 4:
            text = text.replace(value, f"<redacted:{name}>")
    return text[:220]
