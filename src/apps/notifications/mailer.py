"""Dựng kết nối SMTP từ cấu hình trên giao diện, render mẫu email và gửi.

Biến của từng mẫu: xem docstring của migration `0002_seed_email_templates`.
"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail import get_connection as django_get_connection
from django.template import Context, Engine
from django.utils.safestring import mark_safe

from .models import EmailSettings, EmailTemplate

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

_body_engine = Engine(autoescape=True)
_subject_engine = Engine(autoescape=False)


class MailerNotConfigured(Exception):
    """Chưa cấu hình máy chủ SMTP."""


def scrub(text: str, password: str | None = None) -> str:
    """Loại mật khẩu SMTP khỏi chuỗi. Nên truyền đúng mật khẩu đã dùng cho lần gửi đó."""
    if password is None:
        try:
            password = EmailSettings.load().get_password()
        except Exception:  # không giải mã được: không có gì để lọc
            password = ""
    return text.replace(password, "***") if password else text


def safe_error(exc: BaseException, password: str = "") -> str:
    """Chuỗi lỗi an toàn để lưu/hiển thị: tên lớp + mã lỗi (nếu có) + thông điệp đã lọc, tối đa 300 ký tự."""
    code = getattr(exc, "smtp_code", None) or getattr(exc, "errno", None)
    message = scrub(str(exc), password)[:300]
    return f"{type(exc).__name__}{f' [{code}]' if code else ''}: {message}"


def get_connection(cfg: EmailSettings | None = None):
    if settings.EMAIL_BACKEND != SMTP_BACKEND:
        return django_get_connection()  # ví dụ locmem khi kiểm thử
    cfg = cfg or EmailSettings.load()
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
    if "duong_dan" in context:  # URL nội bộ trong email văn bản thuần: không escape dấu & của query string
        context = {**context, "duong_dan": mark_safe(context["duong_dan"])}
    ctx = Context(context)
    subject = _subject_engine.from_string(tpl.subject).render(ctx)
    subject = " ".join(subject.split())  # không cho xuống dòng (chống chèn header)
    body = _body_engine.from_string(tpl.body).render(Context(context))
    return subject, body


def send_now(to: list[str], subject: str, body: str, cfg: EmailSettings | None = None) -> None:
    cfg = cfg or EmailSettings.load()
    from_email = cfg.from_address or settings.DEFAULT_FROM_EMAIL
    EmailMessage(subject, body, from_email, to, connection=get_connection(cfg)).send(fail_silently=False)
