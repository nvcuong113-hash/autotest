from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import streamlit as st

# Show an immediate message before loading the rest of the application.
st.set_page_config(page_title="AutoTest | Nền tảng kiểm thử", page_icon="🧪", layout="wide")
_boot_message = st.empty()
_boot_message.info("AutoTest đang khởi tạo các thành phần...")
print("[AUTOTEST_BOOT] app.py started", flush=True)

try:
    import pandas as pd

    from core.ai_generator import extract_requirements_with_ai, generate_cases_with_ai
    from core.ai_provider import get_ai_status
    from core.application_profile import (
        get_profile_mapping_summary, list_application_profiles, load_application_profile,
    )
    from core.runner_client import inspect_page, run_suite
    from core.db import (
        add_test_cases, create_project, init_db, list_projects, list_requirements,
        list_results, list_runs, list_test_cases, save_requirements, update_test_case,
    )
    from core.srs_parser import parse_srs
    from core.test_generator import generate_cases, validate_steps_json
    from core.suite_catalog import import_guarantee_suite, load_guarantee_suite

    print("[AUTOTEST_BOOT] imports completed", flush=True)
    init_db()
    Path("artifacts").mkdir(exist_ok=True)
    if os.getenv("DATABASE_URL", "").strip() and not list_projects():
        _seed_project_id = create_project(
            "OAP Meta - CCM Bank Guarantee",
            "Kiểm thử module Bảo lãnh CCM OAP Meta; dữ liệu mẫu được nạp từ BRD-CCM-GUARANTEE V1.0.",
        )
        _seed_result = import_guarantee_suite(_seed_project_id)
        print(f"[AUTOTEST_BOOT] seeded default project and {_seed_result.get('case_count', 0)} test cases", flush=True)
    print("[AUTOTEST_BOOT] database initialized", flush=True)
except Exception as exc:
    print("[AUTOTEST_BOOT] startup failed: " + repr(exc), flush=True)
    _boot_message.error("AutoTest không thể khởi tạo. Chi tiết lỗi ở bên dưới:")
    st.code(traceback.format_exc(), language="python")
    st.stop()

_boot_message.empty()

st.markdown("""<style>
.block-container{padding-top:1.5rem;max-width:1500px}
.stApp,.stApp p,.stApp label,.stApp [data-testid="stMarkdownContainer"]{color:#17231f}
.stApp p,.stApp label,.stApp [data-testid="stCaptionContainer"]{font-weight:600}
h1,h2,h3,h4{color:#10251d !important;font-weight:850 !important;letter-spacing:-.25px}
.stCaption,[data-testid="stCaptionContainer"]{color:#46564f !important;font-weight:600 !important}
.hero{padding:1.35rem 1.5rem;border:1px solid #cbd8d1;border-bottom:4px solid #c6d5cc;border-radius:14px;margin-bottom:1rem;background:linear-gradient(180deg,#ffffff 0%,#f6faf7 100%);box-shadow:0 4px 12px rgba(20,50,35,.07)}
.muted{color:#43544b;font-size:.94rem;font-weight:650}
.metric-card{border:1px solid #c7d5cc;border-bottom:4px solid #9db4a5;border-radius:12px;padding:14px 16px;min-height:92px;background:linear-gradient(180deg,#ffffff 0%,#f1f7f3 100%);box-shadow:0 3px 0 rgba(20,70,45,.08),0 7px 15px rgba(20,55,35,.07)}
.metric-label{color:#34463d;font-size:.88rem;font-weight:750;margin-bottom:8px}
.metric-value{font-size:1.9rem;font-weight:850;line-height:1.1;color:#103d2c}
.stButton>button,.stDownloadButton>button{font-weight:800 !important;letter-spacing:.1px;border-radius:9px !important;transition:transform .12s ease,box-shadow .12s ease,filter .12s ease !important}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"]{color:#fff !important;background:linear-gradient(180deg,#15966b 0%,#08714e 100%) !important;border:1px solid #075b3f !important;border-bottom:4px solid #06452f !important;box-shadow:0 3px 0 rgba(4,65,43,.2),0 7px 14px rgba(8,95,65,.18) !important}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover{filter:brightness(1.06);transform:translateY(-1px);box-shadow:0 4px 0 rgba(4,65,43,.22),0 10px 18px rgba(8,95,65,.22) !important}
.stButton>button[kind="primary"]:active,.stDownloadButton>button[kind="primary"]:active{transform:translateY(2px);border-bottom-width:2px !important;box-shadow:0 1px 0 rgba(4,65,43,.2) !important}
.stButton>button:not([kind="primary"]),.stDownloadButton>button:not([kind="primary"]){color:#17382b !important;background:linear-gradient(180deg,#ffffff 0%,#edf4ef 100%) !important;border:1px solid #9eb6a6 !important;border-bottom:3px solid #829c8a !important;box-shadow:0 2px 0 rgba(35,70,48,.08),0 5px 10px rgba(35,70,48,.07) !important;font-weight:750 !important}
.stButton>button:not([kind="primary"]):hover,.stDownloadButton>button:not([kind="primary"]):hover{background:#e5f1e9 !important;transform:translateY(-1px)}
.stButton>button:focus-visible,.stDownloadButton>button:focus-visible{outline:3px solid #f0b429 !important;outline-offset:2px}
[data-testid="stTabs"] button{font-weight:750 !important;color:#263b31 !important}
[data-testid="stDataFrame"]{border:1px solid #bdccc2;border-radius:9px}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🧪 AutoTest")
    st.caption("Nền tảng kiểm thử tự động theo tài liệu SRS")
    st.divider()
    projects = list_projects()
    names = [p["name"] for p in projects]
    selected_name = st.selectbox("Dự án kiểm thử", names, index=0 if names else None, placeholder="Chọn hoặc tạo dự án")
    with st.expander("＋ Tạo dự án", expanded=not projects):
        new_name = st.text_input("Tên dự án", placeholder="Ví dụ: OAP Meta - CCM Bảo lãnh")
        new_desc = st.text_area("Mô tả", placeholder="Phạm vi hệ thống và nghiệp vụ cần kiểm thử")
        if st.button("Tạo dự án", use_container_width=True):
            try:
                create_project(new_name, new_desc)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.divider()
    if os.getenv("DATABASE_URL", "").strip():
        st.success("Cơ sở dữ liệu: PostgreSQL bền vững")
    else:
        st.warning("Đang dùng SQLite tạm trên Render Free. Dữ liệu có thể mất khi service restart; cần cấu hình DATABASE_URL.")
    if os.getenv("RUNNER_URL", "").strip() and os.getenv("RUNNER_API_TOKEN", ""):
        st.success("Browser Runner: đã cấu hình dịch vụ riêng")
    else:
        st.error("Browser Runner chưa được cấu hình. Không chạy Playwright trực tiếp trong Web Service 512 MB.")
    ai_status = get_ai_status()
    if ai_status.configured:
        st.success(f"AI: Gemini · {ai_status.model}")
    else:
        st.info("AI chưa cấu hình. Thêm GEMINI_API_KEY để bật Gemini; chức năng parser cục bộ vẫn dùng được.")
    profile_options = list_application_profiles()
    profile_ids = [item["profile_id"] for item in profile_options]
    if not profile_ids:
        st.error("Chưa có Application Profile nào trong application_profiles/.")
        st.stop()
    application_profile_id = st.selectbox(
        "Ứng dụng / Application Profile",
        profile_ids,
        index=profile_ids.index("oap-meta") if "oap-meta" in profile_ids else 0,
        format_func=lambda value: next(
            (item["name"] for item in profile_options if item["profile_id"] == value), value
        ),
        key="application_profile_id",
    )
    application_profile = load_application_profile(application_profile_id)
    mapping_summary = get_profile_mapping_summary(application_profile)
    st.caption(
        f"Profile v{application_profile.get('version', '1.0.0')} · "
        f"{mapping_summary['page_count']} màn hình · "
        f"{mapping_summary['verified_target_count']} target đã xác minh"
    )
    st.caption("Cấu hình kiểm thử trình duyệt")
    base_url = st.text_input(
        "Địa chỉ hệ thống (Base URL)",
        value=str(application_profile.get("default_base_url") or ""),
        placeholder="https://staging.example.com",
        key=f"base_url_{application_profile_id}",
    )
    username = st.text_input("Tài khoản kiểm thử", key="test_username")
    password = st.text_input("Mật khẩu kiểm thử", type="password", key="test_password")
    headless = st.checkbox("Chạy trình duyệt ẩn", value=True)
    st.caption("Thông tin đăng nhập chỉ lưu trong phiên làm việc, không ghi vào cơ sở dữ liệu.")

if not projects:
    st.title("Chào mừng đến với AutoTest")
    st.write("Tạo dự án để nhập tài liệu SRS, sinh kịch bản kiểm thử và chạy kiểm thử trình duyệt.")
    st.stop()

project = next(p for p in projects if p["name"] == selected_name)
pid = int(project["id"])
requirements = list_requirements(pid)
cases = list_test_cases(pid)
results = list_results(pid)
runs = list_runs(pid)

st.markdown(f"""<div class="hero"><div class="muted">KHÔNG GIAN KIỂM THỬ CHẤT LƯỢNG</div>
<h1 style="margin:.2rem 0">{project['name']}</h1>
<div class="muted">Nhập SRS → rà soát yêu cầu → tạo Test Case → thực thi → lập báo cáo.</div></div>""",
unsafe_allow_html=True)

passed = sum(r["status"] == "PASS" for r in results)
failed = sum(r["status"] == "FAIL" for r in results)
blocked = sum(r["status"] == "BLOCKED" for r in results)
# Thẻ thống kê HTML tĩnh: tránh lỗi tải module frontend của st.metric sau khi redeploy.
metric_cols = st.columns(4)
metric_items = [
    ("Yêu cầu nghiệp vụ", len(requirements)),
    ("Test Case", len(cases)),
    ("Lượt kiểm thử đạt", passed),
    ("Lỗi / Bị chặn", f"{failed} / {blocked}"),
]
for col, (label, value) in zip(metric_cols, metric_items):
    with col:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div></div>',
            unsafe_allow_html=True,
        )

tab_srs, tab_cases, tab_run, tab_report = st.tabs(
    ["📄 Tài liệu & Yêu cầu", "🧩 Bộ Test Case", "▶ Thực thi", "📊 Báo cáo"])

with tab_srs:
    st.subheader("Nhập tài liệu SRS")
    st.caption("Định dạng hỗ trợ: PDF, DOCX, XLSX, CSV, TXT, Markdown, RST, YAML và JSON.")
    upload = st.file_uploader("Tải lên tài liệu đặc tả", type=["pdf","docx","xlsx","xlsm","csv","txt","md","rst","yaml","yml","json"], key=f"upload_{pid}")
    use_gemini_srs = st.checkbox(
        f"Phân tích ngữ nghĩa bằng Gemini 3.5 Flash-Lite ({ai_status.model})",
        value=ai_status.configured,
        disabled=not ai_status.configured,
        key=f"gemini_srs_{pid}",
    )
    if upload and st.button("Phân tích SRS và trích xuất yêu cầu", type="primary"):
        try:
            raw, local_extracted = parse_srs(upload.name, upload.getvalue())
            extracted = (
                extract_requirements_with_ai(raw, upload.name)
                if use_gemini_srs else local_extracted
            )
            st.session_state["srs_raw"] = raw
            st.session_state["srs_items"] = extracted
            st.session_state["srs_name"] = upload.name
            method = "Gemini" if use_gemini_srs else "parser cục bộ"
            st.success(f"Đã nhận diện {len(extracted)} yêu cầu bằng {method}. Vui lòng rà soát trước khi lưu.")
        except Exception as exc:
            st.error(f"Không thể đọc tài liệu: {exc}")
    extracted = st.session_state.get("srs_items", [])
    if extracted:
        st.write(f"**Tài liệu nguồn:** {st.session_state.get('srs_name','Tệp đã tải lên')}")
        edited = st.data_editor(pd.DataFrame(extracted), use_container_width=True, hide_index=True,
            num_rows="dynamic", key=f"req_editor_{pid}",
            column_config={
                "req_key": st.column_config.TextColumn("Mã yêu cầu", required=True),
                "title": st.column_config.TextColumn("Tên yêu cầu", required=True),
                "description": st.column_config.TextColumn("Mô tả yêu cầu", width="large", required=True),
                "source": st.column_config.TextColumn("Nguồn"),
            })
        if st.button("Lưu danh sách yêu cầu đã rà soát", type="primary"):
            count = save_requirements(pid, edited.to_dict("records"))
            st.success(f"Đã lưu {count} yêu cầu.")
            st.rerun()
        with st.expander("Xem trước nội dung văn bản đã trích xuất"):
            st.text(st.session_state.get("srs_raw", "")[:20000])
    st.divider()
    st.subheader("Danh sách yêu cầu đã lưu")
    if requirements:
        req_view = pd.DataFrame(requirements)[["req_key","title","description","source"]].rename(
            columns={"req_key":"Mã yêu cầu","title":"Tên yêu cầu",
                     "description":"Mô tả yêu cầu","source":"Tài liệu nguồn"})
        st.dataframe(req_view, use_container_width=True, hide_index=True)
        with st.expander("Chi tiết phân tích yêu cầu: Actor, điều kiện, Business Rules và Acceptance Criteria"):
            for requirement in requirements:
                try:
                    metadata = json.loads(requirement.get("metadata_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if not isinstance(metadata, dict) or not metadata:
                    continue
                st.markdown("**" + str(requirement["req_key"]) + " — " + str(requirement["title"]) + "**")
                if metadata.get("actor"):
                    st.write("Actor:", metadata["actor"])
                if metadata.get("preconditions"):
                    st.write("Điều kiện tiên quyết:", " · ".join(map(str, metadata["preconditions"])))
                if metadata.get("business_rules"):
                    st.write("Business Rules:")
                    for rule in metadata["business_rules"]:
                        st.markdown("- " + str(rule))
                if metadata.get("acceptance_criteria"):
                    st.write("Acceptance Criteria:")
                    for criterion in metadata["acceptance_criteria"]:
                        st.markdown("- " + str(criterion))
                if metadata.get("source_ref"):
                    st.caption("Tham chiếu nguồn: " + str(metadata["source_ref"]))
                st.divider()
    else:
        st.info("Tải tài liệu SRS lên để tạo danh sách yêu cầu nghiệp vụ.")

with tab_cases:
    st.subheader("Tạo Test Case")
    with st.expander("Nạp bộ kiểm thử mẫu: CCM — Quản lý Bảo lãnh ngân hàng", expanded=False):
        suite_meta = load_guarantee_suite()
        st.write("Nguồn đặc tả: **" + suite_meta["source_version"] + "** · "
                 + str(len(suite_meta["requirements"])) + " nhóm yêu cầu · "
                 + str(len(suite_meta["test_cases"])) + " Test Case")
        st.caption("Các Test Case được biên soạn theo BRD. Bước thao tác đang để thủ công cho đến khi xác minh giao diện và selector.")
        if st.button("Nạp 75 Test Case bảo lãnh", type="primary", key=f"import_guarantee_suite_{pid}"):
            try:
                imported = import_guarantee_suite(pid)
                st.success("Đã nạp " + str(imported["requirement_count"]) + " nhóm yêu cầu và "
                           + str(imported["case_count"]) + " Test Case mới. Các case đã tồn tại không bị nhân bản.")
                st.rerun()
            except Exception as exc:
                st.error("Không thể nạp bộ Test Case: " + str(exc))
    if requirements:
        req_keys = [r["req_key"] for r in requirements]
        selected_req = st.multiselect("Chọn các yêu cầu cần tạo Test Case", req_keys, default=req_keys)
        use_ai = st.checkbox(
            f"Dùng Gemini 3.5 Flash-Lite ({ai_status.model}) để thiết kế Test Case",
            value=ai_status.configured,
            disabled=not ai_status.configured,
            key=f"gemini_testcases_{pid}",
        )
        if not ai_status.configured:
            st.caption("Muốn dùng AI: cấu hình GEMINI_API_KEY trong Render Environment. Không cần OpenAI API key.")
        if st.button("Sinh Test Case", type="primary", disabled=not selected_req):
            selected = [r for r in requirements if r["req_key"] in selected_req]
            try:
                generated = generate_cases_with_ai(selected) if use_ai else generate_cases(selected)
                count = add_test_cases(pid, generated)
                st.success(f"Đã tạo thêm {count} Test Case. Hãy rà soát mức tự động hóa và mapping target trước khi chạy.")
                st.rerun()
            except Exception as exc:
                st.error(f"Không thể tạo Test Case: {exc}")
    else:
        st.info("Hãy lưu danh sách yêu cầu trước khi tạo Test Case.")
    st.divider()
    cases = list_test_cases(pid)
    st.subheader("Danh mục Test Case")
    if cases:
        case_columns = ["case_key","req_key","title","test_type","priority","automation_level"]
        case_view = pd.DataFrame(cases)[case_columns].rename(
            columns={"case_key":"Mã Test Case","req_key":"Mã yêu cầu","title":"Tên Test Case",
                     "test_type":"Loại kiểm thử","priority":"Mức ưu tiên",
                     "automation_level":"Mức tự động hóa"})
        type_labels = {"Positive":"Tích cực","Negative":"Tiêu cực","Boundary":"Kiểm thử biên",
                       "Authorization":"Phân quyền","Integration":"Tích hợp","UI":"Giao diện",
                       "Functional":"Chức năng","Performance":"Hiệu năng"}
        priority_labels = {"Critical":"Nghiêm trọng","High":"Cao","Medium":"Trung bình","Low":"Thấp"}
        case_view["Loại kiểm thử"] = case_view["Loại kiểm thử"].map(lambda v: type_labels.get(v, v))
        case_view["Mức ưu tiên"] = case_view["Mức ưu tiên"].map(lambda v: priority_labels.get(v, v))
        automation_labels = {
            "automatable": "Tự động",
            "partially_automatable": "Một phần",
            "manual": "Thủ công",
        }
        case_view["Mức tự động hóa"] = case_view["Mức tự động hóa"].map(
            lambda value: automation_labels.get(value, value)
        )
        st.dataframe(case_view, use_container_width=True, hide_index=True)
        key = st.selectbox("Chọn Test Case cần chỉnh sửa", [c["case_key"] for c in cases])
        case = next(c for c in cases if c["case_key"] == key)
        kinds = ["Positive","Negative","Boundary","Authorization","Integration","UI","Functional","Performance"]
        priorities = ["Critical","High","Medium","Low"]
        with st.form(f"edit_{case['id']}"):
            title = st.text_input("Tên Test Case", value=case["title"])
            col1,col2 = st.columns(2)
            kind = col1.selectbox("Loại kiểm thử", kinds, index=kinds.index(case["test_type"]) if case["test_type"] in kinds else 6, format_func=lambda v: {"Positive":"Tích cực","Negative":"Tiêu cực","Boundary":"Kiểm thử biên","Authorization":"Phân quyền","Integration":"Tích hợp","UI":"Giao diện","Functional":"Chức năng","Performance":"Hiệu năng"}.get(v, v))
            priority = col2.selectbox("Mức ưu tiên", priorities, index=priorities.index(case["priority"]) if case["priority"] in priorities else 2, format_func=lambda v: {"Critical":"Nghiêm trọng","High":"Cao","Medium":"Trung bình","Low":"Thấp"}.get(v, v))
            automation_levels = ["automatable", "partially_automatable", "manual"]
            automation_labels = {
                "automatable": "Có thể tự động hóa",
                "partially_automatable": "Tự động hóa một phần",
                "manual": "Thủ công / cần mapping",
            }
            current_level = case.get("automation_level") or "manual"
            automation_level = st.selectbox(
                "Mức tự động hóa",
                automation_levels,
                index=automation_levels.index(current_level) if current_level in automation_levels else 2,
                format_func=lambda value: automation_labels[value],
            )
            pre = st.text_area("Điều kiện tiên quyết", value=case["preconditions"])
            expected = st.text_area("Kết quả mong đợi", value=case["expected_result"])
            st.caption("Tham chiếu BRD: " + (case.get("source_ref") or "Chưa xác định"))
            try:
                steps_default = json.dumps(json.loads(case["steps_json"]), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                steps_default = case["steps_json"]
            steps = st.text_area("Các bước kiểm thử trên trình duyệt (JSON)", value=steps_default, height=260)
            enabled = st.checkbox("Cho phép thực thi", value=bool(case["enabled"]))
            if st.form_submit_button("Lưu Test Case"):
                try:
                    validate_steps_json(steps)
                    update_test_case(case["id"], {"title":title,"test_type":kind,"priority":priority,
                        "preconditions":pre,"expected_result":expected,"steps_json":steps,"automation_level":automation_level,"enabled":int(enabled),"source_ref":case.get("source_ref","")})
                    st.success("Đã lưu Test Case.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Test Case không hợp lệ: {exc}")
    else:
        st.info("Chưa có Test Case. Hãy nạp bộ kiểm thử bảo lãnh hoặc tạo từ danh sách yêu cầu.")

with tab_run:
    runner_configured = bool(os.getenv("RUNNER_URL", "").strip() and os.getenv("RUNNER_API_TOKEN", ""))
    st.subheader("Kiểm tra giao diện hệ thống (chỉ đọc)")
    with st.expander("Đọc cấu trúc màn hình Staging (chỉ đăng nhập nếu bật tùy chọn)", expanded=True):
        inspect_url = st.text_input(
            "Địa chỉ màn hình cần kiểm tra",
            placeholder="https://oap-meta-staging.ovigroup.vn/app/OVI_SUITE/ccm/TRM_GUARANTEE_LIST",
            key=f"inspect_url_{pid}",
        )
        st.caption("Công cụ chỉ làm việc trong tên miền Base URL. Khi bật đăng nhập, tài khoản sẽ được dùng để điền form đăng nhập OAP Meta; không lưu vào SQLite và không ghi ra log.")
        use_credentials_for_login = st.checkbox("Đăng nhập OAP Meta bằng tài khoản kiểm thử ở thanh bên", value=False, key=f"inspect_login_{pid}")
        if st.button("Kiểm tra màn hình và thu thập selector", key=f"inspect_btn_{pid}", type="primary", disabled=not runner_configured):
            if not base_url.strip():
                st.error("Nhập địa chỉ gốc của hệ thống ở thanh bên, ví dụ https://oap-meta-staging.ovigroup.vn")
            elif not inspect_url.strip():
                st.error("Nhập đầy đủ URL màn hình Staging cần kiểm tra.")
            elif use_credentials_for_login and (not username.strip() or not password):
                st.error("Đã bật đăng nhập nhưng chưa nhập đủ tài khoản và mật khẩu kiểm thử ở thanh bên.")
            else:
                try:
                    with st.spinner("Đang mở OAP Meta, kiểm tra xác thực và đọc cấu trúc giao diện..."):
                        st.session_state[f"inspection_{pid}"] = inspect_page(
                            inspect_url, base_url, headless=True,
                            username=username, password=password,
                            authenticate=use_credentials_for_login,
                        )
                except Exception as exc:
                    st.error(f"Không thể kiểm tra màn hình: {type(exc).__name__}: {exc}")
        inspection = st.session_state.get(f"inspection_{pid}")
        if inspection:
            status_col, title_col = st.columns([1,3])
            status_col.write("**Mã phản hồi HTTP:** " + str(inspection.get("http_status") or "Không có phản hồi"))
            title_col.write("**Tiêu đề trang:** " + str(inspection.get("title") or "(trống)"))
            st.caption("URL cuối cùng: " + inspection.get("final_url", ""))
            if inspection.get("authentication_required"):
                st.error("OAP Meta yêu cầu đăng nhập. Inspector đã phát hiện chuyển hướng tới trang Login hoặc API xác thực trả 401. Chưa thể kiểm tra màn hình Bảo lãnh cho đến khi có phiên đăng nhập hợp lệ.")
            elif inspection.get("authentication_pending"):
                st.warning("OAP Meta vẫn đang kiểm tra xác thực. Chờ hệ thống hoàn tất xác thực trước khi đọc màn hình nghiệp vụ.")
            st.caption("Trạng thái xác thực: " + str(inspection.get("authentication_state", "UNKNOWN")))
            login_result = inspection.get("login_diagnostic", {}).get("result", "NOT_REQUESTED")
            if login_result == "AUTHENTICATED":
                st.success("Đăng nhập OAP Meta thành công. Phiên đã được xác nhận bằng API /auth/me.")
                page_readiness = inspection.get("business_page_readiness", {})
                if inspection.get("business_page_ready"):
                    st.success("Màn hình nghiệp vụ đã tải xong và DOM ổn định.")
                else:
                    st.warning(
                        "Đăng nhập thành công nhưng nội dung module chưa tải xong hoặc chưa nhận diện được. "
                        "Trạng thái: " + str(page_readiness.get("state", "UNKNOWN"))
                    )
                    st.caption(
                        "Bảng: " + str(page_readiness.get("table_count", 0))
                        + " · Dòng dữ liệu: " + str(page_readiness.get("data_row_count", 0))
                        + " · Loading indicator: " + str(page_readiness.get("loading_indicator_count", 0))
                    )
            elif login_result == "MFA_REQUIRED":
                st.warning("OAP Meta yêu cầu thêm OTP hoặc xác thực nhiều lớp. Inspector chưa tự xử lý bước này.")
            elif login_result == "LOGIN_REJECTED":
                st.error("OAP Meta đã từ chối thông tin đăng nhập. Xem phản hồi API đăng nhập bên dưới để biết nguyên nhân.")
            elif login_result == "LOGIN_NOT_CONFIRMED":
                st.error("Đã gửi form đăng nhập nhưng chưa xác nhận được phiên đăng nhập. Xem phản hồi API và trạng thái /auth/me bên dưới.")
            elif login_result == "LOGIN_FORM_NOT_FOUND":
                st.error("Không tìm thấy đầy đủ trường Tên đăng nhập, Mật khẩu và nút Đăng nhập trong trang hiện tại.")
            elif login_result == "MISSING_CREDENTIALS":
                st.warning("Chưa nhập đủ thông tin tài khoản kiểm thử.")
            elif login_result == "NOT_REQUESTED":
                st.info("Chưa bật tùy chọn đăng nhập. Inspector chỉ đọc trang hiện tại và chưa gửi form đăng nhập.")
            elif login_result == "LOGIN_PAGE_READY":
                st.info("Đã mở trang đăng nhập OAP Meta và tìm thấy form. Chưa gửi thông tin đăng nhập.")
            elif login_result == "LOGIN_FORM_NOT_READY":
                st.error("Đã mở trang /login nhưng chưa tìm thấy đầy đủ trường đăng nhập sau thời gian chờ.")
            elif login_result == "LOGIN_ROUTE_NAVIGATION_FAILED":
                st.error("Không mở được đường dẫn /login của OAP Meta: " + str(inspection.get("login_diagnostic", {}).get("error_type", "Lỗi điều hướng")))
            elif login_result == "SUBMISSION_ERROR":
                st.error("Không thể gửi form đăng nhập: " + str(inspection.get("login_diagnostic", {}).get("error_type", "Lỗi trình duyệt")))
            login_diag = inspection.get("login_diagnostic", {})
            login_response = login_diag.get("login_api_response", {})
            if login_diag.get("login_api_status") is not None or login_response:
                with st.expander("Phản hồi API đăng nhập (đã ẩn thông tin nhạy cảm)", expanded=True):
                    st.write("HTTP đăng nhập:", login_diag.get("login_api_status", "Không ghi nhận"))
                    st.write("HTTP /auth/me gần nhất:", inspection.get("auth_me_latest_status", "Chưa có"))
                    if login_response.get("message"):
                        st.warning(str(login_response["message"]))
                    if login_response.get("success") is not None:
                        st.write("API success:", login_response["success"])
                    if login_response.get("code") or login_response.get("error_code"):
                        st.write("Mã lỗi:", login_response.get("error_code", login_response.get("code")))
                    st.caption("Các trường response: " + ", ".join(login_response.get("response_keys", [])))
                    storage = login_diag.get("storage_metadata", {})
                    if storage:
                        st.caption("Local storage keys: " + ", ".join(storage.get("local_storage_keys", [])))
                        st.caption("Session storage keys: " + ", ".join(storage.get("session_storage_keys", [])))
                    if login_diag.get("cookie_names"):
                        st.caption("Cookie names: " + ", ".join(login_diag["cookie_names"]))
            st.caption("Trạng thái tài liệu: " + str(inspection.get("ready_state", "unknown")))
            frame_rows = inspection.get("frame_diagnostics", [])
            if frame_rows:
                with st.expander("Các frame / vùng đăng nhập nhúng", expanded=True):
                    for frame in frame_rows:
                        st.markdown("**Frame " + str(frame.get("frame_index", "")) + "** · " + str(frame.get("url", "")))
                        if frame.get("inspection_error"):
                            st.caption(frame["inspection_error"])
                        if frame.get("body_text_preview"):
                            st.text(frame["body_text_preview"])
                        if frame.get("inputs"):
                            st.write("Trường nhập trong frame")
                            st.dataframe(pd.DataFrame(frame["inputs"]).rename(columns={"index":"STT","tag":"Thẻ","type":"Kiểu","id":"ID","name":"Tên","placeholder":"Gợi ý nhập","aria_label":"Nhãn","disabled":"Vô hiệu hóa"}), use_container_width=True, hide_index=True)
                        if frame.get("buttons"):
                            st.write("Nút trong frame")
                            st.dataframe(pd.DataFrame(frame["buttons"]).rename(columns={"index":"STT","text":"Nội dung nút","aria_label":"Nhãn","type":"Kiểu"}), use_container_width=True, hide_index=True)
            api_rows = inspection.get("api_responses", [])
            api_failures = [item for item in api_rows if int(item.get("status", 0) or 0) >= 400]
            if api_failures:
                st.warning("Có " + str(len(api_failures)) + " API/XHR trả HTTP 4xx/5xx. Mở bảng request bên dưới để xác định endpoint lỗi.")
            if api_rows:
                with st.expander("Các request API/XHR của OAP Meta", expanded=True):
                    api_view = pd.DataFrame(api_rows).rename(columns={"url":"Địa chỉ API","status":"HTTP","resource_type":"Loại","method":"Phương thức"})
                    st.dataframe(api_view, use_container_width=True, hide_index=True)
            blocked_static = inspection.get("blocked_static_resources", [])
            if blocked_static:
                counts = {}
                for item in blocked_static:
                    kind = str(item.get("resource_type", "other"))
                    counts[kind] = counts.get(kind, 0) + 1
                st.caption(
                    "Đã bỏ qua có chủ đích tài nguyên tĩnh để tiết kiệm RAM: "
                    + ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
                    + ". Đây không được tính là lỗi API."
                )
            failed_rows = inspection.get("failed_requests", [])
            if failed_rows:
                with st.expander("Các request không tải được", expanded=True):
                    failed_view = pd.DataFrame(failed_rows).rename(columns={"url":"Địa chỉ","method":"Phương thức","resource_type":"Loại","failure":"Nguyên nhân"})
                    st.dataframe(failed_view, use_container_width=True, hide_index=True)
            js_errors = inspection.get("console_errors", []) + inspection.get("page_errors", [])
            if js_errors:
                with st.expander("Lỗi JavaScript trên trang", expanded=False):
                    for item in js_errors:
                        st.code(item)
            if inspection.get("navigation_errors"):
                with st.expander("Chi tiết điều hướng cần lưu ý", expanded=False):
                    for item in inspection["navigation_errors"]:
                        st.caption(item)
            if inspection.get("body_text_preview"):
                with st.expander("Nội dung văn bản đầu trang", expanded=False):
                    st.text(inspection["body_text_preview"])
            st.write("**Tiêu đề trên màn hình**")
            st.dataframe(pd.DataFrame(inspection.get("headings", [])).rename(columns={"level":"Cấp tiêu đề","text":"Nội dung"}), use_container_width=True, hide_index=True)
            st.write("**Trường nhập liệu và selector đề xuất**")
            st.dataframe(pd.DataFrame(inspection.get("inputs", [])).rename(columns={"index":"STT","tag":"Thẻ HTML","type":"Kiểu trường","id":"ID","name":"Tên trường","placeholder":"Gợi ý nhập","aria_label":"Nhãn truy cập","labels":"Nhãn liên kết","required":"Bắt buộc","disabled":"Vô hiệu hóa","suggested_selector":"Selector đề xuất"}), use_container_width=True, hide_index=True)
            st.write("**Nút bấm và selector đề xuất**")
            st.dataframe(pd.DataFrame(inspection.get("buttons", [])).rename(columns={"index":"STT","tag":"Thẻ HTML","text":"Nội dung nút","aria_label":"Nhãn truy cập","title":"Tiêu đề","type":"Kiểu nút","disabled":"Vô hiệu hóa","suggested_selector":"Selector đề xuất"}), use_container_width=True, hide_index=True)
            st.write("**Biểu mẫu**")
            st.dataframe(pd.DataFrame(inspection.get("forms", [])).rename(columns={"index":"STT","method":"Phương thức","action":"Địa chỉ gửi","id":"ID","name":"Tên biểu mẫu"}), use_container_width=True, hide_index=True)
            if inspection.get("screenshot_path") and Path(inspection["screenshot_path"]).exists():
                st.image(inspection["screenshot_path"], caption="Ảnh chụp màn hình (chế độ chỉ đọc)", use_container_width=True)
            st.download_button(
                "Tải tệp JSON kết quả kiểm tra",
                json.dumps(inspection, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"page-inspection-{pid}.json",
                mime="application/json",
            )

    st.divider()
    st.subheader("Thực thi kiểm thử tự động bằng Playwright")
    st.warning("Chỉ kiểm thử hệ thống được phép truy cập. Hãy rà soát selector và dữ liệu test; không chạy thao tác phá hủy hoặc dùng dữ liệu production.")
    enabled_cases = [c for c in list_test_cases(pid) if c["enabled"]]
    if enabled_cases:
        options = [c["case_key"] for c in enabled_cases]
        default = []
        for c in enabled_cases:
            try:
                steps = json.loads(c["steps_json"])
                if c.get("automation_level") == "automatable" and not any(
                    step.get("action") == "manual" for step in steps
                ):
                    default.append(c["case_key"])
            except Exception:
                pass
        chosen = st.multiselect("Chọn Test Case cần thực thi (tối đa 5 mỗi lượt)", options, default=default[:5], max_selections=5)
        st.caption("Test Case còn bước thủ công sẽ được đánh dấu BỊ CHẶN, không tự chạy bằng selector phỏng đoán.")
        if st.button("▶ Chạy các Test Case đã chọn", type="primary", disabled=(not chosen or not runner_configured)):
            if not base_url.strip():
                st.error("Nhập địa chỉ hệ thống (Base URL) ở thanh bên.")
            else:
                selection = [c for c in enabled_cases if c["case_key"] in chosen]
                with st.spinner("Đang khởi chạy Chromium và thực thi kiểm thử..."):
                    outcome = run_suite(
                        pid, base_url.strip(), selection, username, password, headless,
                        application_profile_id=application_profile_id,
                    )
                st.session_state["last_run"] = outcome
                st.rerun()
    else:
        st.info("Không có Test Case nào đang được bật để thực thi.")
    last = st.session_state.get("last_run")
    if last:
        st.markdown(f"**Lần chạy gần nhất:** #{last['run_id']} — {last['status']}")
        st.dataframe(pd.DataFrame(last["results"]), use_container_width=True, hide_index=True)

with tab_report:
    st.subheader("Lịch sử thực thi")
    if runs:
        st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có lịch sử thực thi.")
    st.subheader("Kết quả chi tiết")
    if results:
        df = pd.DataFrame(results)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Tải kết quả kiểm thử (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"autotest-results-{pid}.csv", mime="text/csv")
    else:
        st.info("Chưa có kết quả kiểm thử.")
    if cases:
        df_cases = pd.DataFrame(cases)
        st.download_button("Tải danh sách Test Case (CSV)",
            df_cases.drop(columns=["steps_json"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
            file_name=f"autotest-cases-{pid}.csv", mime="text/csv")
        st.download_button("Tải danh sách Test Case (JSON)",
            df_cases.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8"),
            file_name=f"autotest-cases-{pid}.json", mime="application/json")

st.caption("AutoTest MVP · Rà soát yêu cầu và Test Case trước khi sử dụng kết quả kiểm thử.")
