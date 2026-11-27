"""Sinh dữ liệu mẫu GIẢ vào thư mục sample-data/.

    python scripts/make_sample_data.py --out sample-data/

Tạo `Budget Control - DEMO.xlsx` (5 sheet đúng tiêu đề file thật) và `hris_fake.json`.
Mọi tên, mã, số liệu đều là giả; kết quả xác định nhờ random.seed(42).
"""

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

UNIT = "DEMO"
WORKBOOK_NAME = "Budget Control - DEMO.xlsx"
HRIS_NAME = "hris_fake.json"

L8_HEADERS = ["No", "L8_Code", "L8_name", "Capex/Opex", "Main_items", "Main_2025", "Main_2026", "Main_2027"]
L10_HEADERS = ["Project_Code", "Project Name", "Work streams", "Begin_Year", "Dept", "Status"]
EXPENSE_HEADERS = [
    "L8_Code (AOP)", "L8_Code", "L8_name", "Date", "Original", "Adjust", "L10_Code", "Location", "Note",
]
CAPEX_HEADERS = [
    "L8_Code (AOP)", "L8_Code", "L8_name", "Date", "Group", "Original", "Adjust", "L10_Code", "Location", "Note",
]

M1 = "01. Chi phí thuê và vận hành"
M2 = "02. Chi phí hành chính"
M3 = "03. Chi phí dịch vụ"
M4 = "04. Đầu tư mua sắm trang thiết bị"

OPEX = [
    ("DM_1.1", "Thuê văn phòng (giả)", M1),
    ("DM_1.2", "Điện nước (giả)", M1),
    ("DM_2.1", "Văn phòng phẩm (giả)", M2),
    ("DM_2.2", "Công tác phí (giả)", M2),
    ("DM_3.1", "Dịch vụ thuê ngoài (giả)", M3),
]
CAPEX = [
    ("DM_9.1", "Mua sắm thiết bị (giả)", M4, "Capex"),
    ("DM_9.2", "Cải tạo văn phòng (giả)", M4, ""),  # để trống: Capex nhận biết nhờ sheet Budget_Capex
]
PROJECTS = [
    ("DEMO_P1", "Dự án số hoá hồ sơ (giả)", "Chuyển đổi số", 2026),
    ("DEMO_P2", "Dự án cải tạo tầng 3 (giả)", "Cơ sở vật chất", 2025),
]
LOCATIONS = ["HSC", "HNB"]
L9_HEADERS = ["Loại hình", "Mã số thuế", "Tên nhà cung cấp"]
# Nhà cung cấp GIẢ: tên bịa, mã số thuế đúng định dạng nhưng không thuộc doanh nghiệp thật.
VENDORS = [
    ["Tổ chức", "0100000011", "CÔNG TY TNHH MẪU MỘT (GIẢ)"],
    ["Tổ chức", "0100000028", "CÔNG TY CỔ PHẦN DỊCH VỤ THỬ NGHIỆM (GIẢ)"],
    ["Tổ chức", "0100000035-001", "CHI NHÁNH HÀ NỘI - CÔNG TY VÍ DỤ (GIẢ)"],
    ["Tổ chức", "0300000042", "CÔNG TY TNHH THƯƠNG MẠI DEMO (GIẢ)"],
    ["Tổ chức", "0300000059-006", "CHI NHÁNH TP.HCM - CÔNG TY GIẢ LẬP (GIẢ)"],
    ["Tổ chức", "0300000066", "CÔNG TY TNHH VĂN PHÒNG PHẨM MẪU (GIẢ)"],
    ["Tổ chức", "0400000073", "CÔNG TY CỔ PHẦN THIẾT BỊ KIỂM THỬ (GIẢ)"],
    ["Tổ chức", "0400000080", "CÔNG TY TNHH VẬN TẢI VÍ DỤ (GIẢ)"],
    ["Cá nhân", "001000000019", "NGUYỄN VĂN MẪU (GIẢ)"],
    ["Cá nhân", "079000000026", "TRẦN THỊ THỬ (GIẢ)"],
]


def write_workbook(path, l8_rows, l10_rows, expense_rows, capex_rows, vendor_rows=None) -> None:
    """Ghi workbook 4 sheet (+ L9_Code nếu có vendor_rows) với tiêu đề đúng file thật. Mỗi hàng là list giá trị theo thứ tự cột."""
    wb = Workbook()
    wb.properties.created = wb.properties.modified = datetime(2026, 1, 1)
    wb.properties.creator = "make_sample_data"
    ws = wb.active
    ws.title = "L8_Code"
    for title, headers, rows in [
        ("L8_Code", L8_HEADERS, l8_rows),
        ("L10_Code", L10_HEADERS, l10_rows),
        ("Budget_Expense", EXPENSE_HEADERS, expense_rows),
        ("Budget_Capex", CAPEX_HEADERS, capex_rows),
        *([("L9_Code", L9_HEADERS, vendor_rows)] if vendor_rows is not None else []),
    ]:
        sheet = ws if title == "L8_Code" else wb.create_sheet(title)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    wb.save(path)


def demo_rows():
    rng = random.Random(42)

    l8 = []
    for i, (code, name, main) in enumerate(OPEX, 1):
        l8.append([i, code, name, None, main, main, main, main])
    for j, (code, name, main, kind) in enumerate(CAPEX, len(OPEX) + 1):
        l8.append([j, code, name, kind or None, main, main, main, None])

    l10 = [
        [code, name, ws, begin, "6. DEMO", "Active"] for code, name, ws, begin in PROJECTS
    ]

    expense = []
    for code, name, _ in OPEX:
        for loc in LOCATIONS:
            yearly = rng.choice([60, 75, 120, 240]) * 1_000_000
            for month in range(1, 13):
                adjust = None
                if month in (6, 9) and rng.random() < 0.4:
                    adjust = rng.choice([-5, -2, 3, 10]) * 1_000_000
                project = "DEMO_P1" if code == "DM_3.1" and loc == "HSC" else None
                expense.append([
                    None, code, name, datetime(2026, month, 1), yearly * (1 / 12), adjust,
                    project, loc, "Dữ liệu giả" if month == 1 else None,
                ])
    for code, name, _ in OPEX[:2]:  # vài dòng năm 2025 để thử bỏ qua
        expense.append([None, code, name, datetime(2025, 12, 1), 5_000_000, None, None, "HSC", "Năm cũ"])
    expense.append([None, "DM_2.1", "Văn phòng phẩm (giả)", datetime(2025, 11, 1), 1_000_000, 0, None, "HNB", "Năm cũ"])

    capex = []
    for code, name, _, _ in CAPEX:
        total = rng.choice([360, 600]) * 1_000_000
        for month in range(1, 13):
            capex.append([
                None, code, name, datetime(2026, month, 1), "Nhóm A" if code == "DM_9.1" else "Nhóm B",
                total / 12, None, "DEMO_P1" if code == "DM_9.2" else None, "HSC", None,
            ])
    capex.append([None, "DM_9.1", "Mua sắm thiết bị (giả)", datetime(2025, 12, 1), "Nhóm A", 2_000_000, None, None, "HSC", "Năm cũ"])
    return l8, l10, expense, capex


def _emp(code, username, name, org, title, roles):
    return {
        "employee_code": code, "username": username, "email": f"{username}@example.com",
        "full_name": name, "org_unit_code": org, "title": title, "entra_oid": None, "active": True,
        # `roles`: gợi ý phân quyền cho kịch bản demo; sync_hris bỏ qua khoá này.
        "roles": [{"role": r, "org_unit_code": ou} for r, ou in roles],
    }


def hris_data() -> dict:
    org_units = [
        {"code": "KHOI-DEMO", "name": "Khối Demo", "kind": "KHOI", "parent_code": None},
        {"code": "DEMO-A", "name": "Phòng Demo A", "kind": "PHONG", "parent_code": "KHOI-DEMO"},
        {"code": "DEMO-B", "name": "Phòng Demo B", "kind": "PHONG", "parent_code": "KHOI-DEMO"},
        {"code": "ITD-DEMO", "name": "Phòng CNTT Demo", "kind": "PHONG", "parent_code": "KHOI-DEMO"},
        {"code": "ADM-DEMO", "name": "Phòng Hành chính Demo", "kind": "PHONG", "parent_code": "KHOI-DEMO"},
        {"code": "FAD-DEMO", "name": "Phòng Tài chính Kế toán Demo", "kind": "PHONG", "parent_code": "KHOI-DEMO"},
    ]
    employees = [
        _emp("D001", "nv.mau1", "Nguyễn Văn Mẫu", "DEMO-A", "Chuyên viên", [("REQUESTER", "DEMO-A")]),
        _emp("D002", "tp.mau1", "Trần Thị Thử", "DEMO-A", "Trưởng phòng", [("DEPT_HEAD", "DEMO-A")]),
        _emp("D003", "pho.mau1", "Lê Văn Phó Giả", "DEMO-A", "Phó phòng", [("REQUESTER", "DEMO-A")]),
        _emp("D004", "nv.mau2", "Phạm Thị Ví Dụ", "DEMO-B", "Chuyên viên", [("REQUESTER", "DEMO-B")]),
        _emp("D005", "tp.mau2", "Hoàng Văn Kiểm Thử", "DEMO-B", "Trưởng phòng", [("DEPT_HEAD", "DEMO-B")]),
        _emp("D006", "gddh.mau", "Vũ Thị Điều Hành Giả", "KHOI-DEMO", "Giám đốc điều hành", [("GDDH", "KHOI-DEMO")]),
        _emp("D007", "gdnv.mau", "Đặng Văn Nghiệp Vụ Giả", "KHOI-DEMO", "Giám đốc nghiệp vụ", [("GDNV", "KHOI-DEMO")]),
        _emp("D008", "bo.itd", "Bùi Thị Chủ Quản CNTT", "ITD-DEMO", "Trưởng phòng", [("BUDGET_OWNER", "ITD-DEMO"), ("DEPT_HEAD", "ITD-DEMO")]),
        _emp("D009", "bo.adm", "Ngô Văn Chủ Quản HC", "ADM-DEMO", "Trưởng phòng", [("BUDGET_OWNER", "ADM-DEMO"), ("DEPT_HEAD", "ADM-DEMO")]),
        _emp("D010", "fad.tienkiem", "Đỗ Thị Tiền Kiểm", "FAD-DEMO", "Chuyên viên", [("FAD_PRECHECK", "FAD-DEMO")]),
        _emp("D011", "fad.ngansach", "Dương Văn Ngân Sách", "FAD-DEMO", "Chuyên viên", [("FAD_BUDGET_ADMIN", "FAD-DEMO")]),
        _emp("D012", "thuky.bms", "Lý Thị Thư Ký BMS", "FAD-DEMO", "Thư ký BMS", [("BMS_SECRETARY", None)]),
        _emp("D013", "ceo.mau", "Mai Văn Tổng Giả", "KHOI-DEMO", "Tổng giám đốc", [("CEO", None)]),
        _emp("D014", "nv.itd", "Cao Thị Công Nghệ Giả", "ITD-DEMO", "Chuyên viên", [("REQUESTER", "ITD-DEMO")]),
    ]
    return {"org_units": org_units, "employees": employees}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Sinh dữ liệu mẫu giả")
    parser.add_argument("--out", required=True, help="Thư mục đầu ra, ví dụ sample-data/")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_workbook(out / WORKBOOK_NAME, *demo_rows(), VENDORS)
    (out / HRIS_NAME).write_text(
        json.dumps(hris_data(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Đã tạo {out / WORKBOOK_NAME} và {out / HRIS_NAME}")


if __name__ == "__main__":
    main()
