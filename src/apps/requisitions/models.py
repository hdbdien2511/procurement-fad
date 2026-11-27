"""Tờ trình mua sắm (spec 4.1, 7.3): dòng hàng, phân bổ ngân sách, phiên bản.

Vòng đời (nộp, duyệt xong, huỷ, sửa lại, sao chép) nằm ở `apps.requisitions.services`; model chỉ giữ
dữ liệu, cách tính tổng và giao thức đối tượng luồng duyệt (`workflow_context`, `on_workflow_finished`).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.fx import to_vnd
from apps.workflow.models import WorkflowInstance

from .visibility import visibility_filter

DRAFT, IN_APPROVAL, RETURNED, APPROVED, BUDGET_BLOCKED, REJECTED, CANCELLED = (
    "DRAFT", "IN_APPROVAL", "RETURNED", "APPROVED", "BUDGET_BLOCKED", "REJECTED", "CANCELLED"
)
STATUSES = [
    (DRAFT, "Nháp"),
    (IN_APPROVAL, "Đang duyệt"),
    (RETURNED, "Trả lại bổ sung"),
    (APPROVED, "Đã duyệt"),
    (BUDGET_BLOCKED, "Đã duyệt, chưa giữ chỗ được ngân sách"),
    (REJECTED, "Từ chối"),
    (CANCELLED, "Đã huỷ"),
]
PROCUREMENT_TYPES = [("PROJECT", "Dự án"), ("BAU", "Thường xuyên (BAU)"), ("TRAVEL", "Công tác"), ("OTHER", "Khác")]

CENT = Decimal("0.01")
# Trường hệ thống được ghi khi tờ trình đã rời trạng thái nháp (mọi trường khác bị khoá).
SYSTEM_FIELDS = {"status", "number", "total_original", "total_vnd", "fx_rate"}
LOCKED_MESSAGE = "Tờ trình đã nộp, không được sửa nội dung"


class RequisitionQuerySet(models.QuerySet):
    def visible_to(self, user):
        q = visibility_filter(user)
        return self if q is None else self.filter(q).distinct()


def _parent_is_draft(requisition_ids) -> bool:
    ids = set(requisition_ids)
    return Requisition.objects.filter(pk__in=ids, status=DRAFT).count() == len(ids)


class _DraftOnlyQuerySet(models.QuerySet):
    """Dòng hàng / phân bổ chỉ được ghi khi tờ trình cha còn là nháp (kể cả thao tác hàng loạt)."""

    def _guard(self, requisition_ids):
        if not _parent_is_draft(requisition_ids):
            raise PermissionError(LOCKED_MESSAGE)

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        self._guard(o.requisition_id for o in objs)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        self._guard(self.values_list("requisition_id", flat=True))
        return super().update(**kwargs)

    def delete(self):
        self._guard(self.values_list("requisition_id", flat=True))
        return super().delete()


class _DraftOnly(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _parent_is_draft([self.requisition_id]):
            raise PermissionError(LOCKED_MESSAGE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not _parent_is_draft([self.requisition_id]):
            raise PermissionError(LOCKED_MESSAGE)
        return super().delete(*args, **kwargs)


class Requisition(models.Model):
    number = models.CharField("Số tờ trình", max_length=20, null=True, blank=True, editable=False)
    version = models.PositiveIntegerField("Phiên bản", default=1, editable=False)
    previous = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="next_versions",
        editable=False, verbose_name="Phiên bản trước",
    )
    title = models.CharField("Tiêu đề", max_length=300)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="Người đề nghị"
    )
    requester_unit = models.ForeignKey(
        "accounts.OrgUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+", editable=False,
        verbose_name="Đơn vị đề nghị",
    )  # lấy từ đơn vị của người đề nghị khi còn nháp (không cho chọn)
    procurement_type = models.CharField("Loại mua sắm", max_length=10, choices=PROCUREMENT_TYPES)
    necessity = models.TextField("Sự cần thiết", blank=True)
    currency = models.CharField("Loại tiền", max_length=3, default="VND")
    fx_rate = models.DecimalField("Tỷ giá", max_digits=12, decimal_places=4, null=True, blank=True, editable=False)
    total_original = models.DecimalField(
        "Tổng tiền (nguyên tệ)", max_digits=18, decimal_places=2, default=0, editable=False
    )
    total_vnd = models.DecimalField("Tổng tiền (VND)", max_digits=18, decimal_places=0, default=0, editable=False)
    service_start = models.DateField("Ngày bắt đầu dịch vụ")
    months = models.PositiveIntegerField("Số tháng phân bổ", default=1, validators=[MinValueValidator(1)])
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Nhà cung cấp",
    )
    quote_exception_reason = models.TextField("Lý do không đủ 03 báo giá", blank=True)
    consult_units = models.ManyToManyField(
        "accounts.OrgUnit", blank=True, related_name="+", verbose_name="Đơn vị tham vấn"
    )
    status = models.CharField("Trạng thái", max_length=20, choices=STATUSES, default=DRAFT, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="Người tạo"
    )
    created_at = models.DateTimeField("Tạo lúc", default=timezone.now, editable=False)

    objects = RequisitionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Tờ trình mua sắm"
        verbose_name_plural = "Tờ trình mua sắm"
        constraints = [
            models.UniqueConstraint(fields=["number", "version"], name="uniq_requisition_number_version"),
            models.CheckConstraint(condition=Q(months__gte=1), name="requisition_months_positive"),
        ]

    def __str__(self):
        if not self.number:
            return f"Tờ trình nháp #{self.pk}"
        return self.number if self.version == 1 else f"{self.number} (phiên bản {self.version})"

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if not self._state.adding:
            stored = Requisition.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored not in (None, DRAFT) and (update_fields is None or not set(update_fields) <= SYSTEM_FIELDS):
                raise PermissionError(LOCKED_MESSAGE)
        if self.status == DRAFT and self.requester_id is not None:
            from apps.accounts.models import User

            self.requester_unit_id = User.objects.filter(pk=self.requester_id).values_list(
                "org_unit_id", flat=True
            ).first()
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "requester_unit"}
        super().save(*args, **kwargs)

    # --- tiền ---
    def compute_totals(self, on: date) -> tuple[Decimal, Decimal, Decimal]:
        """`(tổng nguyên tệ, tổng VND, tỷ giá)` theo tỷ giá ngày `on`; có thể raise `MissingRate`."""
        total_original = sum((line.amount for line in self.lines.all()), Decimal("0"))
        total_vnd, rate = to_vnd(total_original, self.currency, on)
        return total_original, total_vnd, rate

    @property
    def reserve_start(self) -> date:
        """Kỳ bắt đầu phân bổ chi phí: tháng của ngày bắt đầu dịch vụ."""
        return self.service_start.replace(day=1)

    def budget_allocations(self):
        return [(f.budget_line, f.amount_vnd) for f in self.fundings.select_related("budget_line")]

    def budget_unit_ids(self) -> list[int]:
        return list(
            self.fundings.order_by("budget_line__budget_unit_id")
            .values_list("budget_line__budget_unit_id", flat=True)
            .distinct()
        )

    # --- luồng duyệt ---
    def workflow_instances(self):
        return WorkflowInstance.objects.filter(
            content_type=ContentType.objects.get_for_model(Requisition), object_id=str(self.pk)
        )

    def workflow_context(self) -> dict:
        return {
            "amount_vnd": self.total_vnd,
            "budget_unit_ids": self.budget_unit_ids(),
            "consult_unit_ids": list(self.consult_units.order_by("pk").values_list("pk", flat=True)),
            "requester_unit_id": self.requester_unit_id,
            "created_by_id": self.created_by_id,
            "requester_id": self.requester_id,
            "extra_barred_ids": self.earlier_party_ids(),
        }

    def earlier_party_ids(self) -> list[int]:
        """Người tạo / người đề nghị của các phiên bản trước (cũng không được duyệt phiên bản này)."""
        ids, prev = [], self.previous
        while prev is not None:
            ids += [prev.created_by_id, prev.requester_id]
            prev = prev.previous
        return sorted(set(ids) - {self.created_by_id, self.requester_id})

    def cumulative_amount_vnd(self, scope: str) -> Decimal:
        return self.total_vnd  # tờ trình không xét hạn mức luỹ kế

    def on_workflow_finished(self, status: str) -> None:
        from . import services

        services.on_workflow_finished(self, status)

    # --- quyền xem ---
    def visible_to(self, user) -> bool:
        """Cùng quy tắc với `Requisition.objects.visible_to(user)` (xem `visibility`)."""
        return Requisition.objects.visible_to(user).filter(pk=self.pk).exists()


class RequisitionLine(_DraftOnly):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="lines")
    objects = _DraftOnlyQuerySet.as_manager()
    description = models.CharField("Mô tả hàng hoá/dịch vụ", max_length=500)
    quantity = models.DecimalField("Số lượng", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField("Đơn giá", max_digits=18, decimal_places=2, validators=[MinValueValidator(0)])
    vat_rate = models.DecimalField(
        "Thuế suất VAT (%)", max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    class Meta:
        ordering = ["requisition", "pk"]
        verbose_name = "Dòng hàng tờ trình"
        verbose_name_plural = "Dòng hàng tờ trình"

    def __str__(self):
        return self.description

    @property
    def amount(self) -> Decimal:
        """Thành tiền gồm VAT, theo loại tiền của tờ trình, làm tròn 2 chữ số."""
        raw = self.quantity * self.unit_price * (1 + self.vat_rate / 100)
        return Decimal(raw).quantize(CENT, rounding=ROUND_HALF_UP)


class RequisitionFunding(_DraftOnly):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="fundings")
    objects = _DraftOnlyQuerySet.as_manager()
    budget_line = models.ForeignKey(
        "budget.BudgetLine", on_delete=models.PROTECT, related_name="+", verbose_name="Dòng ngân sách"
    )
    amount_vnd = models.DecimalField(
        "Số tiền phân bổ (VND)", max_digits=18, decimal_places=0, validators=[MinValueValidator(1)]
    )

    class Meta:
        ordering = ["requisition", "pk"]
        verbose_name = "Phân bổ ngân sách tờ trình"
        verbose_name_plural = "Phân bổ ngân sách tờ trình"

    def __str__(self):
        return f"{self.budget_line}: {self.amount_vnd}"
