"""Cảnh báo dấu hiệu chia nhỏ tờ trình để lọt hạn mức duyệt.

Các tờ trình "liên quan" với tờ trình đang xét: cùng đơn vị đề nghị, cùng nhà cung cấp HOẶC có chung
mã chi phí (L8) trong phân bổ ngân sách, tạo trong vòng `split_window_days` ngày (trước hoặc sau),
đang duyệt / đã duyệt / chờ giữ chỗ ngân sách, và không phải phiên bản khác của chính tờ trình này.
Nếu tổng (kể cả tờ trình này) vượt `max_amount` của quy tắc mà tờ trình này khớp trong chính sách
duyệt hiện hành → một cảnh báo nêu số các tờ trình liên quan. Quy tắc không có hạn mức → không cảnh
báo. Tờ trình nháp dùng tổng tính thử theo tỷ giá hôm nay.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.fx import MissingRate
from apps.core.money import format_vnd
from apps.core.services import get_setting

from .engine import active_policy, select_rule
from .exceptions import NoMatchingRule, NoPolicy
from .models import REQUISITION

ACTIVE_STATUSES = ("IN_APPROVAL", "APPROVED", "BUDGET_BLOCKED")


def split_warnings(req) -> list[str]:
    from apps.requisitions.models import Requisition

    amount = Decimal(req.total_vnd)
    if req.status == "DRAFT":  # chưa nộp: tính thử theo tỷ giá hôm nay
        try:
            _, amount, _ = req.compute_totals(timezone.localdate())
        except MissingRate:
            pass
    try:
        rule = select_rule(active_policy(REQUISITION), {"amount_vnd": amount}, None)
    except (NoPolicy, NoMatchingRule):
        return []
    if rule.max_amount is None:
        return []

    window = timedelta(days=int(get_setting("split_window_days")))
    cost_codes = list(req.fundings.values_list("budget_line__cost_code_id", flat=True))
    match = Q(fundings__budget_line__cost_code_id__in=cost_codes) if cost_codes else Q(pk__in=[])
    if req.vendor_id is not None:
        match |= Q(vendor_id=req.vendor_id)
    related = (
        Requisition.objects.filter(
            match,
            requester_unit_id=req.requester_unit_id,
            status__in=ACTIVE_STATUSES,
            created_at__gte=req.created_at - window,
            created_at__lte=req.created_at + window,
        )
        .exclude(pk=req.pk)
        .distinct()
    )
    if req.number:
        related = related.exclude(number=req.number)
    rows = list(Requisition.objects.filter(pk__in=related.values("pk")).order_by("created_at", "pk"))
    if not rows:
        return []
    total = amount + sum((r.total_vnd for r in rows), Decimal(0))
    if total <= rule.max_amount:
        return []
    numbers = ", ".join(str(r) for r in rows)
    return [
        f"Có dấu hiệu chia nhỏ tờ trình: tổng giá trị cùng đơn vị, cùng nhà cung cấp hoặc mã chi phí trong "
        f"{window.days} ngày là {format_vnd(total)} đ, vượt hạn mức {format_vnd(rule.max_amount)} đ của "
        f"quy tắc \"{rule.label}\". Các tờ trình liên quan: {numbers}."
    ]
