from datetime import date
from decimal import Decimal

import pytest

from apps.budget.ledger import post
from apps.budget.models import ORIGINAL, BudgetLine, CostCode, Project
from tests.requisitions.conftest import budget, frozen_today  # noqa: F401  (fixtures)
from tests.workflow.conftest import (  # noqa: F401  (fixtures)
    grant,
    in_budget_policy,
    org,
    out_budget_policy,
    past,
    requester,
)


@pytest.fixture
def adm_line(org, budget):
    """Dòng ngân sách 2026 do ADM quản lý, ngân sách gốc 100tr (tháng 1)."""
    cc = CostCode.objects.create(code="ADM_1.1", name="Văn phòng phẩm", budget_unit=org.bu_adm)
    pj = Project.objects.create(code="BAU_ADM", name="BAU ADM", begin_year=2026, budget_unit=org.bu_adm)
    line = BudgetLine.objects.create(
        year=2026, budget_unit=org.bu_adm, cost_code=cc, project=pj, location=budget.line.location
    )
    post(line, date(2026, 1, 1), ORIGINAL, Decimal("100000000"), source=None, user=budget.admin)
    return line
