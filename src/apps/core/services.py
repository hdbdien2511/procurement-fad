from django.db import transaction

from apps.audit.service import diff, record

from .models import Setting

DEFAULTS = {
    "split_window_days": 30,
    "annual_fixed_cost_vnd": 0,
    "cumulative_scope": "COMPANY",
    "max_upload_mb": 25,
}

_MISSING = object()


def get_setting(key, default=_MISSING):
    row = Setting.objects.filter(key=key).first()
    if row is not None:
        return row.value
    if default is not _MISSING:
        return default
    return DEFAULTS.get(key)


@transaction.atomic
def set_setting(key, value, actor):
    row = Setting.objects.select_for_update().filter(key=key).first()
    before = row.value if row is not None else DEFAULTS.get(key)
    if row is None:
        row = Setting.objects.create(key=key, value=value)
    else:
        row.value = value
        row.save(update_fields=["value"])
    record("setting.changed", row, actor=actor, changes=diff({key: before}, {key: value}))
    return row
