from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROFILE_DIR = Path(__file__).resolve().parent.parent / "application_profiles"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class ApplicationProfileError(ValueError):
    pass


def list_application_profiles() -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    if not PROFILE_DIR.is_dir():
        return profiles
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profile_id = str(data.get("profile_id") or path.stem)
            if not PROFILE_ID_RE.fullmatch(profile_id):
                continue
            profiles.append({
                "profile_id": profile_id,
                "name": str(data.get("name") or profile_id),
                "description": str(data.get("description") or ""),
                "version": str(data.get("version") or "1.0.0"),
            })
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return profiles


def load_application_profile(profile_id: str) -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise ApplicationProfileError("Mã Application Profile không hợp lệ.")
    path = PROFILE_DIR / f"{profile_id}.json"
    if not path.is_file():
        raise ApplicationProfileError(f"Không tìm thấy Application Profile '{profile_id}'.")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplicationProfileError(f"Không đọc được Application Profile '{profile_id}'.") from exc
    if not isinstance(profile, dict) or profile.get("profile_id") != profile_id:
        raise ApplicationProfileError("Application Profile không hợp lệ hoặc sai profile_id.")
    pages = profile.get("pages", {})
    if not isinstance(pages, dict):
        raise ApplicationProfileError("Application Profile: pages phải là object.")
    for page_id, page in pages.items():
        if not isinstance(page, dict):
            raise ApplicationProfileError(f"Page '{page_id}' không hợp lệ.")
        route = str(page.get("path") or "")
        if route and not route.startswith("/") or route.startswith("//"):
            raise ApplicationProfileError(f"Route của page '{page_id}' phải là path nội bộ bắt đầu bằng '/'.")
    return profile


def get_profile_mapping_summary(profile: dict[str, Any]) -> dict[str, int]:
    shared = profile.get("shared_targets", {}) if isinstance(profile.get("shared_targets"), dict) else {}
    pages = profile.get("pages", {}) if isinstance(profile.get("pages"), dict) else {}
    shared_business = [
        target for target in shared.values()
        if isinstance(target, dict) and target.get("purpose") != "authentication"
    ]
    page_targets = [
        target
        for page in pages.values()
        if isinstance(page, dict)
        for target in (page.get("targets", {}) or {}).values()
    ]
    business_targets = shared_business + page_targets
    verified_business = sum(
        1 for item in business_targets
        if isinstance(item, dict) and item.get("verified") is True
    )
    verified_auth = sum(
        1 for item in shared.values()
        if isinstance(item, dict)
        and item.get("purpose") == "authentication"
        and item.get("verified") is True
    )
    pending_pages = sum(
        1 for page in pages.values()
        if isinstance(page, dict)
        and str(page.get("mapping_status") or "").lower() not in {"mapped", "verified", "ready"}
    )
    pending_targets = sum(
        1 for item in business_targets
        if not isinstance(item, dict) or item.get("verified") is not True
    )
    return {
        "page_count": len(pages),
        "target_count": len(business_targets),
        "verified_target_count": verified_business,
        "verified_business_target_count": verified_business,
        "verified_auth_target_count": verified_auth,
        "unmapped_or_unverified_count": pending_targets,
        "unmapped_page_count": pending_pages,
    }


ALLOWED_LOCATOR_STRATEGIES = {"css", "role", "label", "placeholder", "text"}


def merge_profile_mappings(
    profile: dict[str, Any],
    mappings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Apply project-scoped, reviewed business mappings without mutating the base profile."""
    merged = json.loads(json.dumps(profile))
    for item in mappings or []:
        page_id = str(item.get("page_id") or "").strip()
        target_id = str(item.get("target_id") or "").strip()
        strategy = str(item.get("locator_by") or item.get("by") or "").strip().lower()
        value = str(item.get("locator_value") or item.get("value") or "").strip()
        if not target_id or target_id.startswith("auth."):
            raise ApplicationProfileError("Không được tạo hoặc ghi đè target xác thực qua mapping nghiệp vụ.")
        if strategy not in ALLOWED_LOCATOR_STRATEGIES or not value:
            raise ApplicationProfileError(
                f"Mapping '{target_id}' thiếu locator hợp lệ hoặc strategy không được hỗ trợ."
            )
        definition = {
            "by": strategy,
            "value": value,
            "name": str(item.get("locator_name") or item.get("name") or "").strip() or None,
            "exact": bool(item.get("exact", True)),
            "verified": bool(item.get("verified", False)),
            "evidence": str(item.get("evidence") or "").strip(),
            "purpose": "business",
            "source": "project_mapping",
        }
        if page_id:
            pages = merged.setdefault("pages", {})
            if page_id not in pages or not isinstance(pages[page_id], dict):
                raise ApplicationProfileError(f"Mapping '{target_id}' tham chiếu page không tồn tại: {page_id}.")
            pages[page_id].setdefault("targets", {})[target_id] = definition
        else:
            merged.setdefault("shared_targets", {})[target_id] = definition
    return merged
