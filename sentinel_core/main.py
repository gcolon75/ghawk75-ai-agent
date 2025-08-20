"""
Entry point for DeskSentinel.

This script reads configuration from environment variables, initialises the
database, constructs watchers for stocks and games, and runs them concurrently.

You can run this module directly:
    python -m sentinel_core.main

Environment variables:
* `DISCORD_WEBHOOK_URL` – the URL of the Discord webhook
* `MARKET_DATA_API_KEY` – your API key for the stock data provider
* `IS_THERE_ANY_DEAL_API_KEY` – your IsThereAnyDeal API key
* `WATCHLIST` – comma separated list of stock tickers to monitor
* `GAME_LIST` – comma separated list of IsThereAnyDeal "plain" identifiers
* `POLL_INTERVAL` – interval in seconds between stock price polls (default 60)
* `GAME_INTERVAL` – interval in seconds between game price polls (default 3600)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from .game_watcher import GameWatcher
from .notifier import DiscordNotifier
from .stock_watcher import StockWatcher
from .worker import run_worker

logging.basicConfig(level=logging.INFO)


async def async_main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Missing DISCORD_WEBHOOK_URL environment variable", file=sys.stderr)
        return
    market_key = os.environ.get("MARKET_DATA_API_KEY") or ""
    itad_key = os.environ.get("IS_THERE_ANY_DEAL_API_KEY") or ""
    watchlist = os.environ.get("WATCHLIST", "NVDA,QUBT,PLTR,LMT,JPM,AAPL").split(",")
    game_list = os.environ.get("GAME_LIST", "hades,cyberpunk-2077").split(",")
    poll_interval = int(os.environ.get("POLL_INTERVAL", "60"))
    game_interval = int(os.environ.get("GAME_INTERVAL", "3600"))

    notifier = DiscordNotifier(webhook_url)
    stock_watcher = StockWatcher(watchlist, market_key, notifier, poll_interval)
    game_watcher = GameWatcher(game_list, itad_key, notifier, game_interval)

    try:
        await asyncio.gather(
            stock_watcher.start(),
            game_watcher.start(),
            run_worker(notifier),
        )
    except asyncio.CancelledError:
        pass
    finally:
        await notifier.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()