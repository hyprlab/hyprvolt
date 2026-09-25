"""The app shell and its JSON API.

Two shapes of route live here:

* ``index`` renders the shell (sidebar, topbar, records, dialogs) for a page
  load. The filter, sort and view are query parameters, so every screen has a
  URL and the back button works. With ``partial=1`` it returns only the record
  list, which is how "Load more" and infinite scroll page: one renderer for the
  list, not a second one in JavaScript.
* Everything else answers JSON to ``fetch`` calls from ``static/js/app.js``,
  behind the session CSRF check in the app factory. Failures return
  ``{"error": "..."}`` with a 4xx status, written for the person reading it; the
  client shows it as a toast or an inline form error.

Admin routes are grouped at the end behind ``_require_admin``.
"""
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from . import __version__
from .auth import EMAIL_RE, MIN_PASSWORD, siteverify, turnstile_config
from .models import Item, User, db, get_setting, int_setting, set_setting

bp = Blueprint("main", __name__)

VIEWS = ("cards", "list")
FILTERS = ("open", "all", "pinned", "done")
SORTS = {
    "newest": ("Newest first", lambda: Item.created_at.desc()),
    "oldest": ("Oldest first", lambda: Item.created_at.asc()),
    "title": ("Title, A to Z", lambda: func.lower(Item.title).asc()),
}


# ———— Health ————

@bp.route("/healthz")
def healthz():
    """Liveness probe for Docker and any proxy in front of it.

    Outside @login_required and outside the setup gate, and it touches the
    database, so a healthy answer means the app can serve, not just that the
    port is open.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        return jsonify(ok=False), 503
    return jsonify(ok=True, version=__version__)


# ———— The shell ————

def _items_query(filter_name: str, sort: str):
    query = Item.query.filter(Item.user_id == current_user.id)
    if filter_name == "open":
        query = query.filter(Item.done.is_(False))
    elif filter_name == "pinned":
        query = query.filter(Item.pinned.is_(True))
    elif filter_name == "done":
        query = query.filter(Item.done.is_(True))
    # Pinned records lead every list, whatever the sort.
    return query.order_by(Item.pinned.desc(), SORTS[sort][1](), Item.id.desc())


@bp.route("/")
@login_required
def index():
    filter_name = request.args.get("filter", "open")
    if filter_name not in FILTERS:
        filter_name = "open"
    sort = request.args.get("sort", "newest")
    if sort not in SORTS:
        sort = "newest"
    view = request.args.get("view") or current_user.view_mode
    if view not in VIEWS:
        view = "cards"

    page = max(1, request.args.get("page", type=int) or 1)
    per_page = int_setting("items_per_page", 40)
    query = _items_query(filter_name, sort)
    items = query.limit(per_page + 1).offset((page - 1) * per_page).all()
    has_more = len(items) > per_page
    items = items[:per_page]

    context = dict(items=items, filter=filter_name, sort=sort, view=view,
                   page=page, has_more=has_more)
    if request.args.get("partial") == "1":
        return render_template("partials/records.html", **context)

    mine = Item.query.filter_by(user_id=current_user.id)
    counts = {
        "open": mine.filter_by(done=False).count(),
        "pinned": mine.filter_by(pinned=True).count(),
        "done": mine.filter_by(done=True).count(),
    }
    return render_template("app.html", counts=counts, sorts=SORTS, **context, **_admin_context())


def _admin_context() -> dict:
    """What the Admin section needs. Empty for anyone else, so the queries never
    run for an ordinary account."""
    if not current_user.is_admin:
        return {}
    return {
        "admin_users": User.query.order_by(User.created_at).all(),
        "admin_item_counts": dict(
            db.session.query(Item.user_id, func.count(Item.id)).group_by(Item.user_id).all()
        ),
        "admin_stats": {"users": User.query.count(), "records": Item.query.count()},
        "inst_worker": int_setting("worker_minutes", 15),
        "inst_per_page": int_setting("items_per_page", 40),
        "turnstile": _turnstile_status(),
    }


# ———— Records ————

def _own_item(item_id: int) -> Item:
    """404, not 403, for someone else's record: its existence is not theirs to
    learn either."""
    item = db.session.get(Item, item_id)
    if item is None or item.user_id != current_user.id:
        abort(404)
    return item


def _item_json(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "summary": item.summary,
        "pinned": item.pinned,
        "done": item.done,
        "created_at": item.created_at.isoformat() + "Z",
        "updated_at": item.updated_at.isoformat() + "Z",
    }


@bp.route("/items", methods=["POST"])
@login_required
def item_create():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify(error="Give it a title."), 400
    if len(title) > 300:
        return jsonify(error="Titles are limited to 300 characters."), 400
    item = Item(user_id=current_user.id, title=title, body=(data.get("body") or "").strip())
    db.session.add(item)
    db.session.commit()
    return jsonify(ok=True, item=_item_json(item))


@bp.route("/items/<int:item_id>")
@login_required
def item_detail(item_id):
    return jsonify(ok=True, item=_item_json(_own_item(item_id)))


@bp.route("/items/<int:item_id>", methods=["POST"])
@login_required
def item_update(item_id):
    item = _own_item(item_id)
    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify(error="Give it a title."), 400
        if len(title) > 300:
            return jsonify(error="Titles are limited to 300 characters."), 400
        item.title = title
    if "body" in data:
        item.body = (data.get("body") or "").strip()
    if "pinned" in data:
        item.pinned = bool(data["pinned"])
    if "done" in data:
        item.done = bool(data["done"])
    db.session.commit()
    return jsonify(ok=True, item=_item_json(item))


@bp.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def item_delete(item_id):
    item = _own_item(item_id)
    snapshot = _item_json(item)
    db.session.delete(item)
    db.session.commit()
    # The client keeps the snapshot to offer Undo, which re-creates it.
    return jsonify(ok=True, item=snapshot)


@bp.route("/items/restore", methods=["POST"])
@login_required
def item_restore():
    """Undo for a delete: re-create a record from the snapshot the delete
    returned. Only the user's own fields come back; the id is new."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:300]
    if not title:
        return jsonify(error="Nothing to restore."), 400
    item = Item(user_id=current_user.id, title=title, body=(data.get("body") or "").strip(),
                pinned=bool(data.get("pinned")), done=bool(data.get("done")))
    db.session.add(item)
    db.session.commit()
    return jsonify(ok=True, item=_item_json(item))


@bp.route("/search")
@login_required
def search():
    """Backs the Ctrl/Cmd+K palette: a case-insensitive substring match over
    the user's own records, newest first, capped so a broad query stays cheap."""
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify(results=[])
    like = "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        Item.query
        .filter(Item.user_id == current_user.id)
        .filter(or_(func.lower(Item.title).like(like, escape="\\"),
                    func.lower(Item.body).like(like, escape="\\")))
        .order_by(Item.created_at.desc())
        .limit(20).all()
    )
    return jsonify(results=[
        {"id": r.id, "title": r.title, "done": r.done, "when": r.created_at.strftime("%b %-d")}
        for r in rows
    ])


# ———— Account ————

@bp.route("/settings", methods=["POST"])
@login_required
def settings():
    data = request.get_json(silent=True) or {}
    if "name" in data:
        current_user.name = (data.get("name") or "").strip()[:120] or None
    if data.get("theme") in ("system", "light", "dark"):
        current_user.theme = data["theme"]
    if data.get("view_mode") in VIEWS:
        current_user.view_mode = data["view_mode"]
    if "infinite_scroll" in data:
        current_user.infinite_scroll = bool(data["infinite_scroll"])
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    if not current_user.check_password(data.get("current", "")):
        return jsonify(error="Current password is wrong."), 403
    new = data.get("new", "")
    if len(new) < MIN_PASSWORD:
        return jsonify(error=f"New passwords need at least {MIN_PASSWORD} characters."), 400
    current_user.set_password(new)
    db.session.commit()
    return jsonify(ok=True)


# ———— Admin ————

def _require_admin() -> None:
    if not current_user.is_admin:
        abort(403)


INSTANCE_SETTINGS = {
    # key: (lowest, highest, how the error names it)
    "worker_minutes": (0, 1440, "The background interval"),
    "items_per_page": (10, 500, "The page size"),
}


@bp.route("/admin/instance", methods=["POST"])
@login_required
def admin_instance():
    _require_admin()
    data = request.get_json(silent=True) or {}
    for key, (low, high, label) in INSTANCE_SETTINGS.items():
        if key not in data:
            continue
        try:
            value = int(data[key])
        except (TypeError, ValueError):
            return jsonify(error=f"{label} must be a number."), 400
        if not low <= value <= high:
            return jsonify(error=f"{label} must be between {low} and {high}."), 400
        set_setting(key, str(value))
    return jsonify(ok=True)


@bp.route("/admin/registration", methods=["POST"])
@login_required
def admin_registration():
    _require_admin()
    open_ = bool((request.get_json(silent=True) or {}).get("open"))
    set_setting("registration_open", "1" if open_ else "0")
    return jsonify(ok=True, open=open_)


def _turnstile_status() -> dict:
    """What the Security section shows. The secret never leaves the server;
    only its last four characters do, so an admin can tell which one is saved."""
    config = turnstile_config()
    stored_site = get_setting("turnstile_site_key") or ""
    stored_secret = get_setting("turnstile_secret_key") or ""
    return {
        "on": config is not None,
        "source": config["source"] if config else None,
        "site_key": config["site_key"] if config else stored_site,
        "secret_hint": (config["secret_key"] if config else stored_secret)[-4:],
    }


@bp.route("/admin/turnstile", methods=["POST"])
@login_required
def admin_turnstile():
    """Turn Turnstile on, or change its keys.

    Only after the admin has passed a challenge rendered with the new site key
    and Cloudflare has accepted the answer with the new secret. That proves the
    two keys belong together and that this address is allowed for the widget;
    a wrong pair saved blindly would lock everyone, the admin included, out of
    sign-in.
    """
    _require_admin()
    data = request.get_json(silent=True) or {}
    site_key = (data.get("site_key") or "").strip()
    secret_key = (data.get("secret_key") or "").strip()
    if not site_key:
        return jsonify(error="Enter the site key."), 400
    if not secret_key:
        # Blank keeps the secret already in force, so changing only the site
        # key doesn't mean pasting the secret again.
        current = turnstile_config() or {}
        secret_key = current.get("secret_key") or get_setting("turnstile_secret_key") or ""
        if not secret_key:
            return jsonify(error="Enter the secret key."), 400
    if len(site_key) > 200 or len(secret_key) > 200:
        return jsonify(error="That doesn't look like a Turnstile key."), 400
    ok, why = siteverify(secret_key, data.get("token") or "")
    if not ok:
        return jsonify(error=why), 400
    set_setting("turnstile_site_key", site_key)
    set_setting("turnstile_secret_key", secret_key)
    set_setting("turnstile_enabled", "1")
    return jsonify(ok=True, status=_turnstile_status())


@bp.route("/admin/turnstile/disable", methods=["POST"])
@login_required
def admin_turnstile_disable():
    """Turn Turnstile off. The keys stay saved, so turning it back on is one
    challenge away. The stored "off" also overrides TURNSTILE_* variables."""
    _require_admin()
    set_setting("turnstile_enabled", "0")
    return jsonify(ok=True, status=_turnstile_status())


@bp.route("/admin/users", methods=["POST"])
@login_required
def admin_create_user():
    _require_admin()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if len(username) > 80 or not EMAIL_RE.match(username):
        return jsonify(error="Enter a valid email address."), 400
    if len(password) < MIN_PASSWORD:
        return jsonify(error=f"Passwords need at least {MIN_PASSWORD} characters."), 400
    if User.query.filter(func.lower(User.username) == username).first():
        return jsonify(error="An account with that email already exists."), 409
    user = User(username=username, is_admin=bool(data.get("is_admin")),
                name=(data.get("name") or "").strip()[:120] or None)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(ok=True, id=user.id)


@bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@login_required
def admin_reset_password(user_id):
    _require_admin()
    user = db.get_or_404(User, user_id)
    new = (request.get_json(silent=True) or {}).get("new", "")
    if len(new) < MIN_PASSWORD:
        return jsonify(error=f"Passwords need at least {MIN_PASSWORD} characters."), 400
    user.set_password(new)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
def admin_toggle_admin(user_id):
    _require_admin()
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        return jsonify(error="You can't change your own admin status."), 400
    user.is_admin = not user.is_admin
    db.session.commit()
    return jsonify(ok=True, is_admin=user.is_admin)


@bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    _require_admin()
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        return jsonify(error="You can't delete your own account from here."), 400
    db.session.delete(user)   # their records cascade through the relationship
    db.session.commit()
    return jsonify(ok=True)
