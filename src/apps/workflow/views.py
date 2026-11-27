"""Màn hình "Việc chờ tôi", chi tiết bước xử lý, xử lý hàng loạt và uỷ quyền của chính mình.

View mỏng: đọc tham số, gọi service (`engine`, `delegation`, `inbox`), hiển thị. Lỗi nghiệp vụ ra
`messages` qua `ui.feedback.domain_errors`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.documents.models import DELEGATION_LETTER, Document
from apps.documents.permissions import can_view_object
from apps.documents.storage import store_upload
from apps.ui.feedback import domain_errors, error_message
from apps.ui.tables import Column, TableSpec, apply_table

from . import delegation as delegation_service
from . import engine, inbox
from .models import CONSULT, Delegation, WorkflowTask

FORBIDDEN = "Bạn không có quyền xem bước xử lý này."
NOTHING_SELECTED = "Vui lòng chọn ít nhất một hồ sơ để xử lý."

INBOX_SPEC = TableSpec(
    key="viec-cho-toi",
    columns=[
        Column("instance__subject", "Hồ sơ", sortable=False),
        Column("get_kind_display", "Bước", sortable=False),
        Column("role_code", "Vai trò"),
        Column("org_unit__name", "Đơn vị"),
        Column("opened_at", "Đến lượt lúc"),
        Column("due_at", "Hạn xử lý"),
    ],
    filters={"buoc": "kind", "vai_tro": "role_code"},
    default_sort=["due_at", "opened_at"],
    selectable=True,
    row_url="task_detail",
)


@login_required
def inbox_page(request):
    qs = inbox.tasks_for(request.user).select_related("instance", "org_unit").prefetch_related("instance__subject")
    table = apply_table(request, qs, INBOX_SPEC)
    return render(request, "workflow/inbox.html", {
        "heading": "Việc chờ tôi",
        "spec": INBOX_SPEC,
        "table": table,
        "decisions": [("APPROVE", "Chấp thuận"), ("REJECT", "Từ chối"), ("RETURN", "Trả lại bổ sung")],
    })


def _task_or_403(request, pk):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance", "org_unit"), pk=pk)
    subject = task.instance.subject
    if not can_view_object(request.user, subject):
        return None, None, HttpResponseForbidden(FORBIDDEN)
    return task, subject, None


def approval_history(instance):
    return instance.tasks.select_related("org_unit", "acted_by", "on_behalf_of").order_by("seq", "pk")


def subject_audit(subject):
    return AuditEvent.objects.filter(
        object_type=subject._meta.label_lower, object_id=str(subject.pk)
    ).select_related("actor").order_by("-id")[:100]


def subject_documents(subject):
    from django.contrib.contenttypes.models import ContentType

    return Document.objects.filter(
        content_type=ContentType.objects.get_for_model(subject), object_id=str(subject.pk),
        superseded_by__isnull=True,
    ).select_related("uploaded_by")


@login_required
def task_detail(request, pk):
    task, subject, denied = _task_or_403(request, pk)
    if denied:
        return denied
    instance = task.instance
    history = list(approval_history(instance))
    return render(request, "workflow/task_detail.html", {
        "task": task,
        "instance": instance,
        "subject": subject,
        "history": history,
        "opinions": [t for t in history if t.kind == CONSULT and t.comment],
        "documents": subject_documents(subject),
        "audit_events": subject_audit(subject),
        "on_behalf_of": delegation_service.can_act_on_behalf(request.user, task),
        "decisions": _decisions_for(task),
    })


def _decisions_for(task):
    if task.mandatory:
        return [("APPROVE", "Chấp thuận"), ("REJECT", "Từ chối"), ("RETURN", "Trả lại bổ sung")]
    return [("COMMENT", "Gửi ý kiến")]


@login_required
@require_POST
def task_act(request, pk):
    task, _subject, denied = _task_or_403(request, pk)
    if denied:
        return denied
    on_behalf_of = None
    if request.POST.get("on_behalf_of"):
        on_behalf_of = User.objects.filter(pk=request.POST["on_behalf_of"]).first()
    with domain_errors(request, success="Đã ghi nhận ý kiến xử lý."):
        engine.act(task, request.user, request.POST.get("decision", ""), request.POST.get("comment", ""),
                   on_behalf_of=on_behalf_of)
    return redirect("task_detail", pk=pk)


@login_required
@require_POST
def bulk_act(request):
    """Xử lý nhiều bước một lượt: mỗi bước một transaction riêng, báo kết quả từng hồ sơ."""
    ids = request.POST.getlist("ids")
    decision = request.POST.get("decision", "")
    comment = request.POST.get("comment", "")
    if not ids:
        messages.error(request, NOTHING_SELECTED)
        return redirect("home")

    # Quyền xử lý do `engine.act` quyết định (tính lại tại thời điểm xử lý, kể cả uỷ quyền và
    # phân tách nhiệm vụ) — ở đây chỉ gom kết quả từng hồ sơ.
    found = {str(t.pk): t for t in WorkflowTask.objects.filter(pk__in=ids).select_related("instance")}
    done, failed = [], []
    for raw in ids:
        task = found.get(raw)
        if task is None:
            failed.append((f"#{raw}", "Không tìm thấy bước xử lý."))
            continue
        subject = task.instance.subject
        label = str(subject) if can_view_object(request.user, subject) else f"Hồ sơ #{task.pk}"
        try:
            with transaction.atomic():
                engine.act(task, request.user, decision, comment)
        except Exception as exc:  # noqa: BLE001  (một hồ sơ lỗi không chặn các hồ sơ còn lại)
            failed.append((label, error_message(exc)))
        else:
            done.append(label)

    if done:
        messages.success(request, f"Đã xử lý {len(done)} hồ sơ: " + "; ".join(done) + ".")
    for label, reason in failed:
        messages.error(request, f"{label}: {reason}")
    if failed:
        messages.warning(request, f"{len(failed)} hồ sơ không xử lý được.")
    return redirect("home")


# --- uỷ quyền của chính mình ----------------------------------------------------------------------

@login_required
def delegations(request):
    if request.method == "POST":
        _create_delegation(request)
        return redirect("delegations")
    today = timezone.localdate()
    return render(request, "workflow/delegations.html", {
        "given": Delegation.objects.filter(delegator=request.user).select_related("delegate", "org_unit", "letter"),
        "received": Delegation.objects.filter(delegate=request.user).select_related("delegator"),
        "today": today,
        "candidates": User.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("username"),
    })


def _create_delegation(request) -> None:
    """Tạo uỷ quyền kèm văn bản trong MỘT transaction: uỷ quyền không hợp lệ thì chứng từ cũng không còn.

    Văn bản gắn vào người uỷ quyền (`Delegation.letter` phải có sẵn khi tạo và uỷ quyền là bất biến),
    nên quyền xem của hai bên do `documents.permissions.can_view_document` mở riêng.
    """
    post = request.POST
    with domain_errors(request, success="Đã tạo uỷ quyền duyệt thay."):
        with transaction.atomic():
            delegate = User.objects.filter(pk=post.get("delegate"), is_active=True).first()
            if delegate is None:
                raise ValueError("Vui lòng chọn người nhận uỷ quyền.")
            letter = None
            if request.FILES.get("letter"):
                letter = store_upload(
                    request.FILES["letter"], attach_to=request.user, doc_type=DELEGATION_LETTER,
                    user=request.user,
                )
            delegation_service.create_delegation(
                request.user, delegate,
                start_date=post.get("start_date") or timezone.localdate(),
                end_date=post.get("end_date") or timezone.localdate(),
                max_amount_vnd=post.get("max_amount_vnd") or None,
                subject_kinds=post.getlist("subject_kinds"),
                letter=letter,
                actor=request.user,
            )


@login_required
@require_POST
def delegation_revoke(request, pk):
    item = get_object_or_404(Delegation, pk=pk, delegator=request.user)
    with domain_errors(request, success="Đã thu hồi uỷ quyền."):
        item.revoke(request.user)
    return redirect("delegations")
