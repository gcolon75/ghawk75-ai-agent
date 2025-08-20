from __future__ import annotations
from ..util import now_ts
from ..storage import record_trade

class OptionsPaperTrader:
    def __init__(self, starting_equity: float = 500.0, risk_frac: float = 0.2):
        self.equity = starting_equity
        self.risk_frac = risk_frac
        self.positions = {}  # occ -> dict(avg, qty)

    def on_price(self, occ: str, price: float, suggestion: str):
        ts = now_ts()
        if "BUY" in suggestion and occ not in self.positions and price > 0:
            budget = max(1.0, self.equity * self.risk_frac)
            qty = 1  # conservative
            self.positions[occ] = {"avg": price, "qty": qty}
            record_trade(ts=ts, ticker=occ, side="BUY", qty=qty, price=price, instrument="option")
