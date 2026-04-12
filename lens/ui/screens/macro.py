"""Macro Dashboard screen — European morning overview."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

_log = logging.getLogger("lens.macro")

C_AMB  = "#f59e0b"
C_POS  = "#22c55e"
C_NEG  = "#ef4444"
C_DIM  = "#555555"
C_TEXT = "#c8c8c8"
C_BG   = "#000000"

_INDICES: list[tuple[str, str]] = [
    ("^FCHI",     "CAC 40"),
    ("^GDAXI",    "DAX"),
    ("^FTSE",     "FTSE 100"),
    ("^AEX",      "AEX"),
    ("^IBEX",     "IBEX 35"),
    ("^SSMI",     "SMI"),
    ("^STOXX50E", "EURO STOXX 50"),
]

_FX: list[tuple[str, str]] = [
    ("EURUSD=X", "EUR/USD"),
    ("EURGBP=X", "EUR/GBP"),
    ("EURCHF=X", "EUR/CHF"),
    ("EURJPY=X", "EUR/JPY"),
    ("EURCNH=X", "EUR/CNH"),
]

_COMMODITIES: list[tuple[str, str]] = [
    ("BZ=F",  "BRENT"),
    ("TTF=F", "TTF GAS"),
    ("GC=F",  "GOLD"),
    ("SI=F",  "SILVER"),
    ("HG=F",  "COPPER"),
]

_CHART_TICKERS: list[tuple[str, str]] = [
    ("^FCHI",     "CAC 40"),
    ("^GDAXI",    "DAX"),
    ("^STOXX50E", "EURO STOXX 50"),
]


def _pct_color(pct: Optional[float]) -> str:
    if pct is None:
        return C_DIM
    return C_POS if pct > 0 else (C_NEG if pct < 0 else C_TEXT)


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 10_000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:,.2f}"
    return f"{v:.4f}"


# ── Widgets ───────────────────────────────────────────────────────────────────

class _MacroCard(QFrame):
    """Compact stat card: label / value / change%."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")
        self.setMinimumWidth(130)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        self._lbl = QLabel(label.upper())
        self._lbl.setStyleSheet(
            f"color: {C_DIM}; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;"
        )

        self._value_lbl = QLabel("—")
        self._value_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 15px; "
            f"font-weight: 700; color: {C_DIM};"
        )

        self._change_lbl = QLabel("loading…")
        self._change_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 11px; color: {C_DIM};"
        )

        lay.addWidget(self._lbl)
        lay.addWidget(self._value_lbl)
        lay.addWidget(self._change_lbl)

    def set_data(
        self,
        value_str: str,
        pct: Optional[float],
        abs_change: Optional[float] = None,
    ) -> None:
        color = _pct_color(pct)
        self._value_lbl.setText(value_str)
        self._value_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 15px; "
            f"font-weight: 700; color: {color};"
        )
        if pct is not None:
            sign = "+" if pct > 0 else ""
            line = f"{sign}{pct:.2f}%"
            if abs_change is not None:
                sign2 = "+" if abs_change > 0 else ""
                line += f"  {sign2}{abs_change:,.2f}"
            self._change_lbl.setText(line)
            self._change_lbl.setStyleSheet(
                f"font-family: Consolas, monospace; font-size: 11px; color: {color};"
            )
        else:
            self._change_lbl.setText("—")
            self._change_lbl.setStyleSheet(
                f"font-family: Consolas, monospace; font-size: 11px; color: {C_DIM};"
            )


class _MiniChart(QFrame):
    """Single-ticker amber line chart."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {C_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )
        lay.addWidget(title_lbl)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(C_BG)
        self._plot.showAxis("top", False)
        self._plot.showAxis("right", False)
        for side in ("left", "bottom"):
            ax = self._plot.getAxis(side)
            ax.setStyle(tickFont=QFont("Consolas", 7))
            ax.setTextPen(pg.mkPen(C_DIM))
            ax.setPen(pg.mkPen("#1a1a1a"))
        self._plot.showGrid(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.hideButtons()
        self._plot.setMinimumHeight(150)
        lay.addWidget(self._plot)

    def set_data(self, bars: list[dict]) -> None:
        closes = [b["close"] for b in bars if b.get("close") is not None]
        if not closes:
            return
        xs = np.arange(len(closes), dtype=float)
        self._plot.clear()
        pen = pg.mkPen(color=QColor(C_AMB), width=1.5)
        self._plot.plot(xs, closes, pen=pen)
        # Sparse date ticks
        dates = [b["date"] for b in bars if b.get("close") is not None]
        step = max(1, len(dates) // 6)
        ticks = [(float(i), dates[i][:7]) for i in range(0, len(dates), step)]
        self._plot.getAxis("bottom").setTicks([ticks])


# ── Main screen ───────────────────────────────────────────────────────────────

class MacroScreen(QWidget):
    """European Macro Dashboard — indices, FX, commodities, index charts."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        self._lay = QVBoxLayout(content)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setSpacing(8)

        self._build_toolbar()
        self._build_ecb_banner()
        self._build_indices()
        self._build_fx()
        self._build_commodities()
        self._build_charts()
        self._lay.addStretch()

    # ── Layout builders ───────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        bar = QFrame()
        bar.setProperty("class", "panel")
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        title = QLabel("MACRO DASHBOARD")
        title.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 12px; "
            f"font-weight: 700; color: {C_AMB}; letter-spacing: 1px;"
        )
        lay.addWidget(title)
        lay.addStretch()

        self._ts_label = QLabel("Not yet loaded")
        self._ts_label.setStyleSheet(f"color: {C_DIM}; font-size: 11px;")
        lay.addWidget(self._ts_label)

        refresh_btn = QPushButton("↻  REFRESH")
        refresh_btn.setProperty("class", "primary")
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self._fetch)
        lay.addWidget(refresh_btn)

        self._lay.addWidget(bar)

    def _build_ecb_banner(self) -> None:
        banner = QFrame()
        banner.setProperty("class", "panel")
        banner.setFixedHeight(52)
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(0)

        lbl = QLabel("ECB DEPOSIT RATE")
        lbl.setStyleSheet(
            f"color: {C_DIM}; font-size: 12px; font-weight: 600; letter-spacing: 0.5px;"
        )
        lay.addWidget(lbl)

        self._ecb_value = QLabel("—")
        self._ecb_value.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 18px; "
            f"font-weight: 700; color: {C_AMB}; margin-left: 16px;"
        )
        lay.addWidget(self._ecb_value)

        self._ecb_ts = QLabel()
        self._ecb_ts.setStyleSheet(f"color: {C_DIM}; font-size: 10px; margin-left: 12px;")
        lay.addWidget(self._ecb_ts)
        lay.addStretch()

        self._lay.addWidget(banner)

    def _card_row(self, section_title: str, pairs: list[tuple[str, str]]) -> dict[str, _MacroCard]:
        """Build a titled section with a horizontal strip of MacroCards. Returns card map."""
        section = QWidget()
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(0, 0, 0, 0)
        sec_lay.setSpacing(4)

        hdr = QLabel(section_title)
        hdr.setStyleSheet(
            f"color: {C_DIM}; font-size: 9px; font-weight: 700; letter-spacing: 1px;"
        )
        sec_lay.addWidget(hdr)

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        cards: dict[str, _MacroCard] = {}
        for ticker, name in pairs:
            card = _MacroCard(name)
            cards[ticker] = card
            row_lay.addWidget(card)
        row_lay.addStretch()

        sec_lay.addWidget(row)
        self._lay.addWidget(section)
        return cards

    def _build_indices(self) -> None:
        self._index_cards = self._card_row("INDICES", _INDICES)

    def _build_fx(self) -> None:
        self._fx_cards = self._card_row("FX  (EUR BASE)", _FX)

    def _build_commodities(self) -> None:
        self._comm_cards = self._card_row("COMMODITIES", _COMMODITIES)

    def _build_charts(self) -> None:
        section = QWidget()
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(0, 0, 0, 0)
        sec_lay.setSpacing(4)

        hdr = QLabel("INDEX CHARTS  —  1 YEAR DAILY")
        hdr.setStyleSheet(
            f"color: {C_DIM}; font-size: 9px; font-weight: 700; letter-spacing: 1px;"
        )
        sec_lay.addWidget(hdr)

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        self._mini_charts: dict[str, _MiniChart] = {}
        for ticker, name in _CHART_TICKERS:
            chart = _MiniChart(name)
            self._mini_charts[ticker] = chart
            row_lay.addWidget(chart)

        sec_lay.addWidget(row)
        self._lay.addWidget(section)

    # ── Data ──────────────────────────────────────────────────────────────

    def on_show(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            self._fetch()

    def _fetch(self) -> None:
        from lens.ui.workers import FetchMacroWorker
        if self._worker:
            try:
                if self._worker.isRunning():
                    self._worker.terminate()
                    self._worker.wait()
            except RuntimeError:
                pass

        self._worker = FetchMacroWorker()
        self._worker.indices_ready.connect(self._on_indices)
        self._worker.fx_ready.connect(self._on_fx)
        self._worker.commodities_ready.connect(self._on_commodities)
        self._worker.ecb_rate_ready.connect(self._on_ecb)
        self._worker.charts_ready.connect(self._on_charts)
        self._worker.error.connect(lambda msg: _log.warning("MacroWorker: %s", msg))
        self._worker.start()

    def _on_ecb(self, rate: float) -> None:
        self._ecb_value.setText(f"{rate:.2f}%")
        self._ecb_ts.setText(f"updated {datetime.now().strftime('%H:%M')}")

    def _on_indices(self, data: dict) -> None:
        for ticker, _name in _INDICES:
            card = self._index_cards.get(ticker)
            if not card:
                continue
            q = data.get(ticker) or {}
            price = q.get("price")
            if price:
                card.set_data(_fmt_price(price), q.get("change_pct"), q.get("change"))
        self._bump_ts()

    def _on_fx(self, data: dict) -> None:
        for ticker, _name in _FX:
            card = self._fx_cards.get(ticker)
            if not card:
                continue
            q = data.get(ticker) or {}
            price = q.get("price")
            if price:
                card.set_data(f"{price:.4f}", q.get("change_pct"), q.get("change"))

    def _on_commodities(self, data: dict) -> None:
        for ticker, _name in _COMMODITIES:
            card = self._comm_cards.get(ticker)
            if not card:
                continue
            q = data.get(ticker) or {}
            price = q.get("price")
            if price:
                card.set_data(_fmt_price(price), q.get("change_pct"), q.get("change"))

    def _on_charts(self, data: dict) -> None:
        for ticker, _name in _CHART_TICKERS:
            chart = self._mini_charts.get(ticker)
            if chart and ticker in data:
                chart.set_data(data[ticker])

    def _bump_ts(self) -> None:
        self._ts_label.setText(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

    def cleanup(self) -> None:
        if self._worker:
            try:
                if self._worker.isRunning():
                    self._worker.terminate()
                    self._worker.wait()
            except RuntimeError:
                pass
            self._worker = None
