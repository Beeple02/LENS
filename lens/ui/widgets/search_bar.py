"""Global search bar with live dropdown results."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SearchBar(QWidget):
    """
    Search input with debounced live dropdown.
    Emits `ticker_selected(ticker, name)` when the user picks a result.
    """

    ticker_selected = pyqtSignal(str, str)  # ticker, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Container holds both the input and the dropdown overlay
        self._container = QFrame(self)
        self._container.setFixedHeight(32)
        inner = QHBoxLayout(self._container)
        inner.setContentsMargins(0, 0, 0, 0)

        self._icon = QLabel("⌕")
        self._icon.setFixedWidth(28)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("color: #666666; font-size: 16px; background: transparent;")

        self._input = QLineEdit()
        self._input.setProperty("class", "search")
        self._input.setPlaceholderText("Search ticker or company…")
        self._input.setClearButtonEnabled(True)

        inner.addWidget(self._icon)
        inner.addWidget(self._input)
        layout.addWidget(self._container)

        # Dropdown list (shown below the bar)
        self._dropdown = QListWidget()
        self._dropdown.setFixedWidth(400)
        self._dropdown.setMaximumHeight(280)
        self._dropdown.hide()
        self._dropdown.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self._dropdown.setFocusProxy(self._input)

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)

        self._worker = None
        self._results: list[dict] = []

        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_return)
        self._dropdown.itemClicked.connect(self._on_item_clicked)

    def _on_text_changed(self, text: str) -> None:
        if len(text) < 2:
            self._dropdown.hide()
            return
        self._debounce.start(350)

    def _do_search(self) -> None:
        query = self._input.text().strip()
        if len(query) < 2:
            return

        from lens.ui.workers import SearchWorker
        if self._worker and self._worker.isRunning():
            self._worker.quit()

        self._worker = SearchWorker(query, self)
        self._worker.result.connect(self._on_results)
        self._worker.start()

    def _on_results(self, results: list) -> None:
        self._results = results
        self._dropdown.clear()

        for r in results[:12]:
            ticker = r.get("ticker", "")
            name = r.get("name", "")
            exchange = r.get("exchange", "")
            item = QListWidgetItem(f"{ticker:<12}  {name[:35]}  {exchange}")
            item.setData(Qt.ItemDataRole.UserRole, (ticker, name))
            self._dropdown.addItem(item)

        if self._dropdown.count() == 0:
            self._dropdown.hide()
            return

        # Position below the input
        pos = self._input.mapToGlobal(self._input.rect().bottomLeft())
        self._dropdown.move(pos)
        self._dropdown.show()
        self._dropdown.raise_()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            ticker, name = data
            self._input.clear()
            self._dropdown.hide()
            self.ticker_selected.emit(ticker, name)

    def _on_return(self) -> None:
        text = self._input.text().strip().upper()
        if text:
            self._input.clear()
            self._dropdown.hide()
            self.ticker_selected.emit(text, text)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._dropdown.hide()
            self._input.clear()
        elif event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            if not self._dropdown.isHidden():
                self._dropdown.setFocus()
        super().keyPressEvent(event)
