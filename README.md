# Ghawk75 AI Agent

This repository contains the source code for **DeskSentinel**, a modular agent designed to run
continuously on your personal computer (or a small server) and monitor both stock
prices and video game deals.  It delivers real‑time alerts to Discord and
produces daily summaries using a cloud language model.

## Features

* **Real‑time stock monitoring** – Watches a configurable list of tickers via a
  market data API (e.g. Polygon, IEX Cloud, Alpaca).  Maintains rolling price
  history, computes common technical indicators (RSI, moving averages, MACD,
  VWAP) and records all‑time highs/lows.
* **Game deal tracking** – Polls multiple storefront APIs (Steam, Ubisoft
  Connect, EA/Origin, Epic Games Store, G2A) and cross‑references historical
  pricing to identify notable discounts, new lows and bundle opportunities.
* **Rule engine** – Defines flexible conditions for alerting on price changes
  and technical signals.  Supports per‑ticker thresholds, crossovers, percent
  moves and quiet hours with deduplication.
* **Discord notifications** – Sends rich messages to a webhook, including
  contextual data such as current price, percent change, all‑time high/low,
  suggested support/resistance levels or best 12‑month deal.
* **Daily briefs** – Summarises the day’s activity every morning and evening
  using a cloud LLM.  Includes P&L from the built‑in paper trading account and
  highlights potential plays.
* **Paper trading** – Simulates trades based on the agent’s recommendations to
  allow backtesting strategies before risking real capital.  Tracks equity
  curve and win rate.
* **Local dashboard** – Provides a simple web interface to view live prices,
  configure alerts, review the alert log and inspect game deal history.  Only
  bound to `localhost` by default.

## Getting Started

### Prerequisites

* Python 3.10 or newer
* Docker and Docker Compose (optional, recommended for ease of deployment)
* A Discord webhook URL
* API keys for your chosen market data provider (e.g. Polygon or IEX) and
  IsThereAnyDeal (for game pricing)

### Installation

Clone this repository and install the required dependencies:

```
git clone https://github.com/Ghawk75/ghawk75-ai-agent.git
cd ghawk75-ai-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root and populate it with your secrets.  An
example is provided in `.env.example`:

```
# .env
DISCORD_WEBHOOK_URL=your-discord-webhook-url
MARKET_DATA_API_KEY=your-market-data-api-key
IS_THERE_ANY_DEAL_API_KEY=your-itad-api-key
TIMEZONE=America/Los_Angeles
WATCHLIST=NVDA,QUBT,PLTR,LMT,JPM,AAPL
```

To run the agent locally:

```
python -m sentinel_core.main
```

To run using Docker Compose:

```
docker compose up -d
```

## Repository Structure

```
ghawk75_ai_agent/
├── docker-compose.yml     # Container definitions for core, web and worker
├── requirements.txt       # Python dependencies
├── README.md              # This document
└── sentinel_core/         # Core application package
    ├── __init__.py
    ├── database.py        # SQLite schema and helper functions
    ├── game_watcher.py    # Game price crawling and rules
    ├── stock_watcher.py   # Stock price streaming and rules
    ├── rules.py           # Alert definitions and evaluation logic
    └── main.py            # Entry point and orchestration
```

## Contributing

Pull requests are welcome!  Please open an issue first to discuss what you
would like to change.  For major changes, please open an issue to propose
changes and ensure they fit within the scope of this project.

## Disclaimer

This software is provided for educational and personal use only.  It does
**not** constitute financial advice.  Trading stocks carries risk and you
should consult a qualified financial advisor before making any investment
decisions.
