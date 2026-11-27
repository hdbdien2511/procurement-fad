from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import SYS_ADMIN, has_role
from apps.audit.service import diff, record

from . import mailer
from .forms import EmailSettingsForm
from .models import EmailSettings

FORBIDDEN = "Chỉ quản trị hệ thống mới được cấu hình email."
FIELDS = EmailSettingsForm.Meta.fields


def _snapshot(cfg: EmailSettings) -> dict:
    return {f: getattr(cfg, f) for f in FIELDS}


@login_required
def email_settings(request):
    if not has_role(request.user, SYS_ADMIN):
        return HttpResponseForbidden(FORBIDDEN)
    cfg = EmailSettings.load()
    if request.method == "POST":
        form = EmailSettingsForm(request.POST, instance=cfg)
        if form.is_valid():
            with transaction.atomic():
                cfg = EmailSettings.objects.select_for_update().get(pk=1)
                before = _snapshot(cfg)
                form = EmailSettingsForm(request.POST, instance=cfg)
                form.is_valid()
                cfg = form.save(commit=False)
                new_password = form.cleaned_data["password"]
                if new_password:
                    cfg.set_password(new_password)
                cfg.save()
                changes = diff(before, _snapshot(cfg))
                if new_password:
                    changes["password"] = ["***", "***"]  # không bao giờ ghi giá trị thật
                record("settings.email_changed", cfg, actor=request.user, changes=changes)
            messages.success(request, "Đã lưu cấu hình email.")
            return redirect("email_settings")
    else:
        form = EmailSettingsForm(instance=cfg)
    return render(request, "notifications/email_settings.html", {"form": form, "has_password": bool(cfg.password_encrypted)})


@login_required
@require_POST
def email_send_test(request):
    if not has_role(request.user, SYS_ADMIN):
        return HttpResponseForbidden(FORBIDDEN)
    to = request.user.email
    if not to:
        messages.error(request, "Gửi thử không thành công: tài khoản của bạn chưa có địa chỉ email.")
        return redirect("email_settings")
    try:
        mailer.send_now([to], "[Mua sắm] Email thử nghiệm", "Đây là email thử nghiệm từ hệ thống mua sắm.")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, "Gửi thử không thành công: " + mailer.scrub(f"{type(exc).__name__}: {exc}"))
    else:
        messages.success(request, f"Đã gửi email thử tới {to}.")
    return redirect("email_settings")
