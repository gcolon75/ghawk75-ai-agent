"""
Discord notification helpers (webhook-based, no JSONDecodeError).

- send_simple(text): plain message to your webhook
- send_embed(title, description, fields): rich embed to your webhook

Handles:
- Quiet hours (from cfg.quiet_hours / cfg.timezone)
- Simple dedupe/cooldown per 'dedupe_key'
- Discord quirk where webhooks return 204 (empty) -> we use '?wait=true'
"""

from __future__ import annotations

import os
import time
import json
import hashlib
import datetime as dt
from typing import Iterable, List, Tuple, Dict, Optional

import requests
import pytz

try:
    # Your repo should already expose this
    from .config import cfg
except Exception:
    # Fallback shim (only for rare import issues)
    class _Cfg:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        timezone = os.getenv("TIMEZONE", "America/Los_Angeles")
        quiet_hours = os.getenv("QUIET_HOURS", "23:00-07:00")
        alert_cooldown_min = int(os.getenv("ALERT_COOLDOWN_MIN", "30"))
    cfg = _Cfg()  # type: ignore


# in-memory last-send timestamps per key (reset on process restart)
_last_sent: Dict[str, float] = {}


def _parse_quiet_window(q: str) -> Optional[Tuple[dt.time, dt.time]]:
    """
    Accepts "HH:MM-HH:MM" (e.g., "23:00-07:00"), returns (start, end) as time objects.
    Returns None if parsing fails or q empty.
    """
    if not q or "-" not in q:
        return None
    try:
        left, right = q.split("-", 1)
        hh1, mm1 = [int(x) for x in left.strip().split(":")]
        hh2, mm2 = [int(x) for x in right.strip().split(":")]
        return (dt.time(hour=hh1, minute=mm1), dt.time(hour=hh2, minute=mm2))
    except Exception:
        return None


def _now_local() -> dt.datetime:
    tz = pytz.timezone(getattr(cfg, "timezone", "America/Los_Angeles"))
    return dt.datetime.now(tz)


def _in_quiet_hours() -> bool:
    """Return True if current local time is within the quiet window."""
    q = getattr(cfg, "quiet_hours", "") or ""
    window = _parse_quiet_window(q)
    if not window:
        return False
    start, end = window
    now = _now_local().time()
    if start < end:
        return start <= now <= end
    # overnight window (e.g., 23:00-07:00)
    return now >= start or now <= end


def _on_cooldown(dedupe_key: Optional[str]) -> bool:
    """Return True if we should skip sending due to per-key cooldown."""
    if not dedupe_key:
        return False
    cooldown_min = int(getattr(cfg, "alert_cooldown_min", 30) or 30)
    last = _last_sent.get(dedupe_key, 0.0)
    return (time.time() - last) < (cooldown_min * 60)


def _mark_sent(dedupe_key: Optional[str]) -> None:
    if dedupe_key:
        _last_sent[dedupe_key] = time.time()


def _webhook() -> str:
    return getattr(cfg, "webhook_url", "") or os.getenv("DISCORD_WEBHOOK_URL", "")


def _post_json(payload: dict) -> None:
    """
    POST to Discord webhook with '?wait=true' so Discord returns 200 + JSON
    (avoids libraries trying to json.loads('') and exploding).
    """
    url = _webhook()
    if not url:
        return
    try:
        # Explicitly add ?wait=true to avoid 204 No Content
        requests.post(f"{url}?wait=true", json=payload, timeout=12)
    except Exception as e:
        print(f"[notifier] webhook post failed: {e}")


def send_simple(text: str, *, dedupe_key: Optional[str] = None, bypass_quiet: bool = False) -> None:
    """
    Send a plain text message to the webhook.
    Respects quiet hours and cooldown unless bypassed.
    """
    if not text or not _webhook():
        return
    if not bypass_quiet and _in_quiet_hours():
        return
    if _on_cooldown(dedupe_key):
        return
    _post_json({"content": text})
    _mark_sent(dedupe_key)


def send_embed(
    *,
    title: str,
    description: str = "",
    fields: Iterable[Tuple[str, str]] = (),
    color: int = 0x2B3137,  # neutral dark
    dedupe_key: Optional[str] = None,
    bypass_quiet: bool = False,
) -> None:
    """
    Send a rich embed. 'fields' is an iterable of (name, value).
    """
    if not _webhook():
        return
    if not bypass_quiet and _in_quiet_hours():
        return
    if _on_cooldown(dedupe_key):
        return

    embed = {
        "title": title[:256],
        "description": description[:4096],
        "color": color,
        "fields": [{"name": n[:256], "value": v[:1024], "inline": False} for (n, v) in fields],
        "timestamp": _now_local().isoformat(),
    }
    _post_json({"embeds": [embed]})
    _mark_sent(dedupe_key)
