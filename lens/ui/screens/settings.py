"""Settings screen — edit ~/.lens/config.toml via a simple form."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SettingsScreen(QWidget):
    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QFrame()
        header.setProperty("class", "panel")
        header.setFixedHeight(40)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        title = QLabel("SETTINGS")
        title.setProperty("class", "section-header")
        h_layout.addWidget(title)
        outer.addWidget(header)

        # Content
        content = QFrame()
        content.setProperty("class", "panel")
        content.setMaximumWidth(560)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(20)

        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Default watchlist
        self._wl_combo = QComboBox()
        self._wl_combo.setMinimumWidth(200)
        form.addRow("Default watchlist:", self._wl_combo)

        # Default account
        self._acct_combo = QComboBox()
        form.addRow("Default account:", self._acct_combo)

        # Default currency
        self._currency = QLineEdit()
        self._currency.setPlaceholderText("EUR")
        self._currency.setMaximumWidth(80)
        form.addRow("Currency:", self._currency)

        # Refresh interval
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(10, 3600)
        self._refresh_spin.setSuffix("  seconds")
        self._refresh_spin.setMaximumWidth(140)
        form.addRow("Auto-refresh interval:", self._refresh_spin)

        # Default chart interval
        self._chart_interval = QComboBox()
        self._chart_interval.addItems(["1D", "1W", "1M", "3M", "1Y", "5Y"])
        self._chart_interval.setMaximumWidth(100)
        form.addRow("Default chart interval:", self._chart_interval)

        # Default benchmark
        self._benchmark = QLineEdit()
        self._benchmark.setPlaceholderText("^FCHI (CAC 40)")
        self._benchmark.setMaximumWidth(160)
        form.addRow("Default benchmark:", self._benchmark)

        content_layout.addLayout(form)

        # Save button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setProperty("class", "primary")
        save_btn.setFixedWidth(120)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        content_layout.addLayout(btn_row)

        self._status = QLabel()
        self._status.setStyleSheet("color: #22c55e; font-size: 12px;")
        content_layout.addWidget(self._status)
        content_layout.addStretch()

        outer.addWidget(content, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        outer.addStretch()

        self._load_values()

    def on_show(self) -> None:
        self._load_values()

    def _load_values(self) -> None:
        from lens.db.store import list_watchlists, list_accounts
        from lens.config import Config
        cfg = Config()

        # Watchlists
        self._wl_combo.clear()
        try:
            for wl in list_watchlists():
                self._wl_combo.addItem(wl["name"], wl["name"])
            idx = self._wl_combo.findData(cfg.default_watchlist)
            if idx >= 0:
                self._wl_combo.setCurrentIndex(idx)
        except Exception:
            pass

        # Accounts
        self._acct_combo.clear()
        try:
            for acct in list_accounts():
                self._acct_combo.addItem(acct["name"], acct["name"])
            idx = self._acct_combo.findData(cfg.default_account)
            if idx >= 0:
                self._acct_combo.setCurrentIndex(idx)
        except Exception:
            pass

        self._currency.setText(cfg.currency)
        self._refresh_spin.setValue(cfg.refresh_interval)
        self._benchmark.setText(
            self._config.get("portfolio", {}).get("default_benchmark", "^FCHI")
        )

    def _save(self) -> None:
        from lens.config import get_config_path

        config_path = get_config_path()
        new_config = f"""\
[general]
currency = "{self._currency.text() or 'EUR'}"
date_format = "%Y-%m-%d"
http_timeout = 10
cache_fundamentals_hours = 24

[watchlist]
default = "{self._wl_combo.currentData() or 'Main'}"

[portfolio]
default_account = "{self._acct_combo.currentData() or 'Main'}"
default_benchmark = "{self._benchmark.text() or '^FCHI'}"

[display]
refresh_interval = {self._refresh_spin.value()}
sparkline_days = 30
"""
        try:
            config_path.write_text(new_config)
            self._status.setText("Settings saved.")
            self._status.setStyleSheet("color: #22c55e; font-size: 12px;")
        except Exception as e:
            self._status.setText(f"Error: {e}")
            self._status.setStyleSheet("color: #ef4444; font-size: 12px;")
