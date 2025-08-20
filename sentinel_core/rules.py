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
    # RSI calculation
    # Compute 14‑period RSI using average gains and losses.  If the average loss is zero
    # the RSI is set to 100 to avoid division by zero.  Alerts fire when RSI crosses
    # common oversold/overbought thresholds.
    if len(df) >= 15:
        diff = df["price"].diff()
        gain = diff.clip(lower=0)
        loss = -diff.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean().iloc[-1]
        avg_loss = loss.rolling(window=14).mean().iloc[-1]
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        if rsi <= 30:
            signals.append(("rsi_oversold", float(rsi), "RSI <= 30 (oversold)"))
        elif rsi >= 70:
            signals.append(("rsi_overbought", float(rsi), "RSI >= 70 (overbought)"))

    # 20‑period high/low breakouts and moving average crossover
    if len(df) >= 20:
        last20 = df["price"].tail(20)
        high20 = last20.max()
        low20 = last20.min()
        # Alert when current price breaks above the 20‑period high or below the 20‑period low
        if current_price >= high20:
            signals.append(("break_20_high", float(current_price), "Price hit 20‑period high"))
        if current_price <= low20:
            signals.append(("break_20_low", float(current_price), "Price hit 20‑period low"))
        # Compute moving averages on the same window
        ma_short = last20.tail(5).mean()
        ma_long = last20.mean()
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