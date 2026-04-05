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
_BASE_TIMESERIES = (
    "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_RATE_LIMIT_DELAY = 0.3  # 300ms between requests
_last_request_time: float = 0.0
_crumb: Optional[str] = None
_cached_cookies: dict[str, str] = {}   # cookies that go with the crumb


def _invalidate_crumb() -> None:
    global _crumb, _cached_cookies
    _crumb = None
    _cached_cookies = {}


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
    """Fetch and cache a Yahoo Finance crumb + its associated cookies."""
    global _crumb, _cached_cookies
    if _crumb:
        # Re-inject cookies into this client so the crumb is accepted
        for k, v in _cached_cookies.items():
            c.cookies.set(k, v, domain=".yahoo.com")
        return _crumb
    try:
        await c.get("https://fc.yahoo.com/", headers=_HEADERS, follow_redirects=True)
        _cached_cookies = dict(c.cookies)
        r = await c.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            headers={**_HEADERS, "Accept": "*/*"},
        )
        if r.status_code == 200 and r.text.strip():
            _crumb = r.text.strip()
            _cached_cookies = dict(c.cookies)
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
        try:
            data = await _get(c, url, params)
        except Exception as exc:
            # 401 = crumb/cookie expired; invalidate and retry once with fresh crumb
            if "401" in str(exc):
                _invalidate_crumb()
                crumb = await _ensure_crumb(c)
                if crumb:
                    params["crumb"] = crumb
                data = await _get(c, url, params)
            else:
                raise
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


_EUROPEAN_EXCHANGES = frozenset({
    # Euronext
    "PAR", "AMS", "BRU", "LIS", "DUB", "OSL",
    # Germany
    "GER", "FRA", "ETR", "STU", "DUS", "HAM", "MUN", "BER", "TLX",
    # UK
    "LSE", "IOB",
    # Nordic
    "STO", "HEL", "CPH", "ICE",
    # Southern Europe
    "MIL", "MCE", "ATH",
    # Other
    "VIE", "WAR", "BUC", "PRA", "BUD", "SWX", "EBS", "ZRH",
})


async def search(
    query: str,
    client: Optional[httpx.AsyncClient] = None,
    european_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Search Yahoo Finance for securities matching a query.
    Returns list of dicts: {ticker, name, exchange, type, isin}
    By default filters to European exchanges only.
    """
    params = {"q": query, "quotesCount": 20, "newsCount": 0, "listsCount": 0}

    async def _fetch(c: httpx.AsyncClient) -> list[dict[str, Any]]:
        data = await _get(c, _BASE_SEARCH, params)
        quotes = data.get("quotes", [])
        results = []
        for q in quotes:
            if q.get("quoteType") not in ("EQUITY", "ETF", "INDEX"):
                continue
            exchange = q.get("exchange", "")
            if european_only and exchange not in _EUROPEAN_EXCHANGES:
                continue
            results.append({
                "ticker":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname", ""),
                "exchange": exchange,
                "type":     q.get("quoteType", ""),
                "isin":     None,
            })
        return results

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


# ---------------------------------------------------------------------------
# Deep-dive helpers (financials timeseries, quoteSummary modules, peers)
# ---------------------------------------------------------------------------

_ANNUAL_FIELDS = [
    "annualTotalRevenue", "annualGrossProfit", "annualOperatingIncome",
    "annualEbitda", "annualNetIncome", "annualBasicEPS", "annualDilutedEPS",
    "annualResearchAndDevelopment", "annualSellingGeneralAndAdministration",
    "annualTotalAssets", "annualTotalLiabilitiesNetMinorityInterest",
    "annualStockholdersEquity", "annualCashAndCashEquivalents",
    "annualTotalDebt", "annualNetDebt", "annualGoodwillAndOtherIntangibleAssets",
    "annualInventory", "annualCurrentAssets", "annualCurrentLiabilities",
    "annualOperatingCashFlow", "annualCapitalExpenditure", "annualFreeCashFlow",
    "annualCashDividendsPaid", "annualIssuanceOfDebt", "annualRepurchaseOfCapitalStock",
]
_QUARTERLY_FIELDS = [f.replace("annual", "quarterly") for f in _ANNUAL_FIELDS]

_EU_TICKER_SUFFIXES = (".PA", ".DE", ".L", ".AS", ".SW", ".MI", ".MC", ".ST", ".HE", ".OL", ".CO", ".VI")

_PEER_FALLBACKS: dict[str, list[str]] = {
    "luxury":       ["MC.PA", "OR.PA", "RMS.PA", "KER.PA", "EL.PA"],
    "energy":       ["TTE.PA", "ENGI.PA"],
    "banking":      ["BNP.PA", "GLE.PA", "ACA.PA"],
    "aerospace":    ["AIR.PA", "SAF.PA", "HO.PA", "AM.PA"],
    "pharma":       ["SAN.PA", "BN.PA"],
    "technology":   ["CAP.PA", "ATO.PA", "DSY.PA"],
    "telecom":      ["ORA.PA", "PUB.PA"],
}


async def _fetch_timeseries_data(
    ticker: str,
    fields: list[str],
    c: httpx.AsyncClient,
) -> dict[str, dict[str, float]]:
    """Fetch fundamentals timeseries. Returns {field_name: {date_str: raw_value}}."""
    import time as _time
    period2 = int(_time.time())
    period1 = period2 - 5 * 365 * 24 * 3600
    url = _BASE_TIMESERIES.format(ticker=ticker)
    crumb = await _ensure_crumb(c)
    params: dict[str, Any] = {
        "period1": period1,
        "period2": period2,
        "merge": "false",
        "type": ",".join(fields),
    }
    if crumb:
        params["crumb"] = crumb
    try:
        data = await _get(c, url, params)
    except Exception:
        return {}
    out: dict[str, dict[str, float]] = {}
    for item in data.get("timeseries", {}).get("result", []):
        field_name: str = item.get("type", "")
        if not field_name:
            continue
        entries = item.get(field_name) or []
        series: dict[str, float] = {}
        for entry in entries:
            date_str = entry.get("asOfDate", "")
            reported = entry.get("reportedValue", {})
            raw = reported.get("raw") if isinstance(reported, dict) else reported
            if date_str and raw is not None:
                try:
                    series[date_str] = float(raw)
                except (TypeError, ValueError):
                    pass
        if series:
            out[field_name] = series
    return out


async def _fetch_summary_modules(
    ticker: str,
    modules: str,
    c: httpx.AsyncClient,
) -> dict[str, Any]:
    """quoteSummary with crumb auth; returns the first result dict."""
    url = _BASE_SUMMARY.format(ticker=ticker)
    crumb = await _ensure_crumb(c)
    params: dict[str, Any] = {"modules": modules}
    if crumb:
        params["crumb"] = crumb
    try:
        data = await _get(c, url, params)
    except Exception as exc:
        if "401" in str(exc):
            _invalidate_crumb()
            crumb = await _ensure_crumb(c)
            if crumb:
                params["crumb"] = crumb
            data = await _get(c, url, params)
        else:
            raise
    qs = data.get("quoteSummary", {}).get("result")
    if not qs:
        return {}
    return qs[0]


async def _fetch_peer_data(ticker: str, c: httpx.AsyncClient) -> dict[str, Any]:
    """Discover EU peers via industry search + fetch their key stats."""
    # Step 1: get sector/industry from summaryProfile
    sector = industry = ""
    try:
        profile_result = await _fetch_summary_modules(ticker, "summaryProfile", c)
        sp = profile_result.get("summaryProfile", {})
        sector = sp.get("sector", "")
        industry = sp.get("industry", "")
    except Exception:
        pass

    # Step 2: search for EU-listed companies in same industry
    peer_tickers: list[str] = []
    if industry:
        try:
            srch = await _get(c, _BASE_SEARCH, {
                "q": industry, "lang": "en", "region": "FR",
                "quotesCount": 12, "newsCount": 0,
            })
            for q in srch.get("quotes", []):
                sym = q.get("symbol", "")
                if sym == ticker:
                    continue
                if any(sym.endswith(sfx) for sfx in _EU_TICKER_SUFFIXES):
                    peer_tickers.append(sym)
                if len(peer_tickers) >= 5:
                    break
        except Exception:
            pass

    # Step 3: fallback if fewer than 3 EU peers found
    if len(peer_tickers) < 3:
        combined = f"{sector} {industry}".lower()
        for key, fallback in _PEER_FALLBACKS.items():
            if key in combined:
                peer_tickers = [t for t in fallback if t != ticker][:5]
                break

    # Step 4: fetch stats for target + all peers
    all_tickers = [ticker] + peer_tickers
    peer_mods = "defaultKeyStatistics,financialData,summaryDetail"
    gather_results = await asyncio.gather(
        *[_fetch_summary_modules(t, peer_mods, c) for t in all_tickers],
        return_exceptions=True,
    )
    all_data: dict[str, dict] = {}
    for t, r in zip(all_tickers, gather_results):
        if not isinstance(r, Exception):
            all_data[t] = r

    return {
        "target":   ticker,
        "tickers":  peer_tickers,
        "data":     all_data,
        "sector":   sector,
        "industry": industry,
    }


async def get_deep_dive(ticker: str) -> dict[str, Any]:
    """
    Fetch all data needed for the DeepDive screen concurrently.
    Returns dict with keys: quote, financials, earnings, analysts,
    dividends, ownership, peers.
    """
    async with httpx.AsyncClient(timeout=30) as c:
        await _ensure_crumb(c)

        # Dividend chart events (no crumb needed)
        async def _div_chart() -> dict:
            url = _BASE_CHART.format(ticker=ticker)
            try:
                d = await _get(c, url, {"events": "dividends,splits", "range": "10y", "interval": "1d"})
                return d.get("chart", {}).get("result", [{}])[0].get("events", {}).get("dividends", {})
            except Exception:
                return {}

        results = await asyncio.gather(
            get_quote(ticker, client=c),
            _fetch_timeseries_data(ticker, _ANNUAL_FIELDS, c),
            _fetch_timeseries_data(ticker, _QUARTERLY_FIELDS, c),
            _fetch_summary_modules(ticker, "earnings,earningsHistory,earningsTrend,calendarEvents", c),
            _fetch_summary_modules(ticker, "recommendationTrend,upgradeDowngradeHistory,financialData,defaultKeyStatistics", c),
            _fetch_summary_modules(ticker, "summaryDetail,defaultKeyStatistics", c),
            _fetch_summary_modules(ticker, "insiderTransactions,insiderHolders,institutionOwnership,majorHoldersBreakdown,fundOwnership,netSharePurchaseActivity", c),
            _div_chart(),
            _fetch_peer_data(ticker, c),
            return_exceptions=True,
        )

        def _s(v: Any, default: Any) -> Any:
            return default if isinstance(v, Exception) else v

        quote_r, annual_r, qtr_r, earn_r, anal_r, div_qs_r, own_r, div_chart_r, peers_r = results
        return {
            "quote":      _s(quote_r, {}),
            "financials": {"annual": _s(annual_r, {}), "quarterly": _s(qtr_r, {})},
            "earnings":   _s(earn_r, {}),
            "analysts":   _s(anal_r, {}),
            "dividends":  {**_s(div_qs_r, {}), "chart_events": _s(div_chart_r, {})},
            "ownership":  _s(own_r, {}),
            "peers":      _s(peers_r, {"target": ticker, "tickers": [], "data": {}, "sector": "", "industry": ""}),
        }


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
