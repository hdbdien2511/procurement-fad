"""Màn hình tờ trình mua sắm: danh sách, lập mới, chi tiết, các hành động và trang tiền kiểm.

View mỏng: đọc tham số, gọi service (`requisitions.services`, `budget.ledger`, `workflow.*`,
`documents.storage`), hiển thị. Không có quy tắc nghiệp vụ nào ở đây.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.roles import FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role
from apps.budget import ledger
from apps.documents.models import DOC_TYPES, OTHER, Document
from apps.ui.feedback import domain_errors
from apps.ui.responses import xlsx_response
from apps.ui.tables import Column, TableSpec, apply_table
from apps.workflow import engine, splitting, subject
from apps.workflow import views as workflow_views
from apps.workflow.models import CONSULT, PENDING
from apps.workflow.models import FAD_PRECHECK as FAD_PRECHECK_STEP

from . import services
from .forms import FundingFormSet, LineFormSet, RequisitionForm
from .models import APPROVED, BUDGET_BLOCKED, DRAFT, IN_APPROVAL, RETURNED, STATUSES, Requisition

FORBIDDEN = "Bạn không có quyền xem tờ trình này."
NO_PRECHECK_TASK = "Tờ trình này không có bước FAD tiền kiểm đang chờ xử lý."

LIST_SPEC = TableSpec(
    key="to-trinh",
    columns=[
        Column("number", "Số tờ trình"),
        Column("title", "Tiêu đề"),
        Column("requester_unit__name", "Đơn vị đề nghị"),
        Column("requester__first_name", "Người đề nghị"),
        Column("total_vnd", "Tổng tiền (VND)", money=True, sum=True),
        Column("get_status_display", "Trạng thái", sortable=False),
        Column("created_at", "Tạo lúc"),
    ],
    filters={"trang_thai": "status", "loai": "procurement_type", "tu_ngay": "created_at__date__gte"},
    search_fields=["number", "title"],
    default_sort=["-created_at"],
    row_url="requisition_detail",
)


def _visible_or_403(request, pk) -> Requisition:
    req = get_object_or_404(Requisition, pk=pk)
    if not req.visible_to(request.user):
        raise PermissionDenied(FORBIDDEN)
    return req


def _budget_check(req):
    """Chạy thử giữ chỗ cho bản nháp; dữ liệu nháp chưa hợp lệ thì bỏ qua (lỗi đã nêu ở phần kiểm tra)."""
    try:
        return services.check_budget(req)
    except (ValueError, ArithmeticError):
        return None


@login_required
def requisition_list(request):
    qs = Requisition.objects.visible_to(request.user)
    table = apply_table(request, qs, LIST_SPEC)
    return render(request, "ui/list_page.html", {
        "heading": "Tờ trình mua sắm",
        "spec": LIST_SPEC,
        "table": table,
        "filter_fields": [
            {"name": "trang_thai", "label": "Trạng thái", "options": STATUSES,
             "value": table.params.get("trang_thai", "")},
        ],
        "actions": [{"url": "/to-trinh/tao/", "label": "Lập tờ trình"}],
        "export_url": "/to-trinh/xuat/",
    })


@login_required
def requisition_export(request):
    table = apply_table(request, Requisition.objects.visible_to(request.user), LIST_SPEC)
    return xlsx_response(request, LIST_SPEC, table.qs, "to-trinh.xlsx", back="requisition_list")


@login_required
def requisition_create(request):
    """Lập tờ trình nháp: phần đầu + dòng hàng + phân bổ ngân sách trong một lần lưu."""
    form = RequisitionForm(request.POST or None)
    lines = LineFormSet(request.POST or None, prefix="lines")
    fundings = FundingFormSet(request.POST or None, prefix="fundings")
    if request.method == "POST" and form.is_valid() and lines.is_valid() and fundings.is_valid():
        req = form.save(commit=False)
        req.requester = request.user
        req.created_by = request.user
        with domain_errors(request, success="Đã lưu tờ trình nháp."):
            req.save()
            form.save_m2m()
            for formset in (lines, fundings):
                formset.instance = req
                formset.save()
            return redirect("requisition_detail", pk=req.pk)
        return redirect("requisition_create")
    return render(request, "requisitions/form.html", {
        "form": form, "lines": lines, "fundings": fundings, "heading": "Lập tờ trình mua sắm",
    })


def _fundings_with_balance(req):
    rows = []
    for funding in req.fundings.select_related(
        "budget_line__budget_unit", "budget_line__cost_code", "budget_line__project", "budget_line__location"
    ):
        rows.append({"funding": funding, "balance": ledger.balance(funding.budget_line)})
    return rows


def _instances(req):
    return req.workflow_instances().select_related("policy", "rule").order_by("-pk")


def _all_tasks(req):
    tasks = []
    for instance in _instances(req):
        for task in workflow_views.approval_history(instance):
            task.instance = instance
            tasks.append(task)
    return tasks


@login_required
def requisition_detail(request, pk):
    req = _visible_or_403(request, pk)
    tasks = _all_tasks(req)
    can_act = subject.is_owner(req, request.user)
    is_budget_admin = has_role(request.user, FAD_BUDGET_ADMIN)
    return render(request, "requisitions/detail.html", {
        "req": req,
        "lines": req.lines.all(),
        "fundings": _fundings_with_balance(req),
        "documents": workflow_views.subject_documents(req),
        "doc_types": DOC_TYPES,
        "history": tasks,
        "opinions": [t for t in tasks if t.kind == CONSULT and t.comment],
        "audit_events": workflow_views.subject_audit(req),
        "split_warnings": splitting.split_warnings(req),
        "budget_check": _budget_check(req) if req.status == DRAFT else None,
        "submit_errors": services.validate_for_submit(req) if req.status == DRAFT else [],
        "can_submit": can_act and req.status == DRAFT,
        "can_revise": can_act and req.status == RETURNED,
        # Quyền cuối cùng do service quyết định; ở đây chỉ ẩn nút rõ ràng không dùng được (spec 4.1).
        "can_cancel": (can_act and req.status in (DRAFT, RETURNED, IN_APPROVAL, BUDGET_BLOCKED))
                      or (is_budget_admin and req.status in (BUDGET_BLOCKED, APPROVED)),
        "can_retry_reserve": req.status == BUDGET_BLOCKED
                             and (is_budget_admin or has_role(request.user, FAD_PRECHECK)),
        # Khi hồ sơ đang duyệt, người đang xử lý bước duyệt đính kèm được (ví dụ biên bản họp).
        "can_upload": req.status in (DRAFT, RETURNED)
                      or (req.status == IN_APPROVAL and services.handles_pending_task(req, request.user)),
    })


@login_required
@require_POST
def requisition_submit(request, pk):
    req = _visible_or_403(request, pk)
    with domain_errors(request, success="Đã nộp tờ trình, luồng duyệt bắt đầu."):
        services.submit(req, request.user)
    return redirect("requisition_detail", pk=pk)


@login_required
@require_POST
def requisition_copy(request, pk):
    req = _visible_or_403(request, pk)
    new = None
    with domain_errors(request, success="Đã sao chép thành tờ trình nháp mới."):
        new = services.copy_as_new(req, request.user)
    return redirect("requisition_detail", pk=new.pk if new else pk)


@login_required
@require_POST
def requisition_revise(request, pk):
    req = _visible_or_403(request, pk)
    new = None
    with domain_errors(request, success="Đã tạo phiên bản mới của tờ trình."):
        new = services.revise(req, request.user)
    return redirect("requisition_detail", pk=new.pk if new else pk)


@login_required
@require_POST
def requisition_cancel(request, pk):
    req = _visible_or_403(request, pk)
    with domain_errors(request, success="Đã huỷ tờ trình."):
        services.cancel(req, request.user, request.POST.get("reason", ""))
    return redirect("requisition_detail", pk=pk)


@login_required
@require_POST
def requisition_retry_reserve(request, pk):
    req = _visible_or_403(request, pk)
    with domain_errors(request, success="Đã giữ chỗ lại ngân sách cho tờ trình."):
        warnings = services.retry_reserve(req, request.user)
        for warning in warnings:
            messages.warning(request, warning)
    return redirect("requisition_detail", pk=pk)


@login_required
@require_POST
def requisition_upload(request, pk):
    req = _visible_or_403(request, pk)
    with domain_errors(request, success="Đã tải chứng từ lên."):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValueError("Vui lòng chọn tệp cần tải lên.")
        # Quyền ghi do service quyết định (hẹp hơn quyền xem): người lập/đề nghị, nháp hoặc trả lại.
        services.attach_document(req, request.user, upload, request.POST.get("doc_type") or OTHER)
    return redirect("requisition_detail", pk=pk)


# --- tiền kiểm (FAD) ------------------------------------------------------------------------------

def _precheck_task(req):
    for instance in _instances(req):
        task = instance.tasks.filter(kind=FAD_PRECHECK_STEP, status=PENDING).order_by("seq", "pk").first()
        if task is not None:
            task.instance = instance
            return task
    return None


def _document_checklist(req):
    """Các loại chứng từ cần có và số bản hiện hành đã đính kèm."""
    counts = dict.fromkeys([code for code, _ in DOC_TYPES], 0)
    docs = Document.objects.filter(
        content_type=ContentType.objects.get_for_model(req), object_id=str(req.pk), superseded_by__isnull=True,
    ).values_list("doc_type", flat=True)
    for code in docs:
        counts[code] = counts.get(code, 0) + 1
    return [{"code": code, "label": label, "count": counts.get(code, 0)} for code, label in DOC_TYPES]


@login_required
@role_required(FAD_PRECHECK)
def requisition_precheck(request, pk):
    req = _visible_or_403(request, pk)
    task = _precheck_task(req)
    tasks = _all_tasks(req)
    instance = task.instance if task is not None else _instances(req).first()
    return render(request, "requisitions/precheck.html", {
        "req": req,
        "task": task,
        "instance": instance,
        "snapshot_steps": (instance.snapshot.get("steps") if instance else []) or [],
        "rule": (instance.snapshot.get("rule") if instance else {}) or {},
        "fundings": _fundings_with_balance(req),
        "split_warnings": splitting.split_warnings(req),
        "opinions": [t for t in tasks if t.kind == CONSULT and t.comment],
        "checklist": _document_checklist(req),
        "documents": workflow_views.subject_documents(req),
    })


@login_required
@role_required(FAD_PRECHECK)
@require_POST
def requisition_precheck_act(request, pk):
    req = _visible_or_403(request, pk)
    task = _precheck_task(req)
    if task is None:
        messages.error(request, NO_PRECHECK_TASK)
        return redirect("requisition_precheck", pk=pk)
    decision = "APPROVE" if request.POST.get("decision") == "PASS" else "RETURN"
    with domain_errors(request, success="Đã ghi nhận kết quả tiền kiểm."):
        engine.act(task, request.user, decision, request.POST.get("comment", ""))
    return redirect("requisition_precheck", pk=pk)
