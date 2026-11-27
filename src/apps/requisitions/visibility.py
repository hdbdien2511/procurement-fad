"""Quyền xem tờ trình: một bộ lọc truy vấn duy nhất, dùng cho danh sách và cho từng tờ trình.

Người xem được:
- người tạo / người đề nghị; thành viên đơn vị đề nghị;
- người giữ `BUDGET_OWNER` của đơn vị quản lý một đơn vị ngân sách được phân bổ (hoặc toàn công ty) —
  thành viên khác của đơn vị quản lý không xem được (spec 7.3);
- người đã xử lý (hoặc xử lý thay) một bước; người đúng vai trò + phạm vi của một bước (trừ
  `SYS_ADMIN`); người nhận uỷ quyền còn hiệu lực của người đó cho bước đang chờ (phạm vi uỷ quyền:
  đơn vị, loại hồ sơ, hạn mức);
- FAD tiền kiểm, FAD quản trị ngân sách, Kiểm toán: toàn bộ.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import BigIntegerField, Q
from django.db.models.functions import Cast
from django.utils import timezone

from apps.accounts.models import RoleAssignment
from apps.accounts.roles import AUDITOR, BUDGET_OWNER, FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role
from apps.workflow import resolver
from apps.workflow.models import PENDING, REQUISITION, Delegation, WorkflowTask

COMPANY_WIDE_ROLES = (FAD_PRECHECK, FAD_BUDGET_ADMIN, AUDITOR)
NOTHING = Q(pk__in=[])


def _assignments(user_ids) -> list[tuple[int, str, int | None]]:
    """Phân công hiệu lực hôm nay `(user_id, role_code, org_unit_id)` của các người dùng đang hoạt động."""
    today = timezone.localdate()
    return list(
        RoleAssignment.objects.filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=today),
            user_id__in=user_ids, user__is_active=True, valid_from__lte=today,
        ).values_list("user_id", "role__code", "org_unit_id")
    )


def _task_scope(assignments) -> Q:
    """Task mà một trong các phân công thoả vai trò + phạm vi (phân công toàn công ty thoả mọi đơn vị)."""
    q = NOTHING
    for _, role_code, org_unit_id in assignments:
        q |= Q(role_code=role_code) if org_unit_id is None else Q(role_code=role_code, org_unit_id=org_unit_id)
    return q


def _requisition_ids(task_filter: Q):
    tasks = WorkflowTask.objects.filter(
        task_filter, instance__content_type=ContentType.objects.get_for_model(_requisition_model())
    )
    return tasks.annotate(rid=Cast("instance__object_id", BigIntegerField())).values("rid")


def _requisition_model():
    from .models import Requisition

    return Requisition


def visibility_filter(user) -> Q | None:
    """Điều kiện lọc tờ trình `user` xem được; None = xem tất cả."""
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
        q |= Q(fundings__isnull=False)
    elif owner_units:
        q |= Q(fundings__budget_line__budget_unit__managing_org_unit_id__in=owner_units)

    q |= Q(pk__in=_requisition_ids(Q(acted_by_id=user.pk) | Q(on_behalf_of_id=user.pk)))

    sys_admins = set(resolver.sys_admin_ids())
    if user.pk not in sys_admins and own:
        q |= Q(pk__in=_requisition_ids(_task_scope(own)))

    if user.pk not in sys_admins:
        today = timezone.localdate()
        delegations = Delegation.objects.filter(
            delegate_id=user.pk, start_date__lte=today, end_date__gte=today, revoked_at__isnull=True
        ).exclude(delegator_id__in=sys_admins)
        delegations = [d for d in delegations if not d.subject_kinds or REQUISITION in d.subject_kinds]
        by_delegator = {}
        for user_id, role, unit in _assignments([d.delegator_id for d in delegations]):
            by_delegator.setdefault(user_id, []).append((user_id, role, unit))
        for d in delegations:
            scope = _task_scope(by_delegator.get(d.delegator_id, []))
            if d.org_unit_id is not None:
                scope &= Q(org_unit_id=d.org_unit_id)
            dq = Q(pk__in=_requisition_ids(scope & Q(status=PENDING)))
            if d.max_amount_vnd is not None:
                dq &= Q(total_vnd__lte=d.max_amount_vnd)
            q |= dq
    return q
