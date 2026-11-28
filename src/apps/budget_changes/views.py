"""Màn hình đề nghị bổ sung / điều chuyển ngân sách (tạo được từ tờ trình bị chặn).

View mỏng: đọc tham số, gọi `budget_changes.services`, hiển thị.
"""

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.budget import ledger
from apps.budget.visibility import visible_lines
from apps.requisitions.models import Requisition
from apps.ui.feedback import domain_errors
from apps.ui.tables import Column, TableSpec, apply_table
from apps.workflow import views as workflow_views

from . import services
from .models import DRAFT, KINDS, STATUSES, BudgetChangeRequest

FORBIDDEN = "Bạn không có quyền xem đề nghị ngân sách này."

LIST_SPEC = TableSpec(
    key="de-nghi-ngan-sach",
    columns=[
        Column("number", "Số đề nghị"),
        Column("get_kind_display", "Loại", sortable=False),
        Column("to_line__cost_code__code", "Dòng nhận"),
        Column("amount_vnd", "Số tiền (VND)", money=True, sum=True),
        Column("start", "Kỳ bắt đầu"),
        Column("months", "Số tháng"),
        Column("get_status_display", "Trạng thái", sortable=False),
        Column("created_at", "Tạo lúc"),
    ],
    filters={"trang_thai": "status", "loai": "kind"},
    search_fields=["number", "reason"],
    default_sort=["-created_at"],
    row_url="budget_change_detail",
)


def _visible_or_403(request, pk) -> BudgetChangeRequest:
    bcr = get_object_or_404(BudgetChangeRequest, pk=pk)
    if not bcr.visible_to(request.user):
        raise PermissionDenied(FORBIDDEN)
    return bcr


@login_required
def budget_change_list(request):
    table = apply_table(request, BudgetChangeRequest.objects.visible_to(request.user), LIST_SPEC)
    return render(request, "ui/list_page.html", {
        "heading": "Đề nghị bổ sung / điều chuyển ngân sách",
        "spec": LIST_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "trang_thai", "label": "Trạng thái", "options": STATUSES,
             "value": table.params.get("trang_thai", "")},
            {"name": "loai", "label": "Loại đề nghị", "options": KINDS, "value": table.params.get("loai", "")},
        ],
        "actions": [{"url": "/ngan-sach/de-nghi/tao/", "label": "Tạo đề nghị"}],
    })


@login_required
def budget_change_create(request):
    """Tạo đề nghị nháp; `?tu_to_trinh=<id>` tạo sẵn các đề nghị bổ sung cho tờ trình bị chặn."""
    from_req = request.GET.get("tu_to_trinh") or request.POST.get("tu_to_trinh")
    req = None
    if from_req:
        req = get_object_or_404(Requisition, pk=from_req)
        if not req.visible_to(request.user):
            raise PermissionDenied(FORBIDDEN)

    if request.method == "POST":
        if req is not None:
            return _prefill(request, req)
        return _create(request)
    return render(request, "budget_changes/form.html", {
        "heading": "Tạo đề nghị bổ sung / điều chuyển ngân sách",
        "requisition": req,
        "shortfalls": ledger.check_reserve(
            req.budget_allocations(), start=req.reserve_start, months=req.months
        )[0] if req is not None and req.fundings.exists() else [],
        "kinds": KINDS,
        "lines": visible_lines(request.user).select_related("budget_unit", "cost_code", "project", "location"),
    })


def _prefill(request, req):
    created = []
    with domain_errors(request, success="Đã tạo sẵn đề nghị bổ sung ngân sách từ tờ trình."):
        shortfalls, _ = ledger.check_reserve(
            req.budget_allocations(), start=req.reserve_start, months=req.months
        )
        created = services.prefill_from_shortfall(req, shortfalls, request.user)
    if created:
        return redirect("budget_change_detail", pk=created[0].pk)
    return redirect("budget_change_list")


def _amount(raw) -> Decimal:
    try:
        return Decimal((raw or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Số tiền đề nghị không hợp lệ.") from exc


def _create(request):
    post = request.POST
    bcr = None
    with domain_errors(request, success="Đã lưu đề nghị nháp."):
        lines = visible_lines(request.user)
        to_line = lines.filter(pk=post.get("to_line")).first()
        if to_line is None:
            raise ValueError("Vui lòng chọn dòng ngân sách nhận.")
        bcr = BudgetChangeRequest.objects.create(
            kind=post.get("kind", ""),
            to_line=to_line,
            from_line=lines.filter(pk=post.get("from_line")).first(),
            amount_vnd=_amount(post.get("amount_vnd")),
            start=parse_date(post.get("start") or "") or timezone.localdate(),
            months=post.get("months") or 1,
            reason=post.get("reason", ""),
            requester=request.user,
            created_by=request.user,
        )
    if bcr is None:
        return redirect("budget_change_create")
    return redirect("budget_change_detail", pk=bcr.pk)


@login_required
def budget_change_detail(request, pk):
    bcr = _visible_or_403(request, pk)
    tasks = []
    for instance in bcr.workflow_instances().select_related("policy", "rule").order_by("-pk"):
        for task in workflow_views.approval_history(instance):
            task.instance = instance
            tasks.append(task)
    return render(request, "budget_changes/detail.html", {
        "bcr": bcr,
        "to_balance": ledger.balance(bcr.to_line),
        "from_balance": ledger.balance(bcr.from_line) if bcr.from_line_id else None,
        "history": tasks,
        "audit_events": workflow_views.subject_audit(bcr),
        "submit_errors": services.validate_for_submit(bcr) if bcr.status == DRAFT else [],
        "can_submit": bcr.status == DRAFT,
    })


@login_required
@require_POST
def budget_change_submit(request, pk):
    bcr = _visible_or_403(request, pk)
    with domain_errors(request, success="Đã nộp đề nghị, luồng duyệt bắt đầu."):
        services.submit(bcr, request.user)
    return redirect("budget_change_detail", pk=pk)
