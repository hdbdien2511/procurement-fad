from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from apps.core.crypto import decrypt, encrypt


class EmailSettings(models.Model):
    """Cấu hình SMTP (một dòng duy nhất, pk=1). Mật khẩu luôn lưu dạng mã hoá."""

    host = models.CharField("Máy chủ SMTP", max_length=255, blank=True)
    port = models.PositiveIntegerField("Cổng", default=587)
    use_tls = models.BooleanField("Dùng STARTTLS", default=True)
    use_ssl = models.BooleanField("Dùng SSL/TLS ngay từ đầu", default=False)
    username = models.CharField("Tài khoản", max_length=255, blank=True)
    password_encrypted = models.TextField("Mật khẩu (đã mã hoá)", blank=True)
    from_address = models.CharField("Địa chỉ gửi", max_length=255, blank=True)
    timeout_seconds = models.PositiveIntegerField("Thời gian chờ (giây)", default=10)

    class Meta:
        verbose_name = "Cấu hình email"
        verbose_name_plural = "Cấu hình email"

    @classmethod
    def load(cls) -> "EmailSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        if self.use_tls and self.use_ssl:
            raise ValidationError("Không thể bật đồng thời STARTTLS và SSL/TLS.")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def set_password(self, raw: str) -> None:
        self.password_encrypted = encrypt(raw) if raw else ""

    def get_password(self) -> str:
        return decrypt(self.password_encrypted) if self.password_encrypted else ""

    def __str__(self):
        return "Cấu hình email"


class EmailTemplate(models.Model):
    code = models.CharField("Mã", max_length=30, unique=True)
    subject = models.CharField("Tiêu đề", max_length=300)
    body = models.TextField("Nội dung")

    def __str__(self):
        return self.code


class Outbox(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Chờ gửi"
        SENT = "SENT", "Đã gửi"
        FAILED = "FAILED", "Thất bại"

    kind = models.CharField(max_length=20, default="EMAIL")
    payload = models.JSONField(encoder=DjangoJSONEncoder)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="outbox_due_idx")]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=300)
    url = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
