"""
SQLite persistence layer for DeskSentinel.

This module provides helper functions for creating and interacting with the
SQLite database used by the agent.  The schema includes tables for price
history, all‑time extrema, signals, game prices, alerts and simulated trades.

The default database location is `data/sentinel.sqlite` relative to the
repository root.  You can override this by setting the `DATABASE_URL`
environment variable to a different path.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, Optional, Tuple

DEFAULT_DB_PATH = os.environ.get("DATABASE_URL", os.path.join(os.getcwd(), "data", "sentinel.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    ts        TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    price     REAL NOT NULL,
    volume    REAL
);

CREATE TABLE IF NOT EXISTS extrema (
    ticker         TEXT PRIMARY KEY,
    all_time_high  REAL,
    high_ts        TEXT,
    all_time_low   REAL,
    low_ts         TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    ticker   TEXT NOT NULL,
    signal   TEXT NOT NULL,
    value    REAL,
    note     TEXT
);

CREATE TABLE IF NOT EXISTS game_prices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    app_id        TEXT NOT NULL,
    store         TEXT NOT NULL,
    price         REAL NOT NULL,
    normal_price  REAL,
    best_12m      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    subject     TEXT NOT NULL,
    message     TEXT NOT NULL,
    dedupe_key  TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL,
    qty         REAL NOT NULL,
    price_open  REAL NOT NULL,
    ts_close    TEXT,
    price_close REAL
);
"""


@contextmanager
def get_connection(db_path: str = DEFAULT_DB_PATH) -> Iterable[sqlite3.Connection]:
    """Yield a SQLite connection and ensure that foreign keys are enabled.

    The caller is responsible for committing or rolling back transactions.  On
    exit, the connection is closed automatically.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the database and all tables if they do not already exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def record_tick(ts: str, ticker: str, price: float, volume: Optional[float] = None) -> None:
    """Insert a new price tick into the database."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ticks (ts, ticker, price, volume) VALUES (?, ?, ?, ?)",
            (ts, ticker, price, volume),
        )
        conn.commit()


def update_extrema(ticker: str, price: float, ts: str) -> None:
    """Update all‑time high and low prices for a ticker."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT all_time_high, high_ts, all_time_low, low_ts FROM extrema WHERE ticker = ?",
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            high = low = price
            high_ts = low_ts = ts
        else:
            high, high_ts, low, low_ts = row
            if price > (high or price):
                high, high_ts = price, ts
            if price < (low or price):
                low, low_ts = price, ts
        conn.execute(
            "REPLACE INTO extrema (ticker, all_time_high, high_ts, all_time_low, low_ts) VALUES (?, ?, ?, ?, ?)",
            (ticker, high, high_ts, low, low_ts),
        )
        conn.commit()


def insert_signal(ts: str, ticker: str, signal: str, value: float, note: str = "") -> None:
    """Record a computed technical indicator or rule trigger."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO signals (ts, ticker, signal, value, note) VALUES (?, ?, ?, ?, ?)",
            (ts, ticker, signal, value, note),
        )
        conn.commit()


def insert_alert(ts: str, subject: str, message: str, dedupe_key: Optional[str] = None) -> int:
    """Insert an alert record and return the new alert's id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO alerts (ts, subject, message, dedupe_key) VALUES (?, ?, ?, ?)",
            (ts, subject, message, dedupe_key),
        )
        conn.commit()
        return cur.lastrowid


def insert_game_price(ts: str, app_id: str, store: str, price: float, normal_price: Optional[float], best_12m: bool) -> None:
    """Insert a game price observation."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO game_prices (ts, app_id, store, price, normal_price, best_12m) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, app_id, store, price, normal_price, int(best_12m)),
        )
        conn.commit()