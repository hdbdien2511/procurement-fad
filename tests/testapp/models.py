from django.conf import settings
from django.db import models


class Dummy(models.Model):
    """Đối tượng nghiệp vụ giả chỉ dùng trong kiểm thử (gắn chứng từ, ngân sách, quy trình)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    unit = models.ForeignKey("accounts.OrgUnit", null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    amount_vnd = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    budget_unit_ids = models.JSONField(default=list)
    consult_unit_ids = models.JSONField(default=list)

    def visible_to(self, user) -> bool:
        if user.pk == self.owner_id:
            return True
        return self.unit_id is not None and self.unit_id == user.org_unit_id
