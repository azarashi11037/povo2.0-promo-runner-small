#!/usr/bin/env python3
"""Persistent povo2.0 session keeper and single-submit redemption scheduler."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from povo_api import Credentials, PovoClient


JST = ZoneInfo("Asia/Tokyo")
DATA_DIR = Path(os.environ.get("POVO_DATA_DIR", "/data"))
CREDENTIALS_FILE = DATA_DIR / "credentials.xml"
DEVICE_FILE = DATA_DIR / "device.xml"
CODE_FILE = DATA_DIR / "code"
STATE_FILE = DATA_DIR / "state.json"
RUNTIME_FILE = DATA_DIR / "runtime.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
STATE_LOCK_FILE = DATA_DIR / "state.lock"
SESSION_LOCK_FILE = DATA_DIR / "session.lock"
SUBMIT_LOCK_FILE = DATA_DIR / "submit.lock"

REDEMPTION_INTERVAL = timedelta(days=7, minutes=1)
LOOP_SECONDS = 15
NORMAL_REFRESH_SECONDS = 300
AUTH_RETRY_SECONDS = 60
MAX_HISTORY_BYTES = 1_000_000
DEFAULT_EARLY_WAIT_SECONDS = 15 * 60

running = True


def now_jst() -> datetime:
    return datetime.now(JST)


def iso(value: datetime | None = None) -> str:
    return (value or now_jst()).astimezone(JST).isoformat(timespec="seconds")


def iso_minute(value: datetime) -> str:
    return value.astimezone(JST).replace(second=0, microsecond=0).isoformat(
        timespec="minutes"
    )


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    temporary.replace(path)


@contextmanager
def file_lock(path: Path, *, blocking: bool = True):
    with path.open("a+", encoding="utf-8") as handle:
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), operation)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def load_state() -> dict:
    state = load_json(
        STATE_FILE,
        {
            "version": 2,
            "phase": "scheduled",
            "paused": True,
            "next_due_at": None,
            "last_success_at": None,
            "last_attempt_at": None,
            "last_result": "not_configured",
            "last_message": "A next due time must be configured.",
        },
    )
    state.setdefault("paused", False)
    state["version"] = max(int(state.get("version", 1)), 2)
    return state


def save_state(state: dict) -> None:
    state["updated_at"] = iso()
    with file_lock(STATE_LOCK_FILE):
        atomic_json(STATE_FILE, state)


def normalize_due_precision(state: dict) -> dict:
    due = parse_dt(state.get("next_due_at"))
    if due is None:
        return state
    normalized = iso_minute(due)
    if state.get("next_due_at") != normalized:
        state["next_due_at"] = normalized
        save_state(state)
    return state


def load_runtime() -> dict:
    return load_json(RUNTIME_FILE, {})


def save_runtime(changes: dict) -> dict:
    runtime = load_runtime()
    runtime.update(changes)
    atomic_json(RUNTIME_FILE, runtime)
    return runtime


def append_history(event: str, **details) -> None:
    entry = {"time": iso(), "event": event, **details}
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    HISTORY_FILE.chmod(0o600)
    if HISTORY_FILE.stat().st_size > MAX_HISTORY_BYTES:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-300:]
        HISTORY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def log(message: str) -> None:
    print(f"{iso()} {message}", flush=True)


def safe_client() -> PovoClient:
    return PovoClient(Credentials.load(CREDENTIALS_FILE, DEVICE_FILE))


def current_expiry() -> int:
    credentials = Credentials.load(CREDENTIALS_FILE, DEVICE_FILE)
    return int(credentials.claims.get("exp", credentials.claims.get("expiry_time", 0)) or 0)


def refresh_session(*, force: bool = False) -> bool:
    runtime = load_runtime()
    now_epoch = int(time.time())
    last_attempt = int(runtime.get("last_refresh_attempt_epoch", 0) or 0)
    try:
        expiry = current_expiry()
    except Exception as error:
        save_runtime(
            {
                "auth_ok": False,
                "last_refresh_at": iso(),
                "last_refresh_error": type(error).__name__,
                "worker_heartbeat_at": iso(),
            }
        )
        return False

    if not force and expiry > now_epoch and now_epoch - last_attempt < NORMAL_REFRESH_SECONDS:
        save_runtime(
            {
                "auth_ok": True,
                "token_expires_at_epoch": expiry,
                "worker_heartbeat_at": iso(),
            }
        )
        return True

    with file_lock(SESSION_LOCK_FILE):
        api = safe_client()
        status, result = api.refresh(persist=True)
        valid = status == 200 and bool(result.get("valid_auth_token"))
        expiry = current_expiry() if valid else expiry
        save_runtime(
            {
                "auth_ok": valid,
                "last_refresh_at": iso(),
                "last_refresh_attempt_epoch": now_epoch,
                "last_refresh_http": status,
                "last_refresh_error": None if valid else "refresh_rejected",
                "token_expires_at_epoch": expiry,
                "worker_heartbeat_at": iso(),
            }
        )
    if valid:
        append_history("session_refresh", http_status=status, token_expiry=expiry)
        return True
    append_history("session_refresh_failed", http_status=status)
    return False


def read_code() -> str:
    code = CODE_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", code):
        raise ValueError("The protected promo code has an unsupported format.")
    return code


def redeem_once() -> int:
    if os.environ.get("POVO_ENABLE_REDEMPTION") != "1":
        log("Redemption is disabled by configuration; skipped.")
        append_history("submission_disabled")
        return 4
    with file_lock(SUBMIT_LOCK_FILE, blocking=False) as acquired:
        if not acquired:
            log("Another redemption process holds the lock; skipped.")
            return 0

        state = load_state()
        if state.get("paused"):
            return 0
        if state.get("phase") in {"submitting", "unknown"}:
            log("A previous submission is uncertain; automatic retry is blocked.")
            return 3

        with file_lock(SESSION_LOCK_FILE):
            api = safe_client()
            refresh_status, refresh = api.refresh(persist=True)
            if refresh_status != 200 or not refresh.get("valid_auth_token"):
                state["last_result"] = "pre_submit_auth_failure"
                state["last_message"] = "Authentication failed before submission."
                save_state(state)
                append_history("pre_submit_auth_failure", http_status=refresh_status)
                return 2

            code = read_code()
            state["phase"] = "submitting"
            state["last_attempt_at"] = iso()
            state["last_result"] = "submitting_api"
            state["last_message"] = "One API redemption request is being submitted."
            save_state(state)
            append_history("submission_started")

            try:
                status, result = api.redeem(code)
            except Exception as error:
                state = load_state()
                state["phase"] = "unknown"
                state["last_result"] = "unknown_after_api_submission"
                state["last_message"] = (
                    "Submission outcome is unknown; automatic retry is blocked. "
                    f"Error type: {type(error).__name__}."
                )
                save_state(state)
                append_history("submission_unknown", error_type=type(error).__name__)
                return 3

        code_valid = result.get("codeValid") if isinstance(result, dict) else None
        diagnostic = (
            result.get("_safe_diagnostic", {}) if isinstance(result, dict) else {}
        )
        state = load_state()
        if status == 200 and code_valid is True:
            completed = now_jst()
            state["phase"] = "scheduled"
            state["last_success_at"] = iso(completed)
            state["next_due_at"] = iso_minute(completed + REDEMPTION_INTERVAL)
            state["submit_retry_count"] = 0
            state["last_result"] = "success_api"
            state["last_message"] = "Redemption succeeded through the official API."
            save_state(state)
            append_history("submission_success", http_status=status)
            log(f"Redemption succeeded. Next redemption: {state['next_due_at']}")
            return 0

        state["phase"] = "unknown"
        state["last_result"] = "rejected_or_unconfirmed_api"
        state["last_message"] = (
            f"Response was not confirmed as success (HTTP {status}, "
            f"codeValid={code_valid!r}); automatic retry is blocked."
        )
        state["last_api_diagnostic"] = diagnostic
        save_state(state)
        append_history(
            "submission_unconfirmed",
            http_status=status,
            code_valid=code_valid,
            diagnostic=diagnostic,
        )
        return 3


def due_now(state: dict) -> bool:
    due = parse_dt(state.get("next_due_at"))
    return bool(due and now_jst() >= due)


def seconds_until_due(state: dict) -> float | None:
    due = parse_dt(state.get("next_due_at"))
    return None if due is None else (due - now_jst()).total_seconds()


def wait_for_due(state: dict, max_wait_seconds: int) -> bool:
    """Wait only when a scheduled runner started shortly before the due minute."""
    due = parse_dt(state.get("next_due_at"))
    if due is None:
        return False
    remaining = (due - now_jst()).total_seconds()
    if remaining <= 0:
        return True
    if remaining > max_wait_seconds:
        return False
    log(
        f"Runner started {int(remaining)} seconds before the due minute; "
        "waiting with the refreshed session ready."
    )
    while remaining > 0:
        time.sleep(min(remaining, 5))
        remaining = (due - now_jst()).total_seconds()
    log("The due minute has been reached; starting the single-submit path.")
    return True


def handle_signal(_signum, _frame) -> None:
    global running
    running = False


def recover_interrupted_submission() -> None:
    state = load_state()
    if state.get("phase") == "submitting":
        state["phase"] = "unknown"
        state["last_result"] = "unknown_after_restart"
        state["last_message"] = "Worker restarted during an API submission."
        save_state(state)


def run_once(
    *,
    redeem_now: bool = False,
    wait_until_due: bool = False,
    max_wait_seconds: int = DEFAULT_EARLY_WAIT_SECONDS,
) -> int:
    """Refresh the session and execute at most one authorized redemption."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    recover_interrupted_submission()
    append_history("github_run_started")
    state = normalize_due_precision(load_state())
    is_due = due_now(state)
    if wait_until_due and not is_due:
        remaining = seconds_until_due(state)
        if remaining is None or remaining > max_wait_seconds:
            log("Redemption is outside the scheduled look-ahead window; skipped.")
            return 0
    if not refresh_session(force=True):
        log("Session refresh failed; no redemption was attempted.")
        return 2
    if state.get("paused"):
        log("Scheduler is paused; session refresh completed.")
        return 0
    if not redeem_now and not is_due:
        if not wait_until_due or not wait_for_due(state, max_wait_seconds):
            log("Redemption is not due; session refresh completed.")
            return 0
    if redeem_now:
        log("A manually confirmed immediate redemption was requested.")
    return redeem_once()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="refresh once and execute at most one due run"
    )
    parser.add_argument(
        "--redeem-now",
        action="store_true",
        help="immediately redeem once; requires POVO_CONFIRM_REDEEM_NOW=1",
    )
    parser.add_argument(
        "--wait-until-due",
        action="store_true",
        help="wait when a scheduled runner starts shortly before next_due_at",
    )
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=DEFAULT_EARLY_WAIT_SECONDS,
        help="maximum early-start wait; default: 900 seconds",
    )
    args = parser.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.max_wait_seconds < 0:
        parser.error("--max-wait-seconds must not be negative")
    if args.redeem_now and os.environ.get("POVO_CONFIRM_REDEEM_NOW") != "1":
        parser.error("--redeem-now requires POVO_CONFIRM_REDEEM_NOW=1")
    if args.once or args.redeem_now:
        return run_once(
            redeem_now=args.redeem_now,
            wait_until_due=args.wait_until_due,
            max_wait_seconds=args.max_wait_seconds,
        )
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    recover_interrupted_submission()

    append_history("worker_started")
    log("povo2.0 worker started.")
    next_auth_retry = 0
    while running:
        try:
            auth_ok = refresh_session()
            if not auth_ok:
                next_auth_retry = int(time.time()) + AUTH_RETRY_SECONDS
            state = normalize_due_precision(load_state())
            save_runtime(
                {
                    "worker_heartbeat_at": iso(),
                    "worker_running": True,
                    "scheduler_paused": bool(state.get("paused")),
                    "next_due_at": state.get("next_due_at"),
                }
            )
            if due_now(state) and not state.get("paused"):
                result = redeem_once()
                if result == 2:
                    time.sleep(AUTH_RETRY_SECONDS)
        except Exception as error:
            save_runtime(
                {
                    "worker_heartbeat_at": iso(),
                    "worker_error": type(error).__name__,
                }
            )
            append_history("worker_error", error_type=type(error).__name__)
            log(f"Worker loop error type: {type(error).__name__}")
        for _ in range(LOOP_SECONDS):
            if not running:
                break
            time.sleep(1)

    save_runtime({"worker_running": False, "worker_stopped_at": iso()})
    append_history("worker_stopped")
    log("povo2.0 worker stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
