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



def inspect_page(target_url: str, base_url: str, headless: bool = True) -> dict[str, Any]:
    """Read-only inspection of a page on the configured target host.

    It does not fill fields, click buttons, submit forms or store browser cookies.
    """
    if not base_url.strip():
        raise ValueError("Configure the Base URL before inspecting a page.")
    url = _resolve_url(target_url.strip() or base_url.strip(), base_url.strip())
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in the inspection URL.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(ARTIFACT_DIR / f"page-inspection-{time.time_ns()}.png")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(8000)
            response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(800)

            inputs = page.locator("input, textarea, select").evaluate_all(
                """els => els.map((el, i) => {
                    const labels = el.labels ? Array.from(el.labels).map(x => (x.innerText || x.textContent || '').trim()).filter(Boolean) : [];
                    const tag = el.tagName.toLowerCase();
                    const type = (el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : tag)).toLowerCase();
                    const id = el.id || '';
                    const name = el.getAttribute('name') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    let suggested = '';
                    if (id) suggested = '#' + CSS.escape(id);
                    else if (name) suggested = tag + '[name="' + CSS.escape(name) + '"]';
                    else if (placeholder) suggested = tag + '[placeholder="' + CSS.escape(placeholder) + '"]';
                    return {index:i, tag, type, id, name, placeholder,
                            aria_label:el.getAttribute('aria-label') || '',
                            labels, required:!!el.required, disabled:!!el.disabled,
                            suggested_selector:suggested};
                })"""
            )
            buttons = page.locator("button, [role='button'], input[type='submit'], input[type='button']").evaluate_all(
                """els => els.map((el, i) => {
                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.value || el.textContent || '').trim().replace(/\\\\s+/g, ' ');
                    const aria = el.getAttribute('aria-label') || '';
                    const title = el.getAttribute('title') || '';
                    const id = el.id || '';
                    const name = el.getAttribute('name') || '';
                    let suggested = '';
                    if (id) suggested = '#' + CSS.escape(id);
                    else if (name) suggested = tag + '[name="' + CSS.escape(name) + '"]';
                    return {index:i, tag, text:text.slice(0,160), aria_label:aria, title,
                            type:el.getAttribute('type') || '', disabled:!!el.disabled,
                            suggested_selector:suggested};
                })"""
            )
            links = page.locator("a[href]").evaluate_all(
                """els => els.slice(0,100).map((el, i) => ({
                    index:i, text:(el.innerText || el.textContent || '').trim().replace(/\\\\s+/g, ' ').slice(0,120),
                    href:el.href
                }))"""
            )
            headings = page.locator("h1, h2, h3").evaluate_all(
                """els => els.slice(0,80).map(el => ({
                    level:el.tagName.toLowerCase(),
                    text:(el.innerText || el.textContent || '').trim().replace(/\\\\s+/g, ' ').slice(0,200)
                })).filter(x => x.text)"""
            )
            forms = page.locator("form").evaluate_all(
                """els => els.map((el, i) => ({
                    index:i, method:(el.getAttribute('method') || 'get').toUpperCase(),
                    action:el.action || '', id:el.id || '', name:el.getAttribute('name') || ''
                }))"""
            )
            page.screenshot(path=screenshot_path, full_page=True, timeout=10000)
            return {
                "requested_url": url,
                "final_url": page.url,
                "http_status": response.status if response else None,
                "title": page.title(),
                "headings": headings,
                "forms": forms,
                "inputs": inputs,
                "buttons": buttons,
                "links": links,
                "screenshot_path": screenshot_path,
                "read_only": True,
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
