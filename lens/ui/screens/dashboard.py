"""Dashboard screen — main view for LENS TUI."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header, Label, Static

from lens.config import Config
from lens.db import store
from lens.ui.widgets import (
    ClockWidget,
    MarketStatusWidget,
    SparklineWidget,
    _is_xpar_open,
    _sparkline,
    fmt_change,
    fmt_large,
    fmt_number,
    fmt_pct,
)

_config = Config()


class WatchlistTable(Static):
    """Left panel: watchlist with live prices."""

    BORDER_TITLE = "Watchlist"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._table: Optional[DataTable] = None
        self._rows: list[dict[str, Any]] = []
        self._selected_ticker: Optional[str] = None

    def compose(self) -> ComposeResult:
        table = DataTable(id="watchlist-table", cursor_type="row", show_header=True)
        table.add_columns("Ticker", "Price", "Change", "Change%", "Vol")
        yield table

    def on_mount(self) -> None:
        self._table = self.query_one("#watchlist-table", DataTable)

    def update_rows(self, rows: list[dict[str, Any]]) -> None:
        """Refresh the watchlist table with new price data."""
        if not self._table:
            return
        self._table.clear()
        for row in rows:
            ticker = row.get("ticker", "")
            price = row.get("price")
            change = row.get("change")
            change_pct = row.get("change_pct")
            volume = row.get("volume")

            price_text = Text(f"{price:,.2f}" if price else "──────", style="#f59e0b")
            change_text = fmt_change(change)
            change_pct_text = fmt_change(change_pct, is_pct=True)
            vol_text = Text(
                fmt_large(volume, currency="").strip() if volume else "──",
                style="#666666",
            )
            self._table.add_row(
                Text(ticker, style="#e8e8e8 bold"),
                price_text,
                change_text,
                change_pct_text,
                vol_text,
                key=ticker,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._selected_ticker = event.row_key.value if event.row_key else None
        self.post_message(DashboardScreen.TickerSelected(self._selected_ticker))


class ChartPanel(Static):
    """Center panel: sparkline/price chart for selected security."""

    BORDER_TITLE = "Chart"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ticker: Optional[str] = None
        self._prices: list[float] = []

    def compose(self) -> ComposeResult:
        yield Label("Select a security from the watchlist", id="chart-hint", classes="dim")
        yield SparklineWidget(id="dashboard-spark", width=60)
        yield Label("", id="chart-meta", classes="dim")

    def update_chart(self, ticker: str, prices: list[float], meta: dict[str, Any]) -> None:
        self._ticker = ticker
        self._prices = prices

        hint = self.query_one("#chart-hint", Label)
        hint.update(
            Text(ticker, style="#f59e0b bold") +
            Text(f"  {meta.get('name', '')}", style="#e8e8e8") +
            Text("  30d", style="#666666")
        )

        spark = self.query_one("#dashboard-spark", SparklineWidget)
        spark.values = prices

        chart_meta = self.query_one("#chart-meta", Label)
        price = meta.get("price")
        low_52w = meta.get("day_low_52w")
        high_52w = meta.get("day_high_52w")

        meta_parts = []
        if price is not None:
            meta_parts.append(f"Last: {price:,.2f}")
        if low_52w is not None:
            meta_parts.append(f"52w Low: {low_52w:,.2f}")
        if high_52w is not None:
            meta_parts.append(f"52w High: {high_52w:,.2f}")
        chart_meta.update(Text("  ".join(meta_parts), style="#666666"))


class FundamentalsPanel(Static):
    """Right panel: quick fundamentals for selected security."""

    BORDER_TITLE = "Fundamentals"

    def compose(self) -> ComposeResult:
        yield Label("", id="fund-content")

    def update_fundamentals(self, ticker: str, fund: Optional[Any]) -> None:
        content = self.query_one("#fund-content", Label)
        if fund is None:
            content.update(Text("No data", style="#666666"))
            return

        lines = Text()
        def row(label: str, val: str, style: str = "#e8e8e8") -> None:
            lines.append(f"{label:<12}", style="#666666")
            lines.append(f"{val}\n", style=style)

        row("P/E", fmt_number(fund["pe_ratio"], decimals=1))
        row("Fwd P/E", fmt_number(fund["forward_pe"], decimals=1))
        row("P/B", fmt_number(fund["pb_ratio"], decimals=2))
        row("EV/EBITDA", fmt_number(fund["ev_ebitda"], decimals=1))
        row("Div Yield", fmt_pct(fund["dividend_yield"], multiply=True))
        row("Mkt Cap", fmt_large(fund["market_cap"]))
        row("ROE", fmt_pct(fund["roe"], multiply=True))
        row("ROA", fmt_pct(fund["roa"], multiply=True))
        row("Rev Grw", fmt_pct(fund["revenue_growth"], multiply=True))
        row("D/E", fmt_number(fund["debt_to_equity"], decimals=2))

        content.update(lines)


class DashboardScreen(Screen):
    """Main dashboard screen."""

    BINDINGS = [
        Binding("d", "app.switch_screen('dashboard')", "Dashboard", show=True),
        Binding("q", "app.push_screen('quote')", "Quote", show=True),
        Binding("p", "app.push_screen('portfolio')", "Portfolio", show=True),
        Binding("s", "app.push_screen('screener')", "Screener", show=True),
        Binding("c", "app.push_screen('chart')", "Chart", show=True),
        Binding("r", "refresh_data", "Refresh", show=True),
        Binding("w", "app.push_screen('watchlist')", "Watchlists", show=False),
        Binding("slash", "app.push_screen('search')", "Search", show=True),
    ]

    class TickerSelected(Message):
        def __init__(self, ticker: Optional[str]) -> None:
            super().__init__()
            self.ticker = ticker

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="top-bar"):
            yield ClockWidget(id="clock")
            yield MarketStatusWidget(id="market-status")
            yield Label("  LENS v0.1  ", id="app-label", classes="accent")
        with Horizontal(id="main-area"):
            with Vertical(id="left-panel", classes="panel"):
                yield Label("WATCHLIST", classes="panel--title")
                yield WatchlistTable(id="watchlist")
            with Vertical(id="center-panel", classes="panel"):
                yield Label("CHART", classes="panel--title")
                yield ChartPanel(id="chart-panel")
            with Vertical(id="right-panel", classes="panel"):
                yield Label("FUNDAMENTALS", classes="panel--title")
                yield FundamentalsPanel(id="fund-panel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(MarketStatusWidget).is_open = _is_xpar_open()
        self.set_interval(_config.refresh_interval, self._background_refresh)
        self.run_worker(self._load_watchlist(), exclusive=True, group="watchlist")

    async def _load_watchlist(self) -> None:
        """Load watchlist tickers and fetch current prices."""
        from lens.data.yahoo import get_quote
        import httpx

        rows = store.get_watchlist_tickers(_config.default_watchlist)
        if not rows:
            return

        price_data = []
        async with httpx.AsyncClient(timeout=_config.http_timeout) as client:
            for row in rows:
                try:
                    q = await get_quote(row["ticker"], client=client)
                    price_data.append({
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "price": q.get("price"),
                        "change": q.get("change"),
                        "change_pct": q.get("change_pct"),
                        "volume": q.get("volume"),
                        **q,
                    })
                except Exception:
                    price_data.append({
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "price": None,
                        "change": None,
                        "change_pct": None,
                        "volume": None,
                    })

        watchlist = self.query_one("#watchlist", WatchlistTable)
        watchlist.update_rows(price_data)

        # Auto-select first ticker
        if price_data:
            first = price_data[0]
            await self._load_ticker_details(first["ticker"], first)

    async def _load_ticker_details(
        self, ticker: str, quote_data: Optional[dict[str, Any]] = None
    ) -> None:
        """Load chart data and fundamentals for a selected ticker."""
        from lens.data.yahoo import get_chart, get_quote

        # Load price history for sparkline
        try:
            chart = store.get_prices(
                ticker,
                from_date=None,
                to_date=None,
            )
            if chart.empty:
                from lens.data.yahoo import get_chart as yf_chart
                raw = await yf_chart(ticker, interval="1d", range_="1mo")
                prices = [r["close"] for r in raw if r.get("close")]
            else:
                prices = list(chart["close"].tail(30))
        except Exception:
            prices = []

        quote = quote_data or {}
        if not quote.get("price"):
            try:
                from lens.data.yahoo import get_quote
                quote = await get_quote(ticker)
            except Exception:
                pass

        chart_panel = self.query_one("#chart-panel", ChartPanel)
        chart_panel.update_chart(ticker, prices, quote)

        # Load fundamentals
        try:
            fund = store.get_latest_fundamentals(ticker)
        except Exception:
            fund = None

        fund_panel = self.query_one("#fund-panel", FundamentalsPanel)
        fund_panel.update_fundamentals(ticker, fund)

    def on_dashboard_screen_ticker_selected(self, event: TickerSelected) -> None:
        if event.ticker:
            self.run_worker(
                self._load_ticker_details(event.ticker),
                exclusive=True,
                group="ticker_detail",
            )

    def on_watchlist_table_ticker_selected(self, event: WatchlistTable.TickerSelected) -> None:
        if event.ticker:
            self.run_worker(
                self._load_ticker_details(event.ticker),
                exclusive=True,
                group="ticker_detail",
            )

    def _background_refresh(self) -> None:
        self.query_one(MarketStatusWidget).is_open = _is_xpar_open()
        self.run_worker(self._load_watchlist(), exclusive=True, group="watchlist")

    def action_refresh_data(self) -> None:
        self.run_worker(self._load_watchlist(), exclusive=True, group="watchlist")

    DEFAULT_CSS = """
    #top-bar {
        height: 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
        padding: 0 1;
    }
    #clock {
        width: auto;
        color: #f59e0b;
        margin-right: 2;
    }
    #market-status {
        width: auto;
        margin-right: 2;
    }
    #app-label {
        dock: right;
        width: auto;
        color: #666666;
    }
    #main-area {
        height: 1fr;
    }
    #left-panel {
        width: 30%;
        border-right: solid #222222;
    }
    #center-panel {
        width: 50%;
        border-right: solid #222222;
    }
    #right-panel {
        width: 20%;
    }
    .panel--title {
        color: #f59e0b;
        text-style: bold;
        background: #111111;
        padding: 0 1;
        border-bottom: solid #222222;
        height: 1;
    }
    #watchlist {
        height: 1fr;
    }
    #chart-panel {
        height: 1fr;
        padding: 1;
    }
    #fund-panel {
        height: 1fr;
        padding: 1;
    }
    #chart-hint {
        margin-bottom: 1;
    }
    #dashboard-spark {
        margin: 1 0;
        height: 1;
    }
    """
