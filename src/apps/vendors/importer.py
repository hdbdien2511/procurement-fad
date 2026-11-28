"""Nhập danh mục nhà cung cấp từ sheet L9_Code (Loại hình | Mã số thuế | Tên nhà cung cấp).

Đọc và kiểm tra toàn bộ trước; có issue hoặc dry_run thì không ghi. Audit gọi cuối cùng trong transaction.
"""

import unicodedata
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit import service as audit
from apps.core.imports import ImportIssue, ImportReport

from .models import INDIVIDUAL, ORG, Vendor
from .validators import normalize_tax_code, validate_tax_code

SHEET_L9 = "L9_Code"
COL_KIND, COL_TAX, COL_NAME = "Loại hình", "Mã số thuế", "Tên nhà cung cấp"
REQUIRED = [COL_KIND, COL_TAX, COL_NAME]


@dataclass
class PlannedVendor:
    tax_code: str
    name: str
    kind: str


def read_vendor_sheet(wb, report):
    """Đọc sheet L9_Code thành list[dict] (kèm `_row`). Không có sheet: trả None, không ghi issue."""
    if SHEET_L9 not in wb.sheetnames:
        return None
    rows = wb[SHEET_L9].iter_rows(values_only=True)
    headers = [("" if h is None else str(h).strip()) for h in (next(rows, None) or ())]
    missing = [c for c in REQUIRED if c not in headers]
    for c in missing:
        report.issues.append(ImportIssue(SHEET_L9, 1, c, f"Thiếu cột {c}"))
    if missing:
        return []
    out = []
    for n, values in enumerate(rows, start=2):
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        out.append({"_row": n, **dict(zip(headers, values))})
    return out


def validate_vendor_rows(rows, report) -> list[PlannedVendor]:
    """Kiểm tra các dòng; ghi issue vào report; trả danh sách NCC hợp lệ (đã khử trùng)."""
    planned: dict[str, PlannedVendor] = {}
    first_row: dict[str, int] = {}
    for i, r in enumerate(rows):
        n = r.get("_row", i + 2)
        kind_text = unicodedata.normalize("NFC", str(r.get(COL_KIND) or "")).strip().casefold()
        kind = ORG if kind_text == "tổ chức" else INDIVIDUAL
        raw_tax = r.get(COL_TAX)
        name = str(r.get(COL_NAME) or "").strip()
        ok = True
        if isinstance(raw_tax, (int, float)) and not isinstance(raw_tax, bool):
            report.issues.append(ImportIssue(
                SHEET_L9, n, COL_TAX, "Mã số thuế phải nhập dạng văn bản (mất số 0 đầu)"
            ))
            ok, tax = False, ""
        else:
            tax = normalize_tax_code(raw_tax)
            try:
                validate_tax_code(tax, kind=kind)
            except ValidationError as e:
                report.issues.append(ImportIssue(SHEET_L9, n, COL_TAX, e.messages[0]))
                ok = False
        if not name:
            report.issues.append(ImportIssue(SHEET_L9, n, COL_NAME, "Tên nhà cung cấp trống"))
            ok = False
        if ok and tax in planned:
            report.issues.append(ImportIssue(
                SHEET_L9, n, COL_TAX, f"Mã số thuế '{tax}' bị trùng (dòng {first_row[tax]} và dòng {n})"
            ))
            ok = False
        if ok:
            planned[tax] = PlannedVendor(tax, name, kind)
            first_row[tax] = n
    return list(planned.values())


def summarize_vendors(planned, report) -> None:
    existing = set(
        Vendor.objects.filter(tax_code__in=[p.tax_code for p in planned]).values_list("tax_code", flat=True)
    )
    report.created["vendors"] = len([p for p in planned if p.tax_code not in existing])
    changed = 0
    for v in Vendor.objects.filter(tax_code__in=existing):
        p = next(x for x in planned if x.tax_code == v.tax_code)
        if (v.name, v.kind) != (p.name, p.kind):
            changed += 1
    report.created["vendors_updated"] = changed


def apply_vendors(planned, user, report) -> None:
    """Ghi NCC (gọi trong transaction của người gọi). Audit cuối."""
    existing = {v.tax_code: v for v in Vendor.objects.select_for_update().filter(
        tax_code__in=[p.tax_code for p in planned])}
    new = []
    updates = []
    for p in planned:
        v = existing.get(p.tax_code)
        if v is None:
            new.append(Vendor(code=p.tax_code, tax_code=p.tax_code, name=p.name, kind=p.kind, status="ACTIVE"))
            continue
        changes = audit.diff({"name": v.name, "kind": v.kind}, {"name": p.name, "kind": p.kind})
        if changes:
            v.name, v.kind = p.name, p.kind
            v.save(update_fields=["name", "kind"])
            updates.append((v, changes))
    Vendor.objects.bulk_create(new)
    for v, changes in updates:
        audit.record("vendor.updated", v, actor=user, changes=changes)
    audit.record(
        "vendors.imported", None, actor=user,
        changes={"created": len(new), "updated": len(updates)},
    )


def import_vendors_from_rows(rows: list[dict], user, dry_run: bool = True) -> ImportReport:
    report = ImportReport()
    planned = validate_vendor_rows(rows, report)
    if report.issues:
        return report
    summarize_vendors(planned, report)
    if dry_run:
        return report
    with transaction.atomic():
        apply_vendors(planned, user, report)
    return report
