# Thiết kế: Nền tảng Procurement HSC (Đợt 1)

- Ngày: 2026-11-27 (cập nhật lần 3: chọn phương án thanh toán "xuyên suốt, chuyển dần"; chốt quy tắc ngân sách và NCC ngoài danh sách)
- Trạng thái: BẢN NHÁP, chờ người dùng duyệt
- Người sở hữu nghiệp vụ: Kế toán / FAD (người dùng)
- Ký hiệu: **[Đã chốt]** = người dùng quyết định; **[RFP]** = lấy từ tài liệu RFP; **[Đề xuất]** = Claude đề xuất, người dùng có thể sửa; **[Mở]** = chưa có câu trả lời.
- Tài liệu nguồn: `RFP_eProcurement_v0.2.docx`, `RFP_eProcurement_As_is__To_be.xlsx` (không lưu vào repo, xem 8.6). Mã `R1`…`R89` trong tài liệu này là số thứ tự tiêu chí ở sheet "5. Thang điểm".

---

## 0. Quan hệ với RFP (CẦN LÀM RÕ TRƯỚC KHI DUYỆT)

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
| Máy chủ nội bộ HSC, truy cập qua mạng nội bộ/VPN | [Đã chốt] |
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
- Docker Compose (app, db, nginx, worker), để IT cài một lệnh.
- Việc nền: bảng outbox trong PostgreSQL + worker; không Redis/Celery ở đợt 1.
- API nội bộ: REST, xác thực bằng token cấp cho từng hệ thống, chỉ mở trong mạng nội bộ. Đáp ứng R13, R24, R48.
- **Cổng NCC tách riêng:** NCC truy cập từ Internet, nên cổng này **không được** là cùng một ứng dụng với hệ thống nội bộ. Đặt ở DMZ, chỉ gọi vào hệ thống nội bộ qua API giới hạn. Đợt 2 làm trước phần nội bộ (người mua hàng nhập báo giá NCC gửi qua email); cổng NCC là quyết định riêng cùng IT. **[Đề xuất]**
- **Tiền tệ:** số tiền lưu dạng Decimal kèm loại tiền (VND, USD, HKD…) và tỷ giá tại ngày lập; quy đổi VND để so ngưỡng duyệt và trừ ngân sách. **[RFP; thay quyết định "chỉ VND" ở bản trước]**
- Năm tài chính = năm dương lịch. **[Đề xuất]**
- Giao diện tiếng Việt.

## 7. Các thành phần của đợt 1 (nền tảng)

| Thành phần | Nội dung | Tiêu chí RFP |
|---|---|---|
| `accounts` | Người dùng, Khối/Phòng ban, chức danh, vai trò. Bản mẫu: tài khoản nội bộ + MFA; chỗ nối SSO và đồng bộ HRIS cho IT bật sau | R59 |
| `audit` | Nhật ký chỉ-ghi-thêm (8.3); tra cứu; xuất cho kiểm toán | R59, R86 |
| `documents` | Đính kèm nhiều file/hồ sơ, xem trước không cần tải, checklist loại chứng từ theo loại hồ sơ, mã băm SHA-256 | R87 |
| `workflow` | Bộ máy luồng duyệt cấu hình được (7.1), uỷ quyền (7.2), nhắc việc và chuyển cấp khi quá hạn | R20–R23, R63 |
| `budget` | Sổ ngân sách (7.3): lập, duyệt, điều chỉnh/điều chuyển có duyệt, giữ chỗ, giải phóng, hoàn trả; số dư thời gian thực; nhập Excel | R1, R18, R19 |
| `vendors` | Danh mục NCC cơ bản: thông tin, mã số thuế, tài khoản ngân hàng, nhóm hàng hoá/dịch vụ, trạng thái (hiệu lực/chờ duyệt/tạm ngưng/danh sách đen); nhập Excel. Quy trình đánh giá, duyệt NCC để đợt 2 | (nền cho R2–R13) |
| `requisitions` | Tờ trình: theo mẫu, dòng hàng, đa tiền tệ, **nhiều nguồn ngân sách**, 03 báo giá đính kèm (hoặc lý do ngoại lệ), tham vấn, FAD tiền kiểm (màn hình riêng), duyệt end-to-end; lưu nháp, sao chép | R14–R17, R78 |
| `notifications` | Email 2 mẫu (chính thức, xin ý kiến), mẫu mail chỉnh được không cần sửa code; thông báo trong hệ thống; "Việc chờ tôi" | R62, R83 |
| `integrations` | Bộ chuyển đổi SSO, SUN, PAS, IMS, HRIS, email. Đợt 1 dùng **bản giả lập** | (nền cho R60) |
| `ui` (dùng chung) | Bảng dữ liệu chuẩn: lọc (lưu bộ lọc), sắp xếp nhiều cột, tìm nhanh, cố định tiêu đề, phân trang, tổng phụ, định dạng tiền + số tiền bằng chữ, gợi ý chọn, tự điền, kiểm tra khi nhập (MST, số tài khoản, trùng), chọn nhiều + duyệt hàng loạt, xuất Excel/PDF theo bộ lọc, liên kết chứng từ | R65–R81, R88 |

### 7.1 Bộ máy luồng duyệt
- **Chính sách duyệt** có phiên bản, hiệu lực từ ngày. Gồm các **quy tắc**: điều kiện (trong/ngoài ngân sách, khoảng tiền quy đổi VND, luỹ kế năm, loại chi phí, phương án mua sắm (dự án/BAU/công tác…), phòng ban, mua ngoại lệ) → chuỗi **bước** (đề nghị, owner budget, tham vấn, FAD tiền kiểm, lớp 1/2/3, HĐQT).
- Bước gắn **vai trò + phạm vi** (ví dụ "Trưởng phòng của phòng lập", "Owner của nguồn ngân sách", "đơn vị tham vấn theo nội dung"). Hồ sơ nhiều nguồn ngân sách có thể sinh **nhánh duyệt song song** cho từng owner.
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

### 7.3 Sổ ngân sách **[RFP + Đề xuất cách làm]**
- **Chiều ngân sách:** Năm × Khối × Phòng ban × Main Item × Loại chi phí × Mã chi phí × Mã project; mỗi dòng có **Owner budget**; **nguồn ngân sách** (Công ty, Công đoàn…). **[RFP]** Ngân sách có thể theo hạn mức năm hoặc phân bổ theo timeline (tháng/quý). **[RFP]**
- **Cách ghi nhận:** giống sổ kế toán. Mọi biến động ngân sách là một **bút toán ngân sách** chỉ-ghi-thêm: Kế hoạch được duyệt, Bổ sung, Điều chỉnh, Điều chuyển (hai bút toán đối ứng), Giữ chỗ (khi tờ trình được duyệt), Giải phóng (khi huỷ), Thực chi (khi PAS báo đã thanh toán), Hoàn trả (phần nghiệm thu thấp hơn giữ chỗ). Số dư = tổng các bút toán. Không sửa số trực tiếp; muốn sửa thì ghi bút toán điều chỉnh có duyệt. **[Đề xuất]**
- **Số dư khả dụng** = Ngân sách được duyệt − Giữ chỗ − Thực chi. Hiển thị ngay khi lập tờ trình. **Không đủ hoặc không có ngân sách thì chặn**, kèm lối tạo nhanh đề nghị bổ sung/điều chuyển ngân sách (4.1 câu 1).
- **Đề nghị bổ sung/điều chuyển ngân sách** là một loại hồ sơ chạy trên cùng bộ máy luồng duyệt (7.1), có chính sách duyệt riêng.
- **Lập ngân sách năm:** sao chép từ năm trước (giữ nguyên / chỉnh / thêm dự án), nhập Excel, trình duyệt. Dự báo theo thực chi: đợt 3.

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
- Cổng NCC (đợt 2+): ứng dụng tách riêng ở DMZ, tài khoản NCC chỉ thấy dữ liệu của chính NCC đó, chống dò mật khẩu, kiểm thử xâm nhập riêng trước khi mở ra Internet.

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
Repo đang ở **GitHub cá nhân** (`hdbdien2511/procurement-fad`). Đề xuất:
1. Giữ repo ở chế độ **Private**.
2. **Không** đưa vào repo: dữ liệu thật, file chính sách gốc, **file RFP gốc**, tên/email nhân viên thật, số liệu ngân sách thật. Bảng thẩm quyền ở mục 4 là bản trích để thiết kế; nếu chính sách nội bộ không cho phép, sẽ thay bằng số giả.
3. Khi IT tiếp nhận: chuyển repo về hệ thống quản lý mã nguồn của HSC.

Việc phát triển trên GitHub cá nhân và dùng công cụ AI với tài liệu nội bộ cần **người dùng xác nhận với IT/ATTT**.

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
| 2. NCC, tìm nguồn, hợp đồng | Đăng ký/đánh giá/duyệt NCC đầu năm, rủi ro, danh sách đen, xung đột lợi ích; yêu cầu báo giá, so sánh, đấu thầu, mua ngoại lệ; hợp đồng, review, phụ lục, nhắc gia hạn; API NCC cho PAS | R2–R13, R25–R28 | Từ nhu cầu → 03 báo giá → chọn NCC → hợp đồng đã duyệt |
| 3. Thực hiện, thanh toán, báo cáo | PO, nhận hàng/nghiệm thu từng phần, hoàn trả ngân sách; đánh giá sau mua; **ĐNTT theo yêu cầu mua sắm (1 lần/nhiều đợt) và không qua yêu cầu mua sắm** (tạm ứng, hoàn ứng, chi BAU); đối chiếu 3 chiều, IMS, chênh lệch hoá đơn; duyệt FAD Kiểm soát 1 → 2 → Phê duyệt; chuyển lệnh sang PAS + nhận trạng thái; dữ liệu cho SUN; báo cáo, dashboard, hậu kiểm; in mẫu | R24, R29–R37, R41–R42, R44–R53, R82, R84–R85, R89; một phần R38 | Hồ sơ đi hết vòng đời trên một hệ thống; PAS chỉ còn bước chi tiền; báo cáo Budget Control tái tạo được |
| 4. Bàn giao IT | SSO, kết nối thật SUN/PAS/IMS/HRIS, rà soát bảo mật, pentest, cài máy chủ HSC, UAT, đào tạo, go-live (PAS vẫn chi tiền) | R60, R61, R64 | IT ký nhận vận hành |
| 5. Thay PAS (IT chủ trì) | Nối thẳng Bank Gateway (ký lệnh, chứng thư số), kết quả chi thật từ ngân hàng, đối soát sao kê, chuyển hết loại hồ sơ PAS còn lại và dữ liệu cũ, nối IMS trực tiếp; chạy song song rồi tắt PAS | R38, R39, R40, R43 | Một kỳ chạy song song không chênh lệch; ngân hàng và ATTT nghiệm thu |
| Sau | Cổng NCC ra Internet; mở rộng Công tác | R54–R58 (+ phần portal của R2, R8) | Quyết định riêng |

R13 và R24 (API NCC, số dư ngân sách cho PAS) chỉ cần khi PAS còn lập hồ sơ riêng; với phương án đã chọn, vẫn làm ở mức tối thiểu cho giai đoạn chuyển tiếp.

## 11. Câu hỏi gửi IT (soạn sẵn)
1. Máy chủ nội bộ chạy Linux hay Windows? Có cài được Docker không?
2. CSDL chuẩn: PostgreSQL có được chấp nhận hay bắt buộc SQL Server?
3. Đăng nhập công ty: Microsoft Entra ID, ADFS hay Active Directory (LDAP)? HRIS có API lấy cơ cấu tổ chức, chức danh không?
4. Gửi email từ ứng dụng nội bộ qua máy chủ mail nào?
5. PAS: có API hoặc cách nào để tạo hồ sơ thanh toán và lấy trạng thái thanh toán (file, thư mục chung, đọc CSDL)? Ai là đầu mối phía vendor PAS?
6. SUN, IMS nhận/xuất dữ liệu theo cách nào? Đầu mối FPT cho IMS/HRIS?
7. Có chuẩn bảo mật/checklist nội bộ nào ứng dụng mới phải đạt (tiêu chí "ATTT cho công ty chứng khoán" trong RFP cụ thể là gì)? Có yêu cầu pentest trước go-live?
8. Có DMZ để đặt cổng NCC ra Internet không, hay cổng NCC phải do vendor/cloud đảm nhận?
9. Có được phát triển trên GitHub (repo private) và dùng công cụ AI hỗ trợ lập trình không? Khi bàn giao chuyển mã nguồn về đâu?
10. Chính sách lưu trữ chứng từ điện tử bao lâu? Sao lưu do ai phụ trách? Có hệ thống ký số đang dùng không?

## 12. Câu hỏi mở cho người dùng
1. **Quan hệ với RFP** [Mở]: bản tự xây là (a) bản mẫu để làm rõ yêu cầu và kiểm chứng RFP trước khi chọn vendor, (b) phương án thay thế việc mua vendor (tự xây thành hệ thống chính thức), hay (c) phần bổ trợ chạy song song với hệ thống vendor? IT đã biết về việc tự xây chưa?
2. **Quy định uỷ quyền của HSC** [Mở, không chặn đợt 1]: ai được uỷ quyền cho ai, có cần văn bản không, giới hạn thời gian/hạn mức? (Cơ chế chung ở 7.2, chờ quy định để cấu hình.)
3. **Điều kiện ngoại lệ NCC ngoài danh sách** [Mở, người dùng cung cấp sau; cần cho đợt 2].
4. **Xác nhận cách hiểu 4.1 câu 1**: thủ tục xin phê duyệt khi chưa có ngân sách = đề nghị bổ sung/điều chuyển ngân sách, duyệt theo nhóm "Ngoài ngân sách" của bảng thẩm quyền.

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
- Cổng NCC là ứng dụng tách riêng ở DMZ; đợt 2 làm phần nội bộ trước.
- Thủ tục khi chưa có ngân sách = đề nghị bổ sung/điều chuyển ngân sách, duyệt theo nhóm "Ngoài ngân sách" (chờ xác nhận, 12.4).
- Cổng chi tiền một điểm, đổi PAS ↔ Bank Gateway bằng cấu hình; lệnh chi khoá sau duyệt.
- Mã tờ trình dạng `TT-2026-00001`.

## 14. Phần để người lập trình quyết định
Chi tiết mô hình dữ liệu, tên bảng, bố cục màn hình, thư viện phụ trợ (không thêm hạ tầng mới, phải qua quét bảo mật).
