from __future__ import annotations

import json
from typing import Any


def generate_cases_with_ai(requirements: list[dict[str, Any]], api_key: str) -> list[dict[str, Any]]:
    if not api_key.strip():
        raise ValueError("OpenAI API key is required.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key.strip())
    prompt = {
        "task": "Draft software test cases for the supplied requirements.",
        "rules": [
            "Return a JSON object with a test_cases array.",
            "Cover positive, negative, boundary and permission cases where relevant.",
            "Never invent selectors, endpoints, roles or test data.",
            "Use one manual step if details are unknown.",
            "Each case: req_key,title,test_type,priority,preconditions,steps,expected_result.",
            "Allowed actions: goto,fill,click,select_option,check,uncheck,expect_visible,expect_hidden,expect_text,expect_url,assert_title,press,screenshot,wait_for_timeout,manual."
        ],
        "requirements": requirements[:25],
    }
    response = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.2, response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a careful senior QA engineer. Do not fabricate unknown application behavior."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}
        ])
    data = json.loads(response.choices[0].message.content or "{}")
    cases = data.get("test_cases", []) if isinstance(data, dict) else []
    from core.test_generator import validate_steps_json
    result = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        try:
            steps = validate_steps_json(item.get("steps", [{"action": "manual"}]))
        except (ValueError, TypeError):
            steps = [{"action": "manual", "description": "Review AI-generated steps."}]
        result.append({
            "req_key": str(item.get("req_key") or ""),
            "title": str(item.get("title") or "AI-generated case"),
            "test_type": str(item.get("test_type") or "Functional"),
            "priority": str(item.get("priority") or "Medium"),
            "preconditions": str(item.get("preconditions") or ""),
            "steps": steps,
            "expected_result": str(item.get("expected_result") or ""),
        })
    return result
