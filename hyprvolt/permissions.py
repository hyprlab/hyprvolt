"""Roles, and the decorator every route carries.

The data belongs to the instance, not to whoever created it, so access is a
question of role rather than ownership:

* ``viewer`` reads everything but secrets, unless given access to them
* ``editor`` also creates, edits, archives and deletes documentation
* ``admin`` also manages users, modules, custom fields, backups and instance
  settings, and sees every secret: an admin can do everything

Every view declares what it needs with ``@role(...)`` or ``@public``. The app
factory refuses to start if a route has neither (``check_routes``), so a new
route, core or module, can't ship without a decision about who may call it.
"""
from functools import wraps

from flask import Flask, abort, current_app
from flask_login import current_user

ROLES = ("viewer", "editor", "admin")
ROLE_LABELS = {"viewer": "Viewer", "editor": "Editor", "admin": "Admin"}
_RANK = {name: n for n, name in enumerate(ROLES)}

_REFUSED = {
    "editor": "Your account can only read. Ask an admin for the editor role to make changes.",
    "admin": "Only an admin can do that.",
}


def has_role(user, needed: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return _RANK.get(getattr(user, "role", ""), -1) >= _RANK[needed]


def role(needed: str):
    """Signed in, with at least ``needed``. Replaces ``@login_required``."""
    if needed not in _RANK:
        raise ValueError(f"unknown role {needed!r}")

    def decorate(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not has_role(current_user, needed):
                abort(403, description=_REFUSED.get(needed, "Your account does not have access to this."))
            return view(*args, **kwargs)
        wrapper.required_role = needed
        return wrapper
    return decorate


def public(view):
    """Open to anyone: sign-in, setup, the health check."""
    view.required_role = "public"
    return view


def undeclared_routes(app: Flask, prefix: str = "") -> list[str]:
    """Endpoints whose view says nothing about who may call it."""
    missing = []
    for endpoint, view in app.view_functions.items():
        if endpoint == "static" or endpoint.endswith(".static"):
            continue
        if prefix and not endpoint.startswith(prefix):
            continue
        if not getattr(view, "required_role", None):
            missing.append(endpoint)
    return sorted(missing)


def check_routes(app: Flask) -> None:
    missing = undeclared_routes(app)
    if missing:
        raise RuntimeError(
            "These routes declare no role (add @role(...) or @public): " + ", ".join(missing)
        )
