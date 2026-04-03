"""DevLogs screen — live application log viewer for debugging."""

from __future__ import annotations

import html
import logging

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)


# ---------------------------------------------------------------------------
# Logging bridge: Python logging → Qt signal (thread-safe)
# ---------------------------------------------------------------------------

class _LogSignaller(QObject):
    new_record = pyqtSignal(str, str)   # (levelname, formatted_message)


_signaller = _LogSignaller()


class _AppHandler(logging.Handler):
    """Routes all Python log records to the DevLogs screen via Qt signal."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _signaller.new_record.emit(record.levelname, msg)
        except Exception:
            pass


# Install once on import
_handler = _AppHandler()
_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  —  %(message)s",
    datefmt="%H:%M:%S",
))
_root_logger = logging.getLogger()
_root_logger.addHandler(_handler)
_root_logger.setLevel(logging.DEBUG)

# Also capture lens-specific logger at DEBUG
logging.getLogger("lens").setLevel(logging.DEBUG)

# Silence noisy third-party loggers
for _noisy in ("httpx", "httpcore", "asyncio", "PIL"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# DevLogs screen
# ---------------------------------------------------------------------------

_LEVEL_COLORS = {
    "DEBUG":    "#444444",
    "INFO":     "#c8c8c8",
    "WARNING":  "#f59e0b",
    "ERROR":    "#ff3333",
    "CRITICAL": "#ff0000",
}

_MIN_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


class DevLogsScreen(QWidget):
    """Full-screen log viewer — all Python log records, color-coded by level."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._min_level = logging.DEBUG
        self._record_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(34)
        toolbar.setStyleSheet("background: #0d0d0d; border-bottom: 1px solid #f59e0b;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 0, 12, 0)
        tb_layout.setSpacing(12)

        title = QLabel("DEVLOGS  //  APPLICATION EVENT LOG")
        title.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 11px; font-weight: 700; color: #f59e0b; letter-spacing: 2px;"
        )
        tb_layout.addWidget(title)
        tb_layout.addStretch()

        level_lbl = QLabel("MIN LEVEL")
        level_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10px; color: #555555;"
        )
        tb_layout.addWidget(level_lbl)

        self._level_combo = QComboBox()
        self._level_combo.addItems(_MIN_LEVELS)
        self._level_combo.setCurrentText("DEBUG")
        self._level_combo.setFixedWidth(90)
        self._level_combo.currentTextChanged.connect(self._on_level_changed)
        tb_layout.addWidget(self._level_combo)

        self._count_label = QLabel("0 records")
        self._count_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10px; color: #444444;"
        )
        tb_layout.addWidget(self._count_label)

        clear_btn = QPushButton("CLEAR")
        clear_btn.setProperty("class", "interval-btn")
        clear_btn.clicked.connect(self._clear)
        tb_layout.addWidget(clear_btn)

        layout.addWidget(toolbar)

        # Log text area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log.setStyleSheet(
            "background-color: #000000;"
            "color: #c8c8c8;"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 11px;"
            "border: none;"
            "padding: 6px;"
        )
        layout.addWidget(self._log)

        # Connect signal
        _signaller.new_record.connect(self._on_record)

        # Initial marker
        logging.getLogger("lens.devlogs").info(
            "DevLogs initialized — capturing all application events"
        )

    def _on_level_changed(self, level_name: str) -> None:
        self._min_level = getattr(logging, level_name, logging.DEBUG)

    def _on_record(self, levelname: str, message: str) -> None:
        level_no = getattr(logging, levelname, logging.DEBUG)
        if level_no < self._min_level:
            return

        color = _LEVEL_COLORS.get(levelname, "#c8c8c8")
        escaped = html.escape(message)
        self._log.append(
            f'<span style="color: {color};">{escaped}</span>'
        )

        # Auto-scroll
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

        self._record_count += 1
        self._count_label.setText(f"{self._record_count} records")

    def _clear(self) -> None:
        self._log.clear()
        self._record_count = 0
        self._count_label.setText("0 records")

    def on_show(self) -> None:
        pass
