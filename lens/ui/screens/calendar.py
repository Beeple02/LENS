"""Economic Calendar screen — earnings, ECB meetings, ex-dividend dates."""

from __future__ import annotations

import calendar as _cal
from datetime import date as _date, datetime
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

C_AMB     = "#f59e0b"
C_POS     = "#22c55e"
C_NEG     = "#ef4444"
C_DIM     = "#555555"
C_TEXT    = "#c8c8c8"
C_BG      = "#000000"

# ECB Governing Council meeting dates (same list as in workers.py)
_ECB_DATES = {
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-29", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
}

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class _EventPill(QLabel):
    """Colored pill label for calendar events."""

    clicked = pyqtSignal(str)   # emits ticker

    _STYLES = {
        "earnings":  ("background:#451a03; color:#f59e0b;", "#f59e0b"),
        "ecb":       ("background:#1e2535; color:#93c5fd;", "#93c5fd"),
        "dividend":  ("background:#052e16; color:#22c55e;", "#22c55e"),
    }

    def __init__(self, text: str, event_type: str, ticker: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._ticker = ticker
        style_base, _ = self._STYLES.get(event_type, ("background:#222222; color:#888888;", "#888888"))
        self.setStyleSheet(
            f"{style_base} font-size: 9px; font-weight: 700; "
            "border-radius: 2px; padding: 1px 3px; margin: 1px 0;"
        )
        self.setWordWrap(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor if ticker else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, _evt) -> None:
        if self._ticker:
            self.clicked.emit(self._ticker)


class _DayCell(QFrame):
    """Single day cell in the calendar grid."""

    ticker_clicked = pyqtSignal(str)
    day_selected   = pyqtSignal(_date)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._day: Optional[_date] = None
        self.setFixedSize(130, 80)
        self.setStyleSheet(
            "QFrame { background: #0d0d0d; border: 1px solid #1a1a1a; }"
            "QFrame:hover { border: 1px solid #2a2a2a; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(1)

        self._day_lbl = QLabel()
        self._day_lbl.setStyleSheet(
            "font-family: Consolas; font-size: 11px; color: #555555; "
            "border: none; background: transparent;"
        )
        lay.addWidget(self._day_lbl)

        self._events_area = QWidget()
        events_lay = QVBoxLayout(self._events_area)
        events_lay.setContentsMargins(0, 0, 0, 0)
        events_lay.setSpacing(1)
        self._events_area.setLayout(events_lay)
        lay.addWidget(self._events_area)
        lay.addStretch()

        self._events_lay = events_lay

    def set_day(self, day: Optional[_date], today: _date) -> None:
        self._day = day
        # Clear events
        while self._events_lay.count():
            item = self._events_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if day is None:
            self._day_lbl.setText("")
            self.setStyleSheet(
                "QFrame { background: #060606; border: 1px solid #111111; }"
            )
            return

        is_today = day == today
        is_weekend = day.weekday() >= 5

        day_color = C_AMB if is_today else ("#333333" if is_weekend else C_DIM)
        self._day_lbl.setText(str(day.day))
        self._day_lbl.setStyleSheet(
            f"font-family: Consolas; font-size: 11px; color: {day_color}; "
            "border: none; background: transparent; "
            + ("font-weight: 700;" if is_today else "")
        )
        if is_today:
            self.setStyleSheet(
                "QFrame { background: #0d0d0d; border: 1px solid #f59e0b; }"
            )
        elif is_weekend:
            self.setStyleSheet(
                "QFrame { background: #080808; border: 1px solid #111111; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background: #0d0d0d; border: 1px solid #1a1a1a; }"
                "QFrame:hover { border: 1px solid #2a2a2a; }"
            )

    def add_event(self, text: str, event_type: str, ticker: str = "") -> None:
        pill = _EventPill(text, event_type, ticker)
        if ticker:
            pill.clicked.connect(self.ticker_clicked)
        # Show max 3 pills; add "…" if more
        if self._events_lay.count() < 3:
            self._events_lay.addWidget(pill)
        elif self._events_lay.count() == 3:
            more = QLabel("…")
            more.setStyleSheet("font-size: 9px; color: #555555; border: none; background: transparent;")
            self._events_lay.addWidget(more)

    def mousePressEvent(self, _evt) -> None:
        if self._day:
            self.day_selected.emit(self._day)


class _DayDetailDialog(QDialog):
    """Pop-up showing all events for a selected day."""

    ticker_clicked = pyqtSignal(str)

    def __init__(self, day: _date, events: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Events — {day.strftime('%A, %B %-d, %Y')}")
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        if not events:
            lay.addWidget(QLabel("No events on this day."))
        else:
            for ev in events:
                row = QHBoxLayout()
                pill = _EventPill(ev.get("type_label", ""), ev.get("type", "ecb"),
                                  ev.get("ticker", ""))
                if ev.get("ticker"):
                    pill.clicked.connect(self.ticker_clicked)
                row.addWidget(pill)
                desc = QLabel(ev.get("description", ""))
                desc.setStyleSheet("font-size: 12px; color: #c8c8c8;")
                row.addWidget(desc, 1)
                lay.addLayout(row)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)


class EconomicCalendarScreen(QWidget):
    """Standalone Economic Calendar — earnings, ECB meetings, ex-dividend events."""

    open_quote = pyqtSignal(str)   # for cross-screen navigation

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._worker = None
        self._today  = _date.today()

        # Display state
        self._view_year  = self._today.year
        self._view_month = self._today.month

        # Loaded events: {date_str: [event_dict]}
        self._events: dict[str, list[dict]] = {}
        for ds in _ECB_DATES:
            self._events.setdefault(ds, []).append({
                "type": "ecb",
                "type_label": "ECB MEETING",
                "description": "ECB Governing Council Meeting",
                "ticker": "",
            })

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setProperty("class", "panel")
        toolbar.setFixedHeight(48)
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(16, 0, 16, 0)
        tb_lay.setSpacing(8)

        title_lbl = QLabel("ECONOMIC CALENDAR")
        title_lbl.setStyleSheet(
            "font-family: Consolas; font-size: 13px; font-weight: 700; "
            f"color: {C_AMB}; letter-spacing: 1px;"
        )
        tb_lay.addWidget(title_lbl)
        tb_lay.addStretch()

        self._prev_btn = QPushButton("◀  PREV")
        self._prev_btn.setProperty("class", "interval-btn")
        self._prev_btn.setFixedWidth(80)
        self._prev_btn.clicked.connect(self._go_prev)
        tb_lay.addWidget(self._prev_btn)

        self._month_lbl = QLabel()
        self._month_lbl.setStyleSheet(
            "font-family: Consolas; font-size: 13px; font-weight: 700; "
            "color: #e8e8e8; min-width: 160px;"
        )
        self._month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_lay.addWidget(self._month_lbl)

        self._next_btn = QPushButton("NEXT  ▶")
        self._next_btn.setProperty("class", "interval-btn")
        self._next_btn.setFixedWidth(80)
        self._next_btn.clicked.connect(self._go_next)
        tb_lay.addWidget(self._next_btn)

        tb_lay.addSpacing(16)

        refresh_btn = QPushButton("↻  REFRESH")
        refresh_btn.setProperty("class", "primary")
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._fetch)
        tb_lay.addWidget(refresh_btn)

        self._status_lbl = QLabel("Loading…")
        self._status_lbl.setStyleSheet(f"font-size: 11px; color: {C_DIM};")
        tb_lay.addWidget(self._status_lbl)

        layout.addWidget(toolbar)

        # ── Scroll area with calendar grid ────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        self._cal_widget = QWidget()
        self._cal_lay = QVBoxLayout(self._cal_widget)
        self._cal_lay.setContentsMargins(8, 8, 8, 8)
        self._cal_lay.setSpacing(0)
        scroll.setWidget(self._cal_widget)

        # Day-of-week header row
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(2)
        for day_name in _WEEKDAYS:
            lbl = QLabel(day_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(
                "font-size: 10px; font-weight: 700; color: #555555; "
                "padding: 4px 0; letter-spacing: 0.5px;"
            )
            hdr_row.addWidget(lbl)
        hdr_row.addStretch()
        self._cal_lay.addLayout(hdr_row)

        # Grid of day cells (6 rows × 7 columns)
        self._grid = QGridLayout()
        self._grid.setSpacing(2)
        self._cells: list[_DayCell] = []
        for row in range(6):
            for col in range(7):
                cell = _DayCell()
                cell.ticker_clicked.connect(self.open_quote)
                cell.day_selected.connect(self._on_day_selected)
                self._grid.addWidget(cell, row, col)
                self._cells.append(cell)
        self._cal_lay.addLayout(self._grid)
        self._cal_lay.addStretch()

        self._render_calendar()

    def on_show(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            self._fetch()

    def _go_prev(self) -> None:
        if self._view_month == 1:
            self._view_month = 12
            self._view_year -= 1
        else:
            self._view_month -= 1
        self._render_calendar()

    def _go_next(self) -> None:
        if self._view_month == 12:
            self._view_month = 1
            self._view_year += 1
        else:
            self._view_month += 1
        self._render_calendar()

    def _render_calendar(self) -> None:
        self._month_lbl.setText(f"{_MONTHS[self._view_month - 1].upper()}  {self._view_year}")

        # Build a 6×7 grid of dates (None = outside this month)
        cal = _cal.monthcalendar(self._view_year, self._view_month)
        # Pad to exactly 6 rows
        while len(cal) < 6:
            cal.append([0] * 7)

        idx = 0
        for week in cal:
            for day_num in week:
                cell = self._cells[idx]
                if day_num == 0:
                    cell.set_day(None, self._today)
                else:
                    d = _date(self._view_year, self._view_month, day_num)
                    cell.set_day(d, self._today)
                    # Add events for this day
                    ds = d.strftime("%Y-%m-%d")
                    for ev in self._events.get(ds, []):
                        if ev["type"] == "earnings":
                            label = f"EARNINGS · {ev.get('ticker','')}"
                        elif ev["type"] == "ecb":
                            label = "ECB MEETING"
                        else:
                            label = f"EX-DIV · {ev.get('ticker','')}"
                        cell.add_event(label, ev["type"], ev.get("ticker", ""))
                idx += 1

    def _on_day_selected(self, day: _date) -> None:
        ds = day.strftime("%Y-%m-%d")
        evs = self._events.get(ds, [])
        if evs:
            dlg = _DayDetailDialog(day, evs, self)
            dlg.ticker_clicked.connect(self.open_quote)
            dlg.exec()

    def _fetch(self) -> None:
        from lens.ui.workers import FetchCalendarWorker
        if self._worker and self._worker.isRunning():
            return
        self._status_lbl.setText("Loading events…")
        self._status_lbl.setStyleSheet(f"font-size: 11px; color: {C_AMB};")
        self._worker = FetchCalendarWorker(self)
        self._worker.calendar_data_ready.connect(self._on_data)
        self._worker.error.connect(lambda e: self._status_lbl.setText(f"Error: {e[:60]}"))
        self._worker.start()

    def _on_data(self, data: dict) -> None:
        # Rebuild events dict, keeping ECB dates
        self._events = {}
        for ds in _ECB_DATES:
            self._events.setdefault(ds, []).append({
                "type": "ecb",
                "type_label": "ECB MEETING",
                "description": "ECB Governing Council Meeting",
                "ticker": "",
            })

        for ev in data.get("earnings", []):
            ds = ev.get("date", "")
            if ds:
                self._events.setdefault(ds, []).append({
                    "type": "earnings",
                    "type_label": "EARNINGS",
                    "description": f"Earnings — {ev.get('name', ev.get('ticker',''))}",
                    "ticker": ev.get("ticker", ""),
                })

        for ev in data.get("ex_dividends", []):
            ds = ev.get("date", "")
            if ds:
                self._events.setdefault(ds, []).append({
                    "type": "dividend",
                    "type_label": "EX-DIV",
                    "description": f"Ex-Dividend — {ev.get('ticker','')}  ({ev.get('amount','')})",
                    "ticker": ev.get("ticker", ""),
                })

        earnings_count = len(data.get("earnings", []))
        self._status_lbl.setText(f"{earnings_count} earnings events loaded")
        self._status_lbl.setStyleSheet(f"font-size: 11px; color: {C_POS};")
        self._render_calendar()

    def cleanup(self) -> None:
        if self._worker:
            try:
                if self._worker.isRunning():
                    self._worker.terminate()
                    self._worker.wait()
            except RuntimeError:
                pass
            self._worker = None
