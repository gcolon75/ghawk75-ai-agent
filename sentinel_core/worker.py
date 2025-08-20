"""
Background worker for scheduled tasks.

The worker runs periodic jobs such as morning and evening briefs, price cleanup
and backup.  It uses asyncio to schedule coroutines at specific times.

Currently this module implements placeholder tasks.  In production, you would
pull in the summariser from a cloud LLM (e.g. OpenAI) to generate the briefs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone

from .database import insert_alert
from .notifier import DiscordNotifier

logger = logging.getLogger(__name__)


async def run_worker(notifier: DiscordNotifier) -> None:
    """Run scheduled jobs forever."""
    while True:
        now = datetime.now(timezone.utc)
        # Determine times for next morning and evening briefs (7:30 and 17:00 local)
        tz_offset = timedelta(hours=int(os.environ.get("TIMEZONE_OFFSET", "0")))
        local_now = now + tz_offset
        # Compute seconds until next morning and evening (this is a stub)
        # For simplicity we schedule a brief every 12 hours
        await asyncio.sleep(12 * 3600)
        # Placeholder brief content
        heading = "Daily Brief"
        content = "This is a placeholder brief.  Real summaries will include market moves, game deals and P&L."
        await notifier.send_brief(heading, content)