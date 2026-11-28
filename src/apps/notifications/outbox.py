"""Hộp thư đi (outbox): ghi trong transaction nghiệp vụ, worker gửi sau khi commit."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import mailer
from .models import EmailSettings, Notification, Outbox

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BATCH_SIZE = 50


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
    link = settings.SITE_URL + url if url.startswith("/") else url
    ctx = {"nguoi_nhan": user.get_full_name() or user.get_username(), "duong_dan": link, **(context or {})}
    enqueue_email([user.email], email_template, ctx)


def mark_read(notification: Notification, user) -> None:
    if notification.user_id != user.pk:
        raise PermissionError("Không phải thông báo của bạn.")
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])


LEASE = timedelta(minutes=10)  # thời gian "giữ chỗ" khi đang gửi; worker chết giữa chừng thì thử lại sau đó
NOT_CONFIGURED_DEFER = timedelta(minutes=10)


def _send(ob: Outbox, cfg: EmailSettings) -> None:
    p = ob.payload
    subject, body = mailer.render(p["template_code"], p.get("context", {}))
    mailer.send_now(p["to"], subject, body, cfg=cfg)


def _claim(now) -> Outbox | None:
    """Giành một thư đến hạn trong transaction ngắn bằng cách "cho thuê" (đẩy next_attempt_at)."""
    with transaction.atomic():
        ob = (
            Outbox.objects.select_for_update(skip_locked=True)
            .filter(kind="EMAIL", status=Outbox.Status.PENDING, next_attempt_at__lte=now)
            .order_by("next_attempt_at", "id")
            .first()
        )
        if ob is not None:
            ob.next_attempt_at = now + LEASE
            ob.save(update_fields=["next_attempt_at"])
        return ob


def _mark_sent(ob: Outbox, now) -> None:
    with transaction.atomic():
        Outbox.objects.filter(pk=ob.pk).update(
            status=Outbox.Status.SENT, sent_at=now, last_error="", next_attempt_at=now
        )


def _mark_failed(ob: Outbox, now, error: str) -> None:
    attempts = ob.attempts + 1
    fields = {"attempts": attempts, "last_error": error}
    if attempts >= MAX_ATTEMPTS:
        fields["status"] = Outbox.Status.FAILED
    else:
        fields["next_attempt_at"] = now + timedelta(minutes=2**attempts)
    with transaction.atomic():
        Outbox.objects.filter(pk=ob.pk).update(**fields)


def _defer_all_due(now) -> None:
    Outbox.objects.filter(kind="EMAIL", status=Outbox.Status.PENDING, next_attempt_at__lte=now).update(
        next_attempt_at=now + NOT_CONFIGURED_DEFER
    )


def process_due(now) -> int:
    """Gửi các thư đến hạn, từng thư một; trả về số thư đã gửi và ghi nhận.

    Việc gửi SMTP nằm NGOÀI mọi transaction; khoảng trùng lặp tối đa một thư nếu worker chết giữa chừng.
    """
    sent = 0
    for _ in range(BATCH_SIZE):
        ob = _claim(now)
        if ob is None:
            break
        password = ""
        try:
            cfg = EmailSettings.load()
            password = cfg.get_password()  # chụp một lần: dùng cho cả lần gửi lẫn việc lọc lỗi
            _send(ob, cfg)
        except mailer.MailerNotConfigured:
            _defer_all_due(now)  # chưa cấu hình SMTP: không tính là lần thử
            Outbox.objects.filter(pk=ob.pk).update(next_attempt_at=now + NOT_CONFIGURED_DEFER)
            logger.warning("Chưa cấu hình SMTP: hoãn các email trong hộp thư đi %s phút", 10)
            break
        except Exception as exc:  # noqa: BLE001 - mọi lỗi gửi đều tính là một lần thử
            error = mailer.safe_error(exc, password)
            logger.warning("Gửi email outbox #%s lỗi (lần %s): %s", ob.pk, ob.attempts + 1, error)
            try:
                _mark_failed(ob, now, error)
            except Exception:  # noqa: BLE001
                logger.exception("Không ghi được kết quả lỗi cho outbox #%s", ob.pk)
        else:
            try:
                _mark_sent(ob, now)
            except Exception:  # noqa: BLE001
                logger.exception("Đã gửi outbox #%s nhưng không ghi được trạng thái", ob.pk)
            else:
                sent += 1
    return sent
