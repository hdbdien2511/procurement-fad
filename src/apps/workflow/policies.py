"""Dịch vụ quản trị chính sách duyệt: ngừng/bật lại một phiên bản (có audit).

Đây là thay đổi duy nhất được phép trên chính sách đã sử dụng (xem `models.ApprovalPolicy.save`).
"""

from django.db import transaction

from apps.audit import service as audit

from .models import ApprovalPolicy

ANOTHER_ACTIVE_MESSAGE = "Mã chính sách đã có phiên bản khác đang dùng; hãy ngừng phiên bản đó trước"


@transaction.atomic
def set_policy_active(policy: ApprovalPolicy, active: bool, user) -> ApprovalPolicy:
    """Ngừng (`active=False`) hoặc bật lại một phiên bản chính sách; không đổi gì thì không ghi audit.

    Bật lại bị từ chối (`ValueError`) nếu một phiên bản khác cùng mã đang dùng.
    """
    # khoá mọi phiên bản cùng mã (thứ tự pk) để hai lần bật đồng thời không cùng lọt qua kiểm tra
    versions = {p.pk: p for p in ApprovalPolicy.objects.select_for_update().filter(code=policy.code).order_by("pk")}
    locked = versions[policy.pk]
    if locked.is_active == active:
        policy.is_active = active
        return policy
    if active and any(p.is_active for pk, p in versions.items() if pk != locked.pk):
        raise ValueError(ANOTHER_ACTIVE_MESSAGE)
    locked.is_active = active
    locked.save(update_fields=["is_active"])
    policy.is_active = active
    audit.record("policy.activated" if active else "policy.deactivated", locked, actor=user,
                 changes={"code": locked.code, "version": locked.version, "is_active": [not active, active]})
    return policy
