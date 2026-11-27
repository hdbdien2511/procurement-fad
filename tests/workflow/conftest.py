from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts import roles as R
from apps.accounts.models import Role
from tests.factories import OrgUnitFactory, UserFactory
from tests.testapp.models import Dummy
from tests.workflow.policies import build_in_budget_policy, build_out_budget_policy


def grant(user, role_code, org_unit=None):
    # Bảng Role có thể đã bị flush bởi một test transaction=True chạy trước → đảm bảo tồn tại.
    Role.objects.get_or_create(code=role_code, defaults={"name": R.ROLE_NAMES[role_code]})
    R.assign(user, role_code, org_unit)
    return user


def first_task(instance):
    return instance.tasks.filter(status="PENDING").order_by("seq", "pk").first()


def task_of(instance, kind, **filters):
    return instance.tasks.get(kind=kind, **filters)


@pytest.fixture
def past():
    return timezone.localdate() - timedelta(days=30)


@pytest.fixture
def in_budget_policy(db, past):
    return build_in_budget_policy(past)


@pytest.fixture
def out_budget_policy(db, past):
    return build_out_budget_policy(past)


@pytest.fixture
def settings_fixed_cost_100ty(db):
    from apps.core.models import Setting

    Setting.objects.update_or_create(key="annual_fixed_cost_vnd", defaults={"value": 100_000_000_000})


@pytest.fixture
def org(db):
    """Đơn vị và người dùng giả cho các kịch bản luồng duyệt."""
    from apps.budget.models import BudgetUnit

    u = type("Org", (), {})()
    u.req_unit = OrgUnitFactory(code="DEMO-A")
    u.itd = OrgUnitFactory(code="ITD-DEMO")
    u.adm = OrgUnitFactory(code="ADM-DEMO")
    u.dti = OrgUnitFactory(code="DTI-DEMO")
    u.bu_itd = BudgetUnit.objects.create(code="ITD", name="CNTT", managing_org_unit=u.itd)
    u.bu_adm = BudgetUnit.objects.create(code="ADM", name="Hành chính", managing_org_unit=u.adm)
    u.requester = grant(UserFactory(username="requester", org_unit=u.req_unit), R.REQUESTER, u.req_unit)
    u.dept_head = grant(UserFactory(username="tp", org_unit=u.req_unit), R.DEPT_HEAD, u.req_unit)
    u.owner_itd = grant(UserFactory(username="owner_itd", org_unit=u.itd), R.BUDGET_OWNER, u.itd)
    u.owner_adm = grant(UserFactory(username="owner_adm", org_unit=u.adm), R.BUDGET_OWNER, u.adm)
    u.consultant = grant(UserFactory(username="dti", org_unit=u.dti), R.CONSULTANT, u.dti)
    u.fad = grant(UserFactory(username="fad"), R.FAD_PRECHECK)
    u.gddh = grant(UserFactory(username="gddh"), R.GDDH)
    u.bms = grant(UserFactory(username="bms"), R.BMS_SECRETARY)
    u.ceo = grant(UserFactory(username="ceo"), R.CEO)
    u.board = grant(UserFactory(username="hdqt"), R.BOARD_SECRETARY)
    u.sysadmin = grant(UserFactory(username="sysadmin", is_superuser=True, is_staff=True), R.SYS_ADMIN)
    return u


@pytest.fixture
def requester(org):
    return org.requester


@pytest.fixture
def make_req(org):
    def make(amount, *, consult=True, budget_units=None, created_by=None, cumulative=0):
        units = budget_units if budget_units is not None else [org.bu_itd, org.bu_adm]
        return Dummy.objects.create(
            owner=org.requester,
            unit=org.req_unit,
            created_by=created_by or org.requester,
            amount_vnd=Decimal(amount),
            budget_unit_ids=[b.pk for b in units],
            consult_unit_ids=[org.dti.pk] if consult else [],
            cumulative_vnd=Decimal(cumulative),
        )

    return make


@pytest.fixture
def req_two_units(in_budget_policy, make_req):
    return make_req(100_000_000)


@pytest.fixture
def running_instance(req_two_units, requester):
    from apps.workflow.engine import start

    return start(req_two_units, "requisition", requester)
