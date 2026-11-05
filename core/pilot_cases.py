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
