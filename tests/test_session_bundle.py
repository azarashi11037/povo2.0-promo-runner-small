from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.session_bundle import FILES, pack, unpack


class SessionBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.values = {
            "credentials.xml": b"<map><string name='session_key'>very-secret-token</string></map>",
            "device.xml": b"<map><string name='device_uuid'>secret-device</string></map>",
            "code": b"secret-code\n",
            "state.json": b'{"version":2,"phase":"scheduled"}\n',
        }
        for name, value in self.values.items():
            (self.source / name).write_bytes(value)
        self.bundle = self.root / "session.enc"

    def tearDown(self):
        self.temporary.cleanup()

    def test_round_trip_and_plaintext_absence(self):
        pack(self.source, self.bundle, "correct horse battery staple")
        encoded = self.bundle.read_bytes()
        for value in self.values.values():
            self.assertNotIn(value.strip(), encoded)
        destination = self.root / "destination"
        unpack(self.bundle, destination, "correct horse battery staple")
        for name in FILES:
            self.assertEqual((destination / name).read_bytes(), self.values[name])
            self.assertEqual((destination / name).stat().st_mode & 0o777, 0o600)

    def test_wrong_key_fails_closed(self):
        pack(self.source, self.bundle, "correct horse battery staple")
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            unpack(self.bundle, self.root / "bad", "this is definitely the wrong key")


if __name__ == "__main__":
    unittest.main()
