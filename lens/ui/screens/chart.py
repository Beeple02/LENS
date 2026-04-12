"""Full-screen chart screen."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lens.ui.widgets.chart_widget import ChartWidget

INTERVALS = [
    ("1D",  "5m",  "1d"),
    ("1W",  "1h",  "5d"),
    ("1M",  "1d",  "1mo"),
    ("3M",  "1d",  "3mo"),
    ("1Y",  "1d",  "1y"),
    ("5Y",  "1wk", "5y"),
    ("MAX", "1wk", "max"),
]

CHART_TYPES = ["Candles", "Line", "Area"]
SMA_PERIODS = [20, 50, 200]


class ChartScreen(QWidget):
    open_quote     = pyqtSignal(str)
    open_deep_dive = pyqtSignal(str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._ticker: Optional[str] = None
        self._current_interval = INTERVALS[4]  # default 1Y
        self._worker = None
        self._events_worker = None
        self._mode = "candles"
        self._events_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QFrame()
        toolbar.setProperty("class", "panel")
        toolbar.setFixedHeight(48)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 6, 12, 6)
        tb_layout.setSpacing(8)

        # Ticker input
        self._ticker_input = QLineEdit()
        self._ticker_input.setPlaceholderText("Ticker (e.g. MC.PA)")
        self._ticker_input.setFixedWidth(140)
        self._ticker_input.returnPressed.connect(self._on_ticker_enter)
        tb_layout.addWidget(self._ticker_input)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #222222;")
        tb_layout.addWidget(sep1)

        # Interval buttons
        self._iv_btns: list[QPushButton] = []
        for iv_label, *_ in INTERVALS:
            btn = QPushButton(iv_label)
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, lbl=iv_label: self._set_interval(lbl))
            tb_layout.addWidget(btn)
            self._iv_btns.append(btn)
        self._iv_btns[4].setChecked(True)  # 1Y

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #222222;")
        tb_layout.addWidget(sep2)

        # Chart type
        self._type_btns: list[QPushButton] = []
        for ct in CHART_TYPES:
            btn = QPushButton(ct)
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, m=ct.lower(): self._set_mode(m))
            tb_layout.addWidget(btn)
            self._type_btns.append(btn)
        self._type_btns[0].setChecked(True)  # Candles

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("color: #222222;")
        tb_layout.addWidget(sep3)

        # SMA toggles
        self._sma_btns: list[QPushButton] = []
        for period in SMA_PERIODS:
            btn = QPushButton(f"SMA{period}")
            btn.setProperty("class", "interval-btn")
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda checked, p=period: self._chart.toggle_sma(p, checked)
            )
            tb_layout.addWidget(btn)
            self._sma_btns.append(btn)

        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.VLine)
        sep4.setStyleSheet("color: #222222;")
        tb_layout.addWidget(sep4)

        log_btn = QPushButton("LOG")
        log_btn.setProperty("class", "interval-btn")
        log_btn.setCheckable(True)
        log_btn.setToolTip("Toggle logarithmic Y axis")
        log_btn.clicked.connect(lambda checked: self._chart.set_log_mode(checked))
        tb_layout.addWidget(log_btn)

        sep5 = QFrame()
        sep5.setFrameShape(QFrame.Shape.VLine)
        sep5.setStyleSheet("color: #222222;")
        tb_layout.addWidget(sep5)

        self._events_btn = QPushButton("EVENTS")
        self._events_btn.setProperty("class", "interval-btn")
        self._events_btn.setCheckable(True)
        self._events_btn.setToolTip("Toggle earnings & ECB event overlay")
        self._events_btn.clicked.connect(self._on_events_toggled)
        tb_layout.addWidget(self._events_btn)

        tb_layout.addStretch()

        self._ticker_label = QLabel()
        self._ticker_label.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "color: #f59e0b; font-size: 13px; font-weight: 700;"
        )
        tb_layout.addWidget(self._ticker_label)

        layout.addWidget(toolbar)

        # Chart
        self._chart = ChartWidget()
        self._chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._chart.open_quote.connect(self.open_quote)
        self._chart.open_deep_dive.connect(self.open_deep_dive)
        self._chart.interval_change_requested.connect(self._set_interval)
        layout.addWidget(self._chart)

        self._placeholder = QLabel("Enter a ticker above to load a chart")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #444444; font-size: 14px;")
        layout.addWidget(self._placeholder)
        self._placeholder.hide()

    def on_show(self) -> None:
        self._ticker_input.setFocus()

    def load_ticker(self, ticker: str) -> None:
        self._ticker = ticker.upper()
        self._ticker_input.setText(self._ticker)
        self._ticker_label.setText(self._ticker)
        self._chart.set_ticker(self._ticker)
        self._fetch_chart()

    def _on_ticker_enter(self) -> None:
        ticker = self._ticker_input.text().strip().upper()
        if ticker:
            self.load_ticker(ticker)

    def _set_interval(self, label: str) -> None:
        iv = next((i for i in INTERVALS if i[0] == label), None)
        if iv:
            self._current_interval = iv
            for i, (lbl, *_) in enumerate(INTERVALS):
                self._iv_btns[i].setChecked(lbl == label)
            self._chart.set_current_interval_label(label)
            if self._ticker:
                self._fetch_chart()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self._chart.set_mode(mode)
        modes = [ct.lower() for ct in CHART_TYPES]
        for i, m in enumerate(modes):
            self._type_btns[i].setChecked(m == mode)

    def _fetch_chart(self) -> None:
        if not self._ticker:
            return

        from lens.ui.workers import FetchChartWorker

        if self._worker and self._worker.isRunning():
            self._worker.quit()

        _, yf_interval, yf_range = self._current_interval
        self._worker = FetchChartWorker(self._ticker, yf_interval, yf_range, self)
        self._worker.result.connect(self._on_chart_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_chart_result(self, data: list) -> None:
        if data:
            self._chart.load_data(data)
            self._chart.set_mode(self._mode)
        else:
            self._placeholder.setText(f"No chart data for {self._ticker}")
            self._placeholder.show()

    def _on_error(self, msg: str) -> None:
        self._placeholder.setText(f"Error loading chart: {msg[:80]}")
        self._placeholder.show()

    def _on_events_toggled(self, checked: bool) -> None:
        self._events_active = checked
        if checked and self._ticker:
            from lens.ui.workers import FetchTickerEventsWorker
            if self._events_worker and self._events_worker.isRunning():
                return
            self._events_worker = FetchTickerEventsWorker(self._ticker, self)
            self._events_worker.events_ready.connect(self._on_events_ready)
            self._events_worker.start()
        else:
            self._chart.toggle_events(False)

    def _on_events_ready(self, data: dict) -> None:
        self._chart.set_events_data(
            data.get("earnings_past", []),
            data.get("earnings_next"),
        )
        self._chart.toggle_events(self._events_active)
