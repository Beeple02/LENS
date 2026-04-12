"""Screener screen — DSL filter + presets + saved screens + results table."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lens.ui.widgets.data_table import (
    DataTable,
    COLOR_POS, COLOR_NEG, COLOR_DIM, COLOR_AMB, COLOR_TEXT, MONO,
    _item, _large_num,
)

RESULT_COLS = ["Ticker", "Name", "Sector", "P/E", "P/B", "EV/EBITDA",
               "Div Yield", "Mkt Cap", "ROE", "ROA", "Rev Growth"]

FIELD_HELP = """
Available fields:
  pe             P/E ratio
  forward_pe     Forward P/E
  pb             P/B ratio
  ps             P/S ratio
  ev_ebitda      EV / EBITDA
  div_yield      Dividend yield (decimal, e.g. 0.03 = 3%)
  market_cap     Market capitalisation (absolute, e.g. 1e9)
  roe            Return on equity (decimal)
  roa            Return on assets (decimal)
  revenue_growth Revenue growth YoY (decimal)
  debt_equity    Debt / Equity ratio
  current_ratio  Current ratio
  sector         Sector name (string, use = or LIKE)
  industry       Industry name
  ticker         Ticker symbol

Operators: <  <=  >  >=  =  !=  LIKE
Logic:     AND  OR  NOT  ( )

Examples:
  pe < 15 AND div_yield > 0.03
  market_cap > 1e9 AND roe > 0.15
  sector = "Technology" AND pe < 25
  pb < 2 AND debt_equity < 1 AND current_ratio > 1.5
"""

# Built-in presets — not deletable
_BUILTIN_PRESETS: list[tuple[str, str]] = [
    ("Cheap Quality",    "pe < 15 AND roe > 0.15 AND debt_equity < 1"),
    ("High Dividend",    "div_yield > 0.04 AND payout_ratio < 0.7 AND market_cap > 5e8"),
    ("Deep Value",       "pb < 1 AND pe < 12 AND current_ratio > 1.5"),
    ("Growth",           "revenue_growth > 0.15 AND roe > 0.12"),
    ("Low Debt",         "debt_equity < 0.3 AND current_ratio > 2"),
    ("Momentum Quality", "revenue_growth > 0.1 AND net_margin > 0.1 AND pb < 5"),
]


def _fmt(v, decimals=1):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{decimals}f}"

def _fmt_pct(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v * 100:.2f}%"


class ScreenerScreen(QWidget):
    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._worker = None
        self._df: Optional[pd.DataFrame] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Filter bar ────────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setProperty("class", "panel")
        filter_bar.setFixedHeight(52)
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(8)

        # PRESETS button
        self._presets_btn = QPushButton("PRESETS ▾")
        self._presets_btn.setFixedWidth(100)
        self._presets_btn.setStyleSheet(
            "QPushButton { background: #111111; color: #c8c8c8; border: 1px solid #2a2a2a; "
            "font-size: 11px; font-weight: 600; padding: 2px 8px; }"
            "QPushButton:hover { background: #1a1a1a; border-color: #f59e0b; color: #f59e0b; }"
        )
        self._presets_btn.clicked.connect(self._show_presets_menu)
        filter_layout.addWidget(self._presets_btn)

        filter_lbl = QLabel("Filter:")
        filter_lbl.setStyleSheet("color: #f59e0b; font-weight: 600; font-size: 12px;")
        filter_lbl.setFixedWidth(46)
        filter_layout.addWidget(filter_lbl)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText(
            "pe < 15 AND div_yield > 0.03 AND market_cap > 1e9"
        )
        self._filter_input.returnPressed.connect(self._run_screen)
        filter_layout.addWidget(self._filter_input)

        # SAVE button
        save_btn = QPushButton("SAVE ✦")
        save_btn.setFixedWidth(80)
        save_btn.setStyleSheet(
            "QPushButton { background: #111111; color: #c8c8c8; border: 1px solid #2a2a2a; "
            "font-size: 11px; font-weight: 600; padding: 2px 8px; }"
            "QPushButton:hover { background: #1a1a1a; border-color: #f59e0b; color: #f59e0b; }"
        )
        save_btn.clicked.connect(self._save_screen)
        filter_layout.addWidget(save_btn)

        universe_lbl = QLabel("Universe:")
        universe_lbl.setStyleSheet("color: #666666; font-size: 12px;")
        filter_layout.addWidget(universe_lbl)

        self._universe_combo = QComboBox()
        self._universe_combo.setFixedWidth(150)
        self._universe_combo.addItem("All Securities", "all")
        filter_layout.addWidget(self._universe_combo)

        run_btn = QPushButton("Run Screen")
        run_btn.setProperty("class", "primary")
        run_btn.setFixedWidth(100)
        run_btn.clicked.connect(self._run_screen)
        filter_layout.addWidget(run_btn)

        layout.addWidget(filter_bar)

        # ── Status bar ────────────────────────────────────────────────────
        status_frame = QFrame()
        status_frame.setFixedHeight(24)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 0, 12, 0)
        self._status_label = QLabel("Enter a filter expression and click Run Screen")
        self._status_label.setStyleSheet("color: #555555; font-size: 11px;")
        status_layout.addWidget(self._status_label)
        layout.addWidget(status_frame)

        # ── Splitter: table | help ─────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        self._table = DataTable(RESULT_COLS)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i in [0, 3, 4, 5, 6, 7, 8, 9, 10]:
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        splitter.addWidget(self._table)

        help_frame = QFrame()
        help_frame.setProperty("class", "panel")
        help_frame.setFixedWidth(280)
        help_layout = QVBoxLayout(help_frame)
        help_layout.setContentsMargins(8, 8, 8, 8)
        help_hdr = QLabel("FIELD REFERENCE")
        help_hdr.setProperty("class", "section-header")
        help_layout.addWidget(help_hdr)
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setPlainText(FIELD_HELP)
        help_text.setStyleSheet(
            "background: transparent; border: none; color: #666666; font-size: 11px;"
        )
        help_layout.addWidget(help_text)
        splitter.addWidget(help_frame)

        splitter.setSizes([900, 280])
        layout.addWidget(splitter)

        self._load_watchlists()

    # ── On-show ───────────────────────────────────────────────────────────

    def on_show(self) -> None:
        self._load_watchlists()

    # ── Presets ───────────────────────────────────────────────────────────

    def _show_presets_menu(self) -> None:
        menu = QMenu(self)

        for name, expr in _BUILTIN_PRESETS:
            action = menu.addAction(name)
            action.triggered.connect(self._make_preset_handler(expr))

        menu.addSeparator()

        try:
            from lens.db.store import get_saved_screens
            saved = get_saved_screens()
        except Exception:
            saved = []

        if saved:
            for row in saved:
                action = menu.addAction(f"★  {row['name']}")
                action.triggered.connect(self._make_preset_handler(row["expression"]))
                action.setData(row["name"])
            menu.addSeparator()
            del_menu = menu.addMenu("Delete saved screen…")
            for row in saved:
                da = del_menu.addAction(row["name"])
                da.triggered.connect(self._make_delete_handler(row["name"]))
        else:
            no_saved = menu.addAction("No saved screens yet")
            no_saved.setEnabled(False)

        menu.exec(self._presets_btn.mapToGlobal(
            self._presets_btn.rect().bottomLeft()
        ))

    def _make_preset_handler(self, expr: str):
        def _handler():
            self._filter_input.setText(expr)
            self._run_screen()
        return _handler

    def _make_delete_handler(self, name: str):
        def _handler():
            reply = QMessageBox.question(
                self,
                "Delete screen",
                f"Delete saved screen '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    from lens.db.store import delete_screen
                    delete_screen(name)
                except Exception as exc:
                    QMessageBox.warning(self, "Error", str(exc))
        return _handler

    # ── Save screen ───────────────────────────────────────────────────────

    def _save_screen(self) -> None:
        expr = self._filter_input.text().strip()
        if not expr:
            self._status_label.setText("Nothing to save — enter a filter first")
            self._status_label.setStyleSheet("color: #ef4444; font-size: 11px;")
            return

        name, ok = QInputDialog.getText(self, "Save screen", "Name this screen:")
        if not ok or not name.strip():
            return
        name = name.strip()

        # Check for overwrite
        try:
            from lens.db.store import get_saved_screens
            existing = {r["name"] for r in get_saved_screens()}
        except Exception:
            existing = set()

        if name in existing:
            reply = QMessageBox.question(
                self,
                "Overwrite?",
                f"A screen named '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            from lens.db.store import save_screen
            save_screen(name, expr)
            self._status_label.setText(f"Saved as '{name}'")
            self._status_label.setStyleSheet("color: #22c55e; font-size: 11px;")
        except Exception as exc:
            self._status_label.setText(f"Save failed: {exc}")
            self._status_label.setStyleSheet("color: #ef4444; font-size: 11px;")

    # ── Run / results ─────────────────────────────────────────────────────

    def _load_watchlists(self) -> None:
        from lens.db.store import list_watchlists
        try:
            wls = list_watchlists()
            current = self._universe_combo.currentData()
            self._universe_combo.clear()
            self._universe_combo.addItem("All Securities", "all")
            for wl in wls:
                self._universe_combo.addItem(wl["name"], wl["name"])
            idx = self._universe_combo.findData(current)
            if idx >= 0:
                self._universe_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def _run_screen(self) -> None:
        from lens.ui.workers import RunScreenerWorker

        expr = self._filter_input.text().strip()
        universe = self._universe_combo.currentData() or "all"

        self._status_label.setText("Running screen…")
        self._status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")

        if self._worker and self._worker.isRunning():
            self._worker.quit()

        self._worker = RunScreenerWorker(expr, universe, parent=self)
        self._worker.result.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_results(self, df) -> None:
        self._df = df
        if df is None or df.empty:
            self._status_label.setText("No results")
            self._status_label.setStyleSheet("color: #555555; font-size: 11px;")
            self._table.setRowCount(0)
            return

        self._status_label.setText(f"{len(df)} result{'s' if len(df) != 1 else ''}")
        self._status_label.setStyleSheet("color: #22c55e; font-size: 11px;")

        self._table.setRowCount(len(df))
        self._table.setSortingEnabled(False)

        for i, (_, row) in enumerate(df.iterrows()):
            self._table.setItem(i, 0, _item(str(row.get("ticker", "")), color=COLOR_AMB, bold=True))
            self._table.setItem(i, 1, _item(str(row.get("name", ""))[:30]))
            self._table.setItem(i, 2, _item(str(row.get("sector", "") or ""), color=COLOR_DIM))
            self._table.setItem(i, 3, _item(
                _fmt(row.get("pe_ratio")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            self._table.setItem(i, 4, _item(
                _fmt(row.get("pb_ratio")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            self._table.setItem(i, 5, _item(
                _fmt(row.get("ev_ebitda")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            div = row.get("dividend_yield")
            self._table.setItem(i, 6, _item(
                _fmt_pct(div),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_POS if (div and div > 0) else COLOR_TEXT, mono=True,
            ))
            self._table.setItem(i, 7, _item(
                _large_num(row.get("market_cap")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            self._table.setItem(i, 8, _item(
                _fmt_pct(row.get("roe")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            self._table.setItem(i, 9, _item(
                _fmt_pct(row.get("roa")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mono=True,
            ))
            rg = row.get("revenue_growth")
            color = COLOR_POS if (rg and rg > 0) else (COLOR_NEG if (rg and rg < 0) else COLOR_TEXT)
            self._table.setItem(i, 10, _item(
                _fmt_pct(rg),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=color, mono=True,
            ))

        self._table.setSortingEnabled(True)

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg[:100]}")
        self._status_label.setStyleSheet("color: #ef4444; font-size: 11px;")

    def _on_double_click(self, row: int, col: int) -> None:
        item = self._table.item(row, 0)
        if item:
            ticker = item.text()
            mw = self.window()
            if hasattr(mw, "open_quote"):
                mw.open_quote(ticker)
