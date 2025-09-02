# desk_sentinel/discord_agent.py
from __future__ import annotations

import os
import re
import json
import math
import asyncio
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Literal, Tuple
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests  # Ollama + ITAD + HTTP
import pandas as pd  # used by yfinance & (optional) alpaca bars parsing
import yfinance as yf

import discord
from discord import app_commands

from dotenv import load_dotenv, find_dotenv

# ---------- ENV & LOGGING ----------
load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
try:
    discord.utils.setup_logging(level=logging.INFO)  # discord.py >= 2.3
except Exception:
    pass

TOKEN: str = os.getenv("DISCORD_BOT_TOKEN") or ""
GUILDS = [int(g) for g in os.getenv("DISCORD_GUILD_ID", "").split(",") if g.strip()]
TZ_NAME = os.getenv("TIMEZONE", "America/Los_Angeles")
TZ = ZoneInfo(TZ_NAME)

ALERTS_CHANNEL_ID: int = int(os.getenv("DISCORD_CHANNEL_ID_ALERTS", "0") or 0)
BRIEFS_CHANNEL_ID: int = int(os.getenv("DISCORD_CHANNEL_ID_BRIEFS", "0") or 0)
ENABLE_BG_ALERTS: bool = (os.getenv("ENABLE_ALERTS", "false").lower() in {"1", "true", "yes"})

ITAD_KEY: str = os.getenv("ITAD_KEY", "") or os.getenv("ITAD_API_KEY", "")
ITAD_COUNTRY: str = os.getenv("ITAD_COUNTRY", "US")

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

# ---------- ITAD (IsThereAnyDeal) ----------
def fetch_itad_prices(slug: str, key: str, country: str = "US") -> list[dict]:
    """
    Fetch live prices for a game by its ITAD 'plain' (slug).
    Returns a list of {shop, price_new, price_old, url} (best-effort).
    """
    if not key:
        return []
    try:
        url = "https://api.isthereanydeal.com/v01/game/prices/"
        r = requests.get(url, params={"key": key, "plains": slug, "country": country}, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        data = (j.get("data") or {}).get(slug) or {}
        deals = data.get("list") or []
        out = []
        for d in deals:
            shop = (d.get("shop") or {}).get("name") or d.get("shop") or d.get("store") or "store"
            price_new = d.get("price_new") or (d.get("price") or {}).get("amount")
            price_old = d.get("price_old") or None
            url = d.get("url") or ""
            if price_new is not None:
                try:
                    out.append({"shop": shop, "price_new": float(price_new), "price_old": price_old, "url": url})
                except Exception:
                    pass
        out.sort(key=lambda x: x["price_new"])
        return out
    except Exception:
        logging.exception("fetch_itad_prices error for %s", slug)
        return []

# ---------- MARKET HELPERS (stocks) ----------
def _pct_change_safe(price: Optional[float], prev: Optional[float]) -> Optional[float]:
    if price is None or prev in (None, 0):
        return None
    try:
        return (price / prev - 1.0) * 100.0
    except Exception:
        return None

def pct_change(price: Optional[float], prev: Optional[float]) -> Optional[float]:
    return _pct_change_safe(price, prev)

async def fetch_price(symbol: str) -> dict:
    """
    Returns: {"price": float|None, "prev_close": float|None, "asof": str|None, "source": "alpaca"|"yfinance"|"none"}
    Strategy:
      1) Try Alpaca (paper, IEX feed). Requires ALPACA_KEY_ID/SECRET and APCA_API_BASE_URL.
      2) Fallback to yfinance (1m bars, pre/post).
    """
    sym = symbol.upper().strip()

    def _alpaca_try():
        ALPACA_KEY_ID = os.getenv("ALPACA_KEY_ID") or os.getenv("APCA_API_KEY_ID") or ""
        ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or ""
        BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
        if not (ALPACA_KEY_ID and ALPACA_SECRET_KEY):
            return None

        try:
            from alpaca_trade_api.rest import REST, TimeFrame
            api = REST(ALPACA_KEY_ID, ALPACA_SECRET_KEY, base_url=BASE_URL)
            tr = api.get_latest_trade(sym, feed="iex")
            price = float(getattr(tr, "price", 0) or 0) or None
            ts = getattr(tr, "timestamp", None)
            asof = str(ts) if ts else None

            prev_close = None
            bars = api.get_bars(sym, TimeFrame.Day, limit=2, adjustment="raw", feed="iex")
            df = getattr(bars, "df", None)
            if isinstance(df, pd.DataFrame) and not df.empty:
                try:
                    last_two = df.xs(sym).tail(2) if "symbol" in df.index.names else df.tail(2)
                except Exception:
                    last_two = df.tail(2)
                if len(last_two) >= 2 and "close" in last_two:
                    prev_close = float(last_two["close"].iloc[-2])
            else:
                try:
                    rows = list(bars)
                    if len(rows) >= 2:
                        prev_close = float(getattr(rows[-2], "c", None) or getattr(rows[-2], "close", 0) or 0) or None
                except Exception:
                    pass

            if price is None and prev_close is None:
                return None

            return {"price": price, "prev_close": prev_close, "asof": asof, "source": "alpaca"}
        except Exception:
            logging.exception("Alpaca fetch failed for %s (check keys/plan/feed/base_url)", sym)
            return None

    def _yahoo_try():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1d", interval="1m", prepost=True)
            price = None
            asof = None
            if isinstance(hist, pd.DataFrame) and not hist.empty:
                last_row = hist.dropna().iloc[-1]
                price = float(last_row["Close"])
                ix = hist.index[-1]
                asof = ix.isoformat() if hasattr(ix, "isoformat") else str(ix)

            d = t.history(period="5d", interval="1d", prepost=True)
            prev_close = None
            if isinstance(d, pd.DataFrame) and not d.empty:
                prev_close = float(d["Close"].iloc[-2]) if len(d) > 1 else float(d["Close"].iloc[-1])

            if price is None and prev_close is None:
                return None

            return {"price": price, "prev_close": prev_close, "asof": asof, "source": "yfinance"}
        except Exception:
            logging.exception("Yahoo fetch failed for %s", sym)
            return None

    data = await asyncio.to_thread(_alpaca_try)
    if not data:
        data = await asyncio.to_thread(_yahoo_try)
    return data or {"price": None, "prev_close": None, "asof": None, "source": "none"}

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

# ---------- TIME HELPERS ----------
def _norm_tz_name(s: Optional[str]) -> str:
    if not s:
        return os.getenv("TIMEZONE", "America/Los_Angeles")
    key = s.strip().lower()
    mapping = {
        "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pt":  "America/Los_Angeles", "pacific": "America/Los_Angeles",
        "est": "America/New_York", "edt": "America/New_York", "et":  "America/New_York", "eastern": "America/New_York",
        "cst": "America/Chicago", "cdt": "America/Chicago", "ct":  "America/Chicago", "central": "America/Chicago",
        "mst": "America/Denver", "mdt": "America/Denver", "mt":  "America/Denver", "mountain": "America/Denver",
        "utc": "UTC", "gmt": "UTC", "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
        "new york": "America/New_York", "nyc": "America/New_York",
    }
    return mapping.get(key, s)

def _format_now_in_tz(tz_name: Optional[str]) -> str:
    name = _norm_tz_name(tz_name)
    tz = ZoneInfo(name if name.upper() != "UTC" else "UTC")
    now = datetime.now(tz)
    return now.strftime(f"%A, %B %d, %Y • %I:%M:%S %p {now.tzname()}")

# ---------- EARNINGS HELPERS ----------
COMPANY_NAME_TO_TICKER = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "tesla": "TSLA",
    "amazon": "AMZN", "google": "GOOGL", "alphabet": "GOOGL", "meta": "META",
    "facebook": "META", "palantir": "PLTR", "lockheed": "LMT", "jpmorgan": "JPM", "jp morgan": "JPM",
}

def resolve_symbol_token(token: str) -> Optional[str]:
    if not token:
        return None
    tok_raw = token.strip()
    tok_clean = re.sub(r"[’']s$", "", tok_raw, flags=re.I)
    m = re.fullmatch(r"\$([A-Za-z]{1,5})", tok_clean)
    if m:
        return m.group(1).upper()
    name = tok_clean.lower()
    if name in COMPANY_NAME_TO_TICKER:
        return COMPANY_NAME_TO_TICKER[name]
    if re.fullmatch(r"[A-Z]{1,5}", tok_raw):
        return tok_raw
    return None

def extract_symbol_for_earnings(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip()
    m = re.search(r"\$([A-Za-z]{1,5})", t)
    if m:
        return m.group(1).upper()
    lower = t.lower()
    for name, sym in COMPANY_NAME_TO_TICKER.items():
        if re.search(rf"\b{name}(?:[’']s)?\b", lower):
            return sym
    m = re.search(r"\b([A-Za-z$]{1,12})[’']?s?\s+(?:earnings|eps)\b", lower)
    if m:
        return resolve_symbol_token(m.group(1))
    m = re.search(r"\b(?:earnings|eps)\b.*?\b(?:for\s+)?([A-Za-z$]{1,12})\b", lower)
    if m:
        return resolve_symbol_token(m.group(1))
    return None

async def latest_earnings(symbol: str) -> str:
    def _get():
        t = yf.Ticker(symbol)
        try:
            df = t.get_earnings_dates(limit=16)
        except Exception:
            df = None
        if df is None or df.empty:
            return None
        today = datetime.now().date()
        df_sorted = df.sort_index(ascending=False)
        chosen = None
        for idx, row in df_sorted.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            if d <= today:
                chosen = (d, row.to_dict())
                break
        if chosen is None:
            fidx = df.index[0]
            d = fidx.date() if hasattr(fidx, "date") else fidx
            chosen = (d, df.iloc[0].to_dict())
        d, row = chosen
        rep = row.get("Reported EPS")
        est = row.get("EPS Estimate")
        sur = row.get("Surprise(%)")
        parts = [f"**{symbol} earnings** ({d.isoformat()}):"]
        if rep is not None: parts.append(f"Reported EPS: {float(rep):.2f}")
        if est is not None: parts.append(f"Estimate: {float(est):.2f}")
        if sur is not None:
            try: parts.append(f"Surprise: {float(sur):+.2f}%")
            except Exception: pass
        return " | ".join(parts)
    data = await asyncio.to_thread(_get)
    return data or f"Couldn't find earnings for **{symbol}**."

# ---------- OPTIONS HELPERS ----------
OPTION_RIGHTS = {"c": "call", "call": "call", "p": "put", "put": "put"}

def _format_occ_symbol(root: str, expiration_yyyy_mm_dd: str, strike: float, right: str) -> str:
    """
    OCC: ROOT(<=6) + YYMMDD + C/P + STRIKE(8 digits, 3 decimal implied)
    e.g. NVDA 2025-09-19 140 C -> NVDA250919C00140000
    """
    root = root.upper().strip()
    y, m, d = expiration_yyyy_mm_dd.split("-")
    yy = y[-2:]
    mm = f"{int(m):02d}"
    dd = f"{int(d):02d}"
    right_char = "C" if right.lower().startswith("c") else "P"
    strike_int = int(round(strike * 1000))
    strike_str = f"{strike_int:08d}"
    return f"{root}{yy}{mm}{dd}{right_char}{strike_str}"

def _parse_option_freeform(s: str) -> Optional[Tuple[str, str, float, str]]:
    """
    Parse things like:
      NVDA 9/19 140c
      NVDA 2025-09-19 140 C
      $NVDA 09/19/2025 500 put
    Returns (root, YYYY-MM-DD, strike, right) or None.
    """
    if not s:
        return None
    text = s.strip().lower().replace(",", " ")
    # normalize $nvda
    text = re.sub(r"\$([a-z]{1,5})", r"\1", text)
    # date forms
    # 1) yyyy-mm-dd
    m = re.search(r"\b([a-z]{1,6})\s+(\d{4}-\d{1,2}-\d{1,2})\s+(\d+(\.\d+)?)\s*([cp]|call|put)\b", text)
    if m:
        sym, dts, strike, _, right = m.groups()
        y, mo, da = [int(x) for x in dts.split("-")]
        dts_norm = f"{y:04d}-{mo:02d}-{da:02d}"
        return (sym.upper(), dts_norm, float(strike), OPTION_RIGHTS[right])
    # 2) mm/dd(/yy|/yyyy)
    m = re.search(r"\b([a-z]{1,6})\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d+(\.\d+)?)\s*([cp]|call|put)\b", text)
    if m:
        sym, mo, da, yr, strike, _, right = m.groups()
        now = datetime.now()
        if yr:
            y = int(yr)
            y = 2000 + y if y < 100 else y
        else:
            # if month already passed this year, assume next year
            y = now.year
        dts_norm = f"{y:04d}-{int(mo):02d}-{int(da):02d}"
        return (sym.upper(), dts_norm, float(strike), OPTION_RIGHTS[right])
    return None

def _yf_option_quote(root: str, expiration_yyyy_mm_dd: str, strike: float, right: str) -> Optional[dict]:
    """
    Use yfinance to grab an option chain row (works without extra credentials).
    Returns dict with lastPrice/bid/ask/volume/oi/iv + underlying price.
    """
    try:
        t = yf.Ticker(root)
        chains = t.option_chain(expiration_yyyy_mm_dd)
        df = chains.calls if right == "call" else chains.puts
        if df is None or df.empty:
            return None
        row = df.loc[(df["strike"] - strike).abs().idxmin()]
        out = {
            "symbol": root,
            "expiration": expiration_yyyy_mm_dd,
            "strike": float(row["strike"]),
            "right": right,
            "last": float(row.get("lastPrice") or 0) or None,
            "bid": float(row.get("bid") or 0) or None,
            "ask": float(row.get("ask") or 0) or None,
            "volume": int(row.get("volume") or 0),
            "open_interest": int(row.get("openInterest") or 0),
            "iv": float(row.get("impliedVolatility") or 0) or None,
        }
        # underlying spot (approx)
        hist = t.history(period="1d", interval="1m", prepost=True)
        if isinstance(hist, pd.DataFrame) and not hist.empty:
            out["underlying"] = float(hist.dropna().iloc[-1]["Close"])
        else:
            info = getattr(t, "fast_info", None)
            if info and hasattr(info, "last_price"):
                out["underlying"] = float(info.last_price)
        return out
    except Exception:
        logging.exception("yfinance option chain failed for %s %s %s %s", root, expiration_yyyy_mm_dd, strike, right)
        return None

def _expected_move_pct(iv_annual: Optional[float], days_to_exp: int) -> Optional[float]:
    """
    Very rough 1-sigma expected move % by expiration using annual IV.
    EM% ≈ IV_annual * sqrt(days/365)
    """
    if not iv_annual or days_to_exp <= 0:
        return None
    try:
        return iv_annual * math.sqrt(days_to_exp / 365.0) * 100.0
    except Exception:
        return None

# If you later enable Alpaca Options Data, you can replace _yf_option_quote with Alpaca calls here.

# ---------- DISCORD CLIENT ----------
intents = discord.Intents.default()
intents.message_content = True  # allow plain-text chat & Q&A

class DeskBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._bg_task_prices: Optional[asyncio.Task] = None
        self._bg_task_scheduler: Optional[asyncio.Task] = None

    async def setup_hook(self):
        for gid in GUILDS:
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            try:
                synced = await self.tree.sync(guild=discord.Object(id=gid))
                logging.info(f"Synced {len(synced)} commands to guild {gid}")
            except Exception:
                logging.exception("Slash sync failed for guild %s", gid)

        if ENABLE_BG_ALERTS:
            self._bg_task_prices = asyncio.create_task(self.alerts_loop())
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
                    if p is not None:
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
    if p is None:
        await interaction.followup.send(f"Couldn't fetch **{symbol.upper()}** 🤷")
        return
    chg = pct_change(p, pc)
    out = f"**{symbol.upper()}**: ${p:,.2f}"
    if chg is not None:
        out += f"  ({chg:+.2f}%)"
    await interaction.followup.send(out)

@client.tree.command(name="price_dbg", description="Debug price sources & timestamps for a symbol")
@app_commands.describe(symbol="Ticker symbol like NVDA")
async def price_dbg(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer(thinking=True)
    info = await fetch_price(symbol)
    p, pc, asof, src = info.get("price"), info.get("prev_close"), info.get("asof"), info.get("source")
    chg = pct_change(p, pc)
    lines = [
        f"**{symbol.upper()}**",
        f"Source: `{src}`",
        f"As-of: `{asof}`" if asof else "As-of: (unknown)",
        f"Price: {p if p is not None else '(none)'}",
        f"Prev close: {pc if pc is not None else '(none)'}",
        f"Change vs prev: {f'{chg:+.2f}%' if chg is not None else '(n/a)'}",
    ]
    await interaction.followup.send("\n".join(lines))

@client.tree.command(name="brief", description="Post a quick market brief here or to the briefs channel.")
async def brief_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    syms = read_watchlist()[:8]
    lines = []
    for s in syms:
        info = await fetch_price(s)
        p, pc = info.get("price"), info.get("prev_close")
        if p is not None:
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

# --- OLLAMA HELPERS (local LLM via REST) ---
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
        return (data.get("message", {}) or {}).get("content", "").strip() or "…"
    return await asyncio.to_thread(_post)

async def ollama_chat(messages: list[dict], model: str, system: Optional[str] = None) -> str:
    payload_msgs = []
    if system:
        payload_msgs.append({"role": "system", "content": system})
    payload_msgs.extend(messages)

    def _post():
        r = requests.post(
            "http://localhost:11434/api/chat",
            json={"model": model, "messages": payload_msgs, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("message", {}) or {}).get("content", "").strip() or "…"
    return await asyncio.to_thread(_post)

# ---------- GOOD MORNING ----------
async def build_goodmorning_text(note: str | None) -> str:
    syms = read_watchlist()[:6]
    snap_lines = []
    for s in syms:
        info = await fetch_price(s)
        p, pc = info.get("price"), info.get("prev_close")
        if p is not None:
            chg = pct_change(p, pc)
            snap_lines.append(f"{s}: ${p:,.2f}" + (f" ({chg:+.2f}%)" if chg is not None else ""))

    user_line = note or "No specific note."
    context = (
        f"Date/time: {datetime.now(TZ).strftime('%A, %B %d, %Y • %I:%M %p %Z')}\n"
        f"Watchlist: " + (" | ".join(snap_lines) if snap_lines else "no data") + "\n"
        "Tone: quick, warm, a touch of clever humor; 3–6 sentences max.\n"
        "Include one tiny actionable nudge for the day.\n"
    )

    try:
        system = "You are a quick, warm morning assistant. Be concise, friendly, and practical. Add one actionable nudge."
        user   = f"User note: {user_line}\n\nContext:\n{context}"
        model  = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        logging.info("GM: using OLLAMA model=%s", model)
        text   = await ollama_reply(system, user, model)
        return text
    except Exception:
        logging.exception("Ollama call failed")
        return "Morning! (Ollama error—check that Ollama is running and the model is pulled.)\n" + context

@client.tree.command(name="goodmorning", description="Friendly morning reply + quick updates")
@app_commands.describe(note="Anything you want me to consider")
async def goodmorning(interaction: discord.Interaction, note: str | None = None):
    await interaction.response.defer(thinking=True)
    text = await build_goodmorning_text(note)
    await interaction.followup.send(text)

# ---------- ASK (local Ollama) ----------
@client.tree.command(name="ask", description="Ask your local AI (Ollama)")
@app_commands.describe(question="What do you want to ask?")
async def ask_cmd(interaction: discord.Interaction, question: str):
    await interaction.response.defer(thinking=True)
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    system = (
        "You are a helpful, concise assistant for a Discord user. "
        "Prefer clear, direct answers with quick, clever humor when appropriate."
    )
    try:
        text = await ollama_chat([{"role": "user", "content": question}], model, system=system)
        await interaction.followup.send((text or "(no answer)")[:1900])
    except Exception:
        logging.exception("ask_cmd error")
        await interaction.followup.send("Whoops—my local brain (Ollama) didn’t answer. Is the model running?")

# ---------- EARNINGS (slash) ----------
@client.tree.command(name="earnings", description="Show the latest/last earnings for a ticker")
@app_commands.describe(symbol="Ticker symbol, company name, or $TICKER (e.g., NVDA, nvidia, $NVDA)")
async def earnings_cmd(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer(thinking=True)
    sym = extract_symbol_for_earnings(symbol) or resolve_symbol_token(symbol) or symbol.upper()
    msg = await latest_earnings(sym)
    await interaction.followup.send(msg)

# ---------- OPTION (slash) ----------
@client.tree.command(name="option", description="Quote an options contract + rough expected move")
@app_commands.describe(
    symbol="Underlying (e.g., NVDA)",
    expiration="Expiration YYYY-MM-DD",
    strike="Strike price (e.g., 140)",
    right="call or put",
)
async def option_cmd(interaction: discord.Interaction, symbol: str, expiration: str, strike: float, right: str):
    await interaction.response.defer(thinking=True)
    right = OPTION_RIGHTS.get(right.lower(), None)
    if right is None:
        await interaction.followup.send("Right must be 'call' or 'put'.")
        return
    data = await asyncio.to_thread(_yf_option_quote, symbol.upper(), expiration, float(strike), right)
    if not data:
        await interaction.followup.send("Couldn't fetch that option (double-check expiration/strike).")
        return
    # rough expected move by expiration
    try:
        exp_dt = datetime.strptime(expiration, "%Y-%m-%d").date()
        days = max((exp_dt - datetime.now().date()).days, 0)
    except Exception:
        days = 0
    em = _expected_move_pct(data.get("iv"), days)
    lines = [
        f"**{symbol.upper()} {expiration} {data['strike']:.2f} {right.upper()}**",
        f"Underlying: ${data.get('underlying', 'n/a')}",
        f"Last: {data.get('last')}", f"Bid: {data.get('bid')}  Ask: {data.get('ask')}",
        f"Vol: {data.get('volume')}  OI: {data.get('open_interest')}",
        f"IV: {data.get('iv'):.3f}" if data.get("iv") else "IV: n/a",
        f"Rough expected move by exp: {em:.1f}%" if em is not None else "Expected move: n/a",
    ]
    await interaction.followup.send("\n".join(lines))

# ---------- GAME (ITAD price check) ----------
@client.tree.command(name="game", description="Check game price by ITAD slug")
@app_commands.describe(slug="e.g., hades or cyberpunk-2077")
async def game_cmd(interaction: discord.Interaction, slug: str):
    await interaction.response.defer(thinking=True)
    if not ITAD_KEY:
        await interaction.followup.send("ITAD not configured. Set **ITAD_KEY** in your `.env`.")
        return
    deals = fetch_itad_prices(slug, ITAD_KEY, ITAD_COUNTRY)
    if not deals:
        await interaction.followup.send(f"No live prices found for `{slug}`.")
        return
    top = deals[:5]
    lines = []
    for d in top:
        line = f"- {d['shop']}: ${d['price_new']:.2f}"
        po = d.get("price_old")
        try:
            if po not in (None, 0, "0"):
                line += f" (was ${float(po):.2f})"
        except Exception:
            pass
        if d.get("url"):
            line += f" — <{d['url']}>"
        lines.append(line)
    await interaction.followup.send(f"**{slug}** (top prices in {ITAD_COUNTRY})\n" + "\n".join(lines))

# ---------- NATURAL CHAT (DM / mention / 'g:' prefix) ----------
@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    is_dm = message.guild is None
    mentioned = (client.user in message.mentions) if client.user else False
    prefixed = content.lower().startswith("g:")

    if not (is_dm or mentioned or prefixed):
        return

    if mentioned and client.user:
        content = re.sub(rf'<@!?{client.user.id}>', '', content).strip()
    if prefixed:
        content = content[2:].strip()
    if not content:
        content = "Hello!"

    # quick time/date path
    m = re.search(r"\b(time|date)\b(?:\s+in\s+([A-Za-z/_\-\s]+))?", content, flags=re.I)
    if m:
        tz_query = (m.group(2) or "").strip() or None
        try:
            pretty = _format_now_in_tz(tz_query)
            await message.channel.send(
                f"🕒 **Current time** ({_norm_tz_name(tz_query)}): {pretty}",
                allowed_mentions=discord.AllowedMentions.none()
            )
            return
        except Exception:
            pass

    # earnings quick path
    sym = extract_symbol_for_earnings(content)
    if sym and re.search(r"\b(earnings|eps)\b", content, flags=re.I):
        reply = await latest_earnings(sym)
        await message.channel.send(reply, allowed_mentions=discord.AllowedMentions.none())
        return

    # option quick parse: "NVDA 9/19 140c", etc.
    parsed = _parse_option_freeform(content)
    if parsed:
        root, exp, strike, right = parsed
        data = await asyncio.to_thread(_yf_option_quote, root, exp, strike, right)
        if data:
            try:
                exp_dt = datetime.strptime(exp, "%Y-%m-%d").date()
                days = max((exp_dt - datetime.now().date()).days, 0)
            except Exception:
                days = 0
            em = _expected_move_pct(data.get("iv"), days)
            lines = [
                f"**{root} {exp} {data['strike']:.2f} {right.upper()}**",
                f"Underlying: ${data.get('underlying', 'n/a')}",
                f"Last: {data.get('last')}  Bid: {data.get('bid')}  Ask: {data.get('ask')}",
                f"Vol: {data.get('volume')}  OI: {data.get('open_interest')}",
                f"IV: {data.get('iv'):.3f}" if data.get("iv") else "IV: n/a",
                f"Rough expected move by exp: {em:.1f}%" if em is not None else "Expected move: n/a",
            ]
            await message.channel.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
            return

    # otherwise chat with LLM
    history: list[dict] = []
    async for m in message.channel.history(limit=8, oldest_first=False):
        if m.author.bot and (not client.user or m.author.id != client.user.id):
            continue
        role = "assistant" if (client.user and m.author.id == client.user.id) else "user"
        txt = m.content or ""
        if txt.strip():
            history.append({"role": role, "content": txt})
    history.reverse()
    if not history or history[-1]["role"] != "user" or history[-1]["content"] != content:
        history.append({"role": "user", "content": content})

    system = (
        "You are a helpful, concise Discord assistant. "
        "Answer clearly, be practical, and use quick, clever humor when appropriate."
    )
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    async with message.channel.typing():
        try:
            reply = await ollama_chat(history, model, system=system)
        except Exception:
            logging.exception("chat on_message error")
            reply = "Whoops—my local brain (Ollama) didn’t answer. Is the model running?"
        await message.channel.send(reply, allowed_mentions=discord.AllowedMentions.none())

# ---------- ENTRYPOINT ----------
def main():
    if not TOKEN or not GUILDS:
        raise SystemExit("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in .env")
    client.run(TOKEN)

if __name__ == "__main__":
    main()
