"""Màn hình ngân sách: dòng ngân sách + số dư, sổ cái một dòng, nhập ngân sách từ Excel.

View mỏng: đọc tham số, gọi `ledger` / `importer`, hiển thị. Không có quy tắc nghiệp vụ nào ở đây.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import OrgUnit
from apps.accounts.roles import FAD_BUDGET_ADMIN
from apps.core.services import get_setting
from apps.ui.feedback import domain_errors
from apps.ui.responses import xlsx_response
from apps.ui.tables import Column, TableSpec, apply_table

from .importer import import_budget_workbook
from .models import BUDGET_KINDS, ENTRY_KINDS, EXPENSE_KINDS, RESERVED_KINDS, BudgetEntry, BudgetLine
from .visibility import visible_lines

FORBIDDEN = "Bạn không có quyền xem dòng ngân sách này."
SESSION_KEY = "budget_import"
MONEY = DecimalField(max_digits=18, decimal_places=0)

LINE_SPEC = TableSpec(
    key="ngan-sach",
    columns=[
        Column("year", "Năm"),
        Column("budget_unit__code", "Đơn vị NS"),
        Column("cost_code__code", "Mã chi phí (L8)"),
        Column("project__code", "Dự án (L10)"),
        Column("location__code", "Địa điểm"),
        Column("budget", "Ngân sách", money=True),
        Column("reserved", "Đã giữ chỗ", money=True),
        Column("expensed", "Đã ghi nhận", money=True),
        Column("available", "Khả dụng", money=True),
    ],
    filters={"nam": "year", "don_vi": "budget_unit__code"},
    search_fields=["cost_code__code", "project__code", "cost_code__name", "project__name"],
    default_sort=["year", "budget_unit__code", "cost_code__code"],
    row_url="budget_ledger",
)

ENTRY_SPEC = TableSpec(
    key="so-cai-ngan-sach",
    columns=[
        Column("period", "Kỳ"),
        Column("get_kind_display", "Loại bút toán", sortable=False),
        Column("amount", "Số tiền (VND)", money=True, sum=True),
        Column("note", "Ghi chú", sortable=False),
        Column("source_type", "Hồ sơ nguồn"),
        Column("source_id", "Mã hồ sơ", sortable=False),
        Column("created_at", "Ghi lúc"),
    ],
    filters={"ky": "period", "loai": "kind"},
    default_sort=["period", "id"],
)


def _sum(kinds):
    return Coalesce(Sum("entries__amount", filter=Q(entries__kind__in=kinds)), Value(0), output_field=MONEY)


def _with_balances(qs):
    return qs.annotate(
        budget=_sum(BUDGET_KINDS), reserved=_sum(RESERVED_KINDS), expensed=_sum(EXPENSE_KINDS)
    ).annotate(available=F("budget") - F("reserved") - F("expensed"))


@login_required
def budget_list(request):
    table = apply_table(request, _with_balances(visible_lines(request.user)), LINE_SPEC)
    return render(request, "ui/list_page.html", {
        "heading": "Dòng ngân sách và số dư",
        "intro": "Đơn vị quản lý xem phần của mình; FAD và Kiểm toán xem toàn công ty.",
        "spec": LINE_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "nam", "label": "Năm", "options": None, "value": table.params.get("nam", "")},
            {"name": "don_vi", "label": "Đơn vị ngân sách", "options": None,
             "value": table.params.get("don_vi", "")},
        ],
        "actions": [{"url": "/ngan-sach/nhap-excel/", "label": "Nhập ngân sách từ Excel"},
                    {"url": "/ngan-sach/de-nghi/", "label": "Đề nghị bổ sung / điều chuyển"}],
        "export_url": "/ngan-sach/xuat/",
    })


@login_required
def budget_export(request):
    table = apply_table(request, _with_balances(visible_lines(request.user)), LINE_SPEC)
    return xlsx_response(request, LINE_SPEC, table.qs, "ngan-sach.xlsx", back="budget_list")


@login_required
def budget_ledger(request, pk):
    line = get_object_or_404(BudgetLine, pk=pk)
    if not visible_lines(request.user).filter(pk=pk).exists():
        raise PermissionDenied(FORBIDDEN)
    table = apply_table(request, BudgetEntry.objects.filter(line=line), ENTRY_SPEC)
    return render(request, "budget/ledger.html", {
        "heading": f"Sổ cái ngân sách · {line}",
        "line": line,
        "spec": ENTRY_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "loai", "label": "Loại bút toán", "options": ENTRY_KINDS,
             "value": table.params.get("loai", "")},
        ],
    })


# --- nhập ngân sách từ Excel ----------------------------------------------------------------------

def _store_temp(upload) -> str:
    token = uuid.uuid4().hex
    folder = Path(tempfile.mkdtemp(prefix=f"budget-import-{token}-"))
    target = folder / "ngan-sach.xlsx"
    with open(target, "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return str(target)


def _clear_temp(request) -> None:
    pending = request.session.pop(SESSION_KEY, None)
    if pending:
        shutil.rmtree(Path(pending["path"]).parent, ignore_errors=True)


def _params(source) -> dict:
    return {
        "budget_unit_code": (source.get("budget_unit_code") or "").strip(),
        "year": source.get("year") or timezone.localdate().year,
        "managing_org_unit_code": (source.get("managing_org_unit_code") or "").strip() or None,
    }


@login_required
@role_required(FAD_BUDGET_ADMIN)
def budget_import(request):
    """Tải lên → báo cáo làm sạch (chạy thử) → xác nhận nhập. Tệp chờ nằm trong thư mục tạm của phiên."""
    report, pending = None, request.session.get(SESSION_KEY)
    if request.method == "POST":
        if request.POST.get("action") == "cancel":
            _clear_temp(request)
            messages.info(request, "Đã bỏ tệp ngân sách đang chờ nhập.")
            return redirect("budget_import")
        if request.POST.get("action") == "confirm":
            return _confirm(request, pending)
        report, pending = _dry_run(request)
    return render(request, "budget/import.html", {
        "heading": "Nhập ngân sách từ Excel",
        "report": report,
        "pending": pending,
        "org_units": OrgUnit.objects.filter(is_active=True),
        "max_upload_mb": get_setting("max_upload_mb"),
    })


def _dry_run(request):
    upload = request.FILES.get("file")
    params = _params(request.POST)
    if upload is None:
        messages.error(request, "Vui lòng chọn tệp Excel ngân sách.")
        return None, None
    max_mb = get_setting("max_upload_mb")
    if upload.size > max_mb * 1024 * 1024:
        messages.error(request, f"Tệp vượt quá {max_mb} MB.")
        return None, None
    if not params["budget_unit_code"]:
        messages.error(request, "Vui lòng nhập mã đơn vị ngân sách.")
        return None, None

    _clear_temp(request)
    path = _store_temp(upload)
    report = None
    with domain_errors(request):
        report = import_budget_workbook(path, user=request.user, dry_run=True, **params)
    if report is None:
        shutil.rmtree(Path(path).parent, ignore_errors=True)
        return None, None
    if report.ok:
        request.session[SESSION_KEY] = {"path": path, "name": upload.name, **params}
        messages.success(request, "Tệp hợp lệ. Hãy kiểm tra báo cáo rồi bấm "
                                  "“Xác nhận nhập” để ghi vào hệ thống.")
    else:
        shutil.rmtree(Path(path).parent, ignore_errors=True)
        messages.error(request, "Tệp còn lỗi cần sửa; chưa ghi gì vào hệ thống.")
    return report, request.session.get(SESSION_KEY)


def _confirm(request, pending):
    if not pending or not Path(pending["path"]).is_file():
        _clear_temp(request)
        messages.error(request, "Không còn tệp đang chờ; vui lòng tải lên lại.")
        return redirect("budget_import")
    report = None
    with domain_errors(request):
        report = import_budget_workbook(
            pending["path"], user=request.user, dry_run=False, **_params(pending)
        )
    if report is not None and report.ok:
        messages.success(request, "Đã nhập ngân sách: " + ", ".join(
            f"{key}: {value}" for key, value in report.created.items()
        ) + ".")
    elif report is not None:
        messages.error(request, "Tệp còn lỗi cần sửa; chưa ghi gì vào hệ thống.")
    _clear_temp(request)
    return redirect("budget_list")
