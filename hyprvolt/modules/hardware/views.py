"""Hardware's sidebar filters and dashboard widget: warranties about to end
and already over."""
from datetime import date, timedelta

from flask import render_template

from hyprvolt.core import present
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from .models import HardwareDetail

#: How far ahead "ending soon" looks. The dashboard's expiry window
#: (Phase 5) will make this a setting.
SOON_DAYS = 90
#: Statuses that no longer need a warranty.
GONE = ("retired", "disposed")


def _ids(*conditions):
    return db.session.query(HardwareDetail.entity_id).filter(*conditions)


def warranty_soon(query):
    today = date.today()
    return query.filter(Entity.status.notin_(GONE), Entity.id.in_(_ids(
        HardwareDetail.warranty_until >= today,
        HardwareDetail.warranty_until <= today + timedelta(days=SOON_DAYS))))


def warranty_over(query):
    return query.filter(Entity.status.notin_(GONE), Entity.id.in_(_ids(
        HardwareDetail.warranty_until < date.today())))


def warranty_widget() -> str:
    """What ends within the window, soonest first, then the most recently
    ended, so the card never reads as all clear when it isn't."""
    today = date.today()
    rows = (db.session.query(Entity, HardwareDetail.warranty_until)
            .join(HardwareDetail, HardwareDetail.entity_id == Entity.id)
            .filter(Entity.deleted_at.is_(None), Entity.archived.is_(False), Entity.status.notin_(GONE),
                    HardwareDetail.warranty_until.isnot(None),
                    HardwareDetail.warranty_until <= today + timedelta(days=SOON_DAYS))
            .order_by(HardwareDetail.warranty_until).all())
    soon = [(e, d, (d - today).days) for e, d in rows if d >= today]
    over = [(e, d, (today - d).days) for e, d in reversed(rows) if d < today]
    views = {v.id: v for v in present.views([e for e, _, _ in soon + over])}
    return render_template("hardware/warranty_widget.html", soon=[(views[e.id], d, n) for e, d, n in soon][:8],
                           over=[(views[e.id], d, n) for e, d, n in over][:5], n_over=len(over), days=SOON_DAYS)
