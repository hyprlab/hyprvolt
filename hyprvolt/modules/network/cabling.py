"""Suggested cables, for the site setup guide's Cables step: the likely
cabling of a site worked out from what the steps before recorded, each
cable with why, to check before any is made.

The backbone first: each modem to the router or firewall that is the
gateway, the gateway to the core switch (the switch nearest it), and each
other switch to the core. A pair of MoCA adapters (or wireless bridges)
works like one cable: its near end plugs into a switch, and its far end
serves the place it is in. Then every other device plugs into
the nearest of those, by where each is: same rack, same room, same
building. Wireless extenders, patch panels and peripherals are left out,
and so is a device that already has a cable.
"""
from flask import jsonify, render_template, request
from flask_login import current_user
from markupsafe import Markup

from hyprvolt.core import guide, records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.permissions import role
from hyprvolt.registry import current as registry

from . import addresses, cable_labels, ports
from .models import Cable, NetworkDetail, Port
from .views import bp, carriers_of, setup_ends

MAX_ROWS = 500
FAR = 100          # the distance between places with nothing in common
#: What plugs into nothing by a cable of its own: an extender joins over
#: the air, a patch panel is cabled through, and a peripheral is a monitor
#: or a KVM more often than not.
LEFT_OUT = {"extender", "patch_panel", "peripheral"}
GATEWAY_WORDS = {"firewall": "firewall", "router": "router", "modem": "modem"}


class Site:
    """The site's cabled devices, where each is, and what is cabled now."""

    def __init__(self, scope):
        reg = registry()
        keys = [t.key for t in reg.enabled_types() if ports.is_cabled(t)]
        found = guide.in_site(Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all(), scope)
        details = {e.id: records.detail_of(e) for e in found}
        self.devices = {e.id: e for e in found}
        self.name = {e.id: e.name for e in found}
        self.role = {e.id: ports.role(e) for e in found}
        self.port_count = {e.id: getattr(details[e.id], "ports", None) or 0 for e in found}
        self.root = scope.id if scope is not None else None
        self.places = {e.id: e for e in Entity.live().filter(Entity.type.in_([t.key for t in reg.location_types()]))}
        self.chain = {e.id: self._chain(e.location_id) for e in found}
        self.recorded = ports.recorded_ids()
        self.taken = {i for c in db.session.query(Cable.a_id, Cable.b_id) for i in c}
        self.free = {}
        for p in (Port.query.filter(Port.device_id.in_(self.recorded & set(self.devices)), Port.name != "")
                  .order_by(Port.position, Port.id)):
            if p.id not in self.taken:
                self.free.setdefault(p.device_id, []).append(p)
        self.neighbors = self._neighbors()
        # Devices cabled as a whole with a port count: the cables they have.
        self.used = ports.cabled_counts(self.devices)

    def _chain(self, location_id) -> list[int]:
        """A device's place and each one that holds it, up to the site."""
        out = []
        while location_id in self.places and location_id not in out:
            out.append(location_id)
            location_id = self.places[location_id].location_id
        return out or ([self.root] if self.root else [])

    def _neighbors(self) -> dict[int, set[int]]:
        """What each device is cabled to now, through any patch panels."""
        out = {i: set() for i in self.devices}
        for port in Port.query.filter(Port.device_id.in_(list(self.devices)), Port.id.in_(self.taken),
                                      Port.pair_id.is_(None)):
            far = ports.trace(port)[-1]["port"]
            if far.device_id != port.device_id:
                out[port.device_id].add(far.device_id)
                if far.device_id in out:
                    out[far.device_id].add(port.device_id)
        return out

    def distance(self, a, b) -> int:
        """Steps through places from one device to another: 0 in the same
        rack or room, 1 for one in the room the other's rack is in."""
        ca, cb = self.chain[a], self.chain[b]
        for i, place in enumerate(ca):
            if place in cb:
                return i + cb.index(place)
        return FAR

    def where(self, a) -> str:
        chain = self.chain[a]
        return self.places[chain[0]].name if chain and chain[0] in self.places else ""

    def networks(self, a) -> list[Entity]:
        """The subnets its addresses are in, and the VLAN and subnet of each
        wireless network it broadcasts."""
        out = [addresses.subnet_of_ip(d) for _, d in addresses.addresses_of(self.devices[a])]
        for wifi in Relationship.query.filter(Relationship.kind == "broadcast_by", Relationship.target_id == a):
            d = db.session.get(NetworkDetail, wifi.source_id)
            out += [records.live(i) for i in (d.vlan, d.subnet) if d is not None and i]
        return [n for n in dict.fromkeys(out) if n is not None]

    def kind_of(self, a) -> str:
        """What the device's place is: "rack", "room"."""
        chain = self.chain[a]
        etype = registry().type(self.places[chain[0]].type) if chain and chain[0] in self.places else None
        return etype.text() if etype else "place"

    def serves(self, far_end, device_id) -> bool:
        """A far end serves the place it is in, and what is inside that."""
        return bool(self.chain[far_end]) and self.chain[far_end][0] in self.chain[device_id]

    def of(self, *roles) -> list[int]:
        return [i for i in self.devices if self.role[i] in roles]

    def end(self, device_id, uplink=False) -> str | None:
        """Where a cable meets the device: the device itself, or a free port
        of one with its ports recorded (the first for a device plugged in,
        the last for a switch's own uplink); None when none is free, or a
        device cabled as a whole has as many cables as its port count."""
        if device_id not in self.recorded:
            limit = self.port_count[device_id]
            if limit and self.used.get(device_id, 0) >= limit:
                return None
            self.used[device_id] = self.used.get(device_id, 0) + 1
            return f"device:{device_id}"
        free = self.free.get(device_id, [])
        return f"port:{free.pop(-1 if uplink else 0).id}" if free else None


def _pairs(site, relation) -> list[tuple[int, int]]:
    """The site's wireless bridges (wireless_link), or MoCA adapters
    (coax_link), two by two."""
    ids = list(site.devices)
    links = Relationship.query.filter(Relationship.kind == relation, Relationship.source_id.in_(ids),
                                      Relationship.target_id.in_(ids))
    return sorted({tuple(sorted((r.source_id, r.target_id))) for r in links})


def _nearest(site, device_id, among):
    """The nearest of ``among`` to the device; the earliest of them on a tie."""
    among = [a for a in among if a is not None and a != device_id]
    if not among:
        return None
    return min(among, key=lambda a: (site.distance(device_id, a), among.index(a)))


def plan(scope) -> list[dict]:
    """The cables to suggest, the backbone first and then what plugs into
    each switch: [{"a", "b" (device ids), "a_end", "b_end" (where each
    meets it), "why", "state" (likely, check, choose), "group", "title"}]."""
    site = Site(scope)
    name = site.name
    lines = {r.target_id for r in Relationship.query.filter(Relationship.kind == "comes_in_at")}
    modems, switches = site.of("modem"), site.of("switch")
    gateways = sorted(site.of("firewall", "router"),
                      key=lambda i: (i not in lines, site.role[i] != "firewall", name[i].lower()))
    gateway = gateways[0] if gateways else (modems[0] if modems else None)
    backbone, leaves, placed = [], [], set(modems) | {gateway}

    def link(rows, a, b, why, sure=True, group="backbone"):
        if a is not None and b is not None and a != b and b not in site.neighbors[a]:
            rows.append({"a": a, "b": b, "why": why, "sure": sure, "group": group})

    def from_gateway(i):
        return site.distance(i, gateway) if gateway else 0

    # The internet in, through the gateway, to the core switch.
    for m in modems:
        if m != gateway and gateway is not None and not site.neighbors[m]:
            link(backbone, m, gateway, f"The modem hands the internet to the {GATEWAY_WORDS[site.role[gateway]]} "
                                       f"{name[gateway]}, the gateway.")
    core = min(switches, key=lambda s: (from_gateway(s), -site.port_count[s], name[s].lower())) \
        if switches else None
    if core is not None and gateway is not None:
        link(backbone, gateway, core, f"{name[core]} is the switch nearest the gateway, so the core switch.")

    # Places reached over the coax or the air: a MoCA pair, or a wireless
    # bridge, works like one cable. Its near end plugs into a switch, and
    # its far end serves the place it is in.
    far_ends = []
    for relation, why in (("coax_link", "The MoCA adapter nearer the gateway, which puts the network onto the "
                                        "coax to {far}."),
                          ("wireless_link", "The near end of the wireless bridge to {far}, which joins it over "
                                            "the air.")):
        for a, b in _pairs(site, relation):
            near, far = sorted((a, b), key=lambda i: (from_gateway(i), name[i].lower()))
            link(backbone, near, _nearest(site, near, switches or [gateway]), why.format(far=name[far]))
            far_ends.append(far)
            placed |= {a, b}

    # Every other switch uplinks to the core, or to a far end in its place.
    upstream = set(switches) | {gateway} | set(far_ends)
    for s in switches:
        placed.add(s)
        if s == core or site.neighbors[s] & upstream:
            continue
        up = _nearest(site, s, [core] + [f for f in far_ends if site.serves(f, s)])
        link(backbone, s, up, f"Another switch, uplinked to the core switch {name[up]}." if up == core else
             f"Another switch, uplinked to {name[up]}, which brings the network to {site.where(up)}.")

    # The rest plug into the nearest switch, or the far end serving them.
    points = switches + far_ends
    for d in site.devices:
        if d in placed or site.role[d] in LEFT_OUT or site.neighbors[d]:
            continue
        # A switch that carries its network, if any does; else any switch.
        nets = site.networks(d)
        carrying = carriers_of(n.id for n in nets) & set(switches) if nets else set()
        candidates = [s for s in switches if s in carrying] or switches
        unplaced = site.devices[d].location_id is None
        target = (core if unplaced and not carrying else None) or \
            _nearest(site, d, candidates + [f for f in far_ends if site.serves(f, d)]) or gateway
        if target is None:
            continue
        steps = site.distance(d, target)
        if target in carrying:
            net = next(n for n in nets if target in carriers_of([n.id]))
            why = f"{name[target]} carries its network, {net.name}" + \
                (f", in the same {site.kind_of(d)}." if steps == 0 else
                 f", in {site.where(target)}." if steps < FAR and site.where(target) else ".")
        elif target not in points:
            why = f"There is no switch, so it plugs into the {GATEWAY_WORDS[site.role[target]]} {name[target]}."
        elif unplaced:
            why = f"Nothing records where it is, so it goes to the core switch {name[target]}."
        elif steps >= FAR:
            why = f"Nothing places it near a switch, so it goes to {name[target]}."
        elif target in far_ends:
            why = f"{name[target]} brings the network to {site.where(target)}."
        elif steps == 0:
            why = f"{name[target]} is the switch in the same {site.kind_of(d)}, {site.where(d)}."
        else:
            why = f"{name[target]}, in {site.where(target)}, is the nearest switch."
        if site.role[d] == "moca":
            why += " Choose the adapter at the other end of its coax in Network gear, and what it serves follows."
        sure = target in carrying or (not unplaced and (steps <= 1 or target not in points))
        link(leaves, d, target, why, sure=sure, group=target)
    leaves.sort(key=lambda r: (points.index(r["group"]) if r["group"] in points else -1, name[r["a"]].lower()))
    return [_ends(site, r, uplink=r["group"] == "backbone") for r in backbone + leaves]


def _ends(site, row, uplink) -> dict:
    """The row with where each end meets its device, and "choose" when one
    has no free port left."""
    a, b = site.end(row["a"], uplink=uplink), site.end(row["b"])
    full = [site.name[d] for d, e in ((row["a"], a), (row["b"], b)) if e is None]
    state = "choose" if full else "likely" if row["sure"] else "check"
    return {**row, "a_end": a or "", "b_end": b or "", "full": full, "state": state,
            "title": f"{site.name[row['a']]} to {site.name[row['b']]}"}


# ———— Making what was reviewed ————

def _end(value):
    kind, _, raw = str(value or "").partition(":")
    end = db.session.get(Port, int(raw)) if kind == "port" and raw.isdigit() else \
        records.live(int(raw)) if kind == "device" and raw.isdigit() else None
    device = end.device_id if isinstance(end, Port) else end.id if end is not None else None
    if end is None or records.live(device) is None:
        raise Invalid("Choose both ends of the cable.")
    return end


def add_reviewed(form: dict, user=None) -> dict:
    """Make each cable ticked (``use<i>``) from ``a<i>`` to ``b<i>``, with
    ``label<i>``; ``title<i>`` names it. One that can't be made is left out
    and said why; the rest are kept."""
    done = {"added": [], "skipped": 0, "failed": []}
    for i in range(min(int(form.get("count") or 0), MAX_ROWS)):
        if form.get(f"use{i}") not in (True, "1", "on", "true"):
            done["skipped"] += 1
            continue
        nested = db.session.begin_nested()
        try:
            cable = ports.connect(_end(form.get(f"a{i}")), _end(form.get(f"b{i}")),
                                  {"label": str(form.get(f"label{i}") or "")}, user)
            nested.commit()
            done["added"].append(f"{cable.a.label} to {cable.b.label}")
        except Invalid as err:
            nested.rollback()
            done["failed"].append({"name": str(form.get(f"title{i}") or "")[:200], "error": str(err)})
    return done


# ———— The guide's button, and the routes ————

def _back(value) -> str:
    back = str(value or "")
    return back if back.startswith("/") and not back.startswith("//") else "/site-setup/cables"


def setup_extra(scope) -> str:
    """The Cables step: a way to have the cabling worked out, and to label
    the cables that have no label."""
    if not current_user.can_edit:
        return ""
    loose = Cable.query.filter(Cable.label == "").all()
    devices = Site(scope).devices if loose else {}
    unlabeled = sum(1 for c in loose if c.a.device_id in devices or c.b.device_id in devices)
    return render_template("network/cabling_guide.html", site=scope.id if scope else "",
                           back=request.full_path.rstrip("?"), unlabeled=unlabeled)


def _site(form):
    site = records.live(int(form["site"])) if str(form.get("site") or "").isdigit() else None
    return site if site is not None and registry().type(site.type) in registry().location_types() else None


def setup_after(scope) -> str:
    """Below the Cables step's rows: the network diagram they draw, once
    there are cables, when Diagram is on."""
    reg = registry()
    module = reg.module("diagram") if reg.is_enabled("diagram") else None
    page = next((p for p in module.pages if p.key == "network"), None) if module is not None else None
    if page is None:
        return ""
    return render_template("network/cabling_diagram.html", diagram=Markup(page.render()))


@bp.route("/cables/label", methods=["POST"])
@role("editor")
def cables_label():
    """Every cable in the site with no label, given one from its network."""
    n = cable_labels.label_unlabeled(Site(_site(request.get_json(silent=True) or {})).devices, current_user)
    db.session.commit()
    return jsonify(ok=True, message=f"Labeled {n} {'cable' if n == 1 else 'cables'}." if n
                   else "Every cable has a label already.")


@bp.route("/cables/suggest", methods=["POST"])
@role("editor")
def cables_suggest():
    """The cables suggested for the site, each to check."""
    form = request.get_json(silent=True) or {}
    site = _site(form)
    rows = plan(site)
    used = cable_labels.taken()
    for r in rows:
        a, b = cable_labels.end_of(r["a_end"]), cable_labels.end_of(r["b_end"])
        r["label"] = cable_labels.label_for(a, b, used) if a is not None and b is not None else ""
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    for i, r in enumerate(r for g in groups.values() for r in g):
        r["i"] = i
    names = {e.id: e.name for e in Entity.query.filter(Entity.id.in_([k for k in groups if k != "backbone"]))}
    shown = [{"label": "The backbone" if k == "backbone" else f"Plugged into {names.get(k, '')}", "rows": g}
             for k, g in groups.items()]
    counts = {k: sum(1 for r in rows if r["state"] == k) for k in ("likely", "check", "choose")}
    return jsonify(ok=True, html=render_template("network/cabling_review.html", groups=shown, count=len(rows),
                                                 counts=counts, ends=setup_ends(None), back=_back(form.get("back"))))


@bp.route("/cables/suggest/add", methods=["POST"])
@role("editor")
def cables_suggest_add():
    """The cables ticked, made."""
    form = request.get_json(silent=True) or {}
    done = add_reviewed(form)
    db.session.commit()
    return jsonify(ok=True, html=render_template("network/cabling_done.html", done=done,
                                                 back=_back(form.get("back"))))
