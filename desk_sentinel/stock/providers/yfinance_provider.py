from __future__ import annotations
import yfinance as yf

class YFinanceProvider:
    name = "yfinance"
    def get_last_prices(self, tickers):
        data = {}
        try:
            prices = yf.download(list(tickers), period="1d", interval="1m", progress=False, prepost=True, threads=False)
            if "Close" in prices:
                last = prices["Close"].iloc[-1]
                if hasattr(last, "to_dict"):
                    data = {t: float(p) for t, p in last.to_dict().items() if p is not None}
                else:
                    t = list(tickers)[0]
                    data[t] = float(last)
        except Exception:
            pass
        return data
