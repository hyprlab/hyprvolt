"""What the cabling says about dependencies, worked out from the cables
rather than recorded as links, so it follows every change to them.

A cable path runs between two devices through any patch panels on the way.
A device cabled to network gear (a switch, router, firewall, modem, MoCA
adapter or any other network device) needs that gear. Between two pieces of
gear, or two other devices, the one further from where the internet comes in
needs the nearer one; at the same distance (a second link between two
switches) neither needs the other. A pair of MoCA adapters, or of wireless
bridges, counts as a link between the two ends, the far end needing the
near one.
"""
from collections import deque

from sqlalchemy.orm import joinedload

from hyprvolt.core.models import Entity, Relationship

from . import ports
from .models import Cable, Port

#: Record types that are network gear: what a device plugs into.
GEAR_TYPES = ("network_device", "firewall")
#: Managed over the network, and working without it.
MANAGED_ONLY = ("ups", "peripheral")

# (read from the record that needs, read from the one it needs)
PLUGS = ("plugs into", "has plugged in")
UPLINK = ("uplinks to", "is the uplink for")
PAIRS = {"coax_link": ("gets the network over coax from", "passes the network over coax to"),
         "wireless_link": ("gets the network over the air from", "passes the network over the air to")}


class Path:
    """A cable path between two devices: the ports at its ends, the patch
    panels it passes through and the labels of its cables."""

    def __init__(self, a: Port, b: Port, via: list[Entity], labels: list[str]):
        self.a, self.b, self.via, self.labels = a, b, via, labels

    def end(self, device_id: int) -> tuple[Port, Port]:
        """(this device's end, the far end)."""
        return (self.a, self.b) if self.a.device_id == device_id else (self.b, self.a)


def paths() -> list[Path]:
    """Every cable path, once, between two live devices that aren't the
    same one."""
    eager = (joinedload(Cable.a).joinedload(Port.device), joinedload(Cable.b).joinedload(Port.device))
    cables = Cable.query.options(*eager).order_by(Cable.id).all()
    by_port = {}
    for c in cables:
        by_port[c.a_id] = by_port[c.b_id] = c
    out, done = [], set()
    for c in cables:
        if c.id in done:
            continue
        done.add(c.id)
        ends, via, labels = [], [], [c.label] if c.label else []
        for start in (c.a, c.b):
            p, seen = start, set()
            # Into a patch panel's port and out of its pair, along the next cable.
            while p.pair_id is not None and p.pair_id in by_port and p.id not in seen:
                seen.add(p.id)
                via.append(p.device)
                nxt = by_port[p.pair_id]
                if nxt.id in done:
                    break
                done.add(nxt.id)
                if nxt.label:
                    labels.append(nxt.label)
                p = nxt.other(p.pair)
            ends.append(p)
        a, b = ends
        if a.device_id == b.device_id or a.device.deleted_at is not None or b.device.deleted_at is not None:
            continue
        out.append(Path(a, b, list(dict.fromkeys(via)), labels))
    return out


def _pairs() -> list[tuple[int, int, str]]:
    return [(r.source_id, r.target_id, r.kind) for r in Relationship.query.filter(Relationship.kind.in_(PAIRS))]


def _distances(found: list[Path], pairs) -> dict[int, int]:
    """Hops from where the internet comes in, for each device it reaches:
    from the device an internet line comes in at, or else a modem, or
    else a router or firewall."""
    near: dict[int, set[int]] = {}
    for p in found:
        near.setdefault(p.a.device_id, set()).add(p.b.device_id)
        near.setdefault(p.b.device_id, set()).add(p.a.device_id)
    for a, b, _ in pairs:
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    if not near:
        return {}
    devices = {e.id: e for e in Entity.query.filter(Entity.id.in_(near), Entity.deleted_at.is_(None))}
    from .views import line_ids
    lines = line_ids()
    roots = [i for i in devices if i in lines]
    for roles in (("modem",), ("router", "firewall")):
        roots = roots or [i for i, e in devices.items() if ports.role(e) in roles]
    dist = {i: 0 for i in roots}
    queue = deque(roots)
    while queue:
        i = queue.popleft()
        for j in near.get(i, ()):
            if j in devices and j not in dist:
                dist[j] = dist[i] + 1
                queue.append(j)
    return dist


def _upstream(a: Entity, b: Entity, dist, gear: bool):
    """(needs, needed) between two of a kind, or None when neither does."""
    da, db_ = dist.get(a.id), dist.get(b.id)
    if da != db_:
        if da is None or (db_ is not None and da > db_):
            return a, b
        return b, a
    if gear and da is None:
        # No way in from the internet is recorded: by what each one is.
        ra, rb = ports._rank(ports.role(a)), ports._rank(ports.role(b))
        if ra[0] != rb[0]:
            return (a, b) if ra > rb else (b, a)
    return None


def impact_edges() -> list[tuple[int, int, str, str]]:
    """The dependencies the cabling makes: (needs, needed, read from the
    one that needs, read from the one needed)."""
    found, pairs = paths(), _pairs()
    dist = _distances(found, pairs)
    out = []
    for p in found:
        a, b = p.a.device, p.b.device
        if "patch_panel" in (ports.role(a), ports.role(b)):
            continue        # a panel left unpatched at the far side: nothing to need
        ga, gb = a.type in GEAR_TYPES, b.type in GEAR_TYPES
        if ga != gb:
            order = (b, a) if ga else (a, b)
        else:
            order = _upstream(a, b, dist, gear=ga)
        if order is not None and order[0].type not in MANAGED_ONLY:
            out.append((order[0].id, order[1].id) + (UPLINK if ga and gb else PLUGS))
    entities = {e.id: e for e in Entity.query.filter(Entity.id.in_({i for a, b, _ in pairs for i in (a, b)}))}
    for a, b, kind in pairs:
        if a in entities and b in entities:
            order = _upstream(entities[a], entities[b], dist, gear=True)
            if order is not None:
                out.append((order[0].id, order[1].id) + PAIRS[kind])
    return out


def derived_links(entity: Entity) -> list[dict]:
    """The devices this one is cabled to, for its Relationships tab: what
    is at the far end of each cable path, with the ports and labels."""
    out = []
    for p in paths():
        if entity.id not in (p.a.device_id, p.b.device_id):
            continue
        mine, far = p.end(entity.id)
        bits = []
        if mine.name and far.name:
            bits.append(f"{mine.name} to {far.name}")
        elif mine.name or far.name:
            bits.append(f"from {mine.name}" if mine.name else f"to {far.name}")
        if p.via:
            bits.append("through " + ", ".join(d.name for d in p.via))
        if p.labels:
            bits.append(("cable " if len(p.labels) == 1 else "cables ") + ", ".join(p.labels))
        out.append({"other": far.device, "label": "cabled to", "sub": " · ".join(bits),
                    "note": "From the Cabling tab: change or remove the cable there."})
    return sorted(out, key=lambda r: r["other"].name.lower())
