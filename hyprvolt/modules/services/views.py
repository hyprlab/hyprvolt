"""Services' sidebar filters and dashboard widget."""
from flask import render_template

from hyprvolt.core import present
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from .models import ServiceDetail

IMPORTANT = ("high", "critical")


def _important_ids():
    return db.session.query(ServiceDetail.entity_id).filter(ServiceDetail.criticality.in_(IMPORTANT))


def important(query):
    return query.filter(Entity.type == "service", Entity.id.in_(_important_ids()))


def not_running(query):
    return query.filter(Entity.type == "service", Entity.status.in_(("degraded", "down")))


def services_widget() -> str:
    """The services that matter most, and any that aren't running well."""
    rows = (Entity.live().filter(Entity.type == "service", Entity.archived.is_(False))
            .filter(Entity.id.in_(_important_ids()) | Entity.status.in_(("degraded", "down")))
            .order_by(Entity.name).all())
    order = {"down": 0, "degraded": 1}
    rows.sort(key=lambda e: (order.get(e.status, 2), e.name.lower()))
    return render_template("services/widget.html", rows=present.views(rows[:10]), more=max(len(rows) - 10, 0))
