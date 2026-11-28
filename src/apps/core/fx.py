from datetime import date
from decimal import Decimal

from .models import ExchangeRate
from .money import round_vnd


class MissingRate(Exception):
    def __init__(self, currency: str, on: date):
        self.currency = currency
        self.on = on
        super().__init__(f"Chưa có tỷ giá {currency} tại ngày {on:%d/%m/%Y}.")


def to_vnd(amount: Decimal, currency: str, on: date) -> tuple[Decimal, Decimal]:
    cur = (currency or "").strip().upper()
    if cur == "VND":
        return round_vnd(amount), Decimal("1")
    row = ExchangeRate.objects.filter(currency=cur, date__lte=on).order_by("-date").first()
    if row is None:
        raise MissingRate(cur, on)
    return round_vnd(amount * row.rate), row.rate
