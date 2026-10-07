"""The network as a graph, and where to draw it.

Devices are nodes; a cable is an edge, traced through patch panels so a
switch port and the server at the far side of the panel are one link, with
the panels named on it. A pair of MoCA adapters is passed through the same
way, over the coax between them. A "connected to" link between two cabled devices
that no cable joins is an edge too, drawn dashed. Everything is read in a
handful of queries and laid out here, so the template only draws.

The layout is in tiers from the internet side: the internet connections
(each linked to the device it comes in at), then modems, then routers and
firewalls, then outwards by distance. Within a tier, each node sits
near the average place of its neighbors in the tier above, which keeps most
lines from crossing.
"""
from dataclasses import dataclass, field

from sqlalchemy.orm import joinedload

from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.modules.hardware.models import HardwareDetail
from hyprvolt.modules.network.models import Cable, Port
from hyprvolt.registry import current as registry

NODE_W, NODE_H = 164, 48
GAP_X, GAP_Y = 26, 92
MARGIN = 20
#: Upstream first: where the internet comes in.
FIRST = {"modem": 0, "router": 1}


@dataclass
class Node:
    entity: Entity
    x: float = 0
    y: float = 0
    tier: int = 0
    label: str = ""
    type_label: str = ""
    icon: str = ""

    @property
    def id(self):
        return self.entity.id


@dataclass
class Edge:
    a: int
    b: int
    cabled: bool = True
    ends: tuple = ("", "")           # port names at a and b
    via: list = field(default_factory=list)
    coax: list = field(default_factory=list)  # MoCA pairs on the way: "moca-a and moca-b"
    vlans: str = ""
    path: str = ""
    mid: tuple = (0, 0)
    kind: str = ""                   # "internet" (a line coming in), "wireless" (bridges), or a cable

    def title(self, nodes) -> str:
        a, b = nodes[self.a].entity.name, nodes[self.b].entity.name
        if self.kind == "internet":
            return f"{a} comes in at {b}"
        if self.kind == "wireless":
            return f"{a} to {b}, a wireless link"
        text = f"{a} {self.ends[0]} to {b} {self.ends[1]}".replace("  ", " ").strip() if self.cabled else f"{a} to {b}"
        if self.via:
            text += " through " + ", ".join(self.via)
        if self.coax:
            text += " over the coax between " + ", and ".join(self.coax)
        if self.vlans:
            text += f" ({self.vlans})"
        return text if self.cabled else text + ", linked but no cable recorded"


def _live_devices(ids) -> dict[int, Entity]:
    reg = registry()
    keys = set(reg.enabled_type_keys())
    rows = Entity.live().filter(Entity.id.in_(ids)).all() if ids else []
    return {e.id: e for e in rows if e.type in keys}


def _vlans(port: Port) -> str:
    bits = []
    if port.vlan is not None and port.vlan.deleted_at is None:
        bits.append(port.vlan.name)
    if port.tagged:
        bits.append("tagged " + port.tagged)
    return ", ".join(bits)


def network(only=None) -> tuple[dict[int, Node], list[Edge]]:
    """Every cabled device and the links between them; or, with ``only``
    (device ids), the links of those devices."""
    ports = {p.id: p for p in Port.query.options(joinedload(Port.device), joinedload(Port.vlan))}
    cable_at = {}
    for c in Cable.query:
        cable_at[c.a_id] = c
        cable_at[c.b_id] = c
    devices = _live_devices({p.device_id for p in ports.values() if p.id in cable_at})
    # A MoCA adapter, its partner over the coax, and where that is cabled on.
    partner_of = {}
    for r in Relationship.query.filter_by(kind="coax_link"):
        partner_of.setdefault(r.source_id, r.target_id)
        partner_of.setdefault(r.target_id, r.source_id)
    cabled_on = {}
    for p in sorted(ports.values(), key=lambda p: (p.position, p.id)):
        if p.id in cable_at:
            cabled_on.setdefault(p.device_id, p)

    def far_end(port):
        """Follow a cable, and on through panels and over MoCA pairs: (end
        port, the panels on the way, the pairs on the way)."""
        via, coax, seen = [], [], {port.id}
        cable = cable_at.get(port.id)
        while cable is not None:
            other = ports.get(cable.b_id if cable.a_id == port.id else cable.a_id)
            if other is None or other.id in seen:
                return None, via, coax
            seen.add(other.id)
            on = ports.get(other.pair_id) if other.pair_id else None
            partner = devices.get(partner_of.get(other.device_id)) if on is None else None
            if partner is not None:
                on = cabled_on.get(partner.id)
            if on is None or on.id in seen or on.id not in cable_at:
                return other, via, coax
            if partner is not None:
                coax.append(f"{other.device.name} and {partner.name}")
            else:
                via.append(other.device.name)
            seen.add(on.id)
            port, cable = on, cable_at[on.id]
        return None, via, coax

    edges, done = [], set()
    for port in ports.values():
        if port.id not in cable_at or port.pair_id or port.device_id in partner_of:
            continue                      # a panel's or MoCA adapter's port: walked from a device's
        end, via, coax = far_end(port)
        if end is None or port.device_id not in devices or end.device_id not in devices:
            continue
        key = frozenset((port.id, end.id))
        if key in done or port.device_id == end.device_id:
            continue
        done.add(key)
        vlans = _vlans(port) or _vlans(end)
        edges.append(Edge(port.device_id, end.device_id, True, (port.name, end.name), via, coax, vlans))

    # "Connected to" links between cabled devices with no cable between them.
    reg = registry()
    cabled_types = [k for k, t in reg.types.items() if "cabled" in t.traits]
    joined = {frozenset((e.a, e.b)) for e in edges}
    rels = Relationship.query.filter_by(kind="connected_to").all()
    extra = _live_devices({i for r in rels for i in (r.source_id, r.target_id)})
    for r in rels:
        a, b = extra.get(r.source_id), extra.get(r.target_id)
        if a is None or b is None or a.type not in cabled_types or b.type not in cabled_types:
            continue
        if frozenset((a.id, b.id)) in joined:
            continue
        devices.setdefault(a.id, a)
        devices.setdefault(b.id, b)
        joined.add(frozenset((a.id, b.id)))
        edges.append(Edge(a.id, b.id, cabled=False, vlans=r.note or ""))
    # Where the internet comes in: each connection, drawn above the device it
    # plugs into (Network's "comes in at").
    lines = Relationship.query.filter_by(kind="comes_in_at").all()
    ends_of = _live_devices({i for r in lines for i in (r.source_id, r.target_id)})
    for r in lines:
        line, device = ends_of.get(r.source_id), ends_of.get(r.target_id)
        if line is None or device is None:
            continue
        devices.setdefault(line.id, line)
        devices.setdefault(device.id, device)
        edges.append(Edge(line.id, device.id, kind="internet"))
    # A wireless link between two bridges (Hardware's), once each pair.
    air = Relationship.query.filter_by(kind="wireless_link").all()
    ends_of = _live_devices({i for r in air for i in (r.source_id, r.target_id)})
    for r in air:
        a, b = ends_of.get(r.source_id), ends_of.get(r.target_id)
        if a is None or b is None or frozenset((a.id, b.id)) in joined:
            continue
        joined.add(frozenset((a.id, b.id)))
        devices.setdefault(a.id, a)
        devices.setdefault(b.id, b)
        edges.append(Edge(a.id, b.id, kind="wireless"))
    if only is not None:
        edges = [e for e in edges if e.a in only or e.b in only]
    # A device only on the way (a patch panel) is named on its links, not drawn.
    ends = {i for e in edges for i in (e.a, e.b)}
    nodes = {i: Node(e) for i, e in devices.items() if i in ends}
    return nodes, edges


def _rank(nodes) -> dict[int, int]:
    """How far upstream each device is: the internet connections first, then
    modems, then routers and firewalls."""
    kinds = dict(db.session.query(HardwareDetail.entity_id, HardwareDetail.kind)
                 .filter(HardwareDetail.entity_id.in_(list(nodes))))
    out = {}
    for i, n in nodes.items():
        if n.entity.type == "network":
            out[i] = -1
        elif n.entity.type == "firewall":
            out[i] = 1
        elif kinds.get(i) in FIRST and n.entity.type == "network_device":
            out[i] = FIRST[kinds[i]]
    return out


def layout(nodes: dict[int, Node], edges: list[Edge]) -> tuple[float, float]:
    """Place every node and draw every edge's path. Returns the size."""
    from hyprvolt.core import present
    adj = {i: set() for i in nodes}
    for e in edges:
        adj[e.a].add(e.b)
        adj[e.b].add(e.a)
    rank = _rank(nodes)
    tiers: dict[int, int] = {}
    left = set(nodes)
    while left:
        # Each part of the network from its most upstream device, or else its
        # best-connected one.
        start = min(left, key=lambda i: (rank.get(i, 9), -len(adj[i]), nodes[i].entity.name.lower()))
        base = max(tiers.values(), default=-1) + 1 if tiers else 0
        queue = [(start, base)]
        tiers[start] = base
        left.discard(start)
        while queue:
            i, t = queue.pop(0)
            for j in sorted(adj[i], key=lambda j: (rank.get(j, 9), nodes[j].entity.name.lower())):
                if j in left:
                    left.discard(j)
                    tiers[j] = t + 1
                    queue.append((j, t + 1))
    rows: dict[int, list[int]] = {}
    for i, t in tiers.items():
        rows.setdefault(t, []).append(i)
    order: dict[int, float] = {}
    for t in sorted(rows):
        def weight(i):
            above = [order[j] for j in adj[i] if j in order and tiers[j] < t]
            return (sum(above) / len(above) if above else 1e9, nodes[i].entity.name.lower())
        rows[t].sort(key=weight)
        for pos, i in enumerate(rows[t]):
            order[i] = pos
    width = max((len(r) for r in rows.values()), default=1) * (NODE_W + GAP_X) - GAP_X + 2 * MARGIN
    views = {v.id: v for v in present.views([n.entity for n in nodes.values()])}
    for t, ids in rows.items():
        row_w = len(ids) * (NODE_W + GAP_X) - GAP_X
        x0 = (width - row_w) / 2
        for pos, i in enumerate(ids):
            n = nodes[i]
            n.tier, n.x, n.y = t, x0 + pos * (NODE_W + GAP_X), MARGIN + t * (NODE_H + GAP_Y)
            n.label = _fit(n.entity.name, 15)
            n.type_label = views[i].type_label if i in views else ""
            n.icon = views[i].icon if i in views else ""
    for e in edges:
        route(e, nodes[e.a], nodes[e.b])
    height = MARGIN * 2 + (max(rows, default=0) + 1) * (NODE_H + GAP_Y) - GAP_Y
    return width, height


def route(e: Edge, a: Node, b: Node) -> None:
    """A curve from one node to the other: bottom to top between tiers,
    an arc under the row within one."""
    if a.y > b.y:
        a, b = b, a
    ax, bx = a.x + NODE_W / 2, b.x + NODE_W / 2
    if a.y == b.y:
        y = a.y + NODE_H
        dip = 28 + abs(ax - bx) / 8
        e.path = f"M{ax:.0f},{y:.0f} C{ax:.0f},{y + dip:.0f} {bx:.0f},{y + dip:.0f} {bx:.0f},{y:.0f}"
        e.mid = ((ax + bx) / 2, y + dip * 0.75)
        return
    ay, by = a.y + NODE_H, b.y
    bend = (by - ay) / 2
    e.path = f"M{ax:.0f},{ay:.0f} C{ax:.0f},{ay + bend:.0f} {bx:.0f},{by - bend:.0f} {bx:.0f},{by:.0f}"
    # The label sits just above the lower end, where the lines fanning out
    # of a switch are already apart.
    e.mid = (bx, by - 12)


def _fit(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"
