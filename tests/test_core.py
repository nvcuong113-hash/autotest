import json

from core.browser_runner import _resolve_url
from core.srs_parser import extract_requirements
from core.test_generator import generate_cases, validate_steps_json


def test_extract_explicit_requirement_ids():
    text = "FR-001 The system must allow sign in using a registered email.\nNFR-002 The system shall respond within three seconds."
    found = extract_requirements(text, "sample.txt")
    assert len(found) == 2
    assert found[0]["req_key"] == "FR-001"
    assert found[1]["req_key"] == "NFR-002"


def test_generator_creates_four_reviewable_cases():
    cases = generate_cases([{"req_key":"FR-001","title":"User login","description":"The user can log in."}])
    assert len(cases) == 4
    assert all(case["steps"][0]["action"] == "manual" for case in cases)


def test_unknown_step_is_rejected():
    try:
        validate_steps_json(json.dumps([{"action":"execute_shell"}]))
    except ValueError as exc:
        assert "unsupported action" in str(exc)
    else:
        raise AssertionError("Unknown action should fail validation")


def test_url_resolution_and_host_guard():
    assert _resolve_url("/login", "https://example.test") == "https://example.test/login"
    try:
        _resolve_url("https://outside.test", "https://example.test")
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("External host should be blocked")
