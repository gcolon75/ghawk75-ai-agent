from __future__ import annotations
from alpaca_trade_api.rest import REST

class AlpacaProvider:
    name = "alpaca"
    def __init__(self, key, secret):
        self.api = REST(key, secret, api_version="v2")
    def get_last_prices(self, tickers):
        out = {}
        for t in tickers:
            try:
                quote = self.api.get_last_trade(t)
                out[t] = float(quote.price)
            except Exception:
                pass
        return out
