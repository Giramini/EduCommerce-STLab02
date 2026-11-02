# EduCommerce - STLab02 Test Case Execution (Requirement)

Sinh viên: Trần Minh Trí
MSSV 23110119

Môn: Software Testing - Bài thực hành STLab02

Dự án kiểm thử tự động theo dữ liệu (data-driven) cho module EduCommerce trong tài liệu STLab02 Instruction

Mỗi dòng của `test_cases.csv` là một test case độc lập; runner dựng fixture mới cho từng dòng, gọi hàm nghiệp vụ, so sánh kết quả trả về và trạng thái sau khi chạy (kho, đơn hàng, charge, voucher, giỏ hàng) rồi ghi PASS / FAIL / BLOCKED

## 1. Phạm vi: 6 requirement mới (không dùng REQ-06, REQ-08, REQ-11)

| REQ | Module | Số case |
|---|---|---|
| REQ-02 | Cart | 8 (1 BLOCKED chờ làm rõ requirement) |
| REQ-07 | Promotion | 5 |
| REQ-09 | Shipping | 6 |
| REQ-10 | Payment | 4 |
| REQ-15 | Inventory atomicity | 6 |
| REQ-16 | Payment safety | 5 |

Tổng: 6 requirement, 19 test condition, 26 test scenario, 34 test case (24 negative/boundary).
Expected Result suy ra từ acceptance criteria; không sao chép từ kết quả của ứng dụng.

## 2. Cấu trúc thư mục

| File | Vai trò |
|---|---|
| `ecommerce_app.py` | Ứng dụng EduCommerce, giữ nguyên từ tài liệu Instruction (không sửa lỗi) |
| `test_cases.csv` | Bộ test case (nguồn dữ liệu gốc, không bị ghi đè) |
| `design_catalog.csv` | Tên của REQ / condition / scenario để sinh ma trận traceability |
| `test_runner.py` | Fixture, đọc CSV, dispatcher, assertion, xử lý exception, xuất report |
| `experiments.py` | Thí nghiệm làm bằng chứng cho Problem Solving và Interview |
| `verify_fix.py` | Áp bản sửa DEF-001 lên một bản sao tạm rồi chạy lại toàn bộ suite (retest) |
| `dashboard_gradio.py` | Dashboard Gradio: biểu đồ và bảng đặt cạnh nhau |
| `reports/` | Report mẫu: CSV, Excel (4 sheet), HTML dashboard, biểu đồ PNG, log chạy |
| `evidence/` | Output của `experiments.py` và `verify_fix.py` |

## 3. Cách chạy từ môi trường sạch

Máy cá nhân:

```bash
pip install -r requirements.txt
python test_runner.py
python experiments.py
python verify_fix.py
```

Google Colab (mỗi ô là một cell):

```
!git clone https://github.com/<tai-khoan>/<ten-repo>.git
%cd <ten-repo>
!pip -q install -r requirements.txt
!python test_runner.py
```

Dashboard Gradio (tùy chọn): `!pip -q install gradio` rồi `!python dashboard_gradio.py` và mở liên kết gradio.live.
Không đưa dữ liệu khách hàng thật lên liên kết chia sẻ tạm

## 4. Định dạng test_cases.csv

Các cột bắt buộc: `test_case_id, requirement_id, condition_id, scenario_id, title, priority, precondition, fixture_key,
input_json, expected_type, expected_json, execution_status, actual_result, error_message, evidence_reference, operation`.
Cột thêm: `test_type` (positive / negative / boundary / edge), `blocked_reason`.
Các cột kết quả (`execution_status`, `actual_result`, `error_message`, `evidence_reference`) để trống trong file gốc;
runner ghi kết quả ra `reports/test_execution.csv`

`expected_json` có thể chứa: `error`, `stock` ("unchanged" hoặc từng SKU), `orders`, `charges`, `charge_amount`,
`used_codes`, `lines`, `order_status`, `shipping`, `discount`, `total`.
Quy tắc: nếu không có khóa `error` thì nghĩa là KHÔNG mong đợi lỗi, nên exception bất ngờ sẽ làm case FAIL

Operation: `cart_add_sequence` (Cart.add), `shipping_calc` (Shipping.calculate), `place_sequence` (Checkout.place).
Fixture: `empty`, `300k`, `500k`, `499999`, `600k`, `1000k`, `1500k`; `input_json.setup` ghi đè giá, kho, voucher đã dùng, giỏ hàng

Quy ước trạng thái: PASS, FAIL (ứng dụng sai so với expected), BLOCKED (bản thân test không chạy được: dữ liệu sai,
setup lỗi, chưa có oracle). Dòng lỗi dữ liệu không bị bỏ qua mà được ghi BLOCKED, và runner đối chiếu số dòng thực thi với số
bản ghi trong file CSV (`data_completeness`)

## 5. Kết quả mẫu (reports/run_log.txt)

34 case: 28 PASS, 5 FAIL, 1 BLOCKED, pass rate 82.4%, data completeness COMPLETE

| REQ | PASS | FAIL | BLOCKED |
|---|---|---|---|
| REQ-02 | 7 | 0 | 1 |
| REQ-07 | 5 | 0 | 0 |
| REQ-09 | 6 | 0 | 0 |
| REQ-10 | 4 | 0 | 0 |
| REQ-15 | 6 | 0 | 0 |
| REQ-16 | 0 | 5 | 0 |

## 6. Defect phát hiện

DEF-001 (REQ-16, TC-PSF-001 đến TC-PSF-005): khi `method` không phải COD/ONLINE, `Checkout.place()` vẫn trả đúng lỗi
`INVALID_PAYMENT_METHOD` nhưng tồn kho đã bị trừ và không được hoàn lại, vì `inventory.reserve()` chạy trước
`payments.collect()` (ecommerce_app.py dòng 94 và 97) và nhánh lỗi không gọi `release()`.
Bản sửa đề xuất đã được kiểm chứng bằng `verify_fix.py`: 33 PASS, 0 FAIL, 1 BLOCKED, không có hồi quy

## 7. Nguyên tắc

- Không sửa expected để biến FAIL thành PASS; không sửa `ecommerce_app.py` trong bước thực thi
- Mỗi case dựng fixture mới (test isolation); `experiments.py` chứng minh kết quả không phụ thuộc thứ tự chạy
- Không commit thông tin đăng nhập hay token
