"""PriceLabel widget — colour-coded price with change display."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

COLOR_POS = "#22c55e"
COLOR_NEG = "#ef4444"
COLOR_NEU = "#e8e8e8"
COLOR_DIM = "#666666"
COLOR_AMB = "#f59e0b"

MONO_STYLE = (
    'font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;'
)


def _change_color(change: Optional[float]) -> str:
    if change is None or change == 0:
        return COLOR_NEU
    return COLOR_POS if change > 0 else COLOR_NEG


def fmt_price(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def fmt_change(change: Optional[float], pct: Optional[float] = None) -> str:
    if change is None:
        return "—"
    sign = "+" if change > 0 else ""
    s = f"{sign}{change:,.2f}"
    if pct is not None:
        ps = "+" if pct > 0 else ""
        s += f"  ({ps}{pct:.2f}%)"
    return s


class PriceLabel(QWidget):
    """Shows price + change/change_pct side by side, color-coded."""

    def __init__(
        self,
        price: Optional[float] = None,
        change: Optional[float] = None,
        change_pct: Optional[float] = None,
        large: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._price_lbl = QLabel()
        self._price_lbl.setProperty("class", "price-large" if large else "price-normal")

        self._change_lbl = QLabel()
        self._change_lbl.setProperty("class", "price-normal")
        font_size = "16px" if large else "13px"
        self._change_lbl.setStyleSheet(f"{MONO_STYLE} font-size: {font_size};")

        layout.addWidget(self._price_lbl)
        layout.addWidget(self._change_lbl)
        layout.addStretch()

        self.update_price(price, change, change_pct)

    def update_price(
        self,
        price: Optional[float],
        change: Optional[float] = None,
        change_pct: Optional[float] = None,
    ) -> None:
        color = _change_color(change)
        self._price_lbl.setText(fmt_price(price))
        self._price_lbl.setStyleSheet(f"{MONO_STYLE} color: {color};")

        if change is not None:
            self._change_lbl.setText(fmt_change(change, change_pct))
            self._change_lbl.setStyleSheet(f"{MONO_STYLE} color: {color}; font-size: 13px;")
            self._change_lbl.show()
        else:
            self._change_lbl.hide()
