"""Ports on devices and the cables between them, and tracing a cable path
from one end to the other through any patch panels on the way."""
from sqlalchemy.orm import joinedload

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from .models import PORT_KINDS, SPEEDS, Cable, Port

MAX_PORTS = 128


def is_cabled(etype) -> bool:
    return "cabled" in etype.traits


def ports_of(device_id: int) -> list[Port]:
    return (Port.query.filter_by(device_id=device_id).options(joinedload(Port.vlan), joinedload(Port.pair))
            .order_by(Port.position, Port.id).all())


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
        records.audit(device, "added ports", [{"field": "ports", "label": "Ports", "old": "", "new": text}], user)
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


def connect(port: Port, other: Port, data: dict, user=None) -> Cable:
    if port.id == other.id:
        raise Invalid("A cable needs two different ports.")
    if port.pair_id == other.id:
        raise Invalid("Those two are the front and rear of the same patch panel port.")
    for p in (port, other):
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
    cable = Cable(a_id=port.id, b_id=other.id, label=_text(data, "label", 60), color=_text(data, "color", 30),
                  length_m=length)
    db.session.add(cable)
    db.session.flush()
    for p, o in ((port, other), (other, port)):
        records.audit(p.device, "cabled", [{"field": "cable", "label": p.name, "old": "", "new": o.label}], user)
    return cable


def disconnect(cable: Cable) -> dict:
    """Remove a cable; returns what puts it back."""
    snapshot = {"port_id": cable.a_id, "other_id": cable.b_id, "label": cable.label, "color": cable.color,
                "length_m": cable.length_m}
    for p, o in ((cable.a, cable.b), (cable.b, cable.a)):
        records.audit(p.device, "uncabled", [{"field": "cable", "label": p.name, "old": o.label, "new": ""}])
    db.session.delete(cable)
    return snapshot


def remove_port(port: Port) -> dict:
    """Delete a port and its cable; returns what puts both back."""
    snapshot = {k: getattr(port, k) for k in PORT_FIELDS}
    snapshot.update({"id": port.id, "device_id": port.device_id, "position": port.position, "pair_id": port.pair_id})
    cable = cable_of(port)
    if cable is not None:
        other = cable.other(port)
        snapshot["cable"] = {"other_id": other.id, "label": cable.label, "color": cable.color,
                             "length_m": cable.length_m}
        db.session.delete(cable)
    if port.pair is not None:
        port.pair.pair_id = None
    records.audit(port.device, "removed a port", [{"field": "ports", "label": "Port", "old": port.name, "new": ""}])
    db.session.delete(port)
    return snapshot


def restore_port(device: Entity, data: dict) -> Port:
    if any(p.name.lower() == str(data.get("name") or "").lower() for p in ports_of(device.id)):
        raise Invalid(f"{device.name} has a port called {data.get('name')} again.")
    port = Port(device_id=device.id, name=_text(data, "name", 60) or "Port", position=int(data.get("position") or 0),
                kind=_kind(data), speed_mbps=_speed(data), poe=_bool(data.get("poe") or False),
                mac=_text(data, "mac", 17), vlan_id=_vlan(data), tagged=_text(data, "tagged", 200),
                description=_text(data, "description", 200))
    if data.get("id") and db.session.get(Port, int(data["id"])) is None:
        port.id = int(data["id"])      # the same id, so links and a trace read as before
    db.session.add(port)
    db.session.flush()
    pair = db.session.get(Port, int(data["pair_id"])) if data.get("pair_id") else None
    if pair is not None and pair.device_id == device.id and pair.pair_id is None:
        port.pair_id, pair.pair_id = pair.id, port.id
    cable = data.get("cable") or {}
    other = db.session.get(Port, int(cable["other_id"])) if cable.get("other_id") else None
    if other is not None and cable_of(other) is None:
        connect(port, other, cable)
    records.audit(device, "added ports", [{"field": "ports", "label": "Ports", "old": "", "new": port.name}])
    return port
