import os
from alpaca_trade_api.rest import REST, TimeFrame

api = REST(
    os.getenv("ALPACA_KEY_ID"),
    os.getenv("ALPACA_SECRET_KEY"),
    base_url=os.getenv("APCA_API_BASE_URL","https://paper-api.alpaca.markets"),
)

t = api.get_latest_trade("AAPL")
print("price:", getattr(t, "price", None), "ts:", getattr(t, "timestamp", None))
