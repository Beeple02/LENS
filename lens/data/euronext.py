"""Euronext live data client for LENS."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from lens.config import Config
from lens.data.parser import parse_euronext_quote_html, parse_euronext_search_html

_config = Config()

_LIVE_QUOTE_URL = "https://live.euronext.com/fr/ajax/getDetailedQuote/{isin}-{mic}"
_SEARCH_URL = "https://live.euronext.com/fr/search_instruments/{query}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://live.euronext.com/",
    "X-Requested-With": "XMLHttpRequest",
}


async def get_live_quote(
    isin: str,
    mic: str = "XPAR",
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """
    Fetch live quote from Euronext for a security identified by ISIN + MIC.
    Returns: {price, bid, ask, volume, open, high, low, prev_close, change, change_pct}
    Falls back to empty dict on any error.
    """
    url = _LIVE_QUOTE_URL.format(isin=isin, mic=mic)

    async def _fetch(c: httpx.AsyncClient) -> dict[str, Any]:
        try:
            resp = await c.get(url, headers=_HEADERS)
            resp.raise_for_status()
            parsed = parse_euronext_quote_html(resp.text)
            # Compute change if we have price and prev_close
            price = parsed.get("price")
            prev = parsed.get("prev_close")
            if price and prev:
                parsed["change"] = round(float(price) - float(prev), 4)
                parsed["change_pct"] = round(
                    ((float(price) - float(prev)) / float(prev)) * 100, 2
                )
            return parsed
        except Exception:
            return {}

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


async def search(
    query: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, str]]:
    """
    Search Euronext for securities by name or ISIN.
    Returns list of dicts: {name, isin, ticker, market}
    """
    url = _SEARCH_URL.format(query=query)

    async def _fetch(c: httpx.AsyncClient) -> list[dict[str, str]]:
        try:
            resp = await c.get(url, headers=_HEADERS)
            resp.raise_for_status()
            return parse_euronext_search_html(resp.text)
        except Exception:
            return []

    if client is not None:
        return await _fetch(client)
    async with httpx.AsyncClient(timeout=_config.http_timeout) as c:
        return await _fetch(c)


async def get_live_quote_with_fallback(
    isin: str,
    mic: str,
    yahoo_ticker: str,
) -> dict[str, Any]:
    """
    Try Euronext first; fall back to Yahoo quote on failure or empty result.
    Adds a 'source' key: 'euronext' or 'yahoo'.
    """
    result = await get_live_quote(isin, mic)
    if result.get("price"):
        result["source"] = "euronext"
        return result

    # Fallback to Yahoo
    from lens.data.yahoo import get_quote as yahoo_get_quote

    yahoo_result = await yahoo_get_quote(yahoo_ticker)
    yahoo_result["source"] = "yahoo"
    return yahoo_result


if __name__ == "__main__":
    import asyncio
    import json

    async def demo() -> None:
        print("=== Euronext live quote: LVMH (FR0000121014-XPAR) ===")
        q = await get_live_quote("FR0000121014", "XPAR")
        print(json.dumps(q, indent=2))

        print("\n=== Euronext search: LVMH ===")
        results = await search("LVMH")
        for r in results[:5]:
            print(f"  {r.get('isin', ''):14} {r.get('ticker', ''):8} {r.get('name', '')}")

    asyncio.run(demo())
