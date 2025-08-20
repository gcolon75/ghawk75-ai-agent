"""
Stock price monitoring and technical analysis.

This module defines a `StockWatcher` class responsible for connecting to a
market‑data provider, streaming live prices for a list of tickers and
computing basic technical indicators.  When configured rules are met the
watcher will record the signal and forward an alert through the notifier.

To add a new data provider, implement the `_connect_stream` and
`_poll_latest_prices` methods.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

import aiohttp
import pandas as pd

from . import database
from .rules import evaluate_stock_rules
from .notifier import DiscordNotifier

logger = logging.getLogger(__name__)


class StockWatcher:
    """Monitor a set of stock tickers and evaluate alert rules."""

    def __init__(self, tickers: List[str], api_key: str, notifier: DiscordNotifier, interval_sec: int = 60) -> None:
        self.tickers = [t.upper() for t in tickers]
        self.api_key = api_key
        self.notifier = notifier
        self.interval_sec = interval_sec
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        """Entry point to start monitoring.  Spawns tasks for polling."""
        await database.init_db()  # Ensure DB exists
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                try:
                    await self._poll_latest_prices()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error polling prices: %s", exc)
                await asyncio.sleep(self.interval_sec)

    async def _poll_latest_prices(self) -> None:
        """Fetch latest prices for all tickers.

        This default implementation uses the Polygon REST API.  You can
        override this method to support other providers or WebSocket feeds.
        """
        if not self._session:
            return
        tickers_str = ",".join(self.tickers)
        url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?tickers={tickers_str}&apiKey={self.api_key}"
        async with self._session.get(url) as resp:
            data = await resp.json()
        now = datetime.now(timezone.utc).isoformat()
        for item in data.get("tickers", []):
            ticker = item["ticker"].upper()
            price = item["lastTrade"].get("p") or item["lastQuote"].get("p")
            volume = item.get("day", {}).get("v")
            if price is None:
                continue
            database.record_tick(now, ticker, float(price), volume)
            database.update_extrema(ticker, float(price), now)
            # Evaluate rules and send notifications
            signals = evaluate_stock_rules(ticker, now)
            for signal_name, signal_val, description in signals:
                database.insert_signal(now, ticker, signal_name, signal_val, description)
                await self.notifier.send_stock_alert(ticker, float(price), signal_name, signal_val, description)