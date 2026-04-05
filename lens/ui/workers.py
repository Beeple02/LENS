"""QThread workers for async data fetching — all data calls go through here.

Pattern: create a worker, connect .result / .error signals, call .start().
The worker runs asyncio in a fresh event loop on a background thread, then
emits the result back to the main thread via Qt signals.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import logging

from PyQt6.QtCore import QThread, pyqtSignal

_log = logging.getLogger("lens.workers")


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Quote worker
# ---------------------------------------------------------------------------

class FetchQuoteWorker(QThread):
    result = pyqtSignal(dict)
    error  = pyqtSignal(str)

    def __init__(self, ticker: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        try:
            from lens.data.yahoo import get_quote
            data = _run(get_quote(self.ticker))
            self.result.emit(data)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Euronext live quote worker (falls back to Yahoo)
# ---------------------------------------------------------------------------

class FetchLiveQuoteWorker(QThread):
    result = pyqtSignal(dict)
    error  = pyqtSignal(str)

    def __init__(self, ticker: str, isin: Optional[str] = None,
                 mic: str = "XPAR", parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker
        self.isin = isin
        self.mic = mic

    def run(self) -> None:
        try:
            if self.isin:
                from lens.data.euronext import get_live_quote_with_fallback
                data = _run(get_live_quote_with_fallback(self.isin, self.mic, self.ticker))
            else:
                from lens.data.yahoo import get_quote
                data = _run(get_quote(self.ticker))
                data["source"] = "yahoo"
            self.result.emit(data)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Chart worker
# ---------------------------------------------------------------------------

class FetchChartWorker(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, ticker: str, interval: str = "1d",
                 range_: str = "1y", parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker
        self.interval = interval
        self.range_ = range_

    def run(self) -> None:
        try:
            from lens.data.yahoo import get_chart
            data = _run(get_chart(self.ticker, self.interval, self.range_))
            _log.debug("Chart loaded: %s  %s bars", self.ticker, len(data))
            self.result.emit(data)
        except Exception as e:
            _log.error("Chart fetch failed [%s]: %s", self.ticker, e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Fundamentals worker
# ---------------------------------------------------------------------------

class FetchFundamentalsWorker(QThread):
    result = pyqtSignal(dict)
    error  = pyqtSignal(str)

    def __init__(self, ticker: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        try:
            from lens.data.yahoo import get_fundamentals
            from lens.db.store import fundamentals_stale, upsert_fundamentals, upsert_security
            from lens.config import Config
            cfg = Config()

            if fundamentals_stale(self.ticker, cfg.cache_fundamentals_hours):
                data = _run(get_fundamentals(self.ticker))
                if data:
                    # Ensure security row exists before writing fundamentals (FK constraint)
                    upsert_security(ticker=self.ticker, name=self.ticker)
                    upsert_fundamentals(self.ticker, data)
                self.result.emit(data)
            else:
                from lens.db.store import get_latest_fundamentals
                row = get_latest_fundamentals(self.ticker)
                self.result.emit(dict(row) if row else {})
        except Exception as e:
            _log.error("Fundamentals fetch failed [%s]: %s", self.ticker, e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Watchlist worker — fetches all tickers in a watchlist with quotes
# ---------------------------------------------------------------------------

class FetchWatchlistWorker(QThread):
    result = pyqtSignal(list)   # list of dicts
    error  = pyqtSignal(str)

    def __init__(self, watchlist_name: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.watchlist_name = watchlist_name

    def run(self) -> None:
        try:
            import httpx
            from lens.data.yahoo import get_quote
            from lens.db.store import get_watchlist_tickers
            from lens.config import Config
            cfg = Config()

            rows = get_watchlist_tickers(self.watchlist_name)
            results = []

            async def fetch_all() -> list[dict]:
                async with httpx.AsyncClient(timeout=cfg.http_timeout) as client:
                    items = []
                    for row in rows:
                        ticker = row["ticker"]
                        name   = row["name"] or ticker
                        isin   = row["isin"]  if "isin"  in row.keys() else None
                        mic    = row["mic"]   if "mic"   in row.keys() and row["mic"] else "XPAR"
                        try:
                            q = await get_quote(ticker, client=client)
                            items.append({"ticker": ticker, "name": name,
                                          "isin": isin, "mic": mic, **q})
                        except Exception as qe:
                            _log.warning("Quote fetch failed for %s: %s", ticker, qe)
                            items.append({"ticker": ticker, "name": name,
                                          "isin": isin, "mic": mic,
                                          "price": None, "change": None,
                                          "change_pct": None, "volume": None,
                                          "high": None, "low": None})
                    return items

            results = _run(fetch_all())
            self.result.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Search worker
# ---------------------------------------------------------------------------

class SearchWorker(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, query: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.query = query

    def run(self) -> None:
        try:
            from lens.data.yahoo import search
            data = _run(search(self.query))
            self.result.emit(data)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Fetch + store worker (force refresh prices + fundamentals)
# ---------------------------------------------------------------------------

class FetchAndStoreWorker(QThread):
    progress = pyqtSignal(str)
    done     = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, ticker: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        try:
            import httpx
            from lens.data.yahoo import get_chart, get_fundamentals, get_quote
            from lens.db.store import upsert_fundamentals, upsert_price_history, upsert_security
            from lens.config import Config
            cfg = Config()

            async def do_all() -> None:
                async with httpx.AsyncClient(timeout=cfg.http_timeout) as client:
                    self.progress.emit(f"Fetching quote for {self.ticker}…")
                    q = await get_quote(self.ticker, client=client)
                    upsert_security(
                        ticker=self.ticker,
                        name=q.get("name", self.ticker),
                        currency=q.get("currency", "EUR"),
                    )

                    self.progress.emit("Fetching price history…")
                    chart = await get_chart(self.ticker, "1d", "2y", client=client)
                    upsert_price_history(self.ticker, chart)

                    self.progress.emit("Fetching fundamentals…")
                    fund = await get_fundamentals(self.ticker, client=client)
                    if fund:
                        upsert_fundamentals(self.ticker, fund)

            _run(do_all())
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Portfolio worker — builds portfolio summary with live prices
# ---------------------------------------------------------------------------

class FetchPortfolioWorker(QThread):
    result = pyqtSignal(object)  # PortfolioSummary
    error  = pyqtSignal(str)

    def __init__(self, account_name: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.account_name = account_name

    def run(self) -> None:
        try:
            import httpx
            from lens.data.yahoo import get_quote
            from lens.portfolio.tracker import build_portfolio
            from lens.config import Config
            cfg = Config()

            summary = build_portfolio(self.account_name)
            prices: dict[str, float] = {}

            if summary.positions:
                async def fetch_prices() -> None:
                    async with httpx.AsyncClient(timeout=cfg.http_timeout) as client:
                        for ticker in summary.positions:
                            try:
                                q = await get_quote(ticker, client=client)
                                if q.get("price"):
                                    prices[ticker] = float(q["price"])
                            except Exception:
                                pass

                _run(fetch_prices())

            summary = build_portfolio(self.account_name, prices=prices)
            self.result.emit(summary)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Screener worker
# ---------------------------------------------------------------------------

class RunScreenerWorker(QThread):
    result = pyqtSignal(object)  # DataFrame
    error  = pyqtSignal(str)

    def __init__(self, expression: str, universe: str = "all",
                 sort_by: Optional[str] = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.expression = expression
        self.universe = universe
        self.sort_by = sort_by

    def run(self) -> None:
        try:
            from lens.screener.engine import run_screen
            df = run_screen(self.expression, universe=self.universe, sort_by=self.sort_by)
            self.result.emit(df)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Benchmark comparison worker
# ---------------------------------------------------------------------------

class FetchBenchmarkWorker(QThread):
    result = pyqtSignal(dict)
    error  = pyqtSignal(str)

    def __init__(self, account_name: str, benchmark_ticker: str = "^FCHI",
                 parent: Any = None) -> None:
        super().__init__(parent)
        self.account_name = account_name
        self.benchmark_ticker = benchmark_ticker

    def run(self) -> None:
        try:
            import httpx
            from lens.data.yahoo import get_chart
            from lens.db.store import get_prices, get_transactions
            from lens.portfolio.analytics import benchmark_comparison
            from lens.config import Config
            cfg = Config()

            txs = get_transactions(self.account_name)
            if not txs:
                self.result.emit({"portfolio_twr": None, "benchmark_return": None, "alpha": None})
                return

            # Get price series for all portfolio tickers
            tickers = list({t["ticker"] for t in txs})
            price_series = {}
            for ticker in tickers:
                df = get_prices(ticker)
                if not df.empty:
                    price_series[ticker] = df

            # Get benchmark prices
            bm_raw = _run(get_chart(self.benchmark_ticker, "1d", "5y"))
            import pandas as pd
            bm_df = pd.DataFrame(bm_raw) if bm_raw else pd.DataFrame()

            result = benchmark_comparison(list(txs), price_series, bm_df)
            self.result.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Portfolio NAV worker — daily portfolio value over time
# ---------------------------------------------------------------------------

class PortfolioNAVWorker(QThread):
    """Builds a time-series of portfolio NAV from DB transactions + price history."""
    result = pyqtSignal(list)   # list of (date_str, float)
    error  = pyqtSignal(str)

    def __init__(self, account_name: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.account_name = account_name

    def run(self) -> None:
        try:
            from datetime import date as _date
            from lens.db.store import get_transactions, get_prices

            txs = get_transactions(self.account_name)
            if not txs:
                self.result.emit([])
                return

            txs_sorted = sorted(txs, key=lambda t: t["date"])
            tickers = list({t["ticker"] for t in txs_sorted})

            # Load price series for each ticker: {ticker: {date_str: close}}
            price_map: dict[str, dict[str, float]] = {}
            for ticker in tickers:
                df = get_prices(ticker)
                if not df.empty and "date" in df.columns and "close" in df.columns:
                    price_map[ticker] = dict(zip(df["date"], df["close"].astype(float)))

            if not price_map:
                self.result.emit([])
                return

            # All available trading dates across all tickers, from first transaction
            start = txs_sorted[0]["date"][:10]
            all_dates = sorted({d for series in price_map.values() for d in series if d >= start})
            if not all_dates:
                self.result.emit([])
                return

            # Walk forward: update holdings on each transaction date, compute NAV
            holdings: dict[str, float] = {}
            tx_idx = 0
            nav_series: list[tuple[str, float]] = []

            for d in all_dates:
                # Apply all transactions on or before this date
                while tx_idx < len(txs_sorted) and txs_sorted[tx_idx]["date"][:10] <= d:
                    tx = txs_sorted[tx_idx]
                    ticker = tx["ticker"]
                    qty = float(tx["quantity"])
                    tx_type = str(tx["type"]).upper()
                    if tx_type == "BUY":
                        holdings[ticker] = holdings.get(ticker, 0.0) + qty
                    elif tx_type == "SELL":
                        holdings[ticker] = max(0.0, holdings.get(ticker, 0.0) - qty)
                    elif tx_type == "SPLIT":
                        holdings[ticker] = holdings.get(ticker, 0.0) * qty
                    tx_idx += 1

                # Compute NAV: sum shares * latest available price
                nav = 0.0
                for ticker, shares in holdings.items():
                    if shares > 0 and ticker in price_map:
                        series = price_map[ticker]
                        # Most recent price on or before this date
                        candidates = [v for k, v in series.items() if k <= d]
                        if candidates:
                            nav += shares * candidates[-1]

                if nav > 0:
                    nav_series.append((d, nav))

            self.result.emit(nav_series)
        except Exception as e:
            _log.error("PortfolioNAVWorker failed: %s", e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Markets movers worker — top/bottom movers from EU universe
# ---------------------------------------------------------------------------

_EU_UNIVERSE = [
    # CAC 40
    "MC.PA","TTE.PA","SAN.PA","OR.PA","AI.PA","BN.PA","KER.PA","BNP.PA",
    "AIR.PA","SG.PA","DG.PA","RMS.PA","SAF.PA","GLE.PA","ENGI.PA","DSY.PA",
    "HO.PA","STM.PA","RI.PA","CS.PA","ATO.PA","LR.PA","ERF.PA","CA.PA",
    "VIV.PA","MT.PA","CAP.PA","EN.PA","EL.PA","WLN.PA","RNO.PA",
    # DAX
    "SAP.DE","SIE.DE","ALV.DE","DTE.DE","MUV2.DE","BAYN.DE","BAS.DE",
    "BMW.DE","MBG.DE","DBK.DE","IFX.DE","RWE.DE","VOW3.DE","ADS.DE",
    "DHL.DE","EOAN.DE","CON.DE","HEN3.DE","FRE.DE","MRK.DE","MTX.DE",
    # FTSE 100
    "AZN.L","SHEL.L","HSBA.L","ULVR.L","BP.L","GLEN.L","RIO.L",
    "DGE.L","REL.L","BATS.L","NWG.L","LSEG.L","PRU.L","EXPN.L",
    # AEX
    "ASML.AS","HEIA.AS","ING.AS","PHIA.AS","NN.AS","WKL.AS",
    # SMI
    "NESN.SW","ROG.SW","NOVN.SW","ABBN.SW","ZURN.SW","UBSG.SW",
    # IBEX
    "BBVA.MC","SAN.MC","ITX.MC","IBE.MC","REP.MC","TEF.MC",
]


class FetchMarketsWorker(QThread):
    """Fetches quotes for the EU universe, emits list sorted by change_pct desc."""
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def run(self) -> None:
        try:
            import httpx
            from lens.data.yahoo import get_quote
            from lens.config import Config
            cfg = Config()

            async def _fetch_all() -> list[dict]:
                out = []
                async with httpx.AsyncClient(timeout=cfg.http_timeout) as client:
                    for ticker in _EU_UNIVERSE:
                        try:
                            q = await get_quote(ticker, client=client)
                            if q.get("price"):
                                out.append(q)
                        except Exception:
                            pass
                return out

            data = _run(_fetch_all())
            data.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
            _log.debug("Markets loaded: %d quotes", len(data))
            self.result.emit(data)
        except Exception as e:
            _log.error("FetchMarketsWorker failed: %s", e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Deep-dive worker — fires each signal independently as data arrives
# ---------------------------------------------------------------------------

class FetchDeepDiveWorker(QThread):
    """Fetch all data for DeepDiveScreen concurrently; emit each signal as ready."""

    header_ready     = pyqtSignal(dict)   # from get_quote()
    financials_ready = pyqtSignal(dict)   # {"annual": {...}, "quarterly": {...}}
    earnings_ready   = pyqtSignal(dict)   # raw quoteSummary result dict
    analysts_ready   = pyqtSignal(dict)   # raw quoteSummary result dict
    dividends_ready  = pyqtSignal(dict)   # quoteSummary + chart_events
    ownership_ready  = pyqtSignal(dict)   # raw quoteSummary result dict
    peers_ready      = pyqtSignal(dict)   # {target, tickers, data, sector, industry}
    error            = pyqtSignal(str, str)  # (tab_name, message)

    def __init__(self, ticker: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        async def _main() -> None:
            import httpx
            from lens.data.yahoo import (
                get_quote,
                _ensure_crumb,
                _fetch_financials_statements,
                _fetch_summary_modules,
                _fetch_peer_data,
                _BASE_CHART,
                _get,
            )

            async with httpx.AsyncClient(timeout=30) as c:
                _log.info("DeepDive fetch started — %s", self.ticker)

                # Header first — fires before any heavy fetch
                try:
                    q = await get_quote(self.ticker, client=c)
                    self.header_ready.emit(q)
                    _log.debug("DeepDive header ready — %s  price=%s", self.ticker, q.get("price"))
                except Exception as e:
                    _log.error("DeepDive header failed — %s: %s", self.ticker, e)
                    self.error.emit("header", str(e))

                # Prime crumb before parallel authenticated requests
                try:
                    await _ensure_crumb(c)
                except Exception:
                    pass

                # ── Concurrent fetches — each emits its own signal ─────────

                async def _financials() -> None:
                    try:
                        result = await _fetch_financials_statements(self.ticker, c)
                        self.financials_ready.emit(result)
                        ann = result.get("annual", {})
                        qtr = result.get("quarterly", {})
                        _log.debug("DeepDive financials ready — %s  annual=%d fields, quarterly=%d fields",
                                   self.ticker, len(ann), len(qtr))
                    except Exception as e:
                        _log.error("DeepDive financials failed — %s: %s", self.ticker, e)
                        self.error.emit("financials", str(e))

                async def _earnings() -> None:
                    try:
                        d = await _fetch_summary_modules(
                            self.ticker,
                            "earnings,earningsHistory,earningsTrend,calendarEvents",
                            c,
                        )
                        self.earnings_ready.emit(d)
                        _log.debug("DeepDive earnings ready — %s", self.ticker)
                    except Exception as e:
                        _log.error("DeepDive earnings failed — %s: %s", self.ticker, e)
                        self.error.emit("earnings", str(e))

                async def _analysts() -> None:
                    try:
                        d = await _fetch_summary_modules(
                            self.ticker,
                            "recommendationTrend,upgradeDowngradeHistory,financialData,defaultKeyStatistics",
                            c,
                        )
                        # 3-month weekly price history for consensus trend overlay
                        try:
                            ph = await _get(
                                c,
                                _BASE_CHART.format(ticker=self.ticker),
                                {"range": "3mo", "interval": "1wk"},
                            )
                            closes = (
                                ph.get("chart", {})
                                .get("result", [{}])[0]
                                .get("indicators", {})
                                .get("quote", [{}])[0]
                                .get("close", [])
                            )
                            d["_price_3mo"] = [x for x in closes if x is not None]
                        except Exception:
                            d["_price_3mo"] = []
                        self.analysts_ready.emit(d)
                        _log.debug("DeepDive analysts ready — %s", self.ticker)
                    except Exception as e:
                        _log.error("DeepDive analysts failed — %s: %s", self.ticker, e)
                        self.error.emit("analysts", str(e))

                async def _dividends() -> None:
                    try:
                        url = _BASE_CHART.format(ticker=self.ticker)
                        chart_data = await _get(
                            c, url,
                            {"events": "dividends,splits", "range": "10y", "interval": "1d"},
                        )
                        div_events = (
                            chart_data.get("chart", {})
                            .get("result", [{}])[0]
                            .get("events", {})
                            .get("dividends", {})
                        )
                        qs = await _fetch_summary_modules(
                            self.ticker, "summaryDetail,defaultKeyStatistics", c
                        )
                        self.dividends_ready.emit({**qs, "chart_events": div_events})
                        _log.debug("DeepDive dividends ready — %s  events=%d", self.ticker, len(div_events))
                    except Exception as e:
                        _log.error("DeepDive dividends failed — %s: %s", self.ticker, e)
                        self.error.emit("dividends", str(e))

                async def _ownership() -> None:
                    try:
                        d = await _fetch_summary_modules(
                            self.ticker,
                            "insiderTransactions,insiderHolders,institutionOwnership,"
                            "majorHoldersBreakdown,fundOwnership,netSharePurchaseActivity",
                            c,
                        )
                        self.ownership_ready.emit(d)
                        _log.debug("DeepDive ownership ready — %s", self.ticker)
                    except Exception as e:
                        _log.error("DeepDive ownership failed — %s: %s", self.ticker, e)
                        self.error.emit("ownership", str(e))

                async def _peers() -> None:
                    try:
                        d = await _fetch_peer_data(self.ticker, c)
                        self.peers_ready.emit(d)
                        _log.debug("DeepDive peers ready — %s  peers=%s",
                                   self.ticker, d.get("tickers", []))
                    except Exception as e:
                        _log.error("DeepDive peers failed — %s: %s", self.ticker, e)
                        self.error.emit("peers", str(e))

                await asyncio.gather(
                    _financials(), _earnings(), _analysts(),
                    _dividends(), _ownership(), _peers(),
                )
                _log.info("DeepDive fetch complete — %s", self.ticker)

        try:
            _run(_main())
        except Exception as e:
            _log.error("FetchDeepDiveWorker crashed — %s: %s", self.ticker, e)
            self.error.emit("general", str(e))
