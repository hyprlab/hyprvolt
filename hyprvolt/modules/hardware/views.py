"""Hardware's sidebar filters: warranties about to end and already over.
The window is the reminder window (core/reminders.py), an admin setting."""
from datetime import date

from hyprvolt.core import reminders
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from .models import HardwareDetail

#: Statuses that no longer need a warranty, or a reminder.
GONE = ("retired", "disposed")


def warranty_soon(query):
    return reminders.ending_within(query.filter(Entity.status.notin_(GONE)), HardwareDetail,
                                   HardwareDetail.warranty_until)


def warranty_over(query):
    ids = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.warranty_until < date.today())
    return query.filter(Entity.status.notin_(GONE), Entity.id.in_(ids))
