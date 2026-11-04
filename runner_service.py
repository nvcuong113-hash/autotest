from __future__ import annotations

import base64
import hmac
import json
import os
import resource
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from core.application_profile import load_application_profile
from core.browser_runner import inspect_page, run_suite
from core.db import init_db, mark_interrupted_runs

MAX_BODY_BYTES = 2 * 1024 * 1024
RUNNER_TOKEN = os.getenv("RUNNER_API_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
_browser_job_lock = threading.Lock()


class RunnerHandler(BaseHTTPRequestHandler):
    server_version = "AutoTestRunner/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Never write URLs, headers, request bodies or submitted credentials to logs.
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/health":
            peak_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
            self._send(200, {
                "ok": True,
                "service": "autotest-browser-runner",
                "database_configured": bool(DATABASE_URL),
                "token_configured": bool(RUNNER_TOKEN),
                "peak_process_rss_mb": peak_rss_mb,
                "browser_job_active": _browser_job_lock.locked(),
            })
            return
        self._send(404, {"error": "Not found"})

    def _read_payload(self) -> dict[str, Any] | None:
        supplied = self.headers.get("X-Runner-Token", "")
        if not RUNNER_TOKEN or not hmac.compare_digest(supplied, RUNNER_TOKEN):
            self._send(401, {"error": "Runner authorization failed."})
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "Invalid Content-Length."})
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(413, {"error": "Request body is empty or exceeds the 2 MB limit."})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"error": "Invalid JSON request."})
            return None
        if not isinstance(payload, dict):
            self._send(400, {"error": "JSON body must be an object."})
            return None
        return payload

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in {"/inspect", "/run"}:
            self._send(404, {"error": "Not found"})
            return
        payload = self._read_payload()
        if payload is None:
            return
        if not _browser_job_lock.acquire(blocking=False):
            self._send(429, {"error": "Browser Runner đang xử lý một tác vụ khác. Thử lại sau."})
            return
        try:
            peak_before = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
            print(f"[RUNNER] {path} started; process_peak_rss_mb={peak_before}", flush=True)
            if path == "/inspect":
                result = inspect_page(
                    target_url=str(payload.get("target_url") or ""),
                    base_url=str(payload.get("base_url") or ""),
                    headless=True,
                    username=str(payload.get("username") or ""),
                    password=str(payload.get("password") or ""),
                    authenticate=bool(payload.get("authenticate")),
                )
                screenshot_path = str(result.pop("screenshot_path", "") or "")
                if screenshot_path and Path(screenshot_path).is_file():
                    try:
                        result["screenshot_base64"] = base64.b64encode(
                            Path(screenshot_path).read_bytes()
                        ).decode("ascii")
                    finally:
                        try:
                            Path(screenshot_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                peak_after = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
                print(f"[RUNNER] inspect completed; process_peak_rss_mb={peak_after}", flush=True)
                self._send(200, result)
                return

            cases = payload.get("cases")
            if not isinstance(cases, list) or not cases:
                self._send(400, {"error": "Cần truyền danh sách Test Case."})
                return
            if len(cases) > 5:
                self._send(400, {"error": "Mỗi lượt chỉ chạy tối đa 5 Test Case."})
                return
            if not DATABASE_URL:
                self._send(503, {"error": "Browser Runner chưa được cấu hình DATABASE_URL."})
                return
            application_profile = load_application_profile(
                str(payload.get("application_profile_id") or "oap-meta")
            )
            result = run_suite(
                project_id=int(payload["project_id"]),
                base_url=str(payload["base_url"]),
                cases=cases,
                username=str(payload.get("username") or ""),
                password=str(payload.get("password") or ""),
                headless=True,
                application_profile=application_profile,
            )
            # Worker-local screenshot paths are not accessible to the frontend.
            for item in result.get("results", []):
                item["screenshot_path"] = ""
            peak_after = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
            print(f"[RUNNER] run completed; process_peak_rss_mb={peak_after}", flush=True)
            self._send(200, result)
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            # Never return exception strings; they may contain request details.
            print(f"[RUNNER] {path} failed: {type(exc).__name__}", flush=True)
            self._send(500, {"error": f"Browser Runner failed ({type(exc).__name__})."})
        finally:
            _browser_job_lock.release()


class SingleRunnerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    if DATABASE_URL:
        init_db()
        mark_interrupted_runs()
    SingleRunnerHTTPServer(("0.0.0.0", port), RunnerHandler).serve_forever()
