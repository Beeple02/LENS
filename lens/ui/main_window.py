"""Main application window for LENS."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lens.ui.sidebar import Sidebar
from lens.ui.widgets.search_bar import SearchBar


def _is_xpar_open() -> bool:
    from datetime import datetime
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(tz)
        if now.weekday() >= 5:
            return False
        open_t  = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
        close_t = now.replace(hour=17, minute=30, second=0, microsecond=0)
        return open_t <= now <= close_t
    except Exception:
        return False


class TopBar(QFrame):
    """40px top bar: wordmark | search | clock + market status."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "top-bar")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)

        # Wordmark
        wordmark = QLabel("LENS")
        wordmark.setProperty("class", "wordmark")
        wordmark.setFixedWidth(60)
        layout.addWidget(wordmark)

        layout.addStretch(1)

        # Search bar (center, 40% width)
        self._search = SearchBar()
        self._search.setFixedWidth(420)
        layout.addWidget(self._search)

        layout.addStretch(1)

        # Clock
        self._clock = QLabel()
        self._clock.setStyleSheet(
            'font-family: "JetBrains Mono", Consolas, monospace; '
            "color: #e8e8e8; font-size: 12px;"
        )
        self._clock.setFixedWidth(70)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Market status pill
        self._market = QLabel()
        self._market.setFixedWidth(100)
        self._market.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._market.setStyleSheet(
            "border-radius: 2px; padding: 2px 8px; font-size: 11px; font-weight: 700;"
        )

        layout.addWidget(self._clock)
        layout.addWidget(self._market)

        self._update_clock()
        self._update_market()

        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)

        market_timer = QTimer(self)
        market_timer.timeout.connect(self._update_market)
        market_timer.start(60_000)

    def _update_clock(self) -> None:
        from datetime import datetime
        self._clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_market(self) -> None:
        if _is_xpar_open():
            self._market.setText("● XPAR OPEN")
            self._market.setStyleSheet(
                "color: #22c55e; font-size: 11px; font-weight: 700; "
                "background: #0d1f0d; border: 1px solid #1a3a1a; border-radius: 2px; padding: 2px 8px;"
            )
        else:
            self._market.setText("○ XPAR CLOSED")
            self._market.setStyleSheet(
                "color: #555555; font-size: 11px; font-weight: 600; "
                "background: #111111; border: 1px solid #1e1e1e; border-radius: 2px; padding: 2px 8px;"
            )

    @property
    def search(self) -> SearchBar:
        return self._search


class MainWindow(QMainWindow):
    """Root window: top bar + sidebar + stacked content area."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._screens: dict[str, QWidget] = {}

        self.setWindowTitle("LENS — European Equity Terminal")
        self.setMinimumSize(1100, 700)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top bar
        self._top_bar = TopBar()
        root_layout.addWidget(self._top_bar)

        # Body: sidebar + content
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._sidebar = Sidebar()
        body_layout.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        body_layout.addWidget(self._stack)

        root_layout.addWidget(body)

        # Status bar
        self.statusBar().hide()

        # Wire navigation
        self._sidebar.screen_changed.connect(self._switch_screen)
        self._top_bar.search.ticker_selected.connect(self._open_quote)

        # Build and register all screens
        self._build_screens()

        # Start on dashboard
        self._switch_screen("dashboard")

    def _build_screens(self) -> None:
        from lens.ui.screens.dashboard import DashboardScreen
        from lens.ui.screens.quote import QuoteScreen
        from lens.ui.screens.portfolio import PortfolioScreen
        from lens.ui.screens.screener import ScreenerScreen
        from lens.ui.screens.chart import ChartScreen
        from lens.ui.screens.settings import SettingsScreen

        self._screens = {
            "dashboard": DashboardScreen(self._config),
            "quote":     QuoteScreen(self._config),
            "portfolio": PortfolioScreen(self._config),
            "screener":  ScreenerScreen(self._config),
            "chart":     ChartScreen(self._config),
            "settings":  SettingsScreen(self._config),
        }
        for screen in self._screens.values():
            self._stack.addWidget(screen)

    def _switch_screen(self, key: str) -> None:
        screen = self._screens.get(key)
        if screen:
            self._stack.setCurrentWidget(screen)
            self._sidebar.set_active(key)
            if hasattr(screen, "on_show"):
                screen.on_show()

    def _open_quote(self, ticker: str, name: str) -> None:
        quote_screen = self._screens.get("quote")
        if quote_screen:
            quote_screen.load_ticker(ticker)
            self._switch_screen("quote")
            self._sidebar.set_active("quote")

    def open_quote(self, ticker: str) -> None:
        """Public method for other screens to trigger quote navigation."""
        self._open_quote(ticker, ticker)

    def closeEvent(self, event) -> None:
        """Stop all running worker threads before closing."""
        from PyQt6.QtCore import QThread
        for screen in self._screens.values():
            for attr in vars(screen).values():
                if isinstance(attr, QThread) and attr.isRunning():
                    attr.quit()
                    attr.wait(500)
        event.accept()
