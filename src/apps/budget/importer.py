"""Nhập file Budget Control (Excel) cho một đơn vị ngân sách và một năm.

Quy trình: đọc và kiểm tra TOÀN BỘ file trước (báo cáo làm sạch); chỉ khi không còn lỗi và không
phải `dry_run` mới ghi dữ liệu, trong một transaction. Audit `budget.imported` được gọi cuối cùng
(audit giữ khoá toàn cục). Sheet L9_Code (NCC), nếu có, được kiểm tra chung báo cáo và ghi cùng transaction.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from openpyxl import load_workbook

from apps.accounts.models import OrgUnit
from apps.audit import service as audit
from apps.core.imports import (
    ImportIssue,
    ImportReport,
)
from apps.core.money import round_vnd
from apps.vendors import importer as vendor_importer

from . import ledger
from .models import (
    ADJUST,
    ORIGINAL,
    BudgetEntry,
    BudgetLine,
    BudgetUnit,
    CostCode,
    CostCodeMainItem,
    Location,
    MainItem,
    Project,
)

SHEET_L8, SHEET_L10, SHEET_EXPENSE, SHEET_CAPEX = "L8_Code", "L10_Code", "Budget_Expense", "Budget_Capex"
LOCATIONS = {"HSC": "TP.HCM (HO)", "HNB": "Hà Nội"}
_MAIN_RE = re.compile(r"^\s*(\d+)\s*\.\s*(.+?)\s*$")


@dataclass
class _L8:
    code: str
    name: str
    is_capex: bool
    main: tuple[str, str] | None


@dataclass
class _Entry:
    row_ref: str
    l8: str
    l10: str
    location: str
    period: date
    kind: str
    amount: Decimal
    note: str


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _read_sheet(wb, name, required, report):
    """Trả về [(số dòng, {tiêu đề: giá trị})]; thiếu sheet/cột thì ghi issue và trả None."""
    if name not in wb.sheetnames:
        report.issues.append(ImportIssue(name, 0, "", f"Thiếu sheet {name}"))
        return None
    rows = wb[name].iter_rows(values_only=True)
    header = next(rows, None) or ()
    headers = [_text(h) for h in header]
    missing = [c for c in required if c not in headers]
    for c in missing:
        report.issues.append(ImportIssue(name, 1, c, f"Thiếu cột {c}"))
    if missing:
        return None
    out = []
    for n, values in enumerate(rows, start=2):
        if all(v is None or _text(v) == "" for v in values):
            continue
        out.append((n, dict(zip(headers, values))))
    return out


def _parse_main(text, sheet, row, column, report):
    text = _text(text)
    if not text:
        return None
    m = _MAIN_RE.match(text)
    if not m:
        report.issues.append(
            ImportIssue(sheet, row, column, f"Main item '{text}' không đúng dạng '01. Tên nhóm'")
        )
        return None
    return m.group(1), m.group(2)


def _read_l8(wb, year, report):
    rows = _read_sheet(wb, SHEET_L8, ["L8_Code", "L8_name"], report)
    codes: dict[str, _L8] = {}
    if rows is None:
        return codes
    for n, r in rows:
        code = _text(r.get("L8_Code"))
        if not code:
            report.issues.append(ImportIssue(SHEET_L8, n, "L8_Code", "Mã L8 trống"))
            continue
        if code in codes:
            report.issues.append(ImportIssue(SHEET_L8, n, "L8_Code", f"Mã L8 '{code}' bị trùng trong sheet"))
            continue
        column = f"Main_{year}"
        main_text = r.get(column)
        if _text(main_text) == "":
            column, main_text = "Main_items", r.get("Main_items")
        codes[code] = _L8(
            code=code,
            name=_text(r.get("L8_name")) or code,
            is_capex=_text(r.get("Capex/Opex")).lower() == "capex",
            main=_parse_main(main_text, SHEET_L8, n, column, report),
        )
    return codes


def _read_l10(wb, year, report):
    rows = _read_sheet(wb, SHEET_L10, ["Project_Code", "Project Name"], report)
    projects: dict[str, dict] = {}
    for n, r in rows or []:
        code = _text(r.get("Project_Code"))
        if not code:
            report.issues.append(ImportIssue(SHEET_L10, n, "Project_Code", "Mã dự án trống"))
            continue
        if code in projects:
            report.issues.append(ImportIssue(SHEET_L10, n, "Project_Code", f"Mã dự án '{code}' bị trùng"))
            continue
        begin = r.get("Begin_Year")
        if _text(begin) == "":
            begin = year
        else:
            try:
                begin = int(Decimal(str(begin).strip()))
            except (InvalidOperation, ValueError):
                report.issues.append(
                    ImportIssue(SHEET_L10, n, "Begin_Year", f"Năm bắt đầu '{begin}' không hợp lệ")
                )
                begin = year
        projects[code] = {
            "name": _text(r.get("Project Name")) or code,
            "workstream": _text(r.get("Work streams")),
            "begin_year": begin,
        }
    return projects


def _parse_amount(v):
    """Chuyển ô tiền thành Decimal VND; None/trống = 0; không phải số thì trả None."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return Decimal(0)
    if isinstance(v, (bool, datetime, date)):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    return round_vnd(d) if d.is_finite() else None


def _read_budget_rows(wb, sheet, l8, l10, year, unit_code, report, entries, capex_codes):
    required = ["L8_Code", "Date", "Original", "Adjust", "L10_Code", "Location", "Note"]
    if sheet == SHEET_CAPEX:
        required.append("Group")
    rows = _read_sheet(wb, sheet, required, report)
    for n, r in rows or []:
        parsed = {c: _parse_amount(r.get(c)) for c in ("Original", "Adjust")}
        if all(v == 0 for v in parsed.values()):
            continue  # dòng trống số tiền (kể cả dòng gần như trống): bỏ qua im lặng
        d = r.get("Date")
        if _text(d) == "":
            report.issues.append(ImportIssue(sheet, n, "Date", "Ngày trống"))
            d = None
        elif isinstance(d, datetime):
            d = d.date()
        elif not isinstance(d, date):
            report.issues.append(ImportIssue(sheet, n, "Date", f"Ngày '{d}' không phải kiểu ngày của Excel"))
            d = None
        if d is not None and d.year != year:
            report.skipped_other_year += 1
            continue

        ok = d is not None
        code = _text(r.get("L8_Code"))
        if not code:
            report.issues.append(ImportIssue(sheet, n, "L8_Code", "Mã L8 trống"))
            ok = False
        elif code not in l8:
            report.issues.append(ImportIssue(sheet, n, "L8_Code", f"Mã L8 '{code}' không có trong sheet L8_Code"))
            ok = False
        elif sheet == SHEET_CAPEX:
            capex_codes.add(code)

        l10_code = _text(r.get("L10_Code")) or f"BAU_{unit_code}"
        if l10_code != f"BAU_{unit_code}" and l10_code not in l10:
            report.issues.append(
                ImportIssue(sheet, n, "L10_Code", f"Mã dự án '{l10_code}' không có trong sheet L10_Code")
            )
            ok = False

        loc = _text(r.get("Location"))
        if loc not in LOCATIONS:
            report.issues.append(
                ImportIssue(sheet, n, "Location", f"Địa điểm '{loc}' không hợp lệ (chỉ HSC hoặc HNB)")
            )
            ok = False

        for column, amt in parsed.items():
            if amt is None:
                report.issues.append(
                    ImportIssue(sheet, n, column, f"Giá trị '{r.get(column)}' không phải số")
                )
                ok = False
        if not ok:
            continue
        ref = f"{sheet}!R{n}"
        note = _text(r.get("Note"))
        period = date(d.year, d.month, 1)  # ngày bất kỳ trong tháng -> ngày đầu tháng
        orig, adj = parsed["Original"], parsed["Adjust"]
        if orig > 0:
            entries.append(_Entry(ref, code, l10_code, loc, period, ORIGINAL, orig,
                                  f"{ref} — {note}" if note else ref))
        elif orig < 0:  # FAD bù trừ: Original âm ghi như điều chỉnh
            entries.append(_Entry(ref, code, l10_code, loc, period, ADJUST, orig,
                                  f"{ref} (Original âm)" + (f" — {note}" if note else "")))
        if adj:
            entries.append(_Entry(ref, code, l10_code, loc, period, ADJUST, adj,
                                  f"{ref} — {note}" if note else ref))


def _resolve_unit(code, org_unit_code, year, report):
    unit = BudgetUnit.objects.filter(code=code).first()
    if unit is not None:
        if BudgetEntry.objects.filter(
            line__budget_unit=unit, line__year=year, kind=ORIGINAL
        ).exists():
            report.issues.append(ImportIssue(
                "", 0, "", f"Ngân sách năm {year} của đơn vị {code} đã được nhập"
            ))
        return unit, None
    org = OrgUnit.objects.filter(code=org_unit_code).first() if org_unit_code else None
    if org is None:
        report.issues.append(ImportIssue(
            "", 0, "",
            f"Đơn vị ngân sách {code} chưa tồn tại; cần chỉ định đơn vị quản lý (mã đơn vị tổ chức) có sẵn để tạo",
        ))
    return None, org


def import_budget_workbook(
    path, *, budget_unit_code: str, year: int, user, dry_run: bool = True,
    managing_org_unit_code: str | None = None,
) -> ImportReport:
    """Nhập ngân sách năm `year` cho đơn vị `budget_unit_code`. Có issue hoặc dry_run: không ghi gì."""
    report = ImportReport()
    unit_code = budget_unit_code.strip()
    unit, org = _resolve_unit(unit_code, managing_org_unit_code, year, report)

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        l8 = _read_l8(wb, year, report)
        l10 = _read_l10(wb, year, report)
        entries: list[_Entry] = []
        capex_codes: set[str] = set()
        for sheet in (SHEET_EXPENSE, SHEET_CAPEX):
            _read_budget_rows(wb, sheet, l8, l10, year, unit_code, report, entries, capex_codes)
        vendor_rows = vendor_importer.read_vendor_sheet(wb, report)
        planned_vendors = (
            vendor_importer.validate_vendor_rows(vendor_rows, report) if vendor_rows is not None else None
        )
    finally:
        wb.close()

    for kind in (ORIGINAL, ADJUST):
        report.totals[kind] = sum((e.amount for e in entries if e.kind == kind), Decimal(0))
    if report.issues:
        return report

    # CostCode/Project là duy nhất toàn hệ thống: không dùng lại dòng của đơn vị khác.
    for cc in CostCode.objects.filter(code__in={e.l8 for e in entries}).select_related("budget_unit"):
        if cc.budget_unit.code != unit_code:
            report.issues.append(ImportIssue(
                SHEET_L8, 0, "L8_Code", f"Mã L8 '{cc.code}' đã thuộc đơn vị ngân sách {cc.budget_unit.code}"
            ))
    for pj in Project.objects.filter(code__in={e.l10 for e in entries}).select_related("budget_unit"):
        if pj.budget_unit.code != unit_code:
            report.issues.append(ImportIssue(
                SHEET_L10, 0, "L10_Code", f"Mã dự án '{pj.code}' đã thuộc đơn vị ngân sách {pj.budget_unit.code}"
            ))
    # Ngân sách ròng (gốc + điều chỉnh) của từng dòng trong năm không được âm.
    net: dict[tuple, Decimal] = {}
    first_ref: dict[tuple, str] = {}
    for e in entries:
        key = (e.l8, e.l10, e.location)
        net[key] = net.get(key, Decimal(0)) + e.amount
        first_ref.setdefault(key, e.row_ref)
    for key, total in net.items():
        if total < 0:
            sheet, row = first_ref[key].split("!R")
            report.issues.append(ImportIssue(
                sheet, int(row), "Original",
                f"Ngân sách ròng năm {year} của {key[0]}/{key[1]}/{key[2]} bị âm ({total})",
            ))
    if report.issues:
        return report

    used_l8 = sorted({e.l8 for e in entries})
    used_l10 = sorted({e.l10 for e in entries})
    lines = {(e.l8, e.l10, e.location) for e in entries}
    report.created = {
        "cost_codes": len(used_l8) - CostCode.objects.filter(code__in=used_l8).count(),
        "projects": len([p for p in used_l10 if not Project.objects.filter(code=p).exists()]),
        "lines": len(lines),
        "entries": len(entries),
    }
    if planned_vendors is not None:
        vendor_importer.summarize_vendors(planned_vendors, report)
    if dry_run:
        return report

    with transaction.atomic():
        if unit is not None:
            # Khoá đơn vị rồi kiểm tra lại: chặn hai lần nhập đồng thời.
            BudgetUnit.objects.select_for_update().get(pk=unit.pk)
            if BudgetEntry.objects.filter(
                line__budget_unit=unit, line__year=year, kind=ORIGINAL
            ).exists():
                report.issues.append(ImportIssue(
                    "", 0, "", f"Ngân sách năm {year} của đơn vị {unit_code} đã được nhập"
                ))
                return report
        if unit is None:
            unit = BudgetUnit.objects.create(code=unit_code, name=unit_code, managing_org_unit=org)
        locations = {
            c: Location.objects.get_or_create(code=c, defaults={"name": LOCATIONS[c]})[0]
            for c in sorted({e.location for e in entries})
        }
        cost_codes = {}
        for code in used_l8:
            src = l8[code]
            cc, _ = CostCode.objects.get_or_create(
                code=code, defaults={"name": src.name, "budget_unit": unit, "is_capex": False}
            )
            if (src.is_capex or code in capex_codes) and not cc.is_capex:
                cc.is_capex = True
                cc.save(update_fields=["is_capex"])
            if src.main is not None:
                mi, _ = MainItem.objects.get_or_create(code=src.main[0], defaults={"name": src.main[1]})
                CostCodeMainItem.objects.get_or_create(
                    cost_code=cc, year=year, defaults={"main_item": mi}
                )
            cost_codes[code] = cc
        projects = {}
        for code in used_l10:
            info = l10.get(code) or {
                "name": f"BAU {unit_code}", "workstream": "BAU", "begin_year": year,
            }
            projects[code] = Project.objects.get_or_create(
                code=code, defaults={**info, "budget_unit": unit}
            )[0]
        line_objs = {
            key: BudgetLine.objects.get_or_create(
                year=year, budget_unit=unit, cost_code=cost_codes[key[0]],
                project=projects[key[1]], location=locations[key[2]],
            )[0]
            for key in sorted(lines)
        }
        built = []
        for e in entries:
            entry = ledger._build(
                line_objs[(e.l8, e.l10, e.location)], e.period, e.kind, e.amount,
                source=None, user=user, note=e.note,
            )
            entry.source_type, entry.source_id = "budget.import", f"{unit_code}:{year}"
            built.append(entry)
        BudgetEntry.objects.bulk_create(built)
        if planned_vendors:
            vendor_importer.apply_vendors(planned_vendors, user, report)
        audit.record(
            "budget.imported", unit, actor=user,
            changes={
                "year": year, "created": report.created,
                "skipped_other_year": report.skipped_other_year,
                "totals": {k: str(v) for k, v in report.totals.items()},
            },
        )
    return report
