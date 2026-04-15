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
    esg_ready        = pyqtSignal(dict)   # esgScores or empty dict
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

                async def _esg() -> None:
                    try:
                        d = await _fetch_summary_modules(self.ticker, "esgScores", c)
                        esg = d.get("esgScores") or {}
                        self.esg_ready.emit(esg if esg else {})
                        _log.debug("DeepDive ESG ready — %s", self.ticker)
                    except Exception as e:
                        # 404 is normal for EU tickers without Sustainalytics coverage
                        _log.debug("DeepDive ESG unavailable — %s: %s", self.ticker, e)
                        self.esg_ready.emit({})

                await asyncio.gather(
                    _financials(), _earnings(), _analysts(),
                    _dividends(), _ownership(), _peers(), _esg(),
                )
                _log.info("DeepDive fetch complete — %s", self.ticker)

        try:
            _run(_main())
        except Exception as e:
            _log.error("FetchDeepDiveWorker crashed — %s: %s", self.ticker, e)
            self.error.emit("general", str(e))


# ---------------------------------------------------------------------------
# Macro dashboard worker — fires each group independently as data arrives
# ---------------------------------------------------------------------------

class FetchMacroWorker(QThread):
    """Fetch macro data concurrently; emit each category signal as ready."""

    indices_ready     = pyqtSignal(dict)   # {ticker: quote_dict}
    fx_ready          = pyqtSignal(dict)
    commodities_ready = pyqtSignal(dict)
    ecb_rate_ready    = pyqtSignal(float)
    charts_ready      = pyqtSignal(dict)   # {ticker: ohlcv_list}
    error             = pyqtSignal(str)

    # Class-level ECB cache: (rate, fetch_timestamp)
    _ecb_cache: Optional[tuple[float, float]] = None

    _INDICES    = ["^FCHI", "^GDAXI", "^FTSE", "^AEX", "^IBEX", "^SSMI", "^STOXX50E"]
    _FX         = ["EURUSD=X", "EURGBP=X", "EURCHF=X", "EURJPY=X", "EURCNH=X"]
    _COMMS      = ["BZ=F", "TTF=F", "GC=F", "SI=F", "HG=F"]
    _CHART_TKS  = ["^FCHI", "^GDAXI", "^STOXX50E"]

    def run(self) -> None:
        async def _main() -> None:
            import time as _time
            import httpx
            from lens.data.yahoo import get_quote, get_chart

            async with httpx.AsyncClient(timeout=15) as c:

                async def _ecb() -> None:
                    cache = FetchMacroWorker._ecb_cache
                    if cache and (_time.time() - cache[1]) < 3600:
                        self.ecb_rate_ready.emit(cache[0])
                        return
                    try:
                        url = (
                            "https://data-api.ecb.europa.eu/service/data/"
                            "FM/B.U2.EUR.4F.KR.MRR_FR.LEV?format=jsondata"
                        )
                        resp = await c.get(url, headers={"Accept": "application/json"})
                        resp.raise_for_status()
                        series = resp.json()["dataSets"][0]["series"]
                        # Key format can vary (e.g. "0:0:0:0:0:0"); take first key dynamically
                        series_key = next(iter(series))
                        obs = series[series_key]["observations"]
                        last_key = str(max(int(k) for k in obs.keys()))
                        rate = float(obs[last_key][0])
                        FetchMacroWorker._ecb_cache = (rate, _time.time())
                        self.ecb_rate_ready.emit(rate)
                    except Exception as exc:
                        self.error.emit(f"ecb: {exc}")

                async def _indices() -> None:
                    try:
                        results = await asyncio.gather(
                            *[get_quote(t, client=c) for t in self._INDICES],
                            return_exceptions=True,
                        )
                        out = {t: r for t, r in zip(self._INDICES, results)
                               if not isinstance(r, Exception)}
                        self.indices_ready.emit(out)
                    except Exception as exc:
                        self.error.emit(f"indices: {exc}")

                async def _fx() -> None:
                    try:
                        results = await asyncio.gather(
                            *[get_quote(t, client=c) for t in self._FX],
                            return_exceptions=True,
                        )
                        out = {t: r for t, r in zip(self._FX, results)
                               if not isinstance(r, Exception)}
                        self.fx_ready.emit(out)
                    except Exception as exc:
                        self.error.emit(f"fx: {exc}")

                async def _commodities() -> None:
                    try:
                        results = await asyncio.gather(
                            *[get_quote(t, client=c) for t in self._COMMS],
                            return_exceptions=True,
                        )
                        out: dict = {}
                        for t, r in zip(self._COMMS, results):
                            if isinstance(r, Exception):
                                if t == "TTF=F":
                                    try:
                                        out[t] = await get_quote("NG=F", client=c)
                                    except Exception:
                                        pass
                            elif not (r.get("price") or 0) and t == "TTF=F":
                                try:
                                    out[t] = await get_quote("NG=F", client=c)
                                except Exception:
                                    out[t] = r
                            else:
                                out[t] = r
                        self.commodities_ready.emit(out)
                    except Exception as exc:
                        self.error.emit(f"commodities: {exc}")

                async def _charts() -> None:
                    try:
                        results = await asyncio.gather(
                            *[get_chart(t, interval="1d", range_="1y", client=c)
                              for t in self._CHART_TKS],
                            return_exceptions=True,
                        )
                        out = {t: r for t, r in zip(self._CHART_TKS, results)
                               if not isinstance(r, Exception)}
                        self.charts_ready.emit(out)
                    except Exception as exc:
                        self.error.emit(f"charts: {exc}")

                await asyncio.gather(_ecb(), _indices(), _fx(), _commodities(), _charts())

        try:
            _run(_main())
        except Exception as e:
            _log.error("FetchMacroWorker crashed: %s", e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Analytics worker — portfolio risk/return metrics from NAV time-series
# ---------------------------------------------------------------------------

class FetchAnalyticsWorker(QThread):
    """Compute portfolio analytics from transaction history + price DB."""

    analytics_ready = pyqtSignal(dict)
    error           = pyqtSignal(str)

    def __init__(self, account_name: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.account_name = account_name

    def run(self) -> None:
        try:
            import numpy as np
            from lens.db.store import get_transactions, get_prices
            from lens.data.yahoo import get_chart

            txs = get_transactions(self.account_name)
            if not txs:
                self.analytics_ready.emit({})
                return

            txs_sorted = sorted(txs, key=lambda t: t["date"])
            tickers = list({t["ticker"] for t in txs_sorted})

            price_map: dict[str, dict[str, float]] = {}
            for ticker in tickers:
                df = get_prices(ticker)
                if not df.empty and "date" in df.columns and "close" in df.columns:
                    price_map[ticker] = dict(zip(df["date"], df["close"].astype(float)))

            if not price_map:
                self.analytics_ready.emit({})
                return

            start = txs_sorted[0]["date"][:10]
            all_dates = sorted({d for s in price_map.values() for d in s if d >= start})
            if not all_dates:
                self.analytics_ready.emit({})
                return

            holdings: dict[str, float] = {}
            tx_idx = 0
            nav_series: list[tuple[str, float]] = []

            for d in all_dates:
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

                nav = 0.0
                for ticker, shares in holdings.items():
                    if shares > 0 and ticker in price_map:
                        candidates = [v for k, v in price_map[ticker].items() if k <= d]
                        if candidates:
                            nav += shares * candidates[-1]
                if nav > 0:
                    nav_series.append((d, nav))

            if len(nav_series) < 2:
                self.analytics_ready.emit({})
                return

            nav_dates = [x[0] for x in nav_series]
            nav_vals  = np.array([x[1] for x in nav_series], dtype=float)

            # Drawdown series (always computed, full history)
            peak = np.maximum.accumulate(nav_vals)
            dd_arr = (nav_vals - peak) / peak
            drawdown_series = list(zip(nav_dates, dd_arr.tolist()))
            max_drawdown = float(np.min(dd_arr))

            # Daily portfolio returns
            nav_ret_all = np.diff(nav_vals) / nav_vals[:-1]
            ret_dates   = nav_dates[1:]

            # Monthly compound returns for best/worst
            monthly_rets: dict[str, list[float]] = {}
            for i, r in enumerate(nav_ret_all):
                ym = ret_dates[i][:7]
                monthly_rets.setdefault(ym, []).append(float(r))

            monthly_compound: dict[str, float] = {}
            for ym, rets in monthly_rets.items():
                c = 1.0
                for r in rets:
                    c *= 1.0 + r
                monthly_compound[ym] = c - 1.0

            best_month = worst_month = None
            if monthly_compound:
                best_ym  = max(monthly_compound, key=lambda k: monthly_compound[k])
                worst_ym = min(monthly_compound, key=lambda k: monthly_compound[k])
                _mnames  = ["Jan","Feb","Mar","Apr","May","Jun",
                            "Jul","Aug","Sep","Oct","Nov","Dec"]

                def _mfmt(ym: str) -> str:
                    y, m = ym.split("-")
                    return f"{_mnames[int(m)-1]} {y}"

                bv = monthly_compound[best_ym]
                wv = monthly_compound[worst_ym]
                best_month  = f"+{bv*100:.1f}% ({_mfmt(best_ym)})"
                worst_month = f"{wv*100:.1f}% ({_mfmt(worst_ym)})"

            result: dict = {
                "max_drawdown":    max_drawdown,
                "drawdown_series": drawdown_series,
                "best_month":      best_month,
                "worst_month":     worst_month,
            }

            # Risk metrics: last 252 days, minimum 60 days
            n = min(252, len(nav_ret_all))
            if n < 60:
                result.update({"beta": None, "sharpe": None, "sortino": None,
                               "volatility": None, "correlation": None,
                               "up_capture": None, "down_capture": None})
            else:
                ret_n = nav_ret_all[-n:]
                rf    = 0.03 / 252
                mean_r = float(np.mean(ret_n))
                std_r  = float(np.std(ret_n, ddof=1))
                result["volatility"] = float(std_r * np.sqrt(252))
                result["sharpe"] = float((mean_r - rf) / std_r * np.sqrt(252)) if std_r > 0 else None
                down_only = ret_n[ret_n < 0]
                down_std  = float(np.std(down_only, ddof=1)) if len(down_only) > 1 else 0.0
                result["sortino"] = float((mean_r - rf) / down_std * np.sqrt(252)) if down_std > 0 else None

                # Benchmark-aligned metrics: beta, correlation, up/down capture
                bm_raw = _run(get_chart("^FCHI", "1d", "5y"))
                bm_map: dict[str, float] = {}
                if bm_raw:
                    for bar in bm_raw:
                        if bar.get("close") and bar.get("date"):
                            bm_map[bar["date"]] = float(bar["close"])

                aligned_p: list[float] = []
                aligned_b: list[float] = []
                for i in range(1, len(nav_series)):
                    d_prev, nav_prev = nav_series[i - 1]
                    d_curr, nav_curr = nav_series[i]
                    bm_prev = bm_map.get(d_prev)
                    bm_curr = bm_map.get(d_curr)
                    if bm_prev and bm_curr and bm_prev > 0 and nav_prev > 0:
                        aligned_p.append((nav_curr - nav_prev) / nav_prev)
                        aligned_b.append((bm_curr - bm_prev) / bm_prev)

                if len(aligned_p) >= 60:
                    p = np.array(aligned_p[-252:])
                    b = np.array(aligned_b[-252:])
                    var_b  = float(np.var(b, ddof=1))
                    cov_pb = float(np.cov(p, b)[0, 1])
                    result["beta"]        = float(cov_pb / var_b) if var_b > 0 else None
                    result["correlation"] = float(np.corrcoef(p, b)[0, 1]) if len(p) > 1 else None

                    # Monthly up/down capture
                    mp: dict[str, list[float]] = {}
                    mb: dict[str, list[float]] = {}
                    for i, rp in enumerate(aligned_p):
                        d = nav_series[i + 1][0] if i + 1 < len(nav_series) else ""
                        ym = d[:7]
                        if ym:
                            mp.setdefault(ym, []).append(rp)
                            mb.setdefault(ym, []).append(aligned_b[i])

                    def _cmpd(rets: list[float]) -> float:
                        c = 1.0
                        for r in rets:
                            c *= 1.0 + r
                        return c - 1.0

                    port_m = [_cmpd(mp[ym]) for ym in sorted(mp)]
                    bm_m   = [_cmpd(mb[ym]) for ym in sorted(mb)]

                    if port_m:
                        up_p = [port_m[i] for i in range(len(bm_m)) if bm_m[i] >= 0]
                        up_b = [bm_m[i]   for i in range(len(bm_m)) if bm_m[i] >= 0]
                        dn_p = [port_m[i] for i in range(len(bm_m)) if bm_m[i] < 0]
                        dn_b = [bm_m[i]   for i in range(len(bm_m)) if bm_m[i] < 0]
                        avg_ub = float(np.mean(up_b)) if up_b else 0.0
                        avg_db = float(np.mean(dn_b)) if dn_b else 0.0
                        result["up_capture"]   = (float(np.mean(up_p)) / avg_ub * 100) if (up_p and avg_ub != 0) else None
                        result["down_capture"] = (float(np.mean(dn_p)) / avg_db * 100) if (dn_p and avg_db != 0) else None
                    else:
                        result["up_capture"] = result["down_capture"] = None
                else:
                    result.update({"beta": None, "correlation": None,
                                   "up_capture": None, "down_capture": None})

            self.analytics_ready.emit(result)
        except Exception as e:
            _log.error("FetchAnalyticsWorker failed: %s", e)
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Ticker events worker — earnings dates for chart overlay
# ---------------------------------------------------------------------------

class FetchTickerEventsWorker(QThread):
    """Fetch earnings dates for a single ticker (used for chart overlay)."""

    events_ready = pyqtSignal(dict)   # {earnings_past, earnings_next, ecb_dates}
    error        = pyqtSignal(str)

    def __init__(self, ticker: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker

    def run(self) -> None:
        async def _main() -> None:
            import httpx
            from lens.data.yahoo import _fetch_summary_modules, _ensure_crumb
            async with httpx.AsyncClient(timeout=15) as c:
                await _ensure_crumb(c)
                d = await _fetch_summary_modules(self.ticker, "calendarEvents", c)
                cal = d.get("calendarEvents", {}) or {}
                dates_raw = cal.get("earnings", {}).get("earningsDate", [])
                from datetime import datetime, timezone as _tz, date as _date
                today = datetime.now(_tz.utc).date()
                past: list[str] = []
                nxt:  Optional[str] = None
                for ts_obj in dates_raw:
                    from lens.data.yahoo import _safe_float
                    ts = _safe_float(ts_obj)
                    if ts is None:
                        continue
                    try:
                        d_val = datetime.fromtimestamp(ts, tz=_tz.utc).date()
                        ds = d_val.strftime("%Y-%m-%d")
                        if d_val <= today:
                            past.append(ds)
                        elif nxt is None:
                            nxt = ds
                    except Exception:
                        pass
                self.events_ready.emit({
                    "earnings_past": past,
                    "earnings_next": nxt,
                })

        try:
            _run(_main())
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Calendar worker — full economic calendar data for EconomicCalendarScreen
# ---------------------------------------------------------------------------

_ECB_MEETING_DATES = [
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-29", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]


class FetchCalendarWorker(QThread):
    """Fetch earnings / ECB / dividend events for the calendar screen."""

    calendar_data_ready = pyqtSignal(dict)
    error               = pyqtSignal(str)

    def run(self) -> None:
        async def _main() -> None:
            import httpx
            from datetime import datetime, timezone as _tz, timedelta
            from lens.data.yahoo import _fetch_summary_modules, _ensure_crumb, _safe_float, get_chart
            from lens.db.store import list_watchlists, get_watchlist_tickers
            from lens.config import Config
            cfg = Config()

            # Collect tickers from all watchlists
            wl_tickers: list[str] = []
            try:
                for wl in list_watchlists():
                    for row in get_watchlist_tickers(wl["name"]):
                        if row["ticker"] not in wl_tickers:
                            wl_tickers.append(row["ticker"])
            except Exception:
                pass

            # Fallback to sample EU universe if watchlists empty
            if not wl_tickers:
                wl_tickers = _EU_UNIVERSE[:30]

            today = datetime.now(_tz.utc).date()
            horizon = today + timedelta(days=60)

            earnings_events: list[dict] = []
            ex_div_events:   list[dict] = []

            async with httpx.AsyncClient(timeout=15) as c:
                await _ensure_crumb(c)

                # Process in batches of 5 to avoid rate limiting
                semaphore = asyncio.Semaphore(5)

                async def _fetch_ticker(ticker: str) -> None:
                    async with semaphore:
                        try:
                            d = await _fetch_summary_modules(ticker, "calendarEvents", c)
                            cal = (d.get("calendarEvents") or {})
                            for ts_obj in (cal.get("earnings", {}) or {}).get("earningsDate", []):
                                ts = _safe_float(ts_obj)
                                if ts is None:
                                    continue
                                try:
                                    ev_date = datetime.fromtimestamp(ts, tz=_tz.utc).date()
                                    if today <= ev_date <= horizon:
                                        earnings_events.append({
                                            "ticker": ticker,
                                            "name": ticker,
                                            "date": ev_date.strftime("%Y-%m-%d"),
                                        })
                                except Exception:
                                    pass
                        except Exception:
                            pass

                async def _fetch_divs(ticker: str) -> None:
                    async with semaphore:
                        try:
                            bars = await get_chart(ticker, "1d", "3mo", client=c)
                            for bar in bars:
                                if bar.get("date") and bar["date"] >= str(today):
                                    pass  # dividend events are in chart events, not bars
                        except Exception:
                            pass

                await asyncio.gather(*[_fetch_ticker(t) for t in wl_tickers])

            self.calendar_data_ready.emit({
                "earnings":     earnings_events,
                "ecb_meetings": _ECB_MEETING_DATES,
                "ex_dividends": ex_div_events,
            })

        try:
            _run(_main())
        except Exception as e:
            _log.error("FetchCalendarWorker crashed: %s", e)


# ---------------------------------------------------------------------------
# News worker
# ---------------------------------------------------------------------------

class FetchNewsWorker(QThread):
    result = pyqtSignal(list)   # list of dicts: {title, publisher, link, published}
    error  = pyqtSignal(str)

    def __init__(self, ticker: str = "", parent: Any = None) -> None:
        super().__init__(parent)
        self.ticker = ticker   # empty string = market-wide news

    def run(self) -> None:
        try:
            data = _run(self._fetch())
            self.result.emit(data)
        except Exception as e:
            _log.error("News fetch failed [%s]: %s", self.ticker, e)
            self.error.emit(str(e))

    async def _fetch(self) -> list:
        import httpx
        from datetime import datetime as _dt
        # Use search API — /v2/finance/news is dead (500s)
        query = self.ticker if self.ticker else "europe stocks markets"
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {
            "q":                query,
            "newsCount":        "30",
            "quotesCount":      "0",
            "enableFuzzyQuery": "false",
        }
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            items = r.json().get("news", [])
            out = []
            for it in items:
                ts = it.get("providerPublishTime", 0)
                try:
                    pub_str = _dt.utcfromtimestamp(ts).strftime("%d %b  %H:%M")
                except Exception:
                    pub_str = ""
                out.append({
                    "title":     it.get("title", ""),
                    "publisher": it.get("publisher", ""),
                    "link":      it.get("link", ""),
                    "published": pub_str,
                })
            return out


# ---------------------------------------------------------------------------
# Alert monitor worker — polls active alerts every N seconds
# ---------------------------------------------------------------------------

class AlertMonitorWorker(QThread):
    alert_triggered = pyqtSignal(str, str, float, float)  # ticker, condition, threshold, price
    error           = pyqtSignal(str)

    POLL_INTERVAL_MS = 30_000   # 30 seconds

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        while not self._stop:
            try:
                _run(self._check_alerts())
            except Exception as e:
                _log.error("Alert monitor error: %s", e)
            # Wait in small increments so stop() is responsive
            for _ in range(self.POLL_INTERVAL_MS // 200):
                if self._stop:
                    return
                import time
                time.sleep(0.2)

    async def _check_alerts(self) -> None:
        from lens.db.store import get_active_alerts, mark_alert_triggered
        alerts = get_active_alerts()
        if not alerts:
            return
        # Group by ticker
        tickers = list({a["ticker"] for a in alerts})
        from lens.data.yahoo import get_quote
        import asyncio
        quotes = {}
        for ticker in tickers:
            try:
                q = await get_quote(ticker)
                quotes[ticker] = q.get("price")
            except Exception:
                pass
        for alert in alerts:
            ticker = alert["ticker"]
            price = quotes.get(ticker)
            if price is None:
                continue
            cond  = alert["condition_type"]
            thr   = float(alert["threshold"])
            triggered = False
            if cond == "price_above" and price >= thr:
                triggered = True
            elif cond == "price_below" and price <= thr:
                triggered = True
            if triggered:
                mark_alert_triggered(alert["id"])
                self.alert_triggered.emit(ticker, cond, thr, price)


# ---------------------------------------------------------------------------
# Multi-chart worker — fetches OHLCV for multiple tickers in parallel
# ---------------------------------------------------------------------------

class FetchMultiChartWorker(QThread):
    series_ready = pyqtSignal(str, list)   # ticker, data
    all_done     = pyqtSignal()
    error        = pyqtSignal(str, str)    # ticker, message

    def __init__(
        self,
        tickers: list,
        interval: str = "1d",
        range_: str = "1y",
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.tickers  = tickers
        self.interval = interval
        self.range_   = range_

    def run(self) -> None:
        try:
            _run(self._main())
        except Exception as e:
            self.error.emit("", str(e))

    async def _main(self) -> None:
        from lens.data.yahoo import get_chart
        import asyncio
        sem = asyncio.Semaphore(4)

        async def _fetch_one(ticker: str) -> None:
            async with sem:
                try:
                    data = await get_chart(ticker, self.interval, self.range_)
                    self.series_ready.emit(ticker, data)
                except Exception as e:
                    self.error.emit(ticker, str(e))

        await asyncio.gather(*[_fetch_one(t) for t in self.tickers])
        self.all_done.emit()
