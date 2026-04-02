"""Typer CLI layer for LENS — scriptable commands."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lens.config import Config
from lens.db import store

_config = Config()
_console = Console()
_err_console = Console(stderr=True, style="red")

app = typer.Typer(
    name="lens",
    help="LENS — European equity terminal",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)

portfolio_app = typer.Typer(help="Portfolio commands")
watchlist_app = typer.Typer(help="Watchlist commands")

app.add_typer(portfolio_app, name="portfolio")
app.add_typer(watchlist_app, name="watchlist")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Root command: launch TUI
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from lens.app import LensApp
        from lens.db.store import init_db

        init_db()
        LensApp().run()


# ---------------------------------------------------------------------------
# lens quote <TICKER>
# ---------------------------------------------------------------------------

@app.command("quote")
def quote_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g. MC.PA)"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Print current quote for a ticker."""
    from lens.data.yahoo import get_quote

    try:
        q = _run(get_quote(ticker))
    except Exception as e:
        _err_console.print(f"Error fetching quote for {ticker}: {e}")
        raise typer.Exit(1)

    if json_output:
        _console.print_json(json.dumps(q))
        return

    store.init_db()
    table = Table(title=f"[bold #f59e0b]{ticker}[/] — Quote", show_header=False, box=None)
    table.add_column("Field", style="#666666")
    table.add_column("Value", style="#e8e8e8")

    price = q.get("price")
    change = q.get("change")
    change_pct = q.get("change_pct")

    price_str = f"{price:,.2f}" if price else "N/A"
    if change is not None:
        sign = "+" if change >= 0 else ""
        color = "green" if change >= 0 else "red"
        price_str += f"  [{color}]{sign}{change:,.2f} ({sign}{change_pct:.2f}%)[/]"

    table.add_row("Ticker", ticker)
    table.add_row("Name", q.get("name", "N/A"))
    table.add_row("Price", price_str)
    table.add_row("Open", f"{q.get('open'):,.2f}" if q.get("open") else "N/A")
    table.add_row("High", f"{q.get('high'):,.2f}" if q.get("high") else "N/A")
    table.add_row("Low", f"{q.get('low'):,.2f}" if q.get("low") else "N/A")
    table.add_row("Prev Close", f"{q.get('prev_close'):,.2f}" if q.get("prev_close") else "N/A")
    table.add_row("Volume", f"{q.get('volume'):,.0f}" if q.get("volume") else "N/A")
    table.add_row("Exchange", q.get("exchange", "N/A"))
    table.add_row("Currency", q.get("currency", "N/A"))

    _console.print(table)


# ---------------------------------------------------------------------------
# lens chart <TICKER>
# ---------------------------------------------------------------------------

@app.command("chart")
def chart_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    range_: str = typer.Option("1y", "--range", "-r", help="Range: 1d 5d 1mo 3mo 6mo 1y 2y 5y"),
    interval: str = typer.Option("1d", "--interval", "-i", help="Interval: 1m 5m 15m 1h 1d 1wk 1mo"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Print ASCII price chart for a ticker."""
    from lens.data.yahoo import get_chart

    try:
        data = _run(get_chart(ticker, interval=interval, range_=range_))
    except Exception as e:
        _err_console.print(f"Error: {e}")
        raise typer.Exit(1)

    if json_output:
        _console.print_json(json.dumps(data))
        return

    if not data:
        _err_console.print("No data returned.")
        raise typer.Exit(1)

    try:
        import plotext as plt

        prices = [r["close"] for r in data if r.get("close")]
        dates = [r["date"] for r in data if r.get("close")]
        x = list(range(len(prices)))

        plt.clf()
        plt.theme("dark")
        plt.canvas_color("black")
        plt.axes_color("black")
        plt.ticks_color("gray")
        plt.title(f"{ticker}  {range_} / {interval}")
        plt.plot(x, prices, color="orange")
        step = max(1, len(dates) // 8)
        plt.xticks(x[::step], dates[::step])
        plt.show()
    except ImportError:
        from lens.ui.widgets import _sparkline
        prices = [r["close"] for r in data if r.get("close")]
        spark = _sparkline(prices, width=60)
        _console.print(f"\n  [bold #f59e0b]{ticker}[/]  [{interval}] [{range_}]\n")
        _console.print("  ", end="")
        _console.print(spark)
        _console.print(f"\n  {len(prices)} candles", style="#666666")


# ---------------------------------------------------------------------------
# lens portfolio summary
# ---------------------------------------------------------------------------

@portfolio_app.command("summary")
def portfolio_summary(
    account: str = typer.Option(None, "--account", "-a", help="Account name"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Print portfolio summary table."""
    from lens.data.yahoo import get_quote
    from lens.portfolio.tracker import build_portfolio

    account_name = account or _config.default_account
    store.init_db()

    # Fetch current prices
    summary = build_portfolio(account_name)
    prices: dict[str, float] = {}

    if summary.positions:
        async def fetch_prices() -> None:
            import httpx
            async with httpx.AsyncClient(timeout=_config.http_timeout) as client:
                for ticker in summary.positions:
                    try:
                        q = await get_quote(ticker, client=client)
                        if q.get("price"):
                            prices[ticker] = float(q["price"])
                    except Exception:
                        pass

        _run(fetch_prices())

    summary = build_portfolio(account_name, prices=prices)
    rows = summary.position_rows()

    if json_output:
        _console.print_json(json.dumps({
            "account": account_name,
            "positions": rows,
            "total_cost": summary.total_cost,
            "total_value": summary.total_market_value,
            "total_pnl": summary.total_unrealized_pnl,
            "total_pnl_pct": summary.total_unrealized_pnl_pct,
        }, default=str))
        return

    if not rows:
        _console.print(f"[#666666]No positions in account '{account_name}'[/]")
        return

    table = Table(title=f"Portfolio — {account_name}", style="#e8e8e8")
    table.add_column("Ticker", style="#f59e0b bold")
    table.add_column("Name", max_width=25)
    table.add_column("Qty", justify="right")
    table.add_column("Avg Cost", justify="right", style="#666666")
    table.add_column("Price", justify="right")
    table.add_column("Mkt Val", justify="right", style="bold")
    table.add_column("P&L", justify="right")
    table.add_column("P&L%", justify="right")
    table.add_column("Wt%", justify="right", style="#94a3b8")

    for row in rows:
        pnl = row.get("unrealized_pnl", 0) or 0
        pnl_pct = row.get("unrealized_pnl_pct", 0) or 0
        color = "green" if pnl >= 0 else "red"
        sign = "+" if pnl >= 0 else ""
        from lens.ui.widgets import fmt_large, fmt_number

        table.add_row(
            row["ticker"],
            row.get("name", "")[:25],
            f"{row.get('quantity', 0):,.0f}",
            fmt_number(row.get("avg_cost")),
            fmt_number(row.get("current_price")),
            fmt_large(row.get("market_value")),
            f"[{color}]{sign}{fmt_large(pnl, currency='')}[/]",
            f"[{color}]{sign}{pnl_pct:.2f}%[/]",
            f"{row.get('weight_pct', 0):.1f}%",
        )

    _console.print(table)

    pnl_color = "green" if summary.total_unrealized_pnl >= 0 else "red"
    sign = "+" if summary.total_unrealized_pnl >= 0 else ""
    from lens.ui.widgets import fmt_large

    _console.print(
        f"\n  Invested [#666666]→[/] [bold]{fmt_large(summary.total_cost)}[/]"
        f"  Value [#666666]→[/] [bold]{fmt_large(summary.total_market_value)}[/]"
        f"  P&L [#666666]→[/] [{pnl_color} bold]{sign}{fmt_large(summary.total_unrealized_pnl, currency='')} "
        f"({sign}{summary.total_unrealized_pnl_pct:.2f}%)[/]"
    )


@portfolio_app.command("add-tx")
def portfolio_add_tx(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
    tx_type: str = typer.Option(..., "--type", help="Transaction type: BUY/SELL/DIVIDEND/SPLIT"),
    qty: float = typer.Option(..., "--qty", "-q", help="Quantity"),
    price: float = typer.Option(..., "--price", "-p", help="Price per share"),
    date_str: str = typer.Option(str(date.today()), "--date", "-d", help="Date (YYYY-MM-DD)"),
    fees: float = typer.Option(0.0, "--fees", "-f", help="Transaction fees"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account name"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Notes"),
) -> None:
    """Add a transaction to the portfolio."""
    store.init_db()
    account_name = account or _config.default_account

    # Ensure security exists
    sec = store.get_security_by_ticker(ticker.upper())
    if sec is None:
        async def fetch_security() -> None:
            from lens.data.yahoo import get_quote
            q = await get_quote(ticker.upper())
            store.upsert_security(
                ticker=ticker.upper(),
                name=q.get("name", ticker.upper()),
                currency=q.get("currency", "EUR"),
            )

        _run(fetch_security())

    try:
        store.create_account(account_name)
        tx_id = store.add_transaction(
            account_name=account_name,
            ticker=ticker.upper(),
            tx_type=tx_type.upper(),
            date=date_str,
            quantity=qty,
            price=price,
            fees=fees,
            notes=notes,
        )
        _console.print(
            f"[green]✓[/] Added [bold #f59e0b]{tx_type.upper()}[/] "
            f"{qty} × [#f59e0b]{ticker.upper()}[/] @ {price:.2f}  "
            f"[#666666](ID: {tx_id})[/]"
        )
    except Exception as e:
        _err_console.print(f"Error: {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# lens watchlist
# ---------------------------------------------------------------------------

@watchlist_app.command("add")
def watchlist_add(
    ticker: str = typer.Argument(..., help="Ticker to add"),
    watchlist: Optional[str] = typer.Option(None, "--watchlist", "-w", help="Watchlist name"),
) -> None:
    """Add a ticker to a watchlist."""
    store.init_db()
    wl_name = watchlist or _config.default_watchlist

    sec = store.get_security_by_ticker(ticker.upper())
    if sec is None:
        async def fetch_security() -> None:
            from lens.data.yahoo import get_quote
            q = await get_quote(ticker.upper())
            store.upsert_security(
                ticker=ticker.upper(),
                name=q.get("name", ticker.upper()),
                currency=q.get("currency", "EUR"),
            )

        try:
            _run(fetch_security())
        except Exception as e:
            _err_console.print(f"Could not fetch security info: {e}")
            raise typer.Exit(1)

    try:
        store.create_watchlist(wl_name)
        store.add_to_watchlist(wl_name, ticker.upper())
        _console.print(f"[green]✓[/] Added [#f59e0b]{ticker.upper()}[/] to watchlist '[bold]{wl_name}[/]'")
    except Exception as e:
        _err_console.print(f"Error: {e}")
        raise typer.Exit(1)


@watchlist_app.command("remove")
def watchlist_remove(
    ticker: str = typer.Argument(..., help="Ticker to remove"),
    watchlist: Optional[str] = typer.Option(None, "--watchlist", "-w", help="Watchlist name"),
) -> None:
    """Remove a ticker from a watchlist."""
    store.init_db()
    wl_name = watchlist or _config.default_watchlist
    try:
        store.remove_from_watchlist(wl_name, ticker.upper())
        _console.print(f"[green]✓[/] Removed [#f59e0b]{ticker.upper()}[/] from '[bold]{wl_name}[/]'")
    except Exception as e:
        _err_console.print(f"Error: {e}")
        raise typer.Exit(1)


@watchlist_app.command("list")
def watchlist_list(
    watchlist: Optional[str] = typer.Option(None, "--watchlist", "-w", help="Watchlist name"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """List tickers in a watchlist."""
    store.init_db()
    wl_name = watchlist or _config.default_watchlist
    rows = store.get_watchlist_tickers(wl_name)

    if json_output:
        _console.print_json(json.dumps([dict(r) for r in rows], default=str))
        return

    if not rows:
        _console.print(f"[#666666]Watchlist '{wl_name}' is empty[/]")
        return

    table = Table(title=f"Watchlist — {wl_name}", style="#e8e8e8")
    table.add_column("Ticker", style="#f59e0b bold")
    table.add_column("Name")
    table.add_column("ISIN", style="#666666")
    table.add_column("MIC", style="#94a3b8")
    table.add_column("Currency", style="#94a3b8")
    table.add_column("Added", style="#666666")

    for row in rows:
        table.add_row(
            row["ticker"],
            row.get("name", ""),
            row.get("isin", "") or "—",
            row.get("mic", ""),
            row.get("currency", ""),
            str(row.get("wl_added_at", ""))[:10],
        )

    _console.print(table)


# ---------------------------------------------------------------------------
# lens screen
# ---------------------------------------------------------------------------

@app.command("screen")
def screen_cmd(
    expression: str = typer.Argument(..., help='Filter expression, e.g. "pe < 15 AND div_yield > 0.03"'),
    universe: str = typer.Option("all", "--universe", "-u", help="'all' or watchlist name"),
    sort_by: Optional[str] = typer.Option(None, "--sort", "-s", help="Sort field"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run a screener expression against fundamental data."""
    from lens.screener.engine import run_screen

    store.init_db()

    try:
        df = run_screen(expression, universe=universe, sort_by=sort_by, limit=limit)
    except ValueError as e:
        _err_console.print(f"Filter error: {e}")
        raise typer.Exit(1)

    if json_output:
        _console.print_json(df.to_json(orient="records"))
        return

    if df.empty:
        _console.print("[#666666]No results matching filter[/]")
        return

    table = Table(title=f"Screen: {expression}", style="#e8e8e8")
    for col in ["ticker", "name", "sector", "pe_ratio", "pb_ratio", "ev_ebitda",
                "dividend_yield", "market_cap", "roe", "roa", "revenue_growth"]:
        if col in df.columns:
            table.add_column(col, justify="right" if col not in ("ticker", "name", "sector") else "left")

    from lens.ui.widgets import fmt_large, fmt_number, fmt_pct

    for _, row in df.iterrows():
        vals = []
        for col in ["ticker", "name", "sector", "pe_ratio", "pb_ratio", "ev_ebitda",
                    "dividend_yield", "market_cap", "roe", "roa", "revenue_growth"]:
            if col not in df.columns:
                continue
            v = row.get(col)
            if col == "ticker":
                vals.append(f"[#f59e0b bold]{v}[/]")
            elif col in ("name", "sector"):
                vals.append(str(v or "")[:25])
            elif col in ("dividend_yield", "roe", "roa", "revenue_growth"):
                vals.append(fmt_pct(v, multiply=True))
            elif col == "market_cap":
                vals.append(fmt_large(v))
            else:
                vals.append(fmt_number(v, decimals=1))
        table.add_row(*vals)

    _console.print(table)
    _console.print(f"[#666666]{len(df)} result{'s' if len(df) != 1 else ''}[/]")


# ---------------------------------------------------------------------------
# lens fetch
# ---------------------------------------------------------------------------

@app.command("fetch")
def fetch_cmd(
    ticker: str = typer.Argument(..., help="Ticker to refresh"),
    fundamentals: bool = typer.Option(True, "--fundamentals/--no-fundamentals", help="Fetch fundamentals"),
    prices: bool = typer.Option(True, "--prices/--no-prices", help="Fetch price history"),
) -> None:
    """Force refresh price history and fundamentals from APIs."""
    store.init_db()

    async def do_fetch() -> None:
        import httpx
        from lens.data.yahoo import get_chart, get_fundamentals, get_quote

        async with httpx.AsyncClient(timeout=_config.http_timeout) as client:
            _console.print(f"Fetching quote for [#f59e0b]{ticker}[/]…")
            q = await get_quote(ticker, client=client)
            store.upsert_security(
                ticker=ticker,
                name=q.get("name", ticker),
                currency=q.get("currency", "EUR"),
            )
            _console.print(f"  [#666666]Price: {q.get('price')}[/]")

            if prices:
                _console.print(f"Fetching price history…")
                data = await get_chart(ticker, interval="1d", range_="2y", client=client)
                store.upsert_price_history(ticker, data)
                _console.print(f"  [#666666]{len(data)} candles saved[/]")

            if fundamentals:
                _console.print(f"Fetching fundamentals…")
                fund = await get_fundamentals(ticker, client=client)
                store.upsert_fundamentals(ticker, fund)
                _console.print(f"  [#666666]Fundamentals saved[/]")

    try:
        _run(do_fetch())
        _console.print(f"[green]✓[/] Done for [#f59e0b]{ticker}[/]")
    except Exception as e:
        _err_console.print(f"Error: {e}")
        raise typer.Exit(1)


# Type alias to suppress import error
from typing import Any
