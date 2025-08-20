from __future__ import annotations
import time
from ..config import cfg
from ..util import now_ts
from ..storage import record_price, record_signal, update_extrema, record_alert, read_extrema
from .rules import RollingStats, evaluate_signals
from .paper_trade import PaperTrader
from .providers.yfinance_provider import YFinanceProvider
from .providers.alpaca_provider import AlpacaProvider
from .providers.polygon_provider import PolygonProvider

class StockWatcher:
    def __init__(self):
        self.stats = {t: RollingStats() for t in cfg.watchlist}
        self.trader = PaperTrader()
        if cfg.polygon_key:
            self.provider = PolygonProvider(cfg.polygon_key)
        elif cfg.alpaca_key and cfg.alpaca_secret:
            self.provider = AlpacaProvider(cfg.alpaca_key, cfg.alpaca_secret)
        else:
            self.provider = YFinanceProvider()

    def run_forever(self):
        print(f"[stocks] using provider={self.provider.__class__.__name__}, poll={cfg.poll_seconds}s")
        while True:
            prices = self.provider.get_last_prices(cfg.watchlist)
            if prices:
                for t, p in prices.items():
                    ts = now_ts()
                    record_price(ts, t, p, source=getattr(self.provider, "name", "provider"))
                    update_extrema(t, p, ts)
                    s = self.stats[t]; s.add(p)
                    signals = evaluate_signals(t, p, s)
                    for kind, val, note in signals:
                        record_signal(ts, t, kind, float(val), note)
                    if signals:
                        hi_lo = read_extrema().get(t, {})
                        msg = f"{t} @ {p:.2f} | signals: " + ", ".join(k for k,_,_ in signals)
                        if hi_lo: msg += f" | High {hi_lo.get('high')} / Low {hi_lo.get('low')}"
                        record_alert(ts, "stock", t, msg)
                    self.trader.on_signal(t, p, signals)
            time.sleep(cfg.poll_seconds)
