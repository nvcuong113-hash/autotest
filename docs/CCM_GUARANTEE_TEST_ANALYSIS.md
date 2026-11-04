# Test Design — CCM Bank Guarantee Management

Nguồn chuẩn: **BRD-CCM-GUARANTEE V1.0**, Release 1.0 (Outward & Inward BG), ngày 22/09/2026.

## 1. Coverage model

Test suite gồm **75 test case** liên kết với 10 requirement group:
- Outward Guarantee: tạo hồ sơ, master data, validation, hạn mức, ký quỹ, trạng thái/phê duyệt, file đề nghị và scan thư phát hành.
- Amendment: tăng/giảm giá trị, gia hạn, thay đổi nội dung, phí, tài liệu và bút toán chênh lệch.
- Settlement: loại tất toán, chứng từ ERP, giải phóng bảo lãnh/ký quỹ, thu hồi bản gốc, trạng thái SETTLING/SETTLED và các trigger theo từng loại bảo lãnh.
- Inward: tiếp nhận, xác thực, ACTIVE, cảnh báo, claim/thu tiền bồi thường, hoàn trả thư gốc.
- GL: BG_ISSUE_OUT, BG_MARGIN_LOCK, BG_FEE_EXPENSE, BG_AMEND_INC, BG_AMEND_DEC, BG_SETTLE_CLOSE, BG_MARGIN_REFUND.
- Risk & Reports: expiry alerts, APB outstanding alert, utilization thresholds 85%/95%, issuance portfolio, inward portfolio, margin reconciliation.

## 2. Source workflow and UI evidence

Sơ đồ quy trình trang 2 mô tả swimlane của Phòng Kinh tế, Phòng Kế toán, Giám đốc và Ngân hàng. Các bước thể hiện CCM13.1–13.21, bao gồm cả các vòng lặp khi không đồng ý, thẩm định ngân hàng, phát hành, gia hạn và giải tỏa.

Các ảnh giao diện nhúng trong BRD:
- Trang 3-5: form chi tiết đề xuất phát hành và cập nhật kết quả bảo lãnh.
- Trang 6: ảnh form tu chỉnh.
- Trang 7: danh sách bảo lãnh.
- Trang 9-10: chi tiết dữ liệu và form tu chỉnh.
- Không thấy ảnh chi tiết tương ứng cho Settlement, Inward, GL, Alert hoặc Report trong bộ ảnh của tài liệu.

## 3. Execution readiness

Hiện toàn bộ case được tạo dưới dạng `manual` step có hướng dẫn thao tác, vì BRD không cung cấp DOM selector, tài khoản/role staging hoặc dữ liệu test thực tế. AutoTest sẽ đánh dấu BLOCKED thay vì tự đoán selector. Khi đã có quyền truy cập UI, cần:
1. Xác nhận URL và login test account.
2. Kiểm tra DOM/labels/accessible roles để lập selector ổn định.
3. Tạo dữ liệu thử riêng, không dùng giao dịch thật.
4. Chuyển các bước manual sang Playwright actions.
5. Chạy smoke test từng màn hình trước, sau đó chạy regression.
6. Ghi bằng chứng ảnh, log, trạng thái và liên kết case với requirement.

## 4. Specification clarifications required

### Q01 — Công thức hạn mức
Mục 3.2 ghi HMBL còn lại = Max { [HM HĐTD - (Dư nợ vay + Bảo lãnh + LC)] & [HM Bảo lãnh - Dư nợ Bảo lãnh] }. Xác nhận phép kết hợp là Max hay Min, và cách xử lý giới hạn đồng thời.

### Q02 — Master Data Inward
Mục 2.1 liệt kê IN-PB và IN-WB; trường 53 mục 6.2 còn liệt kê IN-APB. Xác nhận có hỗ trợ IN-APB và cập nhật danh mục chuẩn.

### Q03 — Inward status
State machine có 8 trạng thái; trường inward_status mô tả danh sách rút gọn. Xác nhận mã DB và mapping đầy đủ.

### Q04 — APB partial release
Mỗi đợt thanh toán làm giảm bảo lãnh theo tỷ lệ tạm ứng tương ứng, nhưng chưa có công thức, tỷ lệ, rounding, điều kiện hoàn tất và xử lý event trùng.

### Q05 — Approval workflow
Sơ đồ trang 2 có CCM13.3, 13.5, 13.6 và 13.10, 13.13-13.21; nội dung mô tả chi tiết hiện thiếu nhiều bước, role, transition và exception.

### Q06 — Cảnh báo APB
BRD nêu số dư tạm ứng còn tồn đọng lớn nhưng chưa định nghĩa ngưỡng, nguồn số liệu và thời điểm đánh giá.

### Q07 — Quyền và audit
BRD chưa có ma trận role/action, phạm vi pháp nhân cho từng thao tác, quy tắc phê duyệt nhiều cấp, audit log và xử lý sửa/hủy sau khi gửi ngân hàng.

### Q08 — Tích hợp và chống ghi trùng
Chưa có API/event contract, idempotency key, mapping lỗi, retry/reversal, SLA đồng bộ cho ERP, HĐTD, BAM, MT940 và ngân hàng.

### Q09 — UI/field mapping
Ảnh minh họa có màn hình Outward, danh sách và Amendment; chưa có ảnh chi tiết UI Settlement, Inward, GL, Alert và Report để xác định selector và hành vi giao diện.

## 5. Test safety

Chỉ chạy trên staging với tài khoản được ủy quyền và bộ dữ liệu giả lập. Các thao tác tạo/sửa/hủy, phê duyệt, gửi ngân hàng, tất toán, ghi sổ và gửi thông báo có thể gây tác động nghiệp vụ; phải dùng dữ liệu test cô lập và xác nhận rằng các tích hợp downstream không phát lệnh thật.
