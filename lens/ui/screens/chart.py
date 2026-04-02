"""Full-screen chart screen."""

from __future__ import annotations

from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, Static

from lens.config import Config

_config = Config()

_INTERVALS = [
    ("1d", "5m", "1d"),
    ("1wk", "1h", "5d"),
    ("1mo", "1d", "1mo"),
    ("3mo", "1d", "3mo"),
    ("1y", "1d", "1y"),
    ("5y", "1wk", "5y"),
]

_INTERVAL_LABELS = [iv[0] for iv in _INTERVALS]


class ChartDisplay(Static):
    """Renders a price chart using plotext."""

    def compose(self) -> ComposeResult:
        yield Label("", id="chart-output")

    def render_chart(
        self,
        prices: list[float],
        dates: list[str],
        volumes: Optional[list[float]],
        ticker: str,
        interval_label: str,
        sma_20: Optional[list[float]] = None,
        sma_50: Optional[list[float]] = None,
        show_volume: bool = False,
    ) -> None:
        lbl = self.query_one("#chart-output", Label)

        if not prices:
            lbl.update(Text("No data available", style="#666666"))
            return

        try:
            import plotext as plt

            plt.clf()
            plt.theme("dark")
            plt.canvas_color("black")
            plt.axes_color("black")
            plt.ticks_color("gray")

            plt.title(f"{ticker} — {interval_label}")
            plt.ylabel("Price")

            x = list(range(len(prices)))

            if show_volume and volumes:
                plt.subplots(2, 1)
                plt.subplot(1, 1)

            plt.plot(x, prices, color="orange", label="Price")

            if sma_20:
                plt.plot(x[-len(sma_20):], sma_20, color="white", label="SMA20")
            if sma_50:
                plt.plot(x[-len(sma_50):], sma_50, color="cyan", label="SMA50")

            # X-axis labels: show some dates
            if dates:
                step = max(1, len(dates) // 8)
                tick_xs = list(range(0, len(dates), step))
                tick_labels = [dates[i][:10] for i in tick_xs]
                plt.xticks(tick_xs, tick_labels)

            if show_volume and volumes:
                plt.subplot(2, 1)
                plt.bar(x, volumes, color="gray", label="Volume")
                plt.ylabel("Volume")

            chart_str = plt.build()
            lbl.update(Text.from_ansi(chart_str))

        except ImportError:
            # Fallback: simple ASCII sparkline
            from lens.ui.widgets import _sparkline
            spark = _sparkline(prices, width=min(len(prices), 80))
            lbl.update(
                Text(f"\n  {ticker}  {interval_label}\n\n  ", style="#666666") +
                spark +
                Text(f"\n\n  {len(prices)} data points", style="#666666")
            )
        except Exception as e:
            lbl.update(Text(f"Chart error: {e}", style="#ef4444"))


class ChartScreen(Screen):
    """Full-screen price chart."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "set_interval('1d')", "1D"),
        Binding("2", "set_interval('1wk')", "1W"),
        Binding("3", "set_interval('1mo')", "1M"),
        Binding("4", "set_interval('3mo')", "3M"),
        Binding("5", "set_interval('1y')", "1Y"),
        Binding("6", "set_interval('5y')", "5Y"),
        Binding("v", "toggle_volume", "Volume"),
        Binding("m", "toggle_sma", "SMA"),
    ]

    current_interval: reactive[str] = reactive("1mo")
    show_volume: reactive[bool] = reactive(False)
    show_sma: reactive[bool] = reactive(False)

    def __init__(self, ticker: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ticker = ticker

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="chart-controls"):
            yield Input(
                value=self._ticker or "",
                placeholder="Ticker (e.g. MC.PA)",
                id="chart-ticker-input",
            )
            yield Label("", id="chart-interval-bar")
            yield Label("", id="chart-options")
        yield ChartDisplay(id="chart-display")
        yield Footer()

    def on_mount(self) -> None:
        self._update_interval_bar()
        self._update_options_label()
        if self._ticker:
            self.run_worker(self._load(), exclusive=True, group="chart")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ticker = event.value.strip().upper()
        if ticker:
            self._ticker = ticker
            self.run_worker(self._load(), exclusive=True, group="chart")

    def watch_current_interval(self, _: str) -> None:
        self._update_interval_bar()
        if self._ticker:
            self.run_worker(self._load(), exclusive=True, group="chart")

    def watch_show_volume(self, _: bool) -> None:
        self._update_options_label()
        if self._ticker:
            self.run_worker(self._load(), exclusive=True, group="chart")

    def watch_show_sma(self, _: bool) -> None:
        self._update_options_label()
        if self._ticker:
            self.run_worker(self._load(), exclusive=True, group="chart")

    def _update_interval_bar(self) -> None:
        lbl = self.query_one("#chart-interval-bar", Label)
        parts = Text()
        for label in _INTERVAL_LABELS:
            if label == self.current_interval:
                parts.append(f" [{label}] ", style="#f59e0b bold")
            else:
                parts.append(f"  {label}  ", style="#666666")
        lbl.update(parts)

    def _update_options_label(self) -> None:
        lbl = self.query_one("#chart-options", Label)
        parts = Text()
        parts.append("Vol:", style="#666666")
        parts.append("[ON]" if self.show_volume else "off", style="#22c55e" if self.show_volume else "#666666")
        parts.append("  SMA:", style="#666666")
        parts.append("[ON]" if self.show_sma else "off", style="#22c55e" if self.show_sma else "#666666")
        lbl.update(parts)

    def _compute_sma(self, prices: list[float], window: int) -> Optional[list[float]]:
        if len(prices) < window:
            return None
        return [
            sum(prices[i - window:i]) / window
            for i in range(window, len(prices) + 1)
        ]

    async def _load(self) -> None:
        if not self._ticker:
            return

        from lens.data.yahoo import get_chart

        # Find matching interval config
        iv_config = next(
            (iv for iv in _INTERVALS if iv[0] == self.current_interval),
            ("1mo", "1d", "1mo"),
        )
        _, yf_interval, yf_range = iv_config

        try:
            data = await get_chart(self._ticker, interval=yf_interval, range_=yf_range)
        except Exception as e:
            display = self.query_one("#chart-display", ChartDisplay)
            lbl = display.query_one("#chart-output", Label)
            lbl.update(Text(f"Error fetching data: {e}", style="#ef4444"))
            return

        prices = [r["close"] for r in data if r.get("close")]
        dates = [r["date"] for r in data if r.get("close")]
        volumes = [r.get("volume") or 0 for r in data if r.get("close")]

        sma_20 = self._compute_sma(prices, 20) if self.show_sma else None
        sma_50 = self._compute_sma(prices, 50) if self.show_sma else None

        display = self.query_one("#chart-display", ChartDisplay)
        display.render_chart(
            prices=prices,
            dates=dates,
            volumes=volumes if self.show_volume else None,
            ticker=self._ticker,
            interval_label=self.current_interval,
            sma_20=sma_20,
            sma_50=sma_50,
            show_volume=self.show_volume,
        )

    def action_set_interval(self, interval: str) -> None:
        self.current_interval = interval

    def action_refresh(self) -> None:
        if self._ticker:
            self.run_worker(self._load(), exclusive=True, group="chart")

    def action_toggle_volume(self) -> None:
        self.show_volume = not self.show_volume

    def action_toggle_sma(self) -> None:
        self.show_sma = not self.show_sma

    DEFAULT_CSS = """
    #chart-controls {
        height: 3;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #222222;
        align: left middle;
    }
    #chart-ticker-input {
        width: 20;
        margin-right: 2;
    }
    #chart-interval-bar {
        width: auto;
        margin-right: 2;
    }
    #chart-options {
        width: auto;
        dock: right;
    }
    #chart-display {
        height: 1fr;
        padding: 1;
    }
    """
