"""Chính sách duyệt có phiên bản và hồ sơ luồng duyệt đang chạy (spec 7.1).

Chính sách (ApprovalPolicy → PolicyRule → RuleStep) bất biến kể từ khi có WorkflowInstance tham
chiếu: mọi `save`/`delete` (kể cả qua QuerySet `update`/`delete`) đều raise `PermissionError`.
Muốn đổi thì tạo phiên bản mới bằng `ApprovalPolicy.clone_as_new_version`. Ngoại lệ duy nhất:
ngừng/bật lại một chính sách đã dùng bằng `policy.save(update_fields=["is_active"])` (snapshot đã
bảo vệ các hồ sơ đang chạy).

`Delegation`: uỷ quyền duyệt thay (spec 7.2); quy tắc áp dụng nằm ở `apps.workflow.delegation`.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit import service as audit
from apps.documents.models import DELEGATION_LETTER, DOC_TYPES

REQUISITION, BUDGET_CHANGE = "requisition", "budget_change"
SUBJECT_KINDS = [(REQUISITION, "Tờ trình mua sắm"), (BUDGET_CHANGE, "Đề nghị bổ sung/điều chuyển ngân sách")]

PROPOSE, BUDGET_OWNER, CONSULT, FAD_PRECHECK, APPROVE, MEETING = (
    "PROPOSE", "BUDGET_OWNER", "CONSULT", "FAD_PRECHECK", "APPROVE", "MEETING"
)
STEP_KINDS = [
    (PROPOSE, "Đề nghị"),
    (BUDGET_OWNER, "Đơn vị quản lý ngân sách xác nhận"),
    (CONSULT, "Tham vấn"),
    (FAD_PRECHECK, "FAD tiền kiểm"),
    (APPROVE, "Phê duyệt"),
    (MEETING, "Duyệt tại cuộc họp"),
]

REQUESTER_UNIT, BUDGET_UNIT, FIXED_UNIT, SELECTED_UNITS, COMPANY = (
    "REQUESTER_UNIT", "BUDGET_UNIT", "FIXED_UNIT", "SELECTED_UNITS", "COMPANY"
)
SCOPES = [
    (REQUESTER_UNIT, "Đơn vị lập hồ sơ"),
    (BUDGET_UNIT, "Đơn vị quản lý dòng ngân sách"),
    (FIXED_UNIT, "Đơn vị cố định"),
    (SELECTED_UNITS, "Đơn vị tham vấn được chọn"),
    (COMPANY, "Toàn công ty"),
]

RUNNING, APPROVED, REJECTED, RETURNED, CANCELLED = "RUNNING", "APPROVED", "REJECTED", "RETURNED", "CANCELLED"
INSTANCE_STATUSES = [
    (RUNNING, "Đang duyệt"),
    (APPROVED, "Đã duyệt"),
    (REJECTED, "Từ chối"),
    (RETURNED, "Trả lại bổ sung"),
    (CANCELLED, "Đã huỷ"),
]

WAITING, PENDING, COMMENTED, SKIPPED = "WAITING", "PENDING", "COMMENTED", "SKIPPED"
TASK_STATUSES = [
    (WAITING, "Chưa đến lượt"),
    (PENDING, "Chờ xử lý"),
    (APPROVED, "Chấp thuận"),
    (REJECTED, "Từ chối"),
    (RETURNED, "Trả lại"),
    (COMMENTED, "Đã cho ý kiến"),
    (SKIPPED, "Bỏ qua"),
]

IN_USE_MESSAGE = "Chính sách đã được sử dụng; hãy tạo phiên bản mới"


def _policies_in_use(policy_ids) -> bool:
    return WorkflowInstance.objects.filter(policy_id__in=policy_ids).exists()


class _ImmutableWhenUsedQuerySet(models.QuerySet):
    """Chặn `update`/`delete` hàng loạt khi một chính sách liên quan đã được sử dụng."""

    policy_path = None  # đường dẫn tới id chính sách, ví dụ "rule__policy_id"

    def _guard(self):
        if _policies_in_use(self.values(self.policy_path)):
            raise PermissionError(IN_USE_MESSAGE)

    def update(self, **kwargs):
        self._guard()
        return super().update(**kwargs)

    def delete(self):
        self._guard()
        return super().delete()


class PolicyQuerySet(_ImmutableWhenUsedQuerySet):
    policy_path = "pk"


class RuleQuerySet(_ImmutableWhenUsedQuerySet):
    policy_path = "policy_id"


class StepQuerySet(_ImmutableWhenUsedQuerySet):
    policy_path = "rule__policy_id"


class _ImmutableWhenUsed(models.Model):
    class Meta:
        abstract = True

    def _policy_id(self):
        raise NotImplementedError

    def _guard(self):
        policy_id = self._policy_id()
        if policy_id is not None and _policies_in_use([policy_id]):
            raise PermissionError(IN_USE_MESSAGE)

    def save(self, *args, **kwargs):
        self._guard()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard()
        return super().delete(*args, **kwargs)


class ApprovalPolicy(_ImmutableWhenUsed):
    code = models.CharField("Mã chính sách", max_length=50)
    subject_kind = models.CharField("Loại hồ sơ", max_length=20, choices=SUBJECT_KINDS)
    version = models.PositiveIntegerField("Phiên bản")
    effective_from = models.DateField("Hiệu lực từ")
    is_active = models.BooleanField("Đang dùng", default=True)

    objects = PolicyQuerySet.as_manager()

    class Meta:
        verbose_name = "Chính sách duyệt"
        verbose_name_plural = "Chính sách duyệt"
        constraints = [models.UniqueConstraint(fields=["code", "version"], name="uniq_policy_code_version")]

    def __str__(self):
        return f"{self.code} v{self.version}"

    def _policy_id(self):
        return self.pk

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.pk is not None and update_fields is not None and set(update_fields) == {"is_active"}:
            return models.Model.save(self, *args, **kwargs)  # chỉ ngừng/bật lại: được phép kể cả khi đã dùng
        return super().save(*args, **kwargs)

    @transaction.atomic
    def clone_as_new_version(self, effective_from) -> "ApprovalPolicy":
        """Sao chép sâu (rule + step) thành phiên bản kế tiếp của cùng mã chính sách."""
        last = ApprovalPolicy.objects.filter(code=self.code).aggregate(v=Max("version"))["v"] or 0
        clone = ApprovalPolicy.objects.create(
            code=self.code, subject_kind=self.subject_kind, version=last + 1,
            effective_from=effective_from, is_active=True,
        )
        for rule in self.rules.order_by("priority", "pk"):
            new_rule = PolicyRule.objects.create(
                policy=clone, priority=rule.priority, label=rule.label, max_amount=rule.max_amount,
                cumulative_cap=rule.cumulative_cap, cumulative_cap_pct=rule.cumulative_cap_pct,
            )
            for step in rule.steps.order_by("seq", "pk"):
                RuleStep.objects.create(
                    rule=new_rule, seq=step.seq, kind=step.kind, role_code=step.role_code,
                    scope=step.scope, fixed_org_unit_id=step.fixed_org_unit_id, mandatory=step.mandatory,
                    sla_hours=step.sla_hours, escalate_role_code=step.escalate_role_code,
                    requires_doc_type=step.requires_doc_type,
                )
        return clone


class PolicyRule(_ImmutableWhenUsed):
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.CASCADE, related_name="rules")
    priority = models.PositiveIntegerField("Thứ tự ưu tiên")
    label = models.CharField("Nhãn", max_length=100)
    max_amount = models.DecimalField(
        "Số tiền tối đa (≤)", max_digits=18, decimal_places=0, null=True, blank=True
    )
    cumulative_cap = models.DecimalField(
        "Luỹ kế năm phải nhỏ hơn", max_digits=18, decimal_places=0, null=True, blank=True
    )
    cumulative_cap_pct = models.DecimalField(
        "Luỹ kế năm phải nhỏ hơn (% chi phí cố định năm)", max_digits=7, decimal_places=4,
        null=True, blank=True,
    )

    objects = RuleQuerySet.as_manager()

    class Meta:
        ordering = ["policy", "priority"]
        verbose_name = "Quy tắc duyệt"
        verbose_name_plural = "Quy tắc duyệt"

    def __str__(self):
        return f"{self.policy} · {self.label}"

    def _policy_id(self):
        return self.policy_id


class RuleStep(_ImmutableWhenUsed):
    rule = models.ForeignKey(PolicyRule, on_delete=models.CASCADE, related_name="steps")
    seq = models.PositiveIntegerField("Thứ tự bước")
    kind = models.CharField("Loại bước", max_length=20, choices=STEP_KINDS)
    role_code = models.CharField("Vai trò", max_length=50)
    scope = models.CharField("Phạm vi", max_length=20, choices=SCOPES)
    fixed_org_unit = models.ForeignKey(
        "accounts.OrgUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Đơn vị cố định",
    )
    mandatory = models.BooleanField("Bắt buộc chấp thuận", default=True)
    sla_hours = models.PositiveIntegerField("Thời hạn xử lý (giờ)")
    escalate_role_code = models.CharField("Vai trò nhận chuyển cấp", max_length=50, null=True, blank=True)
    requires_doc_type = models.CharField(
        "Chứng từ bắt buộc", max_length=30, choices=DOC_TYPES, null=True, blank=True
    )

    objects = StepQuerySet.as_manager()

    class Meta:
        ordering = ["rule", "seq", "pk"]
        verbose_name = "Bước duyệt"
        verbose_name_plural = "Bước duyệt"

    def __str__(self):
        return f"{self.rule} · {self.seq}. {self.get_kind_display()}"

    def _policy_id(self):
        return self.rule.policy_id if self.rule_id else None

    def clean(self):
        if self.scope == FIXED_UNIT and self.fixed_org_unit_id is None:
            raise ValidationError({"fixed_org_unit": "Phạm vi đơn vị cố định cần chọn đơn vị."})
        if self.kind == MEETING and not self.requires_doc_type:
            raise ValidationError({"requires_doc_type": "Bước duyệt tại cuộc họp cần chứng từ biên bản."})


class WorkflowInstance(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    subject = GenericForeignKey("content_type", "object_id")
    policy = models.ForeignKey(ApprovalPolicy, on_delete=models.PROTECT, related_name="instances")
    rule = models.ForeignKey(PolicyRule, on_delete=models.PROTECT, related_name="instances")
    snapshot = models.JSONField("Ảnh chụp chính sách")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField("Trạng thái", max_length=20, choices=INSTANCE_STATUSES, default=RUNNING)
    started_at = models.DateTimeField("Bắt đầu", default=timezone.now)
    finished_at = models.DateTimeField("Kết thúc", null=True, blank=True)

    class Meta:
        verbose_name = "Hồ sơ luồng duyệt"
        verbose_name_plural = "Hồ sơ luồng duyệt"
        indexes = [models.Index(fields=["content_type", "object_id"], name="wf_instance_subject_idx")]

    def __str__(self):
        return f"Luồng duyệt #{self.pk} ({self.get_status_display()})"


class WorkflowTask(models.Model):
    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name="tasks")
    seq = models.PositiveIntegerField("Thứ tự bước")
    step_index = models.PositiveIntegerField("Vị trí bước trong snapshot")
    branch_key = models.CharField("Nhánh", max_length=50, blank=True)
    kind = models.CharField("Loại bước", max_length=20, choices=STEP_KINDS)
    role_code = models.CharField("Vai trò", max_length=50)
    org_unit = models.ForeignKey(
        "accounts.OrgUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Đơn vị",
    )
    mandatory = models.BooleanField("Bắt buộc chấp thuận")
    status = models.CharField("Trạng thái", max_length=20, choices=TASK_STATUSES, default=WAITING)
    opened_at = models.DateTimeField("Thời điểm đến lượt", null=True, blank=True)
    due_at = models.DateTimeField("Hạn xử lý", null=True, blank=True)
    reminded_at = models.DateTimeField("Đã nhắc hạn lúc", null=True, blank=True)
    overdue_notified_at = models.DateTimeField("Đã báo quá hạn lúc", null=True, blank=True)
    escalated_at = models.DateTimeField("Đã chuyển cấp lúc", null=True, blank=True)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    comment = models.TextField("Ý kiến", blank=True)
    acted_at = models.DateTimeField("Thời điểm xử lý", null=True, blank=True)

    class Meta:
        ordering = ["instance", "seq", "pk"]
        verbose_name = "Bước xử lý"
        verbose_name_plural = "Bước xử lý"
        indexes = [models.Index(fields=["status", "role_code"], name="wf_task_inbox_idx")]

    def __str__(self):
        return f"{self.instance_id}/{self.seq} {self.get_kind_display()} ({self.get_status_display()})"


DELEGATION_IMMUTABLE_MESSAGE = "Uỷ quyền đã tạo không được sửa; hãy thu hồi và tạo uỷ quyền mới"


class DelegationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if set(kwargs) != {"revoked_at"}:
            raise PermissionError(DELEGATION_IMMUTABLE_MESSAGE)
        return super().update(**kwargs)


class Delegation(models.Model):
    """Uỷ quyền duyệt thay: `delegate` xử lý thay `delegator` trong khoảng ngày và phạm vi đã định.

    `subject_kinds` rỗng = mọi loại hồ sơ; `org_unit` null = mọi đơn vị; `max_amount_vnd` null =
    không giới hạn. Tạo qua `delegation.create_delegation` (kiểm tra + audit), thu hồi bằng `revoke`.
    """

    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delegations_given",
        verbose_name="Người uỷ quyền",
    )
    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delegations_received",
        verbose_name="Người nhận uỷ quyền",
    )
    start_date = models.DateField("Từ ngày")
    end_date = models.DateField("Đến ngày")
    max_amount_vnd = models.DecimalField(
        "Hạn mức tối đa (VND)", max_digits=18, decimal_places=0, null=True, blank=True
    )
    subject_kinds = models.JSONField("Loại hồ sơ", default=list, blank=True)
    org_unit = models.ForeignKey(
        "accounts.OrgUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Phòng ban",
    )
    letter = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="Văn bản uỷ quyền",
    )
    created_at = models.DateTimeField("Tạo lúc", default=timezone.now)
    revoked_at = models.DateTimeField("Thu hồi lúc", null=True, blank=True)

    objects = DelegationQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "pk"]
        verbose_name = "Uỷ quyền duyệt thay"
        verbose_name_plural = "Uỷ quyền duyệt thay"
        indexes = [models.Index(fields=["delegate", "start_date", "end_date"], name="wf_delegation_active_idx")]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delegate=models.F("delegator")), name="delegation_not_self",
                violation_error_message="Không thể uỷ quyền cho chính mình",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")), name="delegation_end_after_start",
                violation_error_message="Ngày kết thúc phải từ ngày bắt đầu trở đi",
            ),
        ]

    def __str__(self):
        return f"Uỷ quyền #{self.pk}: {self.delegator} → {self.delegate}"

    def save(self, *args, **kwargs):
        """Bất biến sau khi tạo (không âm thầm nới thẩm quyền), trừ việc đánh dấu thu hồi."""
        update_fields = kwargs.get("update_fields")
        if not self._state.adding and (update_fields is None or set(update_fields) != {"revoked_at"}):
            raise PermissionError(DELEGATION_IMMUTABLE_MESSAGE)
        super().save(*args, **kwargs)

    def clean(self):
        valid = {code for code, _ in SUBJECT_KINDS}
        if not isinstance(self.subject_kinds, list) or not set(self.subject_kinds) <= valid:
            raise ValidationError({"subject_kinds": "Loại hồ sơ không hợp lệ"})
        if self.letter_id is not None and self.letter.doc_type != DELEGATION_LETTER:
            raise ValidationError({"letter": "Văn bản đính kèm phải là chứng từ loại Giấy ủy quyền"})

    @transaction.atomic
    def revoke(self, user) -> None:
        locked = Delegation.objects.select_for_update().get(pk=self.pk)
        if locked.revoked_at is not None:
            raise ValidationError("Uỷ quyền đã bị thu hồi")
        self.revoked_at = locked.revoked_at = timezone.now()
        locked.save(update_fields=["revoked_at"])
        audit.record("delegation.revoked", locked, actor=user, changes={"revoked_at": locked.revoked_at})
