from __future__ import annotations
import requests

class PolygonProvider:
    name = "polygon"
    def __init__(self, api_key: str):
        self.key = api_key
    def get_last_prices(self, tickers):
        out = {}
        for t in tickers:
            try:
                r = requests.get(f"https://api.polygon.io/v2/last/trade/{t}", params={"apiKey": self.key}, timeout=5)
                if r.ok:
                    price = r.json().get("results", {}).get("p")
                    if price is not None:
                        out[t] = float(price)
            except Exception:
                pass
        return out
