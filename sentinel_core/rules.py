"""
Alert rule definitions for DeskSentinel.

The functions in this module examine recent data and decide whether to trigger
alerts.  Each rule returns a list of tuples `(signal_name, value, note)` when
conditions are met.  These signals are recorded to the database and passed to
the notifier for dispatch.

You can add or modify rules by editing this file.  Consider using pandas and
technical analysis libraries (such as `ta`) for more sophisticated signals.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

import pandas as pd  # type: ignore

from . import database

Signal = Tuple[str, float, str]


def evaluate_stock_rules(ticker: str, ts: str) -> List[Signal]:
    """Evaluate stock alert rules for a ticker at the given timestamp.

    This simplistic implementation reads the last few price ticks from the
    database and triggers alerts based on intraday percent change and simple
    moving average crossovers.  You can extend this function to add more
    sophisticated technical indicators.
    """
    # Fetch recent price history (last N minutes)
    with database.get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT ts, price FROM ticks WHERE ticker = ? ORDER BY ts DESC LIMIT 60",  # last hour assuming 1/min polling
            conn,
            params=(ticker,),
            parse_dates=["ts"],
        )
    if df.empty:
        return []
    df = df.sort_values("ts")
    current_price = df["price"].iloc[-1]
    first_price = df["price"].iloc[0]
    pct_change = (current_price - first_price) / first_price * 100
    signals: List[Signal] = []
    # Percent move rule
    if abs(pct_change) >= 2.0:
        signal_name = "pct_move"
        note = f"Price moved {pct_change:.2f}% in the last hour"
        signals.append((signal_name, pct_change, note))
    # Moving average crossover
    if len(df) >= 20:
        ma_short = df["price"].tail(5).mean()
        ma_long = df["price"].tail(20).mean()
        if ma_short > ma_long:
            signals.append(("ma_cross", ma_short - ma_long, "Short MA crossed above long MA"))
        elif ma_short < ma_long:
            signals.append(("ma_cross", ma_short - ma_long, "Short MA crossed below long MA"))
    return signals


def evaluate_game_rules(app_id: str, current_price: float, normal_price: float, best_12m: bool) -> List[Signal]:
    """Evaluate game deal rules and return signals if conditions are met."""
    signals: List[Signal] = []
    if normal_price and current_price <= normal_price * 0.8:
        signals.append(("sale_20", current_price / normal_price, ">= 20% off normal price"))
    if best_12m:
        signals.append(("best_12m", 1.0, "Best price in 12 months"))
    return signals