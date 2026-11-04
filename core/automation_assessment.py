from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


ASSERTION_ACTIONS = {
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "assert_state", "assert_title",
}
TARGET_ACTIONS = {
    "click", "fill", "select_option", "check", "uncheck",
    "expect_visible", "expect_hidden", "expect_text", "assert_state",
}
SUPPORTED_SEMANTIC_ACTIONS = {
    "navigate", "click", "fill", "select_option", "check", "uncheck",
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "wait_for", "assert_state", "manual",
}
LEGACY_SELECTOR_FIELDS = {"selector", "xpath", "css"}


def _steps_for(case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    raw = case.get("steps_json", "[]")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return [], "JSON các bước kiểm thử không hợp lệ."
    if not isinstance(parsed, list) or not parsed:
        return [], "Chưa có workflow kiểm thử."
    if any(not isinstance(step, dict) for step in parsed):
        return [], "Workflow có bước không đúng định dạng object."
    return parsed, ""


def _find_target(profile: dict[str, Any], page_id: str, target_id: str) -> dict[str, Any] | None:
    page = (profile.get("pages") or {}).get(page_id) if page_id else None
    if isinstance(page, dict):
        found = (page.get("targets") or {}).get(target_id)
        if isinstance(found, dict):
            return found
    found = (profile.get("shared_targets") or {}).get(target_id)
    return found if isinstance(found, dict) else None


def extract_case_targets(case: dict[str, Any]) -> list[dict[str, str]]:
    steps, error = _steps_for(case)
    if error:
        return []
    refs: list[dict[str, str]] = []
    current_page = ""
    for step in steps:
        action = str(step.get("action") or "").lower()
        if action == "navigate":
            current_page = str(step.get("page") or step.get("target") or "")
        elif step.get("page"):
            current_page = str(step.get("page") or "")
        target_id = str(step.get("target") or "").strip()
        if target_id and action != "navigate":
            item = {"page_id": current_page, "target_id": target_id}
            if item not in refs:
                refs.append(item)
    return refs


def assess_test_case(case: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    steps, parse_error = _steps_for(case)
    reasons: list[dict[str, str]] = []
    warnings: list[str] = []
    targets: list[dict[str, str]] = []
    active_page = ""
    has_assertion = False

    if parse_error:
        reasons.append({"code": "WORKFLOW_INVALID", "message": parse_error})

    for index, step in enumerate(steps, 1):
        action = str(step.get("action") or "").strip().lower()
        target_id = str(step.get("target") or "").strip()
        page_id = str(step.get("page") or "").strip()

        if action in ASSERTION_ACTIONS:
            has_assertion = True

        if action == "manual":
            reasons.append({
                "code": "MANUAL_STEP",
                "message": f"Bước {index} vẫn là thao tác thủ công: {str(step.get('description') or 'chưa có mô tả')[:180]}",
            })
            continue

        if action not in SUPPORTED_SEMANTIC_ACTIONS and action not in {
            "goto", "press", "screenshot", "wait_for_timeout", "assert_title"
        }:
            reasons.append({
                "code": "UNSUPPORTED_ACTION",
                "message": f"Bước {index} dùng action chưa được hỗ trợ: {action or '(trống)'}.",
            })
            continue

        if action == "navigate":
            active_page = page_id or target_id
            page = (profile.get("pages") or {}).get(active_page)
            if not isinstance(page, dict) or not str(page.get("path") or "").startswith("/"):
                reasons.append({
                    "code": "PAGE_NOT_MAPPED",
                    "message": f"Bước {index}: page '{active_page or '(chưa khai báo)'}' chưa có route trong Application Profile.",
                })
            continue

        if page_id:
            active_page = page_id

        if action in TARGET_ACTIONS and not target_id:
            reasons.append({
                "code": "TARGET_ID_MISSING",
                "message": f"Bước {index}: action '{action}' chưa có semantic target.",
            })
            continue

        if target_id:
            ref = {"page_id": active_page, "target_id": target_id}
            if ref not in targets:
                targets.append(ref)
            definition = _find_target(profile, active_page, target_id)
            if definition is None:
                reasons.append({
                    "code": "TARGET_NOT_MAPPED",
                    "message": f"Bước {index}: target '{target_id}' chưa được mapping"
                    + (f" trên page '{active_page}'." if active_page else "."),
                })
            elif definition.get("verified") is not True:
                reasons.append({
                    "code": "TARGET_NOT_VERIFIED",
                    "message": f"Bước {index}: target '{target_id}' đã khai báo nhưng chưa được xác minh.",
                })
            elif not definition.get("by") or not definition.get("value"):
                reasons.append({
                    "code": "TARGET_LOCATOR_INCOMPLETE",
                    "message": f"Bước {index}: target '{target_id}' thiếu locator strategy/value.",
                })

        # Direct CSS/XPath selectors cannot be included in a reusable,
        # profile-driven Test Case. They must be converted to semantic targets.
        if not target_id and any(step.get(field) for field in LEGACY_SELECTOR_FIELDS):
            warnings.append(f"Bước {index} còn dùng selector trực tiếp; nên chuyển sang semantic target.")

    if not has_assertion:
        reasons.append({
            "code": "ASSERTION_MISSING",
            "message": "Chưa có assertion kiểm chứng kết quả nghiệp vụ; không được mở khóa để tránh PASS giả.",
        })

    # Keep the assessment concise and deterministic.
    deduped: list[dict[str, str]] = []
    seen = set()
    for reason in reasons:
        marker = (reason["code"], reason["message"])
        if marker not in seen:
            seen.add(marker)
            deduped.append(reason)

    if any(reason["code"] in {"MANUAL_STEP", "WORKFLOW_INVALID", "ASSERTION_MISSING", "UNSUPPORTED_ACTION"} for reason in deduped):
        recommended_level = "manual"
    elif deduped:
        recommended_level = "partially_automatable"
    elif warnings:
        recommended_level = "partially_automatable"
    else:
        recommended_level = "automatable"

    ready = not deduped and not warnings and recommended_level == "automatable"
    return {
        "case_id": case.get("id"),
        "case_key": str(case.get("case_key") or ""),
        "title": str(case.get("title") or ""),
        "req_key": str(case.get("req_key") or ""),
        "current_level": str(case.get("automation_level") or "manual"),
        "recommended_level": recommended_level,
        "status": "READY" if ready else "BLOCKED",
        "blocked_reason": " · ".join(reason["message"] for reason in deduped) or " · ".join(warnings),
        "reasons": deduped,
        "warnings": warnings,
        "targets": targets,
        "target_count": len(targets),
    }


def assess_cases(cases: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [assess_test_case(case, profile) for case in cases]


def build_mapping_coverage(
    cases: list[dict[str, Any]],
    profile: dict[str, Any],
    saved_mappings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    usage: dict[tuple[str, str], set[str]] = defaultdict(set)
    for case in cases:
        for ref in extract_case_targets(case):
            usage[(ref["page_id"], ref["target_id"])].add(str(case.get("case_key") or ""))

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for (page_id, target_id), case_keys in usage.items():
        definition = _find_target(profile, page_id, target_id)
        rows[(page_id, target_id)] = {
            "page_id": page_id or "(Shared)",
            "target_id": target_id,
            "mapping_status": "Đã xác minh" if definition and definition.get("verified") is True
                else ("Đã khai báo, chưa xác minh" if definition else "Chưa mapping"),
            "verified": bool(definition and definition.get("verified") is True),
            "usage_count": len(case_keys),
            "case_keys": ", ".join(sorted(case_keys)),
            "locator": f"{definition.get('by')}: {definition.get('value')}" if definition else "",
        }

    # Include mappings created in the project even when no current case references
    # them, so users can prepare reusable page/component dictionaries in advance.
    for mapping in saved_mappings or []:
        key = (str(mapping.get("page_id") or ""), str(mapping.get("target_id") or ""))
        if key not in rows:
            rows[key] = {
                "page_id": key[0] or "(Shared)",
                "target_id": key[1],
                "mapping_status": "Đã xác minh" if mapping.get("verified") else "Đã khai báo, chưa xác minh",
                "verified": bool(mapping.get("verified")),
                "usage_count": 0,
                "case_keys": "",
                "locator": f"{mapping.get('locator_by')}: {mapping.get('locator_value')}",
            }
    return sorted(rows.values(), key=lambda item: (item["page_id"], item["target_id"]))


def assessment_summary(assessments: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(assessments),
        "ready": sum(item["status"] == "READY" for item in assessments),
        "blocked": sum(item["status"] == "BLOCKED" for item in assessments),
        "automatable": sum(item["recommended_level"] == "automatable" for item in assessments),
        "partially_automatable": sum(item["recommended_level"] == "partially_automatable" for item in assessments),
        "manual": sum(item["recommended_level"] == "manual" for item in assessments),
    }
