"""LENS Textual TUI application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, Static

from lens.config import Config
from lens.db.store import init_db
from lens.ui.screens.chart import ChartScreen
from lens.ui.screens.dashboard import DashboardScreen
from lens.ui.screens.portfolio import PortfolioScreen
from lens.ui.screens.quote import QuoteScreen
from lens.ui.screens.screener import ScreenerScreen
from lens.ui.theme import LENS_CSS, LENS_THEME

_config = Config()


class SearchScreen(Screen):
    """Quick ticker / command search screen."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Search: ticker, company name, or ISIN", id="search-title")
        yield Input(placeholder="Type to search…", id="search-input")
        yield Static("", id="search-results")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.run_worker(self._search(event.value), exclusive=True, group="search")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # If user types a ticker-like string, jump to quote
        val = event.value.strip().upper()
        if val:
            self.app.pop_screen()
            self.app.push_screen(QuoteScreen(ticker=val))

    async def _search(self, query: str) -> None:
        if len(query) < 2:
            self.query_one("#search-results", Static).update("")
            return

        from lens.data.yahoo import search as yahoo_search

        try:
            results = await yahoo_search(query)
        except Exception:
            results = []

        from rich.text import Text

        output = Text()
        for r in results[:10]:
            output.append(f"{r['ticker']:<12}", style="#f59e0b bold")
            output.append(f"  {r['name'][:40]:<40}", style="#e8e8e8")
            output.append(f"  {r['exchange']}\n", style="#666666")

        self.query_one("#search-results", Static).update(output)

    DEFAULT_CSS = """
    SearchScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #search-title {
        width: 70;
        color: #f59e0b;
        text-align: center;
        margin-bottom: 1;
    }
    #search-input {
        width: 70;
        margin-bottom: 1;
    }
    #search-results {
        width: 70;
        height: 15;
        background: #111111;
        border: solid #333333;
        padding: 1;
    }
    """


class AddTransactionScreen(Screen):
    """Modal: add a buy/sell/dividend transaction."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Label("Add Transaction", id="tx-title")
        yield Input(placeholder="Ticker (e.g. MC.PA)", id="tx-ticker")
        yield Input(placeholder="Type: BUY / SELL / DIVIDEND", id="tx-type")
        yield Input(placeholder="Date (YYYY-MM-DD)", id="tx-date")
        yield Input(placeholder="Quantity", id="tx-qty")
        yield Input(placeholder="Price per share", id="tx-price")
        yield Input(placeholder="Fees (optional, default 0)", id="tx-fees")
        yield Input(placeholder="Notes (optional)", id="tx-notes")
        yield Label("", id="tx-status")
        yield Label("Press Enter in last field to save, Esc to cancel", id="tx-hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tx-notes":
            self._save()

    def _save(self) -> None:
        from datetime import date as date_cls

        def val(id_: str) -> str:
            return self.query_one(f"#{id_}", Input).value.strip()

        ticker = val("tx-ticker").upper()
        tx_type = val("tx-type").upper()
        date_str = val("tx-date") or str(date_cls.today())
        qty_str = val("tx-qty")
        price_str = val("tx-price")
        fees_str = val("tx-fees") or "0"
        notes = val("tx-notes") or None

        status = self.query_one("#tx-status", Label)

        if not all([ticker, tx_type, qty_str, price_str]):
            status.update("Error: ticker, type, quantity, and price are required.")
            return

        if tx_type not in ("BUY", "SELL", "DIVIDEND", "SPLIT"):
            status.update("Error: type must be BUY, SELL, DIVIDEND, or SPLIT.")
            return

        try:
            qty = float(qty_str)
            price = float(price_str)
            fees = float(fees_str)
        except ValueError:
            status.update("Error: quantity, price, and fees must be numbers.")
            return

        from lens.db import store

        try:
            store.create_account(_config.default_account)
            store.add_transaction(
                account_name=_config.default_account,
                ticker=ticker,
                tx_type=tx_type,
                date=date_str,
                quantity=qty,
                price=price,
                fees=fees,
                notes=notes,
            )
            status.update(f"Saved: {tx_type} {qty} x {ticker} @ {price}")
        except Exception as e:
            status.update(f"Error: {e}")

    DEFAULT_CSS = """
    AddTransactionScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    AddTransactionScreen > * {
        width: 60;
        margin-bottom: 1;
    }
    #tx-title {
        color: #f59e0b;
        text-align: center;
        text-style: bold;
    }
    #tx-status {
        color: #ef4444;
    }
    #tx-hint {
        color: #666666;
    }
    """


class WatchlistManagerScreen(Screen):
    """Simple watchlist management: add/remove tickers."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close")]

    def compose(self) -> ComposeResult:
        yield Label("Watchlist Manager", id="wl-title")
        yield Input(placeholder="Ticker to add (e.g. MC.PA)", id="wl-add-input")
        yield Label("", id="wl-status")
        yield Label("Press Enter to add. Esc to close.", id="wl-hint")

    def on_mount(self) -> None:
        self.query_one("#wl-add-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ticker = event.value.strip().upper()
        if not ticker:
            return
        self._add_ticker(ticker)

    def _add_ticker(self, ticker: str) -> None:
        from lens.db import store

        status = self.query_one("#wl-status", Label)
        try:
            store.create_watchlist(_config.default_watchlist)
            # Try to look up the security; if not in DB, fetch from Yahoo
            sec = store.get_security_by_ticker(ticker)
            if sec is None:
                import asyncio
                from lens.data.yahoo import get_quote

                async def fetch_and_add() -> None:
                    q = await get_quote(ticker)
                    store.upsert_security(
                        ticker=ticker,
                        name=q.get("name", ticker),
                        currency=q.get("currency", "EUR"),
                    )
                    store.add_to_watchlist(_config.default_watchlist, ticker)

                asyncio.get_event_loop().run_until_complete(fetch_and_add())
            else:
                store.add_to_watchlist(_config.default_watchlist, ticker)

            status.update(f"Added {ticker} to watchlist '{_config.default_watchlist}'")
            self.query_one("#wl-add-input", Input).value = ""
        except Exception as e:
            status.update(f"Error: {e}")

    DEFAULT_CSS = """
    WatchlistManagerScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    WatchlistManagerScreen > * {
        width: 60;
        margin-bottom: 1;
    }
    #wl-title {
        color: #f59e0b;
        text-align: center;
        text-style: bold;
    }
    #wl-status {
        color: #22c55e;
    }
    #wl-hint {
        color: #666666;
    }
    """


class HelpScreen(Screen):
    """Help / keybinds reference."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close"), Binding("question_mark", "app.pop_screen", "Close")]

    HELP_CONTENT = """
[bold #f59e0b]LENS — European Equity Terminal[/]

[#666666]Global Keybinds[/]
  [#f59e0b]d[/]   Dashboard
  [#f59e0b]q[/]   Quote screen
  [#f59e0b]p[/]   Portfolio screen
  [#f59e0b]s[/]   Screener
  [#f59e0b]c[/]   Chart
  [#f59e0b]/[/]   Search (ticker / company)
  [#f59e0b]a[/]   Add transaction
  [#f59e0b]w[/]   Watchlist manager
  [#f59e0b]r[/]   Refresh current screen
  [#f59e0b]?[/]   This help screen
  [#f59e0b]Ctrl+C / q[/]   Quit (from dashboard)

[#666666]Chart Keybinds[/]
  [#f59e0b]1-6[/]   Switch interval (1D / 1W / 1M / 3M / 1Y / 5Y)
  [#f59e0b]v[/]   Toggle volume overlay
  [#f59e0b]m[/]   Toggle SMA overlays (20/50 day)

[#666666]Data[/]
  Prices:       Yahoo Finance
  Live quotes:  Euronext (Paris)
  Cache:        ~/.lens/lens.db
  Config:       ~/.lens/config.toml
"""

    def compose(self) -> ComposeResult:
        yield Static(self.HELP_CONTENT, id="help-content", markup=True)

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.85);
    }
    #help-content {
        width: 60;
        height: auto;
        background: #111111;
        border: solid #333333;
        padding: 2;
    }
    """


class LensApp(App):
    """Main LENS TUI application."""

    TITLE = "LENS"
    SUB_TITLE = "European Equity Terminal"
    CSS = LENS_CSS

    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "Dashboard", show=False),
        Binding("p", "go_portfolio", "Portfolio", show=True),
        Binding("s", "go_screener", "Screener", show=True),
        Binding("c", "go_chart", "Chart", show=True),
        Binding("a", "go_add_tx", "Add Tx", show=True),
        Binding("w", "go_watchlist", "Watchlist", show=False),
        Binding("slash", "go_search", "Search", show=True),
        Binding("question_mark", "go_help", "Help", show=True),
    ]

    SCREENS = {
        "dashboard": DashboardScreen,
        "quote": QuoteScreen,
        "portfolio": PortfolioScreen,
        "screener": ScreenerScreen,
        "chart": ChartScreen,
        "search": SearchScreen,
    }

    def on_mount(self) -> None:
        # Ensure DB and config exist
        init_db()
        from lens.db.store import create_account, create_watchlist

        try:
            create_watchlist(_config.default_watchlist)
            create_account(_config.default_account)
        except Exception:
            pass

        self.push_screen(DashboardScreen())

    def action_go_portfolio(self) -> None:
        self.push_screen(PortfolioScreen())

    def action_go_screener(self) -> None:
        self.push_screen(ScreenerScreen())

    def action_go_chart(self) -> None:
        self.push_screen(ChartScreen())

    def action_go_add_tx(self) -> None:
        self.push_screen(AddTransactionScreen())

    def action_go_watchlist(self) -> None:
        self.push_screen(WatchlistManagerScreen())

    def action_go_search(self) -> None:
        self.push_screen(SearchScreen())

    def action_go_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_switch_screen(self, screen: str) -> None:
        self.pop_screen()
