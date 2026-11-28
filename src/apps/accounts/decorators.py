"""Chặn truy cập theo vai trò cho tầng giao diện (service vẫn tự kiểm tra quyền của mình)."""

from functools import wraps

from django.http import HttpResponseForbidden

from .roles import ROLE_NAMES, has_role

FORBIDDEN = "Bạn không có quyền truy cập chức năng này."


def role_required(*codes):
    """Chỉ cho qua khi người dùng giữ ít nhất một trong các vai trò `codes` (dùng sau `login_required`)."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not any(has_role(request.user, code) for code in codes):
                names = ", ".join(ROLE_NAMES.get(code, code) for code in codes)
                return HttpResponseForbidden(f"{FORBIDDEN} Cần vai trò: {names}.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
