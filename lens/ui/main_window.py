"""Main application window for LENS — dynamic browser-style tab layout."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lens.ui.widgets.search_bar import SearchBar

_TABS_FILE = Path.home() / ".lens" / "tabs.json"

# Screen types available from the + menu
_SCREEN_TYPES = [
    ("HOMEPAGE",  "homepage"),
    ("QUOTE",     "quote"),
    ("CHART",     "chart"),
    ("PORTFOLIO", "portfolio"),
    ("SCREENER",  "screener"),
    ("SETTINGS",  "settings"),
    ("DEVLOGS",   "devlogs"),
]

_DEFAULT_TABS = [
    {"id": "default-homepage", "type": "homepage", "label": "HOMEPAGE"},
]


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

        wordmark = QLabel("LENS")
        wordmark.setProperty("class", "wordmark")
        layout.addWidget(wordmark)

        sep1 = QLabel("│")
        sep1.setProperty("class", "top-sep")
        layout.addWidget(sep1)

        self._breadcrumb = QLabel("EUROPEAN EQUITY TERMINAL")
        self._breadcrumb.setProperty("class", "breadcrumb")
        layout.addWidget(self._breadcrumb)

        layout.addStretch(1)

        self._search = SearchBar()
        self._search.setFixedWidth(380)
        layout.addWidget(self._search)

        layout.addStretch(1)

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

        self._clock = QLabel()
        self._clock.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 13px; font-weight: 700; color: #e8e8e8; padding: 0 8px;"
        )

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


class DynamicTabBar(QFrame):
    """Browser-style scrollable tab bar with + button and × close buttons."""

    tab_changed       = pyqtSignal(int)   # index of activated tab
    tab_closed        = pyqtSignal(int)   # index of tab to close
    tab_add_requested = pyqtSignal(str)   # screen type key

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "nav-bar")
        self.setFixedHeight(32)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable area for tabs
        self._scroll = QScrollArea()
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(False)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._scroll.setFixedHeight(32)

        self._tab_container = QWidget()
        self._tab_container.setFixedHeight(32)
        self._tab_layout = QHBoxLayout(self._tab_container)
        self._tab_layout.setContentsMargins(0, 0, 0, 0)
        self._tab_layout.setSpacing(0)
        self._tab_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._tab_layout.addStretch(1)

        self._scroll.setWidget(self._tab_container)
        outer.addWidget(self._scroll, 1)

        # + button
        self._add_btn = QPushButton("+")
        self._add_btn.setProperty("class", "add-tab-btn")
        self._add_btn.setFixedSize(32, 32)
        self._add_btn.setToolTip("Add new tab")
        self._add_btn.clicked.connect(self._show_add_menu)
        outer.addWidget(self._add_btn)

        # Internal state: parallel lists of (frame, label_btn)
        self._tab_frames: list[QFrame] = []
        self._tab_btns:   list[QPushButton] = []
        self._active_idx: int = -1

    # ── Public API ────────────────────────────────────────────────────────

    def count(self) -> int:
        return len(self._tab_frames)

    def add_tab(self, label: str) -> int:
        """Append a new tab; return its index."""
        frame = QFrame()
        frame.setProperty("class", "tab-frame")
        frame.setFixedHeight(32)
        fl = QHBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        lbl_btn = QPushButton(label)
        lbl_btn.setProperty("class", "tab-btn")
        lbl_btn.setCheckable(True)
        lbl_btn.setFixedHeight(32)
        lbl_btn.setMinimumWidth(80)

        close_btn = QPushButton("×")
        close_btn.setProperty("class", "tab-close-btn")
        close_btn.setFixedSize(20, 32)

        fl.addWidget(lbl_btn)
        fl.addWidget(close_btn)

        # Insert before the trailing stretch
        insert_pos = self._tab_layout.count() - 1
        self._tab_layout.insertWidget(insert_pos, frame)

        idx = len(self._tab_frames)
        self._tab_frames.append(frame)
        self._tab_btns.append(lbl_btn)

        lbl_btn.clicked.connect(self._make_label_handler(lbl_btn))
        close_btn.clicked.connect(self._make_close_handler(frame))

        self._update_container_size()
        return idx

    def remove_tab(self, idx: int) -> None:
        if not (0 <= idx < len(self._tab_frames)):
            return
        frame = self._tab_frames.pop(idx)
        self._tab_btns.pop(idx)
        self._tab_layout.removeWidget(frame)
        frame.deleteLater()
        self._update_container_size()

    def set_active(self, idx: int) -> None:
        self._active_idx = idx
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == idx)

    def update_label(self, idx: int, label: str) -> None:
        if 0 <= idx < len(self._tab_btns):
            self._tab_btns[idx].setText(label)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _make_label_handler(self, btn: QPushButton):
        def _handler():
            try:
                idx = self._tab_btns.index(btn)
            except ValueError:
                return
            self.set_active(idx)
            self.tab_changed.emit(idx)
        return _handler

    def _make_close_handler(self, frame: QFrame):
        def _handler():
            try:
                idx = self._tab_frames.index(frame)
            except ValueError:
                return
            self.tab_closed.emit(idx)
        return _handler

    def _update_container_size(self) -> None:
        # Shrink-wrap the container to its minimum content width
        self._tab_container.adjustSize()

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        for label, key in _SCREEN_TYPES:
            menu.addAction(label, lambda k=key: self.tab_add_requested.emit(k))
        menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))


class MainWindow(QMainWindow):
    """Root window: top bar + dynamic tab bar + stacked content area."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        # Each entry: {"id", "type", "label", "ticker", "screen"}
        self._tab_data: list[dict] = []

        self.setWindowTitle("LENS  //  EUROPEAN EQUITY TERMINAL")
        self.setMinimumSize(1100, 700)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._top_bar = TopBar()
        root_layout.addWidget(self._top_bar)

        self._tab_bar = DynamicTabBar()
        root_layout.addWidget(self._tab_bar)

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)

        self._tab_bar.tab_changed.connect(self._on_tab_changed)
        self._tab_bar.tab_closed.connect(self._on_tab_closed)
        self._tab_bar.tab_add_requested.connect(self._add_tab)
        self._top_bar.search.ticker_selected.connect(self._open_quote)

        self._restore_tabs()

    # ── Screen factory ────────────────────────────────────────────────────

    def _make_screen(self, screen_type: str) -> QWidget:
        if screen_type == "homepage":
            from lens.ui.screens.homepage import HomepageScreen
            return HomepageScreen(self._config)
        if screen_type == "quote":
            from lens.ui.screens.quote import QuoteScreen
            return QuoteScreen(self._config)
        if screen_type == "chart":
            from lens.ui.screens.chart import ChartScreen
            return ChartScreen(self._config)
        if screen_type == "portfolio":
            from lens.ui.screens.portfolio import PortfolioScreen
            return PortfolioScreen(self._config)
        if screen_type == "screener":
            from lens.ui.screens.screener import ScreenerScreen
            return ScreenerScreen(self._config)
        if screen_type == "settings":
            from lens.ui.screens.settings import SettingsScreen
            return SettingsScreen(self._config)
        if screen_type == "devlogs":
            from lens.ui.screens.devlogs import DevLogsScreen
            return DevLogsScreen(self._config)
        placeholder = QLabel(f"Unknown screen: {screen_type}")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return placeholder

    # ── Tab management ────────────────────────────────────────────────────

    def _add_tab(
        self,
        screen_type: str,
        label: Optional[str] = None,
        ticker: Optional[str] = None,
        tab_id: Optional[str] = None,
        activate: bool = True,
        save: bool = True,
    ) -> int:
        if label is None:
            label = screen_type.upper()
        if tab_id is None:
            tab_id = str(uuid.uuid4())[:8]

        screen = self._make_screen(screen_type)
        self._stack.addWidget(screen)

        tab_idx = self._tab_bar.add_tab(label)
        self._tab_data.append({
            "id":     tab_id,
            "type":   screen_type,
            "label":  label,
            "ticker": ticker,
            "screen": screen,
        })

        if ticker and hasattr(screen, "load_ticker"):
            screen.load_ticker(ticker)

        if activate:
            self._tab_bar.set_active(tab_idx)
            self._stack.setCurrentWidget(screen)
            self._update_breadcrumb(tab_idx)
            if hasattr(screen, "on_show"):
                screen.on_show()

        if save:
            self._save_tabs()

        return tab_idx

    def _on_tab_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._tab_data):
            screen = self._tab_data[idx]["screen"]
            self._stack.setCurrentWidget(screen)
            self._update_breadcrumb(idx)
            if hasattr(screen, "on_show"):
                screen.on_show()

    def _on_tab_closed(self, idx: int) -> None:
        if len(self._tab_data) <= 1:
            return  # never close the last tab

        tab = self._tab_data.pop(idx)
        screen = tab["screen"]
        self._stack.removeWidget(screen)
        screen.deleteLater()
        self._tab_bar.remove_tab(idx)

        # Activate the nearest remaining tab
        new_idx = min(idx, len(self._tab_data) - 1)
        if new_idx >= 0:
            self._tab_bar.set_active(new_idx)
            self._on_tab_changed(new_idx)

        self._save_tabs()

    def _update_breadcrumb(self, idx: int) -> None:
        if 0 <= idx < len(self._tab_data):
            label = self._tab_data[idx]["label"]
            self._top_bar.set_breadcrumb(f"EQUITY TERMINAL  ›  {label}")

    # ── Search → quote navigation ─────────────────────────────────────────

    def _open_quote(self, ticker: str, name: str) -> None:
        ticker = ticker.upper()

        # 1. Re-use an existing Quote tab that already shows this ticker
        for i, tab in enumerate(self._tab_data):
            if tab["type"] == "quote" and tab.get("ticker") == ticker:
                self._tab_bar.set_active(i)
                self._on_tab_changed(i)
                return

        # 2. Re-use the first empty Quote tab
        for i, tab in enumerate(self._tab_data):
            if tab["type"] == "quote" and not tab.get("ticker"):
                tab["ticker"] = ticker
                tab["label"] = ticker
                self._tab_bar.update_label(i, ticker)
                self._tab_bar.set_active(i)
                self._stack.setCurrentWidget(tab["screen"])
                self._update_breadcrumb(i)
                tab["screen"].load_ticker(ticker)
                if hasattr(tab["screen"], "on_show"):
                    tab["screen"].on_show()
                self._save_tabs()
                return

        # 3. Create a new Quote tab
        self._add_tab("quote", label=ticker, ticker=ticker)

    def open_quote(self, ticker: str) -> None:
        """Public method for cross-screen quote navigation."""
        self._open_quote(ticker, ticker)

    # ── Persistence ───────────────────────────────────────────────────────

    def _restore_tabs(self) -> None:
        tabs_data: list[dict] = []
        if _TABS_FILE.exists():
            try:
                with open(_TABS_FILE) as f:
                    tabs_data = json.load(f)
            except Exception:
                pass

        if not tabs_data:
            tabs_data = list(_DEFAULT_TABS)

        for tab in tabs_data:
            self._add_tab(
                tab.get("type", "homepage"),
                label=tab.get("label"),
                ticker=tab.get("ticker"),
                tab_id=tab.get("id"),
                activate=False,
                save=False,
            )

        # Activate and show first tab
        if self._tab_data:
            self._tab_bar.set_active(0)
            self._on_tab_changed(0)

        self._save_tabs()

    def _save_tabs(self) -> None:
        _TABS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "id":     t["id"],
                "type":   t["type"],
                "label":  t["label"],
                "ticker": t.get("ticker"),
            }
            for t in self._tab_data
        ]
        try:
            with open(_TABS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── Cleanup ───────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        from PyQt6.QtCore import QThread
        for tab in self._tab_data:
            screen = tab["screen"]
            for attr in vars(screen).values():
                if isinstance(attr, QThread) and attr.isRunning():
                    attr.quit()
                    attr.wait(500)
        event.accept()
