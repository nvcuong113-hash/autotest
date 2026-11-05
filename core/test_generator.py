from __future__ import annotations

import hashlib
import json
from typing import Any


PATTERNS = [
    ("Positive", "High", "Provide valid input that satisfies the requirement.",
     "The system completes the requested behavior and displays or persists the expected outcome."),
    ("Negative", "High", "Provide missing, invalid or inconsistent input relevant to the requirement.",
     "The system rejects invalid input safely and gives a clear validation message."),
    ("Boundary", "Medium", "Test minimum, maximum, empty and format/length boundary values where applicable.",
     "The system enforces documented limits without data loss or an unexpected error."),
    ("Authorization", "High", "Repeat the action with a user role that should not be allowed to perform it.",
     "The system denies unauthorized access and does not expose or change protected data."),
]

LEGACY_ACTIONS = {
    "goto", "fill", "click", "select_option", "check", "uncheck",
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "assert_title", "press", "screenshot", "wait_for_timeout", "manual",
}

SEMANTIC_ACTIONS = {
    "navigate", "click", "fill", "select_option", "check", "uncheck",
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "wait_for", "assert_state", "manual",
}


def generate_cases(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic offline fallback; deliberately marks unverified steps as manual."""
    cases = []
    for req in requirements:
        key = str(req.get("req_key") or "")
        title = str(req.get("title") or req.get("description") or key)
        for kind, priority, pre, expected in PATTERNS:
            cases.append({
                "case_key": "TC-" + hashlib.sha256(
                    "|".join([key, kind, title]).encode("utf-8")
                ).hexdigest()[:10].upper(),
                "req_key": key,
                "title": f"[{key}] {kind}: {title[:90]}",
                "test_type": kind,
                "priority": priority,
                "preconditions": pre,
                "steps": [{"action": "manual", "description":
                    "Bổ sung workflow nghiệp vụ và mapping target đã được xác minh trong Application Profile. Không tự đoán selector."}],
                "expected_result": expected,
                "automation_level": "manual",
            })
    return cases


def validate_steps_json(steps: Any) -> list[dict[str, Any]]:
    parsed = json.loads(steps) if isinstance(steps, str) else steps
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("Test steps must be a non-empty JSON array.")
    allowed = LEGACY_ACTIONS | SEMANTIC_ACTIONS
    for i, step in enumerate(parsed, 1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} must be an object.")
        action = str(step.get("action") or "")
        if action not in allowed:
            raise ValueError(f"Step {i}: unsupported action {action!r}.")
        if action == "navigate" and not (step.get("page") or step.get("target")):
            raise ValueError(f"Step {i}: semantic navigate requires page or target.")
        if action in {"click", "fill", "select_option", "check", "uncheck",
                      "expect_visible", "expect_hidden", "assert_state"} and not (
            step.get("target") or step.get("selector")
        ):
            raise ValueError(f"Step {i}: {action} requires a semantic target.")
        if action == "expect_text" and not (
            step.get("expected") or step.get("value") or step.get("text")
        ):
            raise ValueError(f"Step {i}: expect_text requires expected text.")
        if action == "expect_url" and not (
            step.get("expected") or step.get("contains") or step.get("page")
        ):
            raise ValueError(f"Step {i}: expect_url requires an expected path or page.")
        if action == "manual" and not str(step.get("description") or "").strip():
            raise ValueError(f"Step {i}: manual step requires a description.")
    return parsed
