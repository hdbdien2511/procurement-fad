"""Quyền xem đề nghị bổ sung/điều chuyển ngân sách.

Quy tắc chung giống tờ trình và nằm ở `apps.workflow.visibility`; ở đây chỉ khai báo phần riêng:
`BUDGET_OWNER` của đơn vị quản lý đơn vị ngân sách của dòng nhận hoặc dòng nguồn (hoặc toàn công ty)
xem được.
"""

from django.db.models import Q

from apps.workflow.models import BUDGET_CHANGE
from apps.workflow.visibility import ALL, subject_visibility_filter


def _budget_owner_q(owner_units) -> Q | None:
    if None in owner_units:
        return ALL  # phân công toàn công ty: mọi đề nghị đều gắn với dòng ngân sách
    if not owner_units:
        return None
    return (
        Q(to_line__budget_unit__managing_org_unit_id__in=owner_units)
        | Q(from_line__budget_unit__managing_org_unit_id__in=owner_units)
    )


def visibility_filter(user) -> Q | None:
    """Điều kiện lọc đề nghị `user` xem được; None = xem tất cả."""
    from .models import BudgetChangeRequest

    return subject_visibility_filter(
        user, model=BudgetChangeRequest, subject_kind=BUDGET_CHANGE, amount_field="amount_vnd",
        budget_owner_q=_budget_owner_q,
    )
