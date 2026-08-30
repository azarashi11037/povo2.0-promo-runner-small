#!/usr/bin/env python3
"""Create an encrypted povo2.0 session through the authorized email OTP flow."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from povo_api import APP_VERSION, BASE_URL, USER_AGENT, Credentials, PovoClient
from tools.session_bundle import pack


JST = ZoneInfo("Asia/Tokyo")
LOGIN_AAD = b"povo-promo-automation/login-challenge/v1"
PACKAGE_SUFFIX = "com.kddi.kdla.jp"


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Required GitHub Secret is missing: {name}")
    return value


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 20:
        raise ValueError("POVO_BUNDLE_KEY must contain at least 20 characters.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def encrypt_challenge(challenge: dict[str, Any], output: Path, key: str) -> None:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    plaintext = json.dumps(challenge, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_derive_key(key, salt)).encrypt(nonce, plaintext, LOGIN_AAD)
    envelope = {
        "version": 1,
        "cipher": "AES-256-GCM",
        "kdf": {"name": "scrypt", "n": 32768, "r": 8, "p": 1},
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "ciphertext": _encode(ciphertext),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)


def decrypt_challenge(path: Path, key: str) -> dict[str, Any]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("version") != 1 or envelope.get("cipher") != "AES-256-GCM":
        raise ValueError("Unsupported login challenge format.")
    if envelope.get("kdf") != {"name": "scrypt", "n": 32768, "r": 8, "p": 1}:
        raise ValueError("Unsupported login challenge KDF parameters.")
    try:
        plaintext = AESGCM(
            _derive_key(key, _decode(envelope["salt"]))
        ).decrypt(_decode(envelope["nonce"]), _decode(envelope["ciphertext"]), LOGIN_AAD)
    except InvalidTag as error:
        raise ValueError("Login challenge authentication failed.") from error
    value = json.loads(plaintext)
    required = {"email", "device_id", "auth_id", "created_at"}
    if not isinstance(value, dict) or not required <= set(value):
        raise ValueError("Login challenge is incomplete.")
    return value


def _find(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        for item_key, item in value.items():
            if item_key == key:
                return item
            found = _find(item, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find(item, key)
            if found is not None:
                return found
    return None


def _headers(device_id: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Accept-Language": "ja-JP",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-App-Platform": "Android",
        "X-App-Version": APP_VERSION,
        "X-Deviceid": device_id,
    }


def _post(path: str, body: dict[str, Any], device_id: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers=_headers(device_id),
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=30, context=ssl.create_default_context()
        ) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read()
        try:
            detail = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            detail = {}
        return error.code, detail


def start_login(email: str, challenge_path: Path, bundle_key: str) -> None:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("POVO_LOGIN_EMAIL is not a valid email address.")
    device_id = f"{uuid.uuid4()}{PACKAGE_SUFFIX}"
    action_status, action = _post(
        "/api/v3/user-service/v4/jp/ja/mobile/users/login/action",
        {"email": email},
        device_id,
    )
    if action_status != 200:
        raise RuntimeError(f"Login action failed with HTTP {action_status}.")
    actions = _find(action, "actions")
    action_text = json.dumps(actions, ensure_ascii=True) if actions is not None else ""
    if "EMAIL_OTP" not in action_text:
        raise RuntimeError("Account did not offer the EMAIL_OTP login action.")
    otp_status, otp = _post(
        "/api/v3/user-service/v4/jp/ja/mobile/otp",
        {
            "device_id": device_id,
            "email": email,
            "otp_duration": 15,
            "auth_mode": "ENHANCED_EMAIL_OTP",
            "request_type": "LOGIN_EMAIL_OTP",
        },
        device_id,
    )
    auth_id = _find(otp, "auth_id")
    if otp_status != 200 or not isinstance(auth_id, str):
        raise RuntimeError(f"OTP send failed with HTTP {otp_status}.")
    encrypt_challenge(
        {
            "email": email,
            "device_id": device_id,
            "auth_id": auth_id,
            "created_at": int(time.time()),
        },
        challenge_path,
        bundle_key,
    )
    print("Email OTP sent and encrypted challenge saved; no secret was printed.")


def finish_login(
    challenge_path: Path,
    data_dir: Path,
    session_path: Path,
    otp_code: str,
    promo_code: str,
    next_due_at: str | None,
    bundle_key: str,
) -> None:
    if not re.fullmatch(r"\d{6}", otp_code):
        raise ValueError("POVO_LOGIN_OTP must contain exactly six digits.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", promo_code):
        raise ValueError("POVO_PROMO_CODE has an unsupported format.")
    challenge = decrypt_challenge(challenge_path, bundle_key)
    if int(time.time()) - int(challenge["created_at"]) > 15 * 60:
        raise ValueError("The encrypted login challenge has expired; run login start again.")
    device_id = str(challenge["device_id"])
    status, response = _post(
        "/user-service/v5/public/jp/ja/mobile/users/auth",
        {
            "email_auth": {
                "auth_id": challenge["auth_id"],
                "otp_code": otp_code,
                "device_id": device_id,
            },
            "device": {
                "device_id": device_id,
                "device_type": "Mobile",
                "app_type": "ecosystem",
            },
        },
        device_id,
    )
    token = _find(response, "auth_token")
    if status != 200 or not isinstance(token, str):
        code = _find(response, "code")
        raise RuntimeError(f"Email OTP login failed with HTTP {status}, code {code!r}.")

    due = None
    if next_due_at:
        due = datetime.fromisoformat(next_due_at)
        if due.tzinfo is None:
            due = due.replace(tzinfo=JST)
        due = due.astimezone(JST)
        if due <= datetime.now(JST):
            raise ValueError("next_due_at must be in the future.")

    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    credentials = Credentials.create(
        data_dir / "credentials.xml",
        data_dir / "device.xml",
        device_id,
        token,
    )
    profile_status, profile = PovoClient(credentials).profile_probe()
    if profile_status != 200 or not profile.get("authenticated"):
        raise RuntimeError(
            f"Login token failed the read-only profile check with HTTP {profile_status}."
        )
    (data_dir / "code").write_text(promo_code + "\n", encoding="utf-8")
    state = {
        "version": 2,
        "phase": "scheduled" if due else "ready_for_first_redemption",
        "paused": False,
        "next_due_at": (
            due.replace(second=0, microsecond=0).isoformat(timespec="minutes")
            if due
            else None
        ),
        "last_success_at": None,
        "last_attempt_at": None,
        "last_result": "github_email_login",
        "last_message": (
            "Authorized email OTP login stored; awaiting the explicitly confirmed "
            "first redemption."
            if due is None
            else "Authorized email OTP login stored with an imported schedule."
        ),
    }
    (data_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in ("credentials.xml", "device.xml", "code", "state.json"):
        (data_dir / name).chmod(0o600)
    pack(data_dir, session_path, bundle_key)
    print("Email OTP login succeeded and encrypted session bundle was created.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--output", type=Path, required=True)
    finish = subparsers.add_parser("finish")
    finish.add_argument("--challenge", type=Path, required=True)
    finish.add_argument("--data-dir", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument(
        "--next-due-at",
        help="optional recovery override; normal email login schedules after first success",
    )
    args = parser.parse_args()
    bundle_key = _secret("POVO_BUNDLE_KEY")
    if args.command == "start":
        start_login(_secret("POVO_LOGIN_EMAIL"), args.output, bundle_key)
    else:
        finish_login(
            args.challenge,
            args.data_dir,
            args.output,
            _secret("POVO_LOGIN_OTP"),
            _secret("POVO_PROMO_CODE"),
            args.next_due_at,
            bundle_key,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
