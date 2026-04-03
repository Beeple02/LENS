"""Database access layer for LENS. No ORM — raw SQL."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

import pandas as pd

from lens.config import Config

_config = Config()
_DB_PATH = _config.db_path
from lens._resources import resource_path as _rp
_SCHEMA_PATH = _rp("db/schema.sql")


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or _DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_conn(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Create all tables from schema.sql if they don't exist."""
    path = db_path or _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = _SCHEMA_PATH.read_text()
    with db_conn(path) as conn:
        conn.executescript(schema)


# ---------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------

def upsert_security(
    ticker: str,
    name: str,
    isin: Optional[str] = None,
    mic: str = "XPAR",
    currency: str = "EUR",
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert or update a security. Returns its id."""
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO securities (ticker, isin, name, mic, currency, sector, industry)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                isin     = excluded.isin,
                name     = excluded.name,
                mic      = excluded.mic,
                currency = excluded.currency,
                sector   = COALESCE(excluded.sector, sector),
                industry = COALESCE(excluded.industry, industry)
            """,
            (ticker, isin, name, mic, currency, sector, industry),
        )
        row = conn.execute("SELECT id FROM securities WHERE ticker = ?", (ticker,)).fetchone()
        return row["id"]


def get_security_by_ticker(ticker: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM securities WHERE ticker = ?", (ticker,)
        ).fetchone()


def get_security_by_isin(isin: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM securities WHERE isin = ?", (isin,)
        ).fetchone()


def list_securities(db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute("SELECT * FROM securities ORDER BY ticker").fetchall()


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def upsert_price_history(
    ticker: str,
    ohlcv_list: list[dict[str, Any]],
    db_path: Optional[Path] = None,
) -> None:
    """Bulk upsert OHLCV records for a ticker. ohlcv_list items must have keys:
    date, open, high, low, close, adj_close, volume."""
    with db_conn(db_path) as conn:
        row = conn.execute("SELECT id FROM securities WHERE ticker = ?", (ticker,)).fetchone()
        if row is None:
            raise ValueError(f"Security '{ticker}' not found in database")
        security_id = row["id"]
        conn.executemany(
            """
            INSERT INTO prices (security_id, date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(security_id, date) DO UPDATE SET
                open      = excluded.open,
                high      = excluded.high,
                low       = excluded.low,
                close     = excluded.close,
                adj_close = excluded.adj_close,
                volume    = excluded.volume
            """,
            [
                (
                    security_id,
                    row_["date"],
                    row_.get("open"),
                    row_.get("high"),
                    row_.get("low"),
                    row_["close"],
                    row_.get("adj_close"),
                    row_.get("volume"),
                )
                for row_ in ohlcv_list
            ],
        )


def get_prices(
    ticker: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Return price history as a DataFrame."""
    with db_conn(db_path) as conn:
        row = conn.execute("SELECT id FROM securities WHERE ticker = ?", (ticker,)).fetchone()
        if row is None:
            return pd.DataFrame()
        security_id = row["id"]
        query = "SELECT * FROM prices WHERE security_id = ?"
        params: list[Any] = [security_id]
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date"
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])


def get_latest_price_date(ticker: str, db_path: Optional[Path] = None) -> Optional[str]:
    with db_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT p.date FROM prices p
            JOIN securities s ON s.id = p.security_id
            WHERE s.ticker = ?
            ORDER BY p.date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        return row["date"] if row else None


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------

def upsert_fundamentals(
    ticker: str,
    data: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    with db_conn(db_path) as conn:
        row = conn.execute("SELECT id FROM securities WHERE ticker = ?", (ticker,)).fetchone()
        if row is None:
            raise ValueError(f"Security '{ticker}' not found in database")
        security_id = row["id"]
        conn.execute(
            """
            INSERT INTO fundamentals (
                security_id, fetched_at, pe_ratio, forward_pe, pb_ratio, ps_ratio,
                ev_ebitda, dividend_yield, payout_ratio, market_cap, enterprise_value,
                revenue_ttm, ebitda, net_income, debt_to_equity, current_ratio,
                roe, roa, revenue_growth, earnings_growth
            ) VALUES (
                ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                security_id,
                data.get("pe_ratio"),
                data.get("forward_pe"),
                data.get("pb_ratio"),
                data.get("ps_ratio"),
                data.get("ev_ebitda"),
                data.get("dividend_yield"),
                data.get("payout_ratio"),
                data.get("market_cap"),
                data.get("enterprise_value"),
                data.get("revenue_ttm"),
                data.get("ebitda"),
                data.get("net_income"),
                data.get("debt_to_equity"),
                data.get("current_ratio"),
                data.get("roe"),
                data.get("roa"),
                data.get("revenue_growth"),
                data.get("earnings_growth"),
            ),
        )


def get_latest_fundamentals(
    ticker: str, db_path: Optional[Path] = None
) -> Optional[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT f.* FROM fundamentals f
            JOIN securities s ON s.id = f.security_id
            WHERE s.ticker = ?
            ORDER BY f.fetched_at DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()


def fundamentals_stale(
    ticker: str,
    max_age_hours: int = 24,
    db_path: Optional[Path] = None,
) -> bool:
    row = get_latest_fundamentals(ticker, db_path)
    if row is None:
        return True
    fetched_at = datetime.fromisoformat(row["fetched_at"])
    return datetime.utcnow() - fetched_at > timedelta(hours=max_age_hours)


def get_all_fundamentals_for_screen(db_path: Optional[Path] = None) -> pd.DataFrame:
    """Return latest fundamentals joined with securities info for the screener."""
    with db_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.ticker, s.name, s.sector, s.industry, s.mic, s.currency,
                   f.pe_ratio, f.forward_pe, f.pb_ratio, f.ps_ratio, f.ev_ebitda,
                   f.dividend_yield, f.payout_ratio, f.market_cap, f.enterprise_value,
                   f.revenue_ttm, f.ebitda, f.net_income, f.debt_to_equity,
                   f.current_ratio, f.roe, f.roa, f.revenue_growth, f.earnings_growth,
                   f.fetched_at
            FROM securities s
            JOIN fundamentals f ON f.security_id = s.id
            WHERE f.id IN (
                SELECT MAX(id) FROM fundamentals GROUP BY security_id
            )
            ORDER BY s.ticker
            """
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Portfolio accounts
# ---------------------------------------------------------------------------

def create_account(name: str, currency: str = "EUR", db_path: Optional[Path] = None) -> int:
    with db_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portfolio_accounts (name, currency) VALUES (?, ?)",
            (name, currency),
        )
        row = conn.execute(
            "SELECT id FROM portfolio_accounts WHERE name = ?", (name,)
        ).fetchone()
        return row["id"]


def list_accounts(db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute("SELECT * FROM portfolio_accounts ORDER BY name").fetchall()


def get_account(name: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM portfolio_accounts WHERE name = ?", (name,)
        ).fetchone()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def add_transaction(
    account_name: str,
    ticker: str,
    tx_type: str,
    date: str,
    quantity: float,
    price: float,
    fees: float = 0.0,
    currency: str = "EUR",
    fx_rate: float = 1.0,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    with db_conn(db_path) as conn:
        account = conn.execute(
            "SELECT id FROM portfolio_accounts WHERE name = ?", (account_name,)
        ).fetchone()
        if account is None:
            raise ValueError(f"Account '{account_name}' not found")
        security = conn.execute(
            "SELECT id FROM securities WHERE ticker = ?", (ticker,)
        ).fetchone()
        if security is None:
            raise ValueError(f"Security '{ticker}' not found")
        cursor = conn.execute(
            """
            INSERT INTO transactions
                (account_id, security_id, type, date, quantity, price, fees, currency, fx_rate, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (account["id"], security["id"], tx_type, date, quantity, price, fees, currency, fx_rate, notes),
        )
        return cursor.lastrowid


def get_transactions(
    account_name: str,
    ticker: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[sqlite3.Row]:
    with db_conn(db_path) as conn:
        account = conn.execute(
            "SELECT id FROM portfolio_accounts WHERE name = ?", (account_name,)
        ).fetchone()
        if account is None:
            return []
        query = """
            SELECT t.*, s.ticker, s.name, s.currency as sec_currency
            FROM transactions t
            JOIN securities s ON s.id = t.security_id
            WHERE t.account_id = ?
        """
        params: list[Any] = [account["id"]]
        if ticker:
            query += " AND s.ticker = ?"
            params.append(ticker)
        query += " ORDER BY t.date, t.id"
        return conn.execute(query, params).fetchall()


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

def create_watchlist(name: str, db_path: Optional[Path] = None) -> int:
    with db_conn(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO watchlists (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM watchlists WHERE name = ?", (name,)).fetchone()
        return row["id"]


def list_watchlists(db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute("SELECT * FROM watchlists ORDER BY name").fetchall()


def add_to_watchlist(
    watchlist_name: str,
    ticker: str,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    with db_conn(db_path) as conn:
        wl = conn.execute(
            "SELECT id FROM watchlists WHERE name = ?", (watchlist_name,)
        ).fetchone()
        if wl is None:
            raise ValueError(f"Watchlist '{watchlist_name}' not found")
        sec = conn.execute("SELECT id FROM securities WHERE ticker = ?", (ticker,)).fetchone()
        if sec is None:
            raise ValueError(f"Security '{ticker}' not found")
        conn.execute(
            """
            INSERT OR IGNORE INTO watchlist_items (watchlist_id, security_id, notes)
            VALUES (?, ?, ?)
            """,
            (wl["id"], sec["id"], notes),
        )


def remove_from_watchlist(
    watchlist_name: str, ticker: str, db_path: Optional[Path] = None
) -> None:
    with db_conn(db_path) as conn:
        conn.execute(
            """
            DELETE FROM watchlist_items
            WHERE watchlist_id = (SELECT id FROM watchlists WHERE name = ?)
              AND security_id  = (SELECT id FROM securities WHERE ticker = ?)
            """,
            (watchlist_name, ticker),
        )


def get_watchlist_tickers(
    watchlist_name: str, db_path: Optional[Path] = None
) -> list[sqlite3.Row]:
    with db_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT s.*, wi.notes, wi.added_at as wl_added_at
            FROM watchlist_items wi
            JOIN watchlists wl ON wl.id = wi.watchlist_id
            JOIN securities s ON s.id = wi.security_id
            WHERE wl.name = ?
            ORDER BY s.ticker
            """,
            (watchlist_name,),
        ).fetchall()
