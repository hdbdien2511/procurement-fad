"""Dựng 2 chính sách duyệt mẫu theo bảng thẩm quyền spec mục 4 (dùng lại ở Task 16).

Cấu trúc bước (seq: kind/role/scope) bám đúng mô tả seed_demo của Task 16. Tham vấn
`mandatory=False`, FAD tiền kiểm `mandatory=True`, SLA 48 giờ.
"""

from datetime import date
from decimal import Decimal

from apps.accounts import roles as R
from apps.documents.models import MEETING_MINUTES
from apps.workflow.models import ApprovalPolicy, PolicyRule, RuleStep

SLA_HOURS = 48

# (kind, role_code, scope, mandatory, requires_doc_type)
BUDGET_OWNER_STEP = ("BUDGET_OWNER", R.BUDGET_OWNER, "BUDGET_UNIT", True, None)
CONSULT_STEP = ("CONSULT", R.CONSULTANT, "SELECTED_UNITS", False, None)
FAD_STEP = ("FAD_PRECHECK", R.FAD_PRECHECK, "COMPANY", True, None)


def _propose(role, scope="COMPANY"):
    return ("PROPOSE", role, scope, True, None)


def _approve(role, scope="COMPANY"):
    return ("APPROVE", role, scope, True, None)


def _meeting(role):
    return ("MEETING", role, "COMPANY", True, MEETING_MINUTES)


IN_BUDGET_RULES = [
    ("<200tr", Decimal(199_999_999), None, None,
     [BUDGET_OWNER_STEP, CONSULT_STEP, FAD_STEP, _approve(R.DEPT_HEAD, "REQUESTER_UNIT")]),
    ("200tr-2ty", Decimal(2_000_000_000), None, None,
     [_propose(R.DEPT_HEAD, "REQUESTER_UNIT"), BUDGET_OWNER_STEP, CONSULT_STEP, FAD_STEP,
      _approve(R.GDDH)]),
    (">2ty", None, None, None,
     [_propose(R.GDDH), BUDGET_OWNER_STEP, CONSULT_STEP, FAD_STEP, _meeting(R.BMS_SECRETARY)]),
]

OUT_BUDGET_RULES = [
    ("A", Decimal(49_999_999), Decimal(200_000_000), None,
     [_propose(R.DEPT_HEAD, "REQUESTER_UNIT"), FAD_STEP, _approve(R.GDDH)]),
    ("B", Decimal(300_000_000), Decimal(2_000_000_000), None,
     [_propose(R.GDDH), FAD_STEP, _meeting(R.BMS_SECRETARY)]),
    ("C", Decimal(3_000_000_000), None, Decimal(2),
     [_propose(R.GDDH), FAD_STEP, _approve(R.CEO)]),
    ("D", None, None, None,
     [_propose(R.CEO), FAD_STEP, _meeting(R.BOARD_SECRETARY)]),
]


def build_policy(code, subject_kind, rules, *, effective_from: date, version=1) -> ApprovalPolicy:
    policy = ApprovalPolicy.objects.create(
        code=code, subject_kind=subject_kind, version=version, effective_from=effective_from
    )
    for priority, (label, max_amount, cap, cap_pct, steps) in enumerate(rules, start=1):
        rule = PolicyRule.objects.create(
            policy=policy, priority=priority, label=label, max_amount=max_amount,
            cumulative_cap=cap, cumulative_cap_pct=cap_pct,
        )
        for seq, (kind, role, scope, mandatory, doc_type) in enumerate(steps, start=1):
            RuleStep.objects.create(
                rule=rule, seq=seq, kind=kind, role_code=role, scope=scope, mandatory=mandatory,
                sla_hours=SLA_HOURS, requires_doc_type=doc_type,
            )
    return policy


def build_in_budget_policy(effective_from: date) -> ApprovalPolicy:
    return build_policy("TRONG_NGAN_SACH", "requisition", IN_BUDGET_RULES, effective_from=effective_from)


def build_out_budget_policy(effective_from: date) -> ApprovalPolicy:
    return build_policy("NGOAI_NGAN_SACH", "budget_change", OUT_BUDGET_RULES, effective_from=effective_from)
