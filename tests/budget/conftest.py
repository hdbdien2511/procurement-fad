import pytest

from tests.factories import OrgUnitFactory, UserFactory
from tests.testapp.models import Dummy


@pytest.fixture
def dims(db):
    from apps.budget.models import BudgetUnit, CostCode, Location, Project

    bu = BudgetUnit.objects.create(code="ADM", name="Hành chính", managing_org_unit=OrgUnitFactory())
    cc = CostCode.objects.create(code="AD_2.1.7D", name="Thuê văn phòng", budget_unit=bu)
    pj = Project.objects.create(
        code="BAU_ADM", name="BAU ADM", workstream="BAU", begin_year=2026, budget_unit=bu
    )
    loc = Location.objects.create(code="HSC", name="TP.HCM")
    return bu, cc, pj, loc


@pytest.fixture
def line_2026(dims):
    from apps.budget.models import BudgetLine

    bu, cc, pj, loc = dims
    return BudgetLine.objects.create(year=2026, budget_unit=bu, cost_code=cc, project=pj, location=loc)


@pytest.fixture
def user(db):
    return UserFactory(username="fad")


@pytest.fixture
def req(user):
    return Dummy.objects.create(owner=user)
