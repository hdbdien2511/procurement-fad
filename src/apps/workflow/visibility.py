"""Quyền xem hồ sơ đi qua luồng duyệt: một bộ dựng điều kiện lọc dùng chung cho mọi loại hồ sơ.

Dùng cho tờ trình mua sắm (`apps.requisitions.visibility`) và đề nghị bổ sung/điều chuyển ngân sách
(`apps.budget_changes.visibility`). Hồ sơ phải có các trường `created_by`, `requester`,
`requester_unit` và phương thức `workflow_instances()`.

Người xem được:
- người tạo / người đề nghị; thành viên đơn vị đề nghị;
- người giữ `BUDGET_OWNER` của đơn vị quản lý một đơn vị ngân sách liên quan (hoặc toàn công ty) —
  điều kiện cụ thể do từng loại hồ sơ cung cấp qua `budget_owner_q` (spec 7.3);
- người đã xử lý (hoặc xử lý thay) một bước; người đúng vai trò + phạm vi của một bước (trừ
  `SYS_ADMIN`); người nhận uỷ quyền còn hiệu lực của người đó cho bước đang chờ (phạm vi uỷ quyền:
  đơn vị, loại hồ sơ, hạn mức);
- FAD tiền kiểm, FAD quản trị ngân sách, Kiểm toán: toàn bộ.
"""

from collections.abc import Callable

from django.contrib.contenttypes.models import ContentType
from django.db.models import BigIntegerField, Q
from django.db.models.functions import Cast
from django.utils import timezone

from apps.accounts.models import RoleAssignment
from apps.accounts.roles import AUDITOR, BUDGET_OWNER, FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role

from . import resolver
from .models import PENDING, Delegation, WorkflowTask

COMPANY_WIDE_ROLES = (FAD_PRECHECK, FAD_BUDGET_ADMIN, AUDITOR)
NOTHING = Q(pk__in=[])


def assignments(user_ids) -> list[tuple[int, str, int | None]]:
    """Phân công hiệu lực hôm nay `(user_id, role_code, org_unit_id)` của các người dùng đang hoạt động."""
    today = timezone.localdate()
    return list(
        RoleAssignment.objects.filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=today),
            user_id__in=user_ids, user__is_active=True, valid_from__lte=today,
        ).values_list("user_id", "role__code", "org_unit_id")
    )


def task_scope(assignment_rows) -> Q:
    """Task mà một trong các phân công thoả vai trò + phạm vi (phân công toàn công ty thoả mọi đơn vị)."""
    q = NOTHING
    for _, role_code, org_unit_id in assignment_rows:
        q |= Q(role_code=role_code) if org_unit_id is None else Q(role_code=role_code, org_unit_id=org_unit_id)
    return q


def _subject_ids(model, task_filter: Q):
    tasks = WorkflowTask.objects.filter(
        task_filter, instance__content_type=ContentType.objects.get_for_model(model)
    )
    return tasks.annotate(rid=Cast("instance__object_id", BigIntegerField())).values("rid")


def subject_visibility_filter(
    user,
    *,
    model,
    subject_kind: str,
    amount_field: str,
    budget_owner_q: Callable[[list[int | None]], Q | None],
) -> Q | None:
    """Điều kiện lọc hồ sơ `model` mà `user` xem được; None = xem tất cả.

    - `subject_kind`: mã loại hồ sơ dùng để lọc phạm vi uỷ quyền (`Delegation.subject_kinds`);
    - `amount_field`: trường số tiền của hồ sơ, so với hạn mức uỷ quyền;
    - `budget_owner_q(owner_units)`: điều kiện cho `BUDGET_OWNER` theo các đơn vị được phân công
      (`None` trong danh sách = phân công toàn công ty), trả `None` nếu không mở thêm quyền xem nào.
    """
    if not user.is_authenticated or not user.is_active:
        return NOTHING
    if any(has_role(user, role) for role in COMPANY_WIDE_ROLES):
        return None

    q = Q(created_by_id=user.pk) | Q(requester_id=user.pk)
    if user.org_unit_id is not None:
        q |= Q(requester_unit_id=user.org_unit_id)

    own = assignments([user.pk])
    owner_q = budget_owner_q([unit for _, role, unit in own if role == BUDGET_OWNER])
    if owner_q is not None:
        q |= owner_q

    q |= Q(pk__in=_subject_ids(model, Q(acted_by_id=user.pk) | Q(on_behalf_of_id=user.pk)))

    sys_admins = set(resolver.sys_admin_ids())
    if user.pk not in sys_admins and own:
        q |= Q(pk__in=_subject_ids(model, task_scope(own)))

    if user.pk not in sys_admins:
        today = timezone.localdate()
        delegations = Delegation.objects.filter(
            delegate_id=user.pk, start_date__lte=today, end_date__gte=today, revoked_at__isnull=True
        ).exclude(delegator_id__in=sys_admins)
        delegations = [d for d in delegations if not d.subject_kinds or subject_kind in d.subject_kinds]
        by_delegator = {}
        for user_id, role, unit in assignments([d.delegator_id for d in delegations]):
            by_delegator.setdefault(user_id, []).append((user_id, role, unit))
        for d in delegations:
            scope = task_scope(by_delegator.get(d.delegator_id, []))
            if d.org_unit_id is not None:
                scope &= Q(org_unit_id=d.org_unit_id)
            dq = Q(pk__in=_subject_ids(model, scope & Q(status=PENDING)))
            if d.max_amount_vnd is not None:
                dq &= Q(**{f"{amount_field}__lte": d.max_amount_vnd})
            q |= dq
    return q
