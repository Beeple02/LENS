"""pyqtgraph-based chart widget for LENS — candlestick, line, volume."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMenu, QSizePolicy, QVBoxLayout, QWidget

# Palette
C_BG      = "#0a0a0a"
C_SURFACE = "#111111"
C_BORDER  = "#222222"
C_TEXT    = "#e8e8e8"
C_DIM     = "#444444"
C_AMB     = "#f59e0b"
C_POS     = "#22c55e"
C_NEG     = "#ef4444"
C_GRAY    = "#555555"

pg.setConfigOptions(antialias=True, foreground=C_TEXT, background=C_BG)

# ECB Governing Council meeting dates 2025-2026 (hardcoded)
_ECB_DATES = [
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-29", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]

_INTERVALS = [
    ("1D",  "5m",  "1d"),
    ("1W",  "1h",  "5d"),
    ("1M",  "1d",  "1mo"),
    ("3M",  "1d",  "3mo"),
    ("1Y",  "1d",  "1y"),
    ("5Y",  "1wk", "5y"),
    ("MAX", "1wk", "max"),
]


# ── Indicator computation ──────────────────────────────────────────────────

def _compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI. Returns array same length as closes; leading values are NaN."""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    deltas = np.diff(closes)
    gains = np.clip(deltas, 0.0, None)
    losses = np.clip(-deltas, 0.0, None)
    avg_g = float(gains[:period].mean())
    avg_l = float(losses[:period].mean())
    rs = avg_g / avg_l if avg_l > 0 else float("inf")
    rsi[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period, n - 1):
        avg_g = (avg_g * (period - 1) + float(gains[i])) / period
        avg_l = (avg_l * (period - 1) + float(losses[i])) / period
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def _compute_macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple:
    """Returns (macd_line, signal_line, histogram) — all same length as closes."""
    def _ema(arr: np.ndarray, span: int) -> np.ndarray:
        alpha = 2.0 / (span + 1.0)
        out = np.empty(len(arr), dtype=float)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
        return out

    ema_fast  = _ema(closes, fast)
    ema_slow  = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    sig_line  = _ema(macd_line, signal)
    histogram = macd_line - sig_line
    return macd_line, sig_line, histogram


def _compute_bollinger(
    closes: np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple:
    """Returns (upper, middle, lower) — leading (period-1) values are NaN."""
    n = len(closes)
    upper  = np.full(n, np.nan)
    middle = np.full(n, np.nan)
    lower  = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        m = float(window.mean())
        s = float(window.std(ddof=1))
        middle[i] = m
        upper[i]  = m + num_std * s
        lower[i]  = m - num_std * s
    return upper, middle, lower


def _hex(color: str) -> QColor:
    return QColor(color)


class CandlestickItem(pg.GraphicsObject):
    """Fast candlestick renderer using QPainter."""

    def __init__(self, data: list[dict[str, Any]]) -> None:
        super().__init__()
        self._data = data
        self._picture: Optional[Any] = None
        self._generate()

    def _generate(self) -> None:
        from PyQt6.QtGui import QPainter, QPicture, QPen, QBrush
        from PyQt6.QtCore import QRectF
        from PyQt6.QtCore import Qt as _Qt

        picture = QPicture()
        p = QPainter(picture)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w = 0.4   # half candle body width in data units

        def _cpen(color: QColor, width: float = 1.0) -> QPen:
            pen = QPen(color, width)
            pen.setCosmetic(True)
            return pen

        for i, candle in enumerate(self._data):
            o = candle.get("open")
            h = candle.get("high")
            l = candle.get("low")
            c = candle.get("close")
            if None in (o, h, l, c):
                continue

            bullish = c >= o
            color = QColor(C_POS if bullish else C_NEG)

            body_top = max(o, c)
            body_bot = min(o, c)
            body_h   = max(body_top - body_bot, 0.0001)

            p.setPen(_cpen(color, 1.0))
            p.drawLine(pg.Point(i, l),        pg.Point(i, body_bot))
            p.drawLine(pg.Point(i, body_top), pg.Point(i, h))

            if bullish:
                p.setPen(_cpen(color, 1.5))
                p.setBrush(QBrush(_Qt.BrushStyle.NoBrush))
            else:
                p.setPen(_cpen(color, 1.0))
                p.setBrush(QBrush(color))

            p.drawRect(QRectF(i - w, body_bot, w * 2, body_h))

        p.end()
        self._picture = picture

    def paint(self, p, *args) -> None:
        if self._picture:
            self._picture.play(p)

    def boundingRect(self):
        if not self._data:
            return pg.QtCore.QRectF()
        xs = list(range(len(self._data)))
        lows  = [d.get("low")  or 0 for d in self._data]
        highs = [d.get("high") or 0 for d in self._data]
        return pg.QtCore.QRectF(0, min(lows), len(xs), max(highs) - min(lows))

    def update_data(self, data: list[dict[str, Any]]) -> None:
        self._data = data
        self._generate()
        self.update()


class ChartWidget(QWidget):
    """
    Full-featured price chart:
    - Candles or line mode
    - Volume sub-chart
    - SMA overlays (20/50/200)
    - Crosshair with OHLCV tooltip
    - Right-click context menu
    - EVENTS overlay (earnings + ECB meeting dates)
    - Dark-themed, amber accents
    """

    # Signals for cross-screen navigation
    open_quote             = pyqtSignal(str)   # ticker
    open_deep_dive         = pyqtSignal(str)   # ticker
    interval_change_requested = pyqtSignal(str)  # interval label e.g. "1Y"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: list[dict[str, Any]] = []
        self._dates: list[str] = []
        self._mode: str = "candles"
        self._sma: set[int] = set()
        self._show_volume: bool = True

        # Context menu state
        self._ticker: Optional[str] = None
        self._current_interval_label: str = "1Y"

        # Events overlay state
        self._events_active: bool = False
        self._earnings_past: list[str] = []
        self._earnings_next: Optional[str] = None
        self._event_items: list = []   # InfiniteLine + TextItem objects

        # Technical indicators state
        self._indicators: set[str] = set()
        self._bb_items:   list     = []   # overlay items on price plot

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._layout_widget = pg.GraphicsLayoutWidget()
        self._layout_widget.setBackground(C_BG)
        self._layout_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._layout_widget)

        # Price plot
        self._price_plot = self._layout_widget.addPlot(row=0, col=0)
        self._style_plot(self._price_plot)
        self._price_plot.showGrid(x=False, y=True, alpha=0.08)
        self._price_plot.setMinimumHeight(200)

        # Volume plot
        self._vol_plot = self._layout_widget.addPlot(row=1, col=0)
        self._style_plot(self._vol_plot)
        self._vol_plot.setFixedHeight(80)
        self._vol_plot.showGrid(x=False, y=False)

        # Link X axes
        self._vol_plot.setXLink(self._price_plot)

        # Crosshair lines
        self._vline = pg.InfiniteLine(angle=90, movable=False,
                                      pen=pg.mkPen(C_DIM, width=1, style=Qt.PenStyle.DotLine))
        self._hline = pg.InfiniteLine(angle=0, movable=False,
                                      pen=pg.mkPen(C_DIM, width=1, style=Qt.PenStyle.DotLine))
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)

        # OHLCV label overlay
        self._ohlcv_label = pg.TextItem(text="", anchor=(0, 0), color=C_TEXT)
        self._ohlcv_label.setPos(0, 0)
        self._price_plot.addItem(self._ohlcv_label, ignoreBounds=True)

        # Mouse tracking
        self._proxy = pg.SignalProxy(
            self._price_plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        # Right-click context menu
        self._price_plot.scene().sigMouseClicked.connect(self._on_scene_clicked)

        # Placeholder items
        self._candle_item: Optional[CandlestickItem] = None
        self._line_item: Optional[pg.PlotDataItem] = None
        self._vol_item: Optional[pg.BarGraphItem] = None
        self._sma_items: dict[int, pg.PlotDataItem] = {}

        # ── RSI sub-panel ──────────────────────────────────────────────────
        self._rsi_widget = pg.PlotWidget()
        self._rsi_widget.setBackground(C_BG)
        self._rsi_widget.setFixedHeight(80)
        self._rsi_widget.setVisible(False)
        self._style_plot(self._rsi_widget.getPlotItem())
        self._rsi_widget.getPlotItem().showGrid(x=False, y=True, alpha=0.08)
        self._rsi_widget.getPlotItem().setXLink(self._price_plot)
        self._rsi_widget.getPlotItem().setYRange(0, 100, padding=0)
        layout.addWidget(self._rsi_widget)

        # ── MACD sub-panel ─────────────────────────────────────────────────
        self._macd_widget = pg.PlotWidget()
        self._macd_widget.setBackground(C_BG)
        self._macd_widget.setFixedHeight(80)
        self._macd_widget.setVisible(False)
        self._style_plot(self._macd_widget.getPlotItem())
        self._macd_widget.getPlotItem().showGrid(x=False, y=True, alpha=0.08)
        self._macd_widget.getPlotItem().setXLink(self._price_plot)
        layout.addWidget(self._macd_widget)

    def _style_plot(self, plot: pg.PlotItem) -> None:
        plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        plot.getAxis("bottom").setPen(pg.mkPen(C_BORDER))
        plot.getAxis("left").setPen(pg.mkPen(C_BORDER))
        plot.getAxis("bottom").setTextPen(pg.mkPen(C_DIM))
        plot.getAxis("left").setTextPen(pg.mkPen(C_DIM))
        plot.setMenuEnabled(False)
        plot.hideButtons()

    # ── Technical indicator toggles ────────────────────────────────────────

    def toggle_indicator(self, name: str, enabled: bool) -> None:
        """Toggle a named indicator: 'bb', 'rsi', 'macd'."""
        self._indicators.discard(name)
        if enabled:
            self._indicators.add(name)
        if name == "rsi":
            self._rsi_widget.setVisible(enabled)
        elif name == "macd":
            self._macd_widget.setVisible(enabled)
        self._redraw_indicators()

    # ── Public setters ─────────────────────────────────────────────────────

    def set_ticker(self, ticker: str) -> None:
        self._ticker = ticker.upper() if ticker else None

    def set_current_interval_label(self, label: str) -> None:
        self._current_interval_label = label

    # ── Data loading ───────────────────────────────────────────────────────

    def load_data(self, data: list[dict[str, Any]]) -> None:
        """Load OHLCV data and redraw."""
        self._data = [d for d in data if d.get("close")]
        self._dates = [d["date"] for d in self._data]
        self._redraw()
        if self._events_active:
            self._draw_event_lines()

    def set_mode(self, mode: str) -> None:
        """Switch between 'candles' and 'line'."""
        self._mode = mode
        self._redraw()

    def set_log_mode(self, enabled: bool) -> None:
        """Toggle logarithmic Y axis on the price plot."""
        self._price_plot.setLogMode(x=False, y=enabled)

    def toggle_sma(self, period: int, enabled: bool) -> None:
        self._sma.discard(period)
        if enabled:
            self._sma.add(period)
        self._redraw_smas()

    # ── EVENTS overlay ─────────────────────────────────────────────────────

    def set_events_data(
        self,
        earnings_past: list[str],
        earnings_next: Optional[str],
    ) -> None:
        """Store event dates; call toggle_events(True) to draw them."""
        self._earnings_past = earnings_past or []
        self._earnings_next = earnings_next
        if self._events_active:
            self._draw_event_lines()

    def toggle_events(self, enabled: bool) -> None:
        self._events_active = enabled
        self._clear_event_items()
        if enabled and self._data:
            self._draw_event_lines()

    def _clear_event_items(self) -> None:
        for item in self._event_items:
            try:
                self._price_plot.removeItem(item)
            except Exception:
                pass
        self._event_items = []

    def _draw_event_lines(self) -> None:
        self._clear_event_items()
        if not self._dates:
            return

        date_to_idx: dict[str, int] = {d: i for i, d in enumerate(self._dates)}

        # Earnings past — dim amber dashed line
        for ds in self._earnings_past:
            idx = date_to_idx.get(ds)
            if idx is None:
                # nearest available date
                for i, d in enumerate(self._dates):
                    if d >= ds:
                        idx = i
                        break
            if idx is not None:
                pen = pg.mkPen(color=QColor(C_AMB), width=1,
                               style=Qt.PenStyle.DashLine)
                pen.setColor(QColor(245, 158, 11, 100))
                line = pg.InfiniteLine(pos=float(idx), angle=90, movable=False, pen=pen)
                self._price_plot.addItem(line, ignoreBounds=True)
                self._event_items.append(line)
                lbl = pg.TextItem("E", color=QColor(245, 158, 11, 130), anchor=(0.5, 1.0))
                vr = self._price_plot.viewRange()
                lbl.setPos(float(idx), vr[1][1] if vr else 0)
                lbl.setFont(pg.QtGui.QFont("Consolas", 8))
                self._price_plot.addItem(lbl, ignoreBounds=True)
                self._event_items.append(lbl)

        # Next earnings — bright amber
        if self._earnings_next:
            # find closest future date in chart
            idx = None
            for i, d in enumerate(self._dates):
                if d >= self._earnings_next:
                    idx = i
                    break
            if idx is None and self._dates:
                idx = len(self._dates) - 1
            if idx is not None:
                pen = pg.mkPen(color=QColor(C_AMB), width=1.5,
                               style=Qt.PenStyle.DashLine)
                line = pg.InfiniteLine(pos=float(idx), angle=90, movable=False, pen=pen)
                self._price_plot.addItem(line, ignoreBounds=True)
                self._event_items.append(line)
                lbl = pg.TextItem("E↑", color=QColor(C_AMB), anchor=(0.5, 1.0))
                vr = self._price_plot.viewRange()
                lbl.setPos(float(idx), vr[1][1] if vr else 0)
                lbl.setFont(pg.QtGui.QFont("Consolas", 8, weight=pg.QtGui.QFont.Weight.Bold))
                self._price_plot.addItem(lbl, ignoreBounds=True)
                self._event_items.append(lbl)

        # ECB dates — gray dashed
        for ds in _ECB_DATES:
            if not self._dates or ds < self._dates[0] or ds > self._dates[-1]:
                continue
            idx = date_to_idx.get(ds)
            if idx is None:
                for i, d in enumerate(self._dates):
                    if d >= ds:
                        idx = i
                        break
            if idx is not None:
                pen = pg.mkPen(color=QColor("#444444"), width=1,
                               style=Qt.PenStyle.DashLine)
                line = pg.InfiniteLine(pos=float(idx), angle=90, movable=False, pen=pen)
                self._price_plot.addItem(line, ignoreBounds=True)
                self._event_items.append(line)
                lbl = pg.TextItem("ECB", color=QColor("#666666"), anchor=(0.5, 1.0))
                vr = self._price_plot.viewRange()
                lbl.setPos(float(idx), vr[1][1] if vr else 0)
                lbl.setFont(pg.QtGui.QFont("Consolas", 7))
                self._price_plot.addItem(lbl, ignoreBounds=True)
                self._event_items.append(lbl)

    # ── Right-click context menu ───────────────────────────────────────────

    def _on_scene_clicked(self, evt) -> None:
        if evt.button() != Qt.MouseButton.RightButton:
            return
        # Only handle clicks inside the price plot
        if not self._price_plot.sceneBoundingRect().contains(evt.scenePos()):
            return
        evt.accept()
        self._show_context_menu(evt.screenPos().toPoint())

    def _show_context_menu(self, pos) -> None:
        ticker = self._ticker or ""
        menu = QMenu(self)

        # — Navigation ——————————————————————————————————————————————
        if ticker:
            act_quote = menu.addAction(f"Open Quote  →  {ticker}")
            act_quote.triggered.connect(lambda: self.open_quote.emit(ticker))

            act_dd = menu.addAction(f"Open Deep Dive  →  {ticker}")
            act_dd.triggered.connect(lambda: self.open_deep_dive.emit(ticker))

        # — Watchlist submenu ——————————————————————————————————————
        wl_menu = menu.addMenu("Add to Watchlist")
        if ticker:
            try:
                from lens.db.store import list_watchlists, add_to_watchlist, upsert_security, create_watchlist
                wls = list_watchlists()
                if wls:
                    for wl in wls:
                        wl_name = wl["name"]
                        act = wl_menu.addAction(wl_name)
                        def _add_handler(checked, name=wl_name):
                            try:
                                upsert_security(ticker=ticker, name=ticker)
                                add_to_watchlist(name, ticker)
                                self._show_status(f"✓ Added {ticker} to {name}")
                            except Exception:
                                pass
                        act.triggered.connect(_add_handler)
                else:
                    no_wl = wl_menu.addAction("No watchlists found")
                    no_wl.setEnabled(False)
            except Exception:
                err_act = wl_menu.addAction("Could not load watchlists")
                err_act.setEnabled(False)
        else:
            no_t = wl_menu.addAction("No ticker loaded")
            no_t.setEnabled(False)

        # — Alerts ——————————————————————————————————————————————————
        act_alert = menu.addAction("Set Price Alert…")
        act_alert.setEnabled(bool(ticker))
        if ticker:
            def _set_alert():
                try:
                    from lens.db.store import upsert_security, upsert_alert
                    from PyQt6.QtWidgets import (
                        QDialog, QDoubleSpinBox, QComboBox,
                        QDialogButtonBox, QFormLayout,
                    )
                    dlg = QDialog(self)
                    dlg.setWindowTitle(f"Set Alert — {ticker}")
                    form = QFormLayout(dlg)
                    cond = QComboBox()
                    cond.addItems(["Price rises above", "Price falls below"])
                    price_spin = QDoubleSpinBox()
                    price_spin.setRange(0.0, 1_000_000.0)
                    price_spin.setDecimals(4)
                    price_spin.setSingleStep(0.5)
                    if self._data:
                        price_spin.setValue(round(self._data[-1]["close"], 2))
                    btns = QDialogButtonBox(
                        QDialogButtonBox.StandardButton.Ok |
                        QDialogButtonBox.StandardButton.Cancel
                    )
                    btns.accepted.connect(dlg.accept)
                    btns.rejected.connect(dlg.reject)
                    form.addRow("Condition:", cond)
                    form.addRow("Price:", price_spin)
                    form.addRow(btns)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        cond_type = ("price_above" if cond.currentIndex() == 0
                                     else "price_below")
                        upsert_security(ticker=ticker, name=ticker)
                        upsert_alert(ticker, cond_type, price_spin.value())
                        self._show_status(f"✓ Alert set for {ticker}")
                except Exception as exc:
                    self._show_status(f"Alert error: {exc}")
            act_alert.triggered.connect(_set_alert)

        menu.addSeparator()

        # — Copy ———————————————————————————————————————————————————
        act_copy_ticker = menu.addAction("Copy Ticker")
        act_copy_ticker.setEnabled(bool(ticker))
        act_copy_ticker.triggered.connect(lambda: QApplication.clipboard().setText(ticker))

        last_price = self._data[-1]["close"] if self._data else None
        act_copy_price = menu.addAction(
            f"Copy Current Price  ({last_price:,.4f})" if last_price else "Copy Current Price"
        )
        act_copy_price.setEnabled(last_price is not None)
        if last_price is not None:
            act_copy_price.triggered.connect(
                lambda: QApplication.clipboard().setText(str(last_price))
            )

        menu.addSeparator()

        # — Interval submenu ———————————————————————————————————————
        iv_menu = menu.addMenu("Interval")
        for label, *_ in _INTERVALS:
            act = iv_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(label == self._current_interval_label)
            act.triggered.connect(
                lambda checked, lbl=label: self.interval_change_requested.emit(lbl)
            )

        # — SMA submenu ————————————————————————————————————————————
        sma_menu = menu.addMenu("SMA Overlays")
        for period in (20, 50, 200):
            act = sma_menu.addAction(f"SMA {period}")
            act.setCheckable(True)
            act.setChecked(period in self._sma)
            act.triggered.connect(
                lambda checked, p=period: self.toggle_sma(p, p not in self._sma)
            )

        menu.exec(pos)

    def _show_status(self, msg: str) -> None:
        """Briefly show a status message in the OHLCV label area."""
        self._ohlcv_label.setText(msg)
        QTimer.singleShot(2500, lambda: self._ohlcv_label.setText(""))

    # ── Drawing ────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        if not self._data:
            return

        closes = np.array([d["close"] for d in self._data], dtype=float)
        xs = np.arange(len(closes))

        # Clear price chart
        self._price_plot.clear()
        self._price_plot.addItem(self._vline, ignoreBounds=True)
        self._price_plot.addItem(self._hline, ignoreBounds=True)
        self._price_plot.addItem(self._ohlcv_label, ignoreBounds=True)
        self._sma_items = {}
        self._bb_items = []
        self._event_items = []

        if self._mode == "candles" and len(self._data) <= 500:
            self._candle_item = CandlestickItem(self._data)
            self._price_plot.addItem(self._candle_item)
        else:
            pen = pg.mkPen(C_AMB, width=1.5)
            self._line_item = self._price_plot.plot(xs, closes, pen=pen)

        # X-axis date ticks
        step = max(1, len(self._dates) // 8)
        ticks = [(i, self._dates[i][:10]) for i in range(0, len(self._dates), step)]
        self._price_plot.getAxis("bottom").setTicks([ticks])

        # Volume
        self._vol_plot.clear()
        if self._show_volume:
            vols = np.array([d.get("volume") or 0 for d in self._data], dtype=float)
            opens = np.array([d.get("open") or d["close"] for d in self._data], dtype=float)
            colors = [
                pg.mkBrush(C_POS) if c >= o else pg.mkBrush(C_NEG)
                for c, o in zip(closes, opens)
            ]
            self._vol_item = pg.BarGraphItem(
                x=xs, height=vols, width=0.7, brushes=colors,
                pen=pg.mkPen(None)
            )
            self._vol_plot.addItem(self._vol_item)
            self._vol_plot.getAxis("bottom").setTicks([ticks])

        self._redraw_smas()

        lows  = np.array([d.get("low")  or d["close"] for d in self._data], dtype=float)
        highs = np.array([d.get("high") or d["close"] for d in self._data], dtype=float)
        vols  = np.array([d.get("volume") or 0        for d in self._data], dtype=float)

        y_pad = (highs.max() - lows.min()) * 0.04
        self._price_plot.setXRange(0, len(self._data) - 1, padding=0.02)
        self._price_plot.setYRange(lows.min() - y_pad, highs.max() + y_pad, padding=0)

        if self._show_volume and vols.max() > 0:
            self._vol_plot.setXRange(0, len(self._data) - 1, padding=0.02)
            self._vol_plot.setYRange(0, vols.max() * 1.15, padding=0)

        self._redraw_indicators()

    def _redraw_smas(self) -> None:
        for item in self._sma_items.values():
            self._price_plot.removeItem(item)
        self._sma_items = {}

        if not self._data:
            return

        closes = np.array([d["close"] for d in self._data], dtype=float)
        xs = np.arange(len(closes))

        SMA_COLORS = {20: "#60a5fa", 50: "#c084fc", 200: "#f97316"}

        for period in sorted(self._sma):
            if len(closes) < period:
                continue
            sma_vals = np.convolve(closes, np.ones(period) / period, mode="valid")
            sma_xs = xs[period - 1:]
            color = SMA_COLORS.get(period, "#888888")
            item = self._price_plot.plot(
                sma_xs, sma_vals,
                pen=pg.mkPen(color, width=1.2, style=Qt.PenStyle.DashLine),
                name=f"SMA{period}",
            )
            self._sma_items[period] = item

    def _redraw_indicators(self) -> None:
        """Redraw all active technical indicators."""
        # Remove old BB items from price plot
        for item in self._bb_items:
            try:
                self._price_plot.removeItem(item)
            except Exception:
                pass
        self._bb_items = []

        if not self._data:
            return

        closes = np.array([d["close"] for d in self._data], dtype=float)
        xs     = np.arange(len(closes))

        if "bb" in self._indicators:
            self._draw_bb(closes, xs)
        if "rsi" in self._indicators:
            self._draw_rsi(closes, xs)
        else:
            self._rsi_widget.getPlotItem().clear()
        if "macd" in self._indicators:
            self._draw_macd(closes, xs)
        else:
            self._macd_widget.getPlotItem().clear()

    def _draw_bb(self, closes: np.ndarray, xs: np.ndarray) -> None:
        """Draw Bollinger Bands (20, 2σ) as overlay on the price plot."""
        upper, middle, lower = _compute_bollinger(closes)
        valid = ~np.isnan(upper)
        if not valid.any():
            return
        xv = xs[valid]
        pen_bb = pg.mkPen(color="#60a5fa", width=1,
                          style=Qt.PenStyle.DashLine)
        upper_curve = self._price_plot.plot(xv, upper[valid], pen=pen_bb,
                                            name="BB+")
        lower_curve = self._price_plot.plot(xv, lower[valid], pen=pen_bb,
                                            name="BB-")
        fill = pg.FillBetweenItem(upper_curve, lower_curve,
                                  brush=pg.mkBrush(96, 165, 250, 18))
        self._price_plot.addItem(fill)
        self._bb_items.extend([upper_curve, lower_curve, fill])

    def _draw_rsi(self, closes: np.ndarray, xs: np.ndarray) -> None:
        """Draw RSI(14) in the RSI sub-panel."""
        pi = self._rsi_widget.getPlotItem()
        pi.clear()
        rsi = _compute_rsi(closes)
        valid = ~np.isnan(rsi)
        if not valid.any():
            return
        xv = xs[valid]
        # RSI line
        pi.plot(xv, rsi[valid],
                pen=pg.mkPen(C_AMB, width=1.5))
        # Overbought/oversold bands
        for level, color in ((70, "#ef4444"), (30, "#22c55e"), (50, "#333333")):
            line = pg.InfiniteLine(
                pos=level, angle=0, movable=False,
                pen=pg.mkPen(color, width=1,
                             style=Qt.PenStyle.DotLine)
            )
            pi.addItem(line)
        pi.setYRange(0, 100, padding=0.05)
        pi.setXRange(xs[0], xs[-1], padding=0.02)
        # Label
        lbl = pg.TextItem("RSI 14", color=C_DIM, anchor=(0, 0))
        lbl.setFont(pg.QtGui.QFont("Consolas", 8))
        lbl.setPos(xv[0], 95)
        pi.addItem(lbl, ignoreBounds=True)

    def _draw_macd(self, closes: np.ndarray, xs: np.ndarray) -> None:
        """Draw MACD(12,26,9) histogram + lines in the MACD sub-panel."""
        pi = self._macd_widget.getPlotItem()
        pi.clear()
        macd_line, sig_line, histogram = _compute_macd(closes)
        # Histogram bars
        colors = [
            pg.mkBrush(C_POS) if h >= 0 else pg.mkBrush(C_NEG)
            for h in histogram
        ]
        bars = pg.BarGraphItem(x=xs, height=histogram, width=0.8,
                               brushes=colors, pen=pg.mkPen(None))
        pi.addItem(bars)
        # MACD and signal lines
        pi.plot(xs, macd_line,
                pen=pg.mkPen(C_AMB, width=1.2), name="MACD")
        pi.plot(xs, sig_line,
                pen=pg.mkPen("#60a5fa", width=1.0), name="Signal")
        # Zero line
        zero = pg.InfiniteLine(pos=0, angle=0, movable=False,
                               pen=pg.mkPen(C_DIM, width=1))
        pi.addItem(zero)
        pi.setXRange(xs[0], xs[-1], padding=0.02)
        # Label
        lbl = pg.TextItem("MACD 12/26/9", color=C_DIM, anchor=(0, 1))
        lbl.setFont(pg.QtGui.QFont("Consolas", 8))
        vr = pi.viewRange()
        y_top = vr[1][1] if vr else histogram.max()
        lbl.setPos(xs[0], y_top)
        pi.addItem(lbl, ignoreBounds=True)

    def _on_mouse_moved(self, evt) -> None:
        if not self._data:
            return
        pos = evt[0]
        if not self._price_plot.sceneBoundingRect().contains(pos):
            return

        mouse_point = self._price_plot.vb.mapSceneToView(pos)
        x = int(round(mouse_point.x()))
        y = mouse_point.y()

        self._vline.setPos(x)
        self._hline.setPos(y)

        if 0 <= x < len(self._data):
            d = self._data[x]
            o = d.get("open")
            h = d.get("high")
            lo = d.get("low")
            c = d.get("close")
            v = d.get("volume")
            date = self._dates[x] if x < len(self._dates) else ""

            def fmt(v, dec=2):
                return f"{v:,.{dec}f}" if v is not None else "—"

            def fmtv(v):
                if v is None:
                    return "—"
                if v >= 1e6:
                    return f"{v/1e6:.1f}M"
                if v >= 1e3:
                    return f"{v/1e3:.0f}K"
                return str(int(v))

            label = (
                f"{date}  "
                f"O {fmt(o)}  H {fmt(h)}  L {fmt(lo)}  C {fmt(c)}  Vol {fmtv(v)}"
            )
            self._ohlcv_label.setText(label)

            vr = self._price_plot.viewRange()
            self._ohlcv_label.setPos(vr[0][0], vr[1][1])
