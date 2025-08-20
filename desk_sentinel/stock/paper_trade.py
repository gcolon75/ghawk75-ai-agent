from __future__ import annotations
from ..util import now_ts
from ..storage import record_trade

class PaperTrader:
    def __init__(self):
        self.positions = {}
    def on_signal(self, ticker: str, price: float, signals: list[tuple[str,float,str]]):
        kinds = {k for k,_,_ in signals}
        ts = now_ts()
        if "rsi_oversold" in kinds and ticker not in self.positions:
            self.positions[ticker] = {"avg": price, "qty": 1}
            record_trade(ts=ts, ticker=ticker, side="BUY", qty=1, price=price, instrument="stock")
        if "rsi_overbought" in kinds and ticker in self.positions:
            pos = self.positions.pop(ticker)
            record_trade(ts=ts, ticker=ticker, side="SELL", qty=pos["qty"], price=price, instrument="stock")
