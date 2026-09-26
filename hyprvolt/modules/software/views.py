"""Software's tabs, installation routes and filters: where each title is
installed and at which version, and how many seats of each license are used."""
from datetime import date

from flask import Blueprint, abort, jsonify, render_template, request

from hyprvolt.core import records, reminders
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db
from hyprvolt.permissions import role
from hyprvolt.registry import current as registry

from .models import Installation, SoftwareDetail

bp = Blueprint("software", __name__)

def _detail(entity_id):
    return db.session.get(SoftwareDetail, entity_id)


def is_host(etype) -> bool:
    return "host" in etype.traits


def has_software_tab(entity: Entity) -> bool:
    etype = registry().type(entity.type)
    return etype is not None and is_host(etype)


def installs(software_id=None, host_id=None, license_id=None) -> list[Installation]:
    """Installations whose title and host are both live."""
    q = Installation.query
    if software_id is not None:
        q = q.filter(Installation.software_id == software_id)
    if host_id is not None:
        q = q.filter(Installation.host_id == host_id)
    if license_id is not None:
        q = q.filter(Installation.license_id == license_id)
    return [i for i in q if i.software.deleted_at is None and i.host.deleted_at is None]


def behind(i: Installation, current: str | None) -> bool:
    return bool(current and i.version and i.version != current)


def seats(license_: Entity) -> dict:
    d = _detail(license_.id)
    used_here = len(installs(license_id=license_.id))
    used = used_here + (d.extra_seats or 0 if d else 0)
    owned = d.seats if d else None
    return {"owned": owned, "used": used, "here": used_here, "extra": (d.extra_seats or 0) if d else 0,
            "over": owned is not None and used > owned,
            "percent": min(100, round(100 * used / owned)) if owned else 0}


def hosts() -> list[tuple[int, str]]:
    """Every live record software can go on, named with its kind."""
    reg = registry()
    keys = [t.key for t in reg.enabled_types() if is_host(t)]
    rows = Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all()
    return [(e.id, f"{e.name} · {reg.type(e.type).label}") for e in rows]


def kinds(rows) -> dict[int, str]:
    """host id -> what kind of record it is, for the installations listed."""
    reg = registry()
    return {i.host_id: (reg.type(i.host.type).label if reg.type(i.host.type) else "") for i in rows}


def licenses_of(software_id) -> list[Entity]:
    ids = db.session.query(SoftwareDetail.entity_id).filter(SoftwareDetail.software == software_id)
    return Entity.live().filter(Entity.type == "license", Entity.id.in_(ids)).order_by(Entity.name).all()


# ———— Tabs ————

def software_tab(title: Entity) -> str:
    d = _detail(title.id)
    rows = sorted(installs(software_id=title.id), key=lambda i: i.host.name.lower())
    licenses = licenses_of(title.id)
    return render_template("software/installs.html", title=title, rows=rows, current=d.current_version if d else None,
                           behind=behind, hosts=hosts(), licenses=licenses,
                           seats=[(lic, seats(lic)) for lic in licenses], kinds=kinds(rows),
                           license_choices=[(lic.id, lic.name) for lic in licenses])


def software_count(title: Entity):
    return len(installs(software_id=title.id)) or None


def host_tab(host: Entity) -> str:
    rows = sorted(installs(host_id=host.id), key=lambda i: i.software.name.lower())
    titles = Entity.live().filter(Entity.type == "software").order_by(Entity.name).all()
    currents = {i.software_id: (_detail(i.software_id).current_version if _detail(i.software_id) else None)
                for i in rows}
    all_licenses = []
    for lic in Entity.live().filter(Entity.type == "license").order_by(Entity.name):
        d = _detail(lic.id)
        title = records.live(d.software) if d and d.software else None
        all_licenses.append((lic.id, f"{lic.name} · {title.name}" if title else lic.name))
    return render_template("software/host.html", host=host, rows=rows, currents=currents, behind=behind,
                           titles=titles, licenses=all_licenses, license_choices=all_licenses)


def host_count(host: Entity):
    return len(installs(host_id=host.id)) or None


def license_tab(license_: Entity) -> str:
    d = _detail(license_.id)
    title = records.live(d.software) if d and d.software else None
    rows = sorted(installs(license_id=license_.id), key=lambda i: i.host.name.lower())
    return render_template("software/license.html", license=license_, d=d, title=title, s=seats(license_),
                           rows=rows, kinds=kinds(rows))


def license_count(license_: Entity):
    return seats(license_)["used"] or None


# ———— Filters ————

def over_seats(query):
    ids = [e.id for e in Entity.live().filter(Entity.type == "license") if seats(e)["over"]]
    return query.filter(Entity.id.in_(ids))


def renewal_soon(query):
    return reminders.ending_within(query.filter(Entity.type == "license", Entity.status == "active"),
                                   SoftwareDetail, SoftwareDetail.renews, past=True)


def outdated(query):
    ids = set()
    for i in Installation.query:
        d = _detail(i.software_id)
        if d and behind(i, d.current_version) and i.host.deleted_at is None:
            ids.add(i.software_id)
    return query.filter(Entity.type == "software", Entity.id.in_(ids))


# ———— Installations ————

def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _fail(err):
    db.session.rollback()
    return jsonify(error=str(err)), 400


def _text(data, key, limit):
    return " ".join(str(data.get(key) or "").split())[:limit]


def _license(data, software_id):
    raw = data.get("license_id")
    if raw in (None, "", 0, "0"):
        return None
    lic = records.live(raw)
    d = _detail(lic.id) if lic else None
    if lic is None or lic.type != "license":
        raise Invalid("Choose a license that exists.")
    if d is None or d.software != software_id:
        raise Invalid(f"{lic.name} is a license for other software.")
    return lic.id


def _date(data):
    raw = data.get("installed")
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise Invalid("The install date must be a date, such as 2026-09-25.") from None


def install_json(i: Installation) -> dict:
    return {"id": i.id, "software_id": i.software_id, "software": i.software.name, "host_id": i.host_id,
            "host": i.host.name, "version": i.version, "license_id": i.license_id,
            "installed": i.installed.isoformat() if i.installed else None, "note": i.note}


def _was(version):
    """An installation's version for the history: "" when not installed."""
    return "" if version is None else (version or "installed")


def _audit(i: Installation, action, changes, user=None) -> None:
    """``changes`` as (what, old, new): written to the title's history under
    the host's name and to the host's under the title's."""
    for entity, other in ((i.software, i.host), (i.host, i.software)):
        records.audit(entity, action, [{"field": "install", "label": f"{other.name}{': ' + what if what else ''}",
                                        "old": old, "new": new} for what, old, new in changes], user)


def _license_name(license_id):
    lic = records.live(license_id) if license_id else None
    return lic.name if lic else ""


def add_install(data: dict, user=None) -> Installation:
    """``software_id`` and ``host_id``, with ``version``, ``license_id``,
    ``installed`` and ``note``."""
    title, host = records.live(data.get("software_id")), records.live(data.get("host_id"))
    if title is None or title.type != "software":
        raise Invalid("Choose the software.")
    etype = registry().type(host.type) if host else None
    if host is None or not is_host(etype):
        raise Invalid("Choose where it is installed.")
    if Installation.query.filter_by(software_id=title.id, host_id=host.id).first():
        raise Invalid(f"{title.name} is already recorded on {host.name}. Change that one instead.")
    i = Installation(software_id=title.id, host_id=host.id, version=_text(data, "version", 60),
                     license_id=_license(data, title.id), installed=_date(data), note=_text(data, "note", 200))
    db.session.add(i)
    db.session.flush()
    _audit(i, "installed", [("", "", _was(i.version))] +
           ([("license", "", _license_name(i.license_id))] if i.license_id else []), user)
    return i


@bp.route("/installations", methods=["POST"])
@role("editor")
def install_create():
    """Record an installation (``add_install``). Also Undo for a removed one."""
    try:
        i = add_install(_body())
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, installation=install_json(i))


@bp.route("/installations/edit", methods=["POST"])
@role("editor")
def install_edit():
    data = _body()
    i = db.session.get(Installation, int(data.get("installation_id") or 0))
    if i is None:
        abort(404, description="There is no such installation.")
    try:
        before = (i.version, i.license_id)
        if "version" in data:
            i.version = _text(data, "version", 60)
        if "license_id" in data:
            i.license_id = _license(data, i.software_id)
        if "installed" in data:
            i.installed = _date(data)
        if "note" in data:
            i.note = _text(data, "note", 200)
        changes = []
        if before[0] != i.version:
            changes.append(("", _was(before[0]), _was(i.version)))
        if before[1] != i.license_id:
            changes.append(("license", _license_name(before[1]), _license_name(i.license_id)))
        if changes:
            _audit(i, "updated", changes)
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, installation=install_json(i))


@bp.route("/installations/<int:install_id>/delete", methods=["POST"])
@role("editor")
def install_delete(install_id):
    i = db.get_or_404(Installation, install_id)
    snapshot = {k: v for k, v in install_json(i).items() if k not in ("id", "software", "host")}
    _audit(i, "uninstalled", [("", _was(i.version), "")])
    db.session.delete(i)
    db.session.commit()
    return jsonify(ok=True, undo={"url": "/software/installations", "body": snapshot})


@bp.route("/titles/<int:software_id>/installations")
@role("viewer")
def install_list(software_id):
    title = records.live(software_id)
    if title is None or title.type != "software":
        abort(404, description="There is no such software.")
    return jsonify(installations=[install_json(i) for i in installs(software_id=title.id)])


@bp.route("/hosts/<int:host_id>/installations")
@role("viewer")
def host_install_list(host_id):
    host = records.live(host_id)
    if host is None or not has_software_tab(host):
        abort(404, description="There is no such host.")
    return jsonify(installations=[install_json(i) for i in installs(host_id=host.id)])
