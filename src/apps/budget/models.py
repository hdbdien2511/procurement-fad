from django.conf import settings
from django.db import models

# Loại bút toán ngân sách (spec 7.3)
ORIGINAL = "ORIGINAL"
ADJUST = "ADJUST"
TRANSFER = "TRANSFER"
RESERVE = "RESERVE"
RELEASE = "RELEASE"
EXPENSE = "EXPENSE"
ACCRUAL = "ACCRUAL"
REVERSAL = "REVERSAL"
DEPRE = "DEPRE"
FORECAST = "FORECAST"

ENTRY_KINDS = [
    (ORIGINAL, "Kế hoạch gốc"),
    (ADJUST, "Điều chỉnh"),
    (TRANSFER, "Điều chuyển"),
    (RESERVE, "Giữ chỗ"),
    (RELEASE, "Giải phóng giữ chỗ"),
    (EXPENSE, "Chi phí ghi nhận"),
    (ACCRUAL, "Trích trước"),
    (REVERSAL, "Hoàn trích"),
    (DEPRE, "Khấu hao"),
    (FORECAST, "Dự báo"),
]

BUDGET_KINDS = {ORIGINAL, ADJUST, TRANSFER}
RESERVED_KINDS = {RESERVE, RELEASE}
EXPENSE_KINDS = {EXPENSE, ACCRUAL, REVERSAL, DEPRE}

# Dấu bắt buộc theo loại: RELEASE/REVERSAL lưu số âm; ADJUST/TRANSFER tuỳ ý.
NEGATIVE_KINDS = {RELEASE, REVERSAL}
NON_NEGATIVE_KINDS = {RESERVE, EXPENSE, ACCRUAL, DEPRE, ORIGINAL, FORECAST}


class BudgetUnit(models.Model):
    code = models.CharField("Mã", max_length=20, unique=True)
    name = models.CharField("Tên", max_length=255)
    managing_org_unit = models.ForeignKey(
        "accounts.OrgUnit", on_delete=models.PROTECT, related_name="budget_units",
        verbose_name="Đơn vị quản lý",
    )
    is_union_fund = models.BooleanField("Nguồn Công đoàn", default=False)

    class Meta:
        ordering = ["code"]
        verbose_name = "Đơn vị quản lý ngân sách"

    def __str__(self):
        return f"{self.code} · {self.name}"


class MainItem(models.Model):
    code = models.CharField("Mã", max_length=10, unique=True)
    name = models.CharField("Tên", max_length=255)

    class Meta:
        ordering = ["code"]
        verbose_name = "Main item"

    def __str__(self):
        return f"{self.code}. {self.name}"


class CostCode(models.Model):
    code = models.CharField("Mã chi phí (L8)", max_length=50, unique=True)
    name = models.CharField("Tên", max_length=255)
    budget_unit = models.ForeignKey(BudgetUnit, on_delete=models.PROTECT, related_name="cost_codes")
    is_capex = models.BooleanField("Capex", default=False)

    class Meta:
        ordering = ["code"]
        verbose_name = "Mã chi phí"

    def __str__(self):
        return f"{self.code} · {self.name}"


class CostCodeMainItem(models.Model):
    """Ánh xạ L8 → Main item theo phiên bản năm."""

    cost_code = models.ForeignKey(CostCode, on_delete=models.PROTECT, related_name="main_items")
    year = models.PositiveSmallIntegerField("Năm")
    main_item = models.ForeignKey(MainItem, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cost_code", "year"], name="uniq_costcode_mainitem_year")
        ]

    def __str__(self):
        return f"{self.year} · {self.cost_code.code} → {self.main_item.code}"


class Project(models.Model):
    code = models.CharField("Mã dự án (L10)", max_length=50, unique=True)
    name = models.CharField("Tên", max_length=255)
    workstream = models.CharField("Workstream", max_length=100, blank=True, default="")
    begin_year = models.PositiveSmallIntegerField("Năm bắt đầu")
    budget_unit = models.ForeignKey(BudgetUnit, on_delete=models.PROTECT, related_name="projects")

    class Meta:
        ordering = ["code"]
        verbose_name = "Dự án"

    def __str__(self):
        return f"{self.code} · {self.name}"


class Location(models.Model):
    code = models.CharField("Mã", max_length=10, unique=True)
    name = models.CharField("Tên", max_length=100)

    class Meta:
        ordering = ["code"]
        verbose_name = "Địa điểm"

    def __str__(self):
        return f"{self.code} · {self.name}"


class BudgetLine(models.Model):
    year = models.PositiveSmallIntegerField("Năm")
    budget_unit = models.ForeignKey(BudgetUnit, on_delete=models.PROTECT, related_name="lines")
    cost_code = models.ForeignKey(CostCode, on_delete=models.PROTECT, related_name="lines")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="lines")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="lines")

    class Meta:
        ordering = ["year", "budget_unit__code", "cost_code__code", "project__code", "location__code"]
        verbose_name = "Dòng ngân sách"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "budget_unit", "cost_code", "project", "location"],
                name="uniq_budgetline_dims",
            )
        ]

    def __str__(self):
        return (
            f"{self.year} · {self.budget_unit.code} · {self.cost_code.code} · "
            f"{self.project.code} · {self.location.code}"
        )

    @property
    def short_label(self) -> str:
        """Nhãn ngắn dùng trong cảnh báo: L8/L10/địa điểm."""
        return f"{self.cost_code.code}/{self.project.code}/{self.location.code}"


class BudgetEntryQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionError("Bút toán ngân sách là chỉ-ghi-thêm, không được xoá.")


class BudgetEntry(models.Model):
    """Bút toán ngân sách chỉ-ghi-thêm, gắn kỳ tháng (ngày đầu tháng)."""

    id = models.BigAutoField(primary_key=True)
    line = models.ForeignKey(BudgetLine, on_delete=models.PROTECT, related_name="entries")
    period = models.DateField("Kỳ")
    kind = models.CharField("Loại", max_length=10, choices=ENTRY_KINDS)
    amount = models.DecimalField("Số tiền (VND)", max_digits=18, decimal_places=0)
    source_type = models.CharField(max_length=100, blank=True, default="")
    source_id = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField("Ghi chú", blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BudgetEntryQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        verbose_name = "Bút toán ngân sách"
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="budgetentry_source_idx"),
            models.Index(fields=["line", "period"], name="budgetentry_line_period_idx"),
        ]

    def __str__(self):
        return f"{self.period:%m/%Y} · {self.get_kind_display()} · {self.amount}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise PermissionError("Bút toán ngân sách là chỉ-ghi-thêm, không được sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Bút toán ngân sách không được xoá.")
