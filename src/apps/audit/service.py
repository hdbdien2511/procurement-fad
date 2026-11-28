import hashlib
import json
from datetime import timezone as dt_tz

from django.db import connection, transaction
from django.utils import timezone

from .context import audit_context
from .models import AuditEvent

GENESIS = "0" * 64
LOCK_KEY = 4242


def diff(before: dict, after: dict) -> dict:
    out = {}
    for k in before.keys() | after.keys():
        old, new = before.get(k), after.get(k)
        if old != new:
            out[k] = [old, new]
    return out


def compute_hash(occurred_at, actor_id, action, object_type, object_id, changes, prev_hash) -> str:
    payload = {
        "occurred_at": occurred_at.astimezone(dt_tz.utc).isoformat(),
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "changes": changes,
        "prev_hash": prev_hash,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record(action, obj=None, *, actor=None, changes=None) -> AuditEvent:
    ctx = audit_context.get() or {}
    if actor is None:
        actor = ctx.get("user")
    ip = ctx.get("ip")
    object_type = obj._meta.label_lower if obj is not None else ""
    object_id = str(obj.pk) if obj is not None else ""
    changes = changes or {}
    # chuẩn hoá qua JSON để hash khớp giá trị đọc lại từ DB
    changes = json.loads(json.dumps(changes, default=str))
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])
        last = AuditEvent.objects.order_by("-id").values_list("hash", flat=True).first()
        prev_hash = last or GENESIS
        now = timezone.now()
        actor_id = actor.pk if actor is not None else None
        event = AuditEvent(
            occurred_at=now,
            actor=actor,
            actor_label=actor.get_username() if actor is not None else "system",
            action=action,
            object_type=object_type,
            object_id=object_id,
            ip=ip,
            changes=changes,
            prev_hash=prev_hash,
            hash=compute_hash(now, actor_id, action, object_type, object_id, changes, prev_hash),
        )
        event.save()
    return event


def verify_chain() -> list[int]:
    bad = []
    prev = GENESIS
    for e in AuditEvent.objects.order_by("id").iterator():
        expected = compute_hash(
            e.occurred_at, e.actor_id, e.action, e.object_type, e.object_id, e.changes, e.prev_hash
        )
        if e.prev_hash != prev or e.hash != expected:
            bad.append(e.pk)
        prev = e.hash
    return bad
