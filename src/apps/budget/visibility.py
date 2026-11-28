"""Quyền xem dòng ngân sách: FAD và Kiểm toán xem tất cả, đơn vị quản lý xem phần của mình.

Phần của một người: dòng thuộc đơn vị ngân sách do đơn vị tổ chức của họ quản lý, hoặc do đơn vị
mà họ được phân công `BUDGET_OWNER` quản lý (phân công toàn công ty = xem tất cả).
"""

from django.db.models import Q

from apps.accounts.roles import AUDITOR, BUDGET_OWNER, FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role
from apps.workflow.visibility import NOTHING, assignments

COMPANY_WIDE_ROLES = (FAD_PRECHECK, FAD_BUDGET_ADMIN, AUDITOR)


def visibility_filter(user) -> Q | None:
    """Điều kiện lọc `BudgetLine` mà `user` xem được; None = xem tất cả."""
    if not user.is_authenticated or not user.is_active:
        return NOTHING
    if any(has_role(user, role) for role in COMPANY_WIDE_ROLES):
        return None
    owner_units = [unit for _, role, unit in assignments([user.pk]) if role == BUDGET_OWNER]
    if None in owner_units:
        return None
    q = NOTHING
    if user.org_unit_id is not None:
        q |= Q(budget_unit__managing_org_unit_id=user.org_unit_id)
    if owner_units:
        q |= Q(budget_unit__managing_org_unit_id__in=owner_units)
    return q


def visible_lines(user):
    from .models import BudgetLine

    q = visibility_filter(user)
    qs = BudgetLine.objects.all()
    return qs if q is None else qs.filter(q)
