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
