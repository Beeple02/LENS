"""StatCard widget — single metric display: big value + small label."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    """Displays one metric: a prominent value and a muted label below it."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        value_color: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "stat-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        self._value_label = QLabel(value)
        self._value_label.setProperty("class", "stat-value")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if value_color:
            self._value_label.setStyleSheet(f"color: {value_color};")

        self._meta_label = QLabel(label.upper())
        self._meta_label.setProperty("class", "stat-label")
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._value_label)
        layout.addWidget(self._meta_label)

    def set_value(self, value: str, color: Optional[str] = None) -> None:
        self._value_label.setText(value)
        if color:
            self._value_label.setStyleSheet(f"color: {color};")
        else:
            self._value_label.setStyleSheet("")

    def set_label(self, label: str) -> None:
        self._meta_label.setText(label.upper())
