from __future__ import annotations
import time
from ..config import cfg
from ..util import now_ts
from ..storage import record_game_price, record_alert
from .itad_client import current_deals

class GameWatcher:
    def __init__(self):
        self.interval = max(600, cfg.poll_seconds * 60)
    def run_forever(self):
        if not cfg.itad_key:
            return
        print(f"[games] polling every ~{self.interval}s via ITAD")
        while True:
            deals = current_deals(cfg.itad_key, cfg.game_slugs)
            for d in deals:
                slug = d["slug"]
                for e in d.get("entries", [])[:3]:
                    price = float(e.get("price_new") or 0.0)
                    normal = float(e.get("price_old") or 0.0) or None
                    store = e.get("shop", "store")
                    best12 = bool(e.get("is_lowest", False))
                    atl = False
                    record_game_price(now_ts(), store, slug, price, normal, best12, atl)
                    if price and normal and price <= normal * 0.8:
                        record_alert(now_ts(), "game", slug, f"{slug}: {store} ${price:.2f} (normal ${normal:.2f})")
            time.sleep(self.interval)
