"""Homepage — EU market movers, news placeholder, portfolio graph, watchlist."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)

from lens.ui.widgets.data_table import (
    DataTable, COLOR_POS, COLOR_NEG, COLOR_DIM, COLOR_AMB, COLOR_TEXT,
    _item, _large_num,
)

C_BG = "#000000"
C_SURF = "#0d0d0d"
C_BORDER = "#1a1a1a"
C_DIM = "#444444"
C_AMB_STR = "#f59e0b"


def _pct_item(val: Optional[float]) -> Any:
    if val is None:
        return _item("—", color=COLOR_DIM)
    sign = "+" if val > 0 else ""
    color = COLOR_POS if val > 0 else (COLOR_NEG if val < 0 else COLOR_TEXT)
    return _item(f"{sign}{val:.2f}%", color=color, mono=True,
                 align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setProperty("class", "section-header")
    lbl.setContentsMargins(0, 6, 0, 4)
    return lbl


class MoversTable(QFrame):
    """Top/Bottom movers table."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QLabel(title)
        hdr.setProperty("class", "section-header")
        hdr.setContentsMargins(10, 8, 10, 6)
        layout.addWidget(hdr)

        cols = ["TICKER", "NAME", "LAST", "CHG%", "VOLUME"]
        self._table = DataTable(cols)
        from PyQt6.QtWidgets import QHeaderView
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in [0, 2, 3, 4]:
            self._table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMaximumHeight(380)
        layout.addWidget(self._table)

    def update_rows(self, rows: list[dict]) -> None:
        self._table.setRowCount(len(rows))
        self._table.setSortingEnabled(False)
        for i, r in enumerate(rows):
            pct = r.get("change_pct")
            self._table.setItem(i, 0, _item(r.get("ticker", ""), color=COLOR_AMB, bold=True))
            name = (r.get("name") or r.get("ticker", ""))[:24]
            self._table.setItem(i, 1, _item(name, color=COLOR_DIM))
            price = r.get("price")
            self._table.setItem(i, 2, _item(
                f"{price:,.2f}" if price else "—", mono=True,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self._table.setItem(i, 3, _pct_item(pct))
            vol = r.get("volume")
            self._table.setItem(i, 4, _item(
                _large_num(vol, currency="").strip() if vol else "—",
                color=COLOR_DIM, mono=True,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self._table.setSortingEnabled(True)


class PortfolioGraphPanel(QFrame):
    """Portfolio NAV over time, line chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QLabel("PORTFOLIO PERFORMANCE")
        hdr.setProperty("class", "section-header")
        hdr.setContentsMargins(10, 8, 10, 6)
        layout.addWidget(hdr)

        self._status = QLabel("Loading…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #444444; font-size: 12px;")
        layout.addWidget(self._status)

        self._plot_widget = pg.GraphicsLayoutWidget()
        self._plot_widget.setBackground(C_BG)
        self._plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._plot_widget.hide()
        layout.addWidget(self._plot_widget)

        self._plot = self._plot_widget.addPlot()
        self._plot.showGrid(x=False, y=True, alpha=0.08)
        self._plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        self._plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        self._plot.getAxis("bottom").setTextPen(pg.mkPen(C_DIM))
        self._plot.getAxis("left").setTextPen(pg.mkPen(C_DIM))
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()

    def update_nav(self, nav_series: list[tuple[str, float]]) -> None:
        """nav_series: list of (date_str, portfolio_value)."""
        if not nav_series:
            self._status.setText("No portfolio data — add transactions to get started")
            return

        dates = [d for d, _ in nav_series]
        values = np.array([v for _, v in nav_series], dtype=float)
        xs = np.arange(len(values))

        step = max(1, len(dates) // 8)
        ticks = [(i, dates[i][:10]) for i in range(0, len(dates), step)]
        self._plot.getAxis("bottom").setTicks([ticks])

        self._plot.clear()
        pen = pg.mkPen(C_AMB_STR, width=1.5)
        self._plot.plot(xs, values, pen=pen)

        fill = pg.FillBetweenItem(
            pg.PlotDataItem(xs, values),
            pg.PlotDataItem(xs, np.zeros_like(values)),
            brush=pg.mkBrush(245, 158, 11, 25),
        )
        self._plot.addItem(fill)

        y_pad = (values.max() - values.min()) * 0.05 or values.max() * 0.05
        self._plot.setXRange(0, len(xs) - 1, padding=0.02)
        self._plot.setYRange(values.min() - y_pad, values.max() + y_pad, padding=0)

        self._status.hide()
        self._plot_widget.show()


class WatchlistMiniPanel(QFrame):
    """Compact watchlist for homepage."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QLabel("WATCHLIST")
        hdr.setProperty("class", "section-header")
        hdr.setContentsMargins(10, 8, 10, 6)
        layout.addWidget(hdr)

        cols = ["TICKER", "LAST", "CHG%"]
        self._table = DataTable(cols)
        from PyQt6.QtWidgets import QHeaderView
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in [1, 2]:
            self._table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table)

    def update_rows(self, rows: list[dict]) -> None:
        self._table.setRowCount(len(rows))
        self._table.setSortingEnabled(False)
        for i, r in enumerate(rows):
            pct = r.get("change_pct")
            self._table.setItem(i, 0, _item(r.get("ticker", ""), color=COLOR_AMB, bold=True))
            price = r.get("price")
            self._table.setItem(i, 1, _item(
                f"{price:,.2f}" if price else "—", mono=True,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self._table.setItem(i, 2, _pct_item(pct))
        self._table.setSortingEnabled(True)


class HomepageScreen(QWidget):
    """Homepage: EU movers | news WIP | portfolio graph | watchlist."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._markets_worker = None
        self._wl_worker = None
        self._portfolio_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Top row: movers ──────────────────────────────────────────────
        movers_row = QSplitter(Qt.Orientation.Horizontal)
        movers_row.setHandleWidth(4)

        self._winners = MoversTable("▲  TOP MOVERS")
        self._losers  = MoversTable("▼  BOTTOM MOVERS")
        movers_row.addWidget(self._winners)
        movers_row.addWidget(self._losers)
        movers_row.setSizes([700, 700])
        layout.addWidget(movers_row, 3)

        # ── Bottom row: news | portfolio graph | watchlist ────────────────
        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.setHandleWidth(4)

        # News WIP
        news = QFrame()
        news.setProperty("class", "panel")
        news_layout = QVBoxLayout(news)
        news_layout.setContentsMargins(12, 8, 12, 8)
        news_layout.addWidget(_section("NEWS"))
        wip = QLabel("WIP  —  market news feed coming soon")
        wip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wip.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 13px;"
            "color: #333333; letter-spacing: 2px;")
        news_layout.addWidget(wip, 1)
        bottom.addWidget(news)

        # Portfolio graph
        self._port_graph = PortfolioGraphPanel()
        bottom.addWidget(self._port_graph)

        # Watchlist
        self._wl_panel = WatchlistMiniPanel()
        bottom.addWidget(self._wl_panel)

        bottom.setSizes([300, 500, 300])
        layout.addWidget(bottom, 2)

        # Auto-refresh every 5 min
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._load_markets)
        self._refresh_timer.start(300_000)

    def on_show(self) -> None:
        self._load_markets()
        self._load_watchlist()
        self._load_portfolio_nav()

    def cleanup(self) -> None:
        """Stop all background workers cleanly (called before widget deletion)."""
        self._refresh_timer.stop()
        for w in (self._markets_worker, self._wl_worker, self._portfolio_worker):
            if w is not None and w.isRunning():
                w.quit()
                w.wait(1000)

    # ── Data loading ──────────────────────────────────────────────────────

    def _load_markets(self) -> None:
        from lens.ui.workers import FetchMarketsWorker
        if self._markets_worker and self._markets_worker.isRunning():
            return
        self._markets_worker = FetchMarketsWorker(self)
        self._markets_worker.result.connect(self._on_markets)
        self._markets_worker.start()

    def _on_markets(self, data: list) -> None:
        n = min(25, len(data))
        self._winners.update_rows(data[:n])
        self._losers.update_rows(list(reversed(data[-n:])))

    def _load_watchlist(self) -> None:
        from lens.ui.workers import FetchWatchlistWorker
        from lens.config import Config
        wl = Config().default_watchlist
        if self._wl_worker and self._wl_worker.isRunning():
            return
        self._wl_worker = FetchWatchlistWorker(wl, self)
        self._wl_worker.result.connect(self._wl_panel.update_rows)
        self._wl_worker.start()

    def _load_portfolio_nav(self) -> None:
        from lens.ui.workers import PortfolioNAVWorker
        from lens.config import Config
        account = Config().default_account
        if self._portfolio_worker and self._portfolio_worker.isRunning():
            return
        self._portfolio_worker = PortfolioNAVWorker(account, self)
        self._portfolio_worker.result.connect(self._port_graph.update_nav)
        self._portfolio_worker.start()
