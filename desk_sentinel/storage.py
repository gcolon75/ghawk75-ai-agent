from __future__ import annotations
import os, pandas as pd, datetime as dt
from .config import cfg
from .util import ensure_data_dir, load_json, save_json

DATA = ensure_data_dir()
PRICES = os.path.join(DATA, "prices.csv")
SIGNALS = os.path.join(DATA, "signals.csv")
ALERTS = os.path.join(DATA, "alerts.csv")
TRADES = os.path.join(DATA, "paper_trades.csv")
GAMES = os.path.join(DATA, "game_prices.csv")
EXTREMA = os.path.join(DATA, "extrema.json")

def record_price(ts: str, ticker: str, price: float, source: str):
    from .util import rolling_csv_append
    rolling_csv_append(PRICES, {"ts": ts, "ticker": ticker, "price": price, "source": source})

def record_signal(ts: str, ticker: str, kind: str, value: float, note: str):
    from .util import rolling_csv_append
    rolling_csv_append(SIGNALS, {"ts": ts, "ticker": ticker, "kind": kind, "value": value, "note": note})

def record_alert(ts: str, kind: str, subject: str, message: str):
    from .util import rolling_csv_append
    rolling_csv_append(ALERTS, {"ts": ts, "kind": kind, "subject": subject, "message": message})

def record_game_price(ts: str, store: str, slug: str, price: float, normal: float|None, best12: bool, atl: bool):
    from .util import rolling_csv_append
    rolling_csv_append(GAMES, {"ts": ts, "store": store, "slug": slug, "price": price, "normal": normal if normal is not None else "", "best_12m": int(best12), "is_all_time_low": int(atl)})

def record_trade(**row):
    from .util import rolling_csv_append
    rolling_csv_append(TRADES, row)

def update_extrema(ticker: str, price: float, ts: str):
    data = load_json(EXTREMA, {})
    rec = data.get(ticker, {"high": None, "high_ts": None, "low": None, "low_ts": None})
    changed = False
    if rec["high"] is None or price > rec["high"]:
        rec["high"] = price; rec["high_ts"] = ts; changed = True
    if rec["low"] is None or price < rec["low"]:
        rec["low"] = price; rec["low_ts"] = ts; changed = True
    if changed:
        data[ticker] = rec
        save_json(EXTREMA, data)

def read_extrema() -> dict:
    return load_json(EXTREMA, {})
