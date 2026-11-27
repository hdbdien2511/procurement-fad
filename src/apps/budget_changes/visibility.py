"""Quyền xem đề nghị bổ sung/điều chuyển ngân sách: cùng quy tắc với tờ trình (`apps.requisitions.visibility`).

Người xem được:
- người tạo / người đề nghị; thành viên đơn vị đề nghị;
- người giữ `BUDGET_OWNER` của đơn vị quản lý đơn vị ngân sách của dòng nhận hoặc dòng nguồn (hoặc toàn
  công ty);
- người đã xử lý (hoặc xử lý thay) một bước; người đúng vai trò + phạm vi của một bước (trừ
  `SYS_ADMIN`); người nhận uỷ quyền còn hiệu lực cho bước đang chờ (phạm vi uỷ quyền: đơn vị, loại
  hồ sơ, hạn mức);
- FAD tiền kiểm, FAD quản trị ngân sách, Kiểm toán: toàn bộ.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import BigIntegerField, Q
from django.db.models.functions import Cast
from django.utils import timezone

from apps.accounts.roles import BUDGET_OWNER, has_role
from apps.requisitions.visibility import COMPANY_WIDE_ROLES, NOTHING, _assignments, _task_scope
from apps.workflow import resolver
from apps.workflow.models import BUDGET_CHANGE, PENDING, Delegation, WorkflowTask


def _request_ids(task_filter: Q):
    from .models import BudgetChangeRequest

    tasks = WorkflowTask.objects.filter(
        task_filter, instance__content_type=ContentType.objects.get_for_model(BudgetChangeRequest)
    )
    return tasks.annotate(rid=Cast("instance__object_id", BigIntegerField())).values("rid")


def visibility_filter(user) -> Q | None:
    """Điều kiện lọc đề nghị `user` xem được; None = xem tất cả."""
    if not user.is_authenticated or not user.is_active:
        return NOTHING
    if any(has_role(user, role) for role in COMPANY_WIDE_ROLES):
        return None

    q = Q(created_by_id=user.pk) | Q(requester_id=user.pk)
    if user.org_unit_id is not None:
        q |= Q(requester_unit_id=user.org_unit_id)

    own = _assignments([user.pk])
    owner_units = [unit for _, role, unit in own if role == BUDGET_OWNER]
    if None in owner_units:
        return None  # BUDGET_OWNER toàn công ty: mọi đề nghị đều có dòng ngân sách
    if owner_units:
        q |= Q(to_line__budget_unit__managing_org_unit_id__in=owner_units)
        q |= Q(from_line__budget_unit__managing_org_unit_id__in=owner_units)

    q |= Q(pk__in=_request_ids(Q(acted_by_id=user.pk) | Q(on_behalf_of_id=user.pk)))

    sys_admins = set(resolver.sys_admin_ids())
    if user.pk not in sys_admins and own:
        q |= Q(pk__in=_request_ids(_task_scope(own)))

    if user.pk not in sys_admins:
        today = timezone.localdate()
        delegations = Delegation.objects.filter(
            delegate_id=user.pk, start_date__lte=today, end_date__gte=today, revoked_at__isnull=True
        ).exclude(delegator_id__in=sys_admins)
        delegations = [d for d in delegations if not d.subject_kinds or BUDGET_CHANGE in d.subject_kinds]
        by_delegator = {}
        for user_id, role, unit in _assignments([d.delegator_id for d in delegations]):
            by_delegator.setdefault(user_id, []).append((user_id, role, unit))
        for d in delegations:
            scope = _task_scope(by_delegator.get(d.delegator_id, []))
            if d.org_unit_id is not None:
                scope &= Q(org_unit_id=d.org_unit_id)
            dq = Q(pk__in=_request_ids(scope & Q(status=PENDING)))
            if d.max_amount_vnd is not None:
                dq &= Q(amount_vnd__lte=d.max_amount_vnd)
            q |= dq
    return q
