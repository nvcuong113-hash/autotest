from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse


class TargetNotMappedError(RuntimeError):
    """Raised when a semantic business target has no reviewed locator mapping."""


SEMANTIC_ACTIONS = {
    "navigate", "click", "fill", "select_option", "check", "uncheck",
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "wait_for", "assert_state", "manual",
}


def _target_definition(
    profile: dict[str, Any],
    target_id: str,
    page_id: str = "",
) -> dict[str, Any]:
    if page_id:
        page = (profile.get("pages") or {}).get(page_id)
        if isinstance(page, dict):
            definition = (page.get("targets") or {}).get(target_id)
            if isinstance(definition, dict):
                return definition
    definition = (profile.get("shared_targets") or {}).get(target_id)
    if isinstance(definition, dict):
        return definition
    raise TargetNotMappedError(
        f"Semantic target '{target_id}' chưa được khai báo trong Application Profile."
    )


def resolve_semantic_locator(page: Any, profile: dict[str, Any], target_id: str, page_id: str = "") -> Any:
    definition = _target_definition(profile, target_id, page_id)
    policies = profile.get("policies") or {}
    if policies.get("require_verified_targets", True) and definition.get("verified") is not True:
        raise TargetNotMappedError(
            f"Target '{target_id}' đã được khai báo nhưng chưa được xác minh. Không tự đoán selector."
        )
    strategy = str(definition.get("by") or "").lower()
    value = str(definition.get("value") or "")
    name = definition.get("name")
    exact = bool(definition.get("exact", True))
    if strategy == "css" and value:
        return page.locator(value)
    if strategy == "role" and value:
        return page.get_by_role(value, name=name, exact=exact)
    if strategy == "label" and value:
        return page.get_by_label(value, exact=exact)
    if strategy == "placeholder" and value:
        return page.get_by_placeholder(value, exact=exact)
    if strategy == "text" and value:
        return page.get_by_text(value, exact=exact)
    raise TargetNotMappedError(
        f"Target '{target_id}' có locator strategy không hỗ trợ hoặc thiếu value."
    )


def _resolve_page_url(profile: dict[str, Any], base_url: str, page_id: str) -> str:
    definition = (profile.get("pages") or {}).get(page_id)
    if not isinstance(definition, dict):
        raise TargetNotMappedError(f"Page '{page_id}' chưa được khai báo trong Application Profile.")
    path = str(definition.get("path") or "")
    if not path.startswith("/") or path.startswith("//"):
        raise TargetNotMappedError(f"Page '{page_id}' chưa có route nội bộ hợp lệ.")
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    base = urlparse(base_url)
    resolved = urlparse(url)
    if resolved.scheme != base.scheme or resolved.netloc != base.netloc:
        raise TargetNotMappedError("Application Profile không được điều hướng sang origin khác.")
    return url


def execute_semantic_step(
    page: Any,
    profile: dict[str, Any],
    step: dict[str, Any],
    base_url: str,
    variables: dict[str, str] | None = None,
) -> None:
    """Execute business-level actions through a reviewed application page model."""
    variables = variables or {}
    action = str(step.get("action") or "").lower()
    target = str(step.get("target") or "")
    page_id = str(step.get("page") or "")
    timeout = min(max(int(step.get("timeout", 7000)), 500), 30000)

    if action == "manual":
        raise TargetNotMappedError(str(step.get("description") or "Bước này cần thao tác thủ công."))
    if action == "navigate":
        page_id = page_id or target
        page.goto(_resolve_page_url(profile, base_url, page_id), wait_until="domcontentloaded", timeout=timeout)
        return
    if action == "expect_url":
        expected = str(step.get("expected") or step.get("value") or "")
        if not expected and page_id:
            expected = str((profile.get("pages") or {}).get(page_id, {}).get("path") or "")
        if not expected or expected not in str(page.url):
            raise AssertionError(f"URL hiện tại không chứa giá trị mong đợi: {expected or '(chưa khai báo)'}.")
        return
    if action == "wait_for" and not target:
        page.wait_for_timeout(min(max(int(step.get("milliseconds", 500)), 0), 10000))
        return
    if action == "expect_text" and not target:
        expected = str(step.get("expected") or step.get("value") or "")
        actual = page.locator("body").inner_text(timeout=timeout)
        if not expected or expected not in actual:
            raise AssertionError("Không tìm thấy nội dung mong đợi trên trang.")
        return
    if not target:
        raise TargetNotMappedError(f"Action '{action}' yêu cầu semantic target.")
    locator = resolve_semantic_locator(page, profile, target, page_id)
    value = str(step.get("value") or "")
    expected = str(step.get("expected") or step.get("value") or "")

    if action == "click":
        locator.click(timeout=timeout)
    elif action == "fill":
        locator.fill(value, timeout=timeout)
    elif action == "select_option":
        locator.select_option(value, timeout=timeout)
    elif action == "check":
        locator.check(timeout=timeout)
    elif action == "uncheck":
        locator.uncheck(timeout=timeout)
    elif action == "expect_visible":
        locator.wait_for(state="visible", timeout=timeout)
    elif action == "expect_hidden":
        locator.wait_for(state="hidden", timeout=timeout)
    elif action == "wait_for":
        locator.wait_for(state=str(step.get("state") or "visible"), timeout=timeout)
    elif action in {"expect_text", "assert_state"}:
        actual = locator.inner_text(timeout=timeout)
        if not expected or expected not in actual:
            raise AssertionError(f"Target '{target}' không có trạng thái/nội dung mong đợi.")
    else:
        raise ValueError(f"Semantic action chưa được hỗ trợ: {action}")
