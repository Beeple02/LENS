"""Price Alerts screen — view, create, and delete price alerts."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

C_AMB = "#f59e0b"
C_POS = "#22c55e"
C_NEG = "#ef4444"
C_DIM = "#555555"

_CONDITIONS = [
    ("price_above", "Price rises above"),
    ("price_below", "Price falls below"),
]


class _AddAlertDialog(QDialog):
    def __init__(self, ticker: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Price Alert")
        self.setMinimumWidth(320)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Ticker
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Ticker:"))
        self._ticker_edit = QLineEdit(ticker.upper())
        self._ticker_edit.setPlaceholderText("e.g. MC.PA")
        row1.addWidget(self._ticker_edit, 1)
        lay.addLayout(row1)

        # Condition
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Condition:"))
        self._cond_combo = QComboBox()
        for _, label in _CONDITIONS:
            self._cond_combo.addItem(label)
        row2.addWidget(self._cond_combo, 1)
        lay.addLayout(row2)

        # Threshold
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Price:"))
        self._thresh = QDoubleSpinBox()
        self._thresh.setRange(0.0, 1_000_000.0)
        self._thresh.setDecimals(4)
        self._thresh.setSingleStep(0.5)
        row3.addWidget(self._thresh, 1)
        lay.addLayout(row3)

        # Buttons
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add Alert")
        ok_btn.setProperty("class", "primary")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        lay.addLayout(btns)

    @property
    def ticker(self) -> str:
        return self._ticker_edit.text().strip().upper()

    @property
    def condition_type(self) -> str:
        return _CONDITIONS[self._cond_combo.currentIndex()][0]

    @property
    def threshold(self) -> float:
        return self._thresh.value()


class AlertsScreen(QWidget):
    """Full-screen alerts manager."""

    open_quote = pyqtSignal(str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QFrame()
        toolbar.setProperty("class", "panel")
        toolbar.setFixedHeight(48)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 0, 16, 0)
        tb.setSpacing(8)

        title = QLabel("PRICE ALERTS")
        title.setStyleSheet(
            "font-family: Consolas; font-size: 13px; font-weight: 700; "
            f"color: {C_AMB}; letter-spacing: 1px;"
        )
        tb.addWidget(title)
        tb.addStretch()

        add_btn = QPushButton("+ ADD ALERT")
        add_btn.setProperty("class", "primary")
        add_btn.clicked.connect(self._add_alert)
        tb.addWidget(add_btn)

        delete_btn = QPushButton("DELETE")
        delete_btn.setProperty("class", "interval-btn")
        delete_btn.clicked.connect(self._delete_selected)
        tb.addWidget(delete_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"font-size: 11px; color: {C_DIM};")
        tb.addWidget(self._status_lbl)

        layout.addWidget(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Ticker", "Condition", "Threshold", "Status", "Created"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.setStyleSheet(
            "QTableWidget { background: #000000; color: #c8c8c8; "
            "gridline-color: #1a1a1a; border: none; }"
            "QHeaderView::section { background: #111111; color: #888888; "
            "border: none; padding: 4px 8px; font-size: 10px; }"
        )
        layout.addWidget(self._table, 1)

        self._load_alerts()

    def on_show(self) -> None:
        self._load_alerts()

    def _load_alerts(self) -> None:
        from lens.db.store import get_all_alerts
        alerts = get_all_alerts()
        self._alert_ids: list[int] = []

        self._table.setRowCount(len(alerts))
        cond_labels = dict(_CONDITIONS)

        for row, alert in enumerate(alerts):
            self._alert_ids.append(alert["id"])
            ticker = alert["ticker"]
            cond   = cond_labels.get(alert["condition_type"], alert["condition_type"])
            thr    = f"{alert['threshold']:,.4f}"
            status = "Triggered" if alert["triggered"] else "Active"
            status_color = C_DIM if alert["triggered"] else C_POS
            created = alert.get("created_at", "")[:16]

            def _item(text, color="#c8c8c8"):
                it = QTableWidgetItem(text)
                it.setForeground(Qt.GlobalColor.white)
                from PyQt6.QtGui import QColor
                it.setForeground(QColor(color))
                return it

            self._table.setItem(row, 0, _item(ticker, C_AMB))
            self._table.setItem(row, 1, _item(cond))
            self._table.setItem(row, 2, _item(thr))
            self._table.setItem(row, 3, _item(status, status_color))
            self._table.setItem(row, 4, _item(created, C_DIM))

        self._status_lbl.setText(
            f"{sum(1 for a in alerts if not a['triggered'])} active alerts"
        )

    def _add_alert(self, ticker: str = "") -> None:
        dlg = _AddAlertDialog(ticker, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not dlg.ticker or dlg.threshold <= 0:
            return
        try:
            from lens.db.store import upsert_alert, upsert_security
            upsert_security(ticker=dlg.ticker, name=dlg.ticker)
            upsert_alert(dlg.ticker, dlg.condition_type, dlg.threshold)
            self._load_alerts()
        except Exception as e:
            self._status_lbl.setText(f"Error: {str(e)[:60]}")

    def add_alert_for_ticker(self, ticker: str) -> None:
        """Called from chart right-click menu — pre-fills the ticker."""
        self._add_alert(ticker)

    def _delete_selected(self) -> None:
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        if 0 <= row < len(self._alert_ids):
            from lens.db.store import delete_alert
            delete_alert(self._alert_ids[row])
            self._load_alerts()
