from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

def _split(env_name: str, fallback: str) -> list[str]:
    raw = os.getenv(env_name) or fallback
    # allow empty -> []
    items = [s.strip() for s in raw.split(",")] if raw else []
    return [s for s in items if s]

@dataclass
class Config:
    # Discord
    discord_webhook: str | None = os.getenv("DISCORD_WEBHOOK_URL") or None
    discord_channel_id: str | None = os.getenv("DISCORD_CHANNEL_ID") or None
    discord_bot_token: str | None = os.getenv("DISCORD_BOT_TOKEN") or None

    # Market data
    alpaca_key: str | None = os.getenv("ALPACA_API_KEY") or None
    alpaca_secret: str | None = os.getenv("ALPACA_API_SECRET") or None
    polygon_key: str | None = os.getenv("POLYGON_API_KEY") or None

    # LLMs (optional)
    openai_key: str | None = os.getenv("OPENAI_API_KEY") or None
    pplx_key: str | None = os.getenv("PPLX_API_KEY") or None
    xai_key: str | None = os.getenv("XAI_API_KEY") or None

    # Stocks
    watchlist: list[str] = field(default_factory=lambda: _split("WATCHLIST", "NVDA,QUBT,PLTR,LMT,JPM,AAPL"))
    poll_seconds: int = int(os.getenv("POLL_SECONDS") or "30")

    # Options
    options_enabled: bool = (os.getenv("OPTIONS_ENABLED") or "1") == "1"
    options_style: str = os.getenv("OPTIONS_STYLE") or "atm_plusminus1"
    options_expiry_days: int = int(os.getenv("OPTIONS_EXPIRY_DAYS") or "5")
    options_symbols: list[str] = field(default_factory=lambda: _split("OPTIONS_SYMBOLS", "NVDA"))

    # Games
    itad_key: str | None = os.getenv("ITAD_API_KEY") or None
    game_slugs: list[str] = field(default_factory=lambda: _split("GAME_SLUGS", "hades,cyberpunk-2077"))

    # Time & hygiene
    timezone: str = os.getenv("TIMEZONE") or "America/Los_Angeles"
    quiet_hours: str = os.getenv("QUIET_HOURS") or "23:00-07:00"
    alert_cooldown_minutes: int = int(os.getenv("ALERT_COOLDOWN_MIN") or "30")

    # Data dir
    data_dir: str = os.path.abspath(os.path.join(os.getcwd(), "data"))

cfg = Config()
