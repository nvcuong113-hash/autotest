from __future__ import annotations

import json
import uuid
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


def generate_cases(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for req in requirements:
        key = str(req.get("req_key") or "")
        title = str(req.get("title") or req.get("description") or key)
        for kind, priority, pre, expected in PATTERNS:
            cases.append({
                "case_key": f"TC-{uuid.uuid4().hex[:8].upper()}",
                "req_key": key,
                "title": f"[{key}] {kind}: {title[:90]}",
                "test_type": kind,
                "priority": priority,
                "preconditions": pre,
                "steps": [{"action": "manual", "description":
                    "Inspect the application and add verified browser actions, selectors and test data. Do not guess selectors."}],
                "expected_result": expected,
            })
    return cases


def validate_steps_json(steps: Any) -> list[dict[str, Any]]:
    parsed = json.loads(steps) if isinstance(steps, str) else steps
    if not isinstance(parsed, list):
        raise ValueError("Test steps must be a JSON array.")
    allowed = {"goto", "fill", "click", "select_option", "check", "uncheck",
               "expect_visible", "expect_hidden", "expect_text", "expect_url",
               "assert_title", "press", "screenshot", "wait_for_timeout", "manual"}
    for i, step in enumerate(parsed, 1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} must be an object.")
        if step.get("action") not in allowed:
            raise ValueError(f"Step {i}: unsupported action {step.get('action')!r}.")
    return parsed
