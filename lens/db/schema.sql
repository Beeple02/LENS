-- LENS database schema

CREATE TABLE IF NOT EXISTS securities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL UNIQUE,       -- Yahoo format: "MC.PA"
    isin        TEXT,
    name        TEXT NOT NULL,
    mic         TEXT NOT NULL DEFAULT 'XPAR',
    currency    TEXT NOT NULL DEFAULT 'EUR',
    sector      TEXT,
    industry    TEXT,
    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_securities_isin ON securities(isin);
CREATE INDEX IF NOT EXISTS idx_securities_ticker ON securities(ticker);

CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    adj_close   REAL,
    volume      INTEGER,
    UNIQUE(security_id, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_security_date ON prices(security_id, date);

CREATE TABLE IF NOT EXISTS fundamentals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    security_id       INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
    fetched_at        TEXT NOT NULL DEFAULT (datetime('now')),
    pe_ratio          REAL,
    forward_pe        REAL,
    pb_ratio          REAL,
    ps_ratio          REAL,
    ev_ebitda         REAL,
    dividend_yield    REAL,
    payout_ratio      REAL,
    market_cap        REAL,
    enterprise_value  REAL,
    revenue_ttm       REAL,
    ebitda            REAL,
    net_income        REAL,
    debt_to_equity    REAL,
    current_ratio     REAL,
    roe               REAL,
    roa               REAL,
    revenue_growth    REAL,
    earnings_growth   REAL
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_security ON fundamentals(security_id, fetched_at);

CREATE TABLE IF NOT EXISTS portfolio_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    currency    TEXT NOT NULL DEFAULT 'EUR',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
    security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK(type IN ('BUY','SELL','DIVIDEND','SPLIT')),
    date        TEXT NOT NULL,
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    fees        REAL NOT NULL DEFAULT 0,
    currency    TEXT NOT NULL DEFAULT 'EUR',
    fx_rate     REAL NOT NULL DEFAULT 1.0,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_security ON transactions(security_id, date);

CREATE TABLE IF NOT EXISTS watchlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id    INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    security_id     INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT,
    UNIQUE(watchlist_id, security_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    security_id     INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
    condition_type  TEXT NOT NULL,      -- "price_above", "price_below", "change_pct", etc.
    threshold       REAL NOT NULL,
    triggered       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_screens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    expression  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
