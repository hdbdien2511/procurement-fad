"""Quyền xem tờ trình: một bộ lọc truy vấn duy nhất, dùng cho danh sách và cho từng tờ trình.

Quy tắc chung (người tạo/đề nghị, đơn vị đề nghị, người xử lý, uỷ quyền, FAD/Kiểm toán) nằm ở
`apps.workflow.visibility`; ở đây chỉ khai báo phần riêng của tờ trình: `BUDGET_OWNER` của đơn vị quản
lý một đơn vị ngân sách được phân bổ (hoặc toàn công ty) xem được, thành viên khác của đơn vị quản lý
thì không (spec 7.3).
"""

from django.db.models import Q

from apps.workflow.models import REQUISITION
from apps.workflow.visibility import subject_visibility_filter


def _budget_owner_q(owner_units) -> Q | None:
    if None in owner_units:
        return Q(fundings__isnull=False)
    return Q(fundings__budget_line__budget_unit__managing_org_unit_id__in=owner_units) if owner_units else None


def visibility_filter(user) -> Q | None:
    """Điều kiện lọc tờ trình `user` xem được; None = xem tất cả."""
    from .models import Requisition

    return subject_visibility_filter(
        user, model=Requisition, subject_kind=REQUISITION, amount_field="total_vnd",
        budget_owner_q=_budget_owner_q,
    )
