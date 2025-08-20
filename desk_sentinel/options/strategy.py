from __future__ import annotations

def nvda_suggestion(side: str, strike: int, price: float) -> str:
    # Simple placeholder logic; replace later with richer factors.
    if side == "C":
        return "BUY CALL" if price <= strike + 1 else "HOLD"
    else:
        return "BUY PUT" if price >= strike - 1 else "HOLD"
