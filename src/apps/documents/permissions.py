from django.db.models import Q

from apps.accounts.roles import AUDITOR, FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role

COMPANY_WIDE_ROLES = (FAD_PRECHECK, FAD_BUDGET_ADMIN, AUDITOR)


def can_view_object(user, obj) -> bool:
    """FAD và Kiểm toán xem toàn công ty; còn lại do `obj.visible_to(user)` quyết định (mặc định từ chối)."""
    if obj is None or not user.is_authenticated:
        return False
    if any(has_role(user, r) for r in COMPANY_WIDE_ROLES):
        return True
    visible_to = getattr(obj, "visible_to", None)
    if visible_to is None:
        return False
    return bool(visible_to(user))


def _is_delegation_party(user, doc) -> bool:
    """Văn bản uỷ quyền: cả người uỷ quyền và người nhận đều được xem bản đã đính kèm."""
    from apps.workflow.models import Delegation

    return Delegation.objects.filter(
        Q(delegator_id=user.pk) | Q(delegate_id=user.pk), letter_id=doc.pk
    ).exists()


def can_view_document(user, doc) -> bool:
    """Quyền xem một chứng từ: theo hồ sơ nó gắn vào, hoặc theo vai trò riêng của chứng từ đó."""
    if not user.is_authenticated:
        return False
    return can_view_object(user, doc.attached_to) or _is_delegation_party(user, doc)
