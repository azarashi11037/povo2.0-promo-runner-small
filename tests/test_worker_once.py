from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import povo_worker


class RunOnceTests(unittest.TestCase):
    def test_due_time_uses_minute_precision(self):
        value = datetime.fromisoformat("2026-08-31T00:41:47+09:00")
        self.assertEqual(
            povo_worker.iso_minute(value + povo_worker.REDEMPTION_INTERVAL),
            "2026-09-07T00:42+09:00",
        )

    def test_not_due_refreshes_without_redeeming(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "refresh_session", return_value=True
        ) as refresh, patch.object(
            povo_worker, "load_state", return_value={"paused": False}
        ), patch.object(
            povo_worker, "due_now", return_value=False
        ), patch.object(
            povo_worker, "redeem_once"
        ) as redeem:
            self.assertEqual(povo_worker.run_once(), 0)
            refresh.assert_called_once_with(force=True)
            redeem.assert_not_called()

    def test_manual_redemption_ignores_due_time(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "refresh_session", return_value=True
        ), patch.object(
            povo_worker, "load_state", return_value={"paused": False}
        ), patch.object(
            povo_worker, "due_now", return_value=False
        ), patch.object(
            povo_worker, "redeem_once", return_value=0
        ) as redeem:
            self.assertEqual(povo_worker.run_once(redeem_now=True), 0)
            redeem.assert_called_once_with()

    def test_due_calls_redeem_exactly_once(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "refresh_session", return_value=True
        ), patch.object(
            povo_worker, "load_state", return_value={"paused": False}
        ), patch.object(
            povo_worker, "due_now", return_value=True
        ), patch.object(
            povo_worker, "redeem_once", return_value=3
        ) as redeem:
            self.assertEqual(povo_worker.run_once(), 3)
            redeem.assert_called_once_with()

    def test_scheduled_early_start_waits_then_redeems(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "refresh_session", return_value=True
        ), patch.object(
            povo_worker, "load_state", return_value={"paused": False}
        ), patch.object(
            povo_worker, "due_now", return_value=False
        ), patch.object(
            povo_worker, "seconds_until_due", return_value=600
        ), patch.object(
            povo_worker, "wait_for_due", return_value=True
        ) as wait, patch.object(
            povo_worker, "redeem_once", return_value=0
        ) as redeem:
            self.assertEqual(povo_worker.run_once(wait_until_due=True), 0)
            wait.assert_called_once_with({"paused": False}, 900)
            redeem.assert_called_once_with()

    def test_scheduled_run_does_not_wait_when_due_is_far_away(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "load_state", return_value={"paused": False}
        ), patch.object(
            povo_worker, "due_now", return_value=False
        ), patch.object(
            povo_worker, "seconds_until_due", return_value=3600
        ), patch.object(
            povo_worker, "refresh_session"
        ) as refresh, patch.object(
            povo_worker, "wait_for_due"
        ) as wait, patch.object(
            povo_worker, "redeem_once"
        ) as redeem:
            self.assertEqual(
                povo_worker.run_once(wait_until_due=True, max_wait_seconds=900), 0
            )
            refresh.assert_not_called()
            wait.assert_not_called()
            redeem.assert_not_called()

    def test_refresh_failure_never_redeems(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            povo_worker, "DATA_DIR", Path(temporary)
        ), patch.object(povo_worker, "recover_interrupted_submission"), patch.object(
            povo_worker, "append_history"
        ), patch.object(
            povo_worker, "refresh_session", return_value=False
        ), patch.object(
            povo_worker, "redeem_once"
        ) as redeem:
            self.assertEqual(povo_worker.run_once(), 2)
            redeem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
