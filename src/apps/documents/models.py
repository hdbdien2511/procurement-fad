import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

QUOTE = "QUOTE"
PROPOSAL = "PROPOSAL"
MEETING_MINUTES = "MEETING_MINUTES"
DELEGATION_LETTER = "DELEGATION_LETTER"
CONTRACT = "CONTRACT"
OTHER = "OTHER"

DOC_TYPES = [
    (QUOTE, "Báo giá"),
    (PROPOSAL, "Tờ trình"),
    (MEETING_MINUTES, "Biên bản họp"),
    (DELEGATION_LETTER, "Giấy ủy quyền"),
    (CONTRACT, "Hợp đồng"),
    (OTHER, "Khác"),
]

# Chỉ các trường này được cập nhật sau khi tạo (chứng từ lưu vĩnh viễn, không sửa nội dung).
MUTABLE_FIELDS = {"superseded_by", "superseded_by_id", "text_content", "search_vector"}


class DocumentQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionError("Chứng từ được lưu vĩnh viễn, không thể xoá")


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    attached_to = GenericForeignKey("content_type", "object_id")
    doc_type = models.CharField("Loại chứng từ", max_length=30, choices=DOC_TYPES)
    original_name = models.CharField("Tên tệp gốc", max_length=255)
    stored_path = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    mime = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    text_content = models.TextField(blank=True, default="")
    search_vector = SearchVectorField(null=True, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="supersedes"
    )

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            GinIndex(fields=["search_vector"], name="document_search_gin"),
            models.Index(fields=["content_type", "object_id"], name="document_attached_idx"),
        ]

    def __str__(self):
        return self.original_name

    def delete(self, *args, **kwargs):
        raise PermissionError("Chứng từ được lưu vĩnh viễn, không thể xoá")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            fields = kwargs.get("update_fields")
            if not fields or not set(fields) <= MUTABLE_FIELDS:
                raise PermissionError("Chứng từ không được sửa sau khi tải lên")
        super().save(*args, **kwargs)
