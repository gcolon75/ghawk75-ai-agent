from __future__ import annotations
import datetime as dt, pytz, time, requests
from discord_webhook import DiscordWebhook, DiscordEmbed
from .config import cfg

_last_sent = {}  # dedupe/cooldown

def _in_quiet_hours(now: dt.datetime) -> bool:
    try:
        start, end = cfg.quiet_hours.split("-")
        s_h, s_m = map(int, start.split(":"))
        e_h, e_m = map(int, end.split(":"))
        start_dt = now.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
        end_dt = now.replace(hour=e_h, minute=e_m, second=0, microsecond=0)
        if start_dt <= end_dt:
            return start_dt <= now <= end_dt
        else:
            return now >= start_dt or now <= end_dt
    except Exception:
        return False

def _cooldown_ok(key: str, minutes: int) -> bool:
    now = time.time()
    last = _last_sent.get(key, 0)
    if now - last < minutes * 60:
        return False
    _last_sent[key] = now
    return True

def _webhook():
    if not cfg.discord_webhook:
        return None
    return DiscordWebhook(url=cfg.discord_webhook)

def _bot_post(content: str):
    if not (cfg.discord_bot_token and cfg.discord_channel_id):
        return False
    url = f"https://discord.com/api/v10/channels/{cfg.discord_channel_id}/messages"
    headers = {"Authorization": f"Bot {cfg.discord_bot_token}"}
    try:
        r = requests.post(url, headers=headers, json={"content": content}, timeout=10)
        return r.status_code < 300
    except Exception:
        return False

def send_simple(message: str, dedupe_key: str | None = None, bypass_quiet: bool = False):
    tz = pytz.timezone(cfg.timezone)
    now = dt.datetime.now(tz)
    if not bypass_quiet and _in_quiet_hours(now):
        return
    if dedupe_key and not _cooldown_ok(dedupe_key, cfg.alert_cooldown_minutes):
        return
    if cfg.discord_bot_token and cfg.discord_channel_id:
        if _bot_post(message): return
    hook = _webhook()
    if not hook: return
    hook.content = message
    hook.execute()

def send_embed(title: str, description: str, fields=None, color: int = 0x2ecc71, dedupe_key: str | None = None):
    tz = pytz.timezone(cfg.timezone)
    now = dt.datetime.now(tz)
    if _in_quiet_hours(now):
        return
    if dedupe_key and not _cooldown_ok(dedupe_key, cfg.alert_cooldown_minutes):
        return
    if cfg.discord_bot_token and cfg.discord_channel_id:
        body = f"**{title}**\n{description}"
        if fields:
            for name, value in fields:
                body += f"\n**{name}**\n{value}"
        if _bot_post(body): return
    hook = _webhook()
    if not hook: return
    embed = DiscordEmbed(title=title, description=description, color=color)
    if fields:
        for name, value in fields:
            embed.add_embed_field(name=name, value=value, inline=False)
    hook.add_embed(embed)
    hook.execute()
