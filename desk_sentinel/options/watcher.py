from __future__ import annotations
import time
from ..config import cfg
from ..util import now_ts
from ..storage import record_alert
from .provider_polygon import PolygonOptions
from .strategy import nvda_suggestion
from .trader import OptionsPaperTrader

class OptionsWatcher:
    def __init__(self):
        self.provider = PolygonOptions()
        self.poll = max(30, cfg.poll_seconds)
        self.trader = OptionsPaperTrader(starting_equity=500.0)

    def run_forever(self):
        if not cfg.polygon_key or not cfg.options_enabled:
            return
        print("[options] polygon enabled; polling", self.poll, "s")
        while True:
            for t in ["NVDA"]:  # NVDA-only options for testing
                for c in self.provider.list_contracts(t):
                    p = self.provider.last_option_price(c["occ"])
                    if p is None: 
                        continue
                    sugg = nvda_suggestion(c["side"], int(c["strike"]), p)
                    subject = f"{t} {c['occ']}"
                    msg = f"{c['side']} {c['strike']} exp {c['expiry']} @ {p:.2f} | {sugg}"
                    record_alert(now_ts(), "option", subject, msg)
                    self.trader.on_price(c["occ"], p, sugg)
            time.sleep(self.poll)
