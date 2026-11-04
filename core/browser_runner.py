from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from core.db import create_run, finish_run, save_result
from core.test_generator import validate_steps_json

ARTIFACT_DIR = Path("artifacts")


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


def inspect_page(target_url: str, base_url: str, headless: bool = True) -> dict[str, Any]:
    """Read-only inspection that follows application redirects and retries transient navigation."""
    if not base_url.strip():
        raise ValueError("Cần cấu hình Base URL trước khi kiểm tra.")
    url = _resolve_url(target_url.strip() or base_url.strip(), base_url.strip())
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValueError("Không đưa thông tin đăng nhập vào URL.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(ARTIFACT_DIR / f"page-inspection-{time.time_ns()}.png")
    document_responses: list[dict[str, Any]] = []
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
        return {title:document.title || '', final_url:location.href, headings, forms, inputs, buttons, links,
            body_text_preview:clean(document.body ? document.body.innerText : '').slice(0,2500)};
    }'''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(viewport={"width":1440,"height":1000})
            page = context.new_page()
            page.set_default_timeout(8000)
            def on_response(response: Any) -> None:
                try:
                    if response.request.resource_type == "document":
                        document_responses.append({"url":response.url,"status":response.status})
                except Exception:
                    pass
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="commit", timeout=25000)
            except Exception as exc:
                navigation_errors.append(f"Điều hướng ban đầu: {type(exc).__name__}: {exc}")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception as exc:
                navigation_errors.append(f"Chờ DOMContentLoaded: {type(exc).__name__}: {exc}")
            try:
                page.wait_for_timeout(1200)
            except Exception:
                pass
            snapshot = {"title":"", "final_url":page.url, "headings":[], "forms":[], "inputs":[], "buttons":[], "links":[], "body_text_preview":""}
            try:
                snapshot = _evaluate_with_navigation_retry(page, snapshot_script)
            except Exception as exc:
                navigation_errors.append(f"Đọc DOM: {type(exc).__name__}: {exc}")
            screenshot_saved = False
            for attempt in range(3):
                try:
                    page.screenshot(path=screenshot_path, full_page=True, timeout=10000)
                    screenshot_saved = True
                    break
                except Exception as exc:
                    navigation_errors.append(f"Chụp màn hình lần {attempt + 1}: {type(exc).__name__}: {exc}")
                    if page.is_closed():
                        break
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
            if not screenshot_saved:
                screenshot_path = ""
            return {
                "requested_url":url, "final_url":snapshot.get("final_url") or (page.url if not page.is_closed() else ""),
                "http_status":document_responses[-1]["status"] if document_responses else None,
                "title":snapshot.get("title", ""), "headings":snapshot.get("headings", []),
                "forms":snapshot.get("forms", []), "inputs":snapshot.get("inputs", []),
                "buttons":snapshot.get("buttons", []), "links":snapshot.get("links", []),
                "body_text_preview":snapshot.get("body_text_preview", ""),
                "document_responses":document_responses, "navigation_errors":navigation_errors,
                "screenshot_path":screenshot_path, "read_only":True,
            }
        finally:
            browser.close()

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
            browser = pw.chromium.launch(headless=headless)
            try:
                for case in cases:
                    started = time.perf_counter()
                    context = page = None
                    screenshot_path = ""
                    try:
                        context = browser.new_context(viewport={"width": 1440, "height": 900})
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
                                page.screenshot(path=screenshot_path, full_page=True, timeout=3000)
                        except Exception:
                            screenshot_path = ""
                    finally:
                        if context:
                            context.close()
                    duration = time.perf_counter() - started
                    save_result(run_id, int(case["id"]), status, message, screenshot_path, duration)
                    results.append({"case_key": case["case_key"], "title": case["title"], "status": status,
                                    "message": message, "screenshot_path": screenshot_path,
                                    "duration_seconds": round(duration, 2)})
            finally:
                browser.close()
    except Exception as exc:
        overall = "ERROR"
        results.append({"case_key": "-", "title": "Runner setup", "status": "BLOCKED",
                        "message": f"{type(exc).__name__}: {exc}", "screenshot_path": "", "duration_seconds": 0})
    finish_run(run_id, overall)
    return {"run_id": run_id, "status": overall, "results": results}
