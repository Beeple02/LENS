"""Main application window for LENS — Bloomberg terminal layout."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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


def _market_clock(tz_name: str, fmt: str = "%H:%M") -> str:
    from datetime import datetime
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo(tz_name)).strftime(fmt)
    except Exception:
        return "--:--"


class TopBar(QFrame):
    """Bloomberg-style top bar: LENS | breadcrumb | search | market clocks | XPAR."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "top-bar")
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)

        # Wordmark
        wordmark = QLabel("LENS")
        wordmark.setProperty("class", "wordmark")
        layout.addWidget(wordmark)

        sep1 = QLabel("│")
        sep1.setProperty("class", "top-sep")
        layout.addWidget(sep1)

        # Breadcrumb / subtitle
        self._breadcrumb = QLabel("EUROPEAN EQUITY TERMINAL")
        self._breadcrumb.setProperty("class", "breadcrumb")
        layout.addWidget(self._breadcrumb)

        layout.addStretch(1)

        # Search bar
        self._search = SearchBar()
        self._search.setFixedWidth(380)
        layout.addWidget(self._search)

        layout.addStretch(1)

        # Market clocks
        self._lon_label = QLabel()
        self._lon_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 11px; color: #555555; padding-right: 2px;"
        )
        self._ny_label = QLabel()
        self._ny_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 11px; color: #555555; padding-right: 8px;"
        )

        sep2 = QLabel("│")
        sep2.setProperty("class", "top-sep")

        # Local clock
        self._clock = QLabel()
        self._clock.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 13px; font-weight: 700; color: #e8e8e8; padding: 0 8px;"
        )

        # XPAR status
        self._market = QLabel()
        self._market.setFixedWidth(110)
        self._market.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._lon_label)
        layout.addWidget(self._ny_label)
        layout.addWidget(sep2)
        layout.addWidget(self._clock)
        layout.addWidget(self._market)

        self._update_clocks()
        self._update_market()

        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clocks)
        clock_timer.start(1000)

        market_timer = QTimer(self)
        market_timer.timeout.connect(self._update_market)
        market_timer.start(60_000)

    def set_breadcrumb(self, text: str) -> None:
        self._breadcrumb.setText(text)

    def _update_clocks(self) -> None:
        from datetime import datetime
        self._clock.setText(datetime.now().strftime("%H:%M:%S"))
        self._lon_label.setText(f"LON {_market_clock('Europe/London')}")
        self._ny_label.setText(f"  NY {_market_clock('America/New_York')}")

    def _update_market(self) -> None:
        if _is_xpar_open():
            self._market.setText("● XPAR OPEN")
            self._market.setStyleSheet(
                "font-family: Consolas, 'Courier New', monospace;"
                "font-size: 10px; font-weight: 700; color: #00cc44;"
                "background: #001a00; border: 1px solid #004400;"
                "padding: 2px 8px;"
            )
        else:
            self._market.setText("○ XPAR CLOSED")
            self._market.setStyleSheet(
                "font-family: Consolas, 'Courier New', monospace;"
                "font-size: 10px; font-weight: 700; color: #444444;"
                "background: #0a0a0a; border: 1px solid #1a1a1a;"
                "padding: 2px 8px;"
            )

    @property
    def search(self) -> SearchBar:
        return self._search


# Ordered screen definitions: (display label, screen key)
_NAV_ITEMS = [
    ("DASHBOARD", "dashboard"),
    ("QUOTE",     "quote"),
    ("CHART",     "chart"),
    ("PORTFOLIO", "portfolio"),
    ("SCREENER",  "screener"),
    ("SETTINGS",  "settings"),
]

_FKEY_HINTS = [
    ("F1", "HELP"),
    ("ESC", "CLEAR"),
    ("F8", "REFRESH"),
]


class NavBar(QFrame):
    """Horizontal Bloomberg-style labeled tab bar."""

    screen_changed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "nav-bar")
        self.setFixedHeight(26)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons: list[tuple[str, QPushButton]] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for label, key in _NAV_ITEMS:
            btn = QPushButton(label)
            btn.setProperty("class", "nav-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, k=key: self.screen_changed.emit(k))
            self._group.addButton(btn)
            self._buttons.append((key, btn))
            layout.addWidget(btn)

        # Spacer pushes fkey hints to the right
        layout.addStretch(1)

        for key, label in _FKEY_HINTS:
            hint = QLabel(f"{key}:{label}")
            hint.setProperty("class", "fkey-hint")
            layout.addWidget(hint)

        layout.addSpacing(8)

        # Activate first
        self._buttons[0][1].setChecked(True)

    def set_active(self, key: str) -> None:
        for k, btn in self._buttons:
            btn.setChecked(k == key)


class MainWindow(QMainWindow):
    """Root window: top bar + nav bar + stacked content area."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._screens: dict[str, QWidget] = {}

        self.setWindowTitle("LENS  //  EUROPEAN EQUITY TERMINAL")
        self.setMinimumSize(1100, 700)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top bar
        self._top_bar = TopBar()
        root_layout.addWidget(self._top_bar)

        # Nav bar
        self._nav = NavBar()
        root_layout.addWidget(self._nav)

        # Content stack (full width — no sidebar)
        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)

        # Wire signals
        self._nav.screen_changed.connect(self._switch_screen)
        self._top_bar.search.ticker_selected.connect(self._open_quote)

        # Build screens
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
            self._nav.set_active(key)
            # Update breadcrumb
            label = next((l for l, k in _NAV_ITEMS if k == key), key.upper())
            self._top_bar.set_breadcrumb(f"EQUITY TERMINAL  ›  {label}")
            if hasattr(screen, "on_show"):
                screen.on_show()

    def _open_quote(self, ticker: str, name: str) -> None:
        quote_screen = self._screens.get("quote")
        if quote_screen:
            quote_screen.load_ticker(ticker)
            self._switch_screen("quote")

    def open_quote(self, ticker: str) -> None:
        """Public method for cross-screen quote navigation."""
        self._open_quote(ticker, ticker)

    def closeEvent(self, event) -> None:
        from PyQt6.QtCore import QThread
        for screen in self._screens.values():
            for attr in vars(screen).values():
                if isinstance(attr, QThread) and attr.isRunning():
                    attr.quit()
                    attr.wait(500)
        event.accept()
