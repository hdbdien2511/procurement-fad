from django.conf import settings
from django.db import models


class SavedFilter(models.Model):
    """Bộ lọc đã lưu của người dùng cho một bảng dữ liệu."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_filters")
    table_key = models.CharField("Bảng", max_length=100)
    name = models.CharField("Tên bộ lọc", max_length=100)
    params = models.JSONField("Tham số", default=dict)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "table_key", "name"], name="uniq_saved_filter_user_table_name")
        ]

    def __str__(self):
        return self.name
