#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
ITERATIONS = 310_000


def write_private(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a private data directory.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    protected = [data_dir / "web_auth.json", data_dir / "code", data_dir / "state.json"]
    if not args.force and any(path.exists() for path in protected):
        raise SystemExit("Refusing to overwrite existing data; use --force if intentional.")

    username = input("Dashboard username: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        raise SystemExit("Unsupported username format.")
    password = getpass.getpass("Dashboard password: ")
    if len(password) < 12:
        raise SystemExit("Use a dashboard password of at least 12 characters.")
    if password != getpass.getpass("Repeat dashboard password: "):
        raise SystemExit("Passwords do not match.")
    promo_code = getpass.getpass("Promo code (input hidden): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", promo_code):
        raise SystemExit("Unsupported promo code format.")

    due_text = input("Next run in JST (YYYY-MM-DDTHH:MM, blank to pause): ").strip()
    due = None
    if due_text:
        due = datetime.fromisoformat(due_text)
        if due.tzinfo is None:
            due = due.replace(tzinfo=JST)
        due = due.astimezone(JST)
        if due <= datetime.now(JST):
            raise SystemExit("The next run must be in the future.")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    auth = {
        "username": username,
        "salt": salt.hex(),
        "iterations": ITERATIONS,
        "password_hash": digest.hex(),
    }
    state = {
        "version": 2,
        "phase": "scheduled",
        "paused": due is None,
        "next_due_at": (
            due.replace(second=0, microsecond=0).isoformat(timespec="minutes")
            if due
            else None
        ),
        "last_success_at": None,
        "last_attempt_at": None,
        "last_result": "initialized",
        "last_message": "Authentication must be checked before enabling redemption.",
    }
    write_private(data_dir / "web_auth.json", json.dumps(auth, indent=2) + "\n")
    write_private(data_dir / "code", promo_code + "\n")
    write_private(data_dir / "state.json", json.dumps(state, indent=2) + "\n")
    write_private(data_dir / "history.jsonl", "")
    print(f"Initialized {data_dir} without printing secrets.")
    print("Add authorized credentials.xml and device.xml, then keep all files mode 0600.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
