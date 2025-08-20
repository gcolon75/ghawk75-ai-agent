from __future__ import annotations
import datetime as dt, pytz, requests
from ..config import cfg

class PolygonOptions:
    name = "polygon_options"
    def underlying_last(self, ticker: str):
        try:
            r = requests.get(f"https://api.polygon.io/v2/last/trade/{ticker}", params={"apiKey": cfg.polygon_key}, timeout=5)
            if r.ok:
                return float(r.json().get("results", {}).get("p"))
        except Exception:
            return None
        return None

    def list_contracts(self, ticker: str):
        last = self.underlying_last(ticker)
        if last is None: return []
        strikes = [round(last), round(last)+1, round(last)-1]
        tz = pytz.timezone(cfg.timezone)
        now = dt.datetime.now(tz)
        days_ahead = (4 - now.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        expiry = (now + dt.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        contracts = []
        for K in strikes:
            for side in ["C","P"]:
                occ = f"{ticker}{expiry.replace('-','')}{side}{int(K):08d}"
                contracts.append({"ticker": ticker, "occ": occ, "expiry": expiry, "strike": K, "side": side})
        return contracts

    def last_option_price(self, occ: str):
        try:
            r = requests.get(f"https://api.polygon.io/v2/last/trade/O:{occ}", params={"apiKey": cfg.polygon_key}, timeout=5)
            if r.ok:
                p = r.json().get("results", {}).get("p")
                if p is not None:
                    return float(p)
        except Exception:
            return None
        return None
