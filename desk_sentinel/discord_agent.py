# desk_sentinel/discord_agent.py
import os
import asyncio
import logging
import json
import requests  # <-- add this
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Literal
from datetime import datetime, date
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
import yfinance as yf

from dotenv import load_dotenv, find_dotenv

# ---------- ENV & LOGGING ----------
load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
try:
    discord.utils.setup_logging(level=logging.INFO)  # discord.py >=2.3
except Exception:
    pass

TOKEN: str = os.getenv("DISCORD_BOT_TOKEN") or ""
GUILDS = [int(g) for g in os.getenv("DISCORD_GUILD_ID", "").split(",") if g.strip()]
TZ_NAME = os.getenv("TIMEZONE", "America/Los_Angeles")
TZ = ZoneInfo(TZ_NAME)

ALERTS_CHANNEL_ID: int = int(os.getenv("DISCORD_CHANNEL_ID_ALERTS", "0") or 0)
BRIEFS_CHANNEL_ID: int = int(os.getenv("DISCORD_CHANNEL_ID_BRIEFS", "0") or 0)
ENABLE_BG_ALERTS: bool = (os.getenv("ENABLE_ALERTS", "false").lower() in {"1", "true", "yes"})

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
WATCHLIST_FILE = DATA_DIR / "watchlist.txt"
SCHEDULE_FILE = DATA_DIR / "schedules.json"

# ---------- WATCHLIST PERSISTENCE ----------
def read_watchlist() -> List[str]:
    if WATCHLIST_FILE.exists():
        try:
            symbols = [l.strip().upper() for l in WATCHLIST_FILE.read_text().splitlines() if l.strip()]
            if symbols:
                return symbols
        except Exception:
            logging.exception("Failed to read %s", WATCHLIST_FILE)
    env_list = [s.strip().upper() for s in os.getenv("WATCHLIST", "").split(",") if s.strip()]
    return env_list or ["NVDA", "QUBT", "PLTR", "LMT", "JPM", "AAPL"]

def write_watchlist(symbols: List[str]) -> None:
    symbols = sorted({s.upper() for s in symbols})
    try:
        WATCHLIST_FILE.write_text("\n".join(symbols) + "\n")
    except Exception:
        logging.exception("Failed to write %s", WATCHLIST_FILE)

def add_symbol(sym: str) -> List[str]:
    syms = read_watchlist()
    u = sym.upper().strip()
    if u and u not in syms:
        syms.append(u)
        write_watchlist(syms)
    return read_watchlist()

def remove_symbol(sym: str) -> List[str]:
    u = sym.upper().strip()
    syms = [s for s in read_watchlist() if s != u]
    write_watchlist(syms)
    return read_watchlist()

# ---------- MARKET HELPERS ----------
async def fetch_price(symbol: str) -> dict:
    """Grab latest price without blocking the event loop (yfinance in a thread)."""
    sym = symbol.upper().strip()

    def _get():
        t = yf.Ticker(sym)
        info: dict = {}
        try:
            fast = getattr(t, "fast_info", None)
            if fast:
                if hasattr(fast, "last_price"):
                    info["price"] = float(fast.last_price)
                if hasattr(fast, "previous_close"):
                    info["prev_close"] = float(fast.previous_close)
        except Exception:
            pass
        if "price" not in info:
            try:
                hist = t.history(period="1d", interval="1m")
                if not hist.empty:
                    info["price"] = float(hist["Close"].iloc[-1])
            except Exception:
                pass
        if "prev_close" not in info:
            try:
                d = t.history(period="5d", interval="1d")
                if not d.empty:
                    info["prev_close"] = float(d["Close"].iloc[-2]) if len(d) > 1 else float(d["Close"].iloc[-1])
            except Exception:
                pass
        return info

    return await asyncio.to_thread(_get)

def pct_change(price: Optional[float], prev: Optional[float]) -> Optional[float]:
    if not price or not prev:
        return None
    try:
        return (price / prev - 1.0) * 100.0
    except Exception:
        return None

# ---------- SIMPLE DAILY SCHEDULER ----------
DaysKey = Literal["daily", "weekdays", "weekends", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]

@dataclass
class ScheduleItem:
    id: str
    time_hhmm: str            # "07:30"
    days: DaysKey             # e.g. "daily", "weekdays", or "sat"
    channel_id: int           # where to post
    message: str              # what to say
    enabled: bool = True
    last_trigger_ymd: Optional[str] = None  # "YYYY-MM-DD" to avoid dupes per day

def _load_schedule() -> List[ScheduleItem]:
    if SCHEDULE_FILE.exists():
        try:
            raw = json.loads(SCHEDULE_FILE.read_text())
            return [ScheduleItem(**r) for r in raw]
        except Exception:
            logging.exception("Failed reading schedules.json; starting fresh")
    return []

def _save_schedule(items: List[ScheduleItem]) -> None:
    SCHEDULE_FILE.write_text(json.dumps([asdict(i) for i in items], indent=2))

def _matches_day(today: date, key: DaysKey) -> bool:
    wd = today.weekday()  # Mon=0 .. Sun=6
    if key == "daily": return True
    if key == "weekdays": return wd < 5
    if key == "weekends": return wd >= 5
    table = ["mon","tue","wed","thu","fri","sat","sun"]
    return key in table and table[wd] == key

def _valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
        return 0 <= h < 24 and 0 <= m < 60
    except Exception:
        return False

# ---------- DISCORD CLIENT ----------
intents = discord.Intents.default()  # slash-only; no message_content unless you want plain-text triggers
class DeskBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._bg_task_prices: Optional[asyncio.Task] = None
        self._bg_task_scheduler: Optional[asyncio.Task] = None

    async def setup_hook(self):
        # Per-guild sync for instant slash updates during development
        for gid in GUILDS:
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            try:
                synced = await self.tree.sync(guild=discord.Object(id=gid))
                logging.info(f"Synced {len(synced)} commands to guild {gid}")
            except Exception:
                logging.exception("Slash sync failed for guild %s", gid)

        if ENABLE_BG_ALERTS:
            self._bg_task_prices = asyncio.create_task(self.alerts_loop())

        # scheduler loop: checks every 30 seconds for HH:MM matches in your TZ
        self._bg_task_scheduler = asyncio.create_task(self.scheduler_loop())

    async def alerts_loop(self):
        await self.wait_until_ready()
        logging.info("Alerts loop started")
        while not self.is_closed():
            try:
                syms = read_watchlist()[:3]
                chunks = []
                for s in syms:
                    info = await fetch_price(s)
                    p, pc = info.get("price"), info.get("prev_close")
                    chg = pct_change(p, pc)
                    if p:
                        chunks.append(f"{s}: {p:.2f}" + (f" ({chg:+.2f}%)" if chg is not None else ""))
                if ALERTS_CHANNEL_ID and chunks:
                    ch = self.get_channel(ALERTS_CHANNEL_ID)
                    if ch:
                        await ch.send("🔔 Watchlist heartbeat: " + "  |  ".join(chunks))
            except Exception:
                logging.exception("alerts_loop error")
            await asyncio.sleep(60)

    async def scheduler_loop(self):
        await self.wait_until_ready()
        logging.info("Scheduler loop started")
        while not self.is_closed():
            try:
                now = datetime.now(TZ)
                today = now.date()
                hhmm = now.strftime("%H:%M")
                items = _load_schedule()
                changed = False
                for it in items:
                    if not it.enabled or not _valid_hhmm(it.time_hhmm):
                        continue
                    if it.last_trigger_ymd == today.isoformat():
                        continue
                    if hhmm == it.time_hhmm and _matches_day(today, it.days):
                        ch = self.get_channel(it.channel_id) if it.channel_id else None
                        if ch:
                            try:
                                await ch.send(it.message)
                            except Exception:
                                logging.exception("Failed posting schedule message for %s", it.id)
                        it.last_trigger_ymd = today.isoformat()
                        changed = True
                if changed:
                    _save_schedule(items)
            except Exception:
                logging.exception("scheduler_loop error")
            await asyncio.sleep(30)

client = DeskBot()

# ---------- BASIC COMMANDS ----------
@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user} (latency {client.latency*1000:.0f}ms)")

@client.tree.command(name="ping", description="Am I alive?")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! I'm awake.")

@client.tree.command(name="price", description="Get the latest price for a symbol.")
@app_commands.describe(symbol="Ticker symbol like NVDA")
async def price_cmd(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer(thinking=True)
    info = await fetch_price(symbol)
    p, pc = info.get("price"), info.get("prev_close")
    if not p:
        await interaction.followup.send(f"Couldn't fetch **{symbol.upper()}** 🤷")
        return
    chg = pct_change(p, pc)
    out = f"**{symbol.upper()}**: ${p:,.2f}"
    if chg is not None:
        out += f"  ({chg:+.2f}%)"
    await interaction.followup.send(out)

@client.tree.command(name="brief", description="Post a quick market brief here or to the briefs channel.")
async def brief_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    syms = read_watchlist()[:8]
    lines = []
    for s in syms:
        info = await fetch_price(s)
        p, pc = info.get("price"), info.get("prev_close")
        if p:
            chg = pct_change(p, pc)
            line = f"{s}: ${p:,.2f}" + (f" ({chg:+.2f}%)" if chg is not None else "")
            lines.append(line)
    msg = "📊 **Mini Brief**\n" + "\n".join(lines) if lines else "No data."
    if BRIEFS_CHANNEL_ID:
        ch = client.get_channel(BRIEFS_CHANNEL_ID)
        if ch:
            await ch.send(msg)
            await interaction.followup.send("Sent to briefs channel. ✅")
            return
    await interaction.followup.send(msg)

# ---------- WATCHLIST SUBCOMMANDS ----------
watchlist_group = app_commands.Group(
    name="watchlist",
    description="Manage your ticker watchlist",
)

@watchlist_group.command(name="list", description="Show all tickers in the watchlist.")
async def wl_list(interaction: discord.Interaction):
    syms = read_watchlist()
    await interaction.response.send_message("📜 **Watchlist**: " + (", ".join(syms) if syms else "empty"))

@watchlist_group.command(name="add", description="Add a ticker to the watchlist.")
@app_commands.describe(symbol="Ticker symbol (e.g., NVDA)")
async def wl_add(interaction: discord.Interaction, symbol: str):
    sym = symbol.strip().upper()
    syms = add_symbol(sym)
    await interaction.response.send_message(f"✅ Added **{sym}**. Now: " + ", ".join(syms))

@watchlist_group.command(name="remove", description="Remove a ticker from the watchlist.")
@app_commands.describe(symbol="Ticker symbol (e.g., NVDA)")
async def wl_remove(interaction: discord.Interaction, symbol: str):
    sym = symbol.strip().upper()
    syms = remove_symbol(sym)
    await interaction.response.send_message(f"🗑️ Removed **{sym}**. Now: " + ", ".join(syms))

client.tree.add_command(watchlist_group)

# ---------- SCHEDULE SUBCOMMANDS ----------
schedule_group = app_commands.Group(
    name="schedule",
    description="Create daily pings (simple scheduler)"
)

DAYS_CHOICES = ["daily","weekdays","weekends","mon","tue","wed","thu","fri","sat","sun"]

@schedule_group.command(name="add", description="Add a daily/weekday/weekend ping")
@app_commands.describe(
    id="Unique id like 'morning'",
    time_hhmm="24h time like 07:30",
    days=f"One of: {', '.join(DAYS_CHOICES)}",
    message="What should I post at that time?",
    channel="Where to post (defaults to current channel)"
)
async def sched_add(
    interaction: discord.Interaction,
    id: str,
    time_hhmm: str,
    days: str,
    message: str,
    channel: Optional[discord.TextChannel] = None
):
    if days not in DAYS_CHOICES:
        await interaction.response.send_message(f"days must be one of: {', '.join(DAYS_CHOICES)}", ephemeral=True)
        return
    if not _valid_hhmm(time_hhmm):
        await interaction.response.send_message("time must be HH:MM (24h). Example: 07:30", ephemeral=True)
        return
    ch = channel or interaction.channel
    items = _load_schedule()
    if any(i.id == id for i in items):
        await interaction.response.send_message(f"ID `{id}` already exists. Use a new id or /schedule remove first.", ephemeral=True)
        return
    items.append(ScheduleItem(id=id, time_hhmm=time_hhmm, days=days, channel_id=ch.id, message=message))
    _save_schedule(items)
    await interaction.response.send_message(f"⏰ Added `{id}` → {days} at {time_hhmm} in <#{ch.id}>: “{message}”")

@schedule_group.command(name="list", description="List all scheduled pings")
async def sched_list(interaction: discord.Interaction):
    items = _load_schedule()
    if not items:
        await interaction.response.send_message("No schedules yet. Try `/schedule add`.", ephemeral=False)
        return
    lines = []
    for i in items:
        status = "ON" if i.enabled else "OFF"
        lines.append(f"- **{i.id}** [{status}]: {i.days} at {i.time_hhmm} in <#{i.channel_id}> — “{i.message}”")
    await interaction.response.send_message("\n".join(lines))

@schedule_group.command(name="remove", description="Remove a scheduled ping")
@app_commands.describe(id="The id used when you added it")
async def sched_remove(interaction: discord.Interaction, id: str):
    items = _load_schedule()
    new_items = [x for x in items if x.id != id]
    if len(new_items) == len(items):
        await interaction.response.send_message(f"Nothing named `{id}`.", ephemeral=True)
        return
    _save_schedule(new_items)
    await interaction.response.send_message(f"🗑️ Removed `{id}`")

@schedule_group.command(name="toggle", description="Enable/disable a scheduled ping")
@app_commands.describe(id="Schedule id", enabled="true/false")
async def sched_toggle(interaction: discord.Interaction, id: str, enabled: bool):
    items = _load_schedule()
    found = False
    for it in items:
        if it.id == id:
            it.enabled = enabled
            found = True
            break
    if not found:
        await interaction.response.send_message(f"No schedule `{id}`.", ephemeral=True)
        return
    _save_schedule(items)
    await interaction.response.send_message(f"🔁 `{id}` is now {'ON' if enabled else 'OFF'}")
    
client.tree.add_command(schedule_group)


# --- OLLAMA HELPER (local LLM via REST) ---
async def ollama_reply(system: str, user: str, model: str) -> str:
    def _post():
        r = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream": False
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("message", {}) or {}).get("content", "").strip() or "Morning! (no text)"
    return await asyncio.to_thread(_post)


# ---------- GOOD MORNING HELPER (Ollama-first) ----------
async def build_goodmorning_text(note: str | None) -> str:
    syms = read_watchlist()[:6]
    snap_lines = []
    for s in syms:
        info = await fetch_price(s)
        p, pc = info.get("price"), info.get("prev_close")
        if p:
            chg = pct_change(p, pc)
            snap_lines.append(f"{s}: ${p:,.2f}" + (f" ({chg:+.2f}%)" if chg is not None else ""))

    user_line = note or "No specific note."
    context = (
        f"Date/time: {datetime.now(TZ).strftime('%A, %B %d, %Y • %I:%M %p %Z')}\n"
        f"Watchlist: " + (" | ".join(snap_lines) if snap_lines else "no data") + "\n"
        "Tone: quick, warm, a touch of clever humor; 3-6 sentences max.\n"
        "Include a tiny actionable nudge for the day.\n"
    )

    # Prefer Ollama
    if os.getenv("USE_OLLAMA","false").lower() in {"1","true","yes"}:
        try:
            system = "You are a quick, warm morning assistant. Be concise, friendly, and practical. Add one actionable nudge."
            user   = f"User note: {user_line}\n\nContext:\n{context}"
            model  = os.getenv("OLLAMA_MODEL","llama3.1:8b")
            return await ollama_reply(system, user, model)
        except Exception:
            logging.exception("Ollama call failed")
            return "Morning! (Ollama error—check that Ollama is running and the model is pulled.)\n" + context

    # Optional fallback to OpenAI only if you WANT it later:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            oa = OpenAI(api_key=OPENAI_API_KEY)
            resp = oa.responses.create(
                model="gpt-4o-mini",
                instructions="You are a personal morning assistant for a Discord user. Be concise, friendly, and practical.",
                input=[
                    {"role": "user", "content": f"User says: {user_line}"},
                    {"role": "developer", "content": context},
                ],
            )
            return getattr(resp, "output_text", None) or "Morning! (LLM returned no text)"
        except Exception:
            logging.exception("OpenAI call failed")
            return "Morning! (LLM error.)\n" + context

    # Ultimate fallback: no LLM
    return "Good morning! (LLM disabled)\n" + context


# ---------- GOOD MORNING (slash command) ----------
@client.tree.command(name="goodmorning", description="Friendly morning reply + quick updates")
@app_commands.describe(note="Anything you want me to consider")
async def goodmorning(interaction: discord.Interaction, note: str | None = None):
    await interaction.response.defer(thinking=True)
    text = await build_goodmorning_text(note)
    await interaction.followup.send(text)

    # Gather quick stock snapshot
    syms = read_watchlist()[:6]
    snap_lines = []
    for s in syms:
        info = await fetch_price(s)
        p, pc = info.get("price"), info.get("prev_close")
        if p:
            chg = pct_change(p, pc)
            snap_lines.append(f"{s}: ${p:,.2f}" + (f" ({chg:+.2f}%)" if chg is not None else ""))

    # Compose a short prompt
    user_line = note or "No specific note."
    context = (
        f"Date/time: {datetime.now(TZ).strftime('%A, %B %d, %Y • %I:%M %p %Z')}\n"
        f"Watchlist: " + (" | ".join(snap_lines) if snap_lines else "no data") + "\n"
        "Tone: quick, warm, a touch of clever humor; 3-6 sentences max.\n"
        "Include a tiny actionable nudge for the day (e.g., hydrate, stretch, review goals).\n"
    )

    text = None
    if not OPENAI_API_KEY:
        # Fallback if no key configured
        text = "Good morning! (Set OPENAI_API_KEY for a personalized blurb.)\n" + context
    else:
        try:
            # Using OpenAI's current Responses API (official) to generate the blurb.
            # Docs: https://platform.openai.com/docs/api-reference/responses
            from openai import OpenAI
            client_oa = OpenAI(api_key=OPENAI_API_KEY)
            resp = client_oa.responses.create(
                # pick your preferred small model; -mini is cheap/fast. You can swap to gpt-4o if you like.
                model="gpt-4o-mini",
                instructions="You are a personal morning assistant for a Discord user. Be concise, friendly, and practical.",
                input=[
                    {"role": "user", "content": f"User says: {user_line}"},
                    {"role": "developer", "content": context}
                ],
            )
            # The SDK exposes convenience: response.output_text
            text = getattr(resp, "output_text", None) or "Morning! (LLM returned no text)"
        except Exception:
            logging.exception("OpenAI call failed")
            text = "Morning! (LLM error; check OPENAI_API_KEY and network.)"

    await interaction.followup.send(text)

# ---------- ENTRYPOINT ----------
def main():
    if not TOKEN or not GUILDS:
        raise SystemExit("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in .env")
    client.run(TOKEN)

if __name__ == "__main__":
    main()
