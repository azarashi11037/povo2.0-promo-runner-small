from __future__ import annotations

import unittest

from povo_api import _safe_api_diagnostic


class SafeDiagnosticTests(unittest.TestCase):
    def test_keeps_errors_and_drops_secrets(self):
        response = {
            "success": False,
            "title": "request error",
            "token": "secret-token",
            "result": {
                "codeValid": False,
                "code": "secret-promo-code",
                "external_id": "secret-user-id",
                "details": {"message": "MULTIPLE_ADDONS_FOUND"},
            },
        }
        safe = _safe_api_diagnostic(response)
        self.assertEqual(
            safe,
            {
                "success": False,
                "title": "request error",
                "result": {
                    "codeValid": False,
                    "details": {"message": "MULTIPLE_ADDONS_FOUND"},
                },
            },
        )
        self.assertNotIn("secret", repr(safe))


if __name__ == "__main__":
    unittest.main()
