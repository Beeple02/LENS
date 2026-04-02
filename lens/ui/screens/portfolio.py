"""Portfolio screen — positions, transactions, analytics."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static, TabbedContent, TabPane

from lens.config import Config
from lens.db import store
from lens.ui.widgets import fmt_change, fmt_large, fmt_number, fmt_pct

_config = Config()


class PositionsTab(Static):
    """Positions table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="positions-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#positions-table", DataTable)
        table.add_columns(
            "Ticker", "Name", "Qty", "Avg Cost", "Price", "Mkt Val",
            "P&L", "P&L%", "Weight"
        )

    def update_positions(self, rows: list[dict[str, Any]]) -> None:
        table = self.query_one("#positions-table", DataTable)
        table.clear()
        for row in rows:
            pnl = row.get("unrealized_pnl", 0) or 0
            pnl_pct = row.get("unrealized_pnl_pct", 0) or 0
            color = "#22c55e" if pnl >= 0 else "#ef4444"
            sign = "+" if pnl >= 0 else ""

            table.add_row(
                Text(row["ticker"], style="#f59e0b bold"),
                Text(row.get("name", "")[:20], style="#e8e8e8"),
                Text(f"{row.get('quantity', 0):,.0f}", style="#94a3b8"),
                Text(fmt_number(row.get("avg_cost")), style="#666666"),
                Text(fmt_number(row.get("current_price")), style="#e8e8e8"),
                Text(fmt_large(row.get("market_value")), style="#e8e8e8 bold"),
                Text(f"{sign}{fmt_large(pnl, currency='')}", style=color),
                Text(f"{sign}{pnl_pct:.2f}%", style=color),
                Text(f"{row.get('weight_pct', 0):.1f}%", style="#94a3b8"),
                key=row["ticker"],
            )


class TransactionsTab(Static):
    """Transactions history table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="tx-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#tx-table", DataTable)
        table.add_columns("Date", "Ticker", "Type", "Qty", "Price", "Fees", "Total", "Notes")

    def update_transactions(self, txs: list[Any]) -> None:
        table = self.query_one("#tx-table", DataTable)
        table.clear()
        for tx in txs:
            tx_type = tx["type"]
            type_colors = {
                "BUY": "#22c55e",
                "SELL": "#ef4444",
                "DIVIDEND": "#f59e0b",
                "SPLIT": "#94a3b8",
            }
            color = type_colors.get(tx_type, "#e8e8e8")
            qty = float(tx.get("quantity", 0))
            price = float(tx.get("price", 0))
            fees = float(tx.get("fees", 0) or 0)
            total = qty * price + fees

            table.add_row(
                Text(str(tx.get("date", "")), style="#666666"),
                Text(str(tx.get("ticker", "")), style="#f59e0b"),
                Text(tx_type, style=f"{color} bold"),
                Text(f"{qty:,.2f}", style="#e8e8e8"),
                Text(fmt_number(price), style="#e8e8e8"),
                Text(fmt_number(fees), style="#666666"),
                Text(fmt_large(total), style="#e8e8e8"),
                Text(str(tx.get("notes", "") or ""), style="#666666"),
            )


class AnalyticsTab(Static):
    """Analytics: sector breakdown, benchmark, returns."""

    def compose(self) -> ComposeResult:
        yield Label("", id="analytics-summary")
        yield Label("", id="analytics-sectors")
        yield Label("", id="analytics-benchmark")

    def update_analytics(
        self,
        summary: Any,  # PortfolioSummary
        sector_data: list[dict[str, Any]],
        benchmark: Optional[dict[str, Any]] = None,
    ) -> None:
        # Summary stats
        summ_lbl = self.query_one("#analytics-summary", Label)
        pnl_color = "#22c55e" if summary.total_unrealized_pnl >= 0 else "#ef4444"
        sign = "+" if summary.total_unrealized_pnl >= 0 else ""
        summ_text = Text()
        summ_text.append("Total Invested  ", style="#666666")
        summ_text.append(fmt_large(summary.total_cost) + "\n", style="#e8e8e8")
        summ_text.append("Market Value    ", style="#666666")
        summ_text.append(fmt_large(summary.total_market_value) + "\n", style="#e8e8e8 bold")
        summ_text.append("Unrealised P&L  ", style="#666666")
        summ_text.append(
            f"{sign}{fmt_large(summary.total_unrealized_pnl, currency='')}  "
            f"({sign}{summary.total_unrealized_pnl_pct:.2f}%)\n",
            style=pnl_color + " bold",
        )
        summ_text.append("Realised P&L    ", style="#666666")
        summ_lbl.update(summ_text)

        # Sector breakdown ASCII bars
        sec_lbl = self.query_one("#analytics-sectors", Label)
        if sector_data:
            sec_text = Text("\nSector Breakdown\n", style="#f59e0b bold")
            BAR_WIDTH = 20
            for item in sector_data:
                frac = item["weight_pct"] / 100
                filled = int(frac * BAR_WIDTH)
                bar = "█" * filled + "░" * (BAR_WIDTH - filled)
                sec_text.append(f"  {item['sector']:<20}", style="#e8e8e8")
                sec_text.append(bar, style="#f59e0b")
                sec_text.append(f"  {item['weight_pct']:.1f}%\n", style="#94a3b8")
            sec_lbl.update(sec_text)
        else:
            sec_lbl.update("")

        # Benchmark comparison
        bm_lbl = self.query_one("#analytics-benchmark", Label)
        if benchmark:
            bm_text = Text("\nBenchmark Comparison\n", style="#f59e0b bold")
            port_ret = benchmark.get("portfolio_twr")
            bm_ret = benchmark.get("benchmark_return")
            alpha = benchmark.get("alpha")
            if port_ret is not None:
                bm_text.append("Portfolio TWR  ", style="#666666")
                sign = "+" if port_ret >= 0 else ""
                bm_text.append(f"{sign}{port_ret * 100:.2f}%\n", style="#22c55e" if port_ret >= 0 else "#ef4444")
            if bm_ret is not None:
                bm_text.append("Benchmark      ", style="#666666")
                sign = "+" if bm_ret >= 0 else ""
                bm_text.append(f"{sign}{bm_ret * 100:.2f}%\n", style="#22c55e" if bm_ret >= 0 else "#ef4444")
            if alpha is not None:
                bm_text.append("Alpha          ", style="#666666")
                sign = "+" if alpha >= 0 else ""
                bm_text.append(f"{sign}{alpha * 100:.2f}%\n", style="#22c55e" if alpha >= 0 else "#ef4444")
            bm_lbl.update(bm_text)


class PortfolioSummaryBar(Static):
    """Footer bar with portfolio totals."""

    def compose(self) -> ComposeResult:
        yield Label("", id="portfolio-summary-bar")

    def update_summary(self, summary: Any) -> None:
        lbl = self.query_one("#portfolio-summary-bar", Label)
        pnl_color = "#22c55e" if summary.total_unrealized_pnl >= 0 else "#ef4444"
        sign = "+" if summary.total_unrealized_pnl >= 0 else ""
        text = Text()
        text.append("Invested: ", style="#666666")
        text.append(fmt_large(summary.total_cost) + "  ", style="#e8e8e8")
        text.append("Value: ", style="#666666")
        text.append(fmt_large(summary.total_market_value) + "  ", style="#e8e8e8 bold")
        text.append("P&L: ", style="#666666")
        text.append(
            f"{sign}{fmt_large(summary.total_unrealized_pnl, currency='')} "
            f"({sign}{summary.total_unrealized_pnl_pct:.2f}%)",
            style=pnl_color + " bold",
        )
        lbl.update(text)


class PortfolioScreen(Screen):
    """Portfolio management screen."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, account_name: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._account = account_name or _config.default_account

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="portfolio-top"):
            yield Label("", id="portfolio-account-label")
        with TabbedContent(id="portfolio-tabs"):
            with TabPane("Positions", id="tab-positions"):
                yield PositionsTab(id="positions-tab")
            with TabPane("Transactions", id="tab-transactions"):
                yield TransactionsTab(id="transactions-tab")
            with TabPane("Analytics", id="tab-analytics"):
                yield AnalyticsTab(id="analytics-tab")
        yield PortfolioSummaryBar(id="portfolio-summary")
        yield Footer()

    def on_mount(self) -> None:
        acct_lbl = self.query_one("#portfolio-account-label", Label)
        acct_lbl.update(
            Text("Account: ", style="#666666") +
            Text(self._account, style="#f59e0b bold")
        )
        self.run_worker(self._load(), exclusive=True, group="portfolio")

    async def _load(self) -> None:
        from lens.data.yahoo import get_quote
        from lens.portfolio.analytics import sector_attribution
        from lens.portfolio.tracker import build_portfolio
        import httpx

        # Ensure account exists
        try:
            store.create_account(self._account)
        except Exception:
            pass

        # Build portfolio
        summary = build_portfolio(self._account)

        # Fetch current prices for open positions
        prices: dict[str, float] = {}
        if summary.positions:
            async with httpx.AsyncClient(timeout=_config.http_timeout) as client:
                for ticker in list(summary.positions.keys()):
                    try:
                        q = await get_quote(ticker, client=client)
                        if q.get("price"):
                            prices[ticker] = float(q["price"])
                    except Exception:
                        pass

        # Rebuild with prices
        summary = build_portfolio(self._account, prices=prices)

        # Update positions tab
        pos_tab = self.query_one("#positions-tab", PositionsTab)
        pos_tab.update_positions(summary.position_rows())

        # Update transactions tab
        tx_tab = self.query_one("#transactions-tab", TransactionsTab)
        txs = store.get_transactions(self._account)
        tx_tab.update_transactions(list(reversed(txs)))  # newest first

        # Sector attribution
        sector_map: dict[str, str] = {}
        for ticker in summary.positions:
            sec = store.get_security_by_ticker(ticker)
            if sec:
                sector_map[ticker] = sec["sector"] or "Unknown"

        sectors = sector_attribution(summary.positions, sector_map, prices)

        analytics_tab = self.query_one("#analytics-tab", AnalyticsTab)
        analytics_tab.update_analytics(summary, sectors)

        # Summary bar
        summary_bar = self.query_one("#portfolio-summary", PortfolioSummaryBar)
        summary_bar.update_summary(summary)

    def action_refresh(self) -> None:
        self.run_worker(self._load(), exclusive=True, group="portfolio")

    DEFAULT_CSS = """
    #portfolio-top {
        height: 1;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
    }
    #portfolio-account-label {
        width: auto;
    }
    #portfolio-tabs {
        height: 1fr;
    }
    #positions-tab, #transactions-tab, #analytics-tab {
        height: 1fr;
    }
    #portfolio-summary {
        height: 1;
        background: #0a0a0a;
        border-top: solid #222222;
        padding: 0 1;
    }
    TabbedContent {
        background: #000000;
    }
    TabPane {
        padding: 0;
    }
    """
