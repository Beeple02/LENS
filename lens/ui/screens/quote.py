"""Quote screen — full deep-dive for a single security."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lens.ui.widgets.chart_widget import ChartWidget
from lens.ui.widgets.data_table import COLOR_DIM, COLOR_TEXT, _large_num
from lens.ui.widgets.stat_card import StatCard

INTERVALS = [
    ("1D",  "5m",  "1d"),
    ("1W",  "1h",  "5d"),
    ("1M",  "1d",  "1mo"),
    ("3M",  "1d",  "3mo"),
    ("1Y",  "1d",  "1y"),
    ("5Y",  "1wk", "5y"),
]

FUND_SECTIONS = [
    ("Valuation",   [("P/E", "pe_ratio"), ("Fwd P/E", "forward_pe"),
                     ("P/B", "pb_ratio"), ("P/S", "ps_ratio"), ("EV/EBITDA", "ev_ebitda")]),
    ("Profitability",[("ROE", "roe", "pct_mult"), ("ROA", "roa", "pct_mult"),
                     ("EBITDA", "ebitda", "large"), ("Net Income", "net_income", "large")]),
    ("Growth",      [("Rev Growth", "revenue_growth", "pct_mult"),
                     ("EPS Growth", "earnings_growth", "pct_mult")]),
    ("Health",      [("Debt/Equity", "debt_to_equity"), ("Current Ratio", "current_ratio")]),
    ("Dividends",   [("Div Yield", "dividend_yield", "pct_mult"),
                     ("Payout Ratio", "payout_ratio", "pct_mult")]),
]


def _fmt_fund(v, mode=None, decimals=2):
    if v is None:
        return "—"
    if mode == "pct_mult":
        return f"{v * 100:.2f}%"
    if mode == "large":
        return _large_num(v)
    return f"{v:,.{decimals}f}"


class QuoteHeader(QFrame):
    deep_dive_clicked = pyqtSignal(str)  # emits ticker when DEEP DIVE button pressed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(0)

        self._name  = QLabel()
        self._name.setStyleSheet("font-size: 16px; font-weight: 700; color: #e8e8e8;")
        self._ticker = QLabel()
        self._ticker.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "font-size: 14px; font-weight: 700; color: #f59e0b; margin-left: 12px;"
        )
        self._isin = QLabel()
        self._isin.setStyleSheet("font-size: 11px; color: #555555; margin-left: 16px;")
        self._meta = QLabel()
        self._meta.setStyleSheet("font-size: 11px; color: #555555; margin-left: 16px;")

        self._add_btn = QPushButton("+ WATCHLIST")
        self._add_btn.setProperty("class", "interval-btn")
        self._add_btn.setEnabled(False)
        self._add_btn.setFixedWidth(100)
        self._add_btn.clicked.connect(self._on_add_watchlist)

        self._deep_dive_btn = QPushButton("DEEP DIVE ↗")
        self._deep_dive_btn.setProperty("class", "interval-btn")
        self._deep_dive_btn.setEnabled(False)
        self._deep_dive_btn.setFixedWidth(110)
        self._deep_dive_btn.clicked.connect(self._on_deep_dive)

        layout.addWidget(self._name)
        layout.addWidget(self._ticker)
        layout.addWidget(self._isin)
        layout.addWidget(self._meta)
        layout.addStretch()
        layout.addWidget(self._add_btn)
        layout.addSpacing(8)
        layout.addWidget(self._deep_dive_btn)

        self._current_ticker: str = ""
        self._current_name: str = ""
        self._current_currency: str = "EUR"

    def update(self, sec: dict) -> None:
        self._current_ticker  = sec.get("ticker", "")
        self._current_name    = sec.get("name", self._current_ticker)
        self._current_currency = sec.get("currency", "EUR")
        self._name.setText(self._current_name)
        self._ticker.setText(self._current_ticker)
        isin = sec.get("isin", "")
        self._isin.setText(isin or "")
        self._isin.setVisible(bool(isin))
        parts = [sec.get("mic", ""), self._current_currency, sec.get("sector", "")]
        self._meta.setText("  ·  ".join(p for p in parts if p))
        self._add_btn.setEnabled(bool(self._current_ticker))
        self._add_btn.setText("+ WATCHLIST")
        self._deep_dive_btn.setEnabled(bool(self._current_ticker))

    def _on_deep_dive(self) -> None:
        if self._current_ticker:
            self.deep_dive_clicked.emit(self._current_ticker)

    def _on_add_watchlist(self) -> None:
        if not self._current_ticker:
            return
        import logging
        from lens.db.store import add_to_watchlist, create_watchlist, upsert_security
        from lens.config import Config
        wl = Config().default_watchlist
        try:
            # Ensure security exists in DB before adding FK-constrained watchlist entry
            upsert_security(
                ticker=self._current_ticker,
                name=self._current_name,
                currency=self._current_currency,
            )
            create_watchlist(wl)
            add_to_watchlist(wl, self._current_ticker)
            self._add_btn.setText("✓ ADDED")
            logging.getLogger("lens").info(
                "Added %s to watchlist '%s'", self._current_ticker, wl
            )
            QTimer.singleShot(2500, lambda: self._add_btn.setText("+ WATCHLIST"))
        except Exception as e:
            logging.getLogger("lens").error(
                "Failed to add %s to watchlist: %s", self._current_ticker, e
            )


class PricePanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Large price + change
        row1 = QHBoxLayout()
        self._price = QLabel("—")
        self._price.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "font-size: 32px; font-weight: 700; color: #e8e8e8;"
        )
        self._change = QLabel()
        self._change.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "font-size: 16px; margin-left: 12px; margin-top: 14px;"
        )
        self._source = QLabel()
        self._source.setStyleSheet("font-size: 10px; color: #333333; margin-left: 8px; margin-top: 18px;")
        row1.addWidget(self._price)
        row1.addWidget(self._change)
        row1.addWidget(self._source)
        row1.addStretch()
        layout.addLayout(row1)

        # Detail row
        self._detail = QLabel()
        self._detail.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "font-size: 11px; color: #666666;"
        )
        layout.addWidget(self._detail)

    def update_quote(self, quote: dict) -> None:
        price = quote.get("price")
        change = quote.get("change")
        change_pct = quote.get("change_pct")
        color = "#22c55e" if (change and change > 0) else ("#ef4444" if (change and change < 0) else "#e8e8e8")

        self._price.setText(f"{price:,.2f}" if price else "—")
        self._price.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            f"font-size: 32px; font-weight: 700; color: {color};"
        )

        if change is not None:
            sign = "+" if change > 0 else ""
            pct_str = f"  ({sign}{change_pct:.2f}%)" if change_pct else ""
            self._change.setText(f"{sign}{change:,.2f}{pct_str}")
            self._change.setStyleSheet(
                'font-family: "JetBrains Mono", Consolas, monospace; '
                f"font-size: 16px; margin-left: 12px; margin-top: 14px; color: {color};"
            )

        src = quote.get("source", "yahoo")
        self._source.setText(f"via {src}")

        parts = []
        for k, v in [("O", "open"), ("H", "high"), ("L", "low"), ("Prev", "prev_close")]:
            val = quote.get(v)
            if val is not None:
                parts.append(f"{k} {val:,.2f}")
        if quote.get("bid") and quote.get("ask"):
            parts.append(f"Bid {quote['bid']:,.2f}")
            parts.append(f"Ask {quote['ask']:,.2f}")
        vol = quote.get("volume")
        if vol:
            parts.append(f"Vol {_large_num(vol, currency='').strip()}")
        self._detail.setText("   ·   ".join(parts))


class FundamentalsSection(QFrame):
    """A titled group of stat cards."""

    def __init__(self, title: str, fields: list, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hdr = QLabel(title.upper())
        hdr.setProperty("class", "section-header")
        hdr.setContentsMargins(0, 8, 0, 4)
        layout.addWidget(hdr)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._cards: dict[str, StatCard] = {}
        for field_def in fields:
            key = field_def[0]
            card = StatCard(key)
            self._cards[key] = card
            row.addWidget(card)
        layout.addLayout(row)

        self._fields = fields

    def update_data(self, fund: dict) -> None:
        for field_def in self._fields:
            key = field_def[0]
            col = field_def[1]
            mode = field_def[2] if len(field_def) > 2 else None
            card = self._cards.get(key)
            if card:
                card.set_value(_fmt_fund(fund.get(col), mode))


class QuoteScreen(QWidget):
    """Full-screen quote deep-dive."""

    open_deep_dive = pyqtSignal(str)  # emits ticker to open DeepDive tab

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._ticker: Optional[str] = None
        self._current_interval = ("1M", "1d", "1mo")
        self._workers: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QuoteHeader()
        self._header.deep_dive_clicked.connect(self.open_deep_dive)
        layout.addWidget(self._header)

        # Top row: price + interval bar
        top_row = QFrame()
        top_row.setProperty("class", "panel")
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self._price_panel = PricePanel()
        self._price_panel.setFixedWidth(500)
        top_layout.addWidget(self._price_panel)

        # Interval controls
        iv_frame = QFrame()
        iv_frame.setProperty("class", "panel")
        iv_layout = QHBoxLayout(iv_frame)
        iv_layout.setContentsMargins(12, 0, 12, 0)
        iv_layout.setSpacing(4)

        self._iv_buttons: list[QPushButton] = []
        self._btn_group: list = []
        for iv_label, *_ in INTERVALS:
            btn = QPushButton(iv_label)
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, lbl=iv_label: self._set_interval(lbl))
            iv_layout.addWidget(btn)
            self._iv_buttons.append(btn)

        iv_layout.addSpacing(16)

        # Candles / Line toggle
        for label in ("Candles", "Line"):
            btn = QPushButton(label)
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, m=label.lower(): self._set_mode(m))
            iv_layout.addWidget(btn)
            self._iv_buttons.append(btn)

        iv_layout.addSpacing(16)

        # SMA toggles
        for period in (20, 50, 200):
            btn = QPushButton(f"SMA{period}")
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda checked, p=period: self._chart.toggle_sma(p, checked)
            )
            iv_layout.addWidget(btn)

        iv_layout.addSpacing(16)

        # Log scale toggle
        log_btn = QPushButton("LOG")
        log_btn.setProperty("class", "interval-btn")
        log_btn.setCheckable(True)
        log_btn.setToolTip("Toggle logarithmic Y axis")
        log_btn.clicked.connect(lambda checked: self._chart.set_log_mode(checked))
        iv_layout.addWidget(log_btn)

        iv_layout.addStretch()
        top_layout.addWidget(iv_frame)
        layout.addWidget(top_row)

        # Mark default interval
        self._iv_buttons[2].setChecked(True)  # 1M
        self._iv_buttons[len(INTERVALS)].setChecked(True)  # Candles

        # Chart
        self._chart = ChartWidget()
        self._chart.setMinimumHeight(300)
        self._chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._chart)

        # Fundamentals scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(200)

        fund_widget = QWidget()
        fund_layout = QHBoxLayout(fund_widget)
        fund_layout.setContentsMargins(12, 8, 12, 8)
        fund_layout.setSpacing(16)

        self._fund_sections: list[FundamentalsSection] = []
        for section_title, fields in FUND_SECTIONS:
            section = FundamentalsSection(section_title, fields)
            fund_layout.addWidget(section)
            self._fund_sections.append(section)

        fund_layout.addStretch()
        scroll.setWidget(fund_widget)
        layout.addWidget(scroll)

        self._loading_label = QLabel("Enter a ticker to load a quote")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet("color: #555555; font-size: 14px;")

    def load_ticker(self, ticker: str) -> None:
        self._ticker = ticker.upper()
        self._load_all()

    def on_show(self) -> None:
        pass  # Quote screen waits for explicit load_ticker call

    def _load_all(self) -> None:
        if not self._ticker:
            return

        # Load security info from DB
        from lens.db.store import get_security_by_ticker
        sec = get_security_by_ticker(self._ticker)
        sec_data = dict(sec) if sec else {"ticker": self._ticker, "name": self._ticker}
        self._header.update(sec_data)

        # Clear stale fundamentals immediately so old ticker's data never persists
        self._on_fund_result({})

        # Fetch live quote
        self._load_quote()

        # Fetch chart
        self._load_chart()

        # Fetch fundamentals
        self._load_fundamentals()

    def _load_quote(self) -> None:
        from lens.ui.workers import FetchLiveQuoteWorker
        from lens.db.store import get_security_by_ticker
        sec = get_security_by_ticker(self._ticker)
        isin = sec["isin"] if sec else None
        mic  = sec["mic"]  if sec else "XPAR"

        worker = FetchLiveQuoteWorker(self._ticker, isin, mic, self)
        worker.result.connect(self._on_quote_result)
        worker.error.connect(lambda e: self._price_panel._detail.setText(f"Quote error: {e[:80]}"))
        worker.start()
        self._workers.append(worker)

    def _on_quote_result(self, quote: dict) -> None:
        self._price_panel.update_quote(quote)

    def _load_chart(self) -> None:
        from lens.ui.workers import FetchChartWorker
        _, yf_interval, yf_range = self._current_interval
        worker = FetchChartWorker(self._ticker, yf_interval, yf_range, self)
        worker.result.connect(self._chart.load_data)
        worker.error.connect(lambda e: None)
        worker.start()
        self._workers.append(worker)

    def _load_fundamentals(self) -> None:
        from lens.ui.workers import FetchFundamentalsWorker
        worker = FetchFundamentalsWorker(self._ticker, self)
        worker.result.connect(self._on_fund_result)
        worker.start()
        self._workers.append(worker)

    def _on_fund_result(self, fund: dict) -> None:
        for section in self._fund_sections:
            section.update_data(fund)

    def _set_interval(self, label: str) -> None:
        iv = next((i for i in INTERVALS if i[0] == label), None)
        if iv:
            self._current_interval = iv
            # Uncheck all interval buttons and check the selected one
            for i, (lbl, *_) in enumerate(INTERVALS):
                self._iv_buttons[i].setChecked(lbl == label)
            self._load_chart()

    def _set_mode(self, mode: str) -> None:
        self._chart.set_mode(mode)
        # Update button state
        modes = ["candles", "line"]
        for j, m in enumerate(modes):
            self._iv_buttons[len(INTERVALS) + j].setChecked(m == mode)
