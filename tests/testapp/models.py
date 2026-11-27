from decimal import Decimal

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
    cumulative_vnd = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    finished_status = models.CharField(max_length=20, blank=True)

    def visible_to(self, user) -> bool:
        if user.pk == self.owner_id:
            return True
        return self.unit_id is not None and self.unit_id == user.org_unit_id

    # --- giao thức đối tượng luồng duyệt (apps.workflow.engine) ---
    def workflow_context(self) -> dict:
        return {
            "amount_vnd": self.amount_vnd,
            "budget_unit_ids": list(self.budget_unit_ids),
            "consult_unit_ids": list(self.consult_unit_ids),
            "requester_unit_id": self.unit_id,
            "created_by_id": self.created_by_id,
        }

    def cumulative_amount_vnd(self, scope: str) -> Decimal:
        return self.cumulative_vnd

    def on_workflow_finished(self, status: str) -> None:
        self.finished_status = status
        self.save(update_fields=["finished_status"])
