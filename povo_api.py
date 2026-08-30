#!/usr/bin/env python3
"""Minimal povo2.0 API client reconstructed from the Android application.

Secrets remain encrypted at rest in the copied Android SharedPreferences files.
The default command is read-only inspection; redemption requires an explicit flag.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import ssl
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


BASE_URL = os.environ.get("POVO_BASE_URL", "https://app.povo.jp")
APP_VERSION = os.environ.get("POVO_APP_VERSION", "1.70.0-JP")
USER_AGENT = os.environ.get(
    "POVO_USER_AGENT",
    f"selfcare/{APP_VERSION} Android/14 sdk_gphone64_x86_64/en_US",
)
REFRESH_PATH = "/api/v3/user-service/v4/jp/ja/mobile/users/token"
PROFILE_PATH = "/api/v3/user-service/v4/jp/ja/mobile/users?include_telco=true"
REDEEM_PATH = "/v4/jp/ja/mobile/promotions/code/set"

SAFE_DIAGNOSTIC_FIELDS = {
    "success",
    "codeValid",
    "title",
    "subtitle",
    "message",
    "errorCode",
    "status",
    "reason",
}
SAFE_DIAGNOSTIC_CONTAINERS = {"result", "error", "errors", "detail", "details"}


def _safe_api_diagnostic(value: Any, depth: int = 0) -> Any:
    """Keep useful API errors while excluding tokens, identifiers, and promo codes."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if key not in SAFE_DIAGNOSTIC_FIELDS | SAFE_DIAGNOSTIC_CONTAINERS:
                continue
            cleaned = _safe_api_diagnostic(item, depth + 1)
            if cleaned not in (None, {}, []):
                safe[key] = cleaned
        return safe
    if isinstance(value, list):
        return [
            cleaned
            for item in value[:10]
            if (cleaned := _safe_api_diagnostic(item, depth + 1))
            not in (None, {}, [])
        ]
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return None


def _b64decode(value: str) -> bytes:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(padded, altchars=b"-_")


def _decrypt(password: str, blob: bytes) -> bytes:
    cursor = 0
    salt_length = struct.unpack(">I", blob[cursor : cursor + 4])[0]
    cursor += 4
    if salt_length != 8:
        raise ValueError(f"unexpected salt length: {salt_length}")
    salt = blob[cursor : cursor + salt_length]
    cursor += salt_length
    iv_length = struct.unpack(">I", blob[cursor : cursor + 4])[0]
    cursor += 4
    if iv_length != 12:
        raise ValueError(f"unexpected IV length: {iv_length}")
    iv = blob[cursor : cursor + iv_length]
    cursor += iv_length
    key = PBKDF2HMAC(
        algorithm=hashes.SHA1(), length=32, salt=salt, iterations=10_000
    ).derive(password.encode())
    return AESGCM(key).decrypt(iv, blob[cursor:], None)


def _encrypt(password: str, plaintext: bytes) -> bytes:
    salt = os.urandom(8)
    iv = os.urandom(12)
    key = PBKDF2HMAC(
        algorithm=hashes.SHA1(), length=32, salt=salt, iterations=10_000
    ).derive(password.encode())
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    return (
        struct.pack(">I", len(salt))
        + salt
        + struct.pack(">I", len(iv))
        + iv
        + ciphertext
    )


def _xml_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in ET.parse(path).getroot():
        value = item.text if item.tag == "string" else item.attrib.get("value")
        values[item.attrib["name"]] = value or ""
    return values


def _jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("session is not a three-part JWT")
    return json.loads(_b64decode(parts[1]))


def _stored_session(device_id: str, token: str, migration_enabled: bool) -> str:
    """Encode a JWT exactly as povo2.0's encrypted SharedPreferences session value."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("session is not a three-part JWT")
    _jwt_claims(token)
    password = hashlib.sha256(device_id.encode()).hexdigest()
    encrypted_payload = base64.b64encode(
        _encrypt(password, parts[1].encode())
    ).decode()
    inner = f"{parts[0]}.{encrypted_payload}.{parts[2]}"
    return (
        base64.b64encode(_encrypt(password, inner.encode())).decode()
        if migration_enabled
        else inner
    )


@dataclass
class Credentials:
    credentials_path: Path
    device_path: Path
    device_id: str
    password: str
    migration_enabled: bool
    token: str

    @classmethod
    def load(cls, credentials_path: Path, device_path: Path) -> "Credentials":
        values = _xml_values(credentials_path)
        device_id = _xml_values(device_path)["device_uuid"]
        password = hashlib.sha256(device_id.encode()).hexdigest()
        migration_enabled = values.get("session_key_migration_status") == "true"
        stored = values["session_key"]
        outer = (
            _decrypt(password, base64.b64decode(stored)).decode()
            if migration_enabled
            else stored
        )
        parts = outer.split(".")
        if len(parts) != 3:
            raise ValueError("stored session is not a three-part token")
        if parts[1].startswith("ey"):
            token = outer
        else:
            payload = _decrypt(password, _b64decode(parts[1])).decode()
            token = f"{parts[0]}.{payload}.{parts[2]}"
        _jwt_claims(token)
        return cls(
            credentials_path,
            device_path,
            device_id,
            password,
            migration_enabled,
            token,
        )

    @classmethod
    def create(
        cls,
        credentials_path: Path,
        device_path: Path,
        device_id: str,
        token: str,
        migration_enabled: bool = True,
    ) -> "Credentials":
        """Create the minimal private XML files needed by this client."""
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        device_path.parent.mkdir(parents=True, exist_ok=True)

        credentials_root = ET.Element("map")
        session = ET.SubElement(credentials_root, "string", {"name": "session_key"})
        session.text = _stored_session(device_id, token, migration_enabled)
        ET.SubElement(
            credentials_root,
            "boolean",
            {
                "name": "session_key_migration_status",
                "value": "true" if migration_enabled else "false",
            },
        )
        device_root = ET.Element("map")
        device = ET.SubElement(device_root, "string", {"name": "device_uuid"})
        device.text = device_id

        for path, root in (
            (credentials_path, credentials_root),
            (device_path, device_root),
        ):
            tree = ET.ElementTree(root)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
            )
            try:
                os.close(fd)
                tree.write(temporary, encoding="utf-8", xml_declaration=True)
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return cls.load(credentials_path, device_path)

    def persist_token(self, token: str) -> None:
        stored = _stored_session(self.device_id, token, self.migration_enabled)

        tree = ET.parse(self.credentials_path)
        root = tree.getroot()
        target = next(
            item
            for item in root
            if item.tag == "string" and item.attrib.get("name") == "session_key"
        )
        target.text = stored
        fd, temp_name = tempfile.mkstemp(
            prefix=".credentials-", suffix=".xml", dir=self.credentials_path.parent
        )
        try:
            os.close(fd)
            tree.write(temp_name, encoding="utf-8", xml_declaration=True)
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.credentials_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.token = token

    @property
    def claims(self) -> dict[str, Any]:
        return _jwt_claims(self.token)


class PovoClient:
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials

    def _headers(self) -> dict[str, str]:
        claims = self.credentials.claims
        return {
            "Accept": "application/json",
            "Accept-Language": "ja-JP",
            "User-Agent": USER_AGENT,
            "X-AUTH": self.credentials.token,
            "X-USER-ID": str(claims.get("external_id", "")),
            "X-App-Platform": "Android",
            "X-App-Version": APP_VERSION,
            "X-Deviceid": self.credentials.device_id,
        }

    def _request(
        self, method: str, path: str, body: bytes | None = None
    ) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            BASE_URL + path,
            data=body,
            headers=self._headers(),
            method=method,
        )
        if body is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        verify_paths = ssl.get_default_verify_paths()
        fallback_ca = Path("/etc/ssl/cert.pem")
        ssl_context = (
            ssl.create_default_context(cafile=str(fallback_ca))
            if verify_paths.cafile is None and fallback_ca.exists()
            else ssl.create_default_context()
        )
        try:
            with urllib.request.urlopen(
                request, timeout=30, context=ssl_context
            ) as response:
                payload = response.read()
                return response.status, json.loads(payload) if payload else {}
        except urllib.error.HTTPError as error:
            payload = error.read()
            try:
                detail = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                detail = {"body_length": len(payload)}
            return error.code, detail

    def refresh(self, persist: bool) -> tuple[int, dict[str, Any]]:
        status, response = self._request("GET", REFRESH_PATH)
        result = response.get("result", response) if isinstance(response, dict) else {}
        token = result.get("auth_token") if isinstance(result, dict) else None
        if status == 200 and isinstance(token, str):
            _jwt_claims(token)
            if persist:
                self.credentials.persist_token(token)
            return status, {"valid_auth_token": True, "persisted": persist}
        return status, {
            "valid_auth_token": False,
            "success": response.get("success") if isinstance(response, dict) else None,
            "result_keys": sorted(result) if isinstance(result, dict) else [],
        }

    def profile_probe(self) -> tuple[int, dict[str, Any]]:
        """Verify the session with a non-mutating endpoint without printing PII."""
        status, response = self._request("GET", PROFILE_PATH)
        result = response.get("result", response) if isinstance(response, dict) else {}
        return status, {
            "authenticated": status == 200,
            "success": response.get("success") if isinstance(response, dict) else None,
            "result_type": type(result).__name__,
            "result_keys": sorted(result) if isinstance(result, dict) else [],
            "secrets_printed": False,
        }

    def redeem(self, code: str) -> tuple[int, dict[str, Any]]:
        body = urllib.parse.urlencode({"code": code}).encode()
        status, response = self._request("POST", REDEEM_PATH, body)
        result = response.get("result", response) if isinstance(response, dict) else {}
        normalized = dict(result) if isinstance(result, dict) else {}
        normalized["_safe_diagnostic"] = _safe_api_diagnostic(response)
        return status, normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, default=Path("credentials.xml"))
    parser.add_argument(
        "--device", type=Path, default=Path("device.xml")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect")
    subparsers.add_parser("profile-probe")
    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--persist", action="store_true")
    redeem = subparsers.add_parser("redeem")
    redeem.add_argument("code")
    redeem.add_argument("--confirm-redeem", action="store_true")
    args = parser.parse_args()

    credentials = Credentials.load(args.credentials, args.device)
    client = PovoClient(credentials)
    if args.command == "inspect":
        claims = credentials.claims
        expiry = int(claims.get("expiry_time", claims.get("exp", 0)) or 0)
        print(
            json.dumps(
                {
                    "endpoint": BASE_URL,
                    "authenticated": bool(credentials.token),
                    "has_external_id": bool(claims.get("external_id")),
                    "expires_at_epoch": expiry,
                    "expired": expiry <= int(time.time()),
                    "secrets_printed": False,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "refresh":
        status, result = client.refresh(args.persist)
        print(json.dumps({"http_status": status, **result}, indent=2))
        return 0 if status == 200 and result["valid_auth_token"] else 1
    if args.command == "profile-probe":
        status, result = client.profile_probe()
        print(json.dumps({"http_status": status, **result}, indent=2))
        return 0 if status == 200 and result["authenticated"] else 1
    if args.command == "redeem":
        if os.environ.get("POVO_ENABLE_REDEMPTION") != "1":
            parser.error("redemption is disabled; set POVO_ENABLE_REDEMPTION=1")
        if not args.confirm_redeem:
            parser.error("redemption requires --confirm-redeem")
        status, result = client.redeem(args.code)
        safe = {
            key: result.get(key)
            for key in ("codeValid", "title", "subtitle", "message")
            if key in result
        }
        safe["diagnostic"] = result.get("_safe_diagnostic", {})
        print(json.dumps({"http_status": status, "response": safe}, ensure_ascii=False))
        return 0 if status == 200 else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
