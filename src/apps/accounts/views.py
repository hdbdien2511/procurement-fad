from django import forms
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django_otp import devices_for_user, login as otp_login

from apps.audit.service import record


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = False

    def get_success_url(self):
        # sau mật khẩu luôn qua bước OTP (OTP view tự chuyển hướng nếu đã xác thực/OIDC)
        return f"{reverse('otp_verify')}?{urlencode({'next': super().get_success_url()})}"

    def get_context_data(self, **kwargs):
        from django.conf import settings

        ctx = super().get_context_data(**kwargs)
        ctx["oidc_enabled"] = getattr(settings, "OIDC_ENABLED", False)
        return ctx


class OtpForm(forms.Form):
    token = forms.CharField(label="Mã xác thực (6 chữ số)", max_length=8, strip=True)


@login_required
def otp_verify(request):
    nxt = request.GET.get("next") or request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/"
    if request.user.is_verified():
        return redirect(nxt)
    devices = list(devices_for_user(request.user, confirmed=True))
    if not devices:
        return redirect("otp_required")
    form = OtpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for device in devices:
            if device.verify_token(form.cleaned_data["token"]):
                otp_login(request, device)
                record("auth.otp_verified", request.user)
                return redirect(nxt)
        record("auth.otp_failed", request.user)
        form.add_error("token", "Mã xác thực không đúng.")
    return render(request, "accounts/otp.html", {"form": form, "next": nxt})


@login_required
def otp_required(request):
    return render(request, "accounts/otp_required.html")
