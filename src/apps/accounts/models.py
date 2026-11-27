from django.contrib.auth.models import AbstractUser
from django.db import models


class OrgUnit(models.Model):
    class Kind(models.TextChoices):
        KHOI = "KHOI", "Khối"
        PHONG = "PHONG", "Phòng"
        CHI_NHANH = "CHI_NHANH", "Chi nhánh"

    code = models.CharField("Mã đơn vị", max_length=50, unique=True)
    name = models.CharField("Tên đơn vị", max_length=255)
    kind = models.CharField("Loại", max_length=20, choices=Kind.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    head = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="headed_units",
    )
    is_active = models.BooleanField("Đang hoạt động", default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class User(AbstractUser):
    """Người dùng hệ thống. Họ tên đầy đủ lưu ở `first_name` (đồng bộ từ HRIS)."""

    org_unit = models.ForeignKey(
        OrgUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="members"
    )
    title = models.CharField("Chức danh", max_length=255, blank=True)
    employee_code = models.CharField(
        "Mã nhân viên", max_length=50, unique=True, null=True, blank=True
    )
    entra_oid = models.CharField(
        "Entra Object ID", max_length=64, unique=True, null=True, blank=True
    )


class Role(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.code


class RoleAssignment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    org_unit = models.ForeignKey(
        OrgUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="role_assignments"
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
