# Ghawk75 AI Agent — DeskSentinel (Windows)

An always-on desktop agent that watches **stocks** and **video game deals**, stores data in **CSV** (human-readable), keeps **permanent highs/lows**, and pings you on **Discord**. Includes **Polygon stocks + options**, **NVDA-only options** (ATM ±1 to nearest Friday) for testing, **quiet hours**, **cooldowns**, and **morning (7:30am PT) / evening (10:00pm PT)** briefs. Comes with a **Task Scheduler** XML for run-on-logon. On startup it posts a **✅ DeskSentinel is online** ping to your Discord.

---
## Quick Start (Windows)
1. Install Python **3.11+** (check “Add Python to PATH”).
2. Open PowerShell in the project folder and run:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
3. Edit `.env` (Discord webhook or bot, POLYGON key, etc.).
4. Run:
```powershell
python -m desk_sentinel.cli
# or headless:
python -m desk_sentinel.agent
```

---
## What it does
- **Stocks**: polls watchlist; logs prices, computes SMA20/50, RSI14; alerts & keeps all-time high/low.
- **Options**: NVDA-only by default; monitors **nearest Friday** ATM ±1 strikes via Polygon; posts contract updates; simple paper-trade entries.
- **Games**: optional IsThereAnyDeal (ITAD) integration to track multi-store deals.
- **Briefs**: 7:30am and 10:00pm PT summaries to Discord.
- **Hygiene**: quiet hours (default 23:00–07:00), per-alert cooldown, dedupe.
- **Startup ping**: sends a message to Discord immediately when the agent launches.

---
## Files created (in `data/`)
- `prices.csv`, `signals.csv`, `alerts.csv`, `paper_trades.csv`, `game_prices.csv`
- `extrema.json` (permanent highs/lows)

---
## Run on Logon (Task Scheduler)
Import `windows-task-DeskSentinel.xml` in Task Scheduler → set **Start in** to your project folder.

---
## Notes
- Default watchlist: `NVDA,QUBT,PLTR,LMT,JPM,AAPL` (stocks; options watcher is **NVDA only**).
