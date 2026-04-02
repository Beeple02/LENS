"""HTML parsing utilities for Euronext responses."""

from __future__ import annotations

import re
from typing import Optional


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_number(raw: str) -> Optional[float]:
    """Parse European-formatted numbers like '1 234,56' or '1,234.56'."""
    text = raw.strip().replace("\xa0", "").replace(" ", "")
    if not text or text in ("-", "N/A", "n/a", "--"):
        return None
    # Detect European format: comma as decimal separator
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        # e.g. 1.234,56 → 1234.56
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_euronext_quote_html(html: str) -> dict[str, Optional[float | str]]:
    """
    Parse the HTML fragment returned by Euronext live quote endpoint.
    Returns a dict with keys: price, bid, ask, volume, open, high, low, prev_close, change, change_pct.
    """
    result: dict[str, Optional[float | str]] = {
        "price": None,
        "bid": None,
        "ask": None,
        "volume": None,
        "open": None,
        "high": None,
        "low": None,
        "prev_close": None,
        "change": None,
        "change_pct": None,
    }

    try:
        from lxml import etree

        parser = etree.HTMLParser()
        tree = etree.fromstring(html.encode(), parser)

        def xpath_text(expr: str) -> str:
            nodes = tree.xpath(expr)
            if nodes:
                return _clean("".join(nodes[0].itertext()) if hasattr(nodes[0], "itertext") else str(nodes[0]))
            return ""

        def find_by_label(label: str) -> Optional[float]:
            """Find a value near a label text in the HTML."""
            # Look for dt/dd pairs or th/td pairs
            for elem in tree.xpath(f"//*[contains(text(), '{label}')]"):
                sibling = elem.getnext()
                if sibling is not None:
                    txt = _clean("".join(sibling.itertext()))
                    val = _parse_number(txt)
                    if val is not None:
                        return val
            return None

        # Try to extract last price — commonly in a span with class containing "last" or "price"
        for cls_hint in ["last-price", "intraday_price", "cotation"]:
            nodes = tree.xpath(f"//*[contains(@class, '{cls_hint}')]")
            for node in nodes:
                txt = _clean("".join(node.itertext()))
                val = _parse_number(txt)
                if val is not None:
                    result["price"] = val
                    break
            if result["price"] is not None:
                break

        # Label-based extraction
        label_map = {
            "Dernier cours": "price",
            "Last": "price",
            "Ouverture": "open",
            "Open": "open",
            "Haut": "high",
            "High": "high",
            "Bas": "low",
            "Low": "low",
            "Clôture préc.": "prev_close",
            "Prev. Close": "prev_close",
            "Volume": "volume",
            "Bid": "bid",
            "Ask": "ask",
            "Offre": "ask",
            "Demande": "bid",
        }
        for label, field in label_map.items():
            if result[field] is None:
                val = find_by_label(label)
                if val is not None:
                    result[field] = val

    except Exception:
        # Fall back to regex-based parsing
        price_patterns = [
            r'"last[Pp]rice"\s*:\s*"?([\d\s,\.]+)"?',
            r'class="[^"]*price[^"]*"[^>]*>([\d\s,\.]+)<',
        ]
        for pat in price_patterns:
            m = re.search(pat, html)
            if m:
                val = _parse_number(m.group(1))
                if val is not None:
                    result["price"] = val
                    break

    return result


def parse_euronext_search_html(html: str) -> list[dict[str, str]]:
    """
    Parse the search results table from Euronext search endpoint.
    Returns list of dicts with keys: name, isin, ticker, market.
    """
    results: list[dict[str, str]] = []
    try:
        from lxml import etree

        parser = etree.HTMLParser()
        tree = etree.fromstring(html.encode(), parser)
        rows = tree.xpath("//table//tr")
        for row in rows[1:]:  # skip header
            cells = row.xpath(".//td")
            if len(cells) >= 4:
                name = _clean("".join(cells[0].itertext()))
                isin = _clean("".join(cells[1].itertext()))
                ticker = _clean("".join(cells[2].itertext()))
                market = _clean("".join(cells[3].itertext()))
                if isin and len(isin) == 12:
                    results.append({"name": name, "isin": isin, "ticker": ticker, "market": market})
    except Exception:
        # Regex fallback
        rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
        for row_html in rows_html:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
            cells_text = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(cells_text) >= 4 and len(cells_text[1]) == 12:
                results.append({
                    "name": cells_text[0],
                    "isin": cells_text[1],
                    "ticker": cells_text[2],
                    "market": cells_text[3],
                })

    return results
