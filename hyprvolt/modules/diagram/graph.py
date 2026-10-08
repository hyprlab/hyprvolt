"""The network as a graph, and where to draw it.

Devices are nodes; a cable is an edge, traced through patch panels so a
switch port and the server at the far side of the panel are one link, with
the panels named on it. A pair of MoCA adapters is passed through the same
way, over the coax between them. A "connected to" link between two cabled devices
that no cable joins is an edge too, drawn dashed. Everything is read in a
handful of queries and laid out here, so the template only draws.

The layout is in tiers from the internet side: the devices an internet
line comes in at, then modems, then routers and firewalls, then outwards
by distance. Within a tier, each node sits
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
#: A device with more leaves than WRAP_AT (endpoints with nothing below
#: them) has them as a block, at most MAX_COLS to a row, its rows ROW_GAP
#: apart: room for the line along each row and its labels.
WRAP_AT = 8
MAX_COLS = 6
ROW_GAP = 44
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


def network(only=None, strict=False) -> tuple[dict[int, Node], list[Edge]]:
    """Every cabled device and the links between them; or, with ``only``
    (device ids), the links of those devices, and with ``strict`` only
    those between two of them (a network's, not what else its switch has)."""
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
    if only is not None and strict:
        only = _joined(only, edges, devices)
    if only is not None:
        edges = [e for e in edges if (e.a in only and e.b in only) or (not strict and (e.a in only or e.b in only))]
    # A device only on the way (a patch panel) is named on its links, not drawn.
    ends = {i for e in edges for i in (e.a, e.b)}
    nodes = {i: Node(e) for i, e in devices.items() if i in ends}
    return nodes, edges


def _joined(members, edges, devices) -> set[int]:
    """The members (a network's devices) and the devices on the way from
    each to the most upstream of them, so a switch that carries the network
    without saying so still joins its devices to the firewall."""
    from hyprvolt.modules.network import ports
    from hyprvolt.modules.network.views import line_ids
    adj: dict[int, set[int]] = {}
    for e in edges:
        adj.setdefault(e.a, set()).add(e.b)
        adj.setdefault(e.b, set()).add(e.a)
    present = [i for i in members if i in adj and i in devices]
    if not present:
        return set(members)
    lines = line_ids()
    root = min(present, key=lambda i: (i not in lines, ports._rank(ports.group_of(devices[i])), devices[i].name.lower()))
    parent, queue = {root: None}, [root]
    while queue:
        i = queue.pop(0)
        for j in sorted(adj.get(i, ())):
            if j not in parent:
                parent[j] = i
                queue.append(j)
    keep = set(members)
    for m in present:
        i = m
        while i is not None and i in parent:
            keep.add(i)
            i = parent[i]
    return keep


def _rank(nodes) -> dict[int, int]:
    """How far upstream each device is: those an internet line comes in at
    first, then modems, then routers and firewalls."""
    kinds = dict(db.session.query(HardwareDetail.entity_id, HardwareDetail.kind)
                 .filter(HardwareDetail.entity_id.in_(list(nodes))))
    out = {}
    from hyprvolt.modules.network.views import line_ids
    lines = line_ids()
    for i, n in nodes.items():
        if i in lines:
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
        # best-connected one: where the internet comes in, every one of them.
        start = min(left, key=lambda i: (rank.get(i, 9), -len(adj[i]), nodes[i].entity.name.lower()))
        base = max(tiers.values(), default=-1) + 1 if tiers else 0
        # Every way the internet comes into this part (two lines, a modem for
        # each ISP) starts it together, side by side in the top row.
        seeds = [start]
        if rank.get(start, 9) <= 0:
            part, todo = {start}, [start]
            while todo:
                for j in adj[todo.pop()]:
                    if j in left and j not in part:
                        part.add(j)
                        todo.append(j)
            seeds = sorted((i for i in part if rank.get(i, 9) == rank[start]), key=lambda i: nodes[i].entity.name.lower())
        queue = [(i, base) for i in seeds]
        for i in seeds:
            tiers[i] = base
            left.discard(i)
        while queue:
            i, t = queue.pop(0)
            for j in sorted(adj[i], key=lambda j: (rank.get(j, 9), nodes[j].entity.name.lower())):
                if j in left:
                    left.discard(j)
                    tiers[j] = t + 1
                    queue.append((j, t + 1))
    blocks = _blocks(nodes, adj, tiers)
    in_block = {i: p for p, kids in blocks.items() for i in kids}
    # Each tier's items, a device or a block of the leaves under one: ("n", id) or ("b", parent).
    rows: dict[int, list[tuple[str, int]]] = {}
    for i, t in tiers.items():
        if i not in in_block:
            rows.setdefault(t, []).append(("n", i))
    for p, kids in blocks.items():
        rows.setdefault(tiers[kids[0]], []).append(("b", p))
    shape = {p: _grid(len(kids)) for p, kids in blocks.items()}

    def item_w(item):
        return shape[item[1]][2] if item[0] == "b" else NODE_W

    def item_h(item):
        return shape[item[1]][3] if item[0] == "b" else NODE_H
    tier_y, y = {}, MARGIN
    for t in range(max(rows, default=-1) + 1):
        tier_y[t] = y
        y += max((item_h(it) for it in rows.get(t, ())), default=NODE_H) + GAP_Y
    height = y - GAP_Y + MARGIN
    views = {v.id: v for v in present.views([n.entity for n in nodes.values()])}

    def place(i, t, x, y):
        n = nodes[i]
        n.tier, n.x, n.y = t, x, y
        n.label = _fit(n.entity.name, 15)
        n.type_label = views[i].type_label if i in views else ""
        if i in rank and rank[i] == -1:
            n.type_label = "Internet comes in"     # where a line from an ISP plugs in
        n.icon = views[i].icon if i in views else ""
    # Tier by tier, each item under what it hangs from (its devices above, a
    # block under its parent), in that order across, pushed aside only as
    # far as it must be not to overlap the one before it.
    centre: dict[int, float] = {}
    where = {}                                    # a block's parent -> its left edge
    for t in sorted(rows):
        def wanted(item):
            kind, i = item
            above = [i] if kind == "b" else [j for j in adj[i] if j in centre and tiers[j] < t]
            return sum(centre[j] for j in above) / len(above) if above else None
        items = rows[t]
        want = {it: wanted(it) for it in items}
        placed = [w for w in want.values() if w is not None]
        # What hangs from nothing above (the top row) is spread from the left.
        spare = (max(placed) if placed else 0) + NODE_W
        for it in items:
            if want[it] is None:
                want[it] = spare
                spare += item_w(it) + GAP_X
        items.sort(key=lambda it: (want[it], nodes[it[1]].entity.name.lower()))
        right = None
        for item in items:
            x = want[item] - item_w(item) / 2
            if right is not None:
                x = max(x, right + GAP_X)
            right = x + item_w(item)
            kind, i = item
            if kind == "n":
                place(i, t, x, tier_y[t])
                centre[i] = x + NODE_W / 2
                continue
            where[i] = x
            _, cols, _, _ = shape[i]
            kids = blocks[i]
            for k, j in enumerate(kids):
                r, c = divmod(k, cols)
                in_row = min(cols, len(kids) - r * cols)        # the last row centered under the rest
                place(j, t, x + (cols - in_row) * (NODE_W + GAP_X) / 2 + c * (NODE_W + GAP_X),
                      tier_y[t] + r * (NODE_H + ROW_GAP))
    # All of it moved in from the left margin.
    lowest = min((n.x for n in nodes.values()), default=MARGIN)
    for n in nodes.values():
        n.x += MARGIN - lowest
    for p in where:
        where[p] += MARGIN - lowest
    width = max((n.x + NODE_W for n in nodes.values()), default=NODE_W) + MARGIN
    for e in edges:
        p = in_block.get(e.b) if in_block.get(e.b) == e.a else in_block.get(e.a) if in_block.get(e.a) == e.b else None
        if p is not None:
            kid = e.b if e.a == p else e.a
            bus(e, nodes[p], nodes[kid], where[p], shape[p], tier_y[nodes[kid].tier])
        else:
            route(e, nodes[e.a], nodes[e.b])
    return width, height


def _blocks(nodes, adj, tiers) -> dict[int, list[int]]:
    """parent -> its leaves, by name, where it has more than a row of them:
    devices cabled to it alone, with nothing further down (a switch's
    endpoints). They are laid out as a grid under it, not one long row."""
    under: dict[int, list[int]] = {}
    for i, t in tiers.items():
        ups = [j for j in adj[i] if tiers.get(j) == t - 1]
        if len(adj[i]) == 1 and len(ups) == 1:
            under.setdefault(ups[0], []).append(i)
    return {p: sorted(kids, key=lambda i: nodes[i].entity.name.lower())
            for p, kids in under.items() if len(kids) > WRAP_AT}


def _grid(n: int) -> tuple[int, int, float, float]:
    """(rows, columns, width, height) of a block of ``n`` leaves: as few
    rows as fit MAX_COLS to a row, the rows as even as they can be."""
    n_rows = -(-n // MAX_COLS)
    cols = -(-n // n_rows)
    return n_rows, cols, cols * (NODE_W + GAP_X) - GAP_X, n_rows * NODE_H + (n_rows - 1) * ROW_GAP


def bus(e: Edge, parent: Node, kid: Node, left: float, shape, top: float) -> None:
    """A leaf in a block, joined like an org chart: down from its parent to
    a trunk in a gap between the block's columns, along the bus over the
    leaf's row, and down to it."""
    _, cols, _, _ = shape
    trunk = left + (cols // 2) * (NODE_W + GAP_X) - GAP_X / 2      # the gap left of the middle
    px, py = parent.x + NODE_W / 2, parent.y + NODE_H
    cx, cy = kid.x + NODE_W / 2, kid.y
    split = top - GAP_Y / 2                       # halfway down to the block
    rail = cy - ROW_GAP + 12 if cy > top else split   # over the row, clear of the row above's labels
    if cy > top:
        e.path = (f"M{px:.0f},{py:.0f} V{split:.0f} H{trunk:.0f} V{rail:.0f} H{cx:.0f} V{cy:.0f}")
    else:
        e.path = f"M{px:.0f},{py:.0f} V{split:.0f} H{cx:.0f} V{cy:.0f}"
    e.mid = (cx, cy - 7)


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
