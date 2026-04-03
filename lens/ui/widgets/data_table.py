"""Base styled DataTable (QTableWidget) for LENS."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

MONO = "JetBrains Mono, Cascadia Code, Consolas, monospace"
COLOR_POS = "#22c55e"
COLOR_NEG = "#ef4444"
COLOR_AMB = "#f59e0b"
COLOR_DIM = "#666666"
COLOR_TEXT = "#e8e8e8"
COLOR_MUTED = "#94a3b8"


def _item(
    text: str,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    color: Optional[str] = None,
    mono: bool = False,
    bold: bool = False,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    item.setTextAlignment(align)
    if color:
        item.setForeground(QColor(color))
    if mono or bold:
        font = QFont()
        if mono:
            font.setFamily(MONO)
            font.setPointSize(10)
        if bold:
            font.setBold(True)
        item.setFont(font)
    return item


def _num_item(
    value: Optional[float],
    decimals: int = 2,
    color: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    show_sign: bool = False,
) -> QTableWidgetItem:
    if value is None:
        text = "—"
        c = COLOR_DIM
    else:
        sign = "+" if (show_sign and value > 0) else ""
        text = f"{prefix}{sign}{value:,.{decimals}f}{suffix}"
        if color:
            c = color
        elif show_sign:
            c = COLOR_POS if value > 0 else (COLOR_NEG if value < 0 else COLOR_TEXT)
        else:
            c = COLOR_TEXT

    return _item(
        text,
        align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        color=c,
        mono=True,
    )


def _large_num(value: Optional[float], currency: str = "€") -> str:
    if value is None:
        return "—"
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}{currency}{abs_v / 1e12:.2f}T"
    elif abs_v >= 1e9:
        return f"{sign}{currency}{abs_v / 1e9:.2f}B"
    elif abs_v >= 1e6:
        return f"{sign}{currency}{abs_v / 1e6:.2f}M"
    elif abs_v >= 1e3:
        return f"{sign}{currency}{abs_v / 1e3:.1f}K"
    return f"{sign}{currency}{abs_v:.2f}"


class DataTable(QTableWidget):
    """Base styled table widget with sensible defaults for financial data."""

    def __init__(
        self,
        columns: list[str],
        parent=None,
    ) -> None:
        super().__init__(0, len(columns), parent)

        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.verticalHeader().setDefaultSectionSize(28)

    def clear_rows(self) -> None:
        self.setRowCount(0)

    def set_row_count(self, n: int) -> None:
        self.setRowCount(n)
