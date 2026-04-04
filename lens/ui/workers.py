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
            from lens.db.store import fundamentals_stale, upsert_fundamentals
            from lens.config import Config
            cfg = Config()

            if fundamentals_stale(self.ticker, cfg.cache_fundamentals_hours):
                data = _run(get_fundamentals(self.ticker))
                if data:
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
