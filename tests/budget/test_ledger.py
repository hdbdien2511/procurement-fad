import threading
from datetime import date
from decimal import Decimal

import django.db
import pytest
from django.db import connection

from apps.audit.models import AuditEvent
from apps.budget.ledger import (
    InsufficientBudget,
    balance,
    post,
    release,
    reserve,
)
from apps.budget.models import (
    ACCRUAL,
    EXPENSE,
    FORECAST,
    ORIGINAL,
    RELEASE,
    RESERVE,
    REVERSAL,
    BudgetEntry,
    BudgetLine,
)
from tests.testapp.models import Dummy


def test_balance_and_reserve(line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("120000000"), source=None, user=user)
    warnings = reserve([(line_2026, Decimal("30000000"))], start=date(2026, 1, 1), months=1, source=req, user=user)
    assert warnings == []
    b = balance(line_2026)
    assert (b.budget, b.reserved, b.available) == (
        Decimal("120000000"),
        Decimal("30000000"),
        Decimal("90000000"),
    )
    release(req, user)
    assert balance(line_2026).reserved == 0
    assert balance(line_2026).available == Decimal("120000000")


def test_entry_records_source(line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("100"), source=None, user=user)
    reserve([(line_2026, Decimal("100"))], start=date(2026, 1, 1), months=1, source=req, user=user)
    e = BudgetEntry.objects.get(kind=RESERVE)
    assert (e.source_type, e.source_id) == ("testapp.dummy", str(req.pk))
    assert BudgetEntry.objects.get(kind=ORIGINAL).source_type == ""


def test_balance_through_and_expense(line_2026, user, req):
    for m in range(1, 13):
        post(line_2026, date(2026, m, 1), ORIGINAL, Decimal("10000000"), source=None, user=user)
    post(line_2026, date(2026, 2, 1), EXPENSE, Decimal("4000000"), source=req, user=user)
    post(line_2026, date(2026, 3, 1), ACCRUAL, Decimal("2000000"), source=req, user=user)
    post(line_2026, date(2026, 4, 1), REVERSAL, Decimal("-2000000"), source=req, user=user)
    b = balance(line_2026, through=date(2026, 3, 1))
    assert (b.budget, b.expensed, b.available) == (
        Decimal("30000000"),
        Decimal("6000000"),
        Decimal("24000000"),
    )
    full = balance(line_2026)
    assert (full.budget, full.expensed, full.available) == (
        Decimal("120000000"),
        Decimal("4000000"),
        Decimal("116000000"),
    )


def test_forecast_not_deducted(line_2026, user):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("100000000"), source=None, user=user)
    post(line_2026, date(2026, 6, 1), FORECAST, Decimal("50000000"), source=None, user=user)
    b = balance(line_2026)
    assert b.forecast == Decimal("50000000")
    assert b.available == Decimal("100000000")


def test_insufficient_budget_lists_shortfall(line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("10000000"), source=None, user=user)
    with pytest.raises(InsufficientBudget) as e:
        reserve([(line_2026, Decimal("15000000"))], start=date(2026, 1, 1), months=1, source=req, user=user)
    assert e.value.shortfalls == [(line_2026, Decimal("5000000"))]
    assert "5.000.000" in str(e.value)
    assert not BudgetEntry.objects.filter(kind=RESERVE).exists()


def test_insufficient_checks_all_lines_before_posting(dims, line_2026, user, req):
    from apps.budget.models import Location

    bu, cc, pj, _ = dims
    hnb = Location.objects.create(code="HNB", name="Hà Nội")
    line_hn = BudgetLine.objects.create(year=2026, budget_unit=bu, cost_code=cc, project=pj, location=hnb)
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("100"), source=None, user=user)
    post(line_hn, date(2026, 1, 1), ORIGINAL, Decimal("100"), source=None, user=user)
    with pytest.raises(InsufficientBudget) as e:
        reserve(
            [(line_2026, Decimal("50")), (line_hn, Decimal("150"))],
            start=date(2026, 1, 1),
            months=1,
            source=req,
            user=user,
        )
    assert e.value.shortfalls == [(line_hn, Decimal("50"))]
    assert not BudgetEntry.objects.filter(kind=RESERVE).exists()


def test_sufficiency_is_whole_year_not_per_month(line_2026, user, req):
    # Toàn bộ ngân sách năm đặt ở tháng 1; giữ chỗ rải tháng 6–12 vẫn được phép.
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("70000000"), source=None, user=user)
    reserve([(line_2026, Decimal("70000000"))], start=date(2026, 6, 1), months=7, source=req, user=user)
    assert balance(line_2026).available == 0


def test_next_year_periods_warn_not_block(dims, line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("12000000"), source=None, user=user)
    warnings = reserve(
        [(line_2026, Decimal("24000000"))], start=date(2026, 1, 1), months=24, source=req, user=user
    )
    line_2027 = BudgetLine.objects.get(year=2027, cost_code=line_2026.cost_code)
    assert (line_2027.budget_unit, line_2027.project, line_2027.location) == (
        line_2026.budget_unit,
        line_2026.project,
        line_2026.location,
    )
    assert balance(line_2026).reserved == Decimal("12000000")
    assert balance(line_2027).reserved == Decimal("12000000")
    assert warnings == [
        "Năm 2027 chưa có ngân sách cho dòng AD_2.1.7D/BAU_ADM/HSC: "
        "đã ghi giữ chỗ 12.000.000 đ, cần bổ sung ngân sách."
    ]
    # release mirrors both years
    release(req, user)
    assert balance(line_2026).reserved == 0
    assert balance(line_2027).reserved == 0


def test_next_year_with_budget_no_warning(dims, line_2026, user, req):
    bu, cc, pj, loc = dims
    line_2027 = BudgetLine.objects.create(year=2027, budget_unit=bu, cost_code=cc, project=pj, location=loc)
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("12000000"), source=None, user=user)
    post(line_2027, date(2027, 1, 1), ORIGINAL, Decimal("12000000"), source=None, user=user)
    warnings = reserve(
        [(line_2026, Decimal("24000000"))], start=date(2026, 1, 1), months=24, source=req, user=user
    )
    assert warnings == []


def test_release_idempotent_and_mirrors_periods(line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("300"), source=None, user=user)
    reserve([(line_2026, Decimal("300"))], start=date(2026, 1, 1), months=3, source=req, user=user)
    release(req, user)
    rel = list(BudgetEntry.objects.filter(kind=RELEASE).order_by("period").values_list("period", "amount"))
    assert rel == [
        (date(2026, 1, 1), Decimal("-100")),
        (date(2026, 2, 1), Decimal("-100")),
        (date(2026, 3, 1), Decimal("-100")),
    ]
    release(req, user)
    assert BudgetEntry.objects.filter(kind=RELEASE).count() == 3


def test_release_only_touches_own_source(line_2026, user, req):
    other = Dummy.objects.create(owner=user)
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("300"), source=None, user=user)
    reserve([(line_2026, Decimal("100"))], start=date(2026, 1, 1), months=1, source=req, user=user)
    reserve([(line_2026, Decimal("50"))], start=date(2026, 1, 1), months=1, source=other, user=user)
    release(req, user)
    assert balance(line_2026).reserved == Decimal("50")


@pytest.mark.parametrize(
    "kind,amount",
    [(RELEASE, "100"), (REVERSAL, "1"), (RESERVE, "-1"), (EXPENSE, "-1"), (ORIGINAL, "-5"), (FORECAST, "-5")],
)
def test_post_validates_sign(line_2026, user, kind, amount):
    with pytest.raises(ValueError):
        post(line_2026, date(2026, 1, 1), kind, Decimal(amount), source=None, user=user)


def test_post_validates_period(line_2026, user):
    with pytest.raises(ValueError):
        post(line_2026, date(2026, 1, 2), ORIGINAL, Decimal("1"), source=None, user=user)


def test_post_rejects_unknown_kind(line_2026, user):
    with pytest.raises(ValueError):
        post(line_2026, date(2026, 1, 1), "BOGUS", Decimal("1"), source=None, user=user)


def test_audit_records(line_2026, user, req):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("300"), source=None, user=user)
    assert AuditEvent.objects.filter(action="budget.entry_posted").count() == 1
    reserve([(line_2026, Decimal("300"))], start=date(2026, 1, 1), months=3, source=req, user=user)
    ev = AuditEvent.objects.get(action="budget.reserved")
    assert ev.object_type == "testapp.dummy" and ev.object_id == str(req.pk)
    assert len(ev.changes["entries"]) == 3
    release(req, user)
    assert AuditEvent.objects.filter(action="budget.released").count() == 1
    # reserve/release không ghi thêm entry_posted riêng lẻ
    assert AuditEvent.objects.filter(action="budget.entry_posted").count() == 1


@pytest.fixture
def entry(line_2026, user):
    return post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("1000"), source=None, user=user)


def test_budget_entry_append_only(entry):
    with pytest.raises(django.db.ProgrammingError, match="append-only"):
        BudgetEntry.objects.filter(pk=entry.pk).update(amount=0)


def test_budget_entry_no_delete_db(entry):
    with pytest.raises(django.db.ProgrammingError, match="append-only"):
        with connection.cursor() as cur:
            cur.execute("DELETE FROM budget_budgetentry WHERE id = %s", [entry.pk])


def test_budget_entry_model_guards(entry):
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()


def test_str_readable(line_2026):
    assert str(line_2026) == "2026 · ADM · AD_2.1.7D · BAU_ADM · HSC"


@pytest.mark.django_db(transaction=True)
def test_concurrent_reserve_cannot_overspend(line_2026, user):
    post(line_2026, date(2026, 1, 1), ORIGINAL, Decimal("100000000"), source=None, user=user)
    sources = [Dummy.objects.create(owner=user) for _ in range(2)]
    barrier = threading.Barrier(2)
    results = []

    def worker(src):
        try:
            barrier.wait()
            reserve([(line_2026, Decimal("60000000"))], start=date(2026, 1, 1), months=1, source=src, user=user)
            results.append("ok")
        except InsufficientBudget:
            results.append("insufficient")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(s,)) for s in sources]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["insufficient", "ok"]
    assert balance(line_2026).reserved == Decimal("60000000")
