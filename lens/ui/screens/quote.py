"""Quote screen — full-screen deep dive for a single security."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from lens.config import Config
from lens.db import store
from lens.ui.widgets import (
    PriceWidget,
    SparklineWidget,
    fmt_change,
    fmt_large,
    fmt_number,
    fmt_pct,
    staleness_indicator,
)

_config = Config()

_INTERVALS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"]


class QuoteHeader(Static):
    """Security identification header."""

    def compose(self) -> ComposeResult:
        yield Label("", id="q-name")
        yield Label("", id="q-meta")

    def update_security(self, sec: dict[str, Any]) -> None:
        name_lbl = self.query_one("#q-name", Label)
        name_lbl.update(
            Text(sec.get("name", ""), style="#e8e8e8 bold") +
            Text(f"  {sec.get('ticker', '')}", style="#f59e0b bold") +
            Text(f"  {sec.get('isin', '')}", style="#666666") +
            Text(f"  {sec.get('mic', '')}", style="#666666")
        )
        meta_lbl = self.query_one("#q-meta", Label)
        meta_lbl.update(
            Text(sec.get("sector", ""), style="#666666") +
            Text(" · ", style="#333333") +
            Text(sec.get("industry", ""), style="#666666") +
            Text(f"  {sec.get('currency', 'EUR')}", style="#94a3b8")
        )


class PricePanel(Static):
    """Live price panel with bid/ask and day stats."""

    def compose(self) -> ComposeResult:
        yield PriceWidget(id="q-price")
        yield Label("", id="q-price-detail")
        yield Label("", id="q-source")

    def update_quote(self, quote: dict[str, Any]) -> None:
        pw = self.query_one("#q-price", PriceWidget)
        pw.price = quote.get("price")
        pw.change = quote.get("change")
        pw.change_pct = quote.get("change_pct")

        detail = self.query_one("#q-price-detail", Label)
        parts = Text()

        def kv(k: str, v: str, sep: str = "  ") -> None:
            parts.append(f"{k} ", style="#666666")
            parts.append(f"{v}{sep}", style="#e8e8e8")

        kv("Open", fmt_number(quote.get("open")))
        kv("High", fmt_number(quote.get("high")))
        kv("Low", fmt_number(quote.get("low")))
        kv("Vol", fmt_large(quote.get("volume"), currency="").strip())
        kv("Prev", fmt_number(quote.get("prev_close")))
        if quote.get("bid") and quote.get("ask"):
            spread = quote["ask"] - quote["bid"]
            kv("Bid", fmt_number(quote.get("bid")))
            kv("Ask", fmt_number(quote.get("ask")))
            kv("Spread", f"{spread:.4f}", sep="")

        detail.update(parts)

        source_lbl = self.query_one("#q-source", Label)
        src = quote.get("source", "yahoo")
        source_lbl.update(Text(f"Source: {src}", style="#333333"))


class ChartPanel(Static):
    """Price chart panel using sparkline."""

    def compose(self) -> ComposeResult:
        yield Label("", id="q-chart-intervals")
        yield SparklineWidget(id="q-spark", width=80)
        yield Label("", id="q-chart-52w")

    def update_chart(self, prices: list[float], interval: str, quote: dict[str, Any]) -> None:
        interval_lbl = self.query_one("#q-chart-intervals", Label)
        parts = Text()
        for iv in _INTERVALS:
            if iv == interval:
                parts.append(f" [{iv}] ", style="#f59e0b bold")
            else:
                parts.append(f"  {iv}  ", style="#666666")
        interval_lbl.update(parts)

        spark = self.query_one("#q-spark", SparklineWidget)
        spark.values = prices
        spark._spark_width = 80

        lbl_52w = self.query_one("#q-chart-52w", Label)
        low_52 = quote.get("day_low_52w")
        high_52 = quote.get("day_high_52w")
        if low_52 and high_52:
            lbl_52w.update(
                Text(f"52w  ", style="#666666") +
                Text(f"{low_52:,.2f}", style="#ef4444") +
                Text(" ── ", style="#333333") +
                Text(f"{high_52:,.2f}", style="#22c55e")
            )


class FundamentalsTable(Static):
    """Full fundamentals table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="q-fund-table", show_header=False)

    def on_mount(self) -> None:
        table = self.query_one("#q-fund-table", DataTable)
        table.add_columns("Metric", "Value", "Metric", "Value")

    def update_fundamentals(self, fund: Optional[Any]) -> None:
        table = self.query_one("#q-fund-table", DataTable)
        table.clear()

        if fund is None:
            table.add_row("No fundamental data available", "", "", "")
            return

        rows = [
            ("P/E Ratio", fmt_number(fund["pe_ratio"], decimals=1), "Fwd P/E", fmt_number(fund["forward_pe"], decimals=1)),
            ("P/B Ratio", fmt_number(fund["pb_ratio"], decimals=2), "P/S Ratio", fmt_number(fund["ps_ratio"], decimals=2)),
            ("EV/EBITDA", fmt_number(fund["ev_ebitda"], decimals=1), "Market Cap", fmt_large(fund["market_cap"])),
            ("Div Yield", fmt_pct(fund["dividend_yield"], multiply=True), "Payout Ratio", fmt_pct(fund["payout_ratio"], multiply=True)),
            ("ROE", fmt_pct(fund["roe"], multiply=True), "ROA", fmt_pct(fund["roa"], multiply=True)),
            ("Revenue TTM", fmt_large(fund["revenue_ttm"]), "EBITDA", fmt_large(fund["ebitda"])),
            ("Net Income", fmt_large(fund["net_income"]), "Ent. Value", fmt_large(fund["enterprise_value"])),
            ("Debt/Equity", fmt_number(fund["debt_to_equity"], decimals=2), "Current Ratio", fmt_number(fund["current_ratio"], decimals=2)),
            ("Rev Growth", fmt_pct(fund["revenue_growth"], multiply=True), "EPS Growth", fmt_pct(fund["earnings_growth"], multiply=True)),
        ]

        for k1, v1, k2, v2 in rows:
            table.add_row(
                Text(k1, style="#666666"),
                Text(v1, style="#e8e8e8"),
                Text(k2, style="#666666"),
                Text(v2, style="#e8e8e8"),
            )


class QuoteScreen(Screen):
    """Full-screen security quote view."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "set_interval_1d", "1D"),
        Binding("2", "set_interval_1w", "1W"),
        Binding("3", "set_interval_1m", "1M"),
        Binding("4", "set_interval_6m", "6M"),
        Binding("5", "set_interval_1y", "1Y"),
        Binding("6", "set_interval_5y", "5Y"),
    ]

    current_interval: reactive[str] = reactive("1mo")

    def __init__(self, ticker: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ticker = ticker

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="q-top-bar"):
            yield Input(placeholder="Enter ticker (e.g. MC.PA)…", id="q-ticker-input")
        with Vertical(id="q-content"):
            yield QuoteHeader(id="q-header", classes="panel")
            with Horizontal(id="q-middle"):
                with Vertical(id="q-price-panel", classes="panel"):
                    yield Label("LIVE PRICE", classes="panel--title")
                    yield PricePanel(id="price-panel")
                with Vertical(id="q-chart-panel", classes="panel"):
                    yield Label("CHART", classes="panel--title")
                    yield ChartPanel(id="chart-panel")
            with Vertical(id="q-fundamentals", classes="panel"):
                yield Label("FUNDAMENTALS", classes="panel--title")
                yield FundamentalsTable(id="fund-table")
        yield Footer()

    def on_mount(self) -> None:
        if self._ticker:
            self.run_worker(self._load(self._ticker), exclusive=True, group="quote")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ticker = event.value.strip().upper()
        if ticker:
            self._ticker = ticker
            self.run_worker(self._load(ticker), exclusive=True, group="quote")

    def watch_current_interval(self, interval: str) -> None:
        if self._ticker:
            self.run_worker(self._load(self._ticker), exclusive=True, group="quote")

    async def _load(self, ticker: str) -> None:
        import httpx
        from lens.data.euronext import get_live_quote_with_fallback
        from lens.data.yahoo import get_chart, get_quote

        # Fetch security info from DB
        sec_row = store.get_security_by_ticker(ticker)
        sec = dict(sec_row) if sec_row else {"ticker": ticker, "name": ticker}

        hdr = self.query_one("#q-header", QuoteHeader)
        hdr.update_security(sec)

        # Fetch live quote
        try:
            if sec.get("isin") and sec.get("mic"):
                quote = await get_live_quote_with_fallback(
                    sec["isin"], sec["mic"], ticker
                )
            else:
                quote = await get_quote(ticker)
            if not quote.get("name"):
                quote["name"] = sec.get("name", ticker)
        except Exception:
            quote = {"ticker": ticker, "price": None}

        price_panel = self.query_one("#price-panel", PricePanel)
        price_panel.update_quote(quote)

        # Fetch chart data
        try:
            range_map = {
                "1d": ("5m", "1d"),
                "5d": ("15m", "5d"),
                "1mo": ("1d", "1mo"),
                "3mo": ("1d", "3mo"),
                "6mo": ("1d", "6mo"),
                "1y": ("1d", "1y"),
                "5y": ("1wk", "5y"),
            }
            iv, rng = range_map.get(self.current_interval, ("1d", "1y"))
            chart_data = await get_chart(ticker, interval=iv, range_=rng)
            prices = [r["close"] for r in chart_data if r.get("close")]
        except Exception:
            prices = []

        chart_panel = self.query_one("#chart-panel", ChartPanel)
        chart_panel.update_chart(prices, self.current_interval, quote)

        # Fundamentals
        try:
            fund = store.get_latest_fundamentals(ticker)
        except Exception:
            fund = None

        fund_table = self.query_one("#fund-table", FundamentalsTable)
        fund_table.update_fundamentals(fund)

    def action_refresh(self) -> None:
        if self._ticker:
            self.run_worker(self._load(self._ticker), exclusive=True, group="quote")

    def action_set_interval_1d(self) -> None:
        self.current_interval = "1d"

    def action_set_interval_1w(self) -> None:
        self.current_interval = "5d"

    def action_set_interval_1m(self) -> None:
        self.current_interval = "1mo"

    def action_set_interval_6m(self) -> None:
        self.current_interval = "6mo"

    def action_set_interval_1y(self) -> None:
        self.current_interval = "1y"

    def action_set_interval_5y(self) -> None:
        self.current_interval = "5y"

    DEFAULT_CSS = """
    #q-top-bar {
        height: 3;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
    }
    #q-ticker-input {
        width: 30;
    }
    #q-content {
        height: 1fr;
    }
    #q-header {
        height: auto;
        padding: 1;
        border-bottom: solid #222222;
    }
    #q-middle {
        height: 12;
        border-bottom: solid #222222;
    }
    #q-price-panel {
        width: 40%;
        border-right: solid #222222;
    }
    #q-chart-panel {
        width: 60%;
    }
    #q-fundamentals {
        height: 1fr;
    }
    #price-panel, #chart-panel, #fund-table {
        padding: 1;
    }
    .panel--title {
        color: #f59e0b;
        text-style: bold;
        background: #111111;
        padding: 0 1;
        border-bottom: solid #222222;
        height: 1;
    }
    #q-spark {
        height: 3;
        margin: 1 0;
    }
    """
