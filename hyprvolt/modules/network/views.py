"""Network's tabs, JSON routes, sidebar filters and dashboard widget."""

from flask import Blueprint, abort, jsonify, render_template, request

from sqlalchemy.orm import joinedload

from hyprvolt.core import present, records, reminders
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db
from hyprvolt.modules.hardware.models import HardwareDetail
from hyprvolt.permissions import role
from hyprvolt.registry import current as registry

from . import addresses, dns, ports
from .models import DNS_TYPES, PORT_KINDS, SPEEDS, Cable, DnsRecord, NetworkDetail, Port

bp = Blueprint("network", __name__)

def _detail(entity_id):
    return db.session.get(NetworkDetail, entity_id)


def _children(field, parent_id, type_key):
    return (Entity.live().join(NetworkDetail, NetworkDetail.entity_id == Entity.id)
            .filter(Entity.type == type_key, getattr(NetworkDetail, field) == parent_id).all())


# ———— Tabs ————

def subnet_tab(subnet: Entity) -> str:
    return render_template("network/subnet.html", subnet=subnet, u=addresses.usage(subnet))


def subnet_count(subnet: Entity):
    u = addresses.usage(subnet, grid=False)
    return (u["documented"] or None) if u else None


def vlan_tab(vlan: Entity) -> str:
    subnets = sorted(_children("vlan", vlan.id, "subnet"), key=lambda e: addresses.ip_key((_detail(e.id).cidr or "").split("/")[0]))
    on_ports = (Port.query.join(Entity, Entity.id == Port.device_id)
                .filter(Port.vlan_id == vlan.id, Entity.deleted_at.is_(None))
                .order_by(Entity.name, Port.position).all())
    return render_template("network/vlan.html", vlan=vlan,
                           subnets=[(v, addresses.usage(v.entity, grid=False)) for v in present.views(subnets)], ports=on_ports)


def vlan_count(vlan: Entity):
    return len(_children("vlan", vlan.id, "subnet")) or None


def network_tab(network: Entity) -> str:
    vlans = sorted(_children("network", network.id, "vlan"), key=lambda e: _detail(e.id).vid or 0)
    subnets = _children("network", network.id, "subnet")
    return render_template("network/network.html", network=network, vlans=present.views(vlans),
                           subnets=[(v, addresses.usage(v.entity, grid=False)) for v in present.views(subnets)])


def network_count(network: Entity):
    return (len(_children("network", network.id, "vlan")) + len(_children("network", network.id, "subnet"))) or None


def ip_tab(ip: Entity) -> str:
    d = _detail(ip.id)
    subnet = addresses.subnet_of(d.address) if d and d.address else None
    sd = _detail(subnet.id) if subnet else None
    vlan = records.live(sd.vlan) if sd and sd.vlan else None
    names = addresses.dns_names([d.address]).get(d.address, []) if d and d.address else []
    return render_template("network/ip.html", ip=ip, subnet=subnet, sd=sd, vlan=vlan, names=names)


def addresses_tab(entity: Entity) -> str:
    rows = []
    for ip, d in addresses.addresses_of(entity):
        subnet = addresses.subnet_of(d.address)
        sd = _detail(subnet.id) if subnet else None
        rows.append({"ip": ip, "address": d.address, "subnet": subnet, "cidr": sd.cidr if sd else "",
                     "vlan": records.live(sd.vlan) if sd and sd.vlan else None, "mac": d.mac})
    names = addresses.dns_names([r["address"] for r in rows])
    for r in rows:
        r["names"] = names.get(r["address"], [])
    return render_template("network/addresses.html", entity=entity, rows=rows)


def addresses_count(entity: Entity):
    return len(addresses.addresses_of(entity)) or None


def has_addresses_tab(entity: Entity) -> bool:
    etype = registry().type(entity.type)
    return etype is not None and addresses.is_addressable(etype)


def has_ports_tab(entity: Entity) -> bool:
    etype = registry().type(entity.type)
    return etype is not None and ports.is_cabled(etype)


def ports_tab(device: Entity) -> str:
    """Its cables, and with its ports recorded, every port. A device whose
    ports aren't recorded is cabled as a whole."""
    recorded = ports.records_ports(device.id)
    rows = ports.ports_of(device.id)
    cables = ports.cables_for(rows)
    items = []
    for p in rows:
        cable = cables.get(p.id)
        other = cable.other(p) if cable else None
        if other is not None and other.device.deleted_at is not None:
            other = None
        if not recorded and other is None:
            continue
        items.append({"port": p, "cable": cable if other else None, "other": other,
                      "trace": ports.trace(p) if other else [],
                      "facts": [x for x in (ports.kind_label(p.kind), ports.speed_label(p.speed_mbps),
                                            "PoE" if p.poe else "", p.vlan.name if p.vlan and not p.vlan.deleted_at else "",
                                            f"tagged {p.tagged}" if p.tagged else "", p.mac, p.description) if x]
                      if p.name else []})
    own_free = [i["port"] for i in items if i["cable"] is None] if recorded else []
    detail = db.session.get(HardwareDetail, device.id)
    vlans = present.views(Entity.live().filter(Entity.type == "vlan").order_by(Entity.name).all())
    return render_template("network/ports.html", device=device, items=items, recorded=recorded,
                           targets=ports.free_ends(device.id), own_free=own_free, kinds=PORT_KINDS, speeds=SPEEDS,
                           vlans=vlans, is_panel=detail is not None and detail.kind == "patch_panel",
                           count=detail.ports if detail is not None and detail.ports else None)


def ports_count(device: Entity):
    """The cables it has."""
    return (Port.query.join(Cable, (Cable.a_id == Port.id) | (Cable.b_id == Port.id))
            .filter(Port.device_id == device.id).count() or None)



def records_tab(domain: Entity) -> str:
    rows = dns.records_of(domain.id)
    return render_template("network/dns.html", domain=domain, rows=rows, targets=dns.targets(rows), types=DNS_TYPES)


def records_count(domain: Entity):
    return DnsRecord.query.filter_by(domain_id=domain.id).count() or None


# ———— The site setup guide's cables step ————

def setup_ends(scope) -> list[dict]:
    ends = ports.free_ends()
    out = [{"label": "Devices", "options": [(f"device:{d.id}", d.name) for d in ends["devices"]]}]
    out += [{"label": g["device"], "options": [(f"port:{p.id}", p.label) for p in g["ports"]]}
            for g in ends["ports"]]
    return [g for g in out if g["options"]]


def _setup_end(value):
    kind, _, raw = str(value or "").partition(":")
    end = db.session.get(Port, int(raw)) if kind == "port" and raw.isdigit() else \
        records.live(int(raw)) if kind == "device" and raw.isdigit() else None
    device = end.device_id if isinstance(end, Port) else end.id if end is not None else None
    if end is None or records.live(device) is None:
        raise Invalid("Choose both ends of the cable.")
    return end


def setup_cable(values, scope, user) -> None:
    ports.connect(_setup_end(values.get("from")), _setup_end(values.get("to")),
                  {"label": values.get("label", "")}, user)


def setup_cables(scope) -> list[str]:
    out = []
    eager = (joinedload(Cable.a).joinedload(Port.device), joinedload(Cable.b).joinedload(Port.device))
    for c in Cable.query.options(*eager):
        if c.a.device.deleted_at is None and c.b.device.deleted_at is None:
            out.append(f"{c.a.label} to {c.b.label}")
    return sorted(out, key=str.lower)


# ———— Sidebar filters and the dashboard ————

def internet_connections(query):
    wan = db.session.query(NetworkDetail.entity_id).filter(NetworkDetail.kind == "wan")
    return query.filter(Entity.type == "network", Entity.id.in_(wan))


def ips_without_device(query):
    live_ids = db.session.query(Entity.id).filter(Entity.deleted_at.is_(None))
    loose = db.session.query(NetworkDetail.entity_id).filter(
        (NetworkDetail.assigned.is_(None)) | (NetworkDetail.assigned.notin_(live_ids)))
    return query.filter(Entity.type == "ip_address", Entity.status == "active", Entity.id.in_(loose))


def renewal_soon(query):
    return reminders.ending_within(query.filter(Entity.type == "domain", Entity.status != "retired"),
                                   NetworkDetail, NetworkDetail.expires, past=True)


def subnets_widget() -> str:
    rows = []
    for subnet in Entity.live().filter(Entity.type == "subnet", Entity.archived.is_(False)).order_by(Entity.name):
        u = addresses.usage(subnet, grid=False)
        if u:
            rows.append({"subnet": subnet, "u": u})
    rows.sort(key=lambda r: addresses.ip_key(str(r["u"]["net"].network_address)))
    return render_template("network/widget.html", rows=rows[:10])


# ———— JSON routes ————

def _live_or_404(entity_id, check=None, what="record"):
    entity = records.live(entity_id)
    if entity is None or (check is not None and not check(entity)):
        abort(404, description=f"There is no such {what}.")
    return entity


def _device(entity_id):
    return _live_or_404(entity_id, has_ports_tab, "device with ports")


def _port(port_id):
    """A port on a live record of a turned-on module."""
    port = db.session.get(Port, port_id)
    if port is None or records.live(port.device_id) is None:
        abort(404, description="There is no such port.")
    return port


def _id(data, key) -> int:
    try:
        return int(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _fail(err):
    db.session.rollback()
    return jsonify(error=str(err)), 400


@bp.route("/devices/<int:device_id>/ports")
@role("viewer")
def port_list(device_id):
    device = _device(device_id)
    return jsonify(ports=[ports.port_json(p) for p in ports.ports_of(device.id)])


@bp.route("/devices/<int:device_id>/ports", methods=["POST"])
@role("editor")
def port_add(device_id):
    device = _device(device_id)
    try:
        made = ports.add_ports(device, _body())
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, ports=[ports.port_json(p) for p in made])


@bp.route("/devices/<int:device_id>/ports/recorded", methods=["POST"])
@role("editor")
def ports_recorded(device_id):
    """``on``: record each of the device's ports, or cable it as a whole."""
    device = _device(device_id)
    changes = ports.record_ports(device, _body().get("on") or False)
    if changes:
        records.audit(device, "edited", changes)
    db.session.commit()
    return jsonify(ok=True, recorded=ports.records_ports(device.id))


@bp.route("/devices/<int:device_id>/ports/restore", methods=["POST"])
@role("editor")
def port_restore(device_id):
    device = _device(device_id)
    try:
        port = ports.restore_port(device, _body())
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, port=ports.port_json(port))


@bp.route("/ports/edit", methods=["POST"])
@bp.route("/ports/<int:port_id>", methods=["POST"])
@role("editor")
def port_edit(port_id=None):
    """Change a port. The sheet's one edit form names the port as ``port_id``."""
    data = _body()
    port = _port(port_id or _id(data, "port_id"))
    try:
        ports.edit_port(port, {k: v for k, v in data.items() if k != "port_id"})
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, port=ports.port_json(port))


@bp.route("/ports/<int:port_id>/delete", methods=["POST"])
@role("editor")
def port_delete(port_id):
    port = _port(port_id)
    cable = ports.cable_of(port)
    if not port.name and cable is not None:
        # A port with no name is only there for its cable.
        return cable_delete(cable.id)
    device_id = port.device_id
    snapshot = ports.remove_port(port)
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/network/devices/{device_id}/ports/restore", "body": snapshot})


@bp.route("/ports/<int:port_id>/trace")
@role("viewer")
def port_trace(port_id):
    """The cable path from a port, through patch panels, to the far end."""
    path = []
    for step in ports.trace(_port(port_id)):
        if "port" in step:
            p = step["port"]
            path.append({"port": {"id": p.id, "name": p.name, "device_id": p.device_id, "device": p.device.name}})
        elif "cable" in step:
            c = step["cable"]
            path.append({"cable": {"id": c.id, "label": c.label, "color": c.color, "length_m": c.length_m}})
        else:
            path.append({"through": {"device_id": step["through"].id, "device": step["through"].name}})
    return jsonify(path=path)


def _end(data, port_key, device_key):
    """One end of a new cable: a port, or a device cabled as a whole. The
    form's choice of the far end comes as ``to``: "port:12" or "device:5"."""
    if port_key == "other_id" and ":" in str(data.get("to") or ""):
        kind, _, value = str(data["to"]).partition(":")
        data = {port_key: value} if kind == "port" else {device_key: value}
    if _id(data, port_key):
        return _port(_id(data, port_key))
    if _id(data, device_key):
        return _device(_id(data, device_key))
    raise Invalid("Choose what the cable goes to." if port_key == "other_id" else "Choose where the cable starts.")


@bp.route("/cables", methods=["POST"])
@role("editor")
def cable_create():
    """From ``port_id`` (or ``device_id``, a device cabled as a whole) to
    ``other_id`` (or ``other_device_id``), with an optional ``label``,
    ``color`` and ``length_m``."""
    data = _body()
    try:
        port = _end(data, "port_id", "device_id")
        other = _end(data, "other_id", "other_device_id")
        cable = ports.connect(port, other, data)
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, cable={"id": cable.id, "a": cable.a_id, "b": cable.b_id,
                                   "trace": ports.trace_text(cable.a)})


@bp.route("/cables/<int:cable_id>/delete", methods=["POST"])
@role("editor")
def cable_delete(cable_id):
    cable = db.get_or_404(Cable, cable_id)
    _port(cable.a_id), _port(cable.b_id)
    snapshot = ports.disconnect(cable)
    db.session.commit()
    return jsonify(ok=True, undo={"url": "/network/cables", "body": snapshot})


def _domain(domain_id):
    return _live_or_404(domain_id, lambda e: e.type == "domain", "domain")


@bp.route("/domains/<int:domain_id>/records")
@role("viewer")
def dns_list(domain_id):
    return jsonify(records=[dns.record_json(r) for r in dns.records_of(_domain(domain_id).id)])


@bp.route("/domains/<int:domain_id>/records", methods=["POST"])
@role("editor")
def dns_add(domain_id):
    domain = _domain(domain_id)
    try:
        record = dns.add_record(domain, _body())
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, record=dns.record_json(record))


@bp.route("/records/<int:record_id>/delete", methods=["POST"])
@role("editor")
def dns_delete(record_id):
    record = db.get_or_404(DnsRecord, record_id)
    _domain(record.domain_id)
    domain_id = record.domain_id
    snapshot = dns.remove_record(record)
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/network/domains/{domain_id}/records", "body": snapshot})


@bp.route("/subnets/<int:subnet_id>/addresses")
@role("viewer")
def subnet_addresses(subnet_id):
    """Which addresses of a subnet are documented, and how many are left."""
    subnet = _live_or_404(subnet_id, lambda e: e.type == "subnet", "subnet")
    u = addresses.usage(subnet)
    if u is None:
        return jsonify(error="This subnet has no address range yet."), 400
    return jsonify(subnet={"id": subnet.id, "name": subnet.name, "cidr": str(u["net"]), "hosts": u["hosts"],
                           "used": u["used"], "dhcp": u["pool"], "free": u["free"]},
                   addresses=[{"address": r["address"], "state": r["state"], "id": r["ip"].id,
                               "assigned": {"id": r["owner"].id, "name": r["owner"].name} if r["owner"] else None,
                               "dns": r["names"]} for r in u["rows"]])
