"""The dependency view as a diagram: what a record needs above it, what
breaks if it goes down below it, a row further out for each step.

It draws the same walks as the lists (``relations.walk``), as SVG made on
the server. A record reached along two paths is one box with two lines into
it; a loop back to a record already drawn is a dashed line to that box.
"""
from flask import render_template

from . import present, relations

NODE_W, NODE_H = 164, 48
MARGIN = 20
HEAD = 28          # a band for a side's heading
GAP_X = 24
GAP_Y = 64         # between rows: room for the lines and their labels


def fit(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _side(tree: list[dict], root_id: int):
    """Rows (depth -> [entity]) and edges (parent id, child id, label, loop)
    of one walk. A record sits one row past the furthest record it hangs
    from, so every line runs one way, and a row is ordered under the
    records above it, which keeps lines from crossing."""
    entities, edges, seen = {}, [], set()

    def visit(parent, nodes):
        for node in nodes:
            e = node["entity"]
            entities.setdefault(e.id, e)
            if (parent, e.id) not in seen:
                seen.add((parent, e.id))
                edges.append((parent, e.id, node["label"], node["cycle"]))
            visit(e.id, node["children"])
    visit(root_id, tree)

    depth = {root_id: 0}
    for _ in range(len(entities) + 1):          # longest path, as a walk has no loops once they are set aside
        changed = False
        for parent, child, _label, loop in edges:
            if loop or parent not in depth or child == root_id:
                continue
            if depth.get(child, 0) < depth[parent] + 1 <= 24:
                depth[child] = depth[parent] + 1
                changed = True
        if not changed:
            break

    by_depth: dict[int, list] = {}
    for eid, d in depth.items():
        if eid != root_id:
            by_depth.setdefault(d, []).append(entities[eid])
    parents: dict[int, list[int]] = {}
    for parent, child, _label, loop in edges:
        if not loop:
            parents.setdefault(child, []).append(parent)

    # Row by row, each ordered under the records it hangs from.
    rows, place = {}, {root_id: 0.0}
    for d in sorted(by_depth):
        def weight(e):
            seen_at = [place[p] for p in parents.get(e.id, []) if p in place]
            return (sum(seen_at) / len(seen_at) if seen_at else 0, e.name.lower())
        rows[d] = sorted(by_depth[d], key=weight)
        for n, e in enumerate(rows[d]):
            place[e.id] = n - (len(rows[d]) - 1) / 2
    return rows, [(None if p == root_id else p, c, label, loop) for p, c, label, loop in edges]


def draw(entity, needs: list[dict], dependents: list[dict]) -> str:
    """The diagram's HTML, or "" when the record needs nothing and nothing
    needs it. Top to bottom: what it needs (the furthest first), the record,
    what breaks if it goes down (the nearest first)."""
    if not needs and not dependents:
        return ""
    up, up_edges = _side(needs, entity.id)
    down, down_edges = _side(dependents, entity.id)
    n_up, n_down = max(up, default=0), max(down, default=0)
    widest = max([len(r) for r in list(up.values()) + list(down.values())] + [1])
    width = max(widest * NODE_W + (widest - 1) * GAP_X, 3 * NODE_W + 2 * GAP_X) + 2 * MARGIN

    # Each row's top edge, with a heading band above each side.
    tops, y, heads = {}, MARGIN, []
    if n_up:
        heads.append(("What it needs", y + 14))
        y += HEAD
        for depth in range(n_up, 0, -1):
            tops[("U", depth)] = y
            y += NODE_H + GAP_Y
    tops[("", 0)] = y
    y += NODE_H
    if n_down:
        # The heading just under the record; the first row a line's length below.
        heads.append(("What breaks if this goes down", y + 32))
        y += HEAD + GAP_Y
        for depth in range(1, n_down + 1):
            tops[("D", depth)] = y
            y += NODE_H + GAP_Y
        y -= GAP_Y
    height = y + MARGIN

    boxes = {}                      # (side, id) -> (x, y)

    def place(side, depth, items):
        x0 = (width - len(items) * NODE_W - (len(items) - 1) * GAP_X) / 2
        for n, e in enumerate(items):
            boxes[(side, e.id)] = (x0 + n * (NODE_W + GAP_X), tops[(side, depth)])

    place("", 0, [entity])
    for depth, items in up.items():
        place("U", depth, items)
    for depth, items in down.items():
        place("D", depth, items)

    def at(side, eid):
        """A box: the record itself (a loop can lead back to it), or one on this side."""
        return boxes[("", eid)] if eid == entity.id else boxes.get((side, eid))

    def pairs():
        for side, edges in (("U", up_edges), ("D", down_edges)):
            for parent, child, label, loop in edges:
                a, b = at(side, entity.id if parent is None else parent), at(side, child)
                if a is not None and b is not None and a != b:
                    yield a, b, label, loop

    def lines():
        """The links' paths, and how far left and right they reach. Lines
        into one box meet it at points spread along its edge, in the order
        of the boxes they come from, so their labels don't sit on each other."""
        into: dict[tuple, list] = {}
        for a, b, _label, _loop in pairs():
            into.setdefault(b, []).append(a[0])
        out, reach = [], [0, width]
        for a, b, label, loop in pairs():
            froms = sorted(into[b])
            entry = b[0] + NODE_W * (froms.index(a[0]) + 1) / (len(froms) + 1)
            # From the bottom of the upper box to the top of the lower one;
            # the label sits near the box the line leads to (the child).
            below = b[1] > a[1]
            (ux, uy), (lx, ly) = sorted([a, b], key=lambda p: p[1])
            x1, y1, x2, y2 = ux + NODE_W / 2, uy + NODE_H, lx + NODE_W / 2, ly
            if below:
                x2 = entry
            else:
                x1 = entry
            my = (y1 + y2) / 2
            # A line that skips rows goes round the boxes in them, down their
            # right (the headings are on the left), its label beside it.
            between = [x for (x, y) in boxes.values() if y1 < y < y2]
            if between:
                xs = max(between) + NODE_W + 16
                reach[1] = max(reach[1], xs + 70)     # room for the label too
                ya, yb = y1 + GAP_Y / 2, y2 - GAP_Y / 2
                path = (f"M{x1:.0f},{y1:.0f} C{x1:.0f},{ya:.0f} {xs:.0f},{ya:.0f} {xs:.0f},{ya + 16:.0f} "
                        f"L{xs:.0f},{yb - 16:.0f} C{xs:.0f},{yb:.0f} {x2:.0f},{yb:.0f} {x2:.0f},{y2:.0f}")
                out.append({"path": path, "label": label, "lx": xs + 6, "ly": my + 4,
                            "anchor": "start", "loop": loop})
                continue
            path = f"M{x1:.0f},{y1:.0f} C{x1:.0f},{my:.0f} {x2:.0f},{my:.0f} {x2:.0f},{y2:.0f}"
            out.append({"path": path, "label": label, "lx": entry, "anchor": "middle",
                        "ly": b[1] - 10 if below else b[1] + NODE_H + 16, "loop": loop})
        return out, reach

    links, reach = lines()
    if reach[1] > width:       # a line reaches past the right edge: widen, keeping the boxes centered
        shift = (reach[1] - width) / 2
        width = reach[1] + shift
        for key, (x, y) in list(boxes.items()):
            boxes[key] = (x + shift, y)
        links, _ = lines()
    everyone = [entity] + [e for r in list(up.values()) + list(down.values()) for e in r]
    views = {v.id: v for v in present.views(list({e.id: e for e in everyone}.values()))}
    nodes = [{"view": views[eid], "name": fit(views[eid].name, 15), "x": x, "y": y, "center": side == ""}
             for (side, eid), (x, y) in boxes.items()]
    return render_template("sheet/depmap.html", entity=entity, nodes=nodes, links=links, heads=heads,
                           width=width, height=height, w=NODE_W, h=NODE_H, margin=MARGIN,
                           truncated=_truncated(needs) or _truncated(dependents))


def _truncated(tree: list[dict]) -> bool:
    return any(n["truncated"] or _truncated(n["children"]) for n in tree)
