from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.workflow.engine import NoMatchingRule, NoPolicy, active_policy, select_rule
from apps.workflow.models import ApprovalPolicy, PolicyRule
from apps.workflow.sample_policies import IN_BUDGET_RULES, build_policy


# chính sách mẫu "Trong ngân sách" (spec mục 4): rule1 max 199_999_999, rule2 max 2_000_000_000, rule3 không max
@pytest.mark.parametrize("amount,label", [
    (199_999_999, "<200tr"), (200_000_000, "200tr-2ty"), (2_000_000_000, "200tr-2ty"), (2_000_000_001, ">2ty")])
def test_in_budget_rule_boundaries(db, in_budget_policy, amount, label):
    assert select_rule(in_budget_policy, {"amount_vnd": Decimal(amount)}, None).label == label


# chính sách "Ngoài ngân sách": A max 49_999_999 cap 200_000_000; B max 300_000_000 cap 2_000_000_000;
# C max 3_000_000_000 cap_pct 2; D catch-all
def test_cumulative_escalates(db, out_budget_policy, settings_fixed_cost_100ty):
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(10_000_000)}, Decimal(150_000_000)).label == "A"
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(10_000_000)}, Decimal(200_000_000)).label == "B"
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(400_000_000)}, Decimal(2_000_000_000)).label == "D"  # = 2% của 100 tỷ


def test_cap_pct_strictly_below(db, out_budget_policy, settings_fixed_cost_100ty):
    ctx = {"amount_vnd": Decimal(400_000_000)}
    assert select_rule(out_budget_policy, ctx, Decimal(1_999_999_999)).label == "C"


def test_amount_over_max_skips_rule_even_if_cumulative_low(db, out_budget_policy, settings_fixed_cost_100ty):
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(60_000_000)}, Decimal(60_000_000)).label == "B"


def test_cap_pct_with_zero_fixed_cost_never_matches(db, out_budget_policy):
    # annual_fixed_cost_vnd mặc định 0 → không luỹ kế nào < 0 → rule C bị bỏ qua
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(400_000_000)}, Decimal(1)).label == "D"


def test_no_matching_rule(db, past):
    policy = build_policy("X", "requisition", IN_BUDGET_RULES[:1], effective_from=past)
    with pytest.raises(NoMatchingRule):
        select_rule(policy, {"amount_vnd": Decimal(200_000_000)}, None)


def test_active_policy_picks_effective_highest_version(db, past):
    today = timezone.localdate()
    v1 = build_policy("P", "requisition", IN_BUDGET_RULES, effective_from=past)
    v2 = build_policy("P", "requisition", IN_BUDGET_RULES, effective_from=past, version=2)
    build_policy("P", "requisition", IN_BUDGET_RULES, effective_from=today + timedelta(days=1), version=3)
    inactive = build_policy("P", "requisition", IN_BUDGET_RULES, effective_from=today, version=4)
    ApprovalPolicy.objects.filter(pk=inactive.pk).update(is_active=False)
    assert active_policy("requisition") == v2
    ApprovalPolicy.objects.filter(pk=v2.pk).update(is_active=False)
    assert active_policy("requisition") == v1


def test_active_policy_prefers_later_effective_date(db, past):
    build_policy("P", "requisition", IN_BUDGET_RULES, effective_from=past, version=5)
    newer = build_policy("Q", "requisition", IN_BUDGET_RULES, effective_from=past + timedelta(days=1))
    assert active_policy("requisition") == newer


def test_no_policy(db, in_budget_policy):
    with pytest.raises(NoPolicy, match="Chưa có chính sách duyệt"):
        active_policy("budget_change")


def test_rules_checked_by_priority_not_creation_order(db, past):
    policy = ApprovalPolicy.objects.create(code="R", subject_kind="requisition", version=1, effective_from=past)
    PolicyRule.objects.create(policy=policy, priority=2, label="rộng", max_amount=None)
    PolicyRule.objects.create(policy=policy, priority=1, label="hẹp", max_amount=Decimal(100))
    assert select_rule(policy, {"amount_vnd": Decimal(100)}, None).label == "hẹp"
    assert select_rule(policy, {"amount_vnd": Decimal(101)}, None).label == "rộng"


def test_caps_ignored_when_no_cumulative(db, out_budget_policy, settings_fixed_cost_100ty):
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(10_000_000)}, None).label == "A"
