"""Portfolio screen — positions, transactions, analytics."""

from __future__ import annotations

from typing import Any, Optional

import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QScrollArea,
    QSplitter,
)

from lens.ui.widgets.data_table import (
    DataTable,
    COLOR_POS, COLOR_NEG, COLOR_DIM, COLOR_AMB, COLOR_TEXT, MONO,
    _item, _num_item, _large_num,
)
from lens.ui.widgets.stat_card import StatCard

C_BG = "#0a0a0a"


class AddTransactionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Transaction")
        self.setMinimumWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ticker = QLineEdit()
        self._ticker.setPlaceholderText("e.g. MC.PA")
        form.addRow("Ticker:", self._ticker)

        self._type = QComboBox()
        self._type.addItems(["BUY", "SELL", "DIVIDEND", "SPLIT"])
        form.addRow("Type:", self._type)

        from PyQt6.QtCore import QDate
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDate(QDate.currentDate())
        self._date.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Date:", self._date)

        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.0001, 1_000_000)
        self._qty.setDecimals(4)
        self._qty.setValue(1)
        form.addRow("Quantity:", self._qty)

        self._price = QDoubleSpinBox()
        self._price.setRange(0.0001, 1_000_000)
        self._price.setDecimals(4)
        self._price.setValue(0)
        self._price.setPrefix("€ ")
        form.addRow("Price:", self._price)

        self._fees = QDoubleSpinBox()
        self._fees.setRange(0, 10_000)
        self._fees.setDecimals(2)
        self._fees.setValue(0)
        self._fees.setPrefix("€ ")
        form.addRow("Fees:", self._fees)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Optional notes")
        form.addRow("Notes:", self._notes)

        layout.addLayout(form)

        self._status = QLabel()
        self._status.setStyleSheet("color: #ef4444; font-size: 11px;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        ticker = self._ticker.text().strip().upper()
        if not ticker:
            self._status.setText("Ticker is required.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "ticker":  self._ticker.text().strip().upper(),
            "type":    self._type.currentText(),
            "date":    self._date.date().toString("yyyy-MM-dd"),
            "qty":     self._qty.value(),
            "price":   self._price.value(),
            "fees":    self._fees.value(),
            "notes":   self._notes.text().strip() or None,
        }


class SummaryBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setProperty("class", "panel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(0)

        self._cards: dict[str, StatCard] = {}
        for label in ["Market Value", "Invested", "P&L", "P&L%", "XIRR"]:
            card = StatCard(label)
            card.setMinimumWidth(130)
            self._cards[label] = card
            layout.addWidget(card)
            if label != "XIRR":
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet("color: #1e1e1e;")
                layout.addWidget(sep)
        layout.addStretch()

    def update_summary(self, summary: Any) -> None:
        pnl = summary.total_unrealized_pnl
        pnl_pct = summary.total_unrealized_pnl_pct
        color = COLOR_POS if pnl >= 0 else COLOR_NEG
        sign = "+" if pnl >= 0 else ""

        self._cards["Market Value"].set_value(_large_num(summary.total_market_value))
        self._cards["Invested"].set_value(_large_num(summary.total_cost))
        self._cards["P&L"].set_value(
            f"{sign}{_large_num(pnl, currency='').strip()}", color
        )
        self._cards["P&L%"].set_value(f"{sign}{pnl_pct:.2f}%", color)
        self._cards["XIRR"].set_value("—")  # computed separately if needed


class PositionsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        cols = ["Ticker", "Name", "Qty", "Avg Cost", "Last Price",
                "Mkt Value", "Unreal P&L", "Unreal P&L%", "Weight"]
        self._table = DataTable(cols)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in [0, 2, 3, 4, 5, 6, 7, 8]:
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self._table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)
        self._rows: list[dict] = []
        self.open_quote_requested = None

    def update_positions(self, rows: list[dict]) -> None:
        self._rows = rows
        self._table.setRowCount(len(rows))
        self._table.setSortingEnabled(False)

        for i, row in enumerate(rows):
            pnl = row.get("unrealized_pnl", 0) or 0
            pnl_pct = row.get("unrealized_pnl_pct", 0) or 0
            color = COLOR_POS if pnl >= 0 else COLOR_NEG
            sign = "+" if pnl >= 0 else ""

            self._table.setItem(i, 0, _item(row["ticker"], color=COLOR_AMB, bold=True))
            self._table.setItem(i, 1, _item(row.get("name", "")[:28]))
            self._table.setItem(i, 2, _item(
                f"{row.get('quantity', 0):,.2f}",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))
            self._table.setItem(i, 3, _item(
                f"{row.get('avg_cost', 0):,.2f}",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))
            self._table.setItem(i, 4, _item(
                f"{row.get('current_price', 0):,.2f}" if row.get('current_price') else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_TEXT, mono=True,
            ))
            self._table.setItem(i, 5, _item(
                _large_num(row.get("market_value")),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_TEXT, mono=True, bold=True,
            ))
            self._table.setItem(i, 6, _item(
                f"{sign}{_large_num(pnl, currency='').strip()}",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=color, mono=True,
            ))
            self._table.setItem(i, 7, _item(
                f"{sign}{pnl_pct:.2f}%",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=color, mono=True,
            ))
            self._table.setItem(i, 8, _item(
                f"{row.get('weight_pct', 0):.1f}%",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))

        self._table.setSortingEnabled(True)

    def _on_double_click(self, row: int, col: int) -> None:
        if 0 <= row < len(self._rows):
            ticker = self._rows[row].get("ticker", "")
            if ticker and callable(self.open_quote_requested):
                self.open_quote_requested(ticker)


class TransactionsTab(QWidget):
    def __init__(self, account_name: str, refresh_callback=None, parent=None) -> None:
        super().__init__(parent)
        self._account = account_name
        self._refresh_callback = refresh_callback
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 6)
        toolbar.addStretch()
        add_btn = QPushButton("+ Add Transaction")
        add_btn.setProperty("class", "primary")
        add_btn.clicked.connect(self._add_transaction)
        toolbar.addWidget(add_btn)
        layout.addLayout(toolbar)

        cols = ["Date", "Ticker", "Type", "Qty", "Price", "Fees", "Total", "Notes"]
        self._table = DataTable(cols)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        TX_COLORS = {"BUY": COLOR_POS, "SELL": COLOR_NEG, "DIVIDEND": COLOR_AMB}
        self._tx_colors = TX_COLORS

    def update_transactions(self, txs: list) -> None:
        self._table.setRowCount(len(txs))
        self._table.setSortingEnabled(False)

        for i, tx in enumerate(txs):
            tx_type = tx["type"]
            color = self._tx_colors.get(tx_type, COLOR_DIM)
            qty   = float(tx.get("quantity", 0))
            price = float(tx.get("price", 0))
            fees  = float(tx.get("fees") or 0)
            total = qty * price + fees

            self._table.setItem(i, 0, _item(str(tx.get("date", ""))[:10], color=COLOR_DIM))
            self._table.setItem(i, 1, _item(str(tx.get("ticker", "")), color=COLOR_AMB, bold=True))
            self._table.setItem(i, 2, _item(tx_type, color=color, bold=True))
            self._table.setItem(i, 3, _item(
                f"{qty:,.4f}",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                mono=True,
            ))
            self._table.setItem(i, 4, _item(
                f"{price:,.2f}",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                mono=True,
            ))
            self._table.setItem(i, 5, _item(
                f"{fees:,.2f}" if fees else "—",
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                color=COLOR_DIM, mono=True,
            ))
            self._table.setItem(i, 6, _item(
                _large_num(total),
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                mono=True, bold=True,
            ))
            self._table.setItem(i, 7, _item(str(tx.get("notes") or ""), color=COLOR_DIM))

        self._table.setSortingEnabled(True)

    def _add_transaction(self) -> None:
        dlg = AddTransactionDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.values()

        from lens.db.store import (
            create_account, get_security_by_ticker, upsert_security, add_transaction
        )
        from lens.config import Config
        cfg = Config()

        sec = get_security_by_ticker(vals["ticker"])
        if sec is None:
            # Try to fetch from Yahoo
            from lens.ui.workers import FetchAndStoreWorker
            reply = QMessageBox.question(
                self, "Fetch security?",
                f"{vals['ticker']} not in database. Fetch from Yahoo Finance?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            # Simple sync fetch for ticker name
            import asyncio
            from lens.data.yahoo import get_quote

            async def _fetch():
                q = await get_quote(vals["ticker"])
                upsert_security(
                    ticker=vals["ticker"],
                    name=q.get("name", vals["ticker"]),
                    currency=q.get("currency", "EUR"),
                )

            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_fetch())
                loop.close()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not fetch {vals['ticker']}: {e}")
                return

        try:
            create_account(self._account)
            add_transaction(
                account_name=self._account,
                ticker=vals["ticker"],
                tx_type=vals["type"],
                date=vals["date"],
                quantity=vals["qty"],
                price=vals["price"],
                fees=vals["fees"],
                notes=vals["notes"],
            )
            # Refresh portfolio
            if callable(self._refresh_callback):
                self._refresh_callback()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))


class AnalyticsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Row 1: 6 stat cards ──────────────────────────────────────────
        cards_frame = QFrame()
        cards_frame.setProperty("class", "panel")
        cards_row = QHBoxLayout(cards_frame)
        cards_row.setContentsMargins(12, 8, 12, 8)
        cards_row.setSpacing(4)

        self._beta_card     = StatCard("PORTFOLIO BETA",     "—")
        self._sharpe_card   = StatCard("SHARPE RATIO",       "—")
        self._sortino_card  = StatCard("SORTINO RATIO",      "—")
        self._maxdd_card    = StatCard("MAX DRAWDOWN",       "—")
        self._vol_card      = StatCard("ANNUALISED VOL",     "—")
        self._best_m_card   = StatCard("BEST MONTH",         "—")
        self._worst_m_card  = StatCard("WORST MONTH",        "—")

        for card in (self._beta_card, self._sharpe_card, self._sortino_card,
                     self._maxdd_card, self._vol_card,
                     self._best_m_card, self._worst_m_card):
            cards_row.addWidget(card)
        layout.addWidget(cards_frame)

        # ── Row 2: drawdown chart ─────────────────────────────────────────
        dd_frame = QFrame()
        dd_frame.setProperty("class", "panel")
        dd_lay = QVBoxLayout(dd_frame)
        dd_lay.setContentsMargins(12, 8, 12, 8)
        dd_lay.setSpacing(4)
        dd_hdr = QLabel("DRAWDOWN FROM PEAK")
        dd_hdr.setProperty("class", "section-header")
        dd_lay.addWidget(dd_hdr)

        import pyqtgraph as pg
        self._dd_plot = pg.PlotWidget()
        self._dd_plot.setBackground("#000000")
        self._dd_plot.setMinimumHeight(120)
        self._dd_plot.showAxis("top", False)
        self._dd_plot.showAxis("right", False)
        for side in ("left", "bottom"):
            ax = self._dd_plot.getAxis(side)
            ax.setTextPen(pg.mkPen("#555555"))
            ax.setPen(pg.mkPen("#222222"))
            ax.setStyle(tickFont=pg.QtGui.QFont("Consolas", 8))
        self._dd_plot.setMenuEnabled(False)
        self._dd_plot.hideButtons()
        dd_lay.addWidget(self._dd_plot)
        dd_frame.setFixedHeight(160)
        layout.addWidget(dd_frame)

        # ── Row 3: existing left+right panels ────────────────────────────
        lower_row = QHBoxLayout()
        lower_row.setSpacing(10)

        # Left: sector bars
        left = QFrame()
        left.setProperty("class", "panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)

        sec_hdr = QLabel("SECTOR ALLOCATION")
        sec_hdr.setProperty("class", "section-header")
        left_layout.addWidget(sec_hdr)

        self._sector_widget = QWidget()
        self._sector_layout = QVBoxLayout(self._sector_widget)
        self._sector_layout.setSpacing(8)
        left_layout.addWidget(self._sector_widget)
        left_layout.addStretch()
        lower_row.addWidget(left, 1)

        # Right: benchmark + heatmap
        right = QVBoxLayout()

        # Benchmark — now with 6 cards (3 original + 3 new)
        bm_frame = QFrame()
        bm_frame.setProperty("class", "panel")
        bm_layout = QVBoxLayout(bm_frame)
        bm_layout.setContentsMargins(12, 8, 12, 8)
        bm_hdr = QLabel("BENCHMARK COMPARISON  (^FCHI CAC 40)")
        bm_hdr.setProperty("class", "section-header")
        bm_layout.addWidget(bm_hdr)

        bm_row1 = QHBoxLayout()
        self._bm_portfolio_card = StatCard("Portfolio TWR")
        self._bm_bench_card     = StatCard("Benchmark Return")
        self._bm_alpha_card     = StatCard("Alpha")
        bm_row1.addWidget(self._bm_portfolio_card)
        bm_row1.addWidget(self._bm_bench_card)
        bm_row1.addWidget(self._bm_alpha_card)
        bm_layout.addLayout(bm_row1)

        bm_row2 = QHBoxLayout()
        self._bm_corr_card  = StatCard("Correlation")
        self._bm_upcap_card = StatCard("Up Capture")
        self._bm_dncap_card = StatCard("Down Capture")
        bm_row2.addWidget(self._bm_corr_card)
        bm_row2.addWidget(self._bm_upcap_card)
        bm_row2.addWidget(self._bm_dncap_card)
        bm_layout.addLayout(bm_row2)
        right.addWidget(bm_frame)

        # Monthly heatmap
        hm_frame = QFrame()
        hm_frame.setProperty("class", "panel")
        hm_layout = QVBoxLayout(hm_frame)
        hm_layout.setContentsMargins(12, 8, 12, 8)
        hm_hdr = QLabel("MONTHLY RETURNS")
        hm_hdr.setProperty("class", "section-header")
        hm_layout.addWidget(hm_hdr)

        self._heatmap_widget = QWidget()
        self._heatmap_layout = QGridLayout(self._heatmap_widget)
        self._heatmap_layout.setSpacing(3)
        hm_layout.addWidget(self._heatmap_widget)
        right.addWidget(hm_frame)
        right.addStretch()

        right_widget = QWidget()
        right_widget.setLayout(right)
        lower_row.addWidget(right_widget, 1)

        lower_widget = QWidget()
        lower_widget.setLayout(lower_row)
        layout.addWidget(lower_widget)
        layout.addStretch()

    def update_sectors(self, sectors: list[dict]) -> None:
        # Clear
        while self._sector_layout.count():
            item = self._sector_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for item in sectors:
            row = QHBoxLayout()
            lbl = QLabel(f"{item['sector'][:22]:<22}")
            lbl.setFixedWidth(170)
            lbl.setStyleSheet("font-size: 12px; color: #e8e8e8;")
            row.addWidget(lbl)

            bar_frame = QFrame()
            bar_frame.setFixedHeight(16)
            pct = item["weight_pct"]
            bar_frame.setMinimumWidth(int(pct * 2.5))
            bar_frame.setStyleSheet(f"background-color: #f59e0b; border-radius: 1px;")
            row.addWidget(bar_frame)

            pct_lbl = QLabel(f"{pct:.1f}%")
            pct_lbl.setStyleSheet(
                'font-family: "JetBrains Mono", Consolas, monospace; '
                "font-size: 11px; color: #94a3b8;"
            )
            pct_lbl.setFixedWidth(45)
            row.addWidget(pct_lbl)
            row.addStretch()

            container = QWidget()
            container.setLayout(row)
            self._sector_layout.addWidget(container)

    def update_benchmark(self, data: dict) -> None:
        def pct_str(v):
            if v is None:
                return "—"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v * 100:.2f}%"

        port = data.get("portfolio_twr")
        bench = data.get("benchmark_return")
        alpha = data.get("alpha")

        self._bm_portfolio_card.set_value(pct_str(port),
            "#22c55e" if (port and port >= 0) else "#ef4444" if port else None)
        self._bm_bench_card.set_value(pct_str(bench),
            "#22c55e" if (bench and bench >= 0) else "#ef4444" if bench else None)
        self._bm_alpha_card.set_value(pct_str(alpha),
            "#22c55e" if (alpha and alpha >= 0) else "#ef4444" if alpha else None)

    def update_analytics_metrics(self, data: dict) -> None:
        """Update all new stat cards + drawdown chart from FetchAnalyticsWorker output."""
        import pyqtgraph as pg
        import numpy as np

        def _pct(v, decimals=1):
            if v is None:
                return "—"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v * 100:.{decimals}f}%"

        def _num(v, decimals=2):
            if v is None:
                return "—"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.{decimals}f}"

        beta = data.get("beta")
        self._beta_card.set_value(
            f"β {beta:.2f}" if beta is not None else "—",
            "#f59e0b" if beta is not None else None,
        )
        sharpe = data.get("sharpe")
        self._sharpe_card.set_value(
            _num(sharpe), "#22c55e" if (sharpe and sharpe > 0) else "#ef4444" if sharpe else None
        )
        sortino = data.get("sortino")
        self._sortino_card.set_value(
            _num(sortino), "#22c55e" if (sortino and sortino > 0) else "#ef4444" if sortino else None
        )
        maxdd = data.get("max_drawdown")
        self._maxdd_card.set_value(
            _pct(maxdd) if maxdd is not None else "—",
            "#ef4444" if maxdd is not None else None,
        )
        vol = data.get("volatility")
        self._vol_card.set_value(
            f"{vol * 100:.1f}%" if vol is not None else "—",
            "#f59e0b" if vol is not None else None,
        )
        self._best_m_card.set_value(data.get("best_month") or "—", "#22c55e")
        self._worst_m_card.set_value(data.get("worst_month") or "—", "#ef4444")

        # Extended benchmark cards (populated from analytics worker too)
        corr = data.get("correlation")
        self._bm_corr_card.set_value(f"{corr:.2f}" if corr is not None else "—")
        upcap = data.get("up_capture")
        self._bm_upcap_card.set_value(
            f"{upcap:.0f}%" if upcap is not None else "—",
            "#22c55e" if (upcap and upcap >= 100) else "#f59e0b" if upcap else None,
        )
        dncap = data.get("down_capture")
        self._bm_dncap_card.set_value(
            f"{dncap:.0f}%" if dncap is not None else "—",
            "#22c55e" if (dncap and dncap <= 100) else "#ef4444" if dncap else None,
        )

        # Drawdown chart
        dd_series = data.get("drawdown_series", [])
        if dd_series:
            xs = np.arange(len(dd_series), dtype=float)
            ys = np.array([v for _, v in dd_series], dtype=float)
            self._dd_plot.clear()
            pen = pg.mkPen(color="#ef4444", width=1.5)
            self._dd_plot.plot(xs, ys, pen=pen)
            # Red fill under the line
            fill = pg.FillBetweenItem(
                self._dd_plot.plot(xs, ys, pen=pg.mkPen(None)),
                self._dd_plot.plot(xs, np.zeros_like(ys), pen=pg.mkPen(None)),
                brush=pg.mkBrush(239, 68, 68, 60),
            )
            self._dd_plot.addItem(fill)
            # Zero line
            self._dd_plot.addLine(y=0, pen=pg.mkPen("#333333", width=1))
            # X ticks: sample ~6 dates
            dates = [d for d, _ in dd_series]
            step = max(1, len(dates) // 6)
            ticks = [(float(i), dates[i][:7]) for i in range(0, len(dates), step)]
            self._dd_plot.getAxis("bottom").setTicks([ticks])
            y_min = float(np.min(ys))
            self._dd_plot.setYRange(y_min * 1.1, 0.02, padding=0)

    def update_heatmap(self, monthly: dict) -> None:
        # Clear
        while self._heatmap_layout.count():
            item = self._heatmap_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        years = sorted({y for y, m in monthly.keys()}, reverse=True)

        # Header row
        for col, month in enumerate(MONTHS):
            lbl = QLabel(month)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 9px; color: #555555; font-weight: 700;")
            lbl.setFixedSize(36, 16)
            self._heatmap_layout.addWidget(lbl, 0, col + 1)

        for row_idx, year in enumerate(years[:5]):
            yr_lbl = QLabel(str(year))
            yr_lbl.setStyleSheet("font-size: 9px; color: #555555;")
            yr_lbl.setFixedWidth(36)
            self._heatmap_layout.addWidget(yr_lbl, row_idx + 1, 0)

            for col, month_num in enumerate(range(1, 13)):
                ret = monthly.get((year, month_num))
                cell = QLabel(f"{ret:.1f}" if ret is not None else "")
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFixedSize(36, 22)
                if ret is not None:
                    intensity = min(abs(ret) / 5.0, 1.0)
                    if ret >= 0:
                        g = int(80 + 80 * intensity)
                        bg = f"#{0:02x}{g:02x}{0:02x}"
                    else:
                        r = int(80 + 80 * intensity)
                        bg = f"#{r:02x}{0:02x}{0:02x}"
                    cell.setStyleSheet(
                        f"background-color: {bg}; font-size: 9px; color: #e8e8e8; border-radius: 1px;"
                    )
                else:
                    cell.setStyleSheet(
                        "background-color: #111111; font-size: 9px; color: #333333; border-radius: 1px;"
                    )
                self._heatmap_layout.addWidget(cell, row_idx + 1, col + 1)


class PortfolioScreen(QWidget):
    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._worker = None
        self._bm_worker = None
        self._analytics_worker = None

        from lens.config import Config
        self._account = Config().default_account

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Summary bar at top
        self._summary_bar = SummaryBar()
        layout.addWidget(self._summary_bar)

        # Tab widget
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._positions_tab = PositionsTab()
        self._positions_tab.open_quote_requested = self._open_quote
        self._tabs.addTab(self._positions_tab, "Positions")

        self._tx_tab = TransactionsTab(self._account, refresh_callback=self.load_data)
        self._tabs.addTab(self._tx_tab, "Transactions")

        self._analytics_tab = AnalyticsTab()
        self._tabs.addTab(self._analytics_tab, "Analytics")

        self._loading_label = QLabel("Loading portfolio…")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet("color: #555555;")

    def on_show(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        from lens.ui.workers import FetchPortfolioWorker

        if self._worker and self._worker.isRunning():
            return

        self._worker = FetchPortfolioWorker(self._account, self)
        self._worker.result.connect(self._on_portfolio_result)
        self._worker.error.connect(lambda e: None)
        self._worker.start()

    def _on_portfolio_result(self, summary: Any) -> None:
        self._summary_bar.update_summary(summary)
        self._positions_tab.update_positions(summary.position_rows())

        from lens.db.store import get_transactions
        txs = list(reversed(get_transactions(self._account)))
        self._tx_tab.update_transactions(txs)

        # Sector attribution
        from lens.db.store import get_security_by_ticker
        from lens.portfolio.analytics import sector_attribution

        sector_map = {}
        for ticker, pos in summary.positions.items():
            sec = get_security_by_ticker(ticker)
            sector_map[ticker] = (sec["sector"] if sec and sec["sector"] else "Unknown")

        sectors = sector_attribution(summary.positions, sector_map, summary.prices)
        self._analytics_tab.update_sectors(sectors)

        # Monthly returns
        from lens.db.store import get_prices
        from lens.portfolio.analytics import monthly_returns

        # Use first position for heatmap
        monthly: dict = {}
        for ticker in list(summary.positions.keys())[:1]:
            df = get_prices(ticker)
            if not df.empty:
                monthly = monthly_returns(df)
                break
        self._analytics_tab.update_heatmap(monthly)

        # Benchmark
        self._load_benchmark()
        # Analytics
        self._load_analytics()

    def _load_benchmark(self) -> None:
        from lens.ui.workers import FetchBenchmarkWorker

        if self._bm_worker and self._bm_worker.isRunning():
            return

        self._bm_worker = FetchBenchmarkWorker(self._account, "^FCHI", self)
        self._bm_worker.result.connect(self._analytics_tab.update_benchmark)
        self._bm_worker.start()

    def _load_analytics(self) -> None:
        from lens.ui.workers import FetchAnalyticsWorker

        if self._analytics_worker and self._analytics_worker.isRunning():
            return

        self._analytics_worker = FetchAnalyticsWorker(self._account, self)
        self._analytics_worker.analytics_ready.connect(
            self._analytics_tab.update_analytics_metrics
        )
        self._analytics_worker.error.connect(lambda e: None)
        self._analytics_worker.start()

    def _open_quote(self, ticker: str) -> None:
        mw = self.window()
        if hasattr(mw, "open_quote"):
            mw.open_quote(ticker)
