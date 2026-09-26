"""Expiry reminders: warranties, licenses, contracts, domains and anything
else a module marks with ``Field(expires=True)``.

A record is due when such a date falls within the reminder window (an admin
setting, 90 days by default) either side of today, unless the record is
archived, deleted, or in one of its type's ``inactive`` statuses. The
``reminders`` table holds what is due: the worker's hourly pass brings it up
to date as the days go by, and every save of a record updates that record's
rows at once, so an edited date shows on the dashboard straight away.
"""
from datetime import date, timedelta

from ..models import db, int_setting
from ..registry import current as registry
from .models import Entity, Reminder

DEFAULT_DAYS = 90


def window() -> int:
    return int_setting("reminder_days", DEFAULT_DAYS)


def bounds() -> tuple[date, date]:
    today, days = date.today(), timedelta(days=window())
    return today - days, today + days


def dated_fields(etype) -> list:
    return [f for f in etype.fields if f.expires and f.kind == "date" and etype.detail is not None]


def _wanted(entity: Entity) -> dict[str, date]:
    etype = registry().type(entity.type)
    if (etype is None or entity.deleted_at is not None or entity.archived
            or entity.status in etype.inactive or not dated_fields(etype)):
        return {}
    detail = db.session.get(etype.detail, entity.id)
    low, high = bounds()
    out = {}
    for f in dated_fields(etype):
        value = getattr(detail, f.key, None) if detail is not None else None
        if value is not None and low <= value <= high:
            out[f.key] = value
    return out


def _sync(entity_id: int, wanted: dict[str, date], have: list[Reminder]) -> int:
    changed = 0
    for r in have:
        if r.field not in wanted:
            db.session.delete(r)
            changed += 1
        elif r.due != wanted[r.field]:
            r.due = wanted[r.field]
            changed += 1
    known = {r.field for r in have}
    for key, due in wanted.items():
        if key not in known:
            db.session.add(Reminder(entity_id=entity_id, field=key, due=due))
            changed += 1
    return changed


def refresh(entity: Entity) -> None:
    """Bring one record's reminders up to date, after it was saved."""
    if entity.id is None:
        return
    _sync(entity.id, _wanted(entity), Reminder.query.filter_by(entity_id=entity.id).all())


def refresh_all() -> int:
    """Every record's, for the worker and after the window changes.
    Returns how many rows changed."""
    reg = registry()
    low, high = bounds()
    wanted: dict[int, dict[str, date]] = {}
    for etype in reg.types.values():
        fields = dated_fields(etype)
        if not fields:
            continue
        for f in fields:
            column = getattr(etype.detail, f.key)
            rows = (db.session.query(Entity.id, column).join(etype.detail, etype.detail.entity_id == Entity.id)
                    .filter(Entity.type == etype.key, Entity.deleted_at.is_(None), Entity.archived.is_(False),
                            Entity.status.notin_(etype.inactive), column >= low, column <= high))
            for entity_id, due in rows:
                wanted.setdefault(entity_id, {})[f.key] = due
    have: dict[int, list[Reminder]] = {}
    for r in Reminder.query:
        have.setdefault(r.entity_id, []).append(r)
    changed = 0
    for entity_id in set(wanted) | set(have):
        changed += _sync(entity_id, wanted.get(entity_id, {}), have.get(entity_id, []))
    return changed


def due() -> list[dict]:
    """What is due, soonest first: {"entity", "etype", "field", "due", "days"}
    (days is negative once the date has passed). Only turned-on modules."""
    reg = registry()
    keys = reg.enabled_type_keys()
    rows = (Reminder.query.join(Entity, Entity.id == Reminder.entity_id)
            .filter(Entity.type.in_(keys), Entity.deleted_at.is_(None)).order_by(Reminder.due, Entity.name).all())
    today = date.today()
    out = []
    for r in rows:
        etype = reg.type(r.entity.type)
        f = next((f for f in etype.fields if f.key == r.field), None)
        if f is None:
            continue
        out.append({"entity": r.entity, "etype": etype, "field": f, "due": r.due, "days": (r.due - today).days})
    return out


def count() -> int:
    keys = registry().enabled_type_keys()
    return (Reminder.query.join(Entity, Entity.id == Reminder.entity_id)
            .filter(Entity.type.in_(keys), Entity.deleted_at.is_(None)).count())


def ending_within(query, detail, column, past: bool = False):
    """A sidebar filter: records whose ``column`` falls within the window
    ahead, and with ``past`` also the window behind (renewals that were
    missed). The modules' "ending soon" filters are this."""
    low, high = bounds()
    ids = db.session.query(detail.entity_id).filter(column >= (low if past else date.today()), column <= high)
    return query.filter(Entity.id.in_(ids))
