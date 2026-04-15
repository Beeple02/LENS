"""Reusable news feed widget — a scrollable list of headline rows."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

C_AMB  = "#f59e0b"
C_DIM  = "#555555"
C_TEXT = "#c8c8c8"
C_BG   = "#0d0d0d"


class _HeadlineRow(QFrame):
    def __init__(self, item: dict, parent=None) -> None:
        super().__init__(parent)
        self._url = item.get("link", "")
        self.setStyleSheet(
            "QFrame { background: #0d0d0d; border-bottom: 1px solid #1a1a1a; }"
            "QFrame:hover { background: #141414; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._url else Qt.CursorShape.ArrowCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(8)

        ts = QLabel(item.get("published", ""))
        ts.setStyleSheet(
            f"font-family: Consolas; font-size: 9px; color: {C_DIM}; "
            "min-width: 80px; max-width: 80px;"
        )
        ts.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(item.get("title", ""))
        title.setStyleSheet(f"font-size: 11px; color: {C_TEXT}; background: transparent;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        pub = QLabel(item.get("publisher", ""))
        pub.setStyleSheet(
            f"font-family: Consolas; font-size: 9px; color: {C_DIM}; "
            "min-width: 80px; max-width: 80px;"
        )
        pub.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        lay.addWidget(ts)
        lay.addWidget(title, 1)
        lay.addWidget(pub)

    def mousePressEvent(self, _evt) -> None:
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))


class NewsWidget(QFrame):
    """Scrollable news feed. Call load_news(items) to populate."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: #000000; border: none;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._container.setStyleSheet("background: #000000;")
        self._list_lay = QVBoxLayout(self._container)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(0)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._container)

        self._placeholder = QLabel("Loading news…")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {C_DIM}; font-size: 12px; padding: 20px;")
        self._list_lay.insertWidget(0, self._placeholder)

    def _clear_rows(self) -> None:
        to_delete = []
        for i in range(self._list_lay.count()):
            it = self._list_lay.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, _HeadlineRow):
                to_delete.append(w)
        for w in to_delete:
            self._list_lay.removeWidget(w)
            w.deleteLater()

    def load_news(self, items: list) -> None:
        self._clear_rows()
        if not items:
            self._placeholder.setText("No news available.")
            self._placeholder.show()
            return
        self._placeholder.hide()
        for it in items:
            row = _HeadlineRow(it)
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)

    def set_loading(self) -> None:
        self._clear_rows()
        self._placeholder.setText("Loading news…")
        self._placeholder.show()
