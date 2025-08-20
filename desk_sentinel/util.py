from __future__ import annotations
import os, json, time, datetime as dt, pytz
from typing import Any
from .config import cfg

def now_ts() -> str:
    tz = pytz.timezone(cfg.timezone)
    return dt.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def ensure_data_dir() -> str:
    os.makedirs(cfg.data_dir, exist_ok=True)
    return cfg.data_dir

def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def rolling_csv_append(path: str, row_dict: dict[str, Any]) -> None:
    exists = os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if not exists:
            f.write(",".join(row_dict.keys()) + "\n")
        f.write(",".join(str(v) for v in row_dict.values()) + "\n")
