from __future__ import annotations
import threading, time, datetime as dt, pytz, os
from .config import cfg
from .stock.watcher import StockWatcher
from .games.watcher import GameWatcher
from .options.watcher import OptionsWatcher
from .notifier import send_embed, send_simple
from .llm.client import summarize
from .storage import ALERTS

def _thread(target):
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t

def run():
    # Startup ping (bypass quiet hours so you can see it's alive)
    watch = ", ".join(cfg.watchlist)
    send_simple(f"✅ DeskSentinel is online and monitoring: {watch}.\nMorning briefs 07:30 PT, evening briefs 22:00 PT.", dedupe_key="startup_ping", bypass_quiet=True)

    stock = StockWatcher()
    games = GameWatcher()
    opts = OptionsWatcher()
    _thread(stock.run_forever)
    _thread(games.run_forever)
    _thread(opts.run_forever)
    print("[agent] running… Ctrl+C to stop")

    while True:
        tz = pytz.timezone(cfg.timezone); now = dt.datetime.now(tz)
        at_morning = now.hour == 7 and now.minute == 30
        at_evening = now.hour == 22 and now.minute == 0  # 10pm PT
        if at_morning or at_evening:
            try:
                if os.path.exists(ALERTS):
                    with open(ALERTS, "r", encoding="utf-8") as f:
                        last_lines = f.readlines()[-80:]
                else:
                    last_lines = []
                body = "".join(last_lines[-40:])
                summary = summarize(body) if body else "No notable changes."
                send_embed(title=("Morning Brief" if at_morning else "Evening Brief"),
                           description=summary[:1500],
                           fields=[("Recent Alerts (tail)","```\n"+body[-900:]+"\n```")])
            except Exception:
                pass
            time.sleep(61)
        time.sleep(5)

if __name__ == "__main__":
    run()
