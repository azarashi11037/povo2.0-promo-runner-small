#!/usr/bin/env python3
"""Encrypt or decrypt the minimal state needed by a GitHub Actions runner."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


VERSION = 1
AAD = b"povo-promo-automation/session-bundle/v1"
FILES = ("credentials.xml", "device.xml", "code", "state.json")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 20:
        raise ValueError("POVO_BUNDLE_KEY must contain at least 20 characters.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _read_payload(data_dir: Path) -> bytes:
    files: dict[str, str] = {}
    for name in FILES:
        path = data_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Required session file is missing: {name}")
        files[name] = _b64encode(path.read_bytes())
    payload = {"version": VERSION, "files": files}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pack(data_dir: Path, output: Path, passphrase: str) -> None:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext = AESGCM(_derive_key(passphrase, salt)).encrypt(
        nonce, _read_payload(data_dir), AAD
    )
    envelope = {
        "version": VERSION,
        "cipher": "AES-256-GCM",
        "kdf": {"name": "scrypt", "n": 32768, "r": 8, "p": 1},
        "salt": _b64encode(salt),
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)


def unpack(bundle: Path, data_dir: Path, passphrase: str) -> None:
    envelope = json.loads(bundle.read_text(encoding="utf-8"))
    if envelope.get("version") != VERSION:
        raise ValueError("Unsupported session bundle version.")
    if envelope.get("cipher") != "AES-256-GCM":
        raise ValueError("Unsupported session bundle cipher.")
    expected_kdf = {"name": "scrypt", "n": 32768, "r": 8, "p": 1}
    if envelope.get("kdf") != expected_kdf:
        raise ValueError("Unsupported session bundle KDF parameters.")
    salt = _b64decode(envelope["salt"])
    nonce = _b64decode(envelope["nonce"])
    if len(salt) != 16 or len(nonce) != 12:
        raise ValueError("Invalid session bundle salt or nonce length.")
    try:
        plaintext = AESGCM(_derive_key(passphrase, salt)).decrypt(
            nonce, _b64decode(envelope["ciphertext"]), AAD
        )
    except InvalidTag as error:
        raise ValueError("Session bundle authentication failed.") from error
    payload = json.loads(plaintext)
    if payload.get("version") != VERSION or set(payload.get("files", {})) != set(FILES):
        raise ValueError("Session bundle contents are incomplete or unexpected.")
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    for name in FILES:
        path = data_dir / name
        path.write_bytes(_b64decode(payload["files"][name]))
        path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    pack_parser = subparsers.add_parser("pack")
    pack_parser.add_argument("--data-dir", type=Path, required=True)
    pack_parser.add_argument("--output", type=Path, required=True)
    unpack_parser = subparsers.add_parser("unpack")
    unpack_parser.add_argument("--input", type=Path, required=True)
    unpack_parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    passphrase = os.environ.get("POVO_BUNDLE_KEY", "")
    if not passphrase:
        parser.error("POVO_BUNDLE_KEY is required")
    if args.command == "pack":
        pack(args.data_dir, args.output, passphrase)
    else:
        unpack(args.input, args.data_dir, passphrase)
    print(f"Session bundle {args.command} completed without printing secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
