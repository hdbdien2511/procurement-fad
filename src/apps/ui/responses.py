"""Phản hồi tệp xlsx cho các liên kết "xuất" của bảng dữ liệu."""

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect

from .export import ExportTooLarge, to_xlsx

CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_response(request, spec, qs, filename: str, *, back: str):
    """Xuất đúng tập đang xem; quá lớn thì về `back` kèm thông báo thu hẹp bộ lọc."""
    try:
        data = to_xlsx(spec, qs)
    except ExportTooLarge as exc:
        messages.error(request, str(exc))
        return redirect(back)
    response = HttpResponse(data, content_type=CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
