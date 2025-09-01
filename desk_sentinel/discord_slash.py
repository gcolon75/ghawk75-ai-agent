"""
Slash-command Discord bot (global defs + guild fast-sync + diagnostics).
"""

from __future__ import annotations
import os, logging
import discord
from discord import app_commands

from .config import cfg
from .games.itad_client import current_deals
from .storage import ALERTS
from .llm.client import summarize

try:
    from openai import OpenAI  # optional
except Exception:
    OpenAI = None  # type: ignore

# ---------- logging / constants ----------
logging.basicConfig(level=logging.INFO)
INTENTS = discord.Intents.default()  # slash commands don't need message_content
MAX_DISCORD = 1900
EPHEMERAL_DEFAULT = False  # set True if you want private replies by default


# ---------- helpers ----------
async def _ack(i: discord.Interaction, *, ephemeral: bool = EPHEMERAL_DEFAULT, thinking: bool = True):
    if not i.response.is_done():
        try:
            await i.response.defer(ephemeral=ephemeral, thinking=thinking)
        except Exception:
            try:
                await i.response.send_message("Working…", ephemeral=ephemeral)
            except Exception:
                pass

async def _finish(i: discord.Interaction, content: str, *, ephemeral: bool = EPHEMERAL_DEFAULT):
    content = (content or "").strip()
    if len(content) > MAX_DISCORD:
        content = content[:MAX_DISCORD]
    try:
        await i.edit_original_response(content=content or "Done.")
    except Exception:
        try:
            await i.followup.send(content or "Done.", ephemeral=ephemeral)
        except Exception:
            pass


# ---------- client ----------
class SentinelSlash(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)

        # Inline error handler (no forward ref shenanigans)
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: Exception):
            logging.exception("Slash command error", exc_info=error)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {error}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {error}", ephemeral=True)
            except Exception:
                pass  # already logged

    async def setup_hook(self) -> None:
        # Resolve guild (for instant sync)
        guild = None
        gid = os.getenv("DISCORD_GUILD_ID")
        if gid:
            try:
                guild = discord.Object(id=int(gid))
            except Exception:
                logging.warning("Invalid DISCORD_GUILD_ID in .env: %r", gid)

        # 1) Clear local command views (global + this guild) to avoid stale shapes
        self.tree.clear_commands(guild=None)
        if guild:
            self.tree.clear_commands(guild=guild)

        # 2) Register commands as GLOBAL definitions (source of truth)
        self._register_commands()

        # 3) Copy global -> guild for instant availability, then sync
        if guild:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %d guild commands to %s", len(synced), gid)
        else:
            synced = await self.tree.sync()  # global sync (may take minutes to appear)
            logging.info("Synced %d global commands (may take time to appear)", len(synced))

        # 4) Log what we *locally* think exists
        global_names = [c.name for c in self.tree.get_commands()]
        logging.info("Local GLOBAL commands: %s", ", ".join(global_names) or "(none)")
        if guild:
            guild_names = [c.name for c in self.tree.get_commands(guild=guild)]
            logging.info("Local GUILD  commands: %s", ", ".join(guild_names) or "(none)")

    def _register_commands(self) -> None:
        tree = self.tree

        # --- diagnostics ---
        @tree.command(name="diag", description="Show which commands the bot has loaded")
        async def diag(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            # List the names from the local tree to confirm registration
            names = [c.name for c in tree.get_commands()]
            msg = "**Loaded (GLOBAL) commands**\n" + (", ".join(names) or "(none)")
            await _finish(i, msg, ephemeral=False)

        # --- basic ---
        @tree.command(name="ping", description="Bot heartbeat")
        async def _ping(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            await _finish(i, "pong", ephemeral=False)

        # Some servers are picky; give help two names.
        @tree.command(name="help", description="List commands")
        async def _help(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            await _finish(i, _help_text(), ephemeral=False)

        @tree.command(name="commands", description="List commands (alias of /help)")
        async def _commands(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            await _finish(i, _help_text(), ephemeral=False)

        # --- watchlist ---
        @tree.command(name="watchlist_add", description="Add tickers (space-separated)")
        @app_commands.describe(tickers="e.g. NVDA MSFT AAPL")
        async def watchlist_add(i: discord.Interaction, tickers: str):
            await _ack(i, ephemeral=False)
            try:
                toks = [t.strip().upper() for t in tickers.split() if t.strip()]
                added = [t for t in toks if t not in cfg.watchlist]
                cfg.watchlist += added
                msg = f"Added: {', '.join(added) or 'none'}\nCurrent: {', '.join(cfg.watchlist)}"
            except Exception as e:
                logging.exception("watchlist_add")
                msg = f"watchlist_add error: {e}"
            await _finish(i, msg, ephemeral=False)

        @tree.command(name="watchlist_remove", description="Remove tickers (space-separated)")
        @app_commands.describe(tickers="e.g. QUBT PLTR")
        async def watchlist_remove(i: discord.Interaction, tickers: str):
            await _ack(i, ephemeral=False)
            try:
                toks = {t.strip().upper() for t in tickers.split() if t.strip()}
                cfg.watchlist[:] = [t for t in cfg.watchlist if t not in toks]
                msg = f"Removed: {', '.join(sorted(toks)) or 'none'}\nCurrent: {', '.join(cfg.watchlist)}"
            except Exception as e:
                logging.exception("watchlist_remove")
                msg = f"watchlist_remove error: {e}"
            await _finish(i, msg, ephemeral=False)

        @tree.command(name="watchlist_show", description="Show current tickers")
        async def watchlist_show(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            await _finish(i, f"Watchlist: {', '.join(cfg.watchlist) or '(empty)'}", ephemeral=False)

        # --- games ---
        @tree.command(name="game", description="Check game price by ITAD slug")
        @app_commands.describe(slug="e.g. hades or cyberpunk-2077")
        async def game(i: discord.Interaction, slug: str):
            await _ack(i, ephemeral=False)
            try:
                if not cfg.itad_key:
                    await _finish(i, "ITAD not configured.", ephemeral=False); return
                deals = current_deals(cfg.itad_key, [slug])
                if not deals or not deals[0].get("entries"):
                    await _finish(i, f"No live prices for `{slug}`.", ephemeral=False); return
                e = deals[0]["entries"][:5]
                rows = [
                    f"- {x.get('shop','store')}: ${float(x.get('price_new') or 0):.2f}"
                    + (f" (was ${float(x.get('price_old') or 0):.2f})" if x.get('price_old') else "")
                    for x in e
                ]
                await _finish(i, f"**{slug}**\n" + "\n".join(rows), ephemeral=False)
            except Exception as e:
                logging.exception("game")
                await _finish(i, f"game error: {e}", ephemeral=False)

        # --- status / summary ---
        @tree.command(name="status", description="Show watchlist & recent alerts")
        async def status(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            try:
                lines = []
                if os.path.exists(ALERTS):
                    with open(ALERTS, "r", encoding="utf-8") as f:
                        lines = f.readlines()[-6:]
                msg = f"Watching: {', '.join(cfg.watchlist) or '(empty)'}"
                if lines:
                    msg += "\nRecent alerts:\n" + "".join(lines)
            except Exception as e:
                logging.exception("status")
                msg = f"status error: {e}"
            await _finish(i, msg, ephemeral=False)

        @tree.command(name="summary", description="Summarize recent alerts")
        async def summary_cmd(i: discord.Interaction):
            await _ack(i, ephemeral=False)
            try:
                if not os.path.exists(ALERTS):
                    await _finish(i, "No alerts yet.", ephemeral=False); return
                with open(ALERTS, "r", encoding="utf-8") as f:
                    tail = "".join(f.readlines()[-120:])
                s = summarize(tail) if tail else "No notable changes."
                await _finish(i, s, ephemeral=False)
            except Exception as e:
                logging.exception("summary")
                await _finish(i, f"summary error: {e}", ephemeral=False)

        # --- ask LLM ---
        @tree.command(name="ask", description="Ask ChatGPT (requires OPENAI_API_KEY)")
        @app_commands.describe(question="Your question")
        async def ask(i: discord.Interaction, question: str):
            await _ack(i, ephemeral=False)
            try:
                if not OpenAI or not cfg.openai_key:
                    await _finish(i, "OpenAI not configured.", ephemeral=False); return
                client = OpenAI(api_key=cfg.openai_key)
                resp = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": question}],
                    max_tokens=400, temperature=0.4,
                )
                answer = (resp.choices[0].message.content or "").strip()
                await _finish(i, answer or "(no answer)", ephemeral=False)
            except Exception as e:
                logging.exception("ask")
                await _finish(i, f"ask error: {e}", ephemeral=False)

    async def on_ready(self):
        print(f"[slash] Logged in as {self.user}")


def _help_text() -> str:
    return (
        "**Commands**\n"
        "/ping\n"
        "/help   (or /commands)\n"
        "/watchlist_add <TICKERS>\n"
        "/watchlist_remove <TICKERS>\n"
        "/watchlist_show\n"
        "/game <slug>\n"
        "/status\n"
        "/summary\n"
        "/ask <question>\n"
        "/diag   (shows what the bot actually loaded)\n"
    )


# ---------- entrypoint ----------
def main():
    token = cfg.discord_bot_token
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN missing in environment/.env")
    SentinelSlash().run(token)

if __name__ == "__main__":
    main()
