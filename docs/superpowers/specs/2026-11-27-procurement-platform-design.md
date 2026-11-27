# Thiết kế: Nền tảng Procurement HSC (Đợt 1)

- Ngày: 2026-11-27
- Trạng thái: BẢN NHÁP, chờ người dùng duyệt
- Người sở hữu nghiệp vụ: Kế toán / FAD (người dùng)
- Ghi chú ký hiệu: **[Đã chốt]** = người dùng quyết định; **[Đề xuất]** = Claude đề xuất, người dùng có thể sửa; **[Mở]** = chưa có câu trả lời.

---

## 1. Vì sao làm

Hiện nay toàn bộ quy trình mua sắm tại HSC chạy bằng Excel, email và giấy tờ. Bước nào cũng chậm, tốn thời gian, và **không có audit trail**. Chỉ có khâu thanh toán được hỗ trợ bởi hệ thống PAS. **[Đã chốt]**

Phần mềm này đưa toàn bộ vòng đời một hồ sơ mua sắm lên một hệ thống: ai cũng biết hồ sơ đang ở bước nào, chờ ai, bao lâu; mọi thao tác được ghi lại không sửa được; chứng từ nằm cùng hồ sơ.

## 2. Mục tiêu, ngoài phạm vi, phản mục tiêu

### Mục tiêu
1. Số hoá quy trình 11 bước (mục 4), chia làm nhiều đợt, đợt 1 là nền tảng. **[Đã chốt]**
2. Luồng duyệt **cấu hình được**: ngưỡng tiền, lớp duyệt, đơn vị tham vấn là dữ liệu, không viết cứng trong code. Quy định chi tiết sẽ cung cấp sau. **[Đã chốt]**
3. Audit trail đầy đủ, không sửa/xoá được, kể cả bởi quản trị viên.
4. Đạt mức bảo mật để bộ phận CNTT HSC rà soát và tiếp nhận vận hành trên máy chủ nội bộ. **[Đã chốt]**

### Ngoài phạm vi (không làm)
- Thực hiện thanh toán: vẫn trên **PAS**. Phần mềm chỉ chuẩn bị hồ sơ và nhận lại trạng thái. **[Đã chốt]**
- Ghi sổ kế toán: vẫn trên **SUN**. Phần mềm chỉ xuất dữ liệu. **[Đã chốt]**
- Ứng dụng di động riêng (giao diện web vẫn dùng được trên điện thoại).
- Đa tiền tệ ở đợt 1: chỉ VND. **[Đề xuất]**

### Phản mục tiêu (dù chạy được vẫn coi là thất bại)
- Người dùng quay lại email/giấy vì hệ thống chậm hoặc rườm rà hơn cách cũ.
- Audit trail có thể bị sửa, hoặc có thao tác không được ghi.
- Quy tắc duyệt phải nhờ lập trình viên sửa code mới đổi được.
- Dữ liệu thật hoặc tài liệu nội bộ HSC nằm trên hạ tầng cá nhân (GitHub cá nhân, máy cá nhân).

## 3. Ràng buộc

| Ràng buộc | Nguồn |
|---|---|
| Triển khai trên máy chủ nội bộ HSC, truy cập trong mạng nội bộ/VPN | [Đã chốt] |
| Người dùng (không chuyên IT) cùng Claude làm bản mẫu; IT tiếp nhận vận hành | [Đã chốt] |
| Tích hợp: đăng nhập tài khoản công ty (SSO), SUN, PAS, email, Excel | [Đã chốt] |
| Công ty chứng khoán: chịu quy định về an toàn hệ thống thông tin, bảo vệ dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP; Luật Bảo vệ dữ liệu cá nhân 2025) và chính sách nội bộ HSC | Văn bản áp dụng cụ thể cần **Pháp chế/IT xác nhận** |
| Bản mẫu **chỉ dùng dữ liệu giả** | [Đề xuất] |

## 4. Quy trình nghiệp vụ (đã xác nhận)

| Giai đoạn | Bước | Người phụ trách chính |
|---|---|---|
| Chuẩn bị | 1. Ngân sách năm (FAD tổng hợp, CEO duyệt) | Khối/phòng ban |
| | 2. Chọn NCC (có trong danh sách: dùng ngay; NCC mới: đánh giá → FAD tiền kiểm → Ban Mua Sắm duyệt) | Bộ phận đề nghị |
| Xin duyệt | 3. Lập tờ trình kèm 03 báo giá | Người đề nghị |
| | 4. Tham vấn chuyên môn (ITD, DTI, DATA, HRM, COM, GRC, tuỳ nội dung) → FAD tiền kiểm mọi tờ trình → duyệt 3 lớp | Kế toán kiểm soát |
| | 5. Hợp đồng: soạn cùng NCC → FAD + Pháp chế rà soát → ký theo thẩm quyền | Người mua hàng |
| Thực hiện | 6. Đặt hàng, nghiệm thu | Người mua hàng |
| | 7. Đánh giá NCC sau mua (cùng FAD) | Bộ phận sử dụng |
| Chi tiền, ghi sổ | 8. Hồ sơ thanh toán trên PAS; GĐNV/GĐĐH + CFO duyệt; FAD chuyển tiền | Bộ phận đề nghị |
| | 9. Hạch toán trên SUN | Kế toán hạch toán |
| Giám sát | 10. Đối soát, báo cáo | Kế toán kiểm soát |
| | 11. Hậu kiểm hằng tháng, lưu chứng từ (Pháp chế tham gia khi cần) | Kế toán kiểm soát |

**Ba lớp duyệt:** Lớp 1 GĐNV/GĐĐH → Lớp 2 Ban Mua Sắm (BMS) → Lớp 3 CEO (TGĐ); ngoài ra HĐQT ở mức cao nhất. Lớp trên chỉ vào khi vượt thẩm quyền lớp dưới.

**Bảng thẩm quyền mẫu** (trích HSC_Chính sách Mua sắm, mục 7; dùng làm **dữ liệu mẫu** để kiểm thử bộ máy cấu hình, không viết cứng):

| Nhóm | Ngưỡng / tờ trình | Đề nghị | Tham vấn | Phê duyệt |
|---|---|---|---|---|
| Trong ngân sách | < 200tr | – | GĐĐH | GĐNV/TP |
| | 200tr – 2 tỷ | TP | GĐĐH/GĐ/TP-TCKT | GĐĐH |
| | > 2 tỷ | GĐĐH | GĐĐH/GĐ/TP-TCKT | BMS |
| Ngoài ngân sách | < 50tr, luỹ kế < 200tr/năm | TP | GĐĐH/GĐ/TP-TCKT | GĐĐH |
| | 50 – 300tr, luỹ kế < 2 tỷ/năm | GĐĐH | GĐĐH/GĐ/TP-TCKT | BMS |
| | 300tr – 3 tỷ, luỹ kế < 2% chi phí cố định năm | GĐĐH | GĐĐH-TCKT | TGĐ |
| | > 3 tỷ hoặc luỹ kế ≥ 2% | TGĐ | GĐĐH-TCKT | HĐQT |

Duyệt thanh toán luôn là GĐĐH-TCKT (= GĐNV/GĐĐH + CFO, đã xác nhận).

## 5. Phương án công nghệ đã cân nhắc

| Phương án | Ưu | Nhược | Kết quả |
|---|---|---|---|
| **A. Python (Django) + PostgreSQL** | Nhanh có bản mẫu; có sẵn trang quản trị, phân quyền, chống tấn công web phổ biến; code dễ đọc với người không chuyên; chạy Linux/Windows; có thể đổi sang SQL Server | IT HSC có thể phải học thêm nếu chỉ quen Microsoft | **Được chọn** [Đã chốt] |
| B. .NET + SQL Server | Hợp hệ sinh thái Microsoft, nối AD thuận | Code dài, khó đọc với người dùng; tự làm trang quản trị; chậm hơn ~30–50% (ước lượng) | Không chọn |
| C. Power Apps + SharePoint | Nhanh nhất, có sẵn M365 | Chạy cloud, trái yêu cầu máy chủ nội bộ; audit trail và hạn mức luỹ kế khó làm chặt; phí theo đầu người | Loại |

**Rủi ro đã chấp nhận:** chưa biết chuẩn công nghệ của IT HSC. Nếu IT bắt buộc .NET thì phải làm lại. Giảm thiểu: hỏi IT sớm (mục 11).

## 6. Kiến trúc **[Đề xuất]**

```
Trình duyệt (mạng nội bộ / VPN)
        │ HTTPS
   Nginx (reverse proxy, TLS, giới hạn tốc độ, header bảo mật)
        │
   Ứng dụng Django (Gunicorn)  ──►  PostgreSQL 16
        │                            (dữ liệu + audit trail)
        ├──► Kho file chứng từ (ổ đĩa riêng, ngoài thư mục web)
        └──► Worker nền: gửi email, xuất file SUN/PAS (đọc bảng "outbox")
```

- **Ngôn ngữ/khung:** Python 3.12, Django 5.2 LTS (hỗ trợ đến 2028).
- **Giao diện:** Django template render phía máy chủ + HTMX cho thao tác nhanh. Không dùng SPA (React…) để ít thành phần, ít bề mặt tấn công, dễ bàn giao. Mọi thư viện CSS/JS đóng gói sẵn, **không gọi CDN ngoài** (máy chủ nội bộ có thể không ra Internet).
- **Đóng gói:** Docker Compose (app, db, nginx, worker), để IT cài một lệnh.
- **Không dùng Redis/Celery ở đợt 1:** việc nền dùng bảng outbox trong PostgreSQL + tiến trình worker, bớt một hệ thống IT phải vận hành.
- **Tiền:** kiểu Decimal, không dùng số thực; đơn vị VND.
- **Năm tài chính:** theo năm dương lịch. **[Đề xuất]**
- **Giao diện tiếng Việt.**

## 7. Các thành phần của đợt 1 (nền tảng)

| Thành phần | Nội dung |
|---|---|
| `accounts` | Người dùng, phòng ban, chức danh, vai trò. Bản mẫu: tài khoản nội bộ + mật khẩu mạnh + MFA (mã OTP). Có sẵn chỗ nối SSO (OIDC với Entra ID/ADFS hoặc LDAP với AD) để IT bật. |
| `audit` | Nhật ký sự kiện chỉ-ghi-thêm (xem 8.3). Màn hình tra cứu, xuất cho kiểm toán. |
| `documents` | Đính kèm chứng từ vào hồ sơ: giới hạn loại file (PDF, ảnh, Excel, Word), giới hạn dung lượng, lưu mã băm SHA-256, tải về qua kiểm tra quyền. |
| `workflow` | Bộ máy luồng duyệt cấu hình được (xem 7.1). |
| `budget` | Ngân sách năm theo phòng ban × khoản mục; số đã cam kết (tờ trình đã duyệt), đã chi (từ PAS). Nhập từ Excel. |
| `vendors` | Danh mục NCC, trạng thái (đang hiệu lực / chờ đánh giá / bị khoá), lịch sử. Nhập từ Excel. |
| `requisitions` | Tờ trình mua sắm: thông tin, dòng hàng, 03 báo giá đính kèm, liên kết ngân sách, chạy luồng duyệt end-to-end. |
| `notifications` | Email khi có việc chờ, quá hạn; màn hình "Việc chờ tôi"; đo thời gian xử lý từng bước. |
| `integrations` | Bộ chuyển đổi cho SSO, SUN, PAS, email. Đợt 1 dùng **bản giả lập**; IT thay bằng kết nối thật. |

### 7.1 Bộ máy luồng duyệt
- **Chính sách duyệt** có phiên bản, hiệu lực từ ngày. Mỗi chính sách gồm các **quy tắc**: điều kiện (trong/ngoài ngân sách, khoảng tiền, luỹ kế năm, loại chi phí, phòng ban) → chuỗi **bước** (đề nghị, tham vấn, tiền kiểm, duyệt lớp 1/2/3, HĐQT).
- Mỗi bước gắn **vai trò + phạm vi** (ví dụ: "Trưởng phòng của phòng lập tờ trình", "FAD tiền kiểm", "đơn vị tham vấn theo nội dung").
- Bước có thể là **bắt buộc chấp thuận** hoặc **chỉ cho ý kiến**: cấu hình được.
- Khi tờ trình được nộp, hệ thống **chụp lại phiên bản chính sách** đang hiệu lực; sửa chính sách sau đó không ảnh hưởng tờ trình đang chạy.
- **Luỹ kế ngoài ngân sách** tự tính, phạm vi (phòng ban hay toàn công ty) cấu hình được. Người lập không tự chọn cấp duyệt.
- **Duyệt tại cuộc họp** (BMS, HĐQT): người được giao ghi nhận kết quả + đính kèm biên bản.
- Thao tác: chấp thuận, từ chối, **trả lại bổ sung** (tạo phiên bản mới của tờ trình, giữ lịch sử).
- **Cảnh báo chia nhỏ tờ trình:** cùng phòng ban + cùng NCC hoặc khoản mục trong N ngày, tổng vượt ngưỡng → cảnh báo cho FAD tiền kiểm. N cấu hình được.
- **Uỷ quyền khi vắng mặt:** [Mở, mục 12].

## 8. Bảo mật thông tin

Chuẩn tham chiếu: **OWASP ASVS mức 2** (bộ tiêu chí kiểm tra bảo mật ứng dụng web phổ biến). IT/ATTT HSC có thể bổ sung chuẩn nội bộ.

### 8.1 Truy cập
- Chỉ truy cập trong mạng nội bộ/VPN; bắt buộc HTTPS.
- Đăng nhập SSO công ty (khi chạy thật); bản mẫu có MFA. Khoá tạm sau nhiều lần sai; hết phiên sau 30 phút không thao tác. **[Đề xuất]**
- **Phân quyền theo vai trò + theo dữ liệu:** người dùng chỉ thấy hồ sơ của phòng mình và hồ sơ được giao xử lý; FAD/BMS/Kiểm soát thấy theo phạm vi được cấp.
- **Phân tách nhiệm vụ** (bắt buộc trong code, không cấu hình tắt được): người lập không tự duyệt hồ sơ của mình; người tạo NCC mới không tự duyệt NCC đó; quản trị viên kỹ thuật không duyệt nghiệp vụ.

### 8.2 Ứng dụng
- Chống các lỗi web phổ biến (SQL injection, XSS, CSRF, clickjacking) bằng cơ chế sẵn có của Django + header bảo mật (CSP, HSTS…).
- Mọi dữ liệu nhập (form, Excel) đều kiểm tra hợp lệ; file Excel được đọc như dữ liệu, không chạy macro/công thức.
- File tải lên: danh sách loại cho phép, giới hạn dung lượng, lưu ngoài thư mục web, đổi tên ngẫu nhiên; IT có thể nối quét virus (ClamAV).

### 8.3 Audit trail
- Mọi sự kiện (tạo, sửa (kèm giá trị cũ/mới), nộp, duyệt, từ chối, đăng nhập, đổi cấu hình, tải file) ghi vào bảng riêng: ai, lúc nào, từ đâu (IP), làm gì.
- Bảng **chỉ ghi thêm**: tài khoản cơ sở dữ liệu của ứng dụng không có quyền sửa/xoá; thêm trigger chặn sửa/xoá.
- **Chuỗi băm:** mỗi bản ghi chứa mã băm của bản ghi trước. Nếu ai sửa trực tiếp trong cơ sở dữ liệu, kiểm tra định kỳ sẽ phát hiện.

### 8.4 Dữ liệu
- Mật khẩu, khoá bí mật nằm trong biến môi trường/file `.env` trên máy chủ, **không bao giờ đưa vào git**.
- Sao lưu cơ sở dữ liệu và kho file hằng ngày (IT vận hành); có kiểm tra khôi phục.
- Dữ liệu cá nhân (tên, email nhân viên; thông tin liên hệ NCC) ở mức tối thiểu cần thiết.

### 8.5 Quy trình phát triển
- Kiểm thử tự động cho logic nghiệp vụ, đặc biệt luồng duyệt và phân quyền.
- Mỗi lần đẩy code tự chạy: kiểm thử, quét lỗ hổng thư viện (`pip-audit`), quét lỗi bảo mật trong code (`bandit`), quét lộ mật khẩu (`gitleaks`).
- Trước khi chạy thật: IT/ATTT rà soát code và kiểm thử xâm nhập (pentest).

### 8.6 Cảnh báo về nơi lưu code hiện tại
Repo đang ở **GitHub cá nhân** (`hdbdien2511/procurement-fad`). Đề xuất:
1. Đảm bảo repo ở chế độ **Private**.
2. **Không** đưa vào repo: dữ liệu thật, file chính sách nội bộ gốc, tên/email nhân viên thật, số liệu ngân sách thật. Bảng thẩm quyền ở mục 4 chỉ là bản trích để thiết kế; nếu chính sách nội bộ không cho phép, sẽ thay bằng số giả.
3. Khi IT tiếp nhận: chuyển repo sang hệ thống quản lý mã nguồn của HSC.

Việc có được phép phát triển trên GitHub cá nhân và dùng công cụ AI với tài liệu nội bộ hay không cần **bạn xác nhận với IT/ATTT**.

## 9. Cấu trúc thư mục dự án **[Đề xuất]**

```
procurement-fad/
├── README.md                  Giới thiệu, cách chạy thử
├── CLAUDE.md                  Hướng dẫn cho Claude khi làm việc trên repo
├── docs/                      TÀI LIỆU (phần bạn làm chủ)
│   ├── 01-nghiep-vu/          Quy trình, bảng thuật ngữ, yêu cầu nghiệp vụ
│   ├── 02-thiet-ke/           Kiến trúc, mô hình dữ liệu, các quyết định (ADR)
│   ├── 03-bao-mat/            Phân loại dữ liệu, mô hình rủi ro, checklist ATTT
│   ├── 04-kiem-thu/           Kịch bản kiểm thử nghiệp vụ (UAT)
│   ├── 05-ban-giao-it/        Câu hỏi cho IT, hướng dẫn cài đặt, vận hành
│   └── superpowers/           Bản thiết kế (specs) và kế hoạch (plans)
├── src/                       MÃ NGUỒN
│   ├── manage.py
│   ├── config/                Cấu hình Django (chung / dev / prod)
│   ├── apps/
│   │   ├── accounts/          Người dùng, phòng ban, vai trò
│   │   ├── audit/             Audit trail
│   │   ├── documents/         Chứng từ đính kèm
│   │   ├── workflow/          Bộ máy luồng duyệt
│   │   ├── budget/            Ngân sách
│   │   ├── vendors/           Nhà cung cấp
│   │   ├── requisitions/      Tờ trình mua sắm
│   │   ├── notifications/     Email, việc chờ xử lý
│   │   └── integrations/      SSO, SUN, PAS, email (giả lập → thật)
│   ├── templates/             Giao diện (HTML)
│   └── static/                CSS, JS, icon (đóng gói sẵn, không CDN)
├── tests/                     Kiểm thử tự động
├── sample-data/               Dữ liệu GIẢ để chạy thử (Excel mẫu)
├── deploy/                    Docker Compose, Nginx, .env.example
├── scripts/                   Lệnh tiện ích (tạo dữ liệu mẫu, sao lưu…)
├── .github/workflows/         Kiểm tra tự động mỗi lần đẩy code
├── pyproject.toml             Danh sách thư viện
├── .gitignore                 Chặn file nhạy cảm (.env, dữ liệu, file tải lên)
└── .claude/                   Skills cho Claude (đã có)
```

Đợt 2–3 thêm các app: `quotations` (báo giá, chọn NCC), `contracts` (PO/hợp đồng), `receiving` (nghiệm thu, đánh giá sau mua), `payments_handoff` (hồ sơ sang PAS), `reporting`.

**Cách bạn làm việc với cấu trúc này:** bạn chủ yếu làm trong `docs/01-nghiep-vu/` (quy trình, quy định, thuật ngữ) và `docs/04-kiem-thu/` (kịch bản kiểm thử theo nghiệp vụ). Claude viết `src/`, `tests/`, `deploy/` theo tài liệu đó. Mỗi thay đổi đều có kiểm thử chạy được để bạn và IT kiểm chứng.

## 10. Lộ trình

| Đợt | Nội dung | Kết quả kiểm chứng được |
|---|---|---|
| 0. Chuẩn bị | Repo, tài liệu nghiệp vụ, câu hỏi gửi IT, dữ liệu giả | IT trả lời câu hỏi mục 11 |
| **1. Nền tảng** (bản thiết kế này) | Mục 7 | Một tờ trình chạy từ lập → tham vấn → FAD tiền kiểm → duyệt đủ lớp theo bảng thẩm quyền mẫu, có email, audit trail, chứng từ, trừ ngân sách cam kết |
| 2. Chọn NCC & Hợp đồng | Báo giá, đánh giá NCC mới (FAD tiền kiểm, BMS duyệt), PO/hợp đồng, Pháp chế + FAD rà soát | Hồ sơ đi tiếp từ tờ trình đã duyệt đến hợp đồng đã ký |
| 3. Thực hiện & Chi tiền | Nghiệm thu, đánh giá sau mua, đối chiếu PO–nghiệm thu–hoá đơn, xuất sang PAS/SUN, báo cáo, hậu kiểm | Hồ sơ thanh toán xuất được đúng mẫu PAS; báo cáo ngân sách thực chi |
| 4. Bàn giao IT | SSO thật, kết nối SUN/PAS thật, rà soát bảo mật, pentest, cài trên máy chủ HSC, UAT, go-live | IT ký nhận vận hành |

## 11. Câu hỏi gửi IT (soạn sẵn để bạn chuyển)
1. Máy chủ nội bộ chạy Linux hay Windows? Có cài được Docker không?
2. Cơ sở dữ liệu chuẩn: PostgreSQL có được chấp nhận hay bắt buộc SQL Server?
3. Đăng nhập công ty dùng gì: Microsoft Entra ID (Azure AD), ADFS hay Active Directory nội bộ (LDAP)?
4. Gửi email từ ứng dụng nội bộ qua máy chủ mail nào (SMTP relay / Microsoft 365)?
5. SUN và PAS nhận/xuất dữ liệu theo cách nào: file Excel/CSV theo mẫu, thư mục chung, hay API?
6. Có chuẩn bảo mật/checklist nội bộ nào ứng dụng mới phải đạt? Có yêu cầu pentest trước go-live?
7. Có được phát triển trên GitHub (repo private) và dùng công cụ AI hỗ trợ lập trình không? Khi bàn giao, chuyển mã nguồn về đâu?
8. Chính sách lưu trữ chứng từ điện tử bao lâu? Sao lưu do ai phụ trách?

## 12. Câu hỏi mở cho người dùng
1. **Uỷ quyền khi vắng mặt** [Mở]: khi người duyệt nghỉ phép/công tác, hiện HSC xử lý thế nào?
2. **Cấu trúc ngân sách** [Mở]: ngân sách năm được chia theo những chiều nào (phòng ban × khoản mục chi phí? theo mã tài khoản trên SUN?), và có điều chuyển giữa các khoản mục không?

## 13. Các quyết định Claude tự đưa ra (để bạn rà)
- Giao diện render phía máy chủ + HTMX, không SPA.
- Không Redis/Celery ở đợt 1; dùng outbox trong PostgreSQL.
- Chỉ VND; năm tài chính = năm dương lịch.
- Hết phiên sau 30 phút; MFA cho tài khoản nội bộ ở bản mẫu.
- Audit trail chỉ-ghi-thêm + chuỗi băm.
- Phân tách nhiệm vụ cứng trong code.
- Mã tờ trình dạng `TT-2026-00001`.
- Bước tham vấn có thể đặt "bắt buộc chấp thuận" hoặc "chỉ cho ý kiến" theo cấu hình.
- Phạm vi luỹ kế ngoài ngân sách cấu hình được (phòng ban/toàn công ty).

## 14. Phần để người lập trình quyết định
Chi tiết mô hình dữ liệu, tên bảng, bố cục màn hình cụ thể, thư viện phụ trợ (miễn không thêm hạ tầng mới và phải qua quét bảo mật).
