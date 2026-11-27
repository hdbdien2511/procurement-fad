"""Màn hình cài đặt hệ thống (`SYS_ADMIN`): email, tỷ giá, bốn tham số nghiệp vụ."""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.roles import SYS_ADMIN
from apps.ui.feedback import domain_errors

from .models import ExchangeRate
from .services import DEFAULTS, get_setting, set_setting

# (khoá, nhãn, kiểu, lựa chọn)
PARAMS = [
    ("split_window_days", "Cửa sổ xét chia nhỏ tờ trình (ngày)", "int", None),
    ("annual_fixed_cost_vnd", "Chi phí cố định năm (VND)", "int", None),
    ("cumulative_scope", "Phạm vi luỹ kế ngoài ngân sách", "choice", [("COMPANY", "Toàn công ty"),
                                                                      ("UNIT", "Theo đơn vị ngân sách")]),
    ("max_upload_mb", "Dung lượng tệp tải lên tối đa (MB)", "int", None),
]
PARAM_KEYS = {key for key, _, _, _ in PARAMS}


@login_required
@role_required(SYS_ADMIN)
def settings_page(request):
    return render(request, "core/settings.html", {
        "heading": "Cài đặt hệ thống",
        "params": [
            {"key": key, "label": label, "kind": kind, "options": options, "value": get_setting(key)}
            for key, label, kind, options in PARAMS
        ],
        "rates": ExchangeRate.objects.order_by("-date", "currency")[:200],
        "today": timezone.localdate(),
    })


@login_required
@role_required(SYS_ADMIN)
@require_POST
def settings_params(request):
    """Lưu các tham số được gửi lên (mỗi tham số một bản audit qua `set_setting`)."""
    with domain_errors(request, success="Đã lưu tham số hệ thống."):
        for key, _label, kind, options in PARAMS:
            if key not in request.POST:
                continue
            raw = (request.POST.get(key) or "").strip()
            set_setting(key, _parse(key, raw, kind, options), request.user)
    return redirect("settings_page")


def _parse(key, raw: str, kind: str, options):
    if raw == "":
        return DEFAULTS[key]
    if kind == "int":
        if not raw.lstrip("-").isdigit():
            raise ValueError(f"Giá trị của “{key}” phải là số nguyên.")
        return int(raw)
    if kind == "choice" and raw not in {value for value, _ in options}:
        raise ValueError(f"Giá trị của “{key}” không hợp lệ.")
    return raw


@login_required
@role_required(SYS_ADMIN)
@require_POST
def settings_rate_add(request):
    """Thêm / cập nhật tỷ giá của một ngoại tệ tại một ngày."""
    with domain_errors(request, success="Đã lưu tỷ giá."):
        currency = (request.POST.get("currency") or "").strip().upper()
        on = parse_date(request.POST.get("date") or "")
        rate = _rate(request.POST.get("rate"))
        if not isinstance(on, date):
            raise ValueError("Ngày hiệu lực không hợp lệ.")
        row = ExchangeRate(currency=currency, date=on, rate=rate)
        row.full_clean(exclude=["id"], validate_unique=False)
        ExchangeRate.objects.update_or_create(
            currency=row.currency, date=on, defaults={"rate": rate}
        )
    return redirect("settings_page")


def _rate(raw) -> Decimal:
    try:
        return Decimal((raw or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Tỷ giá không hợp lệ.") from exc
