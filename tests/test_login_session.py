from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from povo_api import Credentials
from tools.login_session import decrypt_challenge, encrypt_challenge, finish_login
from tools.session_bundle import unpack


def _jwt() -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"external_id": "user-1", "exp": int(time.time()) + 3600}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.signature"


class LoginSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.key = "correct horse battery staple"

    def tearDown(self):
        self.temporary.cleanup()

    def test_challenge_round_trip_is_encrypted(self):
        challenge = {
            "email": "person@example.com",
            "device_id": "device-secret",
            "auth_id": "auth-secret",
            "created_at": int(time.time()),
        }
        path = self.root / "login.enc"
        encrypt_challenge(challenge, path, self.key)
        encoded = path.read_bytes()
        for secret in challenge.values():
            if isinstance(secret, str):
                self.assertNotIn(secret.encode(), encoded)
        self.assertEqual(decrypt_challenge(path, self.key), challenge)

    @patch("tools.login_session._post")
    def test_finish_creates_usable_encrypted_session(self, mocked_post):
        token = _jwt()
        mocked_post.return_value = (
            200,
            {"success": True, "result": {"auth_token": token, "first_login": False}},
        )
        challenge_path = self.root / "login.enc"
        encrypt_challenge(
            {
                "email": "person@example.com",
                "device_id": "device-secret",
                "auth_id": "auth-secret",
                "created_at": int(time.time()),
            },
            challenge_path,
            self.key,
        )
        private = self.root / "private"
        session = self.root / "session.enc"
        with patch(
            "tools.login_session.PovoClient.profile_probe",
            return_value=(200, {"authenticated": True}),
        ):
            finish_login(
                challenge_path,
                private,
                session,
                "123456",
                "promo-code",
                None,
                self.key,
            )
        encoded = session.read_bytes()
        self.assertNotIn(b"person@example.com", encoded)
        self.assertNotIn(b"auth-secret", encoded)
        self.assertNotIn(b"123456", encoded)
        restored = self.root / "restored"
        unpack(session, restored, self.key)
        credentials = Credentials.load(
            restored / "credentials.xml", restored / "device.xml"
        )
        self.assertEqual(credentials.token, token)
        state = json.loads((restored / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["next_due_at"])
        self.assertFalse(state["paused"])
        self.assertEqual(state["phase"], "ready_for_first_redemption")

    @patch("tools.login_session._post")
    def test_finish_accepts_an_optional_recovery_schedule(self, mocked_post):
        mocked_post.return_value = (
            200,
            {"success": True, "result": {"auth_token": _jwt()}},
        )
        challenge_path = self.root / "scheduled-login.enc"
        encrypt_challenge(
            {
                "email": "person@example.com",
                "device_id": "device-secret",
                "auth_id": "auth-secret",
                "created_at": int(time.time()),
            },
            challenge_path,
            self.key,
        )
        private = self.root / "scheduled-private"
        session = self.root / "scheduled-session.enc"
        with patch(
            "tools.login_session.PovoClient.profile_probe",
            return_value=(200, {"authenticated": True}),
        ):
            finish_login(
                challenge_path,
                private,
                session,
                "123456",
                "promo-code",
                "2099-09-06T16:17:00+09:00",
                self.key,
            )
        restored = self.root / "scheduled-restored"
        unpack(session, restored, self.key)
        state = json.loads((restored / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["next_due_at"], "2099-09-06T16:17+09:00")
        self.assertEqual(state["phase"], "scheduled")


if __name__ == "__main__":
    unittest.main()
