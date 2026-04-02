"""Portfolio analytics: XIRR, TWR, sector attribution, benchmark comparison."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# XIRR — Extended Internal Rate of Return
# ---------------------------------------------------------------------------

def xirr(cashflows: list[tuple[date | str, float]], guess: float = 0.1) -> Optional[float]:
    """
    Compute XIRR given a list of (date, amount) cashflow pairs.
    Negative amounts = cash out (investments). Positive = cash in (returns/sales).
    Uses Newton-Raphson iteration.
    Returns annualised rate as a decimal (e.g. 0.12 = 12%).
    """
    if not cashflows:
        return None

    def to_date(d: date | str) -> date:
        if isinstance(d, str):
            return date.fromisoformat(d)
        return d

    dates = [to_date(d) for d, _ in cashflows]
    amounts = [float(a) for _, a in cashflows]
    base = dates[0]

    def npv(rate: float) -> float:
        return sum(
            amounts[i] / ((1 + rate) ** ((dates[i] - base).days / 365.0))
            for i in range(len(amounts))
        )

    def dnpv(rate: float) -> float:
        return sum(
            -((dates[i] - base).days / 365.0) * amounts[i]
            / ((1 + rate) ** ((dates[i] - base).days / 365.0 + 1))
            for i in range(len(amounts))
        )

    rate = guess
    for _ in range(100):
        f = npv(rate)
        df = dnpv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-8:
            return new_rate
        rate = new_rate

    return rate if abs(npv(rate)) < 0.01 else None


# ---------------------------------------------------------------------------
# TWR — Time-Weighted Return
# ---------------------------------------------------------------------------

def twr(
    transactions: list[dict[str, Any]],
    price_series: dict[str, pd.DataFrame],
) -> Optional[float]:
    """
    Compute Time-Weighted Return for a portfolio.
    Handles external cash flows by dividing the period at each flow date.
    transactions: list of transaction dicts (from DB rows)
    price_series: {ticker: DataFrame with 'date', 'close' columns}
    Returns cumulative TWR as a decimal.
    """
    if not transactions:
        return None

    # Sort by date
    txs = sorted(transactions, key=lambda t: t["date"])

    # Collect unique dates with cash flows
    flow_dates = sorted({t["date"] for t in txs})

    sub_returns = []
    prev_date = flow_dates[0]

    for flow_date in flow_dates[1:]:
        # Compute portfolio value at start and end of sub-period
        # (simplified: use price at start and end for all holdings)
        start_val = _portfolio_value_at(txs, flow_date=prev_date, price_series=price_series, before=True)
        end_val = _portfolio_value_at(txs, flow_date=flow_date, price_series=price_series, before=True)
        if start_val > 0 and end_val > 0:
            sub_returns.append(end_val / start_val)
        prev_date = flow_date

    if not sub_returns:
        return None

    cumulative = 1.0
    for r in sub_returns:
        cumulative *= r
    return cumulative - 1.0


def _portfolio_value_at(
    txs: list[dict[str, Any]],
    flow_date: str,
    price_series: dict[str, pd.DataFrame],
    before: bool = True,
) -> float:
    """
    Estimate portfolio market value at a given date.
    Computes open positions (FIFO) from all transactions up to (and including) flow_date.
    """
    from lens.portfolio.tracker import _fifo_process

    relevant = [t for t in txs if t["date"] <= flow_date]
    positions, _ = _fifo_process(relevant)

    total = 0.0
    for ticker, pos in positions.items():
        df = price_series.get(ticker)
        if df is None or df.empty:
            total += pos.total_cost
            continue
        df_before = df[df["date"] <= flow_date]
        if df_before.empty:
            total += pos.total_cost
        else:
            price = float(df_before.iloc[-1]["close"])
            total += pos.quantity * price
    return total


# ---------------------------------------------------------------------------
# Sector attribution
# ---------------------------------------------------------------------------

def sector_attribution(
    positions: dict[str, Any],  # {ticker: Position}
    sector_map: dict[str, str],  # {ticker: sector}
    prices: dict[str, float],  # {ticker: current_price}
) -> list[dict[str, Any]]:
    """
    Break down portfolio value and weight by sector.
    Returns list of {sector, value, weight_pct} sorted by value desc.
    """
    sector_value: dict[str, float] = defaultdict(float)
    total_value = 0.0

    for ticker, pos in positions.items():
        price = prices.get(ticker, pos.avg_cost)
        val = pos.quantity * price
        sector = sector_map.get(ticker, "Unknown")
        sector_value[sector] += val
        total_value += val

    if not total_value:
        return []

    return sorted(
        [
            {
                "sector": sector,
                "value": val,
                "weight_pct": val / total_value * 100,
            }
            for sector, val in sector_value.items()
        ],
        key=lambda x: x["value"],
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Benchmark comparison
# ---------------------------------------------------------------------------

def benchmark_comparison(
    portfolio_transactions: list[dict[str, Any]],
    portfolio_prices: dict[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
) -> dict[str, Optional[float]]:
    """
    Compare portfolio TWR vs a benchmark's simple price return over the same period.
    Returns {portfolio_twr, benchmark_return, alpha}.
    """
    if benchmark_prices.empty or not portfolio_transactions:
        return {"portfolio_twr": None, "benchmark_return": None, "alpha": None}

    portfolio_return = twr(portfolio_transactions, portfolio_prices)

    # Benchmark simple return over the same period
    txs_sorted = sorted(portfolio_transactions, key=lambda t: t["date"])
    start_date = txs_sorted[0]["date"]
    end_date = txs_sorted[-1]["date"]

    bm_start = benchmark_prices[benchmark_prices["date"] >= start_date]
    if bm_start.empty:
        bm_return = None
    else:
        bm_end = bm_start[bm_start["date"] <= end_date]
        if len(bm_end) < 2:
            bm_return = None
        else:
            bm_first = float(bm_end.iloc[0]["close"])
            bm_last = float(bm_end.iloc[-1]["close"])
            bm_return = (bm_last - bm_first) / bm_first if bm_first else None

    alpha = (
        (portfolio_return - bm_return)
        if portfolio_return is not None and bm_return is not None
        else None
    )

    return {
        "portfolio_twr": portfolio_return,
        "benchmark_return": bm_return,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# Monthly return heatmap data
# ---------------------------------------------------------------------------

def monthly_returns(price_df: pd.DataFrame) -> dict[tuple[int, int], float]:
    """
    Compute month-over-month return from a price DataFrame with 'date', 'close'.
    Returns dict of {(year, month): return_pct}.
    """
    if price_df.empty:
        return {}

    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    # Last close per month
    monthly = df.groupby(["year", "month"])["close"].last().reset_index()
    monthly["prev_close"] = monthly["close"].shift(1)
    monthly = monthly.dropna(subset=["prev_close"])
    monthly["return_pct"] = (monthly["close"] - monthly["prev_close"]) / monthly["prev_close"] * 100

    return {
        (int(row.year), int(row.month)): float(row.return_pct)
        for row in monthly.itertuples()
    }
