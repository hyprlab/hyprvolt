"""API tokens: per-user tokens so scripts can use the JSON API.

A request with ``Authorization: Bearer hv_…`` is that token's user for that
request only: no session, so no CSRF token is needed or checked (a browser
can't be made to send the header by another site). A token has its user's
role, can be limited to reading, never reveals a secret, and can't manage
tokens. Only a SHA-256 of each token is stored.
"""
import hashlib
import secrets
from datetime import timedelta

from flask import Blueprint, g, jsonify, render_template, request
from flask_login import current_user

from .models import ApiToken, db, utcnow
from .permissions import role

bp = Blueprint("tokens", __name__)

PREFIX = "hv_"
MAX_TOKENS = 20
#: last_used_at is written at most this often, so reading doesn't mean writing.
TOUCH_EVERY = timedelta(minutes=1)
SAFE = ("GET", "HEAD", "OPTIONS")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate():
    """The before_request hook: sets the user for a Bearer token, or
    answers 401 or 403. Returns None when the request has no token."""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    raw = header[7:].strip()
    token = ApiToken.query.filter_by(token_hash=_hash(raw), revoked_at=None).first() if raw.startswith(PREFIX) else None
    if token is None:
        return jsonify(error="That API token isn't valid. It may have been revoked."), 401
    if token.read_only and request.method not in SAFE:
        return jsonify(error="This token can only read. Make one that can also change things."), 403
    now = utcnow()
    if token.last_used_at is None or now - token.last_used_at > TOUCH_EVERY:
        token.last_used_at = now
        db.session.commit()
    g.api_token = token
    g._login_user = token.user          # Flask-Login's current_user, for this request only
    return None


def _no_token():
    if g.get("api_token") is not None:
        return jsonify(error="Tokens are made and revoked in Settings, not with a token."), 403
    return None


def mine() -> list[ApiToken]:
    if not getattr(current_user, "is_authenticated", False):
        return []
    return ApiToken.query.filter_by(user_id=current_user.id, revoked_at=None).order_by(ApiToken.created_at).all()


def token_json(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "read_only": t.read_only,
            "created_at": t.created_at.isoformat() + "Z",
            "last_used_at": t.last_used_at.isoformat() + "Z" if t.last_used_at else None}


@bp.route("/account/tokens")
@role("viewer")
def token_list():
    return _no_token() or jsonify(tokens=[token_json(t) for t in mine()])


@bp.route("/account/tokens", methods=["POST"])
@role("viewer")
def token_create():
    """Make a token. The answer holds it, once, and the HTML that shows it."""
    refused = _no_token()
    if refused:
        return refused
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name") or "").split())[:80]
    if not name:
        return jsonify(error="Name the token after what uses it, such as Backup script."), 400
    if len(mine()) >= MAX_TOKENS:
        return jsonify(error=f"An account can have {MAX_TOKENS} tokens. Revoke one first."), 400
    raw = PREFIX + secrets.token_urlsafe(32)
    read_only = data.get("read_only") not in (False, "0", "false", "")
    t = ApiToken(user_id=current_user.id, name=name, token_hash=_hash(raw), prefix=raw[:9], read_only=read_only)
    db.session.add(t)
    db.session.commit()
    return jsonify(ok=True, token=raw, api_token=token_json(t),
                   html=render_template("partials/token_made.html", t=t, raw=raw))


def _own(token_id) -> ApiToken | None:
    t = db.session.get(ApiToken, token_id)
    return t if t is not None and t.user_id == current_user.id else None


@bp.route("/account/tokens/<int:token_id>/revoke", methods=["POST"])
@role("viewer")
def token_revoke(token_id):
    refused = _no_token()
    if refused:
        return refused
    t = _own(token_id)
    if t is None or t.revoked_at is not None:
        return jsonify(error="There is no such token."), 404
    t.revoked_at = utcnow()
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/account/tokens/{t.id}/restore", "body": {}})


@bp.route("/account/tokens/<int:token_id>/restore", methods=["POST"])
@role("viewer")
def token_restore(token_id):
    refused = _no_token()
    if refused:
        return refused
    t = _own(token_id)
    if t is None:
        return jsonify(error="There is no such token."), 404
    t.revoked_at = None
    db.session.commit()
    return jsonify(ok=True, api_token=token_json(t))
