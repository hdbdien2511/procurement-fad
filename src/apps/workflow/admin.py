"""Quản trị chính sách duyệt tại `/quan-tri/` (chỉ `SYS_ADMIN`).

Chính sách đã được dùng là bất biến (xem `models`): ở đây chỉ cho **tạo phiên bản mới**
(`clone_as_new_version`) và **ngừng / bật lại** (`policies.set_policy_active`). Mọi `PermissionError`
của model hiện ra dưới dạng thông báo, không phải lỗi 500.
"""

from functools import update_wrapper

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.utils import timezone

from apps.accounts.decorators import FORBIDDEN
from apps.accounts.roles import SYS_ADMIN, has_role

from .models import IN_USE_MESSAGE, ApprovalPolicy, PolicyRule, RuleStep
from .policies import set_policy_active


class PolicyAdminSite(AdminSite):
    """Khu quản trị kỹ thuật: vào được khi giữ `SYS_ADMIN` (không dựa vào `is_staff`)."""

    site_header = "Quản trị hệ thống mua sắm"
    site_title = "Quản trị mua sắm"
    index_title = "Chính sách duyệt và tham số kỹ thuật"
    final_catch_all_view = False

    def has_permission(self, request):
        user = request.user
        return user.is_authenticated and user.is_active and has_role(user, SYS_ADMIN)

    def admin_view(self, view, cacheable=False):
        inner = super().admin_view(view, cacheable)

        def wrapper(request, *args, **kwargs):
            if not self.has_permission(request):
                if not request.user.is_authenticated:
                    return redirect_to_login(request.get_full_path(), str(settings.LOGIN_URL))
                return HttpResponseForbidden(f"{FORBIDDEN} Cần vai trò: Quản trị hệ thống.")
            return inner(request, *args, **kwargs)

        return update_wrapper(wrapper, view)


site = PolicyAdminSite(name="quantri")


class _NoDelete(admin.ModelAdmin):
    """Chỉ đọc + thao tác có kiểm soát: không xoá, không thêm trực tiếp."""

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def message_user_error(self, request, exc):
        messages.error(request, str(exc) or IN_USE_MESSAGE)

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except PermissionError as exc:
            self.message_user_error(request, exc)


@admin.register(ApprovalPolicy, site=site)
class ApprovalPolicyAdmin(_NoDelete):
    list_display = ("code", "subject_kind", "version", "effective_from", "is_active")
    list_filter = ("subject_kind", "is_active")
    search_fields = ("code",)
    ordering = ("code", "-version")
    actions = ("clone_new_version", "activate", "deactivate")

    @admin.action(description="Tạo phiên bản mới (hiệu lực từ hôm nay)")
    def clone_new_version(self, request, queryset):
        for policy in queryset.order_by("pk"):
            try:
                clone = policy.clone_as_new_version(timezone.localdate())
            except PermissionError as exc:
                self.message_user_error(request, exc)
            else:
                messages.success(request, f"Đã tạo {clone} từ {policy}.")

    @admin.action(description="Bật lại phiên bản")
    def activate(self, request, queryset):
        self._set_active(request, queryset, True)

    @admin.action(description="Ngừng sử dụng phiên bản")
    def deactivate(self, request, queryset):
        self._set_active(request, queryset, False)

    def _set_active(self, request, queryset, active: bool):
        for policy in queryset.order_by("pk"):
            try:
                set_policy_active(policy, active, request.user)
            except (ValueError, PermissionError) as exc:
                self.message_user_error(request, exc)
            else:
                messages.success(request, f"{policy}: {'đang dùng' if active else 'đã ngừng'}.")


@admin.register(PolicyRule, site=site)
class PolicyRuleAdmin(_NoDelete):
    list_display = ("policy", "priority", "label", "max_amount", "cumulative_cap", "cumulative_cap_pct")
    list_filter = ("policy__subject_kind", "policy__is_active")
    ordering = ("policy", "priority")


@admin.register(RuleStep, site=site)
class RuleStepAdmin(_NoDelete):
    list_display = ("rule", "seq", "kind", "role_code", "scope", "mandatory", "sla_hours", "requires_doc_type")
    list_filter = ("kind", "scope", "mandatory")
    ordering = ("rule", "seq")
