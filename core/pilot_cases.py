from __future__ import annotations

from typing import Any


def risk_indicators_ui_smoke_case() -> dict[str, Any]:
    """Read-only pilot grounded in the OAP Meta Inspector evidence.

    It verifies only that the Guarantee list page renders the three summary
    labels observed on Staging. It deliberately does not claim to verify the
    85%/95% thresholds, expiry scheduler, notification delivery or APB rules.
    """
    return {
        "case_key": "TC-021BE33A-UI-01",
        "req_key": "BG-REQ-RISK-01",
        "title": "[BG-REQ-RISK-01] UI Smoke: Hiển thị 3 chỉ tiêu tổng quan rủi ro",
        "test_type": "UI",
        "priority": "High",
        "preconditions": (
            "Đã đăng nhập OAP Meta Staging bằng tài khoản kiểm thử; "
            "module CCM - Danh sách bảo lãnh được phép truy cập."
        ),
        "steps": [
            {
                "action": "navigate",
                "page": "ccm.guarantee.list",
                "timeout": 15000,
            },
            {
                "action": "expect_text",
                "expected": "Tổng bảo lãnh",
                "timeout": 10000,
            },
            {
                "action": "expect_text",
                "expected": "Đã bồi thường",
                "timeout": 10000,
            },
            {
                "action": "expect_text",
                "expected": "Sắp hết hạn",
                "timeout": 10000,
            },
        ],
        "expected_result": (
            "Màn hình Danh sách bảo lãnh hiển thị đầy đủ ba nhãn chỉ tiêu "
            "'Tổng bảo lãnh', 'Đã bồi thường' và 'Sắp hết hạn'. "
            "Đây là kiểm tra hiện diện UI chỉ đọc; KHÔNG xác nhận công thức "
            "85%/95%, lịch cảnh báo 30/15/7 ngày, thông báo Email/App hoặc "
            "điều kiện APB còn dư tạm ứng."
        ),
        "source_ref": (
            "BRD-CCM-GUARANTEE V1.0, BG-REQ-RISK-01, mục 8.1, trang 15; "
            "OAP Meta Staging Inspector evidence for CCM Guarantee list "
            "(observed summary labels: Tổng bảo lãnh / Đã bồi thường / Sắp hết hạn)."
        ),
        "automation_level": "automatable",
    }


def risk_rule_follow_up_cases() -> list[dict[str, Any]]:
    """Explicit manual cases for source rules not automatable from current evidence."""
    return [
        {
            "case_key": "TC-021BE33A-RISK-THRESHOLD",
            "req_key": "BG-REQ-RISK-01",
            "title": "[BG-REQ-RISK-01] Boundary: Cảnh báo vàng 85% và đỏ 95%",
            "test_type": "Boundary",
            "priority": "Critical",
            "preconditions": (
                "Có môi trường kiểm thử cho phép chuẩn bị hạn mức và tổng cam kết "
                "đang sử dụng theo các tỷ lệ kiểm soát."
            ),
            "steps": [
                {
                    "action": "manual",
                    "description": (
                        "Chuẩn bị các mức sử dụng 84.99%, 85%, 94.99%, 95% và trên 95%; "
                        "xác nhận mẫu số/tổng cam kết theo BRD; mở màn hình hiển thị "
                        "mức sử dụng và ghi nhận tag/cảnh báo tương ứng. Chưa tự động "
                        "hóa vì chưa có fixture/API chuẩn bị dữ liệu và selector/tag "
                        "cảnh báo được xác minh."
                    ),
                }
            ],
            "expected_result": (
                "Vàng từ 85%; Đỏ từ 95%; tỷ lệ dùng đúng mẫu số và tổng cam kết đang sử dụng."
            ),
            "source_ref": "BRD-CCM-GUARANTEE V1.0, BG-REQ-RISK-01, mục 8.1, trang 15.",
            "automation_level": "manual",
        },
        {
            "case_key": "TC-021BE33A-RISK-EXPIRY",
            "req_key": "BG-REQ-RISK-01",
            "title": "[BG-REQ-RISK-01] Functional: Cảnh báo đáo hạn Outward tại mốc 30/15/7 ngày",
            "test_type": "Risk",
            "priority": "Critical",
            "preconditions": (
                "Có Outward ACTIVE với expiry_date kiểm soát được; dịch vụ Email/App "
                "và job cảnh báo hoạt động trong môi trường Staging."
            ),
            "steps": [
                {
                    "action": "manual",
                    "description": (
                        "Chuẩn bị hồ sơ còn 31, 30, 15 và 7 ngày đến expiry_date; "
                        "kích hoạt job theo quy trình kiểm thử được phê duyệt; "
                        "đối chiếu nội dung, người nhận Treasury/Ban điều hành dự án "
                        "và kiểm tra không gửi sớm/muộn hoặc lặp ngoài chính sách. "
                        "Chưa tự động hóa vì chưa có API/fixture/job trigger và "
                        "bằng chứng xác định người nhận."
                    ),
                }
            ],
            "expected_result": (
                "Gửi cảnh báo đúng các mốc 30/15/7 ngày; không gửi sớm/muộn "
                "hoặc lặp ngoài chính sách."
            ),
            "source_ref": "BRD-CCM-GUARANTEE V1.0, BG-REQ-RISK-01, mục 8.1, trang 15.",
            "automation_level": "manual",
        },
        {
            "case_key": "TC-021BE33A-RISK-APB",
            "req_key": "BG-REQ-RISK-01",
            "title": "[BG-REQ-RISK-01] Risk: APB gần hết hạn còn dư tạm ứng chưa thu hồi",
            "test_type": "Risk",
            "priority": "Critical",
            "preconditions": (
                "Có APB gần hết hạn và dữ liệu dư nợ tạm ứng ERP có thể đối chiếu."
            ),
            "steps": [
                {
                    "action": "manual",
                    "description": (
                        "Chuẩn bị APB gần hết hạn với dư tạm ứng ERP còn tồn và một "
                        "hồ sơ đối chứng đã thu hồi hết; chạy quy trình cảnh báo được "
                        "phê duyệt và so sánh kết quả. Ngưỡng 'lớn' chưa được định nghĩa "
                        "trong mô tả yêu cầu nên không tự gán giá trị."
                    ),
                }
            ],
            "expected_result": (
                "Cảnh báo khi APB gần hết hạn đồng thời có dư tạm ứng chưa thu hồi "
                "đáp ứng ngưỡng cấu hình; giá trị ngưỡng 'lớn' cần được chủ nghiệp vụ xác nhận."
            ),
            "source_ref": "BRD-CCM-GUARANTEE V1.0, BG-REQ-RISK-01, mục 8.1, trang 15.",
            "automation_level": "manual",
        },
    ]
