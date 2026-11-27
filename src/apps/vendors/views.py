"""Màn hình nhà cung cấp: danh sách và nhập từ Excel (xem báo cáo làm sạch rồi xác nhận)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.decorators import role_required
from apps.accounts.roles import FAD_BUDGET_ADMIN
from apps.core.imports import ImportReport, open_workbook
from apps.core.services import get_setting
from apps.ui.feedback import domain_errors
from apps.ui.responses import xlsx_response
from apps.ui.tables import Column, TableSpec, apply_table

from .importer import import_vendors_from_rows, read_vendor_sheet
from .models import KINDS, STATUSES, Vendor

LIST_SPEC = TableSpec(
    key="nha-cung-cap",
    columns=[
        Column("code", "Mã"),
        Column("tax_code", "Mã số thuế"),
        Column("name", "Tên nhà cung cấp"),
        Column("get_kind_display", "Loại hình", sortable=False),
        Column("get_status_display", "Trạng thái", sortable=False),
        Column("bank_name", "Ngân hàng"),
        Column("bank_account", "Số tài khoản", sortable=False),
    ],
    filters={"trang_thai": "status", "loai": "kind"},
    search_fields=["name", "tax_code", "code"],
    default_sort=["name"],
)


@login_required
def vendor_list(request):
    table = apply_table(request, Vendor.objects.all(), LIST_SPEC)
    return render(request, "ui/list_page.html", {
        "heading": "Nhà cung cấp",
        "spec": LIST_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "trang_thai", "label": "Trạng thái", "options": STATUSES,
             "value": table.params.get("trang_thai", "")},
            {"name": "loai", "label": "Loại hình", "options": KINDS, "value": table.params.get("loai", "")},
        ],
        "actions": [{"url": "/nha-cung-cap/nhap-excel/", "label": "Nhập từ Excel"}],
        "export_url": "/nha-cung-cap/xuat/",
    })


@login_required
def vendor_export(request):
    table = apply_table(request, Vendor.objects.all(), LIST_SPEC)
    return xlsx_response(request, LIST_SPEC, table.qs, "nha-cung-cap.xlsx", back="vendor_list")


@login_required
@role_required(FAD_BUDGET_ADMIN)
def vendor_import(request):
    """Tải lên → báo cáo làm sạch (chạy thử) → tích "Xác nhận nhập" để ghi."""
    report, confirmed = None, request.POST.get("confirm") == "1"
    if request.method == "POST":
        report = _run(request, confirmed)
    return render(request, "vendors/import.html", {
        "heading": "Nhập nhà cung cấp từ Excel",
        "report": report,
        "confirmed": confirmed,
        "max_upload_mb": get_setting("max_upload_mb"),
    })


def _read_rows(upload, report):
    workbook = open_workbook(upload)
    try:
        rows = read_vendor_sheet(workbook, report)
    finally:
        workbook.close()
    if rows is None:
        raise ValueError("Tệp không có sheet L9_Code (danh sách nhà cung cấp).")
    return rows


def _run(request, confirmed: bool):
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Vui lòng chọn tệp Excel nhà cung cấp.")
        return None
    max_mb = get_setting("max_upload_mb")
    if upload.size > max_mb * 1024 * 1024:
        messages.error(request, f"Tệp vượt quá {max_mb} MB.")
        return None

    result = None
    with domain_errors(request):
        report = ImportReport()
        rows = _read_rows(upload, report)
        result = report if report.issues else import_vendors_from_rows(rows, request.user, dry_run=not confirmed)
    if result is None:
        return None
    if not result.ok:
        messages.error(request, "Tệp còn lỗi cần sửa; chưa ghi gì vào hệ thống.")
    elif confirmed:
        messages.success(request, "Đã nhập danh sách nhà cung cấp.")
    else:
        messages.success(request, "Tệp hợp lệ. Tải lại tệp kèm “Xác nhận nhập” để ghi vào hệ thống.")
    return result
