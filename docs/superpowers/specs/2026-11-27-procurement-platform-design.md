# Thiết kế: Nền tảng Procurement HSC (Đợt 1)

- Ngày: 2026-11-27 (cập nhật lần 6: chốt kiểm soát theo chi phí phân bổ; mô hình đơn vị quản lý ngân sách tập trung)
- Trạng thái: BẢN NHÁP HOÀN CHỈNH, chờ người dùng duyệt
- Người sở hữu nghiệp vụ: Kế toán / FAD (người dùng)
- Ký hiệu: **[Đã chốt]** = người dùng quyết định; **[RFP]** = lấy từ tài liệu RFP; **[Đề xuất]** = Claude đề xuất, người dùng có thể sửa; **[Mở]** = chưa có câu trả lời.
- Tài liệu nguồn: `RFP_eProcurement_v0.2.docx`, `RFP_eProcurement_As_is__To_be.xlsx` (không lưu vào repo, xem 8.6). Mã `R1`…`R89` trong tài liệu này là số thứ tự tiêu chí ở sheet "5. Thang điểm".

---

## 0. Quan hệ với RFP (cần làm rõ, không chặn đợt 1)

RFP do IT phát hành để **mua giải pháp từ vendor**. Bản thiết kế này là **tự xây**. Hai việc này phải có quan hệ rõ ràng, nếu không sẽ trùng lặp công sức hoặc gây khó xử với IT. **[Mở, mục 12 câu 1]**

Cho đến khi có câu trả lời, bản thiết kế viết theo hướng: **bản mẫu tự xây bám sát yêu cầu RFP**. Câu trả lời không làm thay đổi đợt 1, nhưng quyết định làm sâu đến đâu ở đợt 3–5.

**Phương án thanh toán: "xuyên suốt, chuyển dần"** **[Đã chốt]**
- Hệ thống mới làm **cả** đề nghị thanh toán (ĐNTT) và luồng duyệt FAD (Kiểm soát 1 → Kiểm soát 2 → Phê duyệt), để người dùng chỉ làm việc trên một hệ thống.
- Giai đoạn đầu, lệnh đã duyệt được **chuyển sang PAS chỉ để chi tiền** qua Bank Gateway; trạng thái chi tiền lấy ngược về.
- Khi phân hệ thanh toán chạy ổn, IT nối thẳng Bank Gateway, chuyển các loại hồ sơ PAS còn lại và dữ liệu cũ, rồi tắt PAS (đợt 5).
- Các phương án đã cân nhắc: (1) Giữ PAS làm cả lập, duyệt và chi (Option 2 RFP): ít rủi ro nhất nhưng hai hệ thống, dễ lệch số liệu. (2) Thay PAS ngay (Option 1 RFP): một hệ thống nhưng rủi ro cao nhất, vì khâu chuyển tiền ra ngân hàng cần IT, ngân hàng, chứng thư số. Phương án 3 được chọn vì người dùng có một hệ thống ngay từ đầu, còn khâu rủi ro nhất được làm sau cùng bởi đúng người.

## 1. Vì sao làm

Hiện HSC đã có PAS (lập/duyệt đề nghị thanh toán, chuyển tiền qua Bank Gateway), IMS (gửi dữ liệu hoá đơn sang PAS) và SUN (hạch toán). Các khâu còn lại (lập ngân sách, quản lý NCC, báo giá, tờ trình, hợp đồng, đặt hàng, nghiệm thu, đánh giá sau mua, báo cáo) làm thủ công, theo dõi bằng Excel (file Budget Control). **[RFP][Đã chốt]**

Hệ quả: bước nào cũng chậm, không có audit trail, khó giám sát ngân sách của các phòng ban, tra cứu và trích xuất chứng từ mất nhiều thời gian. Báo cáo PAS hạn chế: chưa có API, không tuỳ chỉnh được, phụ thuộc vendor. **[RFP]**

## 2. Mục tiêu, ngoài phạm vi, phản mục tiêu

### Mục tiêu
1. Số hoá quy trình 11 bước (mục 4), chia nhiều đợt, đợt 1 là nền tảng. **[Đã chốt]**
2. Luồng duyệt **cấu hình được**: ngưỡng, lớp duyệt, đơn vị tham vấn là dữ liệu, không viết cứng. HSC tự điều chỉnh khi quy trình thay đổi. **[Đã chốt][RFP]**
3. Audit trail đầy đủ, không sửa/xoá được. **[RFP: R59, R86]**
4. **Khắc phục hạn chế của PAS**: hiện số dư ngân sách và chặn/cảnh báo vượt, duyệt tự động theo hạn mức, hồ sơ nhiều nguồn ngân sách, báo cáo tuỳ chỉnh có API, đưa báo cáo Budget Control vào hệ thống. **[RFP]**
5. Đạt mức an toàn thông tin cho công ty chứng khoán. Đây là **điều kiện loại** trong RFP, nên bản tự xây cũng phải đạt cùng mức đó. **[RFP: R61]**

### Ngoài phạm vi
- Chuyển tiền trực tiếp qua ngân hàng, đối soát sao kê, chuyển dữ liệu PAS cũ (R39, R40, R43) **cho đến đợt 5**; đợt 5 do IT chủ trì cùng ngân hàng. **[Đã chốt]**
- Ghi sổ kế toán: vẫn ở SUN; hệ thống chỉ cung cấp dữ liệu. **[Đã chốt]**
- Mở rộng "Công tác" (R54–R58, mức Nên có): để sau đợt 4. **[Đề xuất]**
- Ứng dụng di động riêng (giao diện web vẫn dùng được trên điện thoại).

### Phản mục tiêu
- Người dùng quay lại email/giấy vì hệ thống rườm rà hơn cách cũ.
- Audit trail sửa được, hoặc có thao tác không được ghi.
- Quy tắc duyệt phải sửa code mới đổi được.
- Lệnh chi trên hệ thống mới và PAS (giai đoạn chuyển tiếp) lệch nhau mà không ai phát hiện. Cần đối chiếu tự động hằng ngày giữa lệnh đã chuyển và trạng thái PAS trả về.
- Dữ liệu thật hoặc tài liệu nội bộ HSC nằm trên hạ tầng cá nhân.

## 3. Ràng buộc

| Ràng buộc | Nguồn |
|---|---|
| Máy chủ nội bộ HSC: **Ubuntu 26.04, chạy Docker**; phải bàn giao **bộ cài đặt Docker** cho ứng dụng | [IT] |
| CSDL **PostgreSQL**; đăng nhập **Microsoft Entra ID**; HRIS có API | [IT] |
| Email gửi qua **máy chủ mail công ty**, cấu hình trong mục **Cài đặt** trên giao diện | [IT] |
| Lưu trữ chứng từ **vĩnh viễn**; ký số dùng **hệ thống của FPT**; **IT phụ trách sao lưu** | [IT] |
| Mã nguồn quản lý tập trung trên repo GitHub của dự án (đã được IT chấp thuận) | [IT] |
| Truy cập nội bộ cho nhân viên; phần dành cho NCC mở ra Internet, IT whitelist IP của NCC | [IT] |
| Người dùng cùng Claude làm bản mẫu; IT tiếp nhận vận hành | [Đã chốt] |
| Tích hợp: SSO, SUN, PAS, IMS, email, Excel; HRIS (đợt sau) | [Đã chốt][RFP] |
| PAS chưa có API; IMS và HRIS do FPT quản lý; một số mẫu mail PAS phụ thuộc VTIDC. Kết nối thật phụ thuộc bên thứ ba | [RFP] |
| An toàn thông tin cho công ty chứng khoán; Nghị định 13/2023/NĐ-CP, Luật Bảo vệ dữ liệu cá nhân 2025; chính sách nội bộ HSC | Văn bản cụ thể cần **Pháp chế/IT xác nhận** |
| Bản mẫu **chỉ dùng dữ liệu giả** | [Đề xuất] |

## 4. Quy trình nghiệp vụ (đã xác nhận + RFP)

| Giai đoạn | Bước | Nội dung chính | Hệ thống |
|---|---|---|---|
| Chuẩn bị | 1. Lập ngân sách | Lập theo Khối/Phòng/mã chi phí/dự án (căn cứ năm trước; giữ nguyên hoặc thay đổi/thêm dự án); duyệt; bổ sung; điều chỉnh/điều chuyển (có duyệt); dự báo theo thực chi | Mới |
| | 2. NCC | Đăng ký, thẩm định; danh sách NCC đầu năm do BMS duyệt; đánh giá định kỳ/bổ sung; rủi ro, tạm ngưng, danh sách đen; khai báo xung đột lợi ích | Mới |
| | 3. Tìm nguồn | Mô tả nhu cầu, yêu cầu kỹ thuật; tối thiểu 03 báo giá; chỉ mời NCC trong danh sách; RFQ/RFI, đấu thầu tập trung, đóng thầu tự động; so sánh giá và tiêu chí; **mua ngoại lệ** (khẩn cấp, chỉ định, NCC duy nhất) có luồng duyệt riêng | Mới |
| Xin duyệt | 4. Tờ trình, tiền kiểm, duyệt | Tờ trình chủ trương/mua sắm theo mẫu; nhiều nguồn ngân sách (Công ty + Công đoàn); tham vấn chuyên môn; FAD tiền kiểm (ngân sách còn lại, thẩm quyền, tính hợp lý, tính cần thiết); trả lại nếu chưa đạt; **giữ chỗ ngân sách**; duyệt theo thẩm quyền, **duyệt thay khi vắng mặt**; trường hợp không cần tờ trình thì đi thẳng tới mua hàng | Mới |
| | 5. Hợp đồng | Mua hàng / dịch vụ / nguyên tắc; soạn, đàm phán; Kế toán (FAD) + Pháp chế review; duyệt trước khi ký; ký số; lưu bản gốc; phụ lục; nhắc gia hạn trước 3–6 tháng; đợt thanh toán | Mới |
| Thực hiện | 6. Mua sắm | Đơn đặt hàng; nhận hàng đủ/từng phần; nghiệm thu theo giai đoạn; điều chỉnh đơn, trả hàng; **hoàn trả ngân sách** phần không dùng | Mới |
| | 7. Đánh giá sau mua | Khi hoàn thành hoặc sau chu kỳ (thường 1 năm); bảng điểm tiêu chí tuỳ biến; kết quả đưa vào đánh giá NCC năm sau | Mới |
| Chi tiền, ghi sổ | 8. Thanh toán | Kế thừa chứng từ; đối chiếu 3 chiều (PO – nghiệm thu – hoá đơn); rà soát hoá đơn qua IMS; xử lý chênh lệch; **lập ĐNTT và duyệt FAD trên hệ thống mới**; chuyển lệnh đã duyệt sang PAS để chi (đến đợt 5: chi thẳng qua Bank Gateway) | Mới (+ PAS chỉ chi tiền, tạm thời) |
| | 9. Hạch toán | Hạch toán trên SUN; hệ thống cung cấp dữ liệu kỳ dịch vụ để trích trước/phân bổ, thông tin tài sản cố định | SUN (giữ) |
| Giám sát | 10. Báo cáo | Chi tiêu/ngân sách, NCC, hợp đồng, tiết kiệm, tuân thủ (đủ 03 báo giá, ngoại lệ, quá hạn), timeline từng bước duyệt; tuỳ chỉnh, có API | Mới |
| | 11. Hậu kiểm | Chọn mẫu, checklist, ghi nhận phát hiện, theo dõi khắc phục đến khi đóng; cung cấp chứng từ cho kiểm toán | Mới |

**Vai trò:** Bộ phận đề nghị (người đề nghị, thư ký, người mua hàng, bộ phận sử dụng); Owner budget; Tham vấn chuyên môn (ITD, DTI, DATA, HRM, COM, GRC); FAD (tiền kiểm, kiểm soát, hạch toán, hậu kiểm); 3 lớp duyệt: GĐNV/GĐĐH → Ban Mua Sắm (BMS) → CEO/TGĐ; HĐQT; CFO; Pháp chế (GRC).

**Bảng thẩm quyền mẫu** (trích HSC_Chính sách Mua sắm, mục 7; chỉ là **dữ liệu mẫu** để kiểm thử, không viết cứng):

| Nhóm | Ngưỡng / tờ trình | Đề nghị | Tham vấn | Phê duyệt |
|---|---|---|---|---|
| Trong ngân sách | < 200tr | – | GĐĐH | GĐNV/TP |
| | 200tr – 2 tỷ | TP | GĐĐH/GĐ/TP-TCKT | GĐĐH |
| | > 2 tỷ | GĐĐH | GĐĐH/GĐ/TP-TCKT | BMS |
| Ngoài ngân sách | < 50tr, luỹ kế < 200tr/năm | TP | GĐĐH/GĐ/TP-TCKT | GĐĐH |
| | 50 – 300tr, luỹ kế < 2 tỷ/năm | GĐĐH | GĐĐH/GĐ/TP-TCKT | BMS |
| | 300tr – 3 tỷ, luỹ kế < 2% chi phí cố định năm | GĐĐH | GĐĐH-TCKT | TGĐ |
| | > 3 tỷ hoặc luỹ kế ≥ 2% | TGĐ | GĐĐH-TCKT | HĐQT |

Duyệt thanh toán: GĐĐH-TCKT (= GĐNV/GĐĐH + CFO). Quy trình duyệt FAD trên chứng từ thanh toán: Kiểm soát 1 → Kiểm soát 2 → Phê duyệt → Thanh toán → Hoàn thành → Lưu kho hồ sơ. **[RFP]**

### 4.1 Hai điểm chưa nhất quán giữa các tài liệu (đã chốt)
1. **Chi phí chưa có ngân sách** **[Đã chốt]**: hệ thống **không cho mua sắm** (chặn tạo/nộp tờ trình) và yêu cầu làm thủ tục xin phê duyệt.
   - Cách hiểu của Claude, cần xác nhận **[Đề xuất]**: thủ tục đó là **Đề nghị bổ sung/điều chuyển ngân sách**, được duyệt theo thẩm quyền ở nhóm "Ngoài ngân sách" của bảng thẩm quyền (kể cả hạn mức luỹ kế). Khi được duyệt, ngân sách được ghi tăng, và tờ trình đi theo luồng "Trong ngân sách". Hai tài liệu khớp nhau theo cách này.
   - Khi chặn, hệ thống hiện số còn thiếu và nút tạo sẵn đề nghị bổ sung ngân sách với dữ liệu điền sẵn từ tờ trình.
2. **NCC ngoài danh sách** **[Đã chốt]**: phải **xin phê duyệt bổ sung NCC**. Có một số điều kiện ngoại lệ, người dùng cung cấp sau → thiết kế **bộ quy tắc ngoại lệ cấu hình được** (điều kiện, ví dụ ngưỡng tiền, loại chi phí, mua khẩn cấp; kèm lý do bắt buộc và người duyệt ngoại lệ). Mặc định khi chưa có quy tắc: không có ngoại lệ.

## 5. Phương án công nghệ đã cân nhắc

| Phương án | Ưu | Nhược | Kết quả |
|---|---|---|---|
| **A. Python (Django) + PostgreSQL** | Nhanh có bản mẫu; có sẵn trang quản trị, phân quyền, chống tấn công web phổ biến; code dễ đọc; chạy Linux/Windows; đổi được sang SQL Server | IT HSC có thể phải học thêm | **Được chọn** [Đã chốt] |
| B. .NET + SQL Server | Hợp hệ sinh thái Microsoft, nối AD thuận | Code dài; tự làm trang quản trị; chậm hơn ~30–50% (ước lượng) | Không chọn |
| C. Power Apps + SharePoint | Nhanh nhất, có sẵn M365 | Chạy cloud, trái yêu cầu máy chủ nội bộ; audit trail và luỹ kế khó làm chặt; phí theo đầu người | Loại |

Rủi ro đã chấp nhận: chưa biết chuẩn công nghệ của IT HSC. Giảm thiểu: hỏi IT sớm (mục 11).

## 6. Kiến trúc **[Đề xuất]**

```
                 MẠNG NỘI BỘ HSC / VPN
Trình duyệt nhân viên ──HTTPS──► Nginx ──► Django (Gunicorn) ──► PostgreSQL 16
                                              │                 (dữ liệu + audit + sổ ngân sách)
                                              ├──► Kho file chứng từ (ngoài thư mục web)
                                              ├──► Worker nền (email, nhắc việc, chuyển cấp, xuất SUN/PAS)
                                              └──► API nội bộ (cho PAS: danh sách NCC, số dư ngân sách)

                 VÙNG DMZ (đợt 2 trở đi, nếu IT đồng ý)
NCC trên Internet ──HTTPS──► Cổng NCC (ứng dụng tách riêng, quyền hạn chế) ──► API giới hạn ──► hệ thống nội bộ
```

- Python 3.12, Django 5.2 LTS (hỗ trợ đến 2028).
- Giao diện: Django template + HTMX, không SPA. Thư viện CSS/JS đóng gói sẵn, không gọi CDN ngoài.
- **Bộ cài đặt Docker** cho Ubuntu 26.04 **[IT]**: Docker Compose (app, db, nginx, worker), file `.env.example`, script cài đặt/nâng cấp/sao lưu/khôi phục, hướng dẫn vận hành. IT cài bằng một lệnh; nâng cấp phiên bản không mất dữ liệu (tự chạy migration).
- **Cấu hình qua giao diện** (mục Cài đặt, chỉ quản trị hệ thống): máy chủ email (SMTP), tham số tích hợp (PAS, IMS, HRIS, Entra ID), bảng tỷ giá, thời hạn xử lý. Mật khẩu/khoá lưu **mã hoá** trong CSDL bằng khoá nằm ở biến môi trường; mọi thay đổi cấu hình ghi audit. **[IT + Đề xuất]**
- Việc nền: bảng outbox trong PostgreSQL + worker; không Redis/Celery ở đợt 1.
- API nội bộ: REST, xác thực bằng token cấp cho từng hệ thống, chỉ mở trong mạng nội bộ. Đáp ứng R13, R24, R48.
- **Phần dành cho NCC** **[IT: mở Internet, whitelist IP NCC]**: tách thành **container và tên miền riêng**, xác thực riêng (tài khoản NCC, không dùng Entra ID), chỉ có các chức năng NCC (hồ sơ năng lực, nhận yêu cầu báo giá, gửi báo giá, xem kết quả), qua Nginx có whitelist IP. Whitelist là **lớp bảo vệ bổ sung**, không thay cho xác thực và phân quyền. Lưu ý: nhiều NCC nhỏ không có IP tĩnh, nên cần phương án dự phòng: đường dẫn dùng một lần gửi qua email, có hạn dùng, kèm mã OTP. **[Đề xuất]**
- **Tỷ giá:** bảng tỷ giá theo ngày, cấu hình trên giao diện, thay cho tỷ giá viết cứng trong công thức Excel hiện nay (7.5).
- **Tiền tệ:** số tiền lưu dạng Decimal kèm loại tiền (VND, USD, HKD…) và tỷ giá tại ngày lập; quy đổi VND để so ngưỡng duyệt và trừ ngân sách. **[RFP; thay quyết định "chỉ VND" ở bản trước]**
- Năm tài chính = năm dương lịch. **[Đề xuất]**
- Giao diện tiếng Việt.

## 7. Các thành phần của đợt 1 (nền tảng)

| Thành phần | Nội dung | Tiêu chí RFP |
|---|---|---|
| `accounts` | Người dùng, Khối/Phòng ban, chức danh, vai trò. Đăng nhập **Microsoft Entra ID (OIDC)**; đồng bộ cơ cấu tổ chức, chức danh từ **HRIS API**. Bản mẫu: tài khoản nội bộ + MFA và bộ giả lập Entra/HRIS | R59 |
| `audit` | Nhật ký chỉ-ghi-thêm (8.3); tra cứu; xuất cho kiểm toán | R59, R86 |
| `documents` | Kho chứng từ (7.4): đính kèm nhiều file/hồ sơ, xem trước không cần tải, checklist loại chứng từ theo loại hồ sơ, mã băm SHA-256, trích chữ từ PDF và tìm kiếm toàn văn, thời hạn lưu trữ | R87 |
| `workflow` | Bộ máy luồng duyệt cấu hình được (7.1), uỷ quyền (7.2), nhắc việc và chuyển cấp khi quá hạn | R20–R23, R63 |
| `budget` | Sổ ngân sách (7.3): lập, duyệt, điều chỉnh/điều chuyển có duyệt, giữ chỗ, giải phóng, hoàn trả; số dư thời gian thực; nhập Excel | R1, R18, R19 |
| `vendors` | Danh mục NCC cơ bản: thông tin, mã số thuế, tài khoản ngân hàng, nhóm hàng hoá/dịch vụ, trạng thái (hiệu lực/chờ duyệt/tạm ngưng/danh sách đen); nhập Excel. Quy trình đánh giá, duyệt NCC để đợt 2 | (nền cho R2–R13) |
| `requisitions` | Tờ trình: theo mẫu, dòng hàng, đa tiền tệ, **nhiều nguồn ngân sách**, 03 báo giá đính kèm (hoặc lý do ngoại lệ), tham vấn, FAD tiền kiểm (màn hình riêng), duyệt end-to-end; lưu nháp, sao chép | R14–R17, R78 |
| `notifications` | Email qua máy chủ mail công ty (cấu hình SMTP trên giao diện, có nút gửi thử); 2 mẫu (chính thức, xin ý kiến), mẫu mail chỉnh được không cần sửa code; thông báo trong hệ thống; "Việc chờ tôi" | R62, R83 |
| `integrations` | Bộ chuyển đổi SSO, SUN, PAS, IMS, HRIS, email. Đợt 1 dùng **bản giả lập** | (nền cho R60) |
| `ui` (dùng chung) | Bảng dữ liệu chuẩn: lọc (lưu bộ lọc), sắp xếp nhiều cột, tìm nhanh, cố định tiêu đề, phân trang, tổng phụ, định dạng tiền + số tiền bằng chữ, gợi ý chọn, tự điền, kiểm tra khi nhập (MST, số tài khoản, trùng), chọn nhiều + duyệt hàng loạt, xuất Excel/PDF theo bộ lọc, liên kết chứng từ | R65–R81, R88 |

### 7.1 Bộ máy luồng duyệt
- **Chính sách duyệt** có phiên bản, hiệu lực từ ngày. Gồm các **quy tắc**: điều kiện (trong/ngoài ngân sách, khoảng tiền quy đổi VND, luỹ kế năm, loại chi phí, phương án mua sắm (dự án/BAU/công tác…), phòng ban, mua ngoại lệ) → chuỗi **bước** (đề nghị, owner budget, tham vấn, FAD tiền kiểm, lớp 1/2/3, HĐQT).
- Bước gắn **vai trò + phạm vi** (ví dụ "Trưởng phòng của phòng lập", "Đơn vị quản lý của dòng ngân sách", "đơn vị tham vấn theo nội dung"). Tờ trình dùng ngân sách của nhiều đơn vị sinh **nhánh xác nhận song song**, mỗi đơn vị quản lý một nhánh; đủ các nhánh mới đi tiếp.
- Bước **bắt buộc chấp thuận** hoặc **chỉ cho ý kiến**: cấu hình được. Ý kiến tham vấn hiển thị cho người duyệt trước khi quyết định.
- Khi nộp, hệ thống **chụp phiên bản chính sách**; sửa chính sách sau không ảnh hưởng hồ sơ đang chạy.
- **Tự xác định luồng**, người lập không chọn tay. Luỹ kế ngoài ngân sách tự tính, phạm vi cấu hình được.
- **Duyệt tại cuộc họp** (BMS, HĐQT): người được giao ghi nhận kết quả + đính kèm biên bản.
- Thao tác: chấp thuận, từ chối, **trả lại bổ sung** (tạo phiên bản mới, giữ lịch sử), duyệt hàng loạt.
- **Thời hạn xử lý (SLA)** cho từng bước: nhắc trước hạn, nhắc quá hạn, chuyển cấp khi quá hạn.
- **Cảnh báo chia nhỏ tờ trình:** cùng phòng + cùng NCC/khoản mục trong N ngày, tổng vượt ngưỡng → cảnh báo FAD tiền kiểm.

### 7.2 Uỷ quyền duyệt thay **[RFP: R21 bắt buộc]**
- Người duyệt (hoặc quản trị theo văn bản) tạo uỷ quyền: người nhận, từ ngày – đến ngày, phạm vi (loại hồ sơ, hạn mức tối đa, phòng ban), đính kèm văn bản uỷ quyền.
- Hồ sơ đến hạn duyệt trong thời gian uỷ quyền được chuyển cho người nhận; hiển thị và ghi audit "X duyệt thay Y theo uỷ quyền số…".
- Ràng buộc: không uỷ quyền vượt thẩm quyền của chính mình; người nhận không được duyệt hồ sơ do chính họ lập; không uỷ quyền lại (không uỷ quyền bắc cầu). **[Đề xuất]**
- Chi tiết quy định uỷ quyền của HSC: **[Mở, mục 12]**.

### 7.3 Sổ ngân sách **[RFP + file Budget Control + Đề xuất cách làm]**

**Chiều ngân sách** (đối chiếu với file Budget Control thực tế, 7.5):

| Chiều | Trong file Budget Control | Ghi chú thiết kế |
|---|---|---|
| Năm, tháng | Ngân sách lập **theo tháng** (cột Date của Budget_Expense/Budget_Capex) | Bút toán ngân sách gắn kỳ tháng |
| Đơn vị quản lý ngân sách | 12 file: ADM, COM, DATA, DTI, HRM, ITD, OVH, PMO, Repair, RMD, T&E, UNION | **[Đã chốt]** Mỗi đơn vị được phân công **quản lý ngân sách tập trung** cho nhóm chi phí thuộc chức năng của mình, cho toàn công ty (không chỉ chi tiêu của chính đơn vị đó). UNION tương ứng nguồn Công đoàn |
| Mã chi phí (L8) | Ví dụ `AD_2.1.7D`; tiền tố theo đơn vị | Có cờ Capex/Opex |
| Main item | 01…17 (ví dụ "02. Chi phí thuê và quản lý VP") | Ánh xạ L8 → Main item **có thể đổi theo năm** (cột Main_2025/2026/2027): lưu theo phiên bản năm |
| Dự án (L10) | Ví dụ `Rental_FL7_26`, mặc định `BAU_ADM` | Có workstream, năm bắt đầu, phòng |
| Địa điểm | HSC (TP.HCM, HO), HNB (Hà Nội) | Ngân sách và báo cáo tách theo địa điểm |
| NCC (L9) | Loại hình, MST, tên | Nhập vào danh mục NCC |
| Owner budget, nguồn ngân sách | (từ RFP) | |

**Đơn vị quản lý ngân sách và người đề nghị** **[Đã chốt + Đề xuất cách làm]**
- Phòng đề nghị mua sắm **có thể khác** đơn vị quản lý ngân sách. Ví dụ, một phòng nghiệp vụ mua thiết bị CNTT dùng ngân sách do ITD quản lý.
- Một tờ trình **có thể lấy ngân sách từ nhiều đơn vị**. Mỗi dòng của tờ trình được phân bổ (theo số tiền) vào một hoặc nhiều dòng ngân sách; mỗi đơn vị quản lý liên quan **xác nhận ngân sách** ở một nhánh song song trước khi FAD tiền kiểm (RFP: "yêu cầu được gửi đến owner budget").
- **Vai trò "Quản trị Budget Control" (FAD)**: hiện một đầu mối FAD cập nhật toàn bộ 12 file. Trên hệ thống, vai trò này quản lý danh mục, nhập/điều chỉnh ngân sách theo hồ sơ đã duyệt, xem toàn bộ, nhưng không tự duyệt tờ trình.
- Quyền xem: người đề nghị thấy số dư khả dụng của dòng ngân sách mình chọn; đơn vị quản lý thấy toàn bộ ngân sách mình quản lý (kể cả phần phòng khác đã dùng); FAD thấy tất cả.

**Hai thước đo, kiểm soát theo chi phí phân bổ** **[Đã chốt]**
- *Thanh toán*: theo ngày chi tiền.
- *Chi phí*: phân bổ theo kỳ dịch vụ (ngày bắt đầu, số kỳ, chu kỳ Monthly/Quarterly/Yearly/Once-off), chia đều theo tháng. Ví dụ thuê văn phòng trả theo quý được phân bổ vào 3 tháng.
- Trong file, cột YTD và % sử dụng ngân sách tính trên **chi phí phân bổ** của năm, không tính trên số tiền đã thanh toán. Hệ thống làm giống vậy và vẫn báo cáo song song số thanh toán.

**Cách ghi nhận:** mọi biến động là **bút toán ngân sách** chỉ-ghi-thêm, gắn kỳ tháng. **[Đề xuất]** Ánh xạ với trạng thái trong file:

| Trạng thái trong Excel | Ý nghĩa (sheet Guide/Status) | Bút toán trong hệ thống | Trừ ngân sách |
|---|---|---|---|
| (Budget_Expense Original / Adjust) | Ngân sách gốc / điều chỉnh | Kế hoạch gốc / Điều chỉnh, Điều chuyển (cặp đối ứng) | – |
| Pending | Xin nhưng chưa thực hiện | **Giữ chỗ** (khi tờ trình được duyệt) | Có (giữ chỗ) |
| Pending transfer | Trả nhiều đợt, chưa kết chuyển | Giữ chỗ theo từng đợt | Có (giữ chỗ) |
| Normal | Đã thanh toán và phân bổ | **Chi phí ghi nhận** (giải phóng giữ chỗ tương ứng) | Có |
| Pending payment | Đã kết chuyển, chờ thanh toán | Chi phí ghi nhận, chưa thanh toán | Có |
| Accrual / Reversal | Trích trước / Hoàn trích | Trích trước / Hoàn trích | Có / hoàn lại |
| DEPRE | Khấu hao | Chi phí khấu hao (Capex) | Có |
| Forecast | Dự báo | **Dự báo**, không trừ ngân sách | Không |

- **Số dư khả dụng** (theo kỳ và luỹ kế năm) = Ngân sách (gốc + điều chỉnh) − Giữ chỗ − Chi phí ghi nhận. Hiển thị khi lập tờ trình. **Không đủ hoặc không có ngân sách thì chặn**, kèm lối tạo nhanh đề nghị bổ sung/điều chuyển (4.1).
- **Hợp đồng nhiều năm** (ví dụ thuê kho 3–5 năm): giữ chỗ phân theo kỳ của từng năm; phần năm sau trừ vào ngân sách năm sau khi có. Nếu ngân sách năm sau chưa được duyệt, hệ thống cảnh báo chứ không chặn. **[Đề xuất]**
- **Capex**: ngân sách đầu tư theo dõi riêng (Budget_Capex), chi phí ghi nhận qua khấu hao. Quy tắc chi tiết cần FAD giải thích. **[Mở]**
- **Tỷ giá**: từ bảng tỷ giá theo ngày (mục 6).
- **Đề nghị bổ sung/điều chuyển ngân sách** chạy trên bộ máy luồng duyệt (7.1).
- **Lập ngân sách năm**: sao chép từ năm trước (giữ nguyên / chỉnh / thêm dự án), nhập Excel theo mẫu Budget_Expense/Budget_Capex, trình duyệt. Dự báo theo thực chi: đợt 3.

### 7.4 Kho chứng từ và OCR **[Đã chốt phương án A: OCR mã nguồn mở chạy tại chỗ]**
- Mọi chứng từ nghiệp vụ mua hàng (tờ trình, báo giá, hợp đồng, PO, biên bản nghiệm thu, hoá đơn, ĐNTT) lưu tập trung, gắn với hồ sơ, tra cứu chéo được (drill-down).
- **Ba loại chứng từ, ba cách xử lý:**
  - Hoá đơn điện tử: đọc **file XML gốc** (Nghị định 123/2020), không dùng OCR. Đợt 3, kèm dữ liệu IMS.
  - PDF có sẵn chữ: **trích chữ trực tiếp** (miễn phí, chính xác). Đợt 1.
  - Bản scan/ảnh: **OCR chạy nền trên máy chủ HSC** bằng thư viện mã nguồn mở (Tesseract hoặc PaddleOCR, ngôn ngữ tiếng Việt), không gửi dữ liệu ra ngoài. Đợt 2. Chi phí: chỉ tài nguyên máy chủ (CPU, ổ đĩa), không phí bản quyền.
- **Tìm kiếm toàn văn** trên nội dung chứng từ + thông tin hồ sơ, dùng tính năng full-text sẵn có của PostgreSQL (không thêm hệ thống tìm kiếm riêng). Đợt 1.
- Tự bóc trường dữ liệu từ bản scan (số tiền, MST) để điền sẵn form: **để sau**, chỉ làm nếu thực tế cần.
- **Lưu trữ vĩnh viễn** **[IT]**: chứng từ không bao giờ bị xoá, kể cả bởi quản trị viên; không có chức năng xoá chứng từ đã gắn vào hồ sơ đã nộp (chỉ đánh dấu "thay thế bởi" bản mới). Sao lưu do IT phụ trách; bộ cài đặt có sẵn script sao lưu/khôi phục để IT dùng.
- Dung lượng tăng liên tục: cần IT dự trù ổ đĩa. Hệ thống có báo cáo dung lượng theo năm.
- **Ký số** **[IT: hệ thống của FPT]**: hợp đồng, biên bản ký qua hệ thống ký số FPT (đợt 2–3, chờ tài liệu API). Hệ thống lưu file đã ký và kết quả kiểm tra chữ ký.
- **DMS hiện có** (`dms.hsc.com.vn`): file Budget Control có đường dẫn tới hồ sơ thanh toán trên DMS. Cần làm rõ vai trò của DMS để tránh hai kho chứng từ trùng nhau. **[Mở, 12.7]**
- Bản gốc file không bao giờ bị ghi đè; bản OCR/chữ trích ra lưu riêng.

### 7.5 Phân tích file Budget Control (mẫu: Budget Control - ADM) **[Đã có file]**

File gốc **không lưu trong repo**: có tên người thật và số liệu thật.

**Cấu trúc file:**

| Sheet | Nội dung | Dùng trong hệ thống |
|---|---|---|
| Guide, Status | Ý nghĩa các trạng thái; trạng thái nào ghi nhận P&L | Bảng ánh xạ ở 7.3 |
| Budget_Expense / Budget_Capex | Ngân sách theo L8 × tháng × địa điểm: Original, Adjust, L10, ghi chú (~14.000 dòng) | Mẫu nhập ngân sách năm |
| Data new | Sổ chi tiết giao dịch 2021–2026 (~6.000 dòng): trạng thái, ngày thanh toán, kỳ phân bổ, số kỳ, chu kỳ, diễn giải, L8, L10, nguyên tệ, quy đổi VND, NCC, địa điểm, phòng thanh toán, người duyệt (tờ trình / ĐNTT / đối soát ngân sách In-Out), đường dẫn DMS, phân bổ theo năm và theo tháng | Chuyển thành **lịch sử chi phí** (chỉ đọc) để báo cáo có số thực tế các năm trước |
| L8_Code / L9_Code / L10_Code | Danh mục mã chi phí, NCC, dự án | Nhập danh mục |
| Budget 2026 | Báo cáo theo L8 và Main item: thực tế 3 năm trước, đề nghị thanh toán, đã thanh toán, YTD, dự báo, ngân sách (gốc/điều chỉnh), %, còn lại; tách HCM/HN | **Báo cáo tái tạo** (R49) |
| Reconcile BI | Đối chiếu ngân sách – chi phí theo L8 (đơn vị triệu đồng) cho BI | **Báo cáo tái tạo** + API xuất dữ liệu (R48) |

**Rủi ro tìm thấy trong file** (bằng chứng cho việc cần hệ thống; FAD kiểm tra lại các điểm 4, 5, 8):
1. **Tỷ giá viết cứng trong công thức** (USD 25.460, SGD 17.200, HKD 3.000), không đổi theo ngày.
2. **Người duyệt nhập tay**: cùng một người có nhiều cách viết (thừa dấu cách, thiếu ngoặc, có/không chức danh), nên không thống kê chính xác theo người duyệt được.
3. **Dữ liệu thiếu/không chuẩn**: khoảng 30% dòng (1.807/6.078) trống "Payment Dept."; 415 dòng trống ngày thanh toán; 22 dòng mã tiền tệ có dấu cách thừa.
4. Công thức "%" ở dòng tổng nhóm A tham chiếu lỗi (`#REF!`).
5. Cột "Payment Req" không đồng nhất: đa số dòng cộng cột K, một số dòng (ví dụ AD_10.1) cộng cột I.
6. Số ngân sách lẻ thập phân (ví dụ 6.250.000,000000001) do chia đều theo tháng bằng số thực.
7. Mỗi đơn vị một file, mã có tiền tố riêng; báo cáo toàn công ty phải gộp tay.
8. Cột "Last year allocated" ở Reconcile BI dùng mảng năm `{2025,…,2029,2023}`, cần FAD giải thích ý nghĩa.

**Kế hoạch chuyển dữ liệu** (đợt 1 làm công cụ, chạy thật ở đợt 4):
1. Nhập danh mục L8 (kèm Main item theo năm, Capex/Opex), L10, L9 (NCC: chuẩn hoá MST, gộp trùng).
2. Nhập ngân sách năm hiện hành từ Budget_Expense/Budget_Capex của 12 file (dùng số tiền Decimal, làm tròn đồng).
3. Nhập lịch sử Data new làm lịch sử chi phí chỉ đọc; người duyệt dạng văn bản giữ nguyên (không ánh xạ vào tài khoản).
4. Trước khi nhập, hệ thống xuất **báo cáo làm sạch**: dòng thiếu trường, mã không có trong danh mục, tiền tệ lạ. FAD sửa trên Excel rồi nhập lại.
5. **Đối chiếu sau chuyển**: tổng theo L8 × năm × địa điểm trên hệ thống phải khớp với sheet Budget 2026 và Reconcile BI.

## 8. Bảo mật thông tin

Chuẩn tham chiếu: **OWASP ASVS mức 2**. IT/ATTT HSC bổ sung chuẩn nội bộ. RFP coi ATTT là điều kiện loại; bản tự xây áp dụng cùng tiêu chuẩn.

### 8.1 Truy cập
- Hệ thống nội bộ chỉ truy cập trong mạng nội bộ/VPN; bắt buộc HTTPS.
- SSO công ty khi chạy thật; bản mẫu có MFA. Khoá tạm sau nhiều lần sai; hết phiên sau 30 phút không thao tác. **[Đề xuất]**
- Phân quyền theo vai trò + theo dữ liệu: chỉ thấy hồ sơ của phòng mình, hồ sơ mình là owner budget, hoặc hồ sơ được giao xử lý.
- **Phân tách nhiệm vụ** (cứng trong code): người tạo không tự duyệt (R16); người tạo NCC không tự duyệt NCC đó; người được uỷ quyền không duyệt hồ sơ mình lập; quản trị kỹ thuật không duyệt nghiệp vụ.
- **Khai báo xung đột lợi ích** (R5, đợt 2): người đề xuất và hội đồng chọn NCC khai báo trước khi xem/chấm báo giá; lưu vào audit.

### 8.2 Ứng dụng
- Chống SQL injection, XSS, CSRF, clickjacking bằng cơ chế sẵn có của Django + header bảo mật (CSP, HSTS…).
- Kiểm tra mọi dữ liệu nhập (form, Excel, API); file Excel đọc như dữ liệu, không chạy macro/công thức.
- File tải lên: danh sách loại cho phép, giới hạn dung lượng, lưu ngoài thư mục web, đổi tên ngẫu nhiên; IT có thể nối quét virus (ClamAV).
- API: token riêng cho từng hệ thống, quyền tối thiểu, giới hạn tần suất, ghi log mọi lần gọi.
- Phần dành cho NCC (đợt 2+): container và tên miền riêng, whitelist IP tại Nginx (IT), tài khoản NCC chỉ thấy dữ liệu của chính NCC đó, chống dò mật khẩu, đường dẫn dùng một lần có hạn cho NCC không có IP tĩnh; kiểm thử xâm nhập riêng trước khi mở ra Internet.

### 8.3 Audit trail
- Ghi mọi sự kiện (tạo, sửa (kèm giá trị trước/sau), nộp, duyệt, duyệt thay, từ chối, đăng nhập, đổi cấu hình, tải file, gọi API) vào bảng riêng: ai, lúc nào, từ đâu, làm gì.
- Bảng **chỉ ghi thêm**: tài khoản CSDL của ứng dụng không có quyền sửa/xoá; trigger chặn sửa/xoá.
- **Chuỗi băm:** mỗi bản ghi chứa mã băm bản ghi trước; kiểm tra định kỳ phát hiện sửa trực tiếp trong CSDL.
- Báo cáo **timeline từng bước duyệt** lấy từ audit trail. **[RFP]**

### 8.4 Dữ liệu
- Mật khẩu, khoá bí mật nằm trong biến môi trường trên máy chủ, **không đưa vào git**.
- Sao lưu CSDL và kho file hằng ngày; kiểm tra khôi phục định kỳ (RFP chấm "Backup plan").
- Dữ liệu cá nhân và thông tin tài khoản ngân hàng NCC ở mức tối thiểu; che bớt khi hiển thị cho người không cần.

### 8.5 Quy trình phát triển
- Kiểm thử tự động cho logic nghiệp vụ, đặc biệt luồng duyệt, uỷ quyền, sổ ngân sách, phân quyền.
- Mỗi lần đẩy code: kiểm thử, `pip-audit`, `bandit`, `gitleaks`.
- Trước khi chạy thật: IT/ATTT rà soát code và pentest.

### 8.6 Nơi lưu code và tài liệu
IT đã chấp thuận: mã nguồn quản lý tập trung trên repo GitHub của dự án (`hdbdien2511/procurement-fad`), được dùng công cụ AI hỗ trợ lập trình. **[IT]** Vẫn giữ nguyên tắc:
1. Repo ở chế độ **Private**.
2. **Không** đưa vào repo: dữ liệu thật, file chính sách/RFP/Budget Control gốc, tên/email nhân viên thật, số liệu thật. Dữ liệu mẫu trong `sample-data/` là dữ liệu giả, tạo theo cấu trúc file thật.
3. Bảng thẩm quyền ở mục 4 là bản trích để thiết kế; nếu cần, thay bằng số giả.

## 9. Cấu trúc thư mục dự án **[Đề xuất]**

```
procurement-fad/
├── README.md                  Giới thiệu, cách chạy thử
├── CLAUDE.md                  Hướng dẫn cho Claude khi làm việc trên repo
├── docs/                      TÀI LIỆU (phần người dùng làm chủ)
│   ├── 01-nghiep-vu/          Quy trình, thuật ngữ, yêu cầu nghiệp vụ, ma trận truy vết RFP
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
│   │   ├── workflow/          Luồng duyệt, uỷ quyền, SLA
│   │   ├── budget/            Sổ ngân sách
│   │   ├── vendors/           Nhà cung cấp
│   │   ├── requisitions/      Tờ trình mua sắm
│   │   ├── notifications/     Email, việc chờ xử lý
│   │   ├── integrations/      SSO, SUN, PAS, IMS, HRIS (giả lập → thật)
│   │   ├── api/               API nội bộ cho PAS và báo cáo
│   │   └── ui/                Bảng dữ liệu, bộ lọc, xuất file dùng chung
│   ├── templates/             Giao diện (HTML)
│   └── static/                CSS, JS, icon (đóng gói sẵn)
├── tests/                     Kiểm thử tự động
├── sample-data/               Dữ liệu GIẢ (Excel mẫu ngân sách, NCC)
├── deploy/                    Docker Compose, Nginx, .env.example
├── scripts/                   Tiện ích (tạo dữ liệu mẫu, sao lưu…)
├── .github/workflows/         Kiểm tra tự động mỗi lần đẩy code
├── pyproject.toml             Danh sách thư viện
├── .gitignore                 Chặn file nhạy cảm (.env, dữ liệu, file tải lên, tài liệu gốc)
└── .claude/                   Skills cho Claude (đã có)
```

Đợt 2–3 thêm: `sourcing` (yêu cầu báo giá, đấu thầu, so sánh, ngoại lệ), `contracts`, `purchasing` (PO, nhận hàng, nghiệm thu), `evaluation` (đánh giá NCC), `payments` (ĐNTT, đối chiếu, duyệt FAD, cổng chi tiền: PAS → Bank Gateway), `reporting`, `post_audit`; dự án riêng `vendor-portal/` cho cổng NCC (nếu làm).

**Cổng chi tiền** (`payments`): mọi lệnh chi đã duyệt đi qua một điểm duy nhất với hai bộ chuyển đổi, "PAS" (đợt 3–4) và "Bank Gateway" (đợt 5). Đổi đích đến là đổi cấu hình, không viết lại luồng ĐNTT. Lệnh chi bị khoá sau khi duyệt: không sửa số tiền, người nhận, tài khoản; muốn đổi phải huỷ và lập lại.

**Cách người dùng làm việc với cấu trúc này:** người dùng làm chủ `docs/01-nghiep-vu/` (quy trình, quy định, ma trận truy vết) và `docs/04-kiem-thu/` (kịch bản kiểm thử). Claude viết `src/`, `tests/`, `deploy/` theo tài liệu đó; mỗi thay đổi có kiểm thử chạy được.

## 10. Lộ trình và truy vết RFP

| Đợt | Nội dung | Tiêu chí RFP | Kết quả kiểm chứng được |
|---|---|---|---|
| 0. Chuẩn bị | Repo, tài liệu nghiệp vụ, câu hỏi gửi IT, dữ liệu giả; chốt mục 0 và 4.1 | – | IT trả lời mục 11 |
| **1. Nền tảng** | Mục 7 | R1 (phần lập/điều chỉnh), R14–R23, R59, R62–R63, R65–R81, R83, R86–R88 | Một tờ trình (2 nguồn ngân sách, USD) chạy từ lập → tham vấn → FAD tiền kiểm → duyệt đủ lớp theo bảng mẫu, có duyệt thay, email, audit, chứng từ; giữ chỗ ngân sách đúng; người lập không tự duyệt được |
| 2. NCC, tìm nguồn, hợp đồng | Đăng ký/đánh giá/duyệt NCC đầu năm, rủi ro, danh sách đen, xung đột lợi ích; yêu cầu báo giá, so sánh, đấu thầu, mua ngoại lệ; hợp đồng, review, phụ lục, nhắc gia hạn; API NCC cho PAS; OCR bản scan | R2–R13, R25–R28 | Từ nhu cầu → 03 báo giá → chọn NCC → hợp đồng đã duyệt |
| 3. Thực hiện, thanh toán, báo cáo | PO, nhận hàng/nghiệm thu từng phần, hoàn trả ngân sách; đánh giá sau mua; **ĐNTT theo yêu cầu mua sắm (1 lần/nhiều đợt) và không qua yêu cầu mua sắm** (tạm ứng, hoàn ứng, chi BAU); đối chiếu 3 chiều, IMS, chênh lệch hoá đơn; duyệt FAD Kiểm soát 1 → 2 → Phê duyệt; chuyển lệnh sang PAS + nhận trạng thái; đọc XML hoá đơn điện tử; dữ liệu cho SUN; báo cáo, dashboard, hậu kiểm; in mẫu | R24, R29–R37, R41–R42, R44–R53, R82, R84–R85, R89; một phần R38 | Hồ sơ đi hết vòng đời trên một hệ thống; PAS chỉ còn bước chi tiền; báo cáo Budget Control tái tạo được |
| 4. Bàn giao IT | Entra ID, kết nối thật PAS/IMS (API) và SUN (Excel), HRIS; chuyển dữ liệu Budget Control; rà soát bảo mật và pentest (IT: thực hiện ở giai đoạn này, chưa cần trong lúc phát triển); bộ cài đặt Docker trên Ubuntu 26.04; UAT, đào tạo, go-live (PAS vẫn chi tiền) | R60, R61, R64 | IT ký nhận vận hành |
| 5. Thay PAS (IT chủ trì) | Nối thẳng Bank Gateway (ký lệnh, chứng thư số), kết quả chi thật từ ngân hàng, đối soát sao kê, chuyển hết loại hồ sơ PAS còn lại và dữ liệu cũ, nối IMS trực tiếp; chạy song song rồi tắt PAS | R38, R39, R40, R43 | Một kỳ chạy song song không chênh lệch; ngân hàng và ATTT nghiệm thu |
| Sau | Cổng NCC ra Internet; mở rộng Công tác | R54–R58 (+ phần portal của R2, R8) | Quyết định riêng |

R13 và R24 (API NCC, số dư ngân sách cho PAS) chỉ cần khi PAS còn lập hồ sơ riêng; với phương án đã chọn, vẫn làm ở mức tối thiểu cho giai đoạn chuyển tiếp.

## 11. Trả lời của IT (27/11/2026) và việc còn lại

| # | Chủ đề | Trả lời của IT | Ảnh hưởng thiết kế |
|---|---|---|---|
| 1 | Máy chủ | Ubuntu 26.04, chạy Docker; yêu cầu bộ cài đặt Docker | Mục 6: bàn giao bộ cài đặt |
| 2 | CSDL | PostgreSQL | Đúng thiết kế |
| 3 | Đăng nhập, HRIS | Microsoft Entra ID; HRIS có API | OIDC với Entra ID; đồng bộ tổ chức từ HRIS |
| 4 | Email | Máy chủ mail công ty, cấu hình trong mục Cài đặt trên giao diện | Màn hình cấu hình SMTP, mật khẩu mã hoá |
| 5 | PAS | Có bộ API; cần xin tài liệu từ vendor PAS | **Việc còn lại:** xin tài liệu API PAS (tạo lệnh chi, lấy trạng thái) |
| 6 | SUN, IMS | SUN và IMS xuất Excel; IMS có API | SUN: nhập/xuất Excel theo mẫu; IMS: API (ưu tiên), Excel dự phòng. **Việc còn lại:** mẫu file SUN, tài liệu API IMS |
| 7 | Chuẩn bảo mật, pentest | Làm ở giai đoạn sau, chưa cần trong lúc phát triển | Vẫn áp dụng ASVS mức 2 khi viết code để pentest sau không phải sửa nhiều |
| 8 | NCC truy cập | Ứng dụng ra Internet, IT whitelist IP NCC | Phần NCC tách container/tên miền, whitelist là lớp bổ sung; dự phòng cho NCC không có IP tĩnh |
| 9 | Mã nguồn, AI | Được; mã nguồn quản lý tập trung trên repo GitHub của dự án | Mục 8.6 |
| 10 | Lưu trữ, ký số, sao lưu | Lưu vĩnh viễn; ký số của FPT; IT phụ trách sao lưu | Không xoá chứng từ; tích hợp ký số FPT; script sao lưu cho IT. **Việc còn lại:** tài liệu API ký số FPT |

Câu 11 (hướng phối hợp với RFP) chưa có trả lời.

## 12. Câu hỏi mở cho người dùng
1. **Quan hệ với RFP** [Mở]: (a) bản mẫu làm rõ yêu cầu, (b) phương án tự xây, hay (c) bổ trợ?
2. **Quy định uỷ quyền của HSC** [Mở, không chặn đợt 1].
3. **Điều kiện ngoại lệ NCC ngoài danh sách** [Mở; cần cho đợt 2].
4. **Xác nhận cách hiểu 4.1 câu 1**: thủ tục khi chưa có ngân sách = đề nghị bổ sung/điều chuyển ngân sách, duyệt theo nhóm "Ngoài ngân sách".
5. ~~Kiểm soát theo chi phí phân bổ?~~ **Đã chốt: có.**
6. ~~12 đơn vị Budget Control?~~ **Đã chốt**: đơn vị được phân công quản lý ngân sách tập trung theo chức năng; FAD quản lý toàn bộ file; tờ trình có thể lấy ngân sách từ nhiều đơn vị. Còn lại: danh sách cụ thể đơn vị nào quản lý nhóm chi phí nào (OVH, Repair, T&E…) để cấu hình, cung cấp khi chuẩn bị dữ liệu.
7. **DMS** (`dms.hsc.com.vn`) là hệ thống gì, đang lưu những chứng từ nào? Có cần kết nối hay thay thế không? [Mở]
8. Quy tắc ngân sách **Capex** và khấu hao. [Mở, đợt 3]

## 13. Các quyết định Claude tự đưa ra (để người dùng rà)
- Giao diện render phía máy chủ + HTMX, không SPA.
- Không Redis/Celery ở đợt 1; dùng outbox trong PostgreSQL.
- Đa tiền tệ, quy đổi VND theo tỷ giá ngày lập để so ngưỡng và trừ ngân sách.
- Năm tài chính = năm dương lịch.
- Sổ ngân sách theo kiểu bút toán chỉ-ghi-thêm.
- Hết phiên sau 30 phút; MFA cho tài khoản nội bộ ở bản mẫu.
- Audit trail chỉ-ghi-thêm + chuỗi băm.
- Phân tách nhiệm vụ cứng trong code.
- Uỷ quyền: không vượt thẩm quyền người uỷ quyền, không uỷ quyền bắc cầu.
- Phần dành cho NCC: container và tên miền riêng, whitelist IP là lớp bổ sung; đường dẫn dùng một lần cho NCC không có IP tĩnh.
- Tờ trình nhiều đơn vị ngân sách: nhánh xác nhận song song của từng đơn vị quản lý, trước FAD tiền kiểm.
- Kiểm soát ngân sách theo chi phí phân bổ theo tháng; hợp đồng nhiều năm giữ chỗ theo kỳ từng năm, năm sau chưa có ngân sách thì cảnh báo.
- Lịch sử Data new nhập dạng chỉ đọc; tên người duyệt trong lịch sử giữ dạng văn bản.
- Cấu hình hệ thống (SMTP, tích hợp, tỷ giá) trên giao diện, bí mật được mã hoá.
- Thủ tục khi chưa có ngân sách = đề nghị bổ sung/điều chuyển ngân sách, duyệt theo nhóm "Ngoài ngân sách" (chờ xác nhận, 12.4).
- Cổng chi tiền một điểm, đổi PAS ↔ Bank Gateway bằng cấu hình; lệnh chi khoá sau duyệt.
- Tìm kiếm toàn văn dùng PostgreSQL, không thêm hệ thống tìm kiếm riêng; OCR chọn Tesseract hoặc PaddleOCR sau khi thử trên chứng từ mẫu.
- Mã tờ trình dạng `TT-2026-00001`.

## 14. Phần để người lập trình quyết định
Chi tiết mô hình dữ liệu, tên bảng, bố cục màn hình, thư viện phụ trợ (không thêm hạ tầng mới, phải qua quét bảo mật).
