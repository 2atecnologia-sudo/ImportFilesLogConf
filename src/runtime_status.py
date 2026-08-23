from __future__ import annotations

import json
import os
from datetime import datetime


def _status_path(base_dir: str) -> str:
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "runtime_status.json")


def write_runtime_status(base_dir: str, data: dict) -> None:
    payload = dict(data)
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    path = _status_path(base_dir)
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(temp, path)


def read_runtime_status(base_dir: str) -> dict:
    path = _status_path(base_dir)

    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}