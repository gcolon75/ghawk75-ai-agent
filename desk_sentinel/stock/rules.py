from __future__ import annotations
from collections import deque

class RollingStats:
    def __init__(self, maxlen=200):
        self.prices = deque(maxlen=maxlen)
    def add(self, p: float):
        self.prices.append(p)
    def sma(self, n: int):
        if len(self.prices) < n: return None
        vals = list(self.prices)[-n:]
        return sum(vals)/len(vals)
    def rsi(self, n: int = 14):
        if len(self.prices) < n+1: return None
        gains, losses = 0.0, 0.0
        seq = list(self.prices)
        for a, b in zip(seq[-n-1:-1], seq[-n:]):
            d = b - a
            if d >= 0: gains += d
            else: losses -= d
        if losses == 0: return 100.0
        rs = gains / losses
        return 100 - (100 / (1 + rs))

def evaluate_signals(ticker: str, p: float, stats: RollingStats):
    signals = []
    sma20 = stats.sma(20)
    sma50 = stats.sma(50)
    rsi14 = stats.rsi(14)
    if sma20 and sma50:
        if sma20 > sma50: signals.append(("trend", 1.0, "SMA20>50"))
        elif sma20 < sma50: signals.append(("trend", -1.0, "SMA20<50"))
    if rsi14 is not None:
        if rsi14 <= 30: signals.append(("rsi_oversold", rsi14, "RSI<=30"))
        if rsi14 >= 70: signals.append(("rsi_overbought", rsi14, "RSI>=70"))
    return signals
