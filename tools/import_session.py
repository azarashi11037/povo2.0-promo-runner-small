#!/usr/bin/env python3
"""Build private session files from GitHub Secrets without echoing them."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Required GitHub Secret is missing: {name}")
    return value


def _decode_secret(name: str) -> bytes:
    try:
        return base64.b64decode(_secret(name), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"{name} is not valid standard base64.") from error


def _write_private(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--next-due-at", required=True)
    args = parser.parse_args()

    due = datetime.fromisoformat(args.next_due_at)
    if due.tzinfo is None:
        due = due.replace(tzinfo=JST)
    due = due.astimezone(JST)
    if due <= datetime.now(JST):
        raise ValueError("next_due_at must be in the future.")

    code = _secret("POVO_PROMO_CODE")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", code):
        raise ValueError("POVO_PROMO_CODE has an unsupported format.")

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.data_dir.chmod(0o700)
    _write_private(args.data_dir / "credentials.xml", _decode_secret("POVO_CREDENTIALS_B64"))
    _write_private(args.data_dir / "device.xml", _decode_secret("POVO_DEVICE_B64"))
    _write_private(args.data_dir / "code", (code + "\n").encode("utf-8"))
    state = {
        "version": 2,
        "phase": "scheduled",
        "paused": False,
        "next_due_at": due.replace(second=0, microsecond=0).isoformat(
            timespec="minutes"
        ),
        "last_success_at": None,
        "last_attempt_at": None,
        "last_result": "github_session_imported",
        "last_message": "Authorized session imported into an encrypted GitHub bundle.",
    }
    _write_private(
        args.data_dir / "state.json",
        (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print("Private session files prepared without printing secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
