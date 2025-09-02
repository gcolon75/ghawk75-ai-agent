# desk_sentinel/discord_check.py
import os, asyncio, logging
from dotenv import load_dotenv, find_dotenv   # ⬅️ add this
import discord
from discord import app_commands

load_dotenv(find_dotenv())  # ⬅️ add this (finds .env at repo root reliably)

logging.basicConfig(level=logging.INFO)
try:
    discord.utils.setup_logging(level=logging.INFO)
except Exception:
    pass

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILDS = [int(g) for g in os.getenv("DISCORD_GUILD_ID", "").split(",") if g.strip()]

intents = discord.Intents.default()
intents.message_content = True

class DeskCheck(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        for gid in GUILDS:
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            synced = await self.tree.sync(guild=discord.Object(id=gid))
            logging.info(f"Synced {len(synced)} commands to guild {gid}")

client = DeskCheck()

@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user} (latency {client.latency*1000:.0f}ms)")

@client.tree.command(name="ping", description="Checks if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! I hear you.")

def main():
    if not TOKEN:
        raise SystemExit("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in .env")
    client.run(TOKEN)

if __name__ == "__main__":
    main()
