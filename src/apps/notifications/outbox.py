"""Hộp thư đi (outbox): ghi trong transaction nghiệp vụ, worker gửi sau khi commit."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import mailer
from .models import Notification, Outbox

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BATCH_SIZE = 50
MAX_ERROR_LEN = 1000


def enqueue_email(to: list[str], template_code: str, context: dict) -> Outbox:
    """Chỉ chèn một dòng; gọi BÊN TRONG transaction nghiệp vụ để thư chỉ đi khi nghiệp vụ commit."""
    return Outbox.objects.create(
        kind="EMAIL",
        payload={"to": list(to), "template_code": template_code, "context": context},
    )


def notify(user, title, url, *, email_template: str | None = None, context: dict | None = None) -> None:
    Notification.objects.create(user=user, title=title, url=url)
    if not email_template:
        return
    if not user.email:
        logger.debug("Bỏ qua email cho %s: chưa có địa chỉ email", user.get_username())
        return
    ctx = {"nguoi_nhan": user.get_full_name() or user.get_username(), "duong_dan": url, **(context or {})}
    enqueue_email([user.email], email_template, ctx)


def mark_read(notification: Notification, user) -> None:
    if notification.user_id != user.pk:
        raise PermissionError("Không phải thông báo của bạn.")
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])


def _send(ob: Outbox) -> None:
    p = ob.payload
    subject, body = mailer.render(p["template_code"], p.get("context", {}))
    mailer.send_now(p["to"], subject, body)


def process_due(now) -> int:
    """Gửi các thư đến hạn; trả về số thư đã gửi. Hai worker không bao giờ gửi trùng một thư."""
    sent = 0
    with transaction.atomic():
        due = (
            Outbox.objects.select_for_update(skip_locked=True)
            .filter(kind="EMAIL", status=Outbox.Status.PENDING, next_attempt_at__lte=now)
            .order_by("next_attempt_at", "id")[:BATCH_SIZE]
        )
        for ob in due:
            try:
                _send(ob)
            except Exception as exc:  # noqa: BLE001 - mọi lỗi gửi đều tính là một lần thử
                ob.attempts += 1
                ob.last_error = mailer.scrub(f"{type(exc).__name__}: {exc}")[:MAX_ERROR_LEN]
                if ob.attempts >= MAX_ATTEMPTS:
                    ob.status = Outbox.Status.FAILED
                else:
                    ob.next_attempt_at = now + timedelta(minutes=2**ob.attempts)
                logger.warning("Gửi email outbox #%s lỗi (lần %s): %s", ob.pk, ob.attempts, ob.last_error)
            else:
                ob.status = Outbox.Status.SENT
                ob.sent_at = now
                ob.last_error = ""
                sent += 1
            ob.save()
    return sent
