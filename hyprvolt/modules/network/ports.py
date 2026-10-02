"""Ports on devices and the cables between them, and tracing a cable path
from one end to the other through any patch panels on the way.

A device is cabled as a whole unless its ports are recorded one by one
(``PortsRecorded``): each cable then ends at a port with no name, made with
the cable and removed with it."""
from sqlalchemy.orm import contains_eager, joinedload

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db
from hyprvolt.modules.hardware.models import HardwareDetail

from .models import PORT_KINDS, SPEEDS, Cable, Port, PortsRecorded

MAX_PORTS = 128


def is_cabled(etype) -> bool:
    return "cabled" in etype.traits


def before_retype(entity: Entity, old, new) -> None:
    """Ports stay with a record that can have them: one that would lose
    them keeps them until they are removed."""
    if is_cabled(old) and not is_cabled(new):
        n = Port.query.filter_by(device_id=entity.id).count()
        if n:
            raise Invalid(f"It has {n} {'port or cable' if n == 1 else 'ports or cables'}, and a {new.text()} "
                          f"can't. Remove {'it' if n == 1 else 'them'} from its Cabling tab first.")


def role(entity: Entity) -> str:
    """What a device is to the network: modem, router, firewall, switch,
    moca, bridge, patch_panel, extender, peripheral, or "device"."""
    if entity.type in ("firewall", "peripheral"):
        return entity.type
    detail = db.session.get(HardwareDetail, entity.id) if entity.type == "network_device" else None
    kind = detail.kind if detail is not None else None
    return kind if kind and kind != "other" else "device"


#: The order devices are listed in to cable, by what each is: the network
#: from where the internet comes in, then what plugs into it.
ORDER = ("modem", "router", "firewall", "switch", "access_point", "extender", "bridge", "moca", "patch_panel",
         "network_device", "server", "nas", "workstation", "printer", "ip_phone", "ip_camera", "peripheral", "ups")


def group_of(entity: Entity) -> str:
    """What a device is listed under: its kind of network gear, else its
    type."""
    r = role(entity)
    return entity.type if r == "device" else r


def group_label(key: str) -> str:
    """A group's heading: "Switches", "Firewalls", "Other network gear"."""
    from hyprvolt.manifest import plural
    from hyprvolt.modules.hardware import NETWORK_KINDS
    from hyprvolt.registry import current as registry
    if key == "network_device":
        return "Other network gear"
    kinds = dict(NETWORK_KINDS)
    if key in kinds:
        return plural(kinds[key])
    etype = registry().type(key)
    return etype.plural if etype else key


def _rank(key: str):
    return (ORDER.index(key) if key in ORDER else len(ORDER), key)


def records_ports(device_id: int) -> bool:
    return db.session.get(PortsRecorded, device_id) is not None


def recorded_ids() -> set[int]:
    return {i for (i,) in db.session.query(PortsRecorded.device_id)}


def record_ports(device: Entity, on: bool, user=None) -> list[dict]:
    """Turn recording each port on or off. Off keeps the ports it has, out
    of sight, and its cables; on shows them again."""
    on, was = _bool(on), records_ports(device.id)
    if was == on:
        return []
    if on:
        db.session.add(PortsRecorded(device_id=device.id))
    else:
        db.session.delete(db.session.get(PortsRecorded, device.id))
    db.session.flush()
    return [{"field": "cabling", "label": "Record each port", "old": "Yes" if was else "No",
             "new": "Yes" if on else "No"}]


def port_limit(device_id: int) -> int | None:
    """How many cables a device cabled as a whole takes: its port count
    (Hardware's Ports), if it has one. One with its ports recorded takes a
    cable on each of them instead."""
    if records_ports(device_id):
        return None
    detail = db.session.get(HardwareDetail, device_id)
    return detail.ports if detail is not None and detail.ports else None


def cabled_counts(device_ids) -> dict[int, int]:
    """How many cables each device has."""
    ends = (db.session.query(Port.device_id, db.func.count(Port.id))
            .join(Cable, (Cable.a_id == Port.id) | (Cable.b_id == Port.id))
            .filter(Port.device_id.in_(list(device_ids))).group_by(Port.device_id))
    return dict(ends.all())


def ports_of(device_id: int) -> list[Port]:
    return (Port.query.filter_by(device_id=device_id).options(joinedload(Port.vlan), joinedload(Port.pair))
            .order_by(Port.position, Port.id).all())


def free_ends(exclude: int | None = None) -> dict:
    """Where a cable can go: devices cabled as a whole, and the free ports
    of those with their ports recorded, grouped by device."""
    from hyprvolt.registry import current as registry
    keys = [t.key for t in registry().enabled_types() if is_cabled(t)]
    recorded = recorded_ids()
    everyone = Entity.live().filter(Entity.type.in_(keys), Entity.id != (exclude or 0)).order_by(Entity.name)
    wholes = [e for e in everyone if e.id not in recorded]
    # A device whose every port is cabled takes no more.
    limits = {d.entity_id: d.ports for d in HardwareDetail.query.filter(
        HardwareDetail.entity_id.in_([e.id for e in wholes]), HardwareDetail.ports > 0)}
    used = cabled_counts(limits)
    wholes = [e for e in wholes if e.id not in limits or used.get(e.id, 0) < limits[e.id]]
    taken = {i for c in db.session.query(Cable.a_id, Cable.b_id) for i in c}
    by_kind = {}
    for e in wholes:
        by_kind.setdefault(group_of(e), []).append(e)
    groups = [{"label": group_label(k), "devices": by_kind[k]} for k in sorted(by_kind, key=_rank)]
    own = {}
    for p in (Port.query.join(Entity, Entity.id == Port.device_id).options(contains_eager(Port.device))
              .filter(Entity.deleted_at.is_(None), Entity.type.in_(keys), Port.device_id != (exclude or 0),
                      Port.device_id.in_(recorded), Port.name != "")
              .order_by(Entity.name, Port.position)):
        if p.id not in taken:
            own.setdefault(p.device, []).append(p)
    # Devices with their ports recorded: a group each, in the same order.
    devices = sorted(own, key=lambda d: (_rank(group_of(d)), d.name.lower()))
    return {"devices": wholes, "groups": groups,
            "ports": [{"device": d.name, "ports": own[d]} for d in devices]}


def cable_of(port: Port) -> Cable | None:
    return Cable.query.filter((Cable.a_id == port.id) | (Cable.b_id == port.id)).first()


def cables_for(ports) -> dict[int, Cable]:
    """port id -> its cable, for a page of ports in one query."""
    ids = [p.id for p in ports]
    if not ids:
        return {}
    out = {}
    eager = (joinedload(Cable.a).joinedload(Port.device), joinedload(Cable.b).joinedload(Port.device))
    for c in Cable.query.filter(Cable.a_id.in_(ids) | Cable.b_id.in_(ids)).options(*eager):
        out[c.a_id] = c
        out[c.b_id] = c
    return out


def speed_label(mbps) -> str:
    return dict(SPEEDS).get(mbps, f"{mbps} Mb" if mbps else "")


def kind_label(kind) -> str:
    return dict(PORT_KINDS).get(kind, kind or "")


def trace(port: Port) -> list[dict]:
    """The path from ``port``: [{"port"}, {"cable"}, {"port"}, {"through"},
    {"port"}, ...]. A patch panel's paired port is "through"; a loop stops
    the walk instead of following it."""
    path, seen, p = [], set(), port
    while p is not None and p.id not in seen:
        seen.add(p.id)
        path.append({"port": p})
        cable = cable_of(p)
        if cable is None:
            break
        other = cable.other(p)
        path.append({"cable": cable})
        if other.id in seen:
            break
        seen.add(other.id)
        path.append({"port": other})
        if other.pair is None or other.device.deleted_at is not None:
            break
        path.append({"through": other.device})
        p = other.pair
    return path


def trace_text(port: Port) -> str:
    bits = []
    for step in trace(port):
        if "port" in step:
            bits.append(step["port"].label)
        elif "cable" in step:
            bits.append("→")
        else:
            bits.append("⇄")
    return " ".join(bits)


# ———— Changes, each written to the history of the devices it touches ————

def _int_or_none(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _bool(value) -> bool:
    return str(value).lower() in ("1", "true", "on", "yes") if not isinstance(value, bool) else value


def _text(data, key, limit):
    return " ".join(str(data.get(key) or "").split())[:limit]


def _speed(data):
    raw = data.get("speed_mbps")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise Invalid("The speed must be a whole number of megabits.") from None
    if not 1 <= value <= 1_000_000:
        raise Invalid("The speed must be between 1 and 1,000,000 megabits.")
    return value


def _kind(data):
    kind = data.get("kind") or "rj45"
    if kind not in dict(PORT_KINDS):
        raise Invalid("Choose what kind of port it is.")
    return kind


def _vlan(data):
    raw = data.get("vlan_id")
    if raw in (None, "", 0, "0"):
        return None
    vlan = records.live(raw)
    if vlan is None or vlan.type != "vlan":
        raise Invalid("Choose a VLAN that exists.")
    return vlan.id


def add_ports(device: Entity, data: dict, user=None) -> list[Port]:
    """``prefix`` and the numbers ``first`` to ``last``: "Port " 1 to 24
    makes Port 1 … Port 24. With ``rear`` they are a patch panel's: Front 1
    and Rear 1, paired, and so on."""
    prefix = str(data.get("prefix") if data.get("prefix") is not None else "Port ")[:40]
    try:
        first = int(data["first"]) if data.get("first") not in (None, "") else 1
        last = int(data["last"]) if data.get("last") not in (None, "") else first
    except (TypeError, ValueError):
        raise Invalid("The first and last numbers must be whole numbers.") from None
    if first < 0 or last < first:
        raise Invalid("The last number must be at least the first.")
    rear = _bool(data.get("rear") or False)
    count = (last - first + 1) * (2 if rear else 1)
    existing = ports_of(device.id)
    if len(existing) + count > MAX_PORTS:
        raise Invalid(f"A device can have at most {MAX_PORTS} ports.")
    names = {p.name.lower() for p in existing}
    position = max((p.position for p in existing), default=0)
    made = []
    kind, speed, poe = _kind(data), _speed(data), _bool(data.get("poe") or False)
    for n in range(first, last + 1):
        # A patch panel's pairs are Front 1 and Rear 1, whatever the prefix.
        pair = []
        for full in ((f"Front {n}", f"Rear {n}") if rear else (f"{prefix}{n}".strip(),)):
            if full.lower() in names:
                raise Invalid(f"{device.name} already has a port called {full}.")
            names.add(full.lower())
            position += 1
            port = Port(device_id=device.id, name=full, position=position, kind=kind, speed_mbps=speed, poe=poe)
            db.session.add(port)
            pair.append(port)
        db.session.flush()
        if len(pair) == 2:
            pair[0].pair_id, pair[1].pair_id = pair[1].id, pair[0].id
        made += pair
    if made:
        text = made[0].name if len(made) == 1 else f"{made[0].name} to {made[-1].name} ({len(made)})"
        changes = [{"field": "ports", "label": "Ports", "old": "", "new": text}] + record_ports(device, True)
        records.audit(device, "added ports", changes, user)
    return made


PORT_FIELDS = ("name", "kind", "speed_mbps", "poe", "mac", "vlan_id", "tagged", "description")


def port_json(p: Port) -> dict:
    cable = cable_of(p)
    other = cable.other(p) if cable else None
    return {"id": p.id, "device_id": p.device_id, "name": p.name, "kind": p.kind, "speed_mbps": p.speed_mbps,
            "poe": p.poe, "mac": p.mac, "vlan_id": p.vlan_id, "tagged": p.tagged, "description": p.description,
            "pair_id": p.pair_id, "position": p.position,
            "cable": {"id": cable.id, "label": cable.label, "color": cable.color, "length_m": cable.length_m,
                      "port_id": other.id, "device_id": other.device_id, "to": other.label} if cable else None}


def edit_port(port: Port, data: dict, user=None) -> None:
    changes, was = [], port.name

    def note(label, old, new):
        if old != new:
            changes.append({"field": "port", "label": f"{was}: {label}", "old": old, "new": new})
    if "name" in data:
        name = _text(data, "name", 60)
        if not name:
            raise Invalid("Give the port a name.")
        if name.lower() != port.name.lower() and any(p.name.lower() == name.lower() for p in ports_of(port.device_id)):
            raise Invalid(f"{port.device.name} already has a port called {name}.")
        note("name", port.name, name)
        port.name = name
    if "kind" in data:
        kind = _kind(data)
        note("kind", kind_label(port.kind), kind_label(kind))
        port.kind = kind
    if "speed_mbps" in data:
        speed = _speed(data)
        note("speed", speed_label(port.speed_mbps), speed_label(speed))
        port.speed_mbps = speed
    if "poe" in data:
        poe = _bool(data["poe"])
        note("PoE", "Yes" if port.poe else "No", "Yes" if poe else "No")
        port.poe = poe
    if "mac" in data:
        mac = _text(data, "mac", 17).lower()
        note("MAC", port.mac, mac)
        port.mac = mac
    if "vlan_id" in data:
        vlan = _vlan(data)
        old = port.vlan.name if port.vlan else ""
        port.vlan_id = vlan
        db.session.flush()
        db.session.refresh(port)
        note("VLAN", old, port.vlan.name if port.vlan else "")
    if "tagged" in data:
        tagged = _text(data, "tagged", 200)
        note("tagged VLANs", port.tagged, tagged)
        port.tagged = tagged
    if "description" in data:
        text = _text(data, "description", 200)
        note("description", port.description, text)
        port.description = text
    if changes:
        records.audit(port.device, "edited a port", changes, user)


def _device_end(device: Entity) -> Port:
    """A port with no name on a device cabled as a whole, for one cable."""
    last = db.session.query(db.func.max(Port.position)).filter(Port.device_id == device.id).scalar() or 0
    port = Port(device_id=device.id, name="", position=last + 1)
    db.session.add(port)
    db.session.flush()
    return port


def connect(port: Port | Entity, other: Port | Entity, data: dict, user=None) -> Cable:
    """Cable two ends, each a port or a device whose ports aren't recorded
    (which gets a port with no name for it)."""
    ends = [port, other]
    for end in ends:
        if isinstance(end, Entity) and records_ports(end.id):
            raise Invalid(f"{end.name} has its ports recorded one by one: choose one of them.")
    for end in ends:
        limit = port_limit(end.id) if isinstance(end, Entity) else None
        if limit is not None and cabled_counts([end.id]).get(end.id, 0) >= limit:
            raise Invalid(f"{end.name} has {limit} {'port' if limit == 1 else 'ports'}, and "
                          f"{'it is' if limit == 1 else 'all of them are'} cabled. Give it more ports, or "
                          f"record its ports one by one.")
    devices = [e.id if isinstance(e, Entity) else e.device_id for e in ends]
    if devices[0] == devices[1] and any(isinstance(e, Entity) for e in ends):
        raise Invalid("A cable goes to another device.")
    named = [e for e in ends if isinstance(e, Port)]
    if len(named) == 2:
        if port.id == other.id:
            raise Invalid("A cable needs two different ports.")
        if port.pair_id == other.id:
            raise Invalid("Those two are the front and rear of the same patch panel port.")
    for p in named:
        existing = cable_of(p)
        if existing is not None:
            raise Invalid(f"{p.label} already has a cable, to {existing.other(p).label}.")
    length = data.get("length_m")
    try:
        length = float(length) if length not in (None, "") else None
    except (TypeError, ValueError):
        raise Invalid("The length must be a number of meters.") from None
    if length is not None and not 0 < length <= 10_000:
        raise Invalid("The length must be between 0 and 10,000 meters.")
    port, other = (_device_end(e) if isinstance(e, Entity) else e for e in ends)
    cable = Cable(a_id=port.id, b_id=other.id, label=_text(data, "label", 60), color=_text(data, "color", 30),
                  length_m=length)
    db.session.add(cable)
    db.session.flush()
    for p, o in ((port, other), (other, port)):
        records.audit(p.device, "cabled", [{"field": "cable", "label": p.name or "Cable", "old": "",
                                            "new": o.label}], user)
    return cable


def end_json(port: Port, far: bool = False) -> dict:
    """One end of a cable as the cable route takes it: a port by its id, or
    a device cabled as a whole by the device's."""
    if not port.name:
        return {"other_device_id" if far else "device_id": port.device_id}
    return {"other_id" if far else "port_id": port.id}


def relabel(cable: Cable, label, user=None) -> None:
    """A cable's label, changed, in the history of both its devices."""
    new, old = _text({"label": label}, "label", 60), cable.label
    if new == old:
        return
    cable.label = new
    for p, o in ((cable.a, cable.b), (cable.b, cable.a)):
        records.audit(p.device, "edited a cable", [{"field": "cable", "label": f"{p.name or 'Cable'} to {o.label}",
                                                     "old": old, "new": new}], user)


def disconnect(cable: Cable) -> dict:
    """Remove a cable, and the ports with no name it ended at; returns what
    puts it back."""
    a, b = cable.a, cable.b
    snapshot = {**end_json(a), **end_json(b, far=True), "label": cable.label, "color": cable.color,
                "length_m": cable.length_m}
    for p, o in ((a, b), (b, a)):
        records.audit(p.device, "uncabled", [{"field": "cable", "label": p.name or "Cable", "old": o.label,
                                              "new": ""}])
    db.session.delete(cable)
    db.session.flush()
    for p in (a, b):
        if not p.name:
            db.session.delete(p)
    return snapshot


def remove_port(port: Port) -> dict:
    """Delete a port and its cable; returns what puts both back."""
    snapshot = {k: getattr(port, k) for k in PORT_FIELDS}
    snapshot.update({"id": port.id, "device_id": port.device_id, "position": port.position, "pair_id": port.pair_id})
    cable = cable_of(port)
    if cable is not None:
        other = cable.other(port)
        snapshot["cable"] = {**end_json(other, far=True), "label": cable.label, "color": cable.color,
                             "length_m": cable.length_m}
        db.session.delete(cable)
        db.session.flush()
        if not other.name:
            db.session.delete(other)
    if port.pair is not None:
        port.pair.pair_id = None
    records.audit(port.device, "removed a port", [{"field": "ports", "label": "Port", "old": port.name or "Cable",
                                                   "new": ""}])
    db.session.delete(port)
    return snapshot


def restore_port(device: Entity, data: dict) -> Port:
    name = _text(data, "name", 60) or "Port"
    if any(p.name.lower() == name.lower() for p in ports_of(device.id)):
        raise Invalid(f"{device.name} has a port called {name} again.")
    try:
        position = int(data.get("position") or 0)
    except (TypeError, ValueError):
        position = 0
    port = Port(device_id=device.id, name=name, position=position,
                kind=_kind(data), speed_mbps=_speed(data), poe=_bool(data.get("poe") or False),
                mac=_text(data, "mac", 17), vlan_id=_vlan(data), tagged=_text(data, "tagged", 200),
                description=_text(data, "description", 200))
    same = _int_or_none(data.get("id"))
    if same and db.session.get(Port, same) is None:
        port.id = same                 # the same id, so links and a trace read as before
    db.session.add(port)
    db.session.flush()
    pair = db.session.get(Port, _int_or_none(data.get("pair_id")) or 0)
    if pair is not None and pair.device_id == device.id and pair.pair_id is None:
        port.pair_id, pair.pair_id = pair.id, port.id
    cable = data.get("cable") if isinstance(data.get("cable"), dict) else {}
    other = db.session.get(Port, _int_or_none(cable.get("other_id")) or 0)
    if other is not None and (records.live(other.device_id) is None or cable_of(other) is not None):
        other = None
    far = records.live(_int_or_none(cable.get("other_device_id")) or 0)
    if other is None and far is not None and not records_ports(far.id):
        other = far
    if other is not None:
        connect(port, other, cable)
    records.audit(device, "added ports", [{"field": "ports", "label": "Ports", "old": "", "new": port.name}])
    return port
