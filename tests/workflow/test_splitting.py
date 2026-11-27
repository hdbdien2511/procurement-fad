from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import OrgUnit
from apps.budget.models import BudgetLine, CostCode, Location, Project
from apps.requisitions.models import Requisition, RequisitionFunding
from apps.vendors.models import Vendor
from apps.workflow.splitting import split_warnings


@pytest.fixture
def line(org):
    cc = CostCode.objects.create(code="IT_1.1", name="Thiết bị CNTT", budget_unit=org.bu_itd)
    pj = Project.objects.create(code="BAU_ITD", name="BAU ITD", begin_year=2026, budget_unit=org.bu_itd)
    loc = Location.objects.create(code="HSC", name="TP.HCM")
    return BudgetLine.objects.create(year=2026, budget_unit=org.bu_itd, cost_code=cc, project=pj, location=loc)


@pytest.fixture
def vendor(db):
    return Vendor.objects.create(code="V1", tax_code="0101", name="NCC A", status="ACTIVE")


def make(org, *, number, vendor=None, line=None, unit=None, days_ago=0, status="IN_APPROVAL", amount=80_000_000):
    req = Requisition.objects.create(
        number=number, title="Mua thiết bị", requester=org.requester, requester_unit=unit or org.req_unit,
        procurement_type="BAU", currency="VND", total_original=Decimal(amount), total_vnd=Decimal(amount),
        service_start=date(2026, 1, 1), months=1, vendor=vendor, status=status, created_by=org.requester,
    )
    Requisition.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    if line is not None:
        RequisitionFunding.objects.create(requisition=req, budget_line=line, amount_vnd=Decimal(amount))
    req.refresh_from_db()
    return req


def test_split_warning(db, org, in_budget_policy, vendor):
    # 3 tờ trình 80tr cùng NCC trong 30 ngày, rule max 199_999_999 → 1 cảnh báo nêu 2 số tờ trình kia
    make(org, number="TT-2026-00001", vendor=vendor, days_ago=20)
    make(org, number="TT-2026-00002", vendor=vendor, days_ago=5)
    make(org, number="TT-2026-00009", vendor=vendor, days_ago=45)  # ngoài cửa sổ 30 ngày
    current = make(org, number="TT-2026-00003", vendor=vendor)
    warnings = split_warnings(current)
    assert len(warnings) == 1
    assert "TT-2026-00001" in warnings[0] and "TT-2026-00002" in warnings[0]
    assert "TT-2026-00009" not in warnings[0] and "TT-2026-00003" not in warnings[0]


def test_split_warning_by_cost_code(db, org, in_budget_policy, line):
    make(org, number="TT-2026-00001", line=line, days_ago=3)
    make(org, number="TT-2026-00002", line=line, days_ago=2)
    assert len(split_warnings(make(org, number="TT-2026-00003", line=line))) == 1


def test_no_warning_below_limit_other_unit_or_inactive(db, org, in_budget_policy, vendor):
    other_unit = OrgUnit.objects.create(code="KHAC", name="Phòng khác")
    make(org, number="TT-2026-00001", vendor=vendor, unit=other_unit)
    make(org, number="TT-2026-00002", vendor=vendor, status="CANCELLED")
    make(org, number="TT-2026-00004", vendor=vendor, status="REJECTED")
    current = make(org, number="TT-2026-00003", vendor=vendor)
    assert split_warnings(current) == []


def test_no_warning_when_matched_rule_has_no_limit(db, org, in_budget_policy, vendor):
    make(org, number="TT-2026-00001", vendor=vendor, amount=1_000_000_000)
    current = make(org, number="TT-2026-00002", vendor=vendor, amount=2_500_000_000)  # rule ">2ty"
    assert split_warnings(current) == []
