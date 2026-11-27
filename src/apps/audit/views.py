"""Tra cứu nhật ký audit (Kiểm toán và FAD), xuất xlsx. Chỉ đọc — bản ghi audit là bất biến."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.decorators import role_required
from apps.accounts.roles import AUDITOR, FAD_BUDGET_ADMIN, FAD_PRECHECK
from apps.ui.responses import xlsx_response
from apps.ui.tables import Column, TableSpec, apply_table

from .models import AuditEvent

READERS = (AUDITOR, FAD_PRECHECK, FAD_BUDGET_ADMIN)

LIST_SPEC = TableSpec(
    key="nhat-ky",
    columns=[
        Column("id", "STT"),
        Column("occurred_at", "Thời điểm"),
        Column("actor_label", "Người thực hiện"),
        Column("action", "Hành động"),
        Column("object_type", "Loại đối tượng"),
        Column("object_id", "Mã đối tượng", sortable=False),
        Column("ip", "Địa chỉ IP", sortable=False),
        Column("changes", "Thay đổi", sortable=False),
    ],
    filters={"hanh_dong": "action", "doi_tuong": "object_type", "tu_ngay": "occurred_at__date__gte",
             "den_ngay": "occurred_at__date__lte"},
    search_fields=["action", "actor_label", "object_type"],
    default_sort=["-id"],
)


@login_required
@role_required(*READERS)
def audit_list(request):
    table = apply_table(request, AuditEvent.objects.all(), LIST_SPEC)
    return render(request, "ui/list_page.html", {
        "heading": "Nhật ký hệ thống",
        "intro": "Bản ghi nối chuỗi băm, chỉ ghi thêm. Dùng lệnh `audit_verify` để kiểm tra tính toàn vẹn.",
        "spec": LIST_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "hanh_dong", "label": "Hành động", "options": None,
             "value": table.params.get("hanh_dong", "")},
            {"name": "tu_ngay", "label": "Từ ngày", "options": None, "value": table.params.get("tu_ngay", "")},
            {"name": "den_ngay", "label": "Đến ngày", "options": None, "value": table.params.get("den_ngay", "")},
        ],
        "export_url": "/nhat-ky/xuat/",
    })


@login_required
@role_required(*READERS)
def audit_export(request):
    table = apply_table(request, AuditEvent.objects.all(), LIST_SPEC)
    return xlsx_response(request, LIST_SPEC, table.qs, "nhat-ky.xlsx", back="audit_list")
