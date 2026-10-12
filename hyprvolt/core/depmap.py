"""The dependency view as a diagram: what a record needs above it, what
breaks if it goes down below it, a row further out for each step.

It draws the same walks as the lists (``relations.walk``), as SVG made on
the server. A record reached along two paths is one box with two lines into
it; a loop back to a record already drawn is a dashed line to that box.
A record's branch folds away with the − on it (``folded``), and the diagram
is laid out again without it, while the record stays open (app.js).
"""
from flask import render_template

from . import present, relations

NODE_W, NODE_H = 164, 48
MARGIN = 20
GAP_X = 24
GAP_Y = 64         # between rows: room for the lines and their labels
#: A record with more than WRAP_AT dependents that have none of their own
#: has them as a block under it, at most MAX_COLS to a row, ROW_GAP apart:
#: room for the line along each row and the labels over it.
WRAP_AT = 8
MAX_COLS = 6
ROW_GAP = 44


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


def _blocks(rows: dict, edges: list, root_id: int) -> dict[int, list]:
    """parent id -> the records that hang from it alone with nothing of
    their own below, by name, where there are more than WRAP_AT of them:
    a switch's endpoints, drawn as a block under it, not one long row."""
    kids_of, parents_of = {}, {}
    for parent, child, _label, loop in edges:
        if loop:
            continue
        parent = root_id if parent is None else parent
        kids_of.setdefault(parent, []).append(child)
        parents_of.setdefault(child, []).append(parent)
    known = {e.id: e for r in rows.values() for e in r}
    under: dict[int, list] = {}
    for child, parents in parents_of.items():
        if len(parents) == 1 and child not in kids_of and child in known:
            under.setdefault(parents[0], []).append(known[child])
    return {p: sorted(kids, key=lambda e: e.name.lower()) for p, kids in under.items() if len(kids) > WRAP_AT}


def _grid(n: int) -> tuple[int, int, float, float]:
    """(rows, columns, width, height) of a block of ``n``: as few rows as
    fit MAX_COLS to a row, the rows as even as they can be."""
    n_rows = -(-n // MAX_COLS)
    cols = -(-n // n_rows)
    return n_rows, cols, cols * NODE_W + (cols - 1) * GAP_X, n_rows * NODE_H + (n_rows - 1) * ROW_GAP


def _fold(tree: list[dict], side: str, folded, toggles: dict) -> list[dict]:
    """The tree with the branches of the records in ``folded`` ("D:12", a
    side and an id) cut off, and in ``toggles`` each record that has a
    branch: its key -> how many records its folded branch hides (0 when
    it is open)."""
    out = []
    for n in tree:
        if n["children"]:
            key = f"{side}:{n['entity'].id}"
            hidden = key in folded
            toggles[key] = relations.count(n["children"]) if hidden else 0
            n = {**n, "children": [] if hidden else _fold(n["children"], side, folded, toggles)}
        out.append(n)
    return out


def draw(entity, needs: list[dict], dependents: list[dict], folded=frozenset()) -> str:
    """The diagram's HTML, or "" when the record needs nothing and nothing
    needs it. Top to bottom: what it needs (the furthest first), the record,
    what breaks if it goes down (the nearest first). A record in ``folded``
    shows without what hangs from it, and a + on it says how many that is."""
    if not needs and not dependents:
        return ""
    # Collapse all folds the records next to this one.
    every = [f"U:{n['entity'].id}" for n in needs if n["children"]] + \
            [f"D:{n['entity'].id}" for n in dependents if n["children"]]
    toggles: dict[str, int] = {}
    needs, dependents = _fold(needs, "U", folded, toggles), _fold(dependents, "D", folded, toggles)
    up, up_edges = _side(needs, entity.id)
    down, down_edges = _side(dependents, entity.id)
    n_up, n_down = max(up, default=0), max(down, default=0)
    # What breaks, row by row: a record, or a block of the many leaves under one ("b", parent id).
    blocks = _blocks(down, down_edges, entity.id)
    in_block = {e.id: p for p, kids in blocks.items() for e in kids}
    shape = {p: _grid(len(kids)) for p, kids in blocks.items()}
    items: dict[int, list] = {}
    for depth, row in down.items():
        items[depth] = []
        for e in row:
            if e.id not in in_block:
                items[depth].append(("n", e))
            elif ("b", in_block[e.id]) not in items[depth]:
                items[depth].append(("b", in_block[e.id]))

    def item_w(item):
        return shape[item[1]][2] if item[0] == "b" else NODE_W

    def row_w(row):
        return sum(item_w(it) for it in row) + GAP_X * (len(row) - 1)
    widths = [len(r) * NODE_W + (len(r) - 1) * GAP_X for r in up.values()] + [row_w(r) for r in items.values()]
    width = max(widths + [NODE_W, 3 * NODE_W + 2 * GAP_X]) + 2 * MARGIN

    # Each row's top edge. A dashed line through the record divides the two
    # sides; their names are pinned beside it in the page (app.js), so they
    # stay readable however far it is zoomed or scrolled.
    tops, y = {}, MARGIN
    if n_up:
        for depth in range(n_up, 0, -1):
            tops[("U", depth)] = y
            y += NODE_H + GAP_Y
    tops[("", 0)] = y
    divider = y + NODE_H / 2
    y += NODE_H
    if n_down:
        y += GAP_Y
        for depth in range(1, n_down + 1):
            tops[("D", depth)] = y
            y += max([NODE_H] + [shape[it[1]][3] for it in items.get(depth, ()) if it[0] == "b"]) + GAP_Y
        y -= GAP_Y
    height = y + MARGIN

    boxes = {}                      # (side, id) -> (x, y)

    def place(side, depth, items):
        x0 = (width - len(items) * NODE_W - (len(items) - 1) * GAP_X) / 2
        for n, e in enumerate(items):
            boxes[(side, e.id)] = (x0 + n * (NODE_W + GAP_X), tops[(side, depth)])

    place("", 0, [entity])
    for depth, row in up.items():
        place("U", depth, row)
    block_at = {}                   # a block's parent -> (its left edge, its top)
    for depth, row in items.items():
        x = (width - row_w(row)) / 2
        for kind, it in row:
            if kind == "n":
                boxes[("D", it.id)] = (x, tops[("D", depth)])
            else:
                block_at[it] = (x, tops[("D", depth)])
                _, cols, _, _ = shape[it]
                kids = blocks[it]
                for k, e in enumerate(kids):
                    r, c = divmod(k, cols)
                    in_row = min(cols, len(kids) - r * cols)         # the last row centered under the rest
                    boxes[("D", e.id)] = (x + (cols - in_row) * (NODE_W + GAP_X) / 2 + c * (NODE_W + GAP_X),
                                          tops[("D", depth)] + r * (NODE_H + ROW_GAP))
            x += item_w((kind, it)) + GAP_X

    def at(side, eid):
        """A box: the record itself (a loop can lead back to it), or one on this side."""
        return boxes[("", eid)] if eid == entity.id else boxes.get((side, eid))

    def pairs():
        for side, edges in (("U", up_edges), ("D", down_edges)):
            for parent, child, label, loop in edges:
                if side == "D" and not loop and child in in_block:
                    continue                # a block's: drawn along its rows (bus)
                a, b = at(side, entity.id if parent is None else parent), at(side, child)
                if a is not None and b is not None and a != b:
                    yield a, b, label, loop

    def bus():
        """A block's leaves joined like an org chart: down from the parent to
        a trunk in a gap between the block's columns, along the line over
        each row, and down to each leaf, its label over it."""
        out = []
        for parent, child, label, loop in down_edges:
            p = entity.id if parent is None else parent
            if loop or in_block.get(child) != p:
                continue
            (bx, top), (_, cols, _, _) = block_at[p], shape[p]
            px, py = at("D", p)
            kx, ky = boxes[("D", child)]
            px, py, cx = px + NODE_W / 2, py + NODE_H, kx + NODE_W / 2
            trunk = bx + (cols // 2) * (NODE_W + GAP_X) - GAP_X / 2
            split = top - GAP_Y / 2
            if ky > top:
                rail = ky - ROW_GAP + 12
                path = f"M{px:.0f},{py:.0f} V{split:.0f} H{trunk:.0f} V{rail:.0f} H{cx:.0f} V{ky:.0f}"
            else:
                path = f"M{px:.0f},{py:.0f} V{split:.0f} H{cx:.0f} V{ky:.0f}"
            out.append({"path": path, "label": label, "lx": cx, "ly": ky - 8, "anchor": "middle", "loop": False})
        return out

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
            # (Only those in its way across, not a block off to one side.)
            lo, hi = min(x1, x2), max(x1, x2)
            between = [x for (x, y) in boxes.values() if y1 < y < y2 and x + NODE_W > lo and x < hi]
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
        for key, (x, y) in list(block_at.items()):
            block_at[key] = (x + shift, y)
        links, _ = lines()
    links += bus()
    everyone = [entity] + [e for r in list(up.values()) + list(down.values()) for e in r]
    views = {v.id: v for v in present.views(list({e.id: e for e in everyone}.values()))}
    nodes = [{"view": views[eid], "name": fit(views[eid].name, 15), "x": x, "y": y, "center": side == ""}
             for (side, eid), (x, y) in boxes.items()]
    # A record's fold button sits on the edge its branch leaves from: the
    # bottom below the record, the top above it.
    folds = []
    for key, hidden in toggles.items():
        side, _, eid = key.partition(":")
        x, y = boxes[(side, int(eid))]
        folds.append({"key": key, "x": x + NODE_W / 2, "y": y + (NODE_H if side == "D" else 0),
                      "hidden": hidden, "name": views[int(eid)].name, "side": side})
    return render_template("sheet/depmap.html", entity=entity, nodes=nodes, links=links, folds=folds,
                           divider=divider, above=bool(n_up), below=bool(n_down),
                           record=(boxes[("", entity.id)][0], boxes[("", entity.id)][0] + NODE_W, NODE_H / 2),
                           every=every, folded=sorted(k for k, n in toggles.items() if n), state=sorted(folded),
                           width=width, height=height, w=NODE_W, h=NODE_H, margin=MARGIN,
                           truncated=_truncated(needs) or _truncated(dependents))


def _truncated(tree: list[dict]) -> bool:
    return any(n["truncated"] or _truncated(n["children"]) for n in tree)
