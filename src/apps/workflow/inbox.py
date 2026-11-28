"""Hộp việc "Việc chờ tôi": các bước đang chờ mà người dùng được xử lý trực tiếp hoặc duyệt thay.

Một truy vấn duy nhất, dựng theo cùng cách với `apps.workflow.visibility` (phân công vai trò + phạm
vi làm điều kiện con), nên danh sách dùng được với `apply_table` (lọc/sắp xếp/phân trang).

Bao gồm:
- bước `PENDING` đúng vai trò + phạm vi phân công của người dùng (phân công toàn công ty thoả mọi
  đơn vị), trừ các hồ sơ do chính họ nộp/lập/đề nghị và trừ người giữ `SYS_ADMIN`;
- bước `PENDING` mà họ được duyệt thay theo uỷ quyền còn hiệu lực (phạm vi đơn vị / loại hồ sơ /
  hạn mức của uỷ quyền).

Việc chặn cuối cùng vẫn do `engine.act` quyết định (tính lại tại thời điểm xử lý).
"""

from django.db.models import DecimalField, Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils import timezone

from . import resolver
from .models import PENDING, RUNNING, Delegation, WorkflowTask
from .visibility import NOTHING, assignments, task_scope

AMOUNT = "_context_amount_vnd"


def _delegated_scope(user, sys_admins) -> Q:
    today = timezone.localdate()
    delegations = list(
        Delegation.objects.filter(
            delegate_id=user.pk, start_date__lte=today, end_date__gte=today, revoked_at__isnull=True
        ).exclude(delegator_id__in=sys_admins)
    )
    by_delegator: dict[int, list] = {}
    for row in assignments([d.delegator_id for d in delegations]):
        by_delegator.setdefault(row[0], []).append(row)

    q = NOTHING
    for d in delegations:
        scope = task_scope(by_delegator.get(d.delegator_id, []))
        if d.org_unit_id is not None:
            scope &= Q(org_unit_id=d.org_unit_id)
        if d.subject_kinds:
            scope &= Q(instance__policy__subject_kind__in=d.subject_kinds)
        if d.max_amount_vnd is not None:
            scope &= Q(**{f"{AMOUNT}__lte": d.max_amount_vnd})
        q |= scope
    return q


def tasks_for(user):
    """Queryset các bước `PENDING` mà `user` được xử lý (trực tiếp hoặc duyệt thay)."""
    base = WorkflowTask.objects.filter(status=PENDING, instance__status=RUNNING).annotate(
        **{
            AMOUNT: Cast(
                KeyTextTransform("amount_vnd", KeyTextTransform("context", "instance__snapshot")),
                DecimalField(max_digits=18, decimal_places=0),
            )
        }
    )
    if not user.is_authenticated or not user.is_active:
        return base.none()
    sys_admins = set(resolver.sys_admin_ids())
    if user.pk in sys_admins:
        return base.none()  # quản trị hệ thống không duyệt nghiệp vụ

    scope = task_scope(assignments([user.pk])) | _delegated_scope(user, sys_admins)
    barred = (
        Q(instance__submitted_by_id=user.pk)
        | Q(instance__snapshot__context__created_by_id=user.pk)
        | Q(instance__snapshot__context__requester_id=user.pk)
        | Q(instance__snapshot__context__extra_barred_ids__contains=[user.pk])
    )
    return base.filter(scope).exclude(barred).distinct()
