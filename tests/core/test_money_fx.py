from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.template import Context, Template

from apps.core.fx import MissingRate, to_vnd
from apps.core.models import ExchangeRate
from apps.core.money import amount_in_words_vi, format_vnd, round_vnd
from apps.core.numbering import next_number


def test_to_vnd_rounds_half_up(db):
    ExchangeRate.objects.create(currency="USD", date=date(2026, 11, 1), rate=Decimal("25460.5000"))
    vnd, rate = to_vnd(Decimal("1234.56"), "USD", date(2026, 11, 27))
    assert rate == Decimal("25460.5000") and vnd == Decimal("31432515")


def test_to_vnd_uses_latest_rate_not_after_date(db):
    ExchangeRate.objects.create(currency="USD", date=date(2026, 11, 1), rate=Decimal("25000"))
    ExchangeRate.objects.create(currency="USD", date=date(2026, 11, 20), rate=Decimal("26000"))
    ExchangeRate.objects.create(currency="USD", date=date(2026, 12, 1), rate=Decimal("27000"))
    assert to_vnd(Decimal("1"), "USD", date(2026, 11, 25))[1] == Decimal("26000")
    assert to_vnd(Decimal("1"), "USD", date(2026, 11, 20))[1] == Decimal("26000")
    with pytest.raises(MissingRate):
        to_vnd(Decimal("1"), "USD", date(2026, 10, 1))


def test_to_vnd_vnd_and_normalization(db):
    assert to_vnd(Decimal("1000.5"), " vnd ", date(2026, 1, 1)) == (Decimal("1001"), Decimal("1"))
    ExchangeRate.objects.create(currency="EUR", date=date(2026, 1, 1), rate=Decimal("28000"))
    assert to_vnd(Decimal("2"), " eur", date(2026, 1, 2))[0] == Decimal("56000")


def test_missing_rate(db):
    with pytest.raises(MissingRate):
        to_vnd(Decimal("1"), "HKD", date(2026, 1, 1))


def test_exchange_rate_constraints(db):
    r = ExchangeRate(currency="usd", date=date(2026, 1, 1), rate=Decimal("25000"))
    r.save()
    r.refresh_from_db()
    assert r.currency == "USD"
    with pytest.raises(IntegrityError), transaction.atomic():
        ExchangeRate.objects.create(currency="USD", date=date(2026, 1, 1), rate=Decimal("1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        ExchangeRate.objects.create(currency="EUR", date=date(2026, 1, 1), rate=Decimal("0"))
    with pytest.raises(ValidationError):
        ExchangeRate(currency="US", date=date(2026, 1, 1), rate=Decimal("1")).full_clean()
    with pytest.raises(ValidationError):
        ExchangeRate(currency="EUR", date=date(2026, 1, 1), rate=Decimal("-1")).full_clean()


@pytest.mark.parametrize(
    "n,expected",
    [
        ("1250000", "Một triệu hai trăm năm mươi nghìn đồng"),
        ("2000000005", "Hai tỷ không trăm linh năm đồng"),
        ("0", "Không đồng"),
        ("21", "Hai mươi mốt đồng"),
        ("15", "Mười lăm đồng"),
        ("105", "Một trăm linh năm đồng"),
        ("1000001", "Một triệu không trăm linh một đồng"),
        ("1000000000000", "Một nghìn tỷ đồng"),
        ("-1500", "Âm một nghìn năm trăm đồng"),
        ("10", "Mười đồng"),
        ("25", "Hai mươi lăm đồng"),
        ("14", "Mười bốn đồng"),
        ("1000", "Một nghìn đồng"),
        ("100000", "Một trăm nghìn đồng"),
        ("1000000000000000", "Một triệu tỷ đồng"),
        ("0.5", "Một đồng"),
    ],
)
def test_amount_in_words(n, expected):
    assert amount_in_words_vi(Decimal(n)) == expected


def test_round_and_format_vnd():
    assert round_vnd(Decimal("2.5")) == Decimal("3")
    assert round_vnd(Decimal("-2.5")) == Decimal("-3")
    assert format_vnd(Decimal("-1234567")) == "-1.234.567"
    assert format_vnd(Decimal("1234567.5")) == "1.234.568"
    assert format_vnd(Decimal("0")) == "0"


def test_template_filters():
    out = Template("{% load vn %}{{ a|vnd }}|{{ a|bang_chu }}").render(Context({"a": Decimal("1250000")}))
    assert out == "1.250.000|Một triệu hai trăm năm mươi nghìn đồng"


def test_numbering_sequential(db):
    assert next_number("TT", 2026) == "TT-2026-00001"
    assert next_number("TT", 2026) == "TT-2026-00002"
    assert next_number("TT", 2027) == "TT-2027-00001"
    assert next_number("PO", 2026) == "PO-2026-00001"
