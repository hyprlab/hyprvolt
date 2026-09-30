"""The network diagram page and each record's Neighborhood tab, drawn as
SVG on the server from the layout in graph.py."""
from flask import render_template

from hyprvolt.core import present, relations
from hyprvolt.core.models import Entity
from hyprvolt.modules.network.models import Cable, Port
from hyprvolt.modules.network.ports import trace

from . import graph

#: Neighbors drawn on each side of a record before "and N more".
SIDE = 14
ROW = 58
COL_GAP = 110


def network_page() -> str:
    nodes, edges = graph.network()
    width, height = graph.layout(nodes, edges) if nodes else (0, 0)
    # Top to bottom, left to right: the order a screen reader reads them in.
    ordered = sorted(nodes.values(), key=lambda n: (n.tier, n.x))
    return render_template("diagram/network.html", nodes=ordered, edges=edges, by_id=nodes,
                           width=width, height=height, w=graph.NODE_W, h=graph.NODE_H,
                           dashed=sum(1 for e in edges if not e.cabled),
                           wireless=any(e.kind == "wireless" for e in edges),
                           internet=any(e.kind == "internet" for e in edges))


# ———— One record's neighborhood ————

def _cabled_to(entity: Entity) -> list[tuple[Entity, str]]:
    """The devices at the far end of this one's cables, with the ports."""
    out = []
    for port in Port.query.filter_by(device_id=entity.id).order_by(Port.position, Port.id):
        if Cable.query.filter((Cable.a_id == port.id) | (Cable.b_id == port.id)).first() is None:
            continue
        path = trace(port)
        end = path[-1]["port"] if path and "port" in path[-1] else None
        if end is None or end.device_id == entity.id or end.device.deleted_at is not None:
            continue
        # A device cabled as a whole has no port name to show.
        label = f"{port.name} to {end.name}" if port.name and end.name else f"to {end.name}" if end.name else port.name
        out.append((end.device, label))
    return out


def _neighbors(entity: Entity) -> tuple[list, list]:
    """(out, in): [(entity, label)], what this record points at and what
    points at it, cables counted as out."""
    out, inn = [], []
    for r in relations.for_entity(entity):
        (out if r["outgoing"] else inn).append((r["other"], r["label"]))
    out += [(e, f"cabled {label}".strip()) for e, label in _cabled_to(entity)]
    return out, inn


def has_neighbors(entity: Entity) -> bool:
    return bool(relations.for_entity(entity)) or bool(_cabled_to(entity))


def neighborhood_tab(entity: Entity) -> str:
    out, inn = _neighbors(entity)
    w, h = graph.NODE_W, graph.NODE_H
    rows = max(min(len(out), SIDE), min(len(inn), SIDE), 1)
    height = rows * ROW + 2 * graph.MARGIN
    width = 3 * w + 2 * COL_GAP + 2 * graph.MARGIN
    center = {"x": graph.MARGIN + w + COL_GAP, "y": graph.MARGIN + (rows * ROW - h) / 2}
    views = {v.id: v for v in present.views([e for e, _ in out + inn] + [entity])}

    def column(items, x, side):
        drawn = []
        top = graph.MARGIN + (rows * ROW - min(len(items), SIDE) * ROW) / 2
        for n, (e, label) in enumerate(items[:SIDE]):
            y = top + n * ROW + (ROW - h) / 2
            cx = center["x"] if side == "out" else center["x"] + w
            ex = x + w if side == "out" else x
            cy, ey = center["y"] + h / 2, y + h / 2
            mx = (cx + ex) / 2
            drawn.append({"view": views[e.id], "x": x, "y": y, "label": label, "name": graph._fit(e.name, 15),
                          "path": f"M{cx:.0f},{cy:.0f} C{mx:.0f},{cy:.0f} {mx:.0f},{ey:.0f} {ex:.0f},{ey:.0f}",
                          "lx": ex + (8 if side == "out" else -8), "ly": ey - 7,
                          "anchor": "start" if side == "out" else "end"})
        return drawn, max(len(items) - SIDE, 0)

    left, more_out = column(out, graph.MARGIN, "out")
    right, more_in = column(inn, center["x"] + w + COL_GAP, "in")
    return render_template("diagram/neighborhood.html", entity=entity, me=views[entity.id],
                           name=graph._fit(entity.name, 15), center=center, left=left, right=right,
                           more_out=more_out, more_in=more_in, width=width, height=height, w=w, h=h)
