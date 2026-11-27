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

from apps.accounts.roles import AUDITOR, FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role
from apps.core.fx import to_vnd
from apps.workflow import delegation, resolver
from apps.workflow.models import PENDING, WorkflowInstance, WorkflowTask

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
COMPANY_WIDE_ROLES = (FAD_PRECHECK, FAD_BUDGET_ADMIN, AUDITOR)


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
        "accounts.OrgUnit", on_delete=models.PROTECT, related_name="+", verbose_name="Đơn vị đề nghị"
    )
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
        }

    def cumulative_amount_vnd(self, scope: str) -> Decimal:
        return self.total_vnd  # tờ trình không xét hạn mức luỹ kế

    def on_workflow_finished(self, status: str) -> None:
        from . import services

        services.on_workflow_finished(self, status)

    # --- quyền xem ---
    def visible_to(self, user) -> bool:
        """Người tạo/đề nghị, cùng đơn vị đề nghị, người xử lý (hoặc đã xử lý / nhận uỷ quyền) bước
        duyệt, thành viên đơn vị quản lý ngân sách liên quan, FAD và Kiểm toán."""
        if not user.is_authenticated:
            return False
        if user.pk in (self.created_by_id, self.requester_id):
            return True
        if user.org_unit_id is not None:
            if user.org_unit_id == self.requester_unit_id:
                return True
            if self.fundings.filter(budget_line__budget_unit__managing_org_unit_id=user.org_unit_id).exists():
                return True
        if any(has_role(user, role) for role in COMPANY_WIDE_ROLES):
            return True
        tasks = WorkflowTask.objects.filter(instance__in=self.workflow_instances()).select_related("instance")
        if tasks.filter(Q(acted_by=user) | Q(on_behalf_of=user)).exists():
            return True
        for task in tasks:
            if resolver.candidates(task).filter(pk=user.pk).exists():
                return True
            if task.status == PENDING and delegation.delegates_for(task).filter(pk=user.pk).exists():
                return True
        return False


class RequisitionLine(models.Model):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="lines")
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


class RequisitionFunding(models.Model):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="fundings")
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
