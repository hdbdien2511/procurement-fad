"""Uỷ quyền duyệt thay (spec 7.2).

Người nhận uỷ quyền (`delegate`) chỉ được xử lý một bước khi, TẠI THỜI ĐIỂM XỬ LÝ:

- người uỷ quyền là người xử lý TRỰC TIẾP của bước (`resolver.candidates`: đúng vai trò + phạm vi,
  không phải người nộp/tạo hồ sơ, không giữ `SYS_ADMIN`) → không uỷ quyền vượt thẩm quyền và không
  bắc cầu (uỷ quyền mà người nhận đã nhận không làm họ thành người uỷ quyền);
- uỷ quyền còn hiệu lực hôm nay (`start_date ≤ hôm nay ≤ end_date`, chưa thu hồi);
- loại hồ sơ thuộc `subject_kinds` (rỗng = mọi loại), `org_unit` null hoặc đúng đơn vị của bước,
  số tiền hồ sơ ≤ `max_amount_vnd` (null = không giới hạn);
- bản thân người nhận không phải người nộp/tạo hồ sơ, không giữ `SYS_ADMIN` và đang hoạt động.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import service as audit

from . import resolver
from .models import Delegation


def active_delegations_for(user, on: date):
    """Uỷ quyền `user` đang nhận, còn hiệu lực tại ngày `on`."""
    return Delegation.objects.filter(
        delegate=user, start_date__lte=on, end_date__gte=on, revoked_at__isnull=True
    )


def _valid_for_task(delegations, task):
    """Lọc các uỷ quyền áp dụng được cho `task` (người uỷ quyền phải là người xử lý trực tiếp)."""
    instance = task.instance
    amount = Decimal(instance.snapshot["context"]["amount_vnd"])
    kind = instance.policy.subject_kind
    return delegations.filter(
        Q(org_unit__isnull=True) | Q(org_unit_id=task.org_unit_id),
        Q(max_amount_vnd__isnull=True) | Q(max_amount_vnd__gte=amount),
        Q(subject_kinds=[]) | Q(subject_kinds__contains=[kind]),
        delegator__in=resolver.candidates(task),
    )


def _barred(task):
    return resolver.barred_user_ids(task.instance) | set(resolver.sys_admin_ids())


def find_delegation(delegate, task, delegator=None) -> Delegation | None:
    """Uỷ quyền hợp lệ cho `delegate` xử lý `task` (người uỷ quyền có pk nhỏ nhất nếu có nhiều)."""
    if not delegate.is_active or delegate.pk in _barred(task):
        return None
    qs = _valid_for_task(active_delegations_for(delegate, timezone.localdate()), task)
    if delegator is not None:
        qs = qs.filter(delegator=delegator)
    return qs.select_related("delegator").order_by("delegator_id", "pk").first()


def can_act_on_behalf(delegate, task) -> User | None:
    """Người uỷ quyền mà `delegate` được xử lý thay ở `task`, hoặc None nếu không có uỷ quyền hợp lệ."""
    found = find_delegation(delegate, task)
    return found.delegator if found else None


def delegates_for(task):
    """Người nhận uỷ quyền hợp lệ của các người xử lý trực tiếp `task` (để gửi thông báo)."""
    today = timezone.localdate()
    active = Delegation.objects.filter(start_date__lte=today, end_date__gte=today, revoked_at__isnull=True)
    ids = _valid_for_task(active, task).values("delegate_id")
    return User.objects.filter(pk__in=ids, is_active=True).exclude(pk__in=_barred(task))


@transaction.atomic
def create_delegation(delegator, delegate, *, start_date: date, end_date: date, max_amount_vnd=None,
                      subject_kinds=(), org_unit=None, letter=None, actor=None) -> Delegation:
    """Kiểm tra (`full_clean`), lưu và ghi audit `delegation.created`.

    Phân quyền ai được tạo (chính người uỷ quyền hay quản trị theo văn bản) do tầng giao diện kiểm tra.
    """
    d = Delegation(
        delegator=delegator, delegate=delegate, start_date=start_date, end_date=end_date,
        max_amount_vnd=max_amount_vnd, subject_kinds=list(subject_kinds), org_unit=org_unit, letter=letter,
    )
    d.full_clean()
    d.save()
    audit.record("delegation.created", d, actor=actor or delegator, changes={
        "delegator": delegator.get_username(),
        "delegate": delegate.get_username(),
        "start_date": start_date,
        "end_date": end_date,
        "max_amount_vnd": max_amount_vnd,
        "subject_kinds": d.subject_kinds,
        "org_unit": org_unit.code if org_unit else None,
        "letter": str(letter.pk) if letter else None,
    })
    return d
