"""Dashboard screen — watchlist | chart | stats."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lens.ui.widgets.chart_widget import ChartWidget
from lens.ui.widgets.data_table import (
    DataTable,
    COLOR_POS,
    COLOR_NEG,
    COLOR_DIM,
    COLOR_AMB,
    COLOR_TEXT,
    MONO,
    _item,
    _large_num,
)
from lens.ui.widgets.stat_card import StatCard

WATCHLIST_COLS = ["Ticker", "Last", "Chg%", "Volume", "High", "Low"]
STATS_FIELDS = [
    ("P/E",        "pe_ratio",       None),
    ("P/B",        "pb_ratio",       None),
    ("Div Yield",  "dividend_yield", "pct_mult"),
    ("Mkt Cap",    "market_cap",     "large"),
    ("EV/EBITDA",  "ev_ebitda",      None),
    ("ROE",        "roe",            "pct_mult"),
    ("Rev TTM",    "revenue_ttm",    "large"),
    ("52w High",   None,             "quote_high"),
    ("52w Low",    None,             "quote_low"),
]


def _fmt(v, decimals=2, suffix="", prefix=""):
    if v is None:
        return "—"
    return f"{prefix}{v:,.{decimals}f}{suffix}"


def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


class WatchlistPanel(QFrame):
    """Left panel — watchlist table with live prices."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("WATCHLIST")
        header.setProperty("class", "section-header")
        header.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(header)

        self._table = DataTable(WATCHLIST_COLS)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)

        # Sizing
        hdr = self._table.horizontalHeader()
        from PyQt6.QtWidgets import QHeaderView
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 72)
        self._table.setColumnWidth(1, 84)
        self._table.setColumnWidth(2, 72)
        self._table.setColumnWidth(4, 72)
        self._table.setColumnWidth(5, 72)

        layout.addWidget(self._table)

        self._loading = QLabel("Loading…")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet("color: #555555; font-size: 12px;")
        self._loading.hide()
        layout.addWidget(self._loading)

        self._rows: list[dict] = []
        self._table.currentCellChanged.connect(lambda cr, cc, pr, pc: self._on_row_changed(cr))

    # Public signals
    ticker_selected = None  # set externally
    remove_requested = None

    def set_loading(self, loading: bool) -> None:
        self._loading.setVisible(loading)
        self._table.setVisible(not loading)

    def update_rows(self, rows: list[dict]) -> None:
        self._rows = rows
        self.set_loading(False)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            ticker = row.get("ticker", "")
            price = row.get("price")
            change = row.get("change")
            change_pct = row.get("change_pct")
            volume = row.get("volume")
            high = row.get("high")
            low = row.get("low")

            color = COLOR_POS if (change and change > 0) else (COLOR_NEG if (change and change < 0) else COLOR_TEXT)

            self._table.setItem(i, 0, _item(ticker, color=COLOR_AMB, bold=True))
            self._table.setItem(i, 1, _item(
                f"{price:,.2f}" if price else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=color, mono=True,
            ))
            pct_str = (
                f"{'+'if change_pct > 0 else ''}{change_pct:.2f}%"
                if change_pct is not None else "—"
            )
            self._table.setItem(i, 2, _item(
                pct_str,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=color, mono=True,
            ))
            self._table.setItem(i, 3, _item(
                _large_num(volume, currency="").strip() if volume else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))
            self._table.setItem(i, 4, _item(
                _fmt(high) if high else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))
            self._table.setItem(i, 5, _item(
                _fmt(low) if low else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))

        self._table.setSortingEnabled(True)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            data = self._rows[row]
            if callable(self.ticker_selected):
                self.ticker_selected(data)

    def _context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._rows):
            return
        ticker = self._rows[row].get("ticker", "")
        menu = QMenu(self)
        open_chart = menu.addAction(f"Open chart — {ticker}")
        remove = menu.addAction(f"Remove {ticker} from watchlist")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == remove and callable(self.remove_requested):
            self.remove_requested(ticker)
        elif action == open_chart and callable(self.ticker_selected):
            self.ticker_selected(self._rows[row], open_chart=True)


class StatsPanel(QFrame):
    """Right panel — key fundamentals as stat cards."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel("FUNDAMENTALS")
        self._header.setProperty("class", "section-header")
        self._header.setContentsMargins(12, 8, 12, 4)
        layout.addWidget(self._header)

        self._name_label = QLabel("")
        self._name_label.setContentsMargins(12, 4, 12, 8)
        self._name_label.setStyleSheet("color: #e8e8e8; font-size: 12px; font-weight: 600;")
        layout.addWidget(self._name_label)

        grid_widget = QWidget()
        self._grid = QGridLayout(grid_widget)
        self._grid.setContentsMargins(8, 4, 8, 8)
        self._grid.setSpacing(6)

        self._cards: dict[str, StatCard] = {}
        labels = ["P/E", "P/B", "Div Yield", "Mkt Cap", "EV/EBITDA", "ROE",
                  "Rev TTM", "52w High", "52w Low"]
        for idx, lbl in enumerate(labels):
            card = StatCard(lbl)
            self._cards[lbl] = card
            row, col = divmod(idx, 2)
            self._grid.addWidget(card, row, col)

        layout.addWidget(grid_widget)
        layout.addStretch()

    def update_security(self, name: str, fund: Optional[dict], quote: Optional[dict]) -> None:
        self._name_label.setText(name)
        fund = fund or {}
        quote = quote or {}

        def s(f_key, mode=None):
            v = fund.get(f_key)
            if mode == "pct_mult":
                return _fmt_pct(v)
            elif mode == "large":
                return _large_num(v)
            return _fmt(v, decimals=1) if v is not None else "—"

        self._cards["P/E"].set_value(s("pe_ratio"))
        self._cards["P/B"].set_value(s("pb_ratio"))
        self._cards["Div Yield"].set_value(s("dividend_yield", "pct_mult"))
        self._cards["Mkt Cap"].set_value(s("market_cap", "large"))
        self._cards["EV/EBITDA"].set_value(s("ev_ebitda"))
        self._cards["ROE"].set_value(s("roe", "pct_mult"))
        self._cards["Rev TTM"].set_value(s("revenue_ttm", "large"))

        h52 = quote.get("day_high_52w")
        l52 = quote.get("day_low_52w")
        self._cards["52w High"].set_value(_fmt(h52) if h52 else "—")
        self._cards["52w Low"].set_value(_fmt(l52) if l52 else "—")


class DashboardScreen(QWidget):
    """Main dashboard: watchlist | chart | stats."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._selected_ticker: Optional[str] = None
        self._selected_row: Optional[dict] = None
        self._refresh_worker = None
        self._chart_worker = None
        self._fund_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # Left: watchlist
        self._watchlist_panel = WatchlistPanel()
        self._watchlist_panel.ticker_selected = self._on_ticker_selected
        self._watchlist_panel.remove_requested = self._on_remove_ticker
        splitter.addWidget(self._watchlist_panel)

        # Center: chart
        center = QFrame()
        center.setProperty("class", "panel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        chart_header = QLabel("CHART")
        chart_header.setProperty("class", "section-header")
        chart_header.setContentsMargins(12, 8, 12, 8)
        center_layout.addWidget(chart_header)

        self._chart_label = QLabel("Select a security from the watchlist")
        self._chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_label.setStyleSheet("color: #444444; font-size: 13px;")
        center_layout.addWidget(self._chart_label)

        self._chart = ChartWidget()
        self._chart.hide()
        center_layout.addWidget(self._chart)

        splitter.addWidget(center)

        # Right: stats
        self._stats_panel = StatsPanel()
        splitter.addWidget(self._stats_panel)

        splitter.setSizes([280, 580, 240])
        layout.addWidget(splitter)

        # Auto-refresh timer
        interval_ms = self._config.get("display", {}).get("refresh_interval", 30) * 1000
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_watchlist)
        self._refresh_timer.start(interval_ms)

    def on_show(self) -> None:
        from lens.config import Config
        cfg = Config()
        self._watchlist_name = cfg.default_watchlist
        self._refresh_watchlist()

    def _refresh_watchlist(self) -> None:
        from lens.ui.workers import FetchWatchlistWorker
        from lens.config import Config
        cfg = Config()
        wl = getattr(self, "_watchlist_name", cfg.default_watchlist)

        self._watchlist_panel.set_loading(True)
        if self._refresh_worker and self._refresh_worker.isRunning():
            return

        self._refresh_worker = FetchWatchlistWorker(wl, self)
        self._refresh_worker.result.connect(self._on_watchlist_result)
        self._refresh_worker.error.connect(self._on_error)
        self._refresh_worker.start()

    def _on_watchlist_result(self, rows: list) -> None:
        self._watchlist_panel.update_rows(rows)
        # Auto-select first if nothing selected
        if not self._selected_ticker and rows:
            self._on_ticker_selected(rows[0])

    def _on_ticker_selected(self, data: dict, open_chart: bool = False) -> None:
        ticker = data.get("ticker", "")
        if not ticker:
            return
        self._selected_ticker = ticker
        self._selected_row = data

        # Load chart (30 days)
        self._load_chart(ticker)

        # Load fundamentals
        self._load_fundamentals(ticker, data)

        if open_chart:
            # Signal main window to open chart screen
            mw = self.window()
            if hasattr(mw, "open_quote"):
                mw.open_quote(ticker)

    def _load_chart(self, ticker: str) -> None:
        from lens.ui.workers import FetchChartWorker

        if self._chart_worker and self._chart_worker.isRunning():
            self._chart_worker.quit()

        self._chart.hide()
        self._chart_label.show()
        self._chart_label.setText(f"Loading chart for {ticker}…")

        self._chart_worker = FetchChartWorker(ticker, "1d", "1mo", self)
        self._chart_worker.result.connect(self._on_chart_result)
        self._chart_worker.error.connect(lambda e: self._chart_label.setText(f"Chart unavailable: {e[:60]}"))
        self._chart_worker.start()

    def _on_chart_result(self, data: list) -> None:
        if data:
            self._chart.load_data(data)
            self._chart.show()
            self._chart_label.hide()
        else:
            self._chart_label.setText("No chart data")

    def _load_fundamentals(self, ticker: str, quote_data: dict) -> None:
        from lens.db.store import get_latest_fundamentals
        from lens.ui.workers import FetchFundamentalsWorker

        # Try DB first
        fund_row = get_latest_fundamentals(ticker)
        fund = dict(fund_row) if fund_row else None

        name = quote_data.get("name", ticker)
        self._stats_panel.update_security(name, fund, quote_data)

        # Fetch fresh fundamentals in background if stale
        if self._fund_worker and self._fund_worker.isRunning():
            return
        self._fund_worker = FetchFundamentalsWorker(ticker, self)
        self._fund_worker.result.connect(
            lambda f: self._stats_panel.update_security(name, f, quote_data)
        )
        self._fund_worker.start()

    def _on_remove_ticker(self, ticker: str) -> None:
        from lens.db.store import remove_from_watchlist
        from lens.config import Config
        cfg = Config()
        try:
            remove_from_watchlist(cfg.default_watchlist, ticker)
            self._refresh_watchlist()
        except Exception as e:
            pass  # silently ignore

    def _on_error(self, msg: str) -> None:
        self._watchlist_panel.set_loading(False)
