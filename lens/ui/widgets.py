"""Custom Textual widgets for LENS."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static


# ---------------------------------------------------------------------------
# Sparkline widget
# ---------------------------------------------------------------------------

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[float], width: int = 30, positive_style: str = "#22c55e", negative_style: str = "#ef4444") -> Text:
    """Generate a rich Text sparkline from a list of float values."""
    if not values or len(values) < 2:
        return Text("─" * width, style="#666666")

    trimmed = values[-width:]
    mn = min(v for v in trimmed if v is not None)
    mx = max(v for v in trimmed if v is not None)
    rng = mx - mn

    chars = []
    for v in trimmed:
        if v is None:
            chars.append(("─", "#666666"))
            continue
        if rng == 0:
            idx = 4
        else:
            idx = int((v - mn) / rng * (len(SPARK_CHARS) - 1))
        chars.append((SPARK_CHARS[idx], None))  # colour applied per-segment

    # Colour: green if last > first, red otherwise
    first_val = next((v for v in trimmed if v is not None), None)
    last_val = next((v for v in reversed(trimmed) if v is not None), None)
    trend_style = positive_style if (last_val and first_val and last_val >= first_val) else negative_style

    text = Text()
    for char, override_style in chars:
        text.append(char, style=override_style or trend_style)
    return text


class SparklineWidget(Static):
    """A simple sparkline showing price history."""

    values: reactive[list[float]] = reactive([], layout=True)

    def __init__(self, values: Optional[list[float]] = None, width: int = 40, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._spark_width = width
        if values:
            self.values = values

    def on_mount(self) -> None:
        self._render_spark()

    def watch_values(self, new_values: list[float]) -> None:
        self._render_spark()

    def _render_spark(self) -> None:
        spark = _sparkline(self.values, width=self._spark_width)
        self.update(spark)


# ---------------------------------------------------------------------------
# Price display widget
# ---------------------------------------------------------------------------

class PriceWidget(Static):
    """Displays a price with colour-coded change."""

    price: reactive[Optional[float]] = reactive(None)
    change: reactive[Optional[float]] = reactive(None)
    change_pct: reactive[Optional[float]] = reactive(None)

    def render(self) -> Text:
        text = Text()
        if self.price is None:
            text.append("──────", style="#666666")
            return text

        text.append(f"{self.price:,.2f}", style="#f59e0b bold")

        if self.change is not None:
            color = "#22c55e" if self.change >= 0 else "#ef4444"
            sign = "+" if self.change >= 0 else ""
            text.append(f"  {sign}{self.change:,.2f}", style=color)
            if self.change_pct is not None:
                text.append(f" ({sign}{self.change_pct:.2f}%)", style=color)
        return text


# ---------------------------------------------------------------------------
# Market status indicator
# ---------------------------------------------------------------------------

class MarketStatusWidget(Static):
    """Shows whether the market is open or closed."""

    is_open: reactive[bool] = reactive(False)

    def render(self) -> Text:
        text = Text()
        if self.is_open:
            text.append("● XPAR OPEN", style="#22c55e bold")
        else:
            text.append("○ XPAR CLOSED", style="#666666")
        return text


def _is_xpar_open() -> bool:
    """Check if Euronext Paris is currently open (CET/CEST)."""
    from datetime import datetime
    import zoneinfo

    try:
        tz = zoneinfo.ZoneInfo("Europe/Paris")
    except Exception:
        return False

    now = datetime.now(tz)
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close_time = now.replace(hour=17, minute=30, second=0, microsecond=0)
    return open_time <= now <= close_time


# ---------------------------------------------------------------------------
# Live clock widget
# ---------------------------------------------------------------------------

class ClockWidget(Static):
    """Live clock, updates every second."""

    time_str: reactive[str] = reactive("")

    def on_mount(self) -> None:
        self.set_interval(1, self._update_time)
        self._update_time()

    def _update_time(self) -> None:
        from datetime import datetime
        self.time_str = datetime.now().strftime("%H:%M:%S")

    def render(self) -> Text:
        return Text(self.time_str, style="#f59e0b")


# ---------------------------------------------------------------------------
# Stale data indicator
# ---------------------------------------------------------------------------

def staleness_indicator(fetched_at: Optional[str], max_age_hours: int = 24) -> Text:
    """Return a Text indicator showing data freshness."""
    if fetched_at is None:
        return Text("NO DATA", style="#ef4444 bold")
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(fetched_at)
        age = datetime.utcnow() - dt
        hours = age.total_seconds() / 3600
        if hours < 1:
            return Text(f"Updated {int(age.total_seconds() / 60)}m ago", style="#22c55e")
        elif hours < max_age_hours:
            return Text(f"Updated {int(hours)}h ago", style="#f59e0b")
        else:
            return Text(f"STALE ({int(hours)}h)", style="#ef4444")
    except Exception:
        return Text("Unknown age", style="#666666")


# ---------------------------------------------------------------------------
# Colour formatting helpers
# ---------------------------------------------------------------------------

def fmt_change(value: Optional[float], is_pct: bool = False, decimals: int = 2) -> Text:
    """Format a numeric change value with colour."""
    if value is None:
        return Text("N/A", style="#666666")
    color = "#22c55e" if value >= 0 else "#ef4444"
    sign = "+" if value > 0 else ""
    suffix = "%" if is_pct else ""
    return Text(f"{sign}{value:.{decimals}f}{suffix}", style=color)


def fmt_number(
    value: Optional[float],
    decimals: int = 2,
    suffix: str = "",
    scale: Optional[float] = None,
    na_str: str = "N/A",
) -> str:
    """Format a number for display, optionally scaling (e.g. billions)."""
    if value is None:
        return na_str
    if scale is not None:
        value = value * scale
    return f"{value:,.{decimals}f}{suffix}"


def fmt_large(value: Optional[float], currency: str = "€", na_str: str = "N/A") -> str:
    """Format large numbers as B/M/K."""
    if value is None:
        return na_str
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}{currency}{abs_val / 1e12:.2f}T"
    elif abs_val >= 1e9:
        return f"{sign}{currency}{abs_val / 1e9:.2f}B"
    elif abs_val >= 1e6:
        return f"{sign}{currency}{abs_val / 1e6:.2f}M"
    elif abs_val >= 1e3:
        return f"{sign}{currency}{abs_val / 1e3:.2f}K"
    else:
        return f"{sign}{currency}{abs_val:.2f}"


def fmt_pct(value: Optional[float], decimals: int = 2, multiply: bool = False) -> str:
    """Format a percentage value."""
    if value is None:
        return "N/A"
    if multiply:
        value = value * 100
    return f"{value:.{decimals}f}%"
