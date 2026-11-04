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
