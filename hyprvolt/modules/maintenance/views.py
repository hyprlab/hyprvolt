"""Maintenance's checks, tabs, filters and widget.

A window's phase (coming, under way, over) comes from its times and the
clock, not its status: the status says what people decided (planned, done,
canceled). What a window takes down is what it affects plus everything that
depends on those, walked through the core's relations; the "affects" link
itself carries no dependency, so a window never shows up in what a server
needs.
"""
from datetime import timedelta

from flask import render_template

from hyprvolt.core import present, relations
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db, utcnow

from .models import MaintenanceDetail

WINDOW_STATUSES = (("planned", "Planned"), ("done", "Done"), ("canceled", "Canceled"))
CHANGE_STATUSES = (("done", "Done"), ("planned", "Planned"), ("failed", "Failed"), ("rolled_back", "Rolled back"))
IMPACTS = (("outage", "Outage"), ("degraded", "Degraded"), ("none", "No interruption"))
KINDS = (("config", "Configuration"), ("upgrade", "Upgrade"), ("install", "New install"), ("hardware", "Hardware"),
         ("fix", "Fix"), ("removal", "Removal"), ("other", "Other"))
TROUBLE = ("failed", "rolled_back")
#: How far ahead the dashboard looks, and how far back for changes.
AHEAD = timedelta(days=30)
RECENT = timedelta(days=30)


def _detail(entity_id) -> MaintenanceDetail | None:
    return db.session.get(MaintenanceDetail, entity_id)


# ———— Checks ————

def check_window(entity: Entity, d) -> None:
    if d is not None and d.starts and d.ends and d.ends <= d.starts:
        raise Invalid("A window must end after it starts.")


def check_change(entity: Entity, d) -> None:
    """A change with no time is one made now."""
    if d is not None and d.at is None:
        d.at = utcnow().replace(second=0, microsecond=0)


# ———— What a window touches ————

def affected(entity: Entity) -> list[Entity]:
    ids = [r.target_id for r in Relationship.query.filter_by(kind="affects", source_id=entity.id)]
    return Entity.live().filter(Entity.id.in_(ids)).order_by(Entity.name).all() if ids else []


def knock_on(direct: list[Entity]) -> list[Entity]:
    """What goes down with ``direct``: their dependents, each once, without
    those already listed."""
    seen = {e.id for e in direct}
    out = []

    def visit(nodes):
        for n in nodes:
            e = n["entity"]
            if e.id not in seen and e.deleted_at is None:
                seen.add(e.id)
                out.append(e)
            visit(n["children"])
    for e in direct:
        visit(relations.walk(e, "dependents"))
    return sorted(out, key=lambda e: e.name.lower())


def phase(d: MaintenanceDetail | None, now=None) -> str:
    """"coming", "now" or "over"; "" without times."""
    if d is None or not d.starts or not d.ends:
        return ""
    now = now or utcnow()
    return "coming" if now < d.starts else ("now" if now <= d.ends else "over")


def duration(d: MaintenanceDetail) -> str:
    minutes = int((d.ends - d.starts).total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((days, "day"), (hours, "hour"), (minutes, "minute")) if n]
    return " ".join(parts) or "no time"


# ———— Tabs ————

def impact_tab(entity: Entity) -> str:
    d = _detail(entity.id)
    direct = affected(entity)
    links = {r.target_id: r.id for r in Relationship.query.filter_by(kind="affects", source_id=entity.id)}
    window = entity.type == "maintenance"
    also = knock_on(direct) if window and d and d.impact != "none" else []
    changes = []
    if window:
        ids = db.session.query(MaintenanceDetail.entity_id).filter(MaintenanceDetail.window == entity.id)
        changes = present.views(Entity.live().filter(Entity.id.in_(ids)).all())
    return render_template("maintenance/impact.html", entity=entity, d=d, window=window, phase=phase(d),
                           length=duration(d) if window and d and d.starts and d.ends else "",
                           direct=present.views(direct), links=links, also=present.views(also), changes=changes,
                           impacts=dict(IMPACTS))


def _linked_from(entity: Entity, type_key: str) -> list[Entity]:
    ids = [r.source_id for r in Relationship.query.filter_by(kind="affects", target_id=entity.id)]
    if not ids:
        return []
    return Entity.live().filter(Entity.id.in_(ids), Entity.type == type_key).all()


def on_record(entity: Entity) -> bool:
    """Every record but windows and changes has a Changes tab, so the first
    change can be recorded from it."""
    return entity.type not in ("maintenance", "change")


def record_tab(entity: Entity) -> str:
    """A record's windows, the coming ones first, and its change log."""
    windows = _linked_from(entity, "maintenance")
    details = {w.id: _detail(w.id) for w in windows}
    now = utcnow()
    ahead = [w for w in windows if phase(details[w.id], now) in ("coming", "now") and w.status == "planned"]
    ahead.sort(key=lambda w: details[w.id].starts)
    changes = _linked_from(entity, "change")
    at = {c.id: getattr(_detail(c.id), "at", None) for c in changes}
    changes.sort(key=lambda c: at[c.id] or c.created_at, reverse=True)
    past = [w for w in windows if w not in ahead]
    past.sort(key=lambda w: details[w.id].starts or w.created_at, reverse=True)
    return render_template("maintenance/record.html", entity=entity, ahead=present.views(ahead),
                           past=present.views(past), changes=present.views(changes), details=details,
                           at=at, now=now)


def record_count(entity: Entity):
    return len(_linked_from(entity, "maintenance")) + len(_linked_from(entity, "change")) or None


# ———— Filters ————

def _windows(query):
    return query.filter(Entity.type == "maintenance", Entity.status == "planned")


def upcoming(query):
    ids = db.session.query(MaintenanceDetail.entity_id).filter(MaintenanceDetail.ends >= utcnow())
    return _windows(query).filter(Entity.id.in_(ids))


def under_way(query):
    now = utcnow()
    ids = db.session.query(MaintenanceDetail.entity_id).filter(MaintenanceDetail.starts <= now,
                                                               MaintenanceDetail.ends >= now)
    return _windows(query).filter(Entity.id.in_(ids))


def recent_changes(query):
    ids = db.session.query(MaintenanceDetail.entity_id).filter(MaintenanceDetail.at >= utcnow() - RECENT)
    return query.filter(Entity.type == "change", Entity.id.in_(ids))


def trouble(query):
    return query.filter(Entity.type == "change", Entity.status.in_(TROUBLE))


# ———— The widget ————

def widget() -> str:
    now = utcnow()
    windows = (Entity.live().join(MaintenanceDetail, MaintenanceDetail.entity_id == Entity.id)
               .filter(Entity.type == "maintenance", Entity.status == "planned", Entity.archived.is_(False),
                       MaintenanceDetail.ends >= now, MaintenanceDetail.starts <= now + AHEAD)
               .order_by(MaintenanceDetail.starts).limit(5).all())
    changes = (Entity.live().join(MaintenanceDetail, MaintenanceDetail.entity_id == Entity.id)
               .filter(Entity.type == "change", MaintenanceDetail.at >= now - timedelta(days=7))
               .order_by(MaintenanceDetail.at.desc()).limit(5).all())
    details = {e.id: _detail(e.id) for e in windows + changes}
    return render_template("maintenance/widget.html", windows=present.views(windows), changes=present.views(changes),
                           details=details, now=now, days=AHEAD.days)
