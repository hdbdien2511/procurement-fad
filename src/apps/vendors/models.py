from django.db import models, transaction

from apps.audit import service as audit

ORG, INDIVIDUAL = "ORG", "INDIVIDUAL"
ACTIVE, PENDING, SUSPENDED, BLACKLISTED = "ACTIVE", "PENDING", "SUSPENDED", "BLACKLISTED"

KINDS = [(ORG, "Tổ chức"), (INDIVIDUAL, "Cá nhân")]
STATUSES = [
    (ACTIVE, "Đang hoạt động"),
    (PENDING, "Chờ duyệt"),
    (SUSPENDED, "Tạm ngưng"),
    (BLACKLISTED, "Danh sách đen"),
]


class VendorCategory(models.Model):
    code = models.CharField("Mã", max_length=40, unique=True)
    name = models.CharField("Tên", max_length=200)

    class Meta:
        verbose_name = "Nhóm nhà cung cấp"
        verbose_name_plural = "Nhóm nhà cung cấp"

    def __str__(self):
        return f"{self.code} — {self.name}"


class Vendor(models.Model):
    code = models.CharField("Mã", max_length=40, unique=True)
    tax_code = models.CharField("Mã số thuế", max_length=20, unique=True)
    name = models.CharField("Tên nhà cung cấp", max_length=300)
    kind = models.CharField("Loại hình", max_length=12, choices=KINDS, default=ORG)
    status = models.CharField("Trạng thái", max_length=12, choices=STATUSES, default=PENDING)
    bank_account = models.CharField("Số tài khoản", max_length=20, blank=True)
    bank_name = models.CharField("Ngân hàng", max_length=200, blank=True)
    categories = models.ManyToManyField(VendorCategory, blank=True, related_name="vendors")

    class Meta:
        verbose_name = "Nhà cung cấp"
        verbose_name_plural = "Nhà cung cấp"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.tax_code})"

    def is_selectable(self) -> bool:
        return self.status == ACTIVE

    def change_status(self, new_status: str, user, reason: str = "") -> None:
        if new_status not in {s for s, _ in STATUSES}:
            raise ValueError(f"Trạng thái không hợp lệ: {new_status}")
        with transaction.atomic():
            old = Vendor.objects.select_for_update().get(pk=self.pk).status
            if old == new_status:
                self.status = old
                return
            self.status = new_status
            self.save(update_fields=["status"])
            audit.record(
                "vendor.status_changed", self, actor=user,
                changes={**audit.diff({"status": old}, {"status": new_status}), "reason": reason},
            )
