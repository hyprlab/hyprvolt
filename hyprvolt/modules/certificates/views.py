"""Certificates' tab, filters, live check and routes.

The live check connects to a certificate's "Check at" address and reads what
the server presents. When that is a different certificate from the one on
record (renewed, replaced, or checked for the first time), the record takes
its details through ``records``, so the history says what changed. The
worker checks each certificate about once a day.
"""
import logging
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import inspect

from hyprvolt.core import records, reminders
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db, utcnow
from hyprvolt.permissions import role

from . import tls
from .models import CertificateDetail

bp = Blueprint("certificates", __name__)
log = logging.getLogger(__name__)

#: A certificate that renews by itself is renewed about a month ahead, so
#: only one this close to its end needs a person.
LATE_DAYS = 21
#: How often the worker checks each certificate, and how many in one pass.
CHECK_EVERY = timedelta(hours=20)
CHECKS_PER_PASS = 20


def _detail(entity_id) -> CertificateDetail | None:
    return db.session.get(CertificateDetail, entity_id)


def lead(detail) -> int | None:
    """Days ahead to remind of the expiry: fewer for one that renews itself."""
    return LATE_DAYS if detail is not None and detail.auto_renew else None


def check_fields(entity: Entity, detail) -> None:
    """The type's check: a readable address. A new one is checked on the
    worker's next pass, and the last one's result no longer applies."""
    if detail is None:
        return
    if detail.endpoint:
        try:
            tls.endpoint(detail.endpoint)
        except tls.Unreadable as err:
            raise Invalid(str(err)) from None
    if inspect(detail).attrs.endpoint.history.has_changes():
        detail.checked_at = detail.check_error = None


# ———— Filters ————

def expiring(query):
    return reminders.ending_within(query.filter(Entity.type == "certificate", Entity.status == "active"),
                                   CertificateDetail, CertificateDetail.expires, past=True)


def check_failed(query):
    ids = db.session.query(CertificateDetail.entity_id).filter(CertificateDetail.check_error.isnot(None),
                                                               _has(CertificateDetail.endpoint))
    return query.filter(Entity.type == "certificate", Entity.id.in_(ids))


# ———— The tab ————

def check_tab(cert: Entity) -> str:
    d = _detail(cert.id)
    left = (d.expires - date.today()).days if d and d.expires else None
    return render_template("certificates/check.html", cert=cert, d=d, left=left, late=LATE_DAYS)


# ———— Reading a certificate ————

def apply(cert: Entity, found: dict, user=None) -> list[dict]:
    """Take a certificate's details into the record, unless it is the one
    already on record: then the record's own wording (an issuer written
    out by hand) stays."""
    d = records.detail_of(cert)
    if d is not None and d.fingerprint and d.fingerprint == found["fingerprint"]:
        return []
    return records.update(cert, {"fields": found}, user)


def read_live(d: CertificateDetail) -> tuple[dict | None, str]:
    """What the server at the record's address presents, or why it couldn't
    be read. Writes nothing: the network is slow, and the database waits
    for no one."""
    try:
        host, port = tls.endpoint(d.endpoint)
        return tls.details(tls.fetch(host, port)), ""
    except tls.Unreadable as err:
        return None, str(err)


def record_check(cert: Entity, d: CertificateDetail, found: dict | None, error: str, user=None) -> str:
    """Take what a check found into the record and note how it went.
    Returns "" or what went wrong."""
    if found is not None:
        try:
            with db.session.begin_nested():
                apply(cert, found, user)
        except Invalid as err:
            error = str(err)
    d.checked_at = utcnow()
    d.check_error = error[:300] or None
    return error


def _has(column):
    return column.isnot(None) & (column != "")


def check_due() -> int:
    """The worker's job: check the certificates not checked lately, the
    longest waiting first, committing each on its own. Returns how many it
    checked."""
    cutoff = utcnow() - CHECK_EVERY
    ids = [e.id for e in Entity.live().join(CertificateDetail, CertificateDetail.entity_id == Entity.id)
           .filter(Entity.type == "certificate", Entity.archived.is_(False), Entity.status != "retired",
                   _has(CertificateDetail.endpoint),
                   CertificateDetail.checked_at.is_(None) | (CertificateDetail.checked_at < cutoff))
           .order_by(CertificateDetail.checked_at.is_not(None), CertificateDetail.checked_at)
           .limit(CHECKS_PER_PASS)]
    db.session.commit()
    for entity_id in ids:
        try:
            cert = records.live(entity_id)
            d = _detail(entity_id) if cert else None
            if d is None:
                continue
            found, error = read_live(d)
            record_check(cert, d, found, error)
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("checking certificate %s failed", entity_id)
    return len(ids)


# ———— Routes ————

def _certificate(entity_id) -> Entity:
    cert = records.live(entity_id)
    if cert is None or cert.type != "certificate":
        abort(404, description="There is no such certificate.")
    return cert


def _expiry_message(cert: Entity) -> str:
    d = records.detail_of(cert)
    return f"It expires on {d.expires.isoformat()}." if d and d.expires else "Read."


@bp.route("/<int:entity_id>/check", methods=["POST"])
@role("editor")
def check_now(entity_id):
    cert = _certificate(entity_id)
    d = records.detail_of(cert)
    if d is None or not d.endpoint:
        return jsonify(error="Give it an address in Check at first."), 400
    found, error = read_live(d)
    error = record_check(cert, d, found, error, current_user._get_current_object())
    db.session.commit()
    # A failed check is still a check: the tab shows why, so the answer is
    # not an error; a script reads ``read`` and ``problem``.
    return jsonify(ok=True, read=not error, problem=error or None)


@bp.route("/<int:entity_id>/read", methods=["POST"])
@role("editor")
def read_pem(entity_id):
    cert = _certificate(entity_id)
    data = request.get_json(silent=True)
    text = data.get("pem") if isinstance(data, dict) else ""
    try:
        apply(cert, tls.details(tls.read(str(text or ""))), current_user._get_current_object())
    except (tls.Unreadable, Invalid) as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    return jsonify(ok=True, message="Certificate read. " + _expiry_message(cert))
