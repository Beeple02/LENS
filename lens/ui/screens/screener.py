"""Screener screen — filter securities by fundamentals."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from lens.screener.engine import format_screener_results, run_screen
from lens.ui.widgets import fmt_large, fmt_number, fmt_pct


class ScreenerHelp(Static):
    """Shows available fields and example expressions."""

    HELP_TEXT = (
        "Fields: pe  forward_pe  pb  ps  ev_ebitda  div_yield  market_cap  "
        "roe  roa  revenue_growth  debt_equity  current_ratio  sector  industry\n"
        "Example: pe < 15 AND div_yield > 0.03 AND market_cap > 1e9\n"
        "         sector = \"Technology\" AND roe > 0.15"
    )

    def compose(self) -> ComposeResult:
        yield Label(self.HELP_TEXT, id="screener-help-text")

    DEFAULT_CSS = """
    ScreenerHelp {
        height: auto;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
        color: #666666;
    }
    """


class ScreenerResultsTable(Static):
    """Results table for screener output."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="screener-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#screener-table", DataTable)
        table.add_columns(
            "Ticker", "Name", "Sector",
            "P/E", "Fwd P/E", "P/B", "EV/EBITDA",
            "Div Yield", "Mkt Cap", "ROE", "ROA", "Rev Grw"
        )

    def update_results(self, rows: list[dict[str, Any]]) -> None:
        table = self.query_one("#screener-table", DataTable)
        table.clear()

        for _, row in (rows if isinstance(rows, list) else [
            {k: row[k] for k in row.keys()} for _, row in rows
        ]):
            self._add_row(table, row)

    def update_dataframe(self, df: Any) -> None:
        table = self.query_one("#screener-table", DataTable)
        table.clear()
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            table.add_row(
                Text(str(row.get("ticker", "")), style="#f59e0b bold"),
                Text(str(row.get("name", ""))[:22], style="#e8e8e8"),
                Text(str(row.get("sector", "") or ""), style="#666666"),
                Text(fmt_number(row.get("pe_ratio"), decimals=1), style="#e8e8e8"),
                Text(fmt_number(row.get("forward_pe"), decimals=1), style="#e8e8e8"),
                Text(fmt_number(row.get("pb_ratio"), decimals=2), style="#e8e8e8"),
                Text(fmt_number(row.get("ev_ebitda"), decimals=1), style="#e8e8e8"),
                Text(fmt_pct(row.get("dividend_yield"), multiply=True), style="#22c55e"),
                Text(fmt_large(row.get("market_cap")), style="#94a3b8"),
                Text(fmt_pct(row.get("roe"), multiply=True), style="#e8e8e8"),
                Text(fmt_pct(row.get("roa"), multiply=True), style="#e8e8e8"),
                Text(fmt_pct(row.get("revenue_growth"), multiply=True), style="#e8e8e8"),
                key=str(row.get("ticker", "")),
            )

    def _add_row(self, table: DataTable, row: dict[str, Any]) -> None:
        pass  # covered by update_dataframe


class ScreenerScreen(Screen):
    """Interactive screener screen."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "run_screen", "Run"),
        Binding("ctrl+l", "clear_filter", "Clear"),
    ]

    _debounce_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Static(id="screener-input-bar"):
            yield Label("Filter: ", id="screener-label")
            yield Input(
                placeholder='e.g. pe < 15 AND div_yield > 0.03 AND market_cap > 1e9',
                id="screener-input",
            )
        yield ScreenerHelp()
        yield Label("", id="screener-status")
        yield ScreenerResultsTable(id="screener-results")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#screener-input", Input).focus()
        self._run_screen("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._debounce_timer:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(0.5, lambda: self._run_screen(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._run_screen(event.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        ticker = event.row_key.value if event.row_key else None
        if ticker:
            from lens.ui.screens.quote import QuoteScreen
            self.app.push_screen(QuoteScreen(ticker=ticker))

    def _run_screen(self, expression: str) -> None:
        status = self.query_one("#screener-status", Label)
        try:
            df = run_screen(expression)
            results = self.query_one("#screener-results", ScreenerResultsTable)
            results.update_dataframe(df)
            count = len(df) if df is not None else 0
            status.update(Text(f"{count} result{'s' if count != 1 else ''}", style="#666666"))
        except ValueError as e:
            status.update(Text(f"Error: {e}", style="#ef4444"))
        except Exception as e:
            status.update(Text(f"Error: {e}", style="#ef4444"))

    def action_run_screen(self) -> None:
        expr = self.query_one("#screener-input", Input).value
        self._run_screen(expr)

    def action_clear_filter(self) -> None:
        self.query_one("#screener-input", Input).value = ""
        self._run_screen("")

    DEFAULT_CSS = """
    #screener-input-bar {
        height: 3;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
        layout: horizontal;
    }
    #screener-label {
        width: auto;
        padding: 1 1 0 0;
        color: #f59e0b;
    }
    #screener-input {
        width: 1fr;
    }
    #screener-status {
        height: 1;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
    }
    #screener-results {
        height: 1fr;
    }
    """
