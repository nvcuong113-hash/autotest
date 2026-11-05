from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.db import add_test_cases, save_requirements

SUITE_PATH = Path(__file__).resolve().parent.parent / "testdata" / "ccm_guarantee_suite.json"


def load_guarantee_suite() -> dict[str, Any]:
    with SUITE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data.get("requirements"), list) or not isinstance(data.get("test_cases"), list):
        raise ValueError("Invalid built-in CCM Guarantee suite format.")
    return data


def import_guarantee_suite(project_id: int, db_path: str | None = None) -> dict[str, int | str]:
    suite = load_guarantee_suite()
    requirement_count = save_requirements(project_id, suite["requirements"], db_path=db_path)
    case_count = add_test_cases(project_id, suite["test_cases"], db_path=db_path)
    return {
        "suite_id": str(suite.get("suite_id", "")),
        "requirement_count": requirement_count,
        "case_count": case_count,
    }
