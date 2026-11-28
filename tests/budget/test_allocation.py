from datetime import date
from decimal import Decimal

import pytest

from apps.budget.allocation import allocate


def test_allocate_remainder_to_last():
    assert allocate(Decimal("100000000"), date(2026, 1, 1), 3) == [
        (date(2026, 1, 1), Decimal("33333333")),
        (date(2026, 2, 1), Decimal("33333333")),
        (date(2026, 3, 1), Decimal("33333334")),
    ]


def test_allocate_crosses_year():
    rows = allocate(Decimal("1200"), date(2026, 11, 1), 4)
    assert [p for p, _ in rows] == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]
    assert [a for _, a in rows] == [Decimal("300")] * 4


def test_allocate_once_off():
    assert allocate(Decimal("1500000.6"), date(2026, 5, 1), 1) == [(date(2026, 5, 1), Decimal("1500001"))]


def test_allocate_sum_equals_rounded_total():
    rows = allocate(Decimal("1000"), date(2026, 1, 1), 7)
    assert sum(a for _, a in rows) == Decimal("1000")
    assert [a for _, a in rows] == [Decimal("142")] * 6 + [Decimal("148")]


def test_allocate_tiny_amount_never_negative():
    assert [a for _, a in allocate(Decimal("2"), date(2026, 1, 1), 4)] == [0, 0, 0, Decimal("2")]


@pytest.mark.parametrize("months", [0, -1])
def test_allocate_rejects_non_positive_months(months):
    with pytest.raises(ValueError):
        allocate(Decimal("100"), date(2026, 1, 1), months)


def test_allocate_rejects_mid_month_start():
    with pytest.raises(ValueError):
        allocate(Decimal("100"), date(2026, 1, 15), 2)
