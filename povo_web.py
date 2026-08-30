#!/usr/bin/env python3
"""LAN-only Chinese dashboard for the povo2.0 automation worker."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from povo_api import Credentials, PovoClient


JST = ZoneInfo("Asia/Tokyo")
DATA_DIR = Path(os.environ.get("POVO_DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "state.json"
RUNTIME_FILE = DATA_DIR / "runtime.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
AUTH_FILE = DATA_DIR / "web_auth.json"
STATE_LOCK_FILE = DATA_DIR / "state.lock"
SESSION_LOCK_FILE = DATA_DIR / "session.lock"
CREDENTIALS_FILE = DATA_DIR / "credentials.xml"
DEVICE_FILE = DATA_DIR / "device.xml"
PORT = int(os.environ.get("POVO_WEB_PORT", "8080"))


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>povo2.0 自动续费</title>
<style>
:root{color-scheme:dark;--bg:#0b0f14;--card:#141a22;--line:#283241;--text:#e7edf5;--muted:#91a0b3;--ok:#35c66b;--bad:#ff5d67;--accent:#5e9cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif}.wrap{max-width:980px;margin:0 auto;padding:28px 18px 50px}h1{font-size:25px;margin:0 0 4px}.sub{color:var(--muted);margin-bottom:22px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}.label{color:var(--muted);font-size:13px}.value{font-size:20px;font-weight:650;margin-top:6px;word-break:break-word}.ok{color:var(--ok)}.bad{color:var(--bad)}.section{margin-top:14px}.actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:12px}button{border:1px solid var(--line);background:#202937;color:var(--text);border-radius:9px;padding:9px 13px;cursor:pointer}button.primary{background:var(--accent);color:#07101d;border-color:transparent;font-weight:700}button.danger{border-color:#743942;color:#ffafb5}button:disabled{opacity:.5;cursor:wait}input{background:#0e141c;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px;width:260px}.history{max-height:300px;overflow:auto;margin-top:10px}.event{border-top:1px solid var(--line);padding:9px 0}.event:first-child{border-top:0}.event small{color:var(--muted)}#message{min-height:23px;margin-top:10px;color:var(--muted)}code{color:#b9d0f6}</style>
</head>
<body><main class="wrap">
<h1>povo2.0 自动续费</h1><div class="sub">直接 API 模式 · 页面不会显示令牌、邮箱或兑换码</div>
<div class="grid">
  <div class="card"><div class="label">API 认证</div><div id="auth" class="value">读取中…</div></div>
  <div class="card"><div class="label">Worker</div><div id="worker" class="value">读取中…</div></div>
  <div class="card"><div class="label">下次兑换</div><div id="next" class="value">读取中…</div></div>
  <div class="card"><div class="label">调度状态</div><div id="phase" class="value">读取中…</div></div>
</div>
<section class="card section">
  <div class="label">最近状态</div><div id="last" class="value" style="font-size:16px">—</div>
  <div class="actions">
    <button onclick="action('probe')">认证检查</button>
    <button onclick="action('refresh')">刷新令牌</button>
    <button id="pauseBtn" onclick="togglePause()">暂停调度</button>
  </div><div id="message"></div>
</section>
<section class="card section">
  <div class="label">修改下次执行时间（日本时间）</div>
  <div class="actions"><input id="schedule" type="datetime-local"><button class="primary" onclick="setSchedule()">保存时间</button></div>
</section>
<section class="card section"><div class="label">最近执行记录</div><div id="history" class="history">读取中…</div></section>
</main>
<script>
let snapshot={};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fmtEpoch(v){if(!v)return '未知';return new Date(v*1000).toLocaleString('zh-CN',{timeZone:'Asia/Tokyo',hour12:false})+' JST'}
function fmtIso(v){if(!v)return '未设置';return new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Tokyo',hour12:false})+' JST'}
async function api(path,opt={}){opt.headers={...(opt.headers||{}),'X-Povo-Action':'dashboard'};const r=await fetch(path,opt);const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j}
async function load(){try{snapshot=await api('/api/status');auth.textContent=snapshot.runtime.auth_ok?'正常':'异常';auth.className='value '+(snapshot.runtime.auth_ok?'ok':'bad');worker.textContent=snapshot.worker_healthy?'运行中':'无心跳';worker.className='value '+(snapshot.worker_healthy?'ok':'bad');next.textContent=fmtIso(snapshot.state.next_due_at);phase.textContent=snapshot.state.paused?'已暂停':(snapshot.state.phase||'未知');phase.className='value '+(snapshot.state.paused?'bad':'ok');last.textContent=(snapshot.state.last_result||'—')+' · '+(snapshot.state.last_message||'');pauseBtn.textContent=snapshot.state.paused?'恢复调度':'暂停调度';schedule.value=snapshot.schedule_input||'';history.innerHTML=(snapshot.history||[]).map(x=>`<div class="event"><b>${esc(x.event)}</b><br><small>${esc(x.time)}</small></div>`).join('')||'暂无记录';}catch(e){message.textContent='读取失败：'+e.message}}
async function action(name){message.textContent='处理中…';try{const j=await api('/api/'+name,{method:'POST'});message.textContent=j.message||'完成';await load()}catch(e){message.textContent='失败：'+e.message}}
async function togglePause(){await action(snapshot.state.paused?'resume':'pause')}
async function setSchedule(){if(!schedule.value)return; if(!confirm('确认修改下次执行时间？此操作不会立即兑换。'))return;message.textContent='保存中…';try{const j=await api('/api/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:schedule.value})});message.textContent=j.message;await load()}catch(e){message.textContent='失败：'+e.message}}
load();setInterval(load,15000);
</script></body></html>"""


@contextmanager
def file_lock(path: Path):
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def append_history(event: str) -> None:
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "time": datetime.now(JST).isoformat(timespec="seconds"),
                    "event": event,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def load_auth() -> dict:
    return read_json(AUTH_FILE, {})


def valid_login(header: str | None) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:]).decode("utf-8")
        username, password = raw.split(":", 1)
        auth = load_auth()
        salt = bytes.fromhex(auth["salt"])
        expected = bytes.fromhex(auth["password_hash"])
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, int(auth["iterations"])
        )
        return hmac.compare_digest(username, auth["username"]) and hmac.compare_digest(
            actual, expected
        )
    except Exception:
        return False


def history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    output = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-20:]:
        try:
            item = json.loads(line)
            output.append({"time": item.get("time"), "event": item.get("event")})
        except json.JSONDecodeError:
            pass
    return list(reversed(output))


def schedule_input(value: str | None) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST).strftime("%Y-%m-%dT%H:%M")


def status_payload() -> dict:
    state = read_json(STATE_FILE, {})
    runtime = read_json(RUNTIME_FILE, {})
    heartbeat = runtime.get("worker_heartbeat_at")
    healthy = False
    if heartbeat:
        try:
            healthy = (datetime.now(JST) - datetime.fromisoformat(heartbeat)).total_seconds() < 60
        except ValueError:
            pass
    return {
        "state": state,
        "runtime": runtime,
        "worker_healthy": healthy,
        "schedule_input": schedule_input(state.get("next_due_at")),
        "history": history(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "povo2.0-dashboard/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def headers_common(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
        )

    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.headers_common("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> bool:
        if valid_login(self.headers.get("Authorization")):
            return True
        body = b"Authentication required"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="povo2.0 automation"')
        self.headers_common("text/plain; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            self.send_json(200, {"ok": True})
            return
        if not self.require_auth():
            return
        if path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.headers_common("text/html; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            self.send_json(200, status_payload())
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        if not self.require_auth():
            return
        if self.headers.get("X-Povo-Action") != "dashboard":
            self.send_json(403, {"error": "missing_action_header"})
            return
        path = urlparse(self.path).path
        try:
            if path in {"/api/pause", "/api/resume"}:
                with file_lock(STATE_LOCK_FILE):
                    state = read_json(STATE_FILE, {})
                    state["paused"] = path.endswith("pause")
                    state["updated_at"] = datetime.now(JST).isoformat(timespec="seconds")
                    atomic_json(STATE_FILE, state)
                append_history("scheduler_paused" if state["paused"] else "scheduler_resumed")
                self.send_json(200, {"message": "调度已暂停" if state["paused"] else "调度已恢复"})
                return
            if path == "/api/schedule":
                length = min(int(self.headers.get("Content-Length", "0")), 2048)
                value = json.loads(self.rfile.read(length)).get("value")
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=JST)
                parsed = parsed.astimezone(JST)
                if parsed <= datetime.now(JST):
                    raise ValueError("time_must_be_future")
                with file_lock(STATE_LOCK_FILE):
                    state = read_json(STATE_FILE, {})
                    state["next_due_at"] = parsed.replace(
                        second=0, microsecond=0
                    ).isoformat(timespec="minutes")
                    state["updated_at"] = datetime.now(JST).isoformat(timespec="seconds")
                    atomic_json(STATE_FILE, state)
                append_history("schedule_changed")
                self.send_json(200, {"message": "下次执行时间已保存"})
                return
            if path in {"/api/probe", "/api/refresh"}:
                with file_lock(SESSION_LOCK_FILE):
                    credentials = Credentials.load(CREDENTIALS_FILE, DEVICE_FILE)
                    api = PovoClient(credentials)
                    if path.endswith("probe"):
                        status, result = api.profile_probe()
                        ok = status == 200 and result.get("authenticated")
                    else:
                        status, result = api.refresh(persist=True)
                        ok = status == 200 and result.get("valid_auth_token")
                append_history("manual_auth_probe" if path.endswith("probe") else "manual_session_refresh")
                self.send_json(
                    200 if ok else 502,
                    {"message": "认证正常" if ok else "认证失败", "http_status": status},
                )
                return
            self.send_json(404, {"error": "not_found"})
        except Exception as error:
            self.send_json(400, {"error": type(error).__name__})


def main() -> int:
    if not AUTH_FILE.exists():
        raise SystemExit("web_auth.json is missing")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"povo2.0 dashboard listening on {PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
