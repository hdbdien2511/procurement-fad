from django.db import transaction

from .models import NumberSequence


@transaction.atomic
def next_number(prefix: str, year: int) -> str:
    NumberSequence.objects.get_or_create(prefix=prefix, year=year)
    seq = NumberSequence.objects.select_for_update().get(prefix=prefix, year=year)
    seq.last += 1
    seq.save(update_fields=["last"])
    return f"{prefix}-{year}-{seq.last:05d}"
