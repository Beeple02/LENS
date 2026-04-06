"""Deep Dive screen — comprehensive per-security analysis across 6 tabs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QHeaderView, QAbstractItemView,
)

from lens.ui.widgets.stat_card import StatCard

# ── Palette ────────────────────────────────────────────────────────────────
C_AMB   = "#f59e0b"
C_POS   = "#22c55e"
C_POS2  = "#4ade80"
C_NEG   = "#ef4444"
C_NEG2  = "#f87171"
C_DIM   = "#666666"
C_TEXT  = "#c8c8c8"
C_BG    = "#000000"
C_SURF  = "#0d0d0d"
C_ROW_A = "#111111"
C_ROW_B = "#0f0f0f"


# ── Shared utilities ────────────────────────────────────────────────────────

def _sf(val: Any) -> Optional[float]:
    """Safe float extraction from Yahoo raw/fmt dicts or plain values."""
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("raw")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fmt_large(v: Optional[float], currency: str = "€") -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1e9:
        return f"{sign}{currency}{av / 1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}{currency}{av / 1e6:,.0f}M"
    return f"{sign}{currency}{av:,.0f}"


def _fmt_pct(v: Optional[float], multiplier: bool = False) -> str:
    if v is None:
        return "—"
    if multiplier:
        v = v * 100
    return f"{v:.2f}%"


def _fmt_ratio(v: Optional[float]) -> str:
    return f"{v:.2f}x" if v is not None else "—"


def _fmt_plain(v: Optional[float], decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}" if v is not None else "—"


def _fmt_date(ts: Any) -> str:
    if ts is None:
        return "—"
    try:
        ts = _sf(ts) if isinstance(ts, dict) else float(ts)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "—"


def _days_until(ts: Any) -> str:
    try:
        ts_val = _sf(ts) if isinstance(ts, dict) else float(ts)
        delta = datetime.fromtimestamp(ts_val, tz=timezone.utc).date() - datetime.now(timezone.utc).date()
        if delta.days < 0:
            return "passed"
        return f"in {delta.days}d"
    except Exception:
        return ""


def _loading_lbl() -> QLabel:
    lbl = QLabel("Loading…")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("color: #666666; font-size: 13px;")
    return lbl


def _error_lbl() -> QLabel:
    lbl = QLabel(
        "Could not load data.\nYahoo Finance may be rate-limiting or "
        "this security may not have this data type available."
    )
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #ef4444; font-size: 12px; padding: 24px;")
    return lbl


def _pg_plot(title: str = "") -> pg.PlotItem:
    """Minimally styled pyqtgraph PlotItem."""
    pw = pg.PlotWidget(title=title)
    pw.setBackground(C_BG)
    pw.showGrid(x=False, y=True, alpha=0.08)
    pw.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
    pw.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
    pw.getAxis("bottom").setTextPen(pg.mkPen(C_DIM))
    pw.getAxis("left").setTextPen(pg.mkPen(C_DIM))
    pw.setMenuEnabled(False)
    pw.hideButtons()
    return pw


_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
_C = Qt.AlignmentFlag.AlignCenter


def _twi(text: str, align=None, color: Optional[str] = None,
          bold: bool = False, mono: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if align:
        item.setTextAlignment(align)
    if color:
        item.setForeground(QColor(color))
    if bold or mono:
        f = QFont()
        if bold:
            f.setBold(True)
        if mono:
            f.setFamily("Consolas")
        item.setFont(f)
    return item


def _make_table(headers: list[str], row_count: int = 0) -> QTableWidget:
    t = QTableWidget(row_count, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setStyleSheet(
        f"QTableWidget {{ alternate-background-color: {C_ROW_A}; "
        f"background-color: {C_ROW_B}; }}"
    )
    return t


# ── Header ──────────────────────────────────────────────────────────────────

class DeepDiveHeader(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel")
        self.setFixedHeight(60)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(0)

        self._name = QLabel("—")
        self._name.setStyleSheet("font-size: 16px; font-weight: 700; color: #e8e8e8;")
        self._ticker_lbl = QLabel()
        self._ticker_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 14px; "
            "font-weight: 700; color: #f59e0b; margin-left: 12px;"
        )
        self._price_lbl = QLabel()
        self._price_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 20px; "
            "font-weight: 700; margin-left: 24px;"
        )
        self._change_lbl = QLabel()
        self._change_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 13px; margin-left: 10px;"
        )
        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet("font-size: 11px; color: #555555; margin-left: 16px;")

        lay.addWidget(self._name)
        lay.addWidget(self._ticker_lbl)
        lay.addWidget(self._price_lbl)
        lay.addWidget(self._change_lbl)
        lay.addWidget(self._meta_lbl)
        lay.addStretch()

    def set_ticker(self, ticker: str) -> None:
        self._ticker_lbl.setText(ticker)
        self._name.setText(ticker)

    def update_quote(self, q: dict) -> None:
        name = q.get("name") or q.get("ticker", "")
        self._name.setText(name)
        ticker = q.get("ticker", "")
        self._ticker_lbl.setText(ticker)

        price = _sf(q.get("price"))
        change = _sf(q.get("change"))
        pct = _sf(q.get("change_pct"))

        color = C_POS if (change and change > 0) else (C_NEG if (change and change < 0) else C_TEXT)
        self._price_lbl.setText(f"{price:,.2f}" if price else "—")
        self._price_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 20px; font-weight: 700; "
            f"margin-left: 24px; color: {color};"
        )
        if change is not None:
            sign = "+" if change > 0 else ""
            pct_str = f"  ({sign}{pct:.2f}%)" if pct else ""
            self._change_lbl.setText(f"{sign}{change:,.2f}{pct_str}")
            self._change_lbl.setStyleSheet(
                f"font-family: Consolas, monospace; font-size: 13px; "
                f"margin-left: 10px; color: {color};"
            )
        parts = [q.get("exchange", ""), q.get("currency", "")]
        self._meta_lbl.setText("  ·  ".join(p for p in parts if p))


# ── Tab base ─────────────────────────────────────────────────────────────────

class _BaseTab(QWidget):
    """QWidget with a QStackedWidget: page 0=loading, 1=content, 2=error."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._loading_page = _loading_lbl()
        self._error_page   = _error_lbl()
        self._content      = QWidget()

        self._stack.addWidget(self._loading_page)  # 0
        self._stack.addWidget(self._content)        # 1
        self._stack.addWidget(self._error_page)     # 2
        self._stack.setCurrentIndex(0)

    def _show_content(self) -> None:
        self._stack.setCurrentIndex(1)

    def show_error(self, _tab: str, _msg: str) -> None:
        self._stack.setCurrentIndex(2)


# ── Tab 1: Financials ────────────────────────────────────────────────────────

_INC_ROWS = [
    ("Total Revenue",      "TotalRevenue",                    "val"),
    ("Gross Profit",       "GrossProfit",                     "val"),
    ("Gross Margin %",     "__gross_margin__",                "calc"),
    ("Operating Income",   "OperatingIncome",                 "val"),
    ("EBITDA",             "Ebitda",                          "val"),
    ("Net Income",         "NetIncome",                       "val"),
    ("EPS Basic",          "BasicEPS",                        "eps"),
    ("EPS Diluted",        "DilutedEPS",                      "eps"),
    ("R&D",                "ResearchAndDevelopment",          "val"),
    ("SG&A",               "SellingGeneralAndAdministration", "val"),
]

_BAL_ROWS = [
    ("Total Assets",           "TotalAssets",                         "val"),
    ("Total Liabilities",      "TotalLiabilitiesNetMinorityInterest", "val"),
    ("Shareholders Equity",    "StockholdersEquity",                  "val"),
    ("Cash & Equiv.",          "CashAndCashEquivalents",              "val"),
    ("Total Debt",             "TotalDebt",                           "val"),
    ("Net Debt",               "NetDebt",                             "val"),
    ("Goodwill & Intangibles", "GoodwillAndOtherIntangibleAssets",    "val"),
    ("Inventory",              "Inventory",                           "val"),
    ("Current Assets",         "CurrentAssets",                      "val"),
    ("Current Liabilities",    "CurrentLiabilities",                 "val"),
    ("Current Ratio",          "__current_ratio__",                   "calc"),
]

_CF_ROWS = [
    ("Operating Cash Flow", "OperatingCashFlow",       "val"),
    ("CapEx",               "CapitalExpenditure",      "val"),
    ("Free Cash Flow",      "FreeCashFlow",            "val"),
    ("Dividends Paid",      "CashDividendsPaid",       "val"),
    ("Debt Issuance",       "IssuanceOfDebt",          "val"),
    ("Share Buybacks",      "RepurchaseOfCapitalStock","val"),
]


def _build_fin_table(rows_def: list, ts: dict, prefix: str, max_p: int) -> QTableWidget:
    """Build a financials QTableWidget from timeseries data."""
    all_dates: set[str] = set()
    for _, field, _ in rows_def:
        if field.startswith("__"):
            # derived: gather from its source fields
            if field == "__gross_margin__":
                all_dates.update(ts.get(f"{prefix}TotalRevenue", {}).keys())
            elif field == "__current_ratio__":
                all_dates.update(ts.get(f"{prefix}CurrentAssets", {}).keys())
        else:
            all_dates.update(ts.get(f"{prefix}{field}", {}).keys())

    periods = sorted(all_dates, reverse=True)[:max_p]
    if not periods:
        t = _make_table(["No data available"])
        return t

    headers = [""] + [d[:7] for d in periods] + ["YoY %"]
    t = _make_table(headers, len(rows_def))
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for ci in range(1, len(headers)):
        t.horizontalHeader().setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)

    for ri, (label, field, fmt) in enumerate(rows_def):
        t.setItem(ri, 0, _twi(label, _L, bold=True))
        values: list[Optional[float]] = []

        if field == "__gross_margin__":
            rev = ts.get(f"{prefix}TotalRevenue", {})
            gp  = ts.get(f"{prefix}GrossProfit", {})
            for pi, d in enumerate(periods):
                r, g = rev.get(d), gp.get(d)
                if r and g and r != 0:
                    v = g / r * 100
                    values.append(v)
                    t.setItem(ri, pi + 1, _twi(f"{v:.1f}%", _R, mono=True))
                else:
                    values.append(None)
                    t.setItem(ri, pi + 1, _twi("—", _R, C_DIM))

        elif field == "__current_ratio__":
            ca = ts.get(f"{prefix}CurrentAssets", {})
            cl = ts.get(f"{prefix}CurrentLiabilities", {})
            for pi, d in enumerate(periods):
                a, l = ca.get(d), cl.get(d)
                if a and l and l != 0:
                    v = a / l
                    values.append(v)
                    t.setItem(ri, pi + 1, _twi(f"{v:.2f}x", _R, mono=True))
                else:
                    values.append(None)
                    t.setItem(ri, pi + 1, _twi("—", _R, C_DIM))

        else:
            fd = ts.get(f"{prefix}{field}", {})
            for pi, d in enumerate(periods):
                v = fd.get(d)
                values.append(v)
                if v is None:
                    t.setItem(ri, pi + 1, _twi("—", _R, C_DIM))
                else:
                    text = f"{v:.2f}" if fmt == "eps" else _fmt_large(v)
                    color = C_NEG if v < 0 else None
                    t.setItem(ri, pi + 1, _twi(text, _R, color, mono=True))

        # YoY %
        yoy_col = len(periods) + 1
        if len(values) >= 2 and values[0] is not None and values[1] is not None and values[1] != 0:
            yoy = (values[0] - values[1]) / abs(values[1]) * 100
            sign = "+" if yoy >= 0 else ""
            t.setItem(ri, yoy_col, _twi(f"{sign}{yoy:.1f}%", _R,
                                        C_POS if yoy >= 0 else C_NEG, mono=True))
        else:
            t.setItem(ri, yoy_col, _twi("—", _R, C_DIM))

    return t


class _FinancialsTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ts: dict = {}

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(4, 6, 4, 4)
        lay.setSpacing(6)

        # Toggle row
        tog = QHBoxLayout()
        self._ann_btn = QPushButton("ANNUAL")
        self._ann_btn.setProperty("class", "interval-btn")
        self._ann_btn.setCheckable(True)
        self._ann_btn.setChecked(True)
        self._ann_btn.clicked.connect(lambda: self._switch("annual"))
        self._qtr_btn = QPushButton("QUARTERLY")
        self._qtr_btn.setProperty("class", "interval-btn")
        self._qtr_btn.setCheckable(True)
        self._qtr_btn.clicked.connect(lambda: self._switch("quarterly"))
        tog.addWidget(self._ann_btn)
        tog.addWidget(self._qtr_btn)
        tog.addStretch()
        lay.addLayout(tog)

        self._sub = QTabWidget()
        lay.addWidget(self._sub)

    def on_data(self, data: dict) -> None:
        self._ts = data
        self._switch("annual")
        self._show_content()

    def _switch(self, prefix: str) -> None:
        self._ann_btn.setChecked(prefix == "annual")
        self._qtr_btn.setChecked(prefix == "quarterly")
        ts = self._ts.get(prefix, {})
        max_p = 5 if prefix == "annual" else 4

        while self._sub.count():
            self._sub.removeTab(0)
        self._sub.addTab(_build_fin_table(_INC_ROWS, ts, prefix, max_p), "Income Statement")
        self._sub.addTab(_build_fin_table(_BAL_ROWS, ts, prefix, max_p), "Balance Sheet")
        self._sub.addTab(_build_fin_table(_CF_ROWS,  ts, prefix, max_p), "Cash Flow")


# ── Tab 2: Earnings ──────────────────────────────────────────────────────────

class _EarningsTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        # Charts
        glw = pg.GraphicsLayoutWidget()
        glw.setBackground(C_BG)
        glw.ci.layout.setSpacing(10)
        self._eps_plot = glw.addPlot(title="EPS  —  Actual vs Estimate")
        glw.nextRow()
        self._rev_plot = glw.addPlot(title="Revenue  —  Actual vs Estimate")

        for plot in (self._eps_plot, self._rev_plot):
            plot.showGrid(x=False, y=True, alpha=0.08)
            plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
            plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
            plot.getAxis("bottom").setTextPen(pg.mkPen(C_DIM))
            plot.getAxis("left").setTextPen(pg.mkPen(C_DIM))
            plot.setMenuEnabled(False)
            plot.hideButtons()

        lay.addWidget(glw, 3)

        # Stat cards
        cards_row = QHBoxLayout()
        self._next_date_card = StatCard("NEXT EARNINGS", "—")
        self._eps_est_card   = StatCard("CUR QTR EPS EST", "—")
        cards_row.addWidget(self._next_date_card)
        cards_row.addWidget(self._eps_est_card)
        cards_row.addStretch()
        lay.addLayout(cards_row)

    def on_data(self, data: dict) -> None:
        self._draw_eps_chart(data)
        self._draw_rev_chart(data)
        self._fill_cards(data)
        self._show_content()

    def _draw_eps_chart(self, data: dict) -> None:
        # Prefer earnings.earningsChart.quarterly
        quarterly = (data.get("earnings", {}) or {}).get("earningsChart", {}).get("quarterly", [])
        if not quarterly:
            quarterly = (data.get("earningsHistory", {}) or {}).get("history", [])
            # normalise to same shape
            quarterly = [
                {
                    "date": h.get("quarter", {}).get("fmt", ""),
                    "actual":   {"raw": _sf(h.get("epsActual"))},
                    "estimate": {"raw": _sf(h.get("epsEstimate"))},
                }
                for h in quarterly
            ]

        if not quarterly:
            return

        n = min(8, len(quarterly))
        items = quarterly[-n:]
        labels   = [it.get("date", "") for it in items]
        actuals  = [_sf(it.get("actual"))   or 0.0 for it in items]
        ests     = [_sf(it.get("estimate")) or 0.0 for it in items]
        xs = np.arange(n, dtype=float)

        self._eps_plot.clear()
        self._eps_plot.addItem(pg.BarGraphItem(
            x=xs - 0.22, height=ests, width=0.38,
            brush=pg.mkBrush(245, 158, 11, 120)))
        brushes = [
            pg.mkBrush(34, 197, 94, 220) if a >= e else pg.mkBrush(239, 68, 68, 220)
            for a, e in zip(actuals, ests)
        ]
        self._eps_plot.addItem(pg.BarGraphItem(
            x=xs + 0.22, height=actuals, width=0.38, brushes=brushes))

        ticks = [[(i, labels[i]) for i in range(n)]]
        self._eps_plot.getAxis("bottom").setTicks(ticks)

        for i, (a, e) in enumerate(zip(actuals, ests)):
            diff = a - e
            is_beat = diff >= 0
            sign = "+" if is_beat else ""
            txt = pg.TextItem(
                f"{sign}{diff:.2f} {'BEAT' if is_beat else 'MISS'}",
                color=C_POS if is_beat else C_NEG, anchor=(0.5, 1.0))
            txt.setFont(QFont("Consolas", 7))
            txt.setPos(xs[i] + 0.22, max(a, 0))
            self._eps_plot.addItem(txt)

    def _draw_rev_chart(self, data: dict) -> None:
        quarterly = (data.get("earnings", {}) or {}).get("financialsChart", {}).get("quarterly", [])
        if not quarterly:
            return

        n = min(8, len(quarterly))
        items    = quarterly[-n:]
        labels   = [it.get("date", "") for it in items]
        actuals  = [(_sf(it.get("revenue")) or 0.0) / 1e9 for it in items]
        ests     = [0.0] * n  # financialsChart has no revenue estimates
        xs = np.arange(n, dtype=float)

        self._rev_plot.clear()
        brushes = [pg.mkBrush(34, 197, 94, 220) for _ in actuals]
        self._rev_plot.addItem(pg.BarGraphItem(
            x=xs, height=actuals, width=0.6, brushes=brushes))

        ticks = [[(i, labels[i]) for i in range(n)]]
        self._rev_plot.getAxis("bottom").setTicks(ticks)
        self._rev_plot.getAxis("left").setLabel("Rev (B)")

    def _fill_cards(self, data: dict) -> None:
        # Next earnings date
        cal = (data.get("calendarEvents", {}) or {}).get("earnings", {})
        dates = cal.get("earningsDate", [])
        ts = dates[0] if dates else None
        if ts:
            d = _fmt_date(ts)
            countdown = _days_until(ts)
            self._next_date_card.set_value(f"{d}  ({countdown})")

        # Current quarter EPS estimate
        trend = (data.get("earningsTrend", {}) or {}).get("trend", [])
        for t in trend:
            if t.get("period") == "0q":
                est = _sf((t.get("earningsEstimate") or {}).get("avg"))
                if est is not None:
                    self._eps_est_card.set_value(f"{est:.2f}")
                break


# ── Tab 3: Analysts ──────────────────────────────────────────────────────────

class _ConsensusBar(QWidget):
    """Horizontal stacked bar for Strong Buy / Buy / Hold / Sell / Strong Sell."""

    _KEYS   = ["strongBuy", "buy", "hold", "sell", "strongSell"]
    _COLORS = [C_POS, C_POS2, C_AMB, C_NEG2, C_NEG]
    _LABELS = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._counts: dict[str, int] = {}
        self.setFixedHeight(20)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        total = sum(self._counts.get(k, 0) for k in self._KEYS)
        if total == 0:
            return
        x, w, h = 0, self.width(), self.height()
        for key, color in zip(self._KEYS, self._COLORS):
            count = self._counts.get(key, 0)
            seg_w = int(count / total * w)
            painter.fillRect(x, 0, seg_w, h, QColor(color))
            x += seg_w
        painter.end()


class _AnalystsTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        outer_lay = QVBoxLayout(self._content)
        outer_lay.setContentsMargins(4, 4, 4, 4)
        outer_lay.setSpacing(8)

        # ── Top row: 3 columns ────────────────────────────────────────────
        top_row = QWidget()
        main_lay = QHBoxLayout(top_row)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(8)

        # ── Left: consensus (35%) ────────────────────────────────────────
        left = QFrame()
        left.setProperty("class", "panel")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 10, 12, 10)
        left_lay.setSpacing(6)

        hdr = QLabel("CONSENSUS")
        hdr.setProperty("class", "section-header")
        left_lay.addWidget(hdr)

        self._consensus_bar = _ConsensusBar()
        left_lay.addWidget(self._consensus_bar)

        self._rating_labels: dict[str, QLabel] = {}
        for key, label, color in zip(
            _ConsensusBar._KEYS, _ConsensusBar._LABELS, _ConsensusBar._COLORS
        ):
            row = QHBoxLayout()
            dot = QLabel("■")
            dot.setStyleSheet(f"color: {color}; font-size: 9px;")
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size: 11px;")
            count_lbl = QLabel("0")
            count_lbl.setStyleSheet(f"color: {color}; font-family: Consolas; font-size: 11px;")
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(count_lbl)
            left_lay.addLayout(row)
            self._rating_labels[key] = count_lbl

        self._consensus_text = QLabel()
        self._consensus_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._consensus_text.setStyleSheet(
            "font-family: Consolas; font-size: 13px; font-weight: 700; "
            f"color: {C_AMB}; margin-top: 8px;"
        )
        left_lay.addWidget(self._consensus_text)
        left_lay.addStretch()
        main_lay.addWidget(left, 35)

        # ── Center: price targets (30%) ──────────────────────────────────
        center = QFrame()
        center.setProperty("class", "panel")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(12, 10, 12, 10)
        center_lay.setSpacing(6)

        hdr2 = QLabel("PRICE TARGETS")
        hdr2.setProperty("class", "section-header")
        center_lay.addWidget(hdr2)

        self._target_mean   = StatCard("MEAN TARGET", "—")
        self._target_high   = StatCard("HIGH TARGET", "—")
        self._target_low    = StatCard("LOW TARGET", "—")
        self._current_price = StatCard("CURRENT PRICE", "—")
        for card in (self._target_mean, self._target_high, self._target_low, self._current_price):
            center_lay.addWidget(card)
        center_lay.addStretch()
        main_lay.addWidget(center, 30)

        # ── Right: rating changes (35%) ──────────────────────────────────
        right = QFrame()
        right.setProperty("class", "panel")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        hdr3 = QLabel("RATING CHANGES")
        hdr3.setProperty("class", "section-header")
        hdr3.setContentsMargins(10, 8, 10, 6)
        right_lay.addWidget(hdr3)

        self._ratings_table = _make_table(["Date", "Firm", "Action", "To Rating"])
        self._ratings_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3]:
            self._ratings_table.horizontalHeader().setSectionResizeMode(
                ci, QHeaderView.ResizeMode.ResizeToContents)
        right_lay.addWidget(self._ratings_table)
        main_lay.addWidget(right, 35)

        outer_lay.addWidget(top_row, 55)

        # ── Bottom: consensus trend chart ─────────────────────────────────
        trend_frame = QFrame()
        trend_frame.setProperty("class", "panel")
        trend_lay = QVBoxLayout(trend_frame)
        trend_lay.setContentsMargins(12, 8, 12, 8)
        trend_lay.setSpacing(4)

        trend_hdr = QLabel("CONSENSUS TREND")
        trend_hdr.setProperty("class", "section-header")
        trend_lay.addWidget(trend_hdr)

        self._trend_plot = pg.PlotWidget()
        self._trend_plot.setBackground(C_BG)
        self._trend_plot.setMinimumHeight(130)
        self._trend_plot.showAxis("top", False)
        self._trend_plot.showAxis("right", False)
        for side in ("left", "bottom"):
            ax = self._trend_plot.getAxis(side)
            ax.setTextPen(pg.mkPen(C_DIM))
            ax.setPen(pg.mkPen("#222222"))
            ax.setStyle(tickFont=QFont("Consolas", 8))
        self._trend_plot.getAxis("left").setLabel("%", color=C_DIM)
        self._trend_plot.setYRange(0, 100, padding=0.02)
        self._trend_plot.setMenuEnabled(False)
        self._trend_plot.hideButtons()
        trend_lay.addWidget(self._trend_plot)

        outer_lay.addWidget(trend_frame, 45)

    def on_data(self, data: dict) -> None:
        self._fill_consensus(data)
        self._fill_targets(data)
        self._fill_ratings(data)
        try:
            self._draw_consensus_trend(data)
        except Exception:
            pass  # chart draw failure must not block content display
        self._show_content()

    def _fill_consensus(self, data: dict) -> None:
        trend = (data.get("recommendationTrend", {}) or {}).get("trend", [])
        if not trend:
            return
        counts = {k: trend[0].get(k, 0) for k in _ConsensusBar._KEYS}
        self._consensus_bar.set_counts(counts)
        for key, lbl in self._rating_labels.items():
            lbl.setText(str(counts.get(key, 0)))
        total = sum(counts.values())
        strong_buy_buy = counts.get("strongBuy", 0) + counts.get("buy", 0)
        if total:
            if strong_buy_buy / total > 0.55:
                text = f"BUY — {total} analysts"
            elif counts.get("hold", 0) / total > 0.45:
                text = f"HOLD — {total} analysts"
            else:
                text = f"MIXED — {total} analysts"
            self._consensus_text.setText(text)

    def _fill_targets(self, data: dict) -> None:
        fd = data.get("financialData", {}) or {}
        mean  = _sf(fd.get("targetMeanPrice"))
        high  = _sf(fd.get("targetHighPrice"))
        low   = _sf(fd.get("targetLowPrice"))
        curr  = _sf(fd.get("currentPrice"))
        if curr:
            self._current_price.set_value(f"{curr:,.2f}")
        if mean:
            upside = ((mean - curr) / curr * 100) if curr else None
            sign = "+" if upside and upside >= 0 else ""
            upside_str = f"  ({sign}{upside:.1f}%)" if upside is not None else ""
            color = C_POS if (upside and upside >= 0) else C_NEG
            self._target_mean.set_value(f"{mean:,.2f}{upside_str}", color)
        if high:
            self._target_high.set_value(f"{high:,.2f}")
        if low:
            self._target_low.set_value(f"{low:,.2f}")

    def _fill_ratings(self, data: dict) -> None:
        history = (data.get("upgradeDowngradeHistory", {}) or {}).get("history", [])
        rows = history[:12]
        self._ratings_table.setRowCount(len(rows))
        self._ratings_table.setSortingEnabled(False)

        _BULLISH = {"buy", "outperform", "overweight", "strong buy", "outperformer",
                    "positive", "accumulate", "add"}
        _BEARISH = {"sell", "underperform", "underweight", "strong sell",
                    "negative", "reduce", "avoid"}

        action_map = {"up": "Upgrade ↑", "down": "Downgrade ↓",
                      "main": "Maintain", "init": "Initiated"}

        for ri, h in enumerate(rows):
            date = _fmt_date(h.get("epochGradeDate"))
            firm = h.get("firm", "")
            action = action_map.get(h.get("action", ""), h.get("action", ""))
            to_grade = h.get("toGrade", "")
            grade_lower = to_grade.lower()
            if any(b in grade_lower for b in _BULLISH):
                grade_color = C_POS
            elif any(b in grade_lower for b in _BEARISH):
                grade_color = C_NEG
            else:
                grade_color = C_AMB
            self._ratings_table.setItem(ri, 0, _twi(date, _C, mono=True))
            self._ratings_table.setItem(ri, 1, _twi(firm, _L))
            self._ratings_table.setItem(ri, 2, _twi(action, _C))
            self._ratings_table.setItem(ri, 3, _twi(to_grade, _C, grade_color))
        self._ratings_table.setSortingEnabled(True)

    def _draw_consensus_trend(self, data: dict) -> None:
        """Line chart per analyst stance over 4 monthly periods + dotted amber price overlay."""
        trend = (data.get("recommendationTrend", {}) or {}).get("trend", [])
        if not trend:
            return

        period_order = {"-3m": 0, "-2m": 1, "-1m": 2, "0m": 3}
        sorted_trend = sorted(
            [t for t in trend if t.get("period") in period_order],
            key=lambda t: period_order[t["period"]],
        )
        if not sorted_trend:
            return

        # Compute real month labels from today's date
        now = datetime.now(timezone.utc)
        def _period_label(period: str) -> str:
            try:
                offset = int(period.replace("m", ""))
            except ValueError:
                return period
            m = now.month + offset
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            return datetime(y, m, 1).strftime("%b %Y")

        n = len(sorted_trend)
        keys       = ["strongBuy", "buy", "hold", "sell", "strongSell"]
        line_colors = [C_POS, C_POS2, C_AMB, C_NEG2, C_NEG]
        line_labels = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
        totals = [max(sum(t.get(k, 0) for k in keys), 1) for t in sorted_trend]

        xs = np.arange(n, dtype=float)
        x_ticks = [
            (i, _period_label(t.get("period", "")))
            for i, t in enumerate(sorted_trend)
        ]

        self._trend_plot.clear()

        # One line per stance
        for key, color, _lbl in zip(keys, line_colors, line_labels):
            ys = np.array([
                t.get(key, 0) / totals[i] * 100
                for i, t in enumerate(sorted_trend)
            ])
            pen = pg.mkPen(color=QColor(color), width=2)
            self._trend_plot.plot(xs, ys, pen=pen,
                                  symbol="o", symbolSize=6,
                                  symbolBrush=pg.mkBrush(QColor(color)),
                                  symbolPen=pg.mkPen(None))

        self._trend_plot.getAxis("bottom").setTicks([x_ticks])
        self._trend_plot.setXRange(-0.3, n - 0.7, padding=0)
        # Compute y-max from data and set range explicitly (pyqtgraph rejects None)
        all_pcts = [
            t.get(k, 0) / totals[i] * 100
            for i, t in enumerate(sorted_trend) for k in keys
        ]
        y_top = max(all_pcts) if all_pcts else 60.0
        self._trend_plot.setYRange(0, y_top * 1.15, padding=0)

        # Price overlay: dotted amber line at ~40% opacity, scaled to analyst % range
        price_data = [p for p in data.get("_price_3mo", []) if p is not None]
        if len(price_data) >= 2:
            base = price_data[0]
            if base:
                pct_vals = [(p / base - 1) * 100 for p in price_data]
                vmin = min(pct_vals)
                vmax = max(pct_vals)
                rng  = (vmax - vmin) if vmax != vmin else 1.0
                # Scale price line to 0–max_analyst_pct range for visual alignment
                all_ys = [
                    t.get(k, 0) / totals[i] * 100
                    for i, t in enumerate(sorted_trend) for k in keys
                ]
                y_top = max(all_ys) if all_ys else 100
                scaled = [(v - vmin) / rng * y_top for v in pct_vals]
                px = np.linspace(0, n - 1, len(scaled))
                overlay_color = QColor(C_AMB)
                overlay_color.setAlpha(100)
                pen = pg.mkPen(
                    color=overlay_color, width=2,
                    style=Qt.PenStyle.DotLine,
                )
                self._trend_plot.plot(px, scaled, pen=pen)


# ── Tab 4: Peers ─────────────────────────────────────────────────────────────

_PEER_METRICS: list[tuple[str, str, str]] = [
    # (display label, data key, direction)
    ("Last Price",       "price",          "neutral"),
    ("Market Cap",       "market_cap",     "neutral"),
    ("P/E",              "pe",             "lower"),
    ("Forward P/E",      "fwd_pe",         "lower"),
    ("P/B",              "pb",             "lower"),
    ("P/S",              "ps",             "lower"),
    ("EV/EBITDA",        "ev_ebitda",      "lower"),
    ("Gross Margin %",   "gross_margin",   "higher"),
    ("Oper. Margin %",   "oper_margin",    "higher"),
    ("Net Margin %",     "net_margin",     "higher"),
    ("ROE",              "roe",            "higher"),
    ("ROA",              "roa",            "higher"),
    ("Rev. Growth YoY",  "rev_growth",     "higher"),
    ("EPS Growth YoY",   "eps_growth",     "higher"),
    ("Div Yield",        "div_yield",      "higher"),
    ("Debt/Equity",      "debt_equity",    "lower"),
]


def _extract_peer_metrics(summary: dict, quote: Optional[dict] = None) -> dict[str, Optional[float]]:
    ks = summary.get("defaultKeyStatistics", {}) or {}
    fd = summary.get("financialData", {})      or {}
    sd = summary.get("summaryDetail", {})      or {}
    return {
        "price":        _sf(quote.get("price")) if quote else None,
        "market_cap":   _sf(sd.get("marketCap")),
        "pe":           _sf(sd.get("trailingPE")),
        "fwd_pe":       _sf(sd.get("forwardPE")),
        "pb":           _sf(ks.get("priceToBook")),
        "ps":           _sf(ks.get("priceToSalesTrailing12Months")),
        "ev_ebitda":    _sf(ks.get("enterpriseToEbitda")),
        "gross_margin": (_sf(fd.get("grossMargins")) or 0) * 100,
        "oper_margin":  (_sf(fd.get("operatingMargins")) or 0) * 100,
        "net_margin":   (_sf(fd.get("profitMargins")) or 0) * 100,
        "roe":          (_sf(fd.get("returnOnEquity")) or 0) * 100,
        "roa":          (_sf(fd.get("returnOnAssets")) or 0) * 100,
        "rev_growth":   (_sf(fd.get("revenueGrowth")) or 0) * 100,
        "eps_growth":   (_sf(fd.get("earningsGrowth")) or 0) * 100,
        "div_yield":    (_sf(sd.get("dividendYield")) or 0) * 100,
        "debt_equity":  _sf(fd.get("debtToEquity")),
    }


class _PeersTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(4, 4, 4, 4)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self._scroll)

    def on_data(self, data: dict) -> None:
        target  = data.get("target", "")
        tickers = [target] + data.get("tickers", [])
        all_data = data.get("data", {})

        # Build metrics for each ticker
        metrics: dict[str, dict] = {}
        for t in tickers:
            summary = all_data.get(t, {})
            metrics[t] = _extract_peer_metrics(summary)

        # Build table
        headers = ["Metric"] + tickers
        table = _make_table(headers, len(_PEER_METRICS))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for ci in range(1, len(headers)):
            table.horizontalHeader().setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)
            # Amber header for target
            hi = table.horizontalHeaderItem(ci)
            if hi and tickers[ci - 1] == target:
                hi.setForeground(QColor(C_AMB))

        for ri, (label, key, direction) in enumerate(_PEER_METRICS):
            table.setItem(ri, 0, _twi(label, _L, bold=True))

            # Collect valid values for best/worst highlighting
            vals: dict[str, Optional[float]] = {t: metrics[t].get(key) for t in tickers}
            valid = {t: v for t, v in vals.items() if v is not None}

            best_t = worst_t = None
            if direction != "neutral" and len(valid) > 1:
                if direction == "higher":
                    best_t  = max(valid, key=lambda t: valid[t])
                    worst_t = min(valid, key=lambda t: valid[t])
                else:  # lower
                    best_t  = min(valid, key=lambda t: valid[t])
                    worst_t = max(valid, key=lambda t: valid[t])

            for ci, ticker in enumerate(tickers):
                v = vals.get(ticker)
                if v is None:
                    cell = _twi("—", _R, C_DIM, mono=True)
                else:
                    # Format
                    if key in ("price",):
                        text = f"{v:,.2f}"
                    elif key == "market_cap":
                        text = _fmt_large(v, currency="")
                    elif key in ("gross_margin", "oper_margin", "net_margin",
                                 "roe", "roa", "rev_growth", "eps_growth", "div_yield"):
                        text = f"{v:.1f}%"
                    elif key == "debt_equity":
                        text = f"{v:.1f}"
                    else:
                        text = f"{v:.1f}x"

                    color = None
                    if ticker == best_t:
                        color = C_POS
                    elif ticker == worst_t:
                        color = C_NEG
                    cell = _twi(text, _R, color, mono=True)
                table.setItem(ri, ci + 1, cell)

        self._scroll.setWidget(table)
        self._show_content()


# ── Tab 5: Dividends ─────────────────────────────────────────────────────────

class _DividendsTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        # Chart
        self._chart_widget = _pg_plot("Dividend History  (per share)")
        lay.addWidget(self._chart_widget, 2)

        self._no_div_label = QLabel("No dividend history available")
        self._no_div_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_div_label.setStyleSheet(f"color: {C_DIM}; font-size: 13px;")
        self._no_div_label.hide()
        lay.addWidget(self._no_div_label)

        # Stat cards
        cards_row = QHBoxLayout()
        self._annual_div  = StatCard("ANNUAL DIV", "—")
        self._yield_card  = StatCard("DIV YIELD", "—")
        self._payout_card = StatCard("PAYOUT RATIO", "—")
        self._exdate_card = StatCard("EX-DIV DATE", "—")
        for c in (self._annual_div, self._yield_card, self._payout_card, self._exdate_card):
            cards_row.addWidget(c)
        lay.addLayout(cards_row)

        # History table
        hdr3 = QLabel("DIVIDEND HISTORY")
        hdr3.setProperty("class", "section-header")
        lay.addWidget(hdr3)
        self._hist_table = _make_table(["Ex-Date", "Amount per Share"])
        self._hist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._hist_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._hist_table, 2)

    def on_data(self, data: dict) -> None:
        events = data.get("chart_events", {}) or {}
        sd = data.get("summaryDetail", {}) or {}
        ks = data.get("defaultKeyStatistics", {}) or {}

        # Parse dividend events: {ts_str: {amount, date}}
        div_list = sorted(
            [
                (int(ts), float(v.get("amount", 0)))
                for ts, v in events.items()
                if isinstance(v, dict)
            ],
            key=lambda x: x[0],
        )

        if div_list:
            self._draw_chart(div_list)
        else:
            self._chart_widget.hide()
            self._no_div_label.show()

        # Stat cards
        dy = _sf(sd.get("dividendYield"))
        pr = _sf(sd.get("payoutRatio"))
        exd = _sf(sd.get("exDividendDate"))
        fwd = _sf(sd.get("dividendRate"))
        if fwd is not None:
            self._annual_div.set_value(f"{fwd:.2f}")
        if dy is not None:
            self._yield_card.set_value(f"{dy * 100:.2f}%")
        if pr is not None:
            self._payout_card.set_value(f"{pr * 100:.1f}%")
        if exd is not None:
            self._exdate_card.set_value(_fmt_date(exd))

        # History table
        rows = list(reversed(div_list))
        self._hist_table.setRowCount(len(rows))
        self._hist_table.setSortingEnabled(False)
        for ri, (ts, amount) in enumerate(rows):
            self._hist_table.setItem(ri, 0, _twi(_fmt_date(ts), _C, mono=True))
            self._hist_table.setItem(ri, 1, _twi(f"{amount:.4f}", _R, mono=True))
        self._hist_table.setSortingEnabled(True)

        self._show_content()

    def _draw_chart(self, div_list: list) -> None:
        xs = np.array([ts for ts, _ in div_list], dtype=float)
        ys = np.array([amt for _, amt in div_list], dtype=float)
        n  = len(xs)

        # Normalise xs to 0..n-1 for clean bar placement
        xi = np.arange(n, dtype=float)
        self._chart_widget.clear()
        self._chart_widget.addItem(pg.BarGraphItem(
            x=xi, height=ys, width=0.6,
            brush=pg.mkBrush(245, 158, 11, 200),
            pen=pg.mkPen(C_AMB, width=0.5),
        ))
        step = max(1, n // 8)
        ticks = [[(int(xi[i]), _fmt_date(int(xs[i]))) for i in range(0, n, step)]]
        self._chart_widget.getAxis("bottom").setTicks(ticks)


# ── Tab 6: Ownership ─────────────────────────────────────────────────────────

class _OwnershipTab(_BaseTab):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        # Top stat cards
        cards_row = QHBoxLayout()
        self._insider_card  = StatCard("INSIDERS HELD", "—")
        self._inst_card     = StatCard("INSTITUTIONS", "—")
        self._shares_card   = StatCard("SHARES OUT.", "—")
        self._float_card    = StatCard("FLOAT", "—")
        for c in (self._insider_card, self._inst_card, self._shares_card, self._float_card):
            cards_row.addWidget(c)
        lay.addLayout(cards_row)

        # Split: institutional holders | insider transactions
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Institutional holders
        inst_frame = QFrame()
        inst_frame.setProperty("class", "panel")
        inst_lay = QVBoxLayout(inst_frame)
        inst_lay.setContentsMargins(0, 0, 0, 0)
        inst_hdr = QLabel("TOP INSTITUTIONAL HOLDERS")
        inst_hdr.setProperty("class", "section-header")
        inst_hdr.setContentsMargins(10, 8, 10, 6)
        inst_lay.addWidget(inst_hdr)
        self._inst_table = _make_table(["Institution", "Shares", "% Held", "Value", "Date"])
        self._inst_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci in [1, 2, 3, 4]:
            self._inst_table.horizontalHeader().setSectionResizeMode(
                ci, QHeaderView.ResizeMode.ResizeToContents)
        inst_lay.addWidget(self._inst_table)
        splitter.addWidget(inst_frame)

        # Insider transactions
        ins_frame = QFrame()
        ins_frame.setProperty("class", "panel")
        ins_lay = QVBoxLayout(ins_frame)
        ins_lay.setContentsMargins(0, 0, 0, 0)
        ins_hdr = QLabel("RECENT INSIDER TRANSACTIONS")
        ins_hdr.setProperty("class", "section-header")
        ins_hdr.setContentsMargins(10, 8, 10, 6)
        ins_lay.addWidget(ins_hdr)
        self._insider_table = _make_table(["Date", "Name", "Title", "Transaction", "Shares", "Value"])
        self._insider_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._insider_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 3, 4, 5]:
            self._insider_table.horizontalHeader().setSectionResizeMode(
                ci, QHeaderView.ResizeMode.ResizeToContents)
        ins_lay.addWidget(self._insider_table)
        splitter.addWidget(ins_frame)
        splitter.setSizes([500, 500])

        lay.addWidget(splitter, 1)

    def on_data(self, data: dict) -> None:
        mh  = data.get("majorHoldersBreakdown",  {}) or {}
        io  = data.get("institutionOwnership",    {}) or {}
        it  = data.get("insiderTransactions",     {}) or {}
        ks  = data.get("defaultKeyStatistics",    {}) or {}

        # Stat cards
        insider_pct = _sf(mh.get("insidersPercentHeld"))
        inst_pct    = _sf(mh.get("institutionsPercentHeld"))
        shares_out  = _sf(ks.get("sharesOutstanding"))
        float_sh    = _sf(ks.get("floatShares"))
        if insider_pct is not None:
            self._insider_card.set_value(f"{insider_pct * 100:.1f}%")
        if inst_pct is not None:
            self._inst_card.set_value(f"{inst_pct * 100:.1f}%")
        if shares_out is not None:
            self._shares_card.set_value(_fmt_large(shares_out, currency=""))
        if float_sh is not None:
            self._float_card.set_value(_fmt_large(float_sh, currency=""))

        # Institutional holders table
        owners = (io.get("ownershipList") or [])[:10]
        self._inst_table.setRowCount(len(owners))
        self._inst_table.setSortingEnabled(False)
        for ri, o in enumerate(owners):
            org    = o.get("organization", "")
            pos    = _sf(o.get("position"))
            pct    = _sf(o.get("pctHeld"))
            val    = _sf(o.get("value"))
            date   = _fmt_date(o.get("reportDate"))
            self._inst_table.setItem(ri, 0, _twi(org, _L))
            self._inst_table.setItem(ri, 1, _twi(_fmt_large(pos, currency="") if pos else "—", _R, mono=True))
            self._inst_table.setItem(ri, 2, _twi(f"{pct * 100:.2f}%" if pct else "—", _R, mono=True))
            self._inst_table.setItem(ri, 3, _twi(_fmt_large(val) if val else "—", _R, mono=True))
            self._inst_table.setItem(ri, 4, _twi(date, _C, mono=True))
        self._inst_table.setSortingEnabled(True)

        # Insider transactions
        _BUY_WORDS  = {"purchase", "buy", "award", "grant", "gift", "acquisition"}
        _SELL_WORDS = {"sale", "sell", "disposition", "automatic sale"}

        txns = (it.get("transactions") or [])[:15]
        self._insider_table.setRowCount(len(txns))
        self._insider_table.setSortingEnabled(False)
        for ri, tx in enumerate(txns):
            name     = tx.get("filerName", "")
            relation = tx.get("filerRelation", "")
            text     = (tx.get("transactionText") or "").lower()
            shares   = _sf(tx.get("shares"))
            value    = _sf(tx.get("value"))
            date     = _fmt_date(tx.get("startDate"))

            if any(w in text for w in _BUY_WORDS):
                tx_label, tx_color = "Buy", C_POS
            elif any(w in text for w in _SELL_WORDS):
                tx_label, tx_color = "Sell", C_NEG
            else:
                tx_label, tx_color = "Other", C_DIM

            self._insider_table.setItem(ri, 0, _twi(date, _C, mono=True))
            self._insider_table.setItem(ri, 1, _twi(name.title(), _L))
            self._insider_table.setItem(ri, 2, _twi(relation, _L, C_DIM))
            self._insider_table.setItem(ri, 3, _twi(tx_label, _C, tx_color, bold=True))
            self._insider_table.setItem(ri, 4, _twi(
                _fmt_large(shares, currency="") if shares else "—", _R, mono=True))
            self._insider_table.setItem(ri, 5, _twi(
                _fmt_large(value) if value else "—", _R, mono=True))
        self._insider_table.setSortingEnabled(True)

        self._show_content()


# ── DeepDiveScreen ───────────────────────────────────────────────────────────

class DeepDiveScreen(QWidget):
    """Full deep-dive analysis screen: header + 6-tab analysis."""

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._ticker: Optional[str] = None
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = DeepDiveHeader()
        root.addWidget(self._header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)

        self._fin  = _FinancialsTab()
        self._earn = _EarningsTab()
        self._anal = _AnalystsTab()
        self._peer = _PeersTab()
        self._div  = _DividendsTab()
        self._own  = _OwnershipTab()

        self._tabs.addTab(self._fin,  "Financials")
        self._tabs.addTab(self._earn, "Earnings")
        self._tabs.addTab(self._anal, "Analysts")
        self._tabs.addTab(self._peer, "Peers")
        self._tabs.addTab(self._div,  "Dividends")
        self._tabs.addTab(self._own,  "Ownership")

    def load_ticker(self, ticker: str) -> None:
        import logging
        self._ticker = ticker.upper()
        self._header.set_ticker(self._ticker)
        logging.getLogger("lens.deep_dive").info("Opening Deep Dive — %s", self._ticker)
        self._start_worker()

    def on_show(self) -> None:
        pass  # data load is triggered by load_ticker()

    def _start_worker(self) -> None:
        if not self._ticker:
            return
        if self._worker and self._is_running(self._worker):
            return

        from lens.ui.workers import FetchDeepDiveWorker
        self._worker = FetchDeepDiveWorker(self._ticker)
        self._worker.header_ready.connect(self._on_header)
        self._worker.financials_ready.connect(self._fin.on_data)
        self._worker.earnings_ready.connect(self._earn.on_data)
        self._worker.analysts_ready.connect(self._anal.on_data)
        self._worker.dividends_ready.connect(self._div.on_data)
        self._worker.ownership_ready.connect(self._own.on_data)
        self._worker.peers_ready.connect(self._peer.on_data)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_header(self, quote: dict) -> None:
        self._header.update_quote(quote)

    def _on_error(self, tab: str, msg: str) -> None:
        tab_map = {
            "financials": self._fin,
            "earnings":   self._earn,
            "analysts":   self._anal,
            "dividends":  self._div,
            "ownership":  self._own,
            "peers":      self._peer,
        }
        target = tab_map.get(tab)
        if target:
            target.show_error(tab, msg)

    @staticmethod
    def _is_running(worker) -> bool:
        try:
            return worker.isRunning()
        except RuntimeError:
            return False

    def cleanup(self) -> None:
        if self._worker is not None:
            try:
                if self._worker.isRunning():
                    self._worker.terminate()
                    self._worker.wait()
            except RuntimeError:
                pass
            self._worker = None
