"""Portfolio position tracking with FIFO cost basis and P&L calculation."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from lens.db.store import get_transactions, list_accounts


@dataclass
class Lot:
    """A single purchase lot for FIFO tracking."""
    date: str
    quantity: float
    cost_per_share: float  # in position currency, fx-adjusted
    fees: float = 0.0


@dataclass
class Position:
    ticker: str
    name: str
    currency: str
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> float:
        return sum(lot.quantity for lot in self.lots)

    @property
    def total_cost(self) -> float:
        return sum(lot.quantity * lot.cost_per_share + lot.fees for lot in self.lots)

    @property
    def avg_cost(self) -> float:
        q = self.quantity
        return self.total_cost / q if q else 0.0

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.avg_cost) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        cost = self.total_cost
        return ((current_price * self.quantity - cost) / cost * 100) if cost else 0.0

    def market_value(self, current_price: float) -> float:
        return current_price * self.quantity


@dataclass
class RealizedPnL:
    ticker: str
    quantity: float
    proceeds: float
    cost_basis: float
    pnl: float
    pnl_pct: float


def _fifo_process(
    transactions: list[Any],
) -> tuple[dict[str, Position], list[RealizedPnL]]:
    """
    Process a sorted list of transactions using FIFO to build positions
    and compute realized P&L.
    """
    # lots[ticker] = deque of (qty, cost_per_share, date, fees)
    lots: dict[str, deque[Lot]] = defaultdict(deque)
    positions: dict[str, Position] = {}
    realized: list[RealizedPnL] = []

    # Initialize position metadata
    name_map: dict[str, str] = {}
    currency_map: dict[str, str] = {}

    for tx in transactions:
        ticker = tx["ticker"]
        name_map[ticker] = tx.get("name", ticker)
        currency_map[ticker] = tx.get("currency", "EUR")

    for tx in transactions:
        ticker = tx["ticker"]
        tx_type = tx["type"]
        qty = float(tx["quantity"])
        price = float(tx["price"])
        fees = float(tx.get("fees") or 0)
        fx_rate = float(tx.get("fx_rate") or 1.0)
        # Cost per share adjusted for FX (everything in portfolio base currency EUR)
        cost_per_share = price * fx_rate

        if tx_type == "BUY":
            lots[ticker].append(Lot(
                date=tx["date"],
                quantity=qty,
                cost_per_share=cost_per_share,
                fees=fees,
            ))

        elif tx_type == "SELL":
            remaining_sell = qty
            total_cost_basis = 0.0
            while remaining_sell > 0 and lots[ticker]:
                lot = lots[ticker][0]
                if lot.quantity <= remaining_sell:
                    total_cost_basis += lot.quantity * lot.cost_per_share + lot.fees
                    remaining_sell -= lot.quantity
                    lots[ticker].popleft()
                else:
                    # Partial lot
                    frac = remaining_sell / lot.quantity
                    total_cost_basis += remaining_sell * lot.cost_per_share + lot.fees * frac
                    lot.quantity -= remaining_sell
                    lot.fees *= (1 - frac)
                    remaining_sell = 0

            proceeds = qty * cost_per_share - fees
            pnl = proceeds - total_cost_basis
            pnl_pct = (pnl / total_cost_basis * 100) if total_cost_basis else 0.0
            realized.append(RealizedPnL(
                ticker=ticker,
                quantity=qty,
                proceeds=proceeds,
                cost_basis=total_cost_basis,
                pnl=pnl,
                pnl_pct=pnl_pct,
            ))

        elif tx_type == "SPLIT":
            # qty here represents the ratio (e.g. 2.0 for a 2-for-1 split)
            for lot in lots[ticker]:
                lot.quantity *= qty
                lot.cost_per_share /= qty

        elif tx_type == "DIVIDEND":
            pass  # Dividends tracked but don't affect cost basis

    # Build Position objects from remaining lots
    for ticker, lot_deque in lots.items():
        if lot_deque:
            pos = Position(
                ticker=ticker,
                name=name_map.get(ticker, ticker),
                currency=currency_map.get(ticker, "EUR"),
                lots=list(lot_deque),
            )
            positions[ticker] = pos

    return positions, realized


@dataclass
class PortfolioSummary:
    account_name: str
    positions: dict[str, Position]
    realized: list[RealizedPnL]
    prices: dict[str, float]  # ticker -> current price

    @property
    def total_market_value(self) -> float:
        return sum(
            pos.market_value(self.prices.get(ticker, pos.avg_cost))
            for ticker, pos in self.positions.items()
        )

    @property
    def total_cost(self) -> float:
        return sum(pos.total_cost for pos in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(
            pos.unrealized_pnl(self.prices.get(ticker, pos.avg_cost))
            for ticker, pos in self.positions.items()
        )

    @property
    def total_unrealized_pnl_pct(self) -> float:
        cost = self.total_cost
        return (self.total_unrealized_pnl / cost * 100) if cost else 0.0

    @property
    def total_realized_pnl(self) -> float:
        return sum(r.pnl for r in self.realized)

    def position_rows(self) -> list[dict[str, Any]]:
        """Return list of dicts suitable for tabular display."""
        rows = []
        total_value = self.total_market_value or 1.0
        for ticker, pos in sorted(self.positions.items()):
            current_price = self.prices.get(ticker, pos.avg_cost)
            market_val = pos.market_value(current_price)
            rows.append({
                "ticker": ticker,
                "name": pos.name,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": current_price,
                "market_value": market_val,
                "unrealized_pnl": pos.unrealized_pnl(current_price),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct(current_price),
                "weight_pct": (market_val / total_value * 100),
                "currency": pos.currency,
            })
        return rows


def build_portfolio(
    account_name: str,
    prices: Optional[dict[str, float]] = None,
) -> PortfolioSummary:
    """
    Build a PortfolioSummary for a named account using current transactions from DB.
    prices: optional dict of {ticker: current_price}. If absent, uses avg cost.
    """
    txs = get_transactions(account_name)
    txs_sorted = sorted(txs, key=lambda t: (t["date"], t["id"]))
    positions, realized = _fifo_process(txs_sorted)
    return PortfolioSummary(
        account_name=account_name,
        positions=positions,
        realized=realized,
        prices=prices or {},
    )


def get_portfolio_tickers(account_name: str) -> list[str]:
    """Return list of tickers currently held in the portfolio."""
    summary = build_portfolio(account_name)
    return [t for t, p in summary.positions.items() if p.quantity > 0]
