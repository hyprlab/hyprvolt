"""Network's tabs, JSON routes, sidebar filters and dashboard widget."""
import re

from flask import Blueprint, abort, jsonify, render_template, request

from sqlalchemy.orm import joinedload

from hyprvolt.core import fields as F
from hyprvolt.core import present, records, relations, reminders
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.manifest import Field
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
    subnet = addresses.subnet_of_ip(d) if d else None
    sd = _detail(subnet.id) if subnet else None
    vlan = records.live(sd.vlan) if sd and sd.vlan else None
    names = addresses.dns_names([d.address]).get(d.address, []) if d and d.address else []
    return render_template("network/ip.html", ip=ip, subnet=subnet, sd=sd, vlan=vlan, names=names)


def addresses_tab(entity: Entity) -> str:
    rows = []
    for ip, d in addresses.addresses_of(entity):
        subnet = addresses.subnet_of_ip(d)
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
    limit = ports.port_limit(device.id)
    full = limit is not None and sum(1 for i in items if i["cable"]) >= limit
    vlans = present.views(Entity.live().filter(Entity.type == "vlan").order_by(Entity.name).all())
    return render_template("network/ports.html", device=device, items=items, recorded=recorded,
                           targets=ports.free_ends(device.id), own_free=own_free, kinds=PORT_KINDS, speeds=SPEEDS,
                           vlans=vlans, is_panel=detail is not None and detail.kind == "patch_panel",
                           count=detail.ports if detail is not None and detail.ports else None,
                           limit=limit, full=full)


def ports_count(device: Entity):
    """The cables it has."""
    return (Port.query.join(Cable, (Cable.a_id == Port.id) | (Cable.b_id == Port.id))
            .filter(Port.device_id == device.id).count() or None)



def records_tab(domain: Entity) -> str:
    rows = dns.records_of(domain.id)
    return render_template("network/dns.html", domain=domain, rows=rows, targets=dns.targets(rows), types=DNS_TYPES)


def records_count(domain: Entity):
    return DnsRecord.query.filter_by(domain_id=domain.id).count() or None


# ———— Where the internet comes in: the device's Internet line section ————

#: What a line from the ISP can come in at: a modem or ONT, or a router or
#: firewall where there is no modem. The line is the device's own, not a
#: record of its own: its fields are kept in a network detail row keyed by
#: the device, of the kind "wan" while the line comes in there.
GATEWAY_TYPES = ("network_device", "firewall")
LINE_ON = ("line", True)
STATIC = ("static_ip", True)
LINE_FIELDS = (
    Field("line", "Internet", "boolean", switch=("Not here", "Comes in here"),
          help="Whether a line from an ISP plugs into it: the modem or ONT, or the router or firewall where "
               "there is no modem. The ISP is its Supplier."),
    Field("circuit_id", "Circuit ID", shown_when=LINE_ON,
          help="What the ISP calls this line when you report a fault."),
    Field("download", "Download", "speed", shown_when=LINE_ON,
          help="The speed the ISP sells, toward you: 1 Gb/s, or 940 Mb/s."),
    Field("upload", "Upload", "speed", shown_when=LINE_ON, help="The speed away from you: 40 Mb/s."),
    Field("static_ip", "IP address", "boolean", switch=("Dynamic", "Static"), shown_when=LINE_ON,
          help="Static: the ISP gave the line a fixed address, with its subnet and gateway, to set on your "
               "router. Dynamic: the address is handed out by the ISP and can change; there is nothing more "
               "to record."),
    Field("public_ips", "Static IP", shown_when=STATIC,
          help="The address the ISP gave the line: 203.0.113.26, or a range for a block."),
    Field("cidr", "Subnet", "cidr", shown_when=STATIC, prefills=("gateway",),
          help="The line's block of addresses from the ISP, with the subnet mask chosen beside it: "
               "203.0.113.24 and /29 for a mask of 255.255.255.248."),
    Field("gateway", "Gateway", "ip", shown_when=STATIC,
          help="The ISP's side of the line, which your router sends everything to."),
    Field("dns_servers", "DNS servers", shown_when=STATIC, help="The ISP's, if it gave any. Separated by commas."),
)


def is_gateway_gear(etype) -> bool:
    return etype.key in GATEWAY_TYPES


def line_ids() -> set[int]:
    """The devices a line from an ISP comes in at."""
    return {i for (i,) in db.session.query(NetworkDetail.entity_id).join(Entity, Entity.id == NetworkDetail.entity_id)
            .filter(NetworkDetail.kind == "wan", Entity.type.in_(GATEWAY_TYPES), Entity.deleted_at.is_(None))}


def internet_values(device) -> dict:
    row = _detail(device.id) if device is not None else None
    out = {f.key: getattr(row, f.key, None) if row is not None and f.key != "line" else None for f in LINE_FIELDS}
    out["line"] = row is not None and row.kind == "wan"
    out["static_ip"] = bool(out["static_ip"])
    return out


def _items(device, values=None) -> list[dict]:
    values = values if values is not None else internet_values(device)
    hidden = F.hidden_keys(LINE_FIELDS, values)
    return [{"field": f, "name": "s.internet." + f.key, "value": values.get(f.key), "choices": None,
             "prefix": "s.internet.", "hidden": f.key in hidden} for f in LINE_FIELDS]


def internet_form(etype, device) -> str:
    return render_template("network/line_form.html", items=_items(device), etype=etype)


def internet_save(device, values, user) -> list[dict]:
    """The line's fields, as given; Not here keeps what was typed, hidden,
    as Dynamic keeps a static line's address."""
    given = {f: values[f.key] for f in LINE_FIELDS if f.key in values}
    if not given:
        return []
    old = internet_values(device)
    row = _detail(device.id)
    if row is None:
        row = NetworkDetail(entity_id=device.id)
        db.session.add(row)
    changes = []
    for f, raw in given.items():
        value = F.parse(f, raw)
        if f.key == "line":
            row.kind = "wan" if value else None
        else:
            setattr(row, f.key, value)
        if value != old.get(f.key) and not (old.get(f.key) in (None, "") and value in (None, "")):
            changes.append({"field": "internet." + f.key, "label": f.label if f.key != "line" else "Internet line",
                            "old": F.display(f, old.get(f.key)), "new": F.display(f, value)})
    addresses.check_network(device, row)
    return changes


# ———— Wireless networks and the gear that broadcasts them ————

#: What can broadcast a wireless network: an access point, and network gear
#: of a wireless kind (Hardware's WIRELESS_KINDS: an extender, a bridge, a
#: router with Wi-Fi). The kind's choice hides the section for the others.
WIRELESS_TYPES = ("access_point", "network_device")


def is_wireless_gear(etype) -> bool:
    return etype.key in WIRELESS_TYPES


def is_wifi(etype) -> bool:
    return etype.key == "wifi"


def _wifi_networks() -> list[Entity]:
    return Entity.live().filter(Entity.type == "wifi").order_by(Entity.name).all()


def _wireless_gear() -> list[Entity]:
    from hyprvolt.modules.hardware import WIRELESS_KINDS
    wireless = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.kind.in_(WIRELESS_KINDS))
    return (Entity.live().filter((Entity.type == "access_point")
                                 | ((Entity.type == "network_device") & Entity.id.in_(wireless)))
            .order_by(Entity.name).all())


def _chosen(entity, side) -> str:
    if entity is None:
        return ""
    return ",".join(str(e.id) for e in relations.linked("broadcast_by", entity, side))


def wifi_choices(name) -> list[tuple[int, str]]:
    return [(e.id, e.name) for e in _wifi_networks()]


def wifi_values(device) -> dict:
    return {"list": _chosen(device, "target")}


def wifi_form(etype, device) -> str:
    return render_template("sheet/multi_section.html", name="s.wifi.list", label="Wireless networks",
                           choices=wifi_choices("list"), value=_chosen(device, "target"),
                           hint="The Wi-Fi networks it broadcasts.",
                           empty="No wireless networks recorded yet: add them under Network, then tick them here.")


def wifi_save(device, values, user) -> list[dict]:
    """The wireless networks a device broadcasts, ticked."""
    if "list" not in values:
        return []
    changed = relations.set_linked("broadcast_by", device, "target", values["list"], _wifi_networks(),
                                   "a wireless network", user)
    return [{"field": "wifi", "label": "Wireless networks", **changed}] if changed else []


def broadcast_choices(name) -> list[tuple[int, str]]:
    return [(e.id, e.name) for e in _wireless_gear()]


def broadcast_values(wifi) -> dict:
    return {"list": _chosen(wifi, "source")}


def broadcast_form(etype, wifi) -> str:
    return render_template("sheet/multi_section.html", name="s.broadcast.list", label="Broadcast by",
                           choices=broadcast_choices("list"), value=_chosen(wifi, "source"),
                           hint="The access points, extenders, bridges and Wi-Fi routers that broadcast it.",
                           empty="No access points or other wireless gear recorded yet.")


def broadcast_save(wifi, values, user) -> list[dict]:
    """The gear that broadcasts a wireless network, ticked."""
    if "list" not in values:
        return []
    changed = relations.set_linked("broadcast_by", wifi, "source", values["list"], _wireless_gear(),
                                   "wireless gear", user)
    return [{"field": "broadcast", "label": "Broadcast by", **changed}] if changed else []


# ———— VLANs and subnets, and the gear that carries them ————

#: What can carry a VLAN or a subnet: a firewall, and network gear of a
#: kind that does (Hardware's CARRIER_KINDS: a switch, a router, a modem
#: that is the gateway). The kind's choice hides the section for the others.
CARRIER_TYPES = ("network_device", "firewall")
SEGMENT_TYPES = ("vlan", "subnet")


def is_carrier_gear(etype) -> bool:
    return etype.key in CARRIER_TYPES


def is_segment(etype) -> bool:
    return etype.key in SEGMENT_TYPES


def _segments() -> list[Entity]:
    return Entity.live().filter(Entity.type.in_(SEGMENT_TYPES)).order_by(Entity.name).all()


def _carrier_gear() -> list[Entity]:
    from hyprvolt.modules.hardware import CARRIER_KINDS
    carriers = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.kind.in_(CARRIER_KINDS))
    return (Entity.live().filter((Entity.type == "firewall")
                                 | ((Entity.type == "network_device") & Entity.id.in_(carriers)))
            .order_by(Entity.name).all())


def _carried(entity, side) -> str:
    if entity is None:
        return ""
    return ",".join(str(e.id) for e in relations.linked("carried_by", entity, side))


def networks_choices(name) -> list[dict]:
    """The VLANs, by number, and the subnets, by range, each named for what
    it is: "Servers (VLAN 20)", "Servers 10.0.20.0/24, on VLAN 20", and
    where they are in different places, which: "Servers (VLAN 20, Annex)"."""
    details = {d.entity_id: d for d in NetworkDetail.query.filter(
        NetworkDetail.entity_id.in_([e.id for e in _segments()]))}
    places = {e.location_id for e in _segments()}
    names = dict(db.session.query(Entity.id, Entity.name).filter(
        Entity.id.in_({p for p in places if p}))) if len(places) > 1 else {}
    vlans, subnets = [], []
    for e in _segments():
        d = details.get(e.id)
        net = names.get(e.location_id)
        if e.type == "vlan":
            what = ", ".join(x for x in (f"VLAN {d.vid}" if d and d.vid else "", net) if x)
            vlans.append((d.vid if d else 0, e.id, f"{e.name} ({what})" if what else e.name))
        else:
            vlan = details.get(d.vlan) if d and d.vlan else None
            label = e.name if not d or not d.cidr or d.cidr in e.name else f"{e.name}, {d.cidr}"
            label = f"{label}, on VLAN {vlan.vid}" if vlan and vlan.vid else label
            subnets.append((addresses.ip_key(d.cidr.split("/")[0]) if d and d.cidr else (9, 0), e.id,
                            f"{label}, in {net}" if net else label))
    groups = [("VLANs", sorted(vlans)), ("Subnets", sorted(subnets, key=lambda s: (s[0], s[2])))]
    return [{"label": label, "options": [(i, text) for _, i, text in rows]} for label, rows in groups if rows]


def networks_values(device) -> dict:
    return {"list": _carried(device, "target")}


def networks_form(etype, device) -> str:
    return render_template("sheet/multi_section.html", name="s.networks.list", label="Networks",
                           choices=networks_choices("list"), value=_carried(device, "target"),
                           hint="The VLANs and subnets it carries. A subnet on a VLAN comes with the VLAN.",
                           empty="No VLANs or subnets recorded yet: add them under Network, then tick them here.")


def networks_save(device, values, user) -> list[dict]:
    """The VLANs and subnets a switch, router or firewall carries, ticked."""
    if "list" not in values:
        return []
    changed = relations.set_linked("carried_by", device, "target", values["list"], _segments(),
                                   "a VLAN or subnet", user)
    return [{"field": "networks", "label": "Networks", **changed}] if changed else []


def carriers_choices(name) -> list[tuple[int, str]]:
    return [(e.id, e.name) for e in _carrier_gear()]


def carriers_values(segment) -> dict:
    return {"list": _carried(segment, "source")}


def carriers_form(etype, segment) -> str:
    return render_template("sheet/multi_section.html", name="s.carriers.list", label="Carried by",
                           choices=carriers_choices("list"), value=_carried(segment, "source"),
                           hint="The switches, routers and firewalls it runs through.",
                           empty="No switches, routers or firewalls recorded yet.")


def carriers_save(segment, values, user) -> list[dict]:
    """The gear that carries a VLAN or subnet, ticked."""
    if "list" not in values:
        return []
    changed = relations.set_linked("carried_by", segment, "source", values["list"], _carrier_gear(),
                                   "a switch, router or firewall", user)
    return [{"field": "carriers", "label": "Carried by", **changed}] if changed else []


def carriers_of(segment_ids) -> set[int]:
    """The gear that carries any of these VLANs or subnets, or the VLAN of
    any of these subnets."""
    ids = set(segment_ids)
    ids |= {d.vlan for d in NetworkDetail.query.filter(NetworkDetail.entity_id.in_(ids)) if d.vlan}
    return {r.target_id for r in Relationship.query.filter(Relationship.kind == "carried_by",
                                                           Relationship.source_id.in_(ids))}


# ———— The site setup guide's cables step ————

def _unit_devices(scope, unit=None):
    """The devices of the part of the site the Cables step is doing (or
    ``unit``), or None for all of it."""
    from .cabling import unit_devices
    return unit_devices(scope, unit)


def setup_ends(scope, unit=None) -> list[dict]:
    """The free ends a cable can go to. Cabling one part of a site (a
    building), its own first, then those of each other part under its name,
    "Main · Switches", for a cable between buildings."""
    from hyprvolt.core import guide

    from .cabling import parts, units
    ends = ports.free_ends()

    def groups(keep, prefix=""):
        out = [{"label": prefix + g["label"], "options": [(f"device:{d.id}", d.name) for d in g["devices"]
                                                          if keep(d.id)]}
               for g in ends["groups"]]
        out += [{"label": f"{prefix}{g['device']} ports", "options": [(f"port:{p.id}", p.label) for p in g["ports"]
                                                                       if keep(p.device_id)]}
                for g in ends["ports"]]
        return [g for g in out if g["options"]]
    key = unit if unit is not None else guide.unit()
    only = _unit_devices(scope, key)
    if only is None:
        return groups(lambda i: True)
    out, where = groups(lambda i: i in only), parts(scope)
    for other, name in units(scope):
        if other not in ("all", str(key)):
            out += groups(lambda i, other=other: where.get(i) == other, f"{name} · ")
    return out


def _setup_end(value):
    kind, _, raw = str(value or "").partition(":")
    end = db.session.get(Port, int(raw)) if kind == "port" and raw.isdigit() else \
        records.live(int(raw)) if kind == "device" and raw.isdigit() else None
    device = end.device_id if isinstance(end, Port) else end.id if end is not None else None
    if end is None or records.live(device) is None:
        raise Invalid("Choose both ends of the cable.")
    return end


def setup_cable(values, scope, user) -> None:
    """A cable from the guide; with no label given, one from its network."""
    from . import cable_labels
    a, b = _setup_end(values.get("from")), _setup_end(values.get("to"))
    label = str(values.get("label") or "").strip() or cable_labels.label_for(a, b, cable_labels.taken())
    ports.connect(a, b, {"label": label}, user)


def _end_value(port: Port) -> str:
    return f"port:{port.id}" if port.name else f"device:{port.device_id}"


def _with_end(groups: list[dict], port: Port) -> list[dict]:
    """The ends to choose from, with this cable's own end among them (it is
    taken, so not one of the free ones), in its group."""
    value = _end_value(port)
    if any(value == v for g in groups for v, _ in g["options"]):
        return groups
    label = f"{port.device.name} ports" if port.name else ports.group_label(ports.group_of(port.device))
    out = [dict(g, options=list(g["options"])) for g in groups]
    group = next((g for g in out if g["label"] == label), None)
    if group is None:
        group = {"label": label, "options": []}
        out.append(group)
    group["options"].append((value, port.label))
    group["options"].sort(key=lambda o: o[1].lower())
    return out


def _label_order(cable: Cable) -> tuple:
    """Cables in label order, numbers as numbers (20-2 before 20-10), the
    unlabeled last, then by their ends."""
    bits = tuple((0, int(b), "") if b.isdigit() else (1, 0, b.lower())
                 for b in re.split(r"(\d+)", cable.label) if b)
    return (not cable.label, bits, cable.a.label.lower(), cable.b.label.lower())


def setup_rows(scope) -> list[dict]:
    """Every cable as a row (of the part of the site being cabled, one with
    an end in it): either end to change, and its label. Each row's choices
    are the free ends and its own."""
    out, free, only = [], setup_ends(scope), _unit_devices(scope)
    eager = (joinedload(Cable.a).joinedload(Port.device), joinedload(Cable.b).joinedload(Port.device))
    cables = [c for c in Cable.query.options(*eager)
              if (only is None or c.a.device_id in only or c.b.device_id in only)
              and c.a.device.deleted_at is None and c.b.device.deleted_at is None]
    tree = _CableTree(cables)
    for c in cables:
        up, down = tree.ends(c)
        # Folded: its label, then its two ends; under the device nearer the internet.
        out.append({"id": c.id, "label": f"the cable from {c.a.label} to {c.b.label}",
                    "title": f"{c.a.label} → {c.b.label}", "badge": "label", "in_title": ("from", "to", "label"),
                    "values": {"from": _end_value(c.a), "to": _end_value(c.b), "label": c.label},
                    "choices": {"from": _with_end(free, c.a), "to": _with_end(free, c.b)},
                    "text": {}, "locked": (), "absent": (), "group": tree.heading(up), "depth": tree.depth(up),
                    "sort": (tree.order[up], not tree.is_gear(down), _label_order(c))})
    return sorted(out, key=lambda r: r["sort"])


class _CableTree:
    """The cabled devices as a tree from where the internet comes in: the
    device a line comes in at, else a modem, a router or a firewall, then
    outward along the cables (and over MoCA pairs and wireless bridges),
    switches before what plugs into them. A part not cabled to it hangs
    from its own most upstream device."""

    MAX_DEPTH = 6

    def __init__(self, cables):
        from .impact import _pairs
        near: dict[int, set[int]] = {}
        for c in cables:
            near.setdefault(c.a.device_id, set()).add(c.b.device_id)
            near.setdefault(c.b.device_id, set()).add(c.a.device_id)
        for a, b, _ in _pairs():
            if a in near or b in near:
                near.setdefault(a, set()).add(b)
                near.setdefault(b, set()).add(a)
        self.devices = {e.id: e for e in Entity.query.filter(Entity.id.in_(near), Entity.deleted_at.is_(None))}
        self.lines = line_ids()
        self.levels, self.order = {}, {}
        children: dict[int, list[int]] = {}
        left = set(self.devices)
        while left:
            root = min(left, key=self.rank)
            # Every device a line comes in at in this part is a top of it: two ISPs side by side.
            roots = [root]
            if root in self.lines:
                part, todo = {root}, [root]
                while todo:
                    for j in near.get(todo.pop(), ()):
                        if j in left and j not in part:
                            part.add(j)
                            todo.append(j)
                roots = sorted((i for i in part if i in self.lines), key=self.rank)
            for r in roots:
                self.levels[r] = 0
            queue, found = list(roots), list(roots)
            while queue:
                i = queue.pop(0)
                for j in sorted(near.get(i, ()), key=self.rank):
                    if j in self.devices and j not in self.levels:
                        self.levels[j] = self.levels[i] + 1
                        children.setdefault(i, []).append(j)
                        queue.append(j)
                        found.append(j)
            left -= set(found)
            stack = list(reversed(roots))   # in tree order: each device, then what hangs from it
            while stack:
                i = stack.pop()
                self.order[i] = len(self.order)
                stack.extend(reversed(children.get(i, [])))

    def rank(self, device_id):
        e = self.devices.get(device_id)
        if e is None:
            return (2, (99, ""), "")
        return (0 if device_id in self.lines else 1, ports._rank(ports.group_of(e)), e.name.lower())

    def is_gear(self, device_id) -> bool:
        """Network gear, listed before the devices plugged in beside it."""
        e = self.devices.get(device_id)
        return e is not None and ports.group_of(e) in ports.ORDER[:ports.ORDER.index("network_device") + 1]

    def ends(self, cable) -> tuple[int, int]:
        """(the end nearer the internet, the other), as device ids."""
        a, b = cable.a.device_id, cable.b.device_id
        if (self.levels.get(a, 99), self.rank(a)) <= (self.levels.get(b, 99), self.rank(b)):
            return a, b
        return b, a

    def depth(self, device_id) -> int:
        return min(self.levels.get(device_id, 0), self.MAX_DEPTH)

    def heading(self, device_id) -> str:
        """What a group of cables hangs from: "Cable modem · Modem, the internet comes in"."""
        e = self.devices.get(device_id)
        if e is None:
            return ""
        from hyprvolt.modules.hardware import NETWORK_KINDS
        kind = dict(NETWORK_KINDS).get(ports.role(e)) if e.type == "network_device" else None
        etype = registry().type(e.type)
        what = kind or (etype.label if etype else e.type)
        return f"{e.name} · {what}" + (", the internet comes in" if device_id in self.lines else "")


def _setup_cable_or_404(cable_id) -> Cable:
    cable = db.session.get(Cable, cable_id)
    if cable is None:
        abort(404, description="That cable no longer exists.")
    return cable


def setup_update(cable_id, values, user) -> None:
    """A cable's label, or either end moved to another port or device."""
    cable = _setup_cable_or_404(cable_id)
    if "label" in values:
        ports.relabel(cable, values["label"], user)
    for name, side in (("from", "a"), ("to", "b")):
        if name in values:
            ports.move_end(cable, side, _setup_end(values[name]), user)


def setup_delete(cable_id) -> dict:
    return {"url": "/network/cables", "body": ports.disconnect(_setup_cable_or_404(cable_id))}


# ———— Sidebar filters and the dashboard ————

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
            through = {"device_id": step["through"].id, "device": step["through"].name}
            if step.get("coax") is not None:
                through["coax"] = {"device_id": step["coax"].id, "device": step["coax"].name}
            path.append({"through": through})
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
