# Dữ liệu mẫu (GIẢ)

Toàn bộ dữ liệu trong thư mục này là **giả**: mã, tên người, email (`@example.com`) và số tiền do
script sinh ra, không liên quan đến người hay số liệu thật. File Budget Control thật không bao giờ
được đưa vào repo.

| File | Nội dung |
|---|---|
| `Budget Control - DEMO.xlsx` | 5 sheet `L8_Code`, `L10_Code`, `Budget_Expense`, `Budget_Capex`, `L9_Code` (10 nhà cung cấp giả) đúng tiêu đề file thật; 12 tháng năm 2026, 2 địa điểm (HSC, HNB), vài dòng năm 2025 để thử việc bỏ qua |
| `hris_fake.json` | Đơn vị (DEMO-A, DEMO-B, ITD-DEMO, ADM-DEMO, FAD-DEMO) và nhân viên giả đủ các vai trò của kịch bản demo; khoá `roles` là gợi ý phân quyền, `sync_hris` bỏ qua |

## Sinh lại

```
python scripts/make_sample_data.py --out sample-data/
```

Kết quả xác định (`random.seed(42)`); số liệu không đổi giữa các lần chạy.

## Dùng thử

```
python src/manage.py sync_hris --fake sample-data/hris_fake.json
python src/manage.py import_budget "sample-data/Budget Control - DEMO.xlsx" --unit DEMO --year 2026 --org-unit ADM-DEMO
python src/manage.py import_budget "sample-data/Budget Control - DEMO.xlsx" --unit DEMO --year 2026 --org-unit ADM-DEMO --commit
```

Lệnh đầu chỉ chạy thử và in báo cáo làm sạch; thêm `--commit` mới ghi dữ liệu.
