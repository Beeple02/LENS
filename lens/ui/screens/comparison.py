"""Multi-ticker comparison chart — up to 6 tickers rebased to 100."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

C_BG   = "#0a0a0a"
C_DIM  = "#444444"
C_TEXT = "#e8e8e8"
C_AMB  = "#f59e0b"
C_BORDER = "#222222"

# Distinct colors for up to 6 series
_SERIES_COLORS = ["#f59e0b", "#22c55e", "#60a5fa", "#f87171", "#c084fc", "#34d399"]

INTERVALS = [
    ("1M",  "1d",  "1mo"),
    ("3M",  "1d",  "3mo"),
    ("6M",  "1d",  "6mo"),
    ("1Y",  "1d",  "1y"),
    ("3Y",  "1wk", "3y"),
    ("5Y",  "1wk", "5y"),
]


class _LegendItem(QFrame):
    remove_requested = pyqtSignal(str)   # ticker

    def __init__(self, ticker: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self._ticker = ticker
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 12px;")
        lay.addWidget(dot)

        lbl = QLabel(ticker)
        lbl.setStyleSheet(f"color: {C_TEXT}; font-size: 11px; font-family: Consolas;")
        lay.addWidget(lbl)

        self._val_lbl = QLabel("")
        self._val_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-family: Consolas; min-width: 60px;")
        lay.addWidget(self._val_lbl)

        rm = QPushButton("×")
        rm.setFixedSize(16, 16)
        rm.setStyleSheet(
            "QPushButton { background: transparent; color: #555555; border: none; font-size: 12px; }"
            "QPushButton:hover { color: #ef4444; }"
        )
        rm.clicked.connect(lambda: self.remove_requested.emit(ticker))
        lay.addWidget(rm)

    def set_last_value(self, val: Optional[float]) -> None:
        if val is not None:
            sign = "+" if val >= 100 else ""
            pct = val - 100.0
            sign2 = "+" if pct >= 0 else ""
            self._val_lbl.setText(f"{sign2}{pct:.1f}%")


class ComparisonScreen(QWidget):
    """Multi-ticker comparison chart with tickers rebased to 100."""

    open_quote = pyqtSignal(str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._series: dict[str, list] = {}       # ticker → OHLCV list
        self._workers: dict[str, Any] = {}
        self._current_interval = INTERVALS[3]    # 1Y default
        self._legend_items: dict[str, _LegendItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QFrame()
        toolbar.setProperty("class", "panel")
        toolbar.setFixedHeight(48)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 6, 12, 6)
        tb.setSpacing(8)

        # Ticker inputs (up to 6)
        self._ticker_inputs: list[QLineEdit] = []
        for i in range(6):
            inp = QLineEdit()
            inp.setPlaceholderText(f"Ticker {i+1}")
            inp.setFixedWidth(90)
            inp.returnPressed.connect(self._on_enter)
            tb.addWidget(inp)
            self._ticker_inputs.append(inp)

        tb.addSpacing(8)

        compare_btn = QPushButton("COMPARE")
        compare_btn.setProperty("class", "primary")
        compare_btn.clicked.connect(self._on_enter)
        tb.addWidget(compare_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #222222;")
        tb.addWidget(sep)

        # Interval buttons
        self._iv_btns: list[QPushButton] = []
        for iv_label, *_ in INTERVALS:
            btn = QPushButton(iv_label)
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, lbl=iv_label: self._set_interval(lbl))
            tb.addWidget(btn)
            self._iv_btns.append(btn)
        self._iv_btns[3].setChecked(True)  # 1Y default

        tb.addStretch()
        layout.addWidget(toolbar)

        # Legend bar
        self._legend_bar = QFrame()
        self._legend_bar.setProperty("class", "panel")
        self._legend_bar.setFixedHeight(32)
        self._legend_layout = QHBoxLayout(self._legend_bar)
        self._legend_layout.setContentsMargins(12, 0, 12, 0)
        self._legend_layout.setSpacing(16)
        self._legend_layout.addStretch()
        layout.addWidget(self._legend_bar)

        # Chart
        pg.setConfigOptions(antialias=True, foreground=C_TEXT, background=C_BG)
        self._chart_widget = pg.GraphicsLayoutWidget()
        self._chart_widget.setBackground(C_BG)
        self._chart_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._chart_widget, 1)

        self._plot = self._chart_widget.addPlot(row=0, col=0)
        self._plot.showGrid(x=False, y=True, alpha=0.08)
        self._plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        self._plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        self._plot.getAxis("bottom").setPen(pg.mkPen(C_BORDER))
        self._plot.getAxis("left").setPen(pg.mkPen(C_BORDER))
        self._plot.getAxis("bottom").setTextPen(pg.mkPen(C_DIM))
        self._plot.getAxis("left").setTextPen(pg.mkPen(C_DIM))
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()

        # Zero line at 100
        zero = pg.InfiniteLine(pos=100, angle=0, movable=False,
                               pen=pg.mkPen(C_DIM, width=1, style=Qt.PenStyle.DotLine))
        self._plot.addItem(zero, ignoreBounds=True)

        self._placeholder = QLabel("Enter tickers above and press COMPARE")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {C_DIM}; font-size: 14px;")
        layout.addWidget(self._placeholder)

    def on_show(self) -> None:
        pass

    def load_tickers(self, tickers: list[str]) -> None:
        """Pre-load tickers (e.g. from peers tab)."""
        for i, t in enumerate(tickers[:6]):
            if i < len(self._ticker_inputs):
                self._ticker_inputs[i].setText(t.upper())
        self._on_enter()

    def _on_enter(self) -> None:
        tickers = [inp.text().strip().upper() for inp in self._ticker_inputs if inp.text().strip()]
        if not tickers:
            return
        self._series = {}
        self._placeholder.hide()
        self._clear_legend()
        self._fetch_all(tickers)

    def _set_interval(self, label: str) -> None:
        iv = next((i for i in INTERVALS if i[0] == label), None)
        if iv:
            self._current_interval = iv
            for i, (lbl, *_) in enumerate(INTERVALS):
                self._iv_btns[i].setChecked(lbl == label)
            if self._series:
                tickers = list(self._series.keys())
                self._series = {}
                self._fetch_all(tickers)

    def _fetch_all(self, tickers: list[str]) -> None:
        from lens.ui.workers import FetchChartWorker
        _, yf_interval, yf_range = self._current_interval
        for ticker in tickers:
            w = FetchChartWorker(ticker, yf_interval, yf_range, self)
            w.result.connect(lambda data, t=ticker: self._on_series_ready(t, data))
            w.start()
            self._workers[ticker] = w

    def _on_series_ready(self, ticker: str, data: list) -> None:
        if data:
            self._series[ticker] = data
        self._try_redraw()

    def _try_redraw(self) -> None:
        tickers_pending = [
            inp.text().strip().upper()
            for inp in self._ticker_inputs
            if inp.text().strip()
        ]
        # Redraw as each series comes in (progressive)
        self._redraw()

    def _redraw(self) -> None:
        self._plot.clear()
        # Re-add zero line
        zero = pg.InfiniteLine(pos=100, angle=0, movable=False,
                               pen=pg.mkPen(C_DIM, width=1, style=Qt.PenStyle.DotLine))
        self._plot.addItem(zero, ignoreBounds=True)
        self._clear_legend()

        if not self._series:
            return

        # Find common start date (latest of all start dates)
        all_dates = [set(d["date"] for d in series) for series in self._series.values()]
        if not all_dates:
            return
        common_start = max(min(dates) for dates in all_dates)

        # Build a common date index from the first series
        first_series = next(iter(self._series.values()))
        common_dates = [d["date"] for d in first_series if d["date"] >= common_start]
        date_to_idx = {d: i for i, d in enumerate(common_dates)}

        all_tickers = list(self._series.keys())
        for color_idx, ticker in enumerate(all_tickers):
            color = _SERIES_COLORS[color_idx % len(_SERIES_COLORS)]
            series_data = self._series[ticker]

            # Map dates to common index
            filtered = [(d["date"], d["close"]) for d in series_data
                        if d["date"] >= common_start and d["close"]]
            if not filtered:
                continue

            dates, prices = zip(*filtered)
            prices_arr = np.array(prices, dtype=float)
            base = prices_arr[0]
            if base == 0:
                continue
            rebased = prices_arr / base * 100.0

            xs = np.array([date_to_idx.get(d, i) for i, d in enumerate(dates)])
            self._plot.plot(xs, rebased,
                           pen=pg.mkPen(color, width=1.8),
                           name=ticker)
            self._add_legend_item(ticker, color, rebased[-1] if len(rebased) > 0 else None)

        # X-axis ticks
        n = len(common_dates)
        step = max(1, n // 6)
        ticks = [(i, common_dates[i][:7]) for i in range(0, n, step)]
        self._plot.getAxis("bottom").setTicks([ticks])

    def _add_legend_item(self, ticker: str, color: str, last_val: Optional[float]) -> None:
        item = _LegendItem(ticker, color)
        item.set_last_value(last_val)
        item.remove_requested.connect(self._remove_ticker)
        # Insert before stretch
        idx = self._legend_layout.count() - 1
        self._legend_layout.insertWidget(idx, item)
        self._legend_items[ticker] = item

    def _remove_ticker(self, ticker: str) -> None:
        self._series.pop(ticker, None)
        # Clear the corresponding input field
        for inp in self._ticker_inputs:
            if inp.text().strip().upper() == ticker:
                inp.clear()
                break
        self._redraw()

    def _clear_legend(self) -> None:
        for item in self._legend_items.values():
            item.setParent(None)
        self._legend_items = {}
