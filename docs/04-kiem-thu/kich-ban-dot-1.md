# Kịch bản nghiệm thu đợt 1 (người dùng tự kiểm tra trên giao diện)

Mục tiêu: chứng minh kết quả kiểm chứng của đợt 1 (spec mục 10, dòng "1. Nền tảng") — *một tờ trình
(2 nguồn ngân sách, USD) chạy từ lập → tham vấn → FAD tiền kiểm → duyệt đủ lớp theo bảng mẫu, có
duyệt thay, email, audit, chứng từ; giữ chỗ ngân sách đúng; người lập không tự duyệt được* — và
hành trình chính của FAD: **tờ trình bị chặn vì thiếu ngân sách → bổ sung ngân sách → duyệt**.

Toàn bộ dữ liệu dưới đây là **dữ liệu giả** trong `sample-data/`. Hai kịch bản này cũng được chạy tự
động ở `tests/e2e/test_dot1_scenario.py` (qua tầng dịch vụ); tài liệu này là bản "bấm tay" để người
dùng tự nghiệm thu.

## 1. Chuẩn bị

```bash
source .venv/bin/activate
export DATABASE_URL=postgres://procurement:procurement@localhost:5432/procurement_demo
python src/manage.py migrate
python src/manage.py seed_demo          # chạy lại được; --reset để dựng lại chính sách/phân quyền
python src/manage.py runserver
```

`seed_demo` in ra bản tóm tắt những gì đã tạo và danh sách tài khoản demo:

- đơn vị + người dùng từ `sample-data/hris_fake.json` (lệnh `sync_hris`);
- ngân sách 2026 của đơn vị ngân sách **ITD** từ `sample-data/Budget Control - DEMO.xlsx` (kèm sheet
  `L9_Code` → 10 nhà cung cấp giả), cộng đơn vị ngân sách **ADM** và 2 dòng ngân sách demo:
  `2026 · ITD · DM_9.1 · BAU_ITD · HSC` (1.600.000.000 đ) và `2026 · ADM · ADM_2.1 · BAU_ADM · HSC`
  (1.100.000.000 đ);
- phân quyền theo gợi ý `roles` trong `hris_fake.json`;
- 2 chính sách duyệt mẫu theo bảng thẩm quyền spec mục 4: `TRONG_NGAN_SACH`, `NGOAI_NGAN_SACH`
  (tham vấn không bắt buộc, FAD tiền kiểm bắt buộc, SLA 48 giờ);
- tỷ giá **USD = 25.460** (hiệu lực 01/01/2026) và 4 tham số hệ thống.

Chạy lại `seed_demo` nhiều lần không nhân bản dữ liệu. `--reset` xoá phần xoá được (chính sách mẫu
chưa dùng, phân quyền, uỷ quyền, tỷ giá, tham số) rồi dựng lại; **bút toán ngân sách, nhật ký audit
và chứng từ lưu vĩnh viễn** (Ràng buộc chung) nên muốn làm lại hoàn toàn thì tạo lại cơ sở dữ liệu.

### Tài khoản demo

Mật khẩu chung: `Demo-MuaSam-2026`. Đăng nhập bằng mật khẩu bắt buộc TOTP: với mỗi tài khoản sắp
dùng, chạy `python src/manage.py enroll_totp <tên đăng nhập>` rồi nạp URI in ra vào ứng dụng xác
thực (Microsoft/Google Authenticator). Khi bật đăng nhập Entra ID (OIDC) thì không cần bước này.

| Tên đăng nhập | Vai trò trong kịch bản |
|---|---|
| `nv.mau1` | Người đề nghị, Phòng Demo A (người lập tờ trình) |
| `tp.mau1` | Trưởng phòng Demo A (đề nghị / phê duyệt nhóm < 200tr) |
| `bo.itd` | Đơn vị quản lý ngân sách CNTT (nhánh ITD) |
| `bo.adm` | Đơn vị quản lý ngân sách Hành chính (nhánh ADM) |
| `tv.dti` | Tham vấn chuyên môn, Phòng Dữ liệu Demo |
| `fad.tienkiem` | FAD tiền kiểm |
| `fad.ngansach` | FAD quản trị ngân sách |
| `gddh.mau` | Giám đốc điều hành (GĐĐH) |
| `gdnv.mau` | Giám đốc nghiệp vụ — người được GĐĐH uỷ quyền duyệt thay |
| `thuky.bms` | Thư ký BMS (duyệt tại cuộc họp) |
| `thuky.hdqt` | Thư ký HĐQT |
| `ceo.mau` | Tổng giám đốc |

Chứng từ tải lên: dùng tệp PDF/PNG/JPG/XLSX/DOCX bất kỳ (tối đa 25 MB), ví dụ 3 tệp
`bao-gia-1.pdf`, `bao-gia-2.pdf`, `bao-gia-3.pdf` và `bien-ban-bms.pdf`.

## 2. Kịch bản A — tờ trình USD, 2 nguồn ngân sách, duyệt tại cuộc họp (> 2 tỷ)

Tổng tờ trình: 100.000 USD × 25.460 = **2.546.000.000 đ** → quy tắc **`>2ty`**: Đề nghị (GĐĐH) →
Đơn vị quản lý ngân sách (2 nhánh) → Tham vấn → FAD tiền kiểm → Duyệt tại cuộc họp (BMS).

| Bước | Thao tác | Kết quả mong đợi | Đạt/Không |
|---|---|---|---|
| A1 | Đăng nhập `nv.mau1` (mật khẩu + mã TOTP) | Vào trang "Việc chờ tôi"; thanh trên hiện tên người dùng |  |
| A2 | Tờ trình → "Tạo tờ trình". Thông tin chung: Tiêu đề "Mua máy chủ ảo hoá (demo)", Loại mua sắm "Dự án", Sự cần thiết điền tự do, Loại tiền `USD`, Ngày bắt đầu dịch vụ `01/12/2026`, Số tháng `1`, Đơn vị tham vấn chọn "DTI-DEMO - Phòng Dữ liệu Demo", để trống Lý do không đủ 03 báo giá | Form mở, danh sách đơn vị tham vấn và nhà cung cấp có dữ liệu demo |  |
| A3 | Dòng hàng: Mô tả "Máy chủ ảo hoá", Số lượng `1`, Đơn giá `100000`, VAT `0`. Phân bổ ngân sách: dòng 1 = `2026 · ITD · DM_9.1 · BAU_ITD · HSC` số tiền `1527600000`; dòng 2 = `2026 · ADM · ADM_2.1 · BAU_ADM · HSC` số tiền `1018400000`. Bấm "Lưu tờ trình nháp" | Mở trang chi tiết tờ trình, trạng thái **Nháp**; bảng "Phân bổ ngân sách và số dư khả dụng" hiện 2 dòng với số khả dụng 1.600.000.000 đ và 1.100.000.000 đ |  |
| A4 | Mục "Chứng từ": tải lần lượt 3 tệp báo giá, Loại chứng từ = "Báo giá" | Mỗi lần có thông báo "Đã tải chứng từ lên"; danh sách chứng từ có 3 bản ghi |  |
| A5 | Xem khối cảnh báo trước khi nộp | Không còn lỗi chặn nộp (đủ 03 báo giá, tổng phân bổ = tổng tờ trình 2.546.000.000 đ), nút "Nộp tờ trình" hiện ra |  |
| A6 | Bấm "Nộp tờ trình" | Thông báo "Đã nộp tờ trình, luồng duyệt bắt đầu"; tờ trình có số `TT-2026-xxxxx`, trạng thái **Đang duyệt**; lịch sử duyệt hiện 5 bước, bước 1 "Đề nghị" đang chờ |  |
| A7 | Vẫn là `nv.mau1`: mở "Việc chờ tôi" | **Không** có việc nào của tờ trình này (người lập không tự duyệt hồ sơ của mình — phân tách nhiệm vụ) |  |
| A8 | Đăng nhập `gddh.mau` → Uỷ quyền → "Tạo uỷ quyền mới": người nhận `gdnv.mau`, Từ ngày = hôm nay, Đến ngày = hôm nay + 3 ngày, Loại hồ sơ "Tờ trình mua sắm", để trống hạn mức | Uỷ quyền xuất hiện ở "Uỷ quyền tôi đã cấp" |  |
| A9 | Đăng nhập `gdnv.mau` → "Việc chờ tôi" → mở việc "Đề nghị" của `TT-2026-xxxxx` → chọn "Chấp thuận", nhập ý kiến → "Ghi nhận" | Ghi nhận thành công; lịch sử bước 1 ghi `gdnv.mau` **duyệt thay** `gddh.mau` (cột "Duyệt thay") |  |
| A10 | Đăng nhập `bo.itd` → "Việc chờ tôi" | Có việc "Đơn vị quản lý ngân sách xác nhận" (nhánh Phòng CNTT Demo); `bo.adm` cũng có một việc tương tự (2 nhánh song song) |  |
| A11 | `bo.itd` chấp thuận; đăng nhập `bo.adm` chấp thuận | Sau khi cả 2 nhánh chấp thuận, bước "Tham vấn" và "FAD tiền kiểm" cùng mở |  |
| A12 | Đăng nhập `tv.dti` → "Việc chờ tôi" → mở việc "Tham vấn" → nhập ý kiến "Cấu hình phù hợp" → "Ghi nhận" | Bước tham vấn chuyển "Đã cho ý kiến"; chỉ có lựa chọn cho ý kiến (không có chấp thuận/từ chối) |  |
| A13 | Đăng nhập `fad.tienkiem` → Tờ trình → mở `TT-2026-xxxxx` → "FAD tiền kiểm" | Màn hình tiền kiểm hiện: số dư từng dòng ngân sách, quy tắc thẩm quyền đã chọn (`>2ty`) và 5 bước, **ý kiến tham vấn của `tv.dti`**, checklist chứng từ (Báo giá = 3) |  |
| A14 | Bấm "Đạt" | Thông báo "Đã ghi nhận kết quả tiền kiểm"; bước "Duyệt tại cuộc họp" mở cho thư ký BMS |  |
| A15 | Đăng nhập `thuky.bms` → "Việc chờ tôi" → mở việc "Duyệt tại cuộc họp" → "Chấp thuận" → "Ghi nhận" | Bị từ chối với thông báo **"Cần đính kèm biên bản họp"** |  |
| A16 | Vẫn là `thuky.bms`: mở trang chi tiết tờ trình → mục "Chứng từ" → tải `bien-ban-bms.pdf`, Loại chứng từ = "Biên bản họp" | "Đã tải chứng từ lên"; biên bản xuất hiện trong danh sách chứng từ |  |
| A17 | Quay lại việc "Duyệt tại cuộc họp" → "Chấp thuận" → "Ghi nhận" | Luồng duyệt kết thúc; tờ trình trạng thái **Đã duyệt** |  |
| A18 | Mở lại chi tiết tờ trình, xem bảng "Phân bổ ngân sách và số dư khả dụng" | Cột "Đã giữ chỗ": dòng ITD = 1.527.600.000 đ, dòng ADM = 1.018.400.000 đ (tổng = 2.546.000.000 đ = tổng tờ trình); cột "Khả dụng" giảm tương ứng |  |
| A19 | Đăng nhập `fad.ngansach` → Ngân sách → mở dòng ITD ở trên → "Sổ cái" (người đề nghị không xem được sổ cái của đơn vị khác) | Sổ cái ngân sách của dòng đó có bút toán **Giữ chỗ** kỳ 12/2026 đúng số tiền, hồ sơ nguồn là tờ trình |  |
| A20 | Đăng nhập `fad.ngansach` (hoặc tài khoản có vai trò Kiểm toán) → Nhật ký | Nhật ký có các hành động `requisition.submitted`, `workflow.started`, `workflow.task_acted`, `workflow.approved`, `budget.reserved`, `document.uploaded`, `delegation.created` của hồ sơ này |  |
| A21 | Chạy `python src/manage.py audit_verify` | In "Số bản ghi lỗi: 0" (chuỗi hash nhật ký liền mạch) |  |
| A22 | Email: Cài đặt → Email, cấu hình SMTP thử rồi chạy `python src/manage.py run_worker` (hoặc xem hộp thư đi) | Có email tiêu đề `[Mua sắm] Hồ sơ TT-2026-xxxxx **cần duyệt**` gửi tới người xử lý từng bước; biểu tượng thông báo trong ứng dụng cũng có mục tương ứng |  |

## 3. Kịch bản B — tờ trình bị chặn vì thiếu ngân sách → đề nghị bổ sung → duyệt

Hành trình chính của FAD (spec 4.1: chi phí chưa có ngân sách thì **chặn** và yêu cầu làm thủ tục
bổ sung ngân sách). Nên chạy trên cơ sở dữ liệu vừa `seed_demo` (hoặc đọc lại số khả dụng hiện tại
trên màn hình).

| Bước | Thao tác | Kết quả mong đợi | Đạt/Không |
|---|---|---|---|
| B1 | Đăng nhập `fad.ngansach` → Ngân sách → dòng `2026 · ADM · ADM_2.1 · BAU_ADM · HSC`, ghi lại **số khả dụng** (gọi là `K`, sau `seed_demo` là 1.100.000.000 đ) | Số dư hiển thị đúng: Ngân sách = 1.100.000.000 đ, Đã giữ chỗ = 0 |  |
| B2 | Đăng nhập `nv.mau1`, tạo tờ trình mới: Tiêu đề "Mua thiết bị vượt ngân sách (demo)", Loại "Thường xuyên (BAU)", Loại tiền `VND`, Ngày bắt đầu dịch vụ `01/12/2026`, Số tháng `1`, Lý do không đủ 03 báo giá điền tự do; dòng hàng Số lượng `1`, Đơn giá = `K + 30.000.000`, VAT `0`; phân bổ toàn bộ số đó vào dòng ADM ở B1 | Lưu được tờ trình nháp |  |
| B3 | Xem khối kiểm tra ngân sách trên trang chi tiết | Hiện cảnh báo **thiếu 30.000.000 đ** trên dòng ADM, kèm liên kết "Tạo đề nghị bổ sung ngân sách" |  |
| B4 | Bấm "Nộp tờ trình" | Bị chặn: "Không đủ ngân sách khả dụng — … thiếu 30.000.000 đ"; tờ trình **vẫn là Nháp**, chưa được cấp số |  |
| B5 | Bấm "Tạo đề nghị bổ sung ngân sách" → "Tạo đề nghị bổ sung cho các dòng thiếu" | Mở đề nghị `NS-2026-xxxxx` loại **Bổ sung**, dòng nhận = dòng ADM, số tiền **30.000.000 đ**, kỳ bắt đầu 12/2026, lý do điền sẵn "Bổ sung ngân sách cho tờ trình …" |  |
| B6 | Bấm "Nộp đề nghị" | Trạng thái **Đang duyệt**; luồng "Ngoài ngân sách" nhóm **A** (< 50tr, luỹ kế < 200tr): Đề nghị (Trưởng đơn vị) → FAD tiền kiểm → Phê duyệt (GĐĐH) |  |
| B7 | Đăng nhập `tp.mau1` → "Việc chờ tôi" → việc "Đề nghị" của `NS-2026-xxxxx` → "Chấp thuận" | Bước 1 hoàn tất, bước FAD tiền kiểm mở |  |
| B8 | Đăng nhập `fad.tienkiem` → việc "FAD tiền kiểm" → "Chấp thuận" | Bước phê duyệt của GĐĐH mở |  |
| B9 | Đăng nhập `gddh.mau` → việc "Phê duyệt" → "Chấp thuận" | Đề nghị trạng thái **Đã duyệt**; sổ cái dòng ADM (xem bằng `fad.ngansach`) có bút toán **Điều chỉnh** +30.000.000 đ kỳ 12/2026; số khả dụng = `K + 30.000.000` |  |
| B10 | Đăng nhập `nv.mau1` → mở lại tờ trình ở B2 → "Nộp tờ trình" | Nộp thành công, có số `TT-2026-xxxxx`, trạng thái **Đang duyệt**; quy tắc thẩm quyền là **`200tr-2ty`**: Đề nghị (TP) → Đơn vị quản lý ngân sách → Tham vấn → FAD tiền kiểm → Phê duyệt (GĐĐH) |  |
| B11 | `tp.mau1` chấp thuận bước "Đề nghị"; `bo.adm` chấp thuận bước "Đơn vị quản lý ngân sách xác nhận" | Bước FAD tiền kiểm mở (không có đơn vị tham vấn nào được chọn nên bước tham vấn bị bỏ qua) |  |
| B12 | `fad.tienkiem` mở màn hình "FAD tiền kiểm" của tờ trình → "Đạt" | Bước phê duyệt của GĐĐH mở |  |
| B13 | `gddh.mau` chấp thuận | Tờ trình **Đã duyệt**; cột "Đã giữ chỗ" của dòng ADM = tổng tờ trình (`K + 30.000.000`), số khả dụng về 0 |  |
| B14 | Nhật ký + `python src/manage.py audit_verify` | Có `budget_change.submitted`, `budget_change.status_changed`, `budget.entries_posted`, `requisition.submitted`, `budget.reserved`; audit_verify in "Số bản ghi lỗi: 0" |  |

## 4. Ghi chú khi nghiệm thu

- Nếu một bước duyệt không xuất hiện trong "Việc chờ tôi", kiểm tra lại vai trò và phạm vi: bước
  phạm vi toàn công ty (GĐĐH, TGĐ, thư ký BMS/HĐQT, FAD) chỉ nhận phân công vai trò **toàn công ty**.
- Người lập / người đề nghị (và người lập các phiên bản trước) không bao giờ xử lý được bất kỳ bước
  nào của hồ sơ mình; tài khoản giữ vai trò Quản trị hệ thống cũng không duyệt nghiệp vụ.
- Bước "Duyệt tại cuộc họp" chỉ chấp thuận được khi biên bản họp được đính kèm **sau** thời điểm nộp
  hồ sơ; người đang xử lý bước duyệt được quyền đính kèm chứng từ này.
- Màn hình Ngân sách / Sổ cái chỉ dành cho FAD, Kiểm toán và đơn vị quản lý ngân sách; người đề nghị
  xem số dư các dòng của tờ trình mình ngay trên trang chi tiết tờ trình.
- Tờ trình đã nộp không sửa được nội dung; muốn sửa thì bước duyệt phải "Trả lại bổ sung", sau đó
  người lập bấm "Sửa lại bản mới" (cùng số tờ trình, phiên bản +1).
