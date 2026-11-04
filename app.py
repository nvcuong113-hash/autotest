from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from core.ai_generator import generate_cases_with_ai
from core.browser_runner import inspect_page, run_suite
from core.db import (add_test_cases, create_project, init_db, list_projects, list_requirements,
                    list_results, list_runs, list_test_cases, save_requirements, update_test_case)
from core.srs_parser import parse_srs
from core.test_generator import generate_cases, validate_steps_json
from core.suite_catalog import import_guarantee_suite, load_guarantee_suite

st.set_page_config(page_title="AutoTest | QA Platform", page_icon="🧪", layout="wide")
init_db()
Path("artifacts").mkdir(exist_ok=True)

st.markdown("""<style>
.block-container{padding-top:1.5rem;max-width:1500px}
.hero{padding:1.2rem 1.4rem;border:1px solid rgba(128,128,128,.25);border-radius:14px;margin-bottom:1rem}
.muted{color:#818891;font-size:.9rem}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🧪 AutoTest")
    st.caption("SRS-driven Web QA Platform")
    st.divider()
    projects = list_projects()
    names = [p["name"] for p in projects]
    selected_name = st.selectbox("Project", names, index=0 if names else None, placeholder="Create a project")
    with st.expander("＋ Create project", expanded=not projects):
        new_name = st.text_input("Project name", placeholder="e.g. OAP Meta Staging")
        new_desc = st.text_area("Description", placeholder="System and testing scope")
        if st.button("Create project", use_container_width=True):
            try:
                create_project(new_name, new_desc)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.divider()
    st.caption("Browser test configuration")
    base_url = st.text_input("Base URL", placeholder="https://staging.example.com")
    username = st.text_input("Test username", key="test_username")
    password = st.text_input("Test password", type="password", key="test_password")
    headless = st.checkbox("Run headless", value=True)
    st.caption("Credentials stay in session memory; they are not written to SQLite.")

if not projects:
    st.title("Welcome to AutoTest")
    st.write("Create a project to import an SRS, generate test cases and run browser tests.")
    st.stop()

project = next(p for p in projects if p["name"] == selected_name)
pid = int(project["id"])
requirements = list_requirements(pid)
cases = list_test_cases(pid)
results = list_results(pid)
runs = list_runs(pid)

st.markdown(f"""<div class="hero"><div class="muted">QUALITY ENGINEERING WORKSPACE</div>
<h1 style="margin:.2rem 0">{project['name']}</h1>
<div class="muted">Import SRS → review requirements → generate cases → execute → report.</div></div>""",
unsafe_allow_html=True)

passed = sum(r["status"] == "PASS" for r in results)
failed = sum(r["status"] == "FAIL" for r in results)
blocked = sum(r["status"] == "BLOCKED" for r in results)
m1,m2,m3,m4 = st.columns(4)
m1.metric("Requirements", len(requirements))
m2.metric("Test cases", len(cases))
m3.metric("Passed executions", passed)
m4.metric("Failed / blocked", f"{failed} / {blocked}")

tab_srs, tab_cases, tab_run, tab_report = st.tabs(
    ["📄 SRS & Requirements", "🧩 Test Cases", "▶ Execution", "📊 Reports"])

with tab_srs:
    st.subheader("Import SRS")
    st.caption("PDF, DOCX, XLSX, CSV, TXT, Markdown, RST, YAML and JSON.")
    upload = st.file_uploader("Upload specification", type=["pdf","docx","xlsx","xlsm","csv","txt","md","rst","yaml","yml","json"], key=f"upload_{pid}")
    if upload and st.button("Parse SRS and extract requirements", type="primary"):
        try:
            raw, extracted = parse_srs(upload.name, upload.getvalue())
            st.session_state["srs_raw"] = raw
            st.session_state["srs_items"] = extracted
            st.session_state["srs_name"] = upload.name
            st.success(f"Found {len(extracted)} candidate requirements. Review before saving.")
        except Exception as exc:
            st.error(f"Could not parse document: {exc}")
    extracted = st.session_state.get("srs_items", [])
    if extracted:
        st.write(f"Source: **{st.session_state.get('srs_name','Uploaded file')}**")
        edited = st.data_editor(pd.DataFrame(extracted), use_container_width=True, hide_index=True,
            num_rows="dynamic", key=f"req_editor_{pid}",
            column_config={
                "req_key": st.column_config.TextColumn("Requirement ID", required=True),
                "title": st.column_config.TextColumn("Title", required=True),
                "description": st.column_config.TextColumn("Description", width="large", required=True),
                "source": st.column_config.TextColumn("Source"),
            })
        if st.button("Save reviewed requirements", type="primary"):
            count = save_requirements(pid, edited.to_dict("records"))
            st.success(f"Saved {count} requirement records.")
            st.rerun()
        with st.expander("Preview extracted source text"):
            st.text(st.session_state.get("srs_raw", "")[:20000])
    st.divider()
    st.subheader("Saved requirement register")
    if requirements:
        st.dataframe(pd.DataFrame(requirements)[["req_key","title","description","source"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info("Upload an SRS to create the requirement register.")

with tab_cases:
    st.subheader("Generate test cases")
    with st.expander("Import curated suite: CCM — Bank Guarantee Management", expanded=False):
        suite_meta = load_guarantee_suite()
        st.write("Source: **" + suite_meta["source_version"] + "** · "
                 + str(len(suite_meta["requirements"])) + " requirement groups · "
                 + str(len(suite_meta["test_cases"])) + " test cases")
        st.caption("Các case được biên soạn theo BRD và đang để bước manual. Sau khi xác minh màn hình/selector, chỉnh bước JSON để Playwright thực thi.")
        if st.button("Import CCM Guarantee test suite", type="primary", key=f"import_guarantee_suite_{pid}"):
            try:
                imported = import_guarantee_suite(pid)
                st.success("Đã nạp " + str(imported["requirement_count"]) + " requirement và "
                           + str(imported["case_count"]) + " test case mới. Case đã có sẽ không bị nhân bản.")
                st.rerun()
            except Exception as exc:
                st.error("Không thể nạp bộ test: " + str(exc))
    if requirements:
        req_keys = [r["req_key"] for r in requirements]
        selected_req = st.multiselect("Requirements to cover", req_keys, default=req_keys)
        use_ai = st.checkbox("Use AI-assisted generation (optional)")
        ai_key = st.text_input("OpenAI API key", value=os.getenv("OPENAI_API_KEY",""), type="password") if use_ai else ""
        if st.button("Generate test cases", type="primary", disabled=not selected_req):
            selected = [r for r in requirements if r["req_key"] in selected_req]
            try:
                generated = generate_cases_with_ai(selected, ai_key) if use_ai else generate_cases(selected)
                count = add_test_cases(pid, generated)
                st.success(f"Added {count} new test case drafts.")
                st.rerun()
            except Exception as exc:
                st.error(f"Generation failed: {exc}")
    else:
        st.info("Save requirements before generating test cases.")
    st.divider()
    cases = list_test_cases(pid)
    st.subheader("Test case repository")
    if cases:
        st.dataframe(pd.DataFrame(cases)[["case_key","req_key","title","test_type","priority"]],
                     use_container_width=True, hide_index=True)
        key = st.selectbox("Edit test case", [c["case_key"] for c in cases])
        case = next(c for c in cases if c["case_key"] == key)
        kinds = ["Positive","Negative","Boundary","Authorization","Integration","UI","Functional","Performance"]
        priorities = ["Critical","High","Medium","Low"]
        with st.form(f"edit_{case['id']}"):
            title = st.text_input("Title", value=case["title"])
            col1,col2 = st.columns(2)
            kind = col1.selectbox("Type", kinds, index=kinds.index(case["test_type"]) if case["test_type"] in kinds else 6)
            priority = col2.selectbox("Priority", priorities, index=priorities.index(case["priority"]) if case["priority"] in priorities else 2)
            pre = st.text_area("Preconditions", value=case["preconditions"])
            expected = st.text_area("Expected result", value=case["expected_result"])
            st.caption("BRD traceability: " + (case.get("source_ref") or "Not specified"))
            try:
                steps_default = json.dumps(json.loads(case["steps_json"]), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                steps_default = case["steps_json"]
            steps = st.text_area("Browser steps (JSON)", value=steps_default, height=260)
            enabled = st.checkbox("Enabled", value=bool(case["enabled"]))
            if st.form_submit_button("Save test case"):
                try:
                    validate_steps_json(steps)
                    update_test_case(case["id"], {"title":title,"test_type":kind,"priority":priority,
                        "preconditions":pre,"expected_result":expected,"steps_json":steps,"enabled":int(enabled),"source_ref":case.get("source_ref","")})
                    st.success("Test case saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Invalid test case: {exc}")
    else:
        st.info("No test cases yet.")

with tab_run:
    st.subheader("Browser Inspector — read-only")
    with st.expander("Inspect staging page structure without logging in or submitting forms", expanded=True):
        inspect_url = st.text_input(
            "Inspection URL",
            placeholder="https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
            key=f"inspect_url_{pid}",
        )
        st.caption("Base URL in the sidebar must be the same host. Inspector only opens the page and reads its DOM; it does not click or submit.")
        if st.button("Inspect page and collect selectors", key=f"inspect_btn_{pid}", type="primary"):
            if not base_url.strip():
                st.error("Enter the site's origin in Base URL in the sidebar, e.g. https://oap-meta-staging.ovigroup.vn")
            elif not inspect_url.strip():
                st.error("Enter the full staging URL to inspect.")
            else:
                try:
                    with st.spinner("Opening page with Playwright and reading visible page structure..."):
                        st.session_state[f"inspection_{pid}"] = inspect_page(inspect_url, base_url, headless=True)
                except Exception as exc:
                    st.error(f"Page inspection failed: {type(exc).__name__}: {exc}")
        inspection = st.session_state.get(f"inspection_{pid}")
        if inspection:
            status_col, title_col = st.columns([1,3])
            status_col.metric("HTTP status", inspection.get("http_status") or "No response")
            title_col.metric("Page title", inspection.get("title") or "(empty)")
            st.caption("Final URL: " + inspection.get("final_url", ""))
            st.write("**Headings**")
            st.dataframe(pd.DataFrame(inspection.get("headings", [])), use_container_width=True, hide_index=True)
            st.write("**Input fields and suggested selectors**")
            st.dataframe(pd.DataFrame(inspection.get("inputs", [])), use_container_width=True, hide_index=True)
            st.write("**Buttons and suggested selectors**")
            st.dataframe(pd.DataFrame(inspection.get("buttons", [])), use_container_width=True, hide_index=True)
            st.write("**Forms**")
            st.dataframe(pd.DataFrame(inspection.get("forms", [])), use_container_width=True, hide_index=True)
            if inspection.get("screenshot_path") and Path(inspection["screenshot_path"]).exists():
                st.image(inspection["screenshot_path"], caption="Read-only page screenshot", use_container_width=True)
            st.download_button(
                "Download inspection JSON",
                json.dumps(inspection, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"page-inspection-{pid}.json",
                mime="application/json",
            )

    st.divider()
    st.subheader("Playwright browser execution")
    st.warning("Only test systems you are authorized to access. Review selectors and test data. Avoid destructive tests and production data.")
    enabled_cases = [c for c in list_test_cases(pid) if c["enabled"]]
    if enabled_cases:
        options = [c["case_key"] for c in enabled_cases]
        default = []
        for c in enabled_cases:
            try:
                if not any(s.get("action") == "manual" for s in json.loads(c["steps_json"])):
                    default.append(c["case_key"])
            except Exception:
                pass
        chosen = st.multiselect("Test cases to execute", options, default=default)
        st.caption("Cases with a manual placeholder are marked BLOCKED rather than executed with guessed selectors.")
        if st.button("▶ Run selected tests", type="primary", disabled=not chosen):
            if not base_url.strip():
                st.error("Enter Base URL in the sidebar.")
            else:
                selection = [c for c in enabled_cases if c["case_key"] in chosen]
                with st.spinner("Launching Chromium and running tests..."):
                    outcome = run_suite(pid, base_url.strip(), selection, username, password, headless)
                st.session_state["last_run"] = outcome
                st.rerun()
    else:
        st.info("No enabled test cases to run.")
    last = st.session_state.get("last_run")
    if last:
        st.markdown(f"**Latest run:** #{last['run_id']} — {last['status']}")
        st.dataframe(pd.DataFrame(last["results"]), use_container_width=True, hide_index=True)

with tab_report:
    st.subheader("Execution history")
    if runs:
        st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
    else:
        st.info("No runs recorded.")
    st.subheader("Detailed results")
    if results:
        df = pd.DataFrame(results)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download results CSV", df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"autotest-results-{pid}.csv", mime="text/csv")
    else:
        st.info("No results available.")
    if cases:
        df_cases = pd.DataFrame(cases)
        st.download_button("Download test cases CSV",
            df_cases.drop(columns=["steps_json"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
            file_name=f"autotest-cases-{pid}.csv", mime="text/csv")
        st.download_button("Download test cases JSON",
            df_cases.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8"),
            file_name=f"autotest-cases-{pid}.json", mime="application/json")

st.caption("AutoTest MVP · Review generated requirements and cases before relying on test results.")
