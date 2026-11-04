import json

from core.browser_runner import _resolve_url
from core.db import add_test_cases, create_project, init_db, list_requirements, list_test_cases, save_requirements
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


def test_database_requirement_to_case_traceability(tmp_path):
    db = str(tmp_path / "autotest.sqlite3")
    init_db(db)
    project_id = create_project("Sample QA Project", db_path=db)
    reqs = [{"req_key":"FR-001","title":"User login","description":"The system must allow login.","source":"sample.docx"}]
    assert save_requirements(project_id, reqs, db_path=db) == 1
    assert list_requirements(project_id, db_path=db)[0]["req_key"] == "FR-001"
    generated = generate_cases(reqs)
    assert add_test_cases(project_id, generated, db_path=db) == 4
    saved_cases = list_test_cases(project_id, db_path=db)
    assert len(saved_cases) == 4
    assert all(row["req_key"] == "FR-001" for row in saved_cases)



def test_builtin_guarantee_suite_import_and_traceability(tmp_path):
    from core.db import create_project, init_db, list_requirements, list_test_cases
    from core.suite_catalog import import_guarantee_suite, load_guarantee_suite

    db = str(tmp_path / "guarantee-suite.sqlite3")
    init_db(db)
    project_id = create_project("CCM Guarantee", db_path=db)
    suite = load_guarantee_suite()
    assert len(suite["test_cases"]) >= 60

    imported = import_guarantee_suite(project_id, db_path=db)
    assert imported["requirement_count"] == len(suite["requirements"])
    assert imported["case_count"] == len(suite["test_cases"])

    saved_requirements = list_requirements(project_id, db_path=db)
    saved_cases = list_test_cases(project_id, db_path=db)
    assert len(saved_requirements) == len(suite["requirements"])
    assert len(saved_cases) == len(suite["test_cases"])
    assert all(case["req_key"] for case in saved_cases)
    assert all(case["source_ref"] for case in saved_cases)

    # Re-importing the catalogue to the same project must be idempotent.
    repeated = import_guarantee_suite(project_id, db_path=db)
    assert repeated["case_count"] == 0
    assert len(list_test_cases(project_id, db_path=db)) == len(suite["test_cases"])

    # The same built-in catalogue must also be importable into a second project.
    second_project = create_project("CCM Guarantee - Second Entity", db_path=db)
    second_import = import_guarantee_suite(second_project, db_path=db)
    assert second_import["case_count"] == len(suite["test_cases"])
    second_cases = list_test_cases(second_project, db_path=db)
    assert len(second_cases) == len(suite["test_cases"])
    assert all(case["case_key"].startswith("P" + str(second_project) + "-BG-") for case in second_cases)



def test_resolve_inspection_url_rejects_different_host():
    from core.browser_runner import _resolve_url
    try:
        _resolve_url("https://different.example/login", "https://oap-meta-staging.ovigroup.vn")
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("Inspector must not navigate to a different host")


def test_evaluate_with_navigation_retry_recovers_after_redirect():
    from core.browser_runner import _evaluate_with_navigation_retry

    class FakePage:
        def __init__(self):
            self.calls = 0

        def evaluate(self, script):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
            return {"title": "Login", "ok": True}

        def wait_for_load_state(self, state, timeout):
            return None

        def wait_for_timeout(self, milliseconds):
            return None

        def is_closed(self):
            return False

    page = FakePage()
    result = _evaluate_with_navigation_retry(page, "() => document.title", attempts=3)
    assert result == {"title": "Login", "ok": True}
    assert page.calls == 2


def test_evaluate_with_navigation_retry_does_not_hide_real_errors():
    from core.browser_runner import _evaluate_with_navigation_retry

    class FakePage:
        def evaluate(self, script):
            raise RuntimeError("selector syntax is invalid")

        def is_closed(self):
            return False

    try:
        _evaluate_with_navigation_retry(FakePage(), "() => 1")
    except RuntimeError as exc:
        assert "selector syntax" in str(exc)
    else:
        raise AssertionError("Non-navigation errors must not be swallowed")

def test_classify_auth_state_from_login_redirect_and_401():
    from core.browser_runner import _classify_auth_state

    redirected = _classify_auth_state(
        "https://oap-meta-staging.ovigroup.vn/login",
        [{"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me","status":401}],
        "",
    )
    assert redirected["authentication_required"] is True
    assert redirected["authentication_pending"] is False
    assert redirected["authentication_state"] == "LOGIN_REQUIRED"
    assert redirected["auth_api_401"] is True
    assert redirected["redirected_to_login"] is True


def test_classify_auth_state_pending_without_login_redirect():
    from core.browser_runner import _classify_auth_state

    pending = _classify_auth_state(
        "https://oap-meta-staging.ovigroup.vn/app/ccm",
        [{"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me","status":202}],
        "Checking authentication...",
    )
    assert pending["authentication_required"] is False
    assert pending["authentication_pending"] is True
    assert pending["authentication_state"] == "AUTH_PENDING"