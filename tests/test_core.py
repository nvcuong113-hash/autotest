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


def test_low_memory_chromium_profile_limits_renderer_processes():
    from core.browser_runner import CHROMIUM_ARGS, _launch_low_memory_browser

    class FakeChromium:
        def __init__(self):
            self.kwargs = None

        def launch(self, **kwargs):
            self.kwargs = kwargs
            return "browser"

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

    playwright = FakePlaywright()
    assert _launch_low_memory_browser(playwright, True) == "browser"
    assert playwright.chromium.kwargs["headless"] is True
    assert "--renderer-process-limit=1" in CHROMIUM_ARGS
    assert "--disable-dev-shm-usage" in CHROMIUM_ARGS
    assert "--no-zygote" in CHROMIUM_ARGS


def test_runner_client_fails_closed_when_remote_runner_is_not_configured(monkeypatch):
    from core.runner_client import inspect_page

    monkeypatch.delenv("RUNNER_URL", raising=False)
    monkeypatch.delenv("RUNNER_API_TOKEN", raising=False)
    try:
        inspect_page("https://example.test", "https://example.test")
    except RuntimeError as exc:
        assert "RUNNER_URL" in str(exc)
    else:
        raise AssertionError("Must not fall back to local Playwright on the UI instance")


def test_runner_client_caps_browser_batch_at_five_cases():
    from core.runner_client import run_suite

    try:
        run_suite(1, "https://example.test", [{}] * 6)
    except ValueError as exc:
        assert "5" in str(exc)
    else:
        raise AssertionError("Browser batches must be capped at five cases")



def test_classify_auth_state_detects_auth_me_401_even_with_url_query():
    from core.browser_runner import _classify_auth_state

    result = _classify_auth_state(
        "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
        [{"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me?ts=123","status":"HTTP 401 Unauthorized"}],
        "Checking authentication...",
    )
    assert result["authentication_required"] is True
    assert result["authentication_state"] == "LOGIN_REQUIRED"


def test_navigate_to_login_page_builds_first_party_login_url():
    from core.browser_runner import _navigate_to_login_page

    class Locator:
        def __init__(self, count):
            self._count = count

        def count(self):
            return self._count

    class FakePage:
        def __init__(self):
            self.url = "https://oap-meta-staging.ovigroup.vn/app/ccm"
            self.goto_url = ""

        def goto(self, url, wait_until, timeout):
            self.goto_url = url
            self.url = url

        def locator(self, selector):
            return Locator(1)

        def wait_for_timeout(self, milliseconds):
            return None

    page = FakePage()
    result = _navigate_to_login_page(page, "https://oap-meta-staging.ovigroup.vn")
    assert page.goto_url == "https://oap-meta-staging.ovigroup.vn/login"
    assert result["result"] == "LOGIN_PAGE_READY"



def test_auth_login_http_200_does_not_mean_authenticated_until_auth_me_200():
    from core.browser_runner import _classify_auth_state

    events = [
        {
            "url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me",
            "method":"GET",
            "status":401,
        },
        {
            "url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/login",
            "method":"POST",
            "status":200,
        },
    ]
    result = _classify_auth_state(
        "https://oap-meta-staging.ovigroup.vn/login",
        events,
        "Login Username Password",
        login_attempted=True,
    )
    assert result["login_api_latest_status"] == 200
    assert result["auth_me_latest_status"] == 401
    assert result["authentication_required"] is True
    assert result["authenticated"] is False
    assert result["authentication_state"] == "LOGIN_NOT_CONFIRMED"


def test_auth_me_200_after_login_confirms_session():
    from core.browser_runner import _classify_auth_state

    events = [
        {"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me","method":"GET","status":401},
        {"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/login","method":"POST","status":200},
        {"url":"https://oap-meta-staging.ovigroup.vn/api/v1/auth/me","method":"GET","status":200},
    ]
    result = _classify_auth_state(
        "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
        events,
        "Quản lý bảo lãnh",
        login_attempted=True,
    )
    assert result["auth_api_success"] is True
    assert result["authenticated"] is True
    assert result["authentication_state"] == "AUTHENTICATED"


def test_auth_login_response_summary_never_exposes_token_values():
    from core.browser_runner import _auth_login_response_summary

    result = _auth_login_response_summary(
        200,
        {
            "success": False,
            "message": "Invalid credentials for test.user@example.com",
            "data": {"access_token": "super-secret-token", "refreshToken": "refresh-secret"},
        },
        "application/json",
        True,
    )
    serialized = str(result)
    assert result["success"] is False
    assert result["message"] == "Invalid credentials for [email]"
    assert result["token_fields_present"]["access_token"] is True
    assert "super-secret-token" not in serialized
    assert "refresh-secret" not in serialized



def test_browser_runner_diagnostic_buffers_are_bounded():
    from core.browser_runner import _append_limited

    values = []
    for number in range(10):
        _append_limited(values, number, limit=6)
    assert len(values) <= 6
    assert values[-1] == 9
    assert 9 in values


def test_low_memory_chromium_profile_caps_v8_heap():
    from core.browser_runner import CHROMIUM_ARGS

    assert "--js-flags=--max-old-space-size=128" in CHROMIUM_ARGS
    assert "--renderer-process-limit=1" in CHROMIUM_ARGS
    assert "--disable-dev-shm-usage" in CHROMIUM_ARGS



def test_authenticated_inspection_starts_at_login_to_avoid_loading_business_spa():
    from core.browser_runner import _inspection_start_url

    assert _inspection_start_url(
        "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
        "https://oap-meta-staging.ovigroup.vn",
        True,
    ) == "https://oap-meta-staging.ovigroup.vn/login"


def test_read_only_inspection_keeps_requested_business_url():
    from core.browser_runner import _inspection_start_url

    target = "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST"
    assert _inspection_start_url(
        target, "https://oap-meta-staging.ovigroup.vn", False
    ) == target



def test_page_readiness_does_not_confuse_auth_shell_loading_with_loaded_module():
    from core.browser_runner import _assess_page_readiness

    result = _assess_page_readiness(
        {
            "final_url":"https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
            "body_text_preview":"OAP Meta Loading... My Tasks Approvals Discussions Alerts Me",
            "main_text_preview":"Loading...",
            "loading_indicator_count":1,
            "table_count":0,
            "data_row_count":0,
        },
        "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
    )
    assert result["ready_candidate"] is False
    assert result["state"] == "BUSINESS_PAGE_LOADING"


def test_page_readiness_accepts_stable_business_table_content():
    from core.browser_runner import _assess_page_readiness

    result = _assess_page_readiness(
        {
            "final_url":"https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
            "body_text_preview":"OAP Meta Quản lý bảo lãnh Danh sách bảo lãnh",
            "main_text_preview":"Quản lý bảo lãnh Danh sách bảo lãnh Mã bảo lãnh Trạng thái",
            "loading_indicator_count":0,
            "table_count":1,
            "data_row_count":3,
            "headings":[{"text":"Quản lý bảo lãnh"}],
        },
        "https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
    )
    assert result["ready_candidate"] is True
    assert result["state"] == "BUSINESS_CONTENT_CANDIDATE"


def test_gemini_provider_status_and_json_parsing(monkeypatch):
    from core.ai_provider import get_ai_status, parse_json_response, GeminiProvider

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-real-secret")
    status = get_ai_status()
    assert status.provider == "gemini"
    assert status.model == "gemini-3.5-flash-lite"
    assert status.configured is True
    assert GeminiProvider().model == "gemini-3.5-flash-lite"
    assert parse_json_response('{"ok":true}') == {"ok": True}
    assert parse_json_response('```json\\n{"ok":true}\\n```') == {"ok": True}


def test_gemini_provider_requires_google_key_not_openai(monkeypatch):
    from core.ai_provider import AIProviderError, GeminiProvider, get_ai_status

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unused-openai-key")
    assert get_ai_status().configured is False
    try:
        GeminiProvider()
    except AIProviderError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("Gemini must require its own API key")


def test_application_profile_registry_loads_oap_meta():
    from core.application_profile import (
        get_profile_mapping_summary, list_application_profiles, load_application_profile,
    )

    assert "oap-meta" in {item["profile_id"] for item in list_application_profiles()}
    profile = load_application_profile("oap-meta")
    assert profile["authentication"]["session_probe"]["path"] == "/api/v1/auth/me"
    assert profile["pages"]["ccm.guarantee.list"]["path"].endswith("TRM_GUARANTEE_LIST")
    summary = get_profile_mapping_summary(profile)
    assert summary["verified_target_count"] == 0
    assert summary["verified_auth_target_count"] == 3
    assert summary["unmapped_page_count"] == 1
    assert summary["page_count"] == 1


def test_application_profile_never_guesses_unmapped_business_target():
    from core.action_registry import TargetNotMappedError, resolve_semantic_locator
    from core.application_profile import load_application_profile

    class FakePage:
        def locator(self, value):
            return ("css", value)

        def get_by_role(self, role, name=None, exact=True):
            return ("role", role, name, exact)

    profile = load_application_profile("oap-meta")
    locator = resolve_semantic_locator(FakePage(), profile, "auth.username")
    assert locator == ("css", "input[name='usernameOrEmail']")
    try:
        resolve_semantic_locator(FakePage(), profile, "guarantee.create_button", "ccm.guarantee.list")
    except TargetNotMappedError as exc:
        assert "chưa được khai báo" in str(exc)
    else:
        raise AssertionError("Unmapped business targets must not be guessed")


def test_semantic_test_steps_are_validated_without_css_selector():
    from core.test_generator import validate_steps_json

    steps = [
        {"action": "navigate", "page": "ccm.guarantee.list"},
        {"action": "click", "target": "guarantee.create_button"},
        {"action": "fill", "target": "guarantee.amount", "value": "${data.amount}"},
        {"action": "expect_text", "target": "guarantee.status", "expected": "DRAFT"},
    ]
    assert validate_steps_json(steps) == steps
    try:
        validate_steps_json([{"action": "fill", "value": "100"}])
    except ValueError as exc:
        assert "semantic target" in str(exc)
    else:
        raise AssertionError("Semantic fill without target must be rejected")


def test_gemini_requirement_extraction_assigns_internal_id_and_preserves_evidence(monkeypatch):
    import json
    import core.ai_generator as generator

    class FakeProvider:
        def generate_json(self, prompt, schema, max_output_tokens):
            return {"requirements": [{
                "req_key": "",
                "title": "Tạo đề xuất bảo lãnh",
                "description": "Người dùng có thể tạo đề xuất bảo lãnh.",
                "actor": "RM",
                "preconditions": ["Có quyền tạo"],
                "business_rules": ["Giá trị phải lớn hơn 0"],
                "acceptance_criteria": ["Sinh mã đề xuất"],
                "source_ref": "Mục 3.3",
            }]}

    monkeypatch.setattr(generator, "get_ai_provider", lambda: FakeProvider())
    result = generator.extract_requirements_with_ai("Yêu cầu tạo đề xuất bảo lãnh.", "BRD.docx")
    assert len(result) == 1
    assert result[0]["req_key"] == "REQ-001"
    metadata = json.loads(result[0]["metadata_json"])
    assert metadata["actor"] == "RM"
    assert metadata["source_ref"] == "Mục 3.3"


def test_gemini_test_design_uses_semantic_target_and_not_selector(monkeypatch):
    import core.ai_generator as generator

    class FakeProvider:
        def generate_json(self, prompt, schema, max_output_tokens):
            return {"test_cases": [{
                "req_key": "BG-REQ-01",
                "title": "Tạo đề xuất bảo lãnh hợp lệ",
                "test_type": "Positive",
                "priority": "High",
                "preconditions": "Người dùng có quyền tạo",
                "steps": [
                    {"action": "navigate", "page": "ccm.guarantee.list"},
                    {"action": "click", "target": "guarantee.create_button"},
                    {"action": "fill", "target": "guarantee.amount", "value": "${data.amount}"},
                    {"action": "expect_text", "target": "guarantee.status", "expected": "DRAFT"},
                ],
                "expected_result": "Đề xuất được lưu ở trạng thái DRAFT.",
                "source_ref": "Mục 3.3",
                "automation_level": "partially_automatable",
            }]}

    monkeypatch.setattr(generator, "get_ai_provider", lambda: FakeProvider())
    cases = generator.generate_cases_with_ai([{"req_key": "BG-REQ-01", "title": "Create guarantee"}])
    assert len(cases) == 1
    assert cases[0]["automation_level"] == "partially_automatable"
    assert cases[0]["steps"][1]["target"] == "guarantee.create_button"
    assert not any("selector" in step for step in cases[0]["steps"])


def test_sqlite_persists_structured_requirement_metadata_and_automation_level(tmp_path):
    import json
    from core.db import (
        init_db, create_project, save_requirements, list_requirements,
        add_test_cases, list_test_cases,
    )

    db_path = str(tmp_path / "autotest.sqlite3")
    init_db(db_path)
    project_id = create_project("Reusable profile test", "Test DB migrations", db_path=db_path)
    save_requirements(project_id, [{
        "req_key": "REQ-001",
        "title": "Create guarantee",
        "description": "User can create a guarantee draft",
        "source": "BRD.docx",
        "metadata_json": json.dumps({
            "actor": "RM",
            "business_rules": ["Amount must be positive"],
            "acceptance_criteria": ["Draft is created"],
            "source_ref": "Section 3.3",
        }),
    }], db_path=db_path)
    requirement = list_requirements(project_id, db_path=db_path)[0]
    assert json.loads(requirement["metadata_json"])["actor"] == "RM"
    add_test_cases(project_id, [{
        "case_key": "TC-001",
        "req_key": "REQ-001",
        "title": "Create valid draft",
        "steps": [{"action": "manual", "description": "Map UI target"}],
        "automation_level": "partially_automatable",
    }], db_path=db_path)
    case = list_test_cases(project_id, db_path=db_path)[0]
    assert case["automation_level"] == "partially_automatable"


def test_profile_authentication_reuses_existing_browser_context_session():
    from core.application_profile import load_application_profile
    from core.authentication import ensure_authenticated

    class FakeResponse:
        status = 200

    class FakeRequest:
        def get(self, url, timeout):
            assert url.endswith("/api/v1/auth/me")
            return FakeResponse()

    class FakeContext:
        request = FakeRequest()

        def new_page(self):
            raise AssertionError("Should not open the login page when the session is already valid")

    result = ensure_authenticated(
        FakeContext(),
        load_application_profile("oap-meta"),
        "https://oap-meta-staging.ovigroup.vn",
    )
    assert result["authenticated"] is True
    assert result["status"] == "ALREADY_AUTHENTICATED"


def test_profile_authentication_rejects_cross_origin_session_probe():
    from core.authentication import AuthenticationError, ensure_authenticated

    profile = {
        "authentication": {
            "strategy": "web_form",
            "login_path": "/login",
            "username_target": "auth.username",
            "password_target": "auth.password",
            "submit_target": "auth.submit",
            "session_probe": {"path": "//evil.example/auth/me", "success_status": 200},
        }
    }

    class FakeContext:
        pass

    try:
        ensure_authenticated(FakeContext(), profile, "https://oap-meta-staging.ovigroup.vn")
    except AuthenticationError as exc:
        assert "session_probe path" in str(exc)
    else:
        raise AssertionError("Cross-origin session probes must be rejected")


def test_execute_case_blocks_manual_level_and_assertion_free_cases():
    from core.browser_runner import execute_case, ManualStepRequired

    case_manual = {
        "case_key": "TC-MANUAL",
        "steps_json": json.dumps([{"action": "navigate", "page": "ccm.guarantee.list"}]),
        "automation_level": "manual",
    }
    try:
        execute_case(case_manual, object(), "https://example.test", application_profile={"pages": {}})
    except ManualStepRequired as exc:
        assert "thủ công" in str(exc)
    else:
        raise AssertionError("Manual cases must not execute or report PASS")

    case_no_assert = {
        "case_key": "TC-NO-ASSERT",
        "steps_json": json.dumps([{"action": "navigate", "page": "ccm.guarantee.list"}]),
        "automation_level": "automatable",
    }
    try:
        execute_case(case_no_assert, object(), "https://example.test", application_profile={"pages": {}})
    except ManualStepRequired as exc:
        assert "assertion" in str(exc)
    else:
        raise AssertionError("Assertion-free cases must not report PASS")


def test_gemini_downgrades_unverified_targets_and_assertion_free_cases(monkeypatch):
    import core.ai_generator as generator

    class FakeProvider:
        def generate_json(self, prompt, schema, max_output_tokens):
            return {"test_cases": [{
                "req_key": "REQ-01",
                "title": "Create guarantee",
                "test_type": "Positive",
                "priority": "High",
                "preconditions": "",
                "steps": [
                    {"action": "navigate", "page": "ccm.guarantee.list"},
                    {"action": "click", "target": "guarantee.create_button"},
                ],
                "expected_result": "A draft is created",
                "source_ref": "Section 3",
                "automation_level": "automatable",
            }]}

    monkeypatch.setattr(generator, "get_ai_provider", lambda: FakeProvider())
    profile = {
        "profile_id": "sample",
        "pages": {"ccm.guarantee.list": {"path": "/guarantee", "targets": {}}},
        "shared_targets": {},
    }
    cases = generator.generate_cases_with_ai(
        [{"req_key": "REQ-01", "title": "Create guarantee"}],
        application_profile=profile,
    )
    assert len(cases) == 1
    assert cases[0]["automation_level"] == "manual"
    assert any(step["action"] == "manual" for step in cases[0]["steps"])


def test_oap_meta_profile_requires_workspace_initialization_after_auth():
    from core.application_profile import load_application_profile

    profile = load_application_profile("oap-meta")
    readiness = profile["authentication"]["post_login_readiness"]["required_api"]
    assert readiness["path_contains"] == "/api/v1/auth/set-workspace"
    assert readiness["method"] == "POST"
    assert readiness["status"] == 200


def test_offline_case_generation_uses_stable_case_ids():
    from core.test_generator import generate_cases

    requirements = [{
        "req_key": "REQ-001",
        "title": "Create guarantee",
        "description": "User can create a guarantee draft",
    }]
    first = generate_cases(requirements)
    second = generate_cases(requirements)
    assert [case["case_key"] for case in first] == [case["case_key"] for case in second]
    assert len({case["case_key"] for case in first}) == len(first)
