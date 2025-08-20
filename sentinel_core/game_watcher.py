"""
Game price tracking and deal detection.

This module defines the `GameWatcher` class responsible for periodically
polling various game storefronts (via APIs such as IsThereAnyDeal) and
recording price history.  When configured rules are met, the watcher will
record a signal and notify via the notifier.

Note: Many stores do not provide official APIs.  The default implementation
uses the IsThereAnyDeal API, which aggregates deals across multiple stores.  You
will need an API key from their developer portal.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import aiohttp

from . import database
from .rules import evaluate_game_rules
from .notifier import DiscordNotifier

logger = logging.getLogger(__name__)


class GameWatcher:
    """Monitor game prices and detect deals."""

    def __init__(
        self,
        app_ids: Iterable[str],
        api_key: str,
        notifier: DiscordNotifier,
        interval_sec: int = 3600,
    ) -> None:
        self.app_ids = list(app_ids)
        self.api_key = api_key
        self.notifier = notifier
        self.interval_sec = interval_sec
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        await database.init_db()
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                try:
                    await self._check_deals()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error fetching game prices: %s", exc)
                await asyncio.sleep(self.interval_sec)

    async def _check_deals(self) -> None:
        """Query the IsThereAnyDeal API for each game and evaluate rules."""
        if not self._session:
            return
        base_url = "https://api.isthereanydeal.com/v01/game/prices/"
        for app_id in self.app_ids:
            params = {
                "key": self.api_key,
                "plain": app_id,
                "country": "us",
                "region": "us",
                "shops": "steam,epic,gog,uplay,origin,amazon,gamersgate,hb,greenmangaming",
            }
            async with self._session.get(base_url, params=params) as resp:
                data = await resp.json()
            now = datetime.now(timezone.utc).isoformat()
            try:
                price_info = data["data"][app_id]["list"][0]
            except Exception:  # noqa: BLE001
                logger.warning("No price info for %s", app_id)
                continue
            price = price_info["price"]
            normal_price = price_info.get("regular")
            best_12m = price_info.get("cut") == price_info.get("lowest")["cut"] if price_info.get("lowest") else False
            store = price_info["shop"]
            # Record price observation
            database.insert_game_price(now, app_id, store, price, normal_price, best_12m)
            # Evaluate rules
            signals = evaluate_game_rules(app_id, price, normal_price or 0.0, best_12m)
            if signals:
                # Compose descriptive signal names
                signal_names = [s for s, _, _ in signals]
                await self.notifier.send_game_alert(app_id, store, price, normal_price, signal_names)