from __future__ import annotations
import sys, pandas as pd, os
from .agent import run as run_agent
from .storage import PRICES, ALERTS, GAMES, TRADES, read_extrema
from .util import ensure_data_dir

MENU = (
    "\nDeskSentinel - choose:\n"
    "  1 - Run agent\n"
    "  2 - Show latest stock prices\n"
    "  3 - Show recent alerts\n"
    "  4 - Show latest game deals\n"
    "  5 - Show paper trading log\n"
    "  6 - Show permanent highs/lows\n"
    "  0 - Exit\n> "
)

def tail_csv(path: str, n: int = 20):
    if not os.path.exists(path):
        print("(no data yet)"); return
    try:
        df = pd.read_csv(path)
        print(df.tail(n).to_string(index=False))
    except Exception as e:
        print(f"error reading {path}: {e}")

def main():
    ensure_data_dir()
    while True:
        choice = input(MENU).strip()
        if choice == "1":
            print("Starting agent... press Ctrl+C to stop.")
            try:
                run_agent()
            except KeyboardInterrupt:
                print("\nStopped.")
        elif choice == "2":
            tail_csv(PRICES)
        elif choice == "3":
            tail_csv(ALERTS)
        elif choice == "4":
            tail_csv(GAMES)
        elif choice == "5":
            tail_csv(TRADES)
        elif choice == "6":
            print(read_extrema())
        elif choice == "0":
            sys.exit(0)
        else:
            print("??")

if __name__ == "__main__":
    main()
