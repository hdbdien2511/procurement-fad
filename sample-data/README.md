# Dữ liệu mẫu (GIẢ)

Toàn bộ dữ liệu trong thư mục này là **giả**: mã, tên người, email (`@example.com`) và số tiền do
script sinh ra, không liên quan đến người hay số liệu thật. File Budget Control thật không bao giờ
được đưa vào repo.

| File | Nội dung |
|---|---|
| `Budget Control - DEMO.xlsx` | 5 sheet `L8_Code`, `L10_Code`, `Budget_Expense`, `Budget_Capex`, `L9_Code` (10 nhà cung cấp giả) đúng tiêu đề file thật; 12 tháng năm 2026, 2 địa điểm (HSC, HNB), vài dòng năm 2025 để thử việc bỏ qua |
| `hris_fake.json` | Đơn vị (DEMO-A, DEMO-B, ITD-DEMO, ADM-DEMO, FAD-DEMO, DTI-DEMO) và nhân viên giả đủ các vai trò của kịch bản demo; khoá `roles` là gợi ý phân quyền (lệnh `seed_demo` đọc, `sync_hris` bỏ qua). Vai trò phạm vi toàn công ty (GĐĐH, TGĐ, thư ký BMS/HĐQT, FAD) có `org_unit_code = null` vì bước duyệt phạm vi COMPANY chỉ nhận phân công toàn công ty |

## Sinh lại

```
python scripts/make_sample_data.py --out sample-data/
```

Kết quả xác định (`random.seed(42)`); số liệu không đổi giữa các lần chạy.

## Dựng toàn bộ dữ liệu demo (khuyến nghị)

```
python src/manage.py seed_demo
```

Một lệnh làm hết: đồng bộ HRIS giả, nhập ngân sách 2026 + nhà cung cấp từ workbook, phân quyền theo
`roles`, 2 chính sách duyệt mẫu, tỷ giá USD và tham số hệ thống. Chạy lại được nhiều lần. Kịch bản
nghiệm thu dùng dữ liệu này: `docs/04-kiem-thu/kich-ban-dot-1.md`.

## Dùng từng lệnh một

```
python src/manage.py sync_hris --fake sample-data/hris_fake.json
python src/manage.py import_budget "sample-data/Budget Control - DEMO.xlsx" --unit DEMO --year 2026 --org-unit ADM-DEMO
python src/manage.py import_budget "sample-data/Budget Control - DEMO.xlsx" --unit DEMO --year 2026 --org-unit ADM-DEMO --commit
```

Lệnh đầu chỉ chạy thử và in báo cáo làm sạch; thêm `--commit` mới ghi dữ liệu.
