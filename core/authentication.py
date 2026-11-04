from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin, urlparse

from core.action_registry import resolve_semantic_locator


class AuthenticationError(RuntimeError):
    pass


def ensure_authenticated(
    context: Any,
    profile: dict[str, Any],
    base_url: str,
    username: str = "",
    password: str = "",
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Authenticate once per Browser Context using the selected Application Profile."""
    auth = profile.get("authentication") or {}
    if not auth or str(auth.get("strategy") or "none") == "none":
        return {"authenticated": True, "status": "NOT_REQUIRED"}
    if str(auth.get("strategy")) != "web_form":
        raise AuthenticationError("Application Profile dùng authentication strategy chưa được hỗ trợ.")
    probe = auth.get("session_probe") or {}
    probe_path = str(probe.get("path") or "")
    expected_status = int(probe.get("success_status") or 200)
    if not probe_path.startswith("/") or probe_path.startswith("//"):
        raise AuthenticationError("Application Profile thiếu session_probe path hợp lệ.")
    base = urlparse(base_url)
    probe_url = urljoin(base_url.rstrip("/") + "/", probe_path.lstrip("/"))
    probe_parts = urlparse(probe_url)
    if probe_parts.scheme != base.scheme or probe_parts.netloc != base.netloc:
        raise AuthenticationError("Session probe phải cùng origin với Base URL.")

    def session_is_valid() -> bool:
        try:
            response = context.request.get(probe_url, timeout=5000)
            return int(response.status) == expected_status
        except Exception:
            return False

    if session_is_valid():
        return {"authenticated": True, "status": "ALREADY_AUTHENTICATED"}
    if not username.strip() or not password:
        raise AuthenticationError("Cần tài khoản và mật khẩu kiểm thử để đăng nhập.")
    login_path = str(auth.get("login_path") or "")
    if not login_path.startswith("/") or login_path.startswith("//"):
        raise AuthenticationError("Application Profile thiếu login_path nội bộ hợp lệ.")
    login_url = urljoin(base_url.rstrip("/") + "/", login_path.lstrip("/"))
    login_parts = urlparse(login_url)
    if login_parts.scheme != base.scheme or login_parts.netloc != base.netloc:
        raise AuthenticationError("Login route phải cùng origin với Base URL.")

    page = context.new_page()
    workspace_events: list[dict[str, Any]] = []
    readiness = auth.get("post_login_readiness") or {}
    required_api = readiness.get("required_api") or {}
    required_path = str(required_api.get("path_contains") or "")
    required_method = str(required_api.get("method") or "POST").upper()
    required_status = int(required_api.get("status") or 200)

    def on_response(response: Any) -> None:
        try:
            response_path = urlparse(response.url).path
            request_method = str(response.request.method).upper()
            if required_path and required_path in response_path and request_method == required_method:
                workspace_events.append({
                    "path": response_path,
                    "method": request_method,
                    "status": int(response.status),
                })
                if len(workspace_events) > 10:
                    del workspace_events[:-10]
        except Exception:
            pass

    try:
        page.on("response", on_response)
        # Authentication pages can load fonts/images that are not needed to fill
        # credentials; apply the same low-memory rule as the inspection page.
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "font", "media"}
            else route.continue_(),
        )
        page.goto(login_url, wait_until="domcontentloaded", timeout=20000)
        username_target = str(auth.get("username_target") or "")
        password_target = str(auth.get("password_target") or "")
        submit_target = str(auth.get("submit_target") or "")
        if not username_target or not password_target or not submit_target:
            raise AuthenticationError("Application Profile chưa ánh xạ đủ các target đăng nhập.")
        resolve_semantic_locator(page, profile, username_target).fill(username.strip(), timeout=8000)
        resolve_semantic_locator(page, profile, password_target).fill(password, timeout=8000)
        resolve_semantic_locator(page, profile, submit_target).click(timeout=8000)

        deadline = time.monotonic() + max(5, min(timeout_seconds, 45))
        while time.monotonic() < deadline:
            session_ok = session_is_valid()
            required_api_ok = (
                not required_path
                or any(event["status"] == required_status for event in workspace_events)
            )
            # Keep the auth page alive until profile-defined initialization completes.
            # The caller will navigate to its own target page using this same context.
            if session_ok and required_api_ok:
                return {
                    "authenticated": True,
                    "status": "AUTHENTICATED",
                    "login_url": login_url,
                    "post_login_api": workspace_events[-1] if workspace_events else None,
                }
            try:
                page.wait_for_timeout(500)
            except Exception:
                break
        if session_is_valid() and required_path and not any(
            event["status"] == required_status for event in workspace_events
        ):
            raise AuthenticationError(
                "API session_probe đã trả thành công nhưng chưa hoàn tất bước post-login bắt buộc "
                f"({required_method} {required_path} HTTP {required_status})."
            )
        raise AuthenticationError(
            "Đã gửi form đăng nhập nhưng chưa hoàn tất xác thực/điều hướng sau đăng nhập. "
            "Kiểm tra tài khoản, MFA hoặc cấu hình post_login_readiness của Application Profile."
        )
    finally:
        if not page.is_closed():
            page.close()
