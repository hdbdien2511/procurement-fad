"""Thông báo/email của luồng duyệt: khi mở bước, khi hồ sơ kết thúc; dùng chung cho engine và sla.

Chỉ INSERT (Notification + Outbox) — người gọi đặt trước các bản audit cuối transaction.
"""

from django.utils import timezone

from apps.notifications.outbox import notify

from . import delegation, resolver
from .models import INSTANCE_STATUSES


def task_url(task) -> str:
    return f"/viec/{task.pk}/"  # trang xử lý việc (giao diện làm ở task sau)


def format_due(due_at) -> str:
    return timezone.localtime(due_at).strftime("%d/%m/%Y %H:%M") if due_at else ""


def task_recipients(task) -> list:
    """Người xử lý trực tiếp + người nhận uỷ quyền hợp lệ của họ, tính tại thời điểm gọi."""
    users = list(resolver.candidates(task).order_by("pk"))
    seen = {u.pk for u in users}
    users += [u for u in delegation.delegates_for(task).order_by("pk") if u.pk not in seen]
    return users


def notify_opened(task, subject) -> None:
    ho_so = str(subject)
    if task.mandatory:
        template, title = "OFFICIAL", f"Hồ sơ {ho_so} cần duyệt"
    else:
        template, title = "CONSULT", f"Xin ý kiến về hồ sơ {ho_so}"
    for user in task_recipients(task):
        notify(user, title, task_url(task), email_template=template,
               context={"ho_so": ho_so, "han_xu_ly": format_due(task.due_at)})


def notify_result(instance, subject) -> None:
    ho_so, ket_qua = str(subject), dict(INSTANCE_STATUSES)[instance.status]
    url = subject.get_absolute_url() if hasattr(subject, "get_absolute_url") else "/"
    notify(instance.submitted_by, f"Hồ sơ {ho_so}: {ket_qua}", url, email_template="RESULT",
           context={"ho_so": ho_so, "ket_qua": ket_qua})
