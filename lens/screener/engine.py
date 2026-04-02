"""Screener engine: DSL → SQL → results DataFrame."""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from lens.db.store import get_all_fundamentals_for_screen, get_watchlist_tickers

# Mapping from DSL field names to DB column names
_FIELD_MAP = {
    "pe": "pe_ratio",
    "forward_pe": "forward_pe",
    "pb": "pb_ratio",
    "ps": "ps_ratio",
    "ev_ebitda": "ev_ebitda",
    "div_yield": "dividend_yield",
    "dividend_yield": "dividend_yield",
    "payout_ratio": "payout_ratio",
    "market_cap": "market_cap",
    "ev": "enterprise_value",
    "revenue": "revenue_ttm",
    "ebitda": "ebitda",
    "net_income": "net_income",
    "debt_equity": "debt_to_equity",
    "current_ratio": "current_ratio",
    "roe": "roe",
    "roa": "roa",
    "revenue_growth": "revenue_growth",
    "earnings_growth": "earnings_growth",
    "sector": "sector",
    "industry": "industry",
    "ticker": "ticker",
    "currency": "currency",
    "mic": "mic",
}

_NUMERIC_OPS = {"<", "<=", ">", ">=", "=", "!="}
_STRING_OPS = {"=", "!=", "LIKE", "like"}


def _tokenize(expression: str) -> list[str]:
    """Simple tokenizer for the screener DSL."""
    # Match: AND/OR (case insensitive), operators, strings, numbers, identifiers
    pattern = r"""
        (?i:AND|OR|NOT)         |   # logical operators
        [<>!]?=|[<>]            |   # comparison operators
        (?i:LIKE)               |   # LIKE operator
        "[^"]*"                 |   # double-quoted strings
        '[^']*'                 |   # single-quoted strings
        \d+(?:\.\d+)?(?:[eE][+-]?\d+)?  |   # numbers
        [A-Za-z_][A-Za-z0-9_]*  |   # identifiers
        [()%]                       # parens and wildcard
    """
    return re.findall(pattern, expression, re.VERBOSE)


def _parse_expression(tokens: list[str]) -> str:
    """
    Convert DSL tokens into a SQL WHERE clause fragment.
    Supports: field op value, AND, OR, NOT, parentheses.
    """
    sql_parts = []
    i = 0

    while i < len(tokens):
        tok = tokens[i]

        if tok.upper() in ("AND", "OR", "NOT"):
            sql_parts.append(tok.upper())
            i += 1
            continue

        if tok == "(":
            sql_parts.append("(")
            i += 1
            continue

        if tok == ")":
            sql_parts.append(")")
            i += 1
            continue

        # Expect: field op value
        if i + 2 < len(tokens):
            field = tok
            op = tokens[i + 1]
            value = tokens[i + 2]
            i += 3

            db_col = _FIELD_MAP.get(field.lower())
            if db_col is None:
                raise ValueError(f"Unknown field: '{field}'. Valid fields: {', '.join(sorted(_FIELD_MAP.keys()))}")

            # String fields
            if db_col in ("sector", "industry", "ticker", "currency", "mic"):
                # Strip quotes if present
                stripped = value.strip("\"'")
                if op.upper() == "LIKE":
                    sql_parts.append(f"LOWER({db_col}) LIKE LOWER('{stripped}')")
                elif op in ("=", "!="):
                    sql_parts.append(f"LOWER({db_col}) {op} LOWER('{stripped}')")
                else:
                    raise ValueError(f"Operator '{op}' not valid for string field '{field}'")
            else:
                # Numeric fields
                try:
                    float(value)
                except ValueError:
                    raise ValueError(f"Expected a number for field '{field}', got '{value}'")
                if op not in _NUMERIC_OPS:
                    raise ValueError(f"Unknown operator '{op}'")
                sql_parts.append(f"{db_col} {op} {value}")
        else:
            raise ValueError(f"Unexpected token at position {i}: '{tok}'")

    return " ".join(sql_parts)


def parse_filter(expression: str) -> str:
    """
    Parse a DSL filter expression into a SQL WHERE clause.
    Example: 'pe < 15 AND div_yield > 0.03' → 'pe_ratio < 15 AND dividend_yield > 0.03'
    Raises ValueError on syntax errors.
    """
    if not expression.strip():
        return "1=1"
    tokens = _tokenize(expression.strip())
    return _parse_expression(tokens)


def run_screen(
    expression: str,
    universe: str = "all",
    sort_by: Optional[str] = None,
    ascending: bool = True,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Run a screen against the fundamentals table.
    universe: "all" or a watchlist name.
    Returns a DataFrame of matching securities with fundamental data.
    Raises ValueError on invalid expressions.
    """
    # Load all fundamentals
    df = get_all_fundamentals_for_screen()
    if df.empty:
        return df

    # Filter to universe (watchlist)
    if universe != "all":
        wl_rows = get_watchlist_tickers(universe)
        wl_tickers = {r["ticker"] for r in wl_rows}
        df = df[df["ticker"].isin(wl_tickers)]
        if df.empty:
            return df

    # Apply filter expression via pandas query
    # We translate the DSL to a SQL-like condition that we apply on the DataFrame
    try:
        pandas_expr = _dsl_to_pandas(expression)
        if pandas_expr and pandas_expr.strip() != "1=1":
            df = df.query(pandas_expr)
    except Exception as e:
        raise ValueError(f"Filter error: {e}") from e

    # Sort
    if sort_by:
        db_col = _FIELD_MAP.get(sort_by.lower(), sort_by)
        if db_col in df.columns:
            df = df.sort_values(db_col, ascending=ascending, na_position="last")

    if limit:
        df = df.head(limit)

    return df.reset_index(drop=True)


def _dsl_to_pandas(expression: str) -> str:
    """
    Convert the screener DSL to a pandas query string.
    """
    if not expression.strip():
        return ""

    tokens = _tokenize(expression.strip())
    parts = []
    i = 0

    while i < len(tokens):
        tok = tokens[i]

        if tok.upper() in ("AND", "OR"):
            parts.append("&" if tok.upper() == "AND" else "|")
            i += 1
            continue

        if tok.upper() == "NOT":
            parts.append("~")
            i += 1
            continue

        if tok in ("(", ")"):
            parts.append(tok)
            i += 1
            continue

        if i + 2 < len(tokens):
            field = tok
            op = tokens[i + 1]
            value = tokens[i + 2]
            i += 3

            db_col = _FIELD_MAP.get(field.lower())
            if db_col is None:
                raise ValueError(f"Unknown field: '{field}'")

            if db_col in ("sector", "industry", "ticker", "currency", "mic"):
                stripped = value.strip("\"'").lower()
                if op.upper() == "LIKE":
                    # Convert SQL LIKE to pandas str.contains
                    pattern = stripped.replace("%", ".*").replace("_", ".")
                    parts.append(f'{db_col}.str.lower().str.contains("{pattern}", na=False)')
                elif op == "=":
                    parts.append(f'{db_col}.str.lower() == "{stripped}"')
                elif op == "!=":
                    parts.append(f'{db_col}.str.lower() != "{stripped}"')
                else:
                    raise ValueError(f"Invalid op '{op}' for string field")
            else:
                # Numeric: handle pandas NaN properly
                if op == "=":
                    op = "=="
                parts.append(f"{db_col} {op} {value}")
        else:
            raise ValueError(f"Unexpected end of expression near '{tok}'")

    return " ".join(parts)


def format_screener_results(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-friendly version of screener results."""
    if df.empty:
        return df

    display_cols = [
        "ticker", "name", "sector",
        "pe_ratio", "forward_pe", "pb_ratio", "ev_ebitda",
        "dividend_yield", "market_cap", "roe", "roa",
        "revenue_growth", "debt_to_equity", "current_ratio",
    ]
    existing = [c for c in display_cols if c in df.columns]
    result = df[existing].copy()

    rename_map = {
        "pe_ratio": "P/E",
        "forward_pe": "Fwd P/E",
        "pb_ratio": "P/B",
        "ev_ebitda": "EV/EBITDA",
        "dividend_yield": "Div Yield",
        "market_cap": "Mkt Cap",
        "roe": "ROE",
        "roa": "ROA",
        "revenue_growth": "Rev Growth",
        "debt_to_equity": "D/E",
        "current_ratio": "Curr Ratio",
    }
    result = result.rename(columns=rename_map)
    return result
