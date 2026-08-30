#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen


def worker_health() -> int:
    path = Path(os.environ.get("POVO_DATA_DIR", "/data")) / "runtime.json"
    if not path.exists():
        return 1
    heartbeat = json.loads(path.read_text(encoding="utf-8")).get("worker_heartbeat_at")
    if not heartbeat:
        return 1
    age = (datetime.now().astimezone() - datetime.fromisoformat(heartbeat)).total_seconds()
    return 0 if age < 60 else 1


def web_health() -> int:
    with urlopen("http://127.0.0.1:8080/healthz", timeout=3) as response:
        return 0 if response.status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(worker_health() if sys.argv[1:] == ["worker"] else web_health())
