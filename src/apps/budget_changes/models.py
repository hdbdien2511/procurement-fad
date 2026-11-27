"""Đề nghị bổ sung / điều chuyển ngân sách (spec 4.1 câu 1): duyệt theo nhóm "Ngoài ngân sách".

Vòng đời (nộp, duyệt xong, ghi lại, mở lại, huỷ, tạo sẵn từ tờ trình bị chặn) nằm ở
`apps.budget_changes.services`; model chỉ giữ dữ liệu, cách tính luỹ kế và giao thức đối tượng luồng
duyệt (`workflow_context`, `cumulative_amount_vnd`, `on_workflow_finished`).
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.money import round_vnd
from apps.workflow.models import WorkflowInstance

from .visibility import visibility_filter

DRAFT, IN_APPROVAL, RETURNED, APPROVED, BLOCKED, REJECTED, CANCELLED = (
    "DRAFT", "IN_APPROVAL", "RETURNED", "APPROVED", "BLOCKED", "REJECTED", "CANCELLED"
)
STATUSES = [
    (DRAFT, "Nháp"),
    (IN_APPROVAL, "Đang duyệt"),
    (RETURNED, "Trả lại bổ sung"),
    (APPROVED, "Đã duyệt"),
    (BLOCKED, "Đã duyệt, chưa ghi được ngân sách"),
    (REJECTED, "Từ chối"),
    (CANCELLED, "Đã huỷ"),
]
SUPPLEMENT, TRANSFER = "SUPPLEMENT", "TRANSFER"
KINDS = [(SUPPLEMENT, "Bổ sung ngân sách"), (TRANSFER, "Điều chuyển ngân sách")]
COMPANY_SCOPE, UNIT_SCOPE = "COMPANY", "UNIT"

# Trường hệ thống được ghi khi đề nghị đã rời trạng thái nháp (mọi trường khác bị khoá).
SYSTEM_FIELDS = {"status", "number"}
LOCKED_MESSAGE = "Đề nghị đã nộp, không được sửa nội dung"
WHOLE_DONG_MESSAGE = "Số tiền đề nghị phải là số nguyên đồng"


class BudgetChangeQuerySet(models.QuerySet):
    def visible_to(self, user):
        q = visibility_filter(user)
        return self if q is None else self.filter(q).distinct()


class BudgetChangeRequest(models.Model):
    number = models.CharField("Số đề nghị", max_length=20, null=True, blank=True, unique=True, editable=False)
    kind = models.CharField("Loại đề nghị", max_length=10, choices=KINDS)
    from_line = models.ForeignKey(
        "budget.BudgetLine", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Dòng ngân sách nguồn",
    )  # chỉ dùng cho điều chuyển
    to_line = models.ForeignKey(
        "budget.BudgetLine", on_delete=models.PROTECT, related_name="+", verbose_name="Dòng ngân sách nhận"
    )
    amount_vnd = models.DecimalField(
        "Số tiền (VND)", max_digits=18, decimal_places=0, validators=[MinValueValidator(1)]
    )
    start = models.DateField("Kỳ bắt đầu")  # chuẩn hoá về ngày đầu tháng
    months = models.PositiveIntegerField("Số tháng phân bổ", default=1, validators=[MinValueValidator(1)])
    reason = models.TextField("Lý do")
    requisition = models.ForeignKey(
        "requisitions.Requisition", null=True, blank=True, on_delete=models.PROTECT,
        related_name="budget_change_requests", verbose_name="Tờ trình liên quan",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="Người đề nghị"
    )
    requester_unit = models.ForeignKey(
        "accounts.OrgUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+", editable=False,
        verbose_name="Đơn vị đề nghị",
    )  # lấy từ đơn vị của người đề nghị khi còn nháp (không cho chọn)
    status = models.CharField("Trạng thái", max_length=20, choices=STATUSES, default=DRAFT, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="Người tạo"
    )
    created_at = models.DateTimeField("Tạo lúc", default=timezone.now, editable=False)

    objects = BudgetChangeQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Đề nghị bổ sung/điều chuyển ngân sách"
        verbose_name_plural = "Đề nghị bổ sung/điều chuyển ngân sách"
        constraints = [
            models.CheckConstraint(condition=Q(months__gte=1), name="budget_change_months_positive"),
        ]

    def __str__(self):
        return self.number or f"Đề nghị ngân sách nháp #{self.pk}"

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if not self._state.adding:
            stored = BudgetChangeRequest.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored not in (None, DRAFT) and (update_fields is None or not set(update_fields) <= SYSTEM_FIELDS):
                raise PermissionError(LOCKED_MESSAGE)
        if self.status == DRAFT:
            if self.amount_vnd is not None and Decimal(self.amount_vnd) != round_vnd(Decimal(self.amount_vnd)):
                raise ValueError(WHOLE_DONG_MESSAGE)
            if self.start is not None:
                self.start = self.start.replace(day=1)
            extra = {"start"}
            if self.requester_id is not None:
                from apps.accounts.models import User

                self.requester_unit_id = User.objects.filter(pk=self.requester_id).values_list(
                    "org_unit_id", flat=True
                ).first()
                extra.add("requester_unit")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, *extra}
        super().save(*args, **kwargs)

    # --- ngân sách ---
    @property
    def year(self) -> int:
        return self.to_line.year

    def legs(self) -> list:
        """Các chân bút toán `(dòng, số tiền có dấu)` khi đề nghị được duyệt."""
        if self.kind == TRANSFER:
            return [(self.from_line, -self.amount_vnd), (self.to_line, self.amount_vnd)]
        return [(self.to_line, self.amount_vnd)]

    def budget_unit_ids(self) -> list[int]:
        ids = {self.to_line.budget_unit_id}
        if self.kind == TRANSFER and self.from_line_id is not None:
            ids.add(self.from_line.budget_unit_id)
        return sorted(ids)

    # --- luồng duyệt ---
    def workflow_instances(self):
        return WorkflowInstance.objects.filter(
            content_type=ContentType.objects.get_for_model(BudgetChangeRequest), object_id=str(self.pk)
        )

    def workflow_context(self) -> dict:
        return {
            "amount_vnd": self.amount_vnd,
            "budget_unit_ids": self.budget_unit_ids(),
            "consult_unit_ids": [],
            "requester_unit_id": self.requester_unit_id,
            "created_by_id": self.created_by_id,
            "requester_id": self.requester_id,
            "extra_barred_ids": [],
        }

    def cumulative_amount_vnd(self, scope: str) -> Decimal:
        """Luỹ kế ngoài ngân sách sau đề nghị này: tổng đề nghị bổ sung đã duyệt trong năm của dòng nhận
        (toàn công ty, hoặc cùng đơn vị ngân sách khi `scope == "UNIT"`) cộng chính đề nghị này.
        Điều chuyển không làm tăng tổng ngân sách nên không tính luỹ kế (chỉ trả số của chính nó)."""
        if self.kind == TRANSFER:
            return self.amount_vnd
        if scope not in (COMPANY_SCOPE, UNIT_SCOPE):
            raise ValueError(f"Phạm vi luỹ kế không hợp lệ: {scope}")
        approved = BudgetChangeRequest.objects.filter(
            kind=SUPPLEMENT, status=APPROVED, to_line__year=self.to_line.year
        ).exclude(pk=self.pk)
        if scope == UNIT_SCOPE:
            approved = approved.filter(to_line__budget_unit_id=self.to_line.budget_unit_id)
        total = approved.aggregate(total=Sum("amount_vnd"))["total"] or Decimal(0)
        return total + self.amount_vnd

    def on_workflow_finished(self, status: str) -> None:
        from . import services

        services.on_workflow_finished(self, status)

    # --- quyền xem ---
    def visible_to(self, user) -> bool:
        """Cùng quy tắc với `BudgetChangeRequest.objects.visible_to(user)` (xem `visibility`)."""
        return BudgetChangeRequest.objects.visible_to(user).filter(pk=self.pk).exists()
