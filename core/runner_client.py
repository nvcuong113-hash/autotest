from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _runner_request(path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    base_url = os.getenv("RUNNER_URL", "").strip().rstrip("/")
    token = os.getenv("RUNNER_API_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError(
            "Chưa cấu hình Browser Runner. Cần đặt RUNNER_URL và RUNNER_API_TOKEN "
            "trong Environment của dịch vụ AutoTest."
        )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        raise RuntimeError(f"Browser Runner trả HTTP {exc.code}. Kiểm tra trạng thái dịch vụ Runner.") from None
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
        },
        timeout=1800,
    )
