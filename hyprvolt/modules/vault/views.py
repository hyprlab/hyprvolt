"""The vault's tab, routes, settings pane and purge.

Only accounts granted the secrets permission see any of it; changing a
secret also takes the editor role. Every reveal and copy is written to the
record's history, and a value is never sent anywhere but in answer to one.
API tokens can't reveal secrets: scripts get the list, never a value.
"""
from datetime import timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request
from flask_login import current_user

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import AuditLog, Entity
from hyprvolt.models import User, db, int_setting, utcnow
from hyprvolt.permissions import role

from . import crypto
from .models import KINDS, Secret

bp = Blueprint("vault", __name__)

MAX_VALUE = 20_000
ACTIONS = ("added a secret", "changed a secret", "removed a secret", "restored a secret", "revealed a secret")


def allowed(user=None) -> bool:
    user = user or current_user
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "can_see_secrets", False))


def _require(edit=False):
    if not allowed():
        abort(403, description="Only people an admin has given access to secrets can see them.")
    if edit and not current_user.can_edit:
        abort(403, description="Your account can only read. Ask an admin for the editor role to make changes.")


def secrets_of(entity_id) -> list[Secret]:
    return (Secret.query.filter_by(entity_id=entity_id, deleted_at=None)
            .order_by(Secret.name, Secret.id).all())


def _secret(secret_id, deleted_ok=False) -> Secret:
    s = db.session.get(Secret, secret_id)
    if s is None or (s.deleted_at is not None and not deleted_ok) or s.entity.deleted_at is not None:
        abort(404, description="There is no such secret.")
    return s


def _json(s: Secret) -> dict:
    return {"id": s.id, "entity_id": s.entity_id, "name": s.name, "kind": s.kind, "username": s.username,
            "url": s.url, "note": s.note, "updated_at": s.updated_at.isoformat() + "Z"}


def _audit(s: Secret, action: str, old: str = "", new: str = "") -> None:
    records.audit(s.entity, action, [{"field": "secret", "label": "Secret", "old": old, "new": new or s.name}])


def _clean(data, key, limit):
    return " ".join(str(data.get(key) or "").split())[:limit]


def _apply(s: Secret, data: dict, creating: bool) -> None:
    if creating or "name" in data:
        name = _clean(data, "name", 120)
        if not name:
            raise Invalid("Give the secret a name, such as Root password.")
        s.name = name
    if creating or "kind" in data:
        kind = data.get("kind") or "password"
        if kind not in dict(KINDS):
            raise Invalid("Choose what kind of secret it is.")
        s.kind = kind
    for key, limit in (("username", 200), ("url", 500), ("note", 500)):
        if creating or key in data:
            setattr(s, key, _clean(data, key, limit))
    value = data.get("value")
    if value not in (None, ""):
        value = str(value)
        if len(value) > MAX_VALUE:
            raise Invalid(f"A secret is limited to {MAX_VALUE:,} characters.")
        try:
            s.ciphertext = crypto.encrypt(value)
        except crypto.BadKey as err:
            raise Invalid(str(err)) from None
    elif creating:
        raise Invalid("Enter the secret itself.")
    s.updated_by_id = current_user.id
    s.updated_at = utcnow()


# ———— The tab ————

def tab(entity: Entity) -> str:
    return render_template("vault/tab.html", entity=entity, rows=secrets_of(entity.id), kinds=KINDS)


def count(entity: Entity):
    return len(secrets_of(entity.id)) or None


def shows(entity: Entity) -> bool:
    return allowed()


# ———— Routes ————

@bp.route("/entities/<int:entity_id>/secrets")
@role("viewer")
def secret_list(entity_id):
    """The secrets on a record, without their values."""
    _require()
    entity = records.live(entity_id)
    if entity is None:
        abort(404, description="There is no such record.")
    return jsonify(secrets=[_json(s) for s in secrets_of(entity.id)])


@bp.route("/entities/<int:entity_id>/secrets", methods=["POST"])
@role("viewer")
def secret_create(entity_id):
    _require(edit=True)
    entity = records.live(entity_id)
    if entity is None:
        abort(404, description="There is no such record.")
    s = Secret(entity_id=entity.id, created_by_id=current_user.id)
    try:
        _apply(s, request.get_json(silent=True) or {}, creating=True)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.add(s)
    db.session.flush()
    _audit(s, "added a secret")
    db.session.commit()
    return jsonify(ok=True, secret=_json(s))


@bp.route("/secrets/edit", methods=["POST"])
@role("viewer")
def secret_edit():
    """Change a secret, named as ``secret_id``. An empty value keeps the old one."""
    _require(edit=True)
    data = request.get_json(silent=True) or {}
    try:
        s = _secret(int(data.get("secret_id") or 0))
    except ValueError:
        abort(404, description="There is no such secret.")
    old = s.name
    try:
        _apply(s, {k: v for k, v in data.items() if k != "secret_id"}, creating=False)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    _audit(s, "changed a secret", old if old != s.name else "", s.name)
    db.session.commit()
    return jsonify(ok=True, secret=_json(s))


@bp.route("/secrets/<int:secret_id>/reveal", methods=["POST"])
@role("viewer")
def secret_reveal(secret_id):
    """The value, and a line in the record's history saying who asked."""
    _require()
    if g.get("api_token") is not None:
        abort(403, description="Secrets can't be read with an API token.")
    s = _secret(secret_id)
    try:
        value = crypto.decrypt(s.ciphertext)
    except (crypto.Unreadable, crypto.BadKey) as err:
        return jsonify(error=str(err)), 409
    _audit(s, "revealed a secret")
    db.session.commit()
    return jsonify(ok=True, value=value)


@bp.route("/secrets/<int:secret_id>/delete", methods=["POST"])
@role("viewer")
def secret_delete(secret_id):
    _require(edit=True)
    s = _secret(secret_id)
    s.deleted_at = utcnow()
    _audit(s, "removed a secret", s.name, "")
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/vault/secrets/{s.id}/restore", "body": {}})


@bp.route("/secrets/<int:secret_id>/restore", methods=["POST"])
@role("viewer")
def secret_restore(secret_id):
    _require(edit=True)
    s = _secret(secret_id, deleted_ok=True)
    if s.deleted_at is not None:
        s.deleted_at = None
        _audit(s, "restored a secret")
        db.session.commit()
    return jsonify(ok=True, secret=_json(s))


# ———— Settings > Secrets, and the purge ————

def pane() -> str:
    total = Secret.query.filter_by(deleted_at=None).count()
    sample = Secret.query.filter_by(deleted_at=None).order_by(Secret.id).first()
    readable, problem = True, ""
    try:
        if sample is not None:
            crypto.decrypt(sample.ciphertext)
    except (crypto.Unreadable, crypto.BadKey) as err:
        readable, problem = False, str(err)
    reveals = (AuditLog.query.filter(AuditLog.action == "revealed a secret")
               .order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(15).all())
    try:
        src = crypto.source()
    except crypto.BadKey:
        src = "environment"
    return render_template("vault/pane.html", source=src, path=crypto.key_path(), total=total,
                           readable=readable, problem=problem, reveals=reveals,
                           people=User.query.filter_by(can_see_secrets=True).order_by(User.username).all())


def purge() -> int:
    cutoff = utcnow() - timedelta(days=int_setting("purge_days", 30))
    doomed = Secret.query.filter(Secret.deleted_at.isnot(None), Secret.deleted_at <= cutoff).all()
    for s in doomed:
        db.session.delete(s)
    return len(doomed)
