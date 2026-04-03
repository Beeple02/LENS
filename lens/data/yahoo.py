"""Yahoo Finance async client for LENS."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx

from lens.config import Config

_config = Config()

_BASE_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_BASE_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
_BASE_SUMMARY = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_RATE_LIMIT_DELAY = 0.3  # 300ms between requests
_last_request_time: float = 0.0
_crumb: Optional[str] = None


async def _throttle() -> None:
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[dict[str, Any]] = None,
    retries: int = 3,
) -> Any:
    """GET with throttling and exponential backoff on 429."""
    await _throttle()
    backoff = 2.0
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=_HEADERS)
            if resp.status_code == 429:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("raw")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def get_chart(
    ticker: str,
    interval: str = "1d",
    range_: str = "1y",
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """
    Fetch OHLCV data from Yahoo Finance chart API.
    Returns list of dicts: {date, open, high, low, close, adj_close, volume}
    """
    url = _BASE_CHART.format(ticker=ticker)
    params = {"interval": interval, "range": range_}

    async def _fetch(c: httpx.AsyncClient) -> list[dict[str, Any]]:
        data = await _get(c, url, params)
        result_data = data.get("chart", {}).get("result")
        if not result_data:
            return []
        result = result_data[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        adjclose_list = (
            result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
        )

        from datetime import datetime, timezone

        rows = []
        for i, ts in enumerate(timestamps):
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
                close_val = (quote.get("close") or [])[i] if quote.get("close") else None
                if close_val is None:
                    continue
                rows.append({
                    "date": date_str,
                    "open": (quote.get("open") or [])[i] if quote.get("open") else None,
                    "high": (quote.get("high") or [])[i] if quote.get("high") else None,
                    "low": (quote.get("low") or [])[i] if quote.get("low") else None,
                    "close": close_val,
                    "adj_close": adjclose_list[i] if i < len(adjclose_list) else close_val,
                    "volume": (quote.get("volume") or [])[i] if quote.get("volume") else None,
                })
            except (IndexError, TypeError):
                continue
        return rows

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


async def get_quote(
    ticker: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """
    Fetch current quote for a ticker.
    Returns: {price, change, change_pct, volume, market_cap, prev_close, open, high, low,
               day_high_52w, day_low_52w, name, currency, exchange}
    """
    url = _BASE_CHART.format(ticker=ticker)
    params = {"interval": "1d", "range": "1d"}

    async def _fetch(c: httpx.AsyncClient) -> dict[str, Any]:
        data = await _get(c, url, params)
        result_data = data.get("chart", {}).get("result")
        if not result_data:
            return {}
        result = result_data[0]
        meta = result.get("meta", {})
        return {
            "ticker": ticker,
            "name": meta.get("longName") or meta.get("shortName", ticker),
            "price": _safe_float(meta.get("regularMarketPrice")),
            "prev_close": _safe_float(meta.get("previousClose") or meta.get("chartPreviousClose")),
            "change": None,  # computed below
            "change_pct": None,
            "open": _safe_float(meta.get("regularMarketOpen")),
            "high": _safe_float(meta.get("regularMarketDayHigh")),
            "low": _safe_float(meta.get("regularMarketDayLow")),
            "volume": _safe_float(meta.get("regularMarketVolume")),
            "market_cap": None,
            "currency": meta.get("currency", "EUR"),
            "exchange": meta.get("exchangeName", ""),
            "day_high_52w": _safe_float(meta.get("fiftyTwoWeekHigh")),
            "day_low_52w": _safe_float(meta.get("fiftyTwoWeekLow")),
        }

    if client is not None:
        q = await _fetch(client)
    else:
        async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
            q = await _fetch(c)

    # Compute change from prev_close
    if q.get("price") and q.get("prev_close"):
        q["change"] = round(q["price"] - q["prev_close"], 4)
        q["change_pct"] = round((q["change"] / q["prev_close"]) * 100, 2)

    return q


async def _ensure_crumb(c: httpx.AsyncClient) -> Optional[str]:
    """Fetch and cache a Yahoo Finance crumb (required for quoteSummary v10)."""
    global _crumb
    if _crumb:
        return _crumb
    try:
        # Establish a session cookie with Yahoo Finance
        await c.get("https://fc.yahoo.com/", headers=_HEADERS, follow_redirects=True)
        r = await c.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            headers={**_HEADERS, "Accept": "*/*"},
        )
        if r.status_code == 200 and r.text.strip():
            _crumb = r.text.strip()
    except Exception:
        pass
    return _crumb


async def get_fundamentals(
    ticker: str,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """
    Fetch fundamental data snapshot from Yahoo quoteSummary.
    Returns flat dict matching the fundamentals table schema.
    """
    url = _BASE_SUMMARY.format(ticker=ticker)
    modules = ",".join([
        "summaryDetail",
        "defaultKeyStatistics",
        "financialData",
        "incomeStatementHistory",
        "balanceSheetHistory",
        "cashflowStatementHistory",
    ])

    async def _fetch(c: httpx.AsyncClient) -> dict[str, Any]:
        crumb = await _ensure_crumb(c)
        params: dict[str, Any] = {"modules": modules}
        if crumb:
            params["crumb"] = crumb
        data = await _get(c, url, params)
        qs = data.get("quoteSummary", {}).get("result")
        if not qs:
            return {}
        result = qs[0]
        sd = result.get("summaryDetail", {})
        ks = result.get("defaultKeyStatistics", {})
        fd = result.get("financialData", {})

        return {
            "pe_ratio": _safe_float(sd.get("trailingPE")),
            "forward_pe": _safe_float(sd.get("forwardPE")),
            "pb_ratio": _safe_float(ks.get("priceToBook")),
            "ps_ratio": _safe_float(ks.get("priceToSalesTrailing12Months")),
            "ev_ebitda": _safe_float(ks.get("enterpriseToEbitda")),
            "dividend_yield": _safe_float(sd.get("dividendYield")),
            "payout_ratio": _safe_float(sd.get("payoutRatio")),
            "market_cap": _safe_float(sd.get("marketCap")),
            "enterprise_value": _safe_float(ks.get("enterpriseValue")),
            "revenue_ttm": _safe_float(fd.get("totalRevenue")),
            "ebitda": _safe_float(fd.get("ebitda")),
            "net_income": _safe_float(fd.get("netIncomeToCommon")),
            "debt_to_equity": _safe_float(fd.get("debtToEquity")),
            "current_ratio": _safe_float(fd.get("currentRatio")),
            "roe": _safe_float(fd.get("returnOnEquity")),
            "roa": _safe_float(fd.get("returnOnAssets")),
            "revenue_growth": _safe_float(fd.get("revenueGrowth")),
            "earnings_growth": _safe_float(fd.get("earningsGrowth")),
        }

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


async def search(
    query: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """
    Search Yahoo Finance for securities matching a query.
    Returns list of dicts: {ticker, name, exchange, type, isin}
    """
    params = {"q": query, "quotesCount": 20, "newsCount": 0, "listsCount": 0}

    async def _fetch(c: httpx.AsyncClient) -> list[dict[str, Any]]:
        data = await _get(c, _BASE_SEARCH, params)
        quotes = data.get("quotes", [])
        results = []
        for q in quotes:
            if q.get("quoteType") in ("EQUITY", "ETF", "INDEX"):
                results.append({
                    "ticker": q.get("symbol", ""),
                    "name": q.get("longname") or q.get("shortname", ""),
                    "exchange": q.get("exchange", ""),
                    "type": q.get("quoteType", ""),
                    "isin": None,  # Yahoo doesn't return ISIN in search
                })
        return results

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


if __name__ == "__main__":
    import asyncio
    import json

    async def demo() -> None:
        print("=== Chart (MC.PA, 1d, 1mo) ===")
        chart = await get_chart("MC.PA", interval="1d", range_="1mo")
        print(f"  {len(chart)} rows")
        if chart:
            print(f"  First: {chart[0]}")
            print(f"  Last:  {chart[-1]}")

        print("\n=== Quote (MC.PA) ===")
        q = await get_quote("MC.PA")
        print(json.dumps(q, indent=2))

        print("\n=== Fundamentals (MC.PA) ===")
        f = await get_fundamentals("MC.PA")
        print(json.dumps(f, indent=2))

        print("\n=== Search 'LVMH' ===")
        results = await search("LVMH")
        for r in results[:5]:
            print(f"  {r['ticker']:12} {r['name']}")

    asyncio.run(demo())
