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
    page_targets = [
        target
        for page in pages.values()
        if isinstance(page, dict)
        for target in (page.get("targets", {}) or {}).values()
    ]
    all_targets = list(shared.values()) + page_targets
    verified = sum(1 for item in all_targets if isinstance(item, dict) and item.get("verified") is True)
    pending = sum(1 for item in all_targets if not isinstance(item, dict) or item.get("verified") is not True)
    return {
        "page_count": len(pages),
        "target_count": len(all_targets),
        "verified_target_count": verified,
        "unmapped_or_unverified_count": pending,
    }
