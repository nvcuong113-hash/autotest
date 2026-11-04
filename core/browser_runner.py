from __future__ import annotations

import gc
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from core.db import create_run, finish_run, save_result
from core.test_generator import validate_steps_json

ARTIFACT_DIR = Path("artifacts")

# Keep Chromium's process count and background services low on small cloud instances.
CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-extensions",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-breakpad",
    "--disable-component-update",
    "--disable-features=Translate,BackForwardCache,MediaRouter",
    "--renderer-process-limit=1",
    "--no-zygote",
    "--metrics-recording-only",
    "--no-first-run",
]


def _launch_low_memory_browser(playwright: Any, headless: bool = True) -> Any:
    return playwright.chromium.launch(headless=headless, args=CHROMIUM_ARGS)


class ManualStepRequired(Exception):
    pass


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    for key, replacement in variables.items():
        value = value.replace("${" + key + "}", replacement)
    return value


def _resolve_url(value: str, base_url: str) -> str:
    target = value.replace("${BASE_URL}", base_url.rstrip("/"))
    parsed, base = urlparse(target), urlparse(base_url)
    if not parsed.scheme:
        target = urljoin(base_url.rstrip("/") + "/", target.lstrip("/"))
        parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported.")
    if parsed.netloc.lower() != base.netloc.lower():
        raise ValueError("Navigation outside the configured base host is blocked.")
    return target



def _evaluate_with_navigation_retry(page: Any, script: str, attempts: int = 6) -> Any:
    """Retry a read-only DOM snapshot when the application redirects during inspection."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return page.evaluate(script)
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            transient = any(token in message for token in (
                "execution context was destroyed",
                "most likely because of a navigation",
                "cannot find context with specified id",
                "context was destroyed",
                "navigation interrupted",
            ))
            if not transient or page.is_closed():
                raise
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3500)
            except Exception:
                pass
            try:
                page.wait_for_timeout(350 + attempt * 250)
            except Exception:
                if page.is_closed():
                    raise
    if last_error:
        raise last_error
    raise RuntimeError("Không thể đọc DOM sau nhiều lần thử.")


def _http_status(item: dict[str, Any]) -> int:
    raw = str(item.get("status", "")).strip()
    digits = "".join(character for character in raw if character.isdigit())
    return int(digits[:3]) if len(digits) >= 3 else 0


def _safe_auth_text(value: Any) -> str:
    """Return short diagnostic text without email addresses or bearer/token strings."""
    text = str(value or "")
    text = re.sub(r"(?i)bearer\\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"(?i)(access[_-]?token|refresh[_-]?token|password)\\s*[:=]\\s*[^,;\\s]+", r"\\1=[REDACTED]", text)
    return text[:240]


def _auth_login_response_summary(status: int, payload: Any, content_type: str = "",
                                 has_set_cookie: bool = False) -> dict[str, Any]:
    """Summarize a login response without exposing credentials, cookies or tokens."""
    summary: dict[str, Any] = {
        "http_status": int(status),
        "content_type": _safe_auth_text(content_type),
        "has_set_cookie": bool(has_set_cookie),
        "payload_type": type(payload).__name__,
    }
    if isinstance(payload, dict):
        summary["response_keys"] = sorted(str(key)[:60] for key in payload.keys())[:40]
        for key in ("success", "ok", "authenticated"):
            if isinstance(payload.get(key), bool):
                summary[key] = payload[key]
        for key in ("code", "error_code", "status"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                summary[key] = _safe_auth_text(value)
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)):
                summary["message"] = _safe_auth_text(value)
                break
        data = payload.get("data")
        if isinstance(data, dict):
            summary["data_keys"] = sorted(str(key)[:60] for key in data.keys())[:40]
            summary["token_fields_present"] = {
                key: key in data
                for key in ("token", "access_token", "accessToken", "refresh_token", "refreshToken")
            }
    elif isinstance(payload, list):
        summary["item_count"] = len(payload)
    elif isinstance(payload, str):
        summary["message"] = _safe_auth_text(payload)
    return summary


def _classify_auth_state(final_url: str, api_responses: list[dict[str, Any]], body_text: str,
                         login_attempted: bool = False) -> dict[str, Any]:
    """Only /auth/me can confirm a session; POST /auth/login HTTP 200 is not proof."""
    path = urlparse(final_url).path.rstrip("/").lower()
    login_path = path.endswith("/login") or path.endswith("/signin") or path.endswith("/sign-in")
    auth_me_events = [
        item for item in api_responses
        if urlparse(str(item.get("url", ""))).path.rstrip("/").lower().endswith("/auth/me")
    ]
    login_events = [
        item for item in api_responses
        if urlparse(str(item.get("url", ""))).path.rstrip("/").lower().endswith("/auth/login")
        and str(item.get("method", "")).upper() == "POST"
    ]
    latest_me_status = _http_status(auth_me_events[-1]) if auth_me_events else 0
    auth_api_401 = latest_me_status == 401
    auth_api_success = latest_me_status == 200
    latest_login = login_events[-1] if login_events else None
    login_status = _http_status(latest_login) if latest_login else 0

    body_lower = body_text.lower()
    pending = "checking authentication" in body_lower or "đang kiểm tra xác thực" in body_lower
    mfa_required = any(token in body_lower for token in (
        "mã xác thực", "verification code", "one-time password", "two-factor", "2fa", "otp"
    ))
    authenticated = auth_api_success and not login_path
    required = not authenticated and (login_path or auth_api_401 or mfa_required)

    if authenticated:
        state = "AUTHENTICATED"
    elif mfa_required:
        state = "MFA_REQUIRED"
    elif login_attempted and login_path and login_status >= 400:
        state = "LOGIN_REJECTED"
    elif login_attempted and (login_path or auth_api_401):
        state = "LOGIN_NOT_CONFIRMED"
    elif login_path or auth_api_401:
        state = "LOGIN_REQUIRED"
    elif pending:
        state = "AUTH_PENDING"
    else:
        state = "AUTH_STATE_UNKNOWN"

    return {
        "authentication_required": required,
        "authentication_pending": pending and not authenticated,
        "authentication_state": state,
        "auth_api_401": auth_api_401,
        "auth_api_success": auth_api_success,
        "auth_me_latest_status": latest_me_status or None,
        "login_api_latest_status": login_status or None,
        "redirected_to_login": login_path,
        "authenticated": authenticated,
        "mfa_required": mfa_required,
    }


def _navigate_to_login_page(page: Any, base_url: str, timeout_seconds: int = 12) -> dict[str, Any]:
    """Open the first-party OAP Meta login route before locating credentials fields."""
    login_url = urljoin(base_url.rstrip("/") + "/", "login")
    current_path = urlparse(page.url).path.rstrip("/").lower()
    navigated = False
    if current_path not in {"/login", "/signin", "/sign-in"}:
        try:
            page.goto(login_url, wait_until="commit", timeout=20000)
            navigated = True
        except Exception as exc:
            return {"navigated": navigated, "result": "LOGIN_ROUTE_NAVIGATION_FAILED",
                    "error_type": type(exc).__name__}
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            password_count = page.locator('input[type="password"]').count()
            username_count = page.locator(
                'input[type="email"], input[autocomplete="username"], input[type="text"]'
            ).count()
            if password_count > 0 and username_count > 0:
                return {"navigated": navigated, "result": "LOGIN_PAGE_READY"}
        except Exception:
            pass
        try:
            page.wait_for_timeout(400)
        except Exception:
            break
    return {"navigated": navigated, "result": "LOGIN_FORM_NOT_READY"}


def _submit_username_password_login(page: Any, username: str, password: str) -> dict[str, Any]:
    """Submit the visible username/password form without logging or returning credentials."""
    if not username or not password:
        return {"attempted": False, "result": "MISSING_CREDENTIALS"}

    def first_visible(locators: list[Any]) -> Any | None:
        for locator in locators:
            try:
                for index in range(min(locator.count(), 5)):
                    candidate = locator.nth(index)
                    if candidate.is_visible() and candidate.is_enabled():
                        return candidate
            except Exception:
                continue
        return None

    username_field = first_visible([
        page.get_by_label(re.compile(r"Tên đăng nhập|Username|Email", re.I)),
        page.locator('input[autocomplete="username"]'),
        page.locator('input[type="email"]'),
        page.locator('input[name*="username" i], input[name*="email" i]'),
        page.locator('input[placeholder*="Tên đăng nhập" i]'),
        page.locator('input[type="text"]'),
    ])
    password_field = first_visible([
        page.get_by_label(re.compile(r"Mật khẩu|Password", re.I)),
        page.locator('input[autocomplete="current-password"]'),
        page.locator('input[type="password"]'),
    ])
    login_button = first_visible([
        page.get_by_role("button", name=re.compile(r"^\s*Đăng nhập\s*$", re.I)),
        page.locator('button:has-text("Đăng nhập")'),
        page.locator('button[type="submit"], input[type="submit"]'),
    ])
    if username_field is None or password_field is None or login_button is None:
        return {"attempted": False, "result": "LOGIN_FORM_NOT_FOUND"}
    try:
        username_field.fill(username, timeout=8000)
        password_field.fill(password, timeout=8000)
        login_button.click(timeout=8000)
        return {"attempted": True, "result": "SUBMITTED"}
    except Exception as exc:
        return {"attempted": True, "result": "SUBMISSION_ERROR", "error_type": type(exc).__name__}

def inspect_page(target_url: str, base_url: str, headless: bool = True,
                 username: str = "", password: str = "", authenticate: bool = False) -> dict[str, Any]:
    """Read-only page inspection with SPA/authentication polling and network diagnostics."""
    if not base_url.strip():
        raise ValueError("Cần cấu hình Base URL trước khi kiểm tra.")
    url = _resolve_url(target_url.strip() or base_url.strip(), base_url.strip())
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValueError("Không đưa thông tin đăng nhập vào URL.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(ARTIFACT_DIR / f"page-inspection-{time.time_ns()}.png")
    document_responses: list[dict[str, Any]] = []
    api_responses: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    navigation_errors: list[str] = []
    from playwright.sync_api import sync_playwright

    snapshot_script = r'''() => {
        const clean = value => (value || '').trim().replace(/\\s+/g, ' ');
        const cssEscape = value => (window.CSS && CSS.escape) ? CSS.escape(String(value)) : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
        const selectorFor = (el, tag) => {
            if (el.id) return '#' + cssEscape(el.id);
            const name = el.getAttribute('name');
            if (name) return tag + '[name="' + String(name).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"') + '"]';
            const placeholder = el.getAttribute('placeholder');
            if (placeholder) return tag + '[placeholder="' + String(placeholder).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"') + '"]';
            const aria = el.getAttribute('aria-label');
            if (aria) return tag + '[aria-label="' + String(aria).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"') + '"]';
            return '';
        };
        const inputs = Array.from(document.querySelectorAll('input, textarea, select')).map((el, i) => {
            const tag = el.tagName.toLowerCase();
            const labels = el.labels ? Array.from(el.labels).map(x => clean(x.innerText || x.textContent)).filter(Boolean) : [];
            return {index:i, tag, type:clean(el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : tag)).toLowerCase(),
                id:el.id || '', name:el.getAttribute('name') || '', placeholder:el.getAttribute('placeholder') || '',
                aria_label:el.getAttribute('aria-label') || '', labels, required:!!el.required, disabled:!!el.disabled,
                suggested_selector:selectorFor(el, tag)};
        });
        const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]')).map((el, i) => {
            const tag = el.tagName.toLowerCase();
            return {index:i, tag, text:clean(el.innerText || el.value || el.textContent).slice(0,160),
                aria_label:el.getAttribute('aria-label') || '', title:el.getAttribute('title') || '',
                type:el.getAttribute('type') || '', disabled:!!el.disabled, suggested_selector:selectorFor(el, tag)};
        });
        const headings = Array.from(document.querySelectorAll('h1, h2, h3')).slice(0,80)
            .map(el => ({level:el.tagName.toLowerCase(), text:clean(el.innerText || el.textContent).slice(0,200)})).filter(x => x.text);
        const forms = Array.from(document.querySelectorAll('form')).map((el, i) => ({index:i,
            method:(el.getAttribute('method') || 'get').toUpperCase(), action:el.action || '', id:el.id || '', name:el.getAttribute('name') || ''}));
        const links = Array.from(document.querySelectorAll('a[href]')).slice(0,100).map((el, i) => ({
            index:i, text:clean(el.innerText || el.textContent).slice(0,120), href:el.href}));
        return {title:document.title || '', final_url:location.href, ready_state:document.readyState,
            headings, forms, inputs, buttons, links,
            body_text_preview:clean(document.body ? document.body.innerText : '').slice(0,2500)};
    }'''

    def safe_url(raw_url: str) -> str:
        parsed_url = urlparse(raw_url)
        return parsed_url._replace(query="", fragment="").geturl()

    with sync_playwright() as playwright:
        browser = _launch_low_memory_browser(playwright, headless)
        try:
            context = browser.new_context(viewport={"width":1024,"height":768}, device_scale_factor=1, service_workers="block")
            page = context.new_page()
            page.set_default_timeout(8000)
            # Static media does not affect DOM/selector discovery and can consume
            # considerable memory while remote fonts/images are loading.
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_(),
            )

            def on_response(response: Any) -> None:
                try:
                    request = response.request
                    entry = {"url":safe_url(response.url), "status":response.status,
                             "resource_type":request.resource_type, "method":request.method}
                    response_path = urlparse(response.url).path.rstrip("/").lower()
                    if response_path.endswith("/api/v1/auth/login") and request.method.upper() == "POST":
                        payload: Any = None
                        try:
                            payload = response.json()
                        except Exception:
                            payload = None
                        headers = response.headers
                        entry["login_response_summary"] = _auth_login_response_summary(
                            response.status, payload,
                            headers.get("content-type", ""),
                            bool(headers.get("set-cookie")),
                        )
                    if request.resource_type == "document":
                        document_responses.append(entry)
                    elif request.resource_type in {"xhr", "fetch"}:
                        api_responses.append(entry)
                except Exception:
                    pass

            def on_request_failed(request: Any) -> None:
                try:
                    failed_requests.append({"url":safe_url(request.url), "method":request.method,
                                            "resource_type":request.resource_type,
                                            "failure":str(request.failure or "Unknown failure")[:300]})
                except Exception:
                    pass

            def on_console(message: Any) -> None:
                try:
                    if message.type == "error":
                        console_errors.append(str(message.text)[:500])
                except Exception:
                    pass

            def on_page_error(error: Any) -> None:
                page_errors.append(str(error)[:500])

            page.on("response", on_response)
            page.on("requestfailed", on_request_failed)
            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            try:
                page.goto(url, wait_until="commit", timeout=25000)
            except Exception as exc:
                navigation_errors.append(f"Điều hướng ban đầu: {type(exc).__name__}: {exc}")

            # Do not wait for networkidle or DOMContentLoaded: enterprise SPAs and
            # authentication polling can keep navigation events pending indefinitely.
            snapshot: dict[str, Any] = {"title":"", "final_url":page.url, "ready_state":"unknown",
                "headings":[], "forms":[], "inputs":[], "buttons":[], "links":[], "body_text_preview":""}
            deadline = time.monotonic() + 22
            last_body = ""
            stable_count = 0
            while time.monotonic() < deadline:
                try:
                    current = _evaluate_with_navigation_retry(page, snapshot_script, attempts=3)
                    snapshot = current
                    body = str(current.get("body_text_preview", ""))
                    pending_auth = "checking authentication" in body.lower() or "đang kiểm tra xác thực" in body.lower()
                    if body and body == last_body and not pending_auth:
                        stable_count += 1
                    else:
                        stable_count = 0
                    last_body = body
                    if body and not pending_auth and stable_count >= 2:
                        break
                except Exception as exc:
                    navigation_errors.append(f"Đọc DOM trong khi trang tải: {type(exc).__name__}: {exc}")
                try:
                    page.wait_for_timeout(600)
                except Exception:
                    break

            final_body = str(snapshot.get("body_text_preview", ""))
            final_url = snapshot.get("final_url") or (page.url if not page.is_closed() else "")
            auth_state = _classify_auth_state(final_url, api_responses, final_body)
            login_diagnostic = {"attempted": False, "result": "NOT_REQUESTED"}
            if authenticate and auth_state["authentication_required"]:
                login_route = _navigate_to_login_page(page, base_url)
                login_diagnostic = {
                    "attempted": False,
                    "result": login_route["result"],
                    "login_page_navigated": login_route.get("navigated", False),
                }
                if login_route["result"] == "LOGIN_PAGE_READY":
                    login_diagnostic = _submit_username_password_login(page, username, password)
                    login_diagnostic["login_page_navigated"] = login_route.get("navigated", False)
                if login_diagnostic["result"] == "SUBMITTED":
                    # Wait briefly for the login endpoint, then force a fresh protected-page
                    # navigation so the app must re-check its newly issued session.
                    page.wait_for_timeout(1200)
                    latest_login_event = next((
                        item for item in reversed(api_responses)
                        if urlparse(str(item.get("url", ""))).path.rstrip("/").lower().endswith("/api/v1/auth/login")
                        and str(item.get("method", "")).upper() == "POST"
                    ), None)
                    if latest_login_event:
                        login_diagnostic["login_api_status"] = _http_status(latest_login_event)
                        login_diagnostic["login_api_response"] = latest_login_event.get("login_response_summary", {})
                    else:
                        login_diagnostic["login_api_status"] = None
                    try:
                        page.goto(url, wait_until="commit", timeout=20000)
                    except Exception as exc:
                        navigation_errors.append(f"Kiểm tra phiên sau đăng nhập: {type(exc).__name__}")
                    auth_deadline = time.monotonic() + 18
                    while time.monotonic() < auth_deadline:
                        try:
                            snapshot = _evaluate_with_navigation_retry(page, snapshot_script, attempts=2)
                            final_body = str(snapshot.get("body_text_preview", ""))
                            final_url = snapshot.get("final_url") or page.url
                            auth_state = _classify_auth_state(
                                final_url, api_responses, final_body, login_attempted=True
                            )
                            if auth_state["authenticated"] or auth_state["mfa_required"]:
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(600)
                    if auth_state["authenticated"]:
                        login_diagnostic["result"] = "AUTHENTICATED"
                        try:
                            page.goto(url, wait_until="commit", timeout=20000)
                            auth_deadline = time.monotonic() + 12
                            while time.monotonic() < auth_deadline:
                                try:
                                    snapshot = _evaluate_with_navigation_retry(page, snapshot_script, attempts=2)
                                    final_body = str(snapshot.get("body_text_preview", ""))
                                    final_url = snapshot.get("final_url") or page.url
                                    auth_state = _classify_auth_state(final_url, api_responses, final_body)
                                    if final_body and not auth_state["authentication_pending"]:
                                        break
                                except Exception:
                                    pass
                                page.wait_for_timeout(500)
                        except Exception as exc:
                            navigation_errors.append(f"Không mở lại được màn hình sau đăng nhập: {type(exc).__name__}")
                    elif auth_state["mfa_required"]:
                        login_diagnostic["result"] = "MFA_REQUIRED"
                    else:
                        login_diagnostic["result"] = "LOGIN_NOT_CONFIRMED"
                    try:
                        login_diagnostic["storage_metadata"] = page.evaluate(
                            """() => ({
                                local_storage_keys: Object.keys(localStorage),
                                session_storage_keys: Object.keys(sessionStorage)
                            })"""
                        )
                        cookie_list = context.cookies([base_url])
                        login_diagnostic["cookie_names"] = sorted({item.get("name", "") for item in cookie_list})[:40]
                    except Exception:
                        pass
            elif authenticate and not auth_state["authentication_required"]:
                login_diagnostic["result"] = "LOGIN_NOT_NEEDED"
            elif authenticate and (not username or not password):
                login_diagnostic["result"] = "MISSING_CREDENTIALS"

            final_body = str(snapshot.get("body_text_preview", ""))
            final_url = snapshot.get("final_url") or (page.url if not page.is_closed() else "")
            auth_state = _classify_auth_state(final_url, api_responses, final_body,
                                              login_attempted=login_diagnostic.get("attempted", False))

            # Inspect each frame separately: enterprise SSO pages may render controls in an iframe.
            frame_diagnostics: list[dict[str, Any]] = []
            if not page.is_closed():
                for frame_index, frame in enumerate(page.frames):
                    try:
                        frame_data = frame.evaluate("""() => {
                            const clean = value => (value || '').trim().replace(/\\s+/g, ' ');
                            return {
                                title: document.title || '',
                                url: location.href,
                                body_text_preview: clean(document.body ? document.body.innerText : '').slice(0, 1200),
                                inputs: Array.from(document.querySelectorAll('input,textarea,select')).map((el, i) => ({
                                    index: i, tag: el.tagName.toLowerCase(),
                                    type: el.getAttribute('type') || el.tagName.toLowerCase(),
                                    id: el.id || '', name: el.getAttribute('name') || '',
                                    placeholder: el.getAttribute('placeholder') || '',
                                    aria_label: el.getAttribute('aria-label') || '',
                                    disabled: !!el.disabled
                                })),
                                buttons: Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]')).map((el, i) => ({
                                    index: i, text: clean(el.innerText || el.value || el.textContent).slice(0,120),
                                    aria_label: el.getAttribute('aria-label') || '',
                                    type: el.getAttribute('type') || ''
                                }))
                            };
                        }""")
                        frame_diagnostics.append({"frame_index":frame_index, **frame_data})
                    except Exception as exc:
                        frame_diagnostics.append({
                            "frame_index":frame_index, "url":frame.url,
                            "inspection_error":f"{type(exc).__name__}: {exc}"[:300]
                        })

            screenshot_saved = False
            try:
                page.screenshot(
                    path=screenshot_path, full_page=False, timeout=15000,
                    animations="disabled", caret="hide"
                )
                screenshot_saved = True
            except Exception as exc:
                navigation_errors.append(f"Chụp màn hình: {type(exc).__name__}: {exc}")
            if not screenshot_saved:
                screenshot_path = ""

            return {
                "requested_url":url,
                "final_url":final_url,
                "http_status":document_responses[-1]["status"] if document_responses else None,
                "title":snapshot.get("title", ""),
                "ready_state":snapshot.get("ready_state", "unknown"),
                **auth_state,
                "login_diagnostic":login_diagnostic,
                "frame_diagnostics":frame_diagnostics,
                "headings":snapshot.get("headings", []),
                "forms":snapshot.get("forms", []),
                "inputs":snapshot.get("inputs", []),
                "buttons":snapshot.get("buttons", []),
                "links":snapshot.get("links", []),
                "body_text_preview":final_body,
                "document_responses":document_responses[-20:],
                "api_responses":api_responses[-80:],
                "failed_requests":failed_requests[-40:],
                "console_errors":console_errors[-30:],
                "page_errors":page_errors[-20:],
                "navigation_errors":navigation_errors[-20:],
                "screenshot_path":screenshot_path,
                "read_only":True,
            }
        finally:
            browser.close()
            gc.collect()

def execute_case(case: dict[str, Any], page: Any, base_url: str,
                 username: str = "", password: str = "") -> tuple[str, str, str]:
    steps = validate_steps_json(case.get("steps_json", "[]"))
    if any(s.get("action") == "manual" for s in steps):
        raise ManualStepRequired("Case contains a manual placeholder. Add verified browser steps before execution.")
    variables = {"BASE_URL": base_url.rstrip("/"), "USERNAME": username, "PASSWORD": password}
    for index, step in enumerate(steps, 1):
        action = step["action"]
        selector = _substitute(step.get("selector", ""), variables)
        value = _substitute(step.get("value", ""), variables)
        timeout = min(int(step.get("timeout", 7000)), 30000)
        if action == "goto":
            url = _resolve_url(str(_substitute(step.get("url", "${BASE_URL}"), variables)), base_url)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        elif action == "fill":
            if not selector: raise ValueError(f"Step {index}: fill requires selector.")
            page.locator(selector).fill(str(value), timeout=timeout)
        elif action == "click":
            if not selector: raise ValueError(f"Step {index}: click requires selector.")
            page.locator(selector).click(timeout=timeout)
        elif action == "select_option":
            page.locator(selector).select_option(str(value), timeout=timeout)
        elif action == "check":
            page.locator(selector).check(timeout=timeout)
        elif action == "uncheck":
            page.locator(selector).uncheck(timeout=timeout)
        elif action == "expect_visible":
            page.locator(selector).wait_for(state="visible", timeout=timeout)
        elif action == "expect_hidden":
            page.locator(selector).wait_for(state="hidden", timeout=timeout)
        elif action == "expect_text":
            expected = str(_substitute(step.get("text", ""), variables))
            actual = (page.locator(selector) if selector else page.locator("body")).inner_text(timeout=timeout)
            if expected not in actual: raise AssertionError(f"Expected text {expected!r} was not found.")
        elif action == "expect_url":
            expected = str(_substitute(step.get("contains", ""), variables))
            if expected not in page.url: raise AssertionError(f"Expected URL to contain {expected!r}; actual: {page.url}")
        elif action == "assert_title":
            expected = str(_substitute(step.get("contains", ""), variables))
            actual = page.title()
            if expected not in actual: raise AssertionError(f"Expected title to contain {expected!r}; actual: {actual!r}")
        elif action == "press":
            page.locator(selector).press(str(step.get("key", "Enter")), timeout=timeout)
        elif action == "screenshot":
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(step.get("name") or f"step-{index}"))[:45]
            path = ARTIFACT_DIR / f"{case['case_key']}-{name}.png"
            page.screenshot(path=str(path), full_page=True)
        elif action == "wait_for_timeout":
            page.wait_for_timeout(min(max(int(step.get("milliseconds", 500)), 0), 10000))
        else:
            raise ValueError(f"Unsupported action: {action}")
    return "PASS", "All browser assertions passed.", ""


def run_suite(project_id: int, base_url: str, cases: list[dict[str, Any]],
              username: str = "", password: str = "", headless: bool = True) -> dict[str, Any]:
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a full Base URL including https:// or http://.")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in the URL.")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = create_run(project_id, base_url.strip())
    results = []
    overall = "COMPLETED"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = _launch_low_memory_browser(pw, True)
            try:
                for case in cases:
                    started = time.perf_counter()
                    context = page = None
                    screenshot_path = ""
                    try:
                        context = browser.new_context(viewport={"width": 1024, "height": 768}, device_scale_factor=1, service_workers="block")
                        page = context.new_page()
                        page.set_default_timeout(7000)
                        status, message, screenshot_path = execute_case(case, page, base_url.strip(), username, password)
                    except ManualStepRequired as exc:
                        status, message = "BLOCKED", str(exc)
                    except Exception as exc:
                        status, message = "FAIL", f"{type(exc).__name__}: {exc}"
                        try:
                            if page and not page.is_closed():
                                screenshot_path = str(ARTIFACT_DIR / f"{case['case_key']}-failure.png")
                                page.screenshot(path=screenshot_path, full_page=False, timeout=2500)
                        except Exception:
                            screenshot_path = ""
                    finally:
                        if context:
                            context.close()
                        gc.collect()
                    duration = time.perf_counter() - started
                    save_result(run_id, int(case["id"]), status, message, screenshot_path, duration)
                    results.append({"case_key": case["case_key"], "title": case["title"], "status": status,
                                    "message": message, "screenshot_path": screenshot_path,
                                    "duration_seconds": round(duration, 2)})
            finally:
                browser.close()
                gc.collect()
    except Exception as exc:
        overall = "ERROR"
        results.append({"case_key": "-", "title": "Runner setup", "status": "BLOCKED",
                        "message": f"{type(exc).__name__}: {exc}", "screenshot_path": "", "duration_seconds": 0})
    finish_run(run_id, overall)
    return {"run_id": run_id, "status": overall, "results": results}
