"""
Notification subsystem for DeskSentinel.

This module wraps the logic for sending messages to Discord via webhook.
Messages are formatted as Discord embeds when appropriate.  The notifier
exposes coroutine methods for stock alerts, game alerts and daily briefs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Send notifications to a Discord channel via webhook."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def send(self, content: str = "", embeds: Optional[List[Dict[str, Any]]] = None) -> None:
        """Post a generic message to Discord."""
        session = await self._ensure_session()
        payload = {"content": content}
        if embeds:
            payload["embeds"] = embeds
        try:
            async with session.post(self.webhook_url, json=payload) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning("Discord webhook returned %s: %s", resp.status, text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to send Discord message: %s", exc)

    async def send_stock_alert(self, ticker: str, price: float, signal: str, value: float, note: str) -> None:
        """Format and send a stock alert embed."""
        title = f"{ticker} signal: {signal}"
        embed = {
            "title": title,
            "description": note,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Value", "value": f"{value:.2f}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "color": 0x00BFFF if value >= 0 else 0xFF4500,
        }
        await self.send(embeds=[embed])

    async def send_game_alert(self, title: str, store: str, price: float, normal_price: Optional[float], signals: List[str]) -> None:
        """Format and send a game deal alert."""
        description = f"Available on **{store}** for **${price:.2f}**"
        if normal_price:
            description += f" (normal ${normal_price:.2f})"
        embed = {
            "title": title,
            "description": description,
            "fields": [
                {"name": "Signals", "value": ", ".join(signals) or "N/A", "inline": False},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "color": 0xFFD700,
        }
        await self.send(embeds=[embed])

    async def send_brief(self, heading: str, content: str) -> None:
        """Send a plain text brief."""
        await self.send(content=f"**{heading}**\n{content}")