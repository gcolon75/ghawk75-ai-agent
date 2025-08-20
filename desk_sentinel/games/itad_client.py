from __future__ import annotations
import requests, time

BASE = "https://api.isthereanydeal.com/v02"
def current_deals(key: str, slugs: list[str]) -> list[dict]:
    out = []
    for s in slugs:
        try:
            r = requests.get(f"{BASE}/game/prices/", params={"key": key, "plains": s, "region":"us", "country":"US"})
            if r.ok:
                data = r.json().get("data", {})
                if s in data:
                    out.append({"slug": s, "entries": data[s].get("list", [])})
        except Exception:
            pass
        time.sleep(0.25)
    return out
