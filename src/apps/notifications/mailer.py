"""Dựng kết nối SMTP từ cấu hình trên giao diện, render mẫu email và gửi.

Biến của từng mẫu: xem docstring của migration `0002_seed_email_templates`.
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail import get_connection as django_get_connection
from django.template import Context, Engine

from .models import EmailSettings, EmailTemplate

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

_body_engine = Engine(autoescape=True)
_subject_engine = Engine(autoescape=False)


class MailerNotConfigured(Exception):
    """Chưa cấu hình máy chủ SMTP."""


def scrub(text: str) -> str:
    """Loại mật khẩu SMTP khỏi chuỗi lỗi trước khi lưu/hiển thị."""
    try:
        password = EmailSettings.load().get_password()
    except Exception:  # không giải mã được: không có gì để lọc
        password = ""
    if password:
        text = text.replace(password, "***")
    return text


def get_connection():
    if settings.EMAIL_BACKEND != SMTP_BACKEND:
        return django_get_connection()  # ví dụ locmem khi kiểm thử
    cfg = EmailSettings.load()
    if not cfg.host:
        raise MailerNotConfigured("Chưa cấu hình máy chủ SMTP.")
    return django_get_connection(
        backend=SMTP_BACKEND,
        host=cfg.host,
        port=cfg.port,
        username=cfg.username,
        password=cfg.get_password(),
        use_tls=cfg.use_tls,
        use_ssl=cfg.use_ssl,
        timeout=cfg.timeout_seconds,
    )


def render(template_code: str, context: dict) -> tuple[str, str]:
    tpl = EmailTemplate.objects.get(code=template_code)
    ctx = Context(context)
    subject = _subject_engine.from_string(tpl.subject).render(ctx)
    subject = " ".join(subject.split())  # không cho xuống dòng (chống chèn header)
    body = _body_engine.from_string(tpl.body).render(Context(context))
    return subject, body


def send_now(to: list[str], subject: str, body: str) -> None:
    cfg = EmailSettings.load()
    from_email = cfg.from_address or settings.DEFAULT_FROM_EMAIL
    EmailMessage(subject, body, from_email, to, connection=get_connection()).send(fail_silently=False)
