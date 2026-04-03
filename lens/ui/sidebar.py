"""Left navigation sidebar for LENS."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QPushButton, QVBoxLayout, QWidget

# (icon_unicode, label, screen_key)
NAV_ITEMS = [
    ("⊞", "Dashboard",  "dashboard"),
    ("◈", "Quote",       "quote"),
    ("⬡", "Portfolio",  "portfolio"),
    ("⧖", "Screener",   "screener"),
    ("⬲", "Chart",      "chart"),
]
SETTINGS_ITEM = ("⚙", "Settings", "settings")


class NavButton(QPushButton):
    def __init__(self, icon: str, tooltip: str) -> None:
        super().__init__(icon)
        self.setProperty("class", "nav-btn")
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Sidebar(QFrame):
    """60px icon-only sidebar. Emits `screen_changed(screen_key)` on click."""

    screen_changed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "sidebar")
        self.setFixedWidth(60)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._key_map: dict[NavButton, str] = {}

        for icon, label, key in NAV_ITEMS:
            btn = NavButton(icon, label)
            self._group.addButton(btn)
            self._key_map[btn] = key
            btn.clicked.connect(self._on_click)
            outer.addWidget(btn)

        outer.addStretch()

        # Settings at bottom
        icon, label, key = SETTINGS_ITEM
        self._settings_btn = NavButton(icon, label)
        self._group.addButton(self._settings_btn)
        self._key_map[self._settings_btn] = key
        self._settings_btn.clicked.connect(self._on_click)
        outer.addWidget(self._settings_btn)

        # Select dashboard by default
        first = list(self._key_map.keys())[0]
        first.setChecked(True)
        self._update_active()

    def _on_click(self) -> None:
        btn = self.sender()
        key = self._key_map.get(btn)
        if key:
            self._update_active()
            self.screen_changed.emit(key)

    def _update_active(self) -> None:
        for btn, _ in self._key_map.items():
            checked = btn.isChecked()
            btn.setProperty("active", "true" if checked else "false")
            # Force style refresh
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_active(self, key: str) -> None:
        for btn, k in self._key_map.items():
            if k == key:
                btn.setChecked(True)
        self._update_active()
