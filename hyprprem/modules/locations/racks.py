"""Rack elevations: what occupies which units, on which face, and where two
things claim the same unit or something doesn't fit.

A full-depth mount occupies its units on both faces. Units are numbered
from the bottom (U1 at the bottom) unless the rack says "top".
"""
from hyprprem.core.models import Entity
from hyprprem.models import db

from .models import LocationDetail, RackMount

DEFAULT_HEIGHT = 42


def faces_of(mount) -> tuple[str, ...]:
    return ("front", "rear") if mount.face == "full" else (mount.face,)


def visible_mounts(rack_id: int) -> list[RackMount]:
    """Mounts whose record isn't deleted (a label has none)."""
    rows = (RackMount.query.filter_by(rack_id=rack_id)
            .outerjoin(Entity, Entity.id == RackMount.entity_id)
            .filter((RackMount.entity_id.is_(None)) | (Entity.deleted_at.is_(None)))
            .order_by(RackMount.position_u.desc(), RackMount.id).all())
    return rows


def height_of(rack_id: int) -> int:
    detail = db.session.get(LocationDetail, rack_id)
    return (detail.height_u if detail and detail.height_u else DEFAULT_HEIGHT), \
        (detail.numbering if detail and detail.numbering in ("bottom", "top") else "bottom")


def conflicts(height: int, mounts: list[RackMount]) -> dict[int, list[str]]:
    """mount id -> what is wrong with it, in words."""
    problems: dict[int, list[str]] = {}
    claimed: dict[tuple[str, int], list[RackMount]] = {}
    for m in mounts:
        if m.position_u < 1 or m.top_u > height:
            problems.setdefault(m.id, []).append(
                f"{m.units_label} is outside the rack's U1–U{height}")
        for face in faces_of(m):
            for u in range(m.position_u, m.top_u + 1):
                claimed.setdefault((face, u), []).append(m)
    for (face, u), ms in claimed.items():
        if len(ms) < 2:
            continue
        for m in ms:
            others = ", ".join(sorted({o.name for o in ms if o.id != m.id}))
            text = f"overlaps {others} on the {face}"
            if text not in problems.setdefault(m.id, []):
                problems[m.id].append(text)
    return problems


def layout(rack: Entity) -> dict:
    """Everything the elevation template needs."""
    height, numbering = height_of(rack.id)
    mounts = visible_mounts(rack.id)
    problems = conflicts(height, mounts)

    def row(u: int) -> int:           # grid row, 1 at the top
        return u if numbering == "top" else height - u + 1

    faces = {}
    for face in ("front", "rear"):
        blocks, taken = [], set()
        for m in mounts:
            if face not in faces_of(m):
                continue
            units = [u for u in range(m.position_u, m.top_u + 1) if 1 <= u <= height]
            taken.update(units)
            if not units:
                continue
            rows = sorted(row(u) for u in units)
            blocks.append({"mount": m, "row": rows[0], "span": len(rows), "problems": problems.get(m.id, [])})
        _lanes(blocks)
        empty = [{"u": u, "row": row(u)} for u in range(1, height + 1) if u not in taken]
        faces[face] = {"blocks": blocks, "empty": empty}
    used = len({u for m in mounts for u in range(max(m.position_u, 1), min(m.top_u, height) + 1)})
    labels = [{"u": u, "row": row(u)} for u in range(1, height + 1)]
    return {"height": height, "numbering": numbering, "faces": faces, "labels": labels, "used": used,
            "problems": [(m, problems[m.id]) for m in mounts if m.id in problems], "mounts": mounts}


def _lanes(blocks: list[dict]) -> None:
    """Overlapping mounts go side by side instead of on top of each other:
    each gets a lane, and every block in a cluster of overlaps knows how
    many lanes its cluster needs."""
    blocks.sort(key=lambda b: (b["row"], -b["span"]))
    cluster, cluster_end, lane_ends = [], 0, []

    def close():
        for b in cluster:
            b["lanes"] = len(lane_ends)
    for b in blocks:
        start, end = b["row"], b["row"] + b["span"]
        if cluster and start >= cluster_end:
            close()
            cluster, lane_ends = [], []
        lane = next((i for i, e in enumerate(lane_ends) if e <= start), None)
        if lane is None:
            lane = len(lane_ends)
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        b["lane"] = lane
        cluster.append(b)
        cluster_end = max(cluster_end, end) if len(cluster) > 1 else end
    if cluster:
        close()


def conflicted_rack_ids() -> set[int]:
    """Racks where something overlaps or doesn't fit, for the sidebar filter."""
    out = set()
    racks = db.session.query(Entity.id).filter(Entity.type == "rack", Entity.deleted_at.is_(None)).all()
    for (rack_id,) in racks:
        height, _ = height_of(rack_id)
        if conflicts(height, visible_mounts(rack_id)):
            out.add(rack_id)
    return out
