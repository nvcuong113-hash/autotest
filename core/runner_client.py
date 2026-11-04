from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from enum import Enum
from uuid import UUID
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    """Convert database/domain values to lossless JSON-compatible values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, datetime_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Preserve decimal precision (e.g. financial amounts) rather than
        # silently converting to a potentially lossy binary float.
        return str(value)
    if isinstance(value, (UUID, Path, os.PathLike)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    # Support scalar types from optional data libraries (e.g. NumPy/Pandas)
    # without making those libraries runtime dependencies of the client.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            scalar = item()
            if scalar is not value:
                return scalar
        except (TypeError, ValueError):
            pass
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable "
        "for the Browser Runner request."
    )


def _runner_request(path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    base_url = os.getenv("RUNNER_URL", "").strip().rstrip("/")
    token = os.getenv("RUNNER_API_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError(
            "Chưa cấu hình Browser Runner. Cần đặt RUNNER_URL và RUNNER_API_TOKEN "
            "trong Environment của dịch vụ AutoTest."
        )
    body = json.dumps(
        payload,
        ensure_ascii=False,
        default=_json_default,
        allow_nan=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Runner-Token": token,
            "User-Agent": "AutoTest-Frontend/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not echo request payloads or credentials in UI errors.
        if exc.code in {502, 503, 504}:
            raise RuntimeError(
                f"Browser Runner trả HTTP {exc.code}; instance có thể đang restart hoặc thiếu RAM. "
                "Kiểm tra Runner Events/Logs trước khi thử lại."
            ) from None
        raise RuntimeError(f"Browser Runner trả HTTP {exc.code}. Kiểm tra cấu hình dịch vụ Runner.") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Không kết nối được Browser Runner ({type(exc).__name__}).") from None
    if not isinstance(result, dict):
        raise RuntimeError("Browser Runner trả về dữ liệu không hợp lệ.")
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result


def inspect_page(
    target_url: str,
    base_url: str,
    headless: bool = True,
    username: str = "",
    password: str = "",
    authenticate: bool = False,
    application_profile_id: str = "oap-meta",
) -> dict[str, Any]:
    result = _runner_request(
        "/inspect",
        {
            "target_url": target_url,
            "base_url": base_url,
            "headless": True,
            "username": username,
            "password": password,
            "authenticate": bool(authenticate),
            "application_profile_id": application_profile_id,
        },
        timeout=240,
    )
    image_data = result.pop("screenshot_base64", "")
    if image_data:
        try:
            image_bytes = base64.b64decode(image_data, validate=True)
            image_path = Path(tempfile.gettempdir()) / f"autotest-inspection-{uuid.uuid4().hex}.png"
            image_path.write_bytes(image_bytes)
            result["screenshot_path"] = str(image_path)
        except Exception:
            result["screenshot_path"] = ""
    else:
        result["screenshot_path"] = ""
    return result


def run_suite(
    project_id: int,
    base_url: str,
    cases: list[dict[str, Any]],
    username: str = "",
    password: str = "",
    headless: bool = True,
    application_profile_id: str = "oap-meta",
    profile_mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(cases) > 5:
        raise ValueError("Mỗi lượt chỉ chạy tối đa 5 Test Case để giới hạn tài nguyên.")
    return _runner_request(
        "/run",
        {
            "project_id": int(project_id),
            "base_url": base_url,
            "cases": cases,
            "username": username,
            "password": password,
            "headless": True,
            "application_profile_id": application_profile_id,
            "profile_mappings": profile_mappings or [],
        },
        timeout=1800,
    )
