"""The Network diagram page's choice of what to draw: a site (when there is
more than one), then within it each building with equipment in it, what is
in no building, each network (a VLAN, or a subnet on none), or the whole
site, as a segmented control above the diagram.

A building is its cabled devices; a network, the devices on it: those with
an address in it, the gear that carries it, those with a port set to the
VLAN, and the wireless gear broadcasting a Wi-Fi network on it. A building
is drawn with what its devices are cabled to, one step beyond (another
building's switch); a network with the links between its own devices only.
"""
from flask import render_template, request, url_for
from markupsafe import Markup

from hyprvolt.core import guide, present
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.modules.network import addresses, cabling
from hyprvolt.modules.network.models import NetworkDetail, Port
from hyprvolt.modules.network.views import carriers_of
from hyprvolt.registry import current as registry


def _sites() -> list[Entity]:
    """The sites with cabled equipment in them, by name."""
    keys = [k for s in registry().setup_steps() if s.scope for k in (x.type for x in s.kinds)]
    sites = Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all() if keys else []
    return [s for s in sites if cabling.parts(s)]


def _networks(scope) -> list[Entity]:
    """The site's VLANs, and its subnets on no VLAN, by name."""
    rows = Entity.live().filter(Entity.type.in_(("vlan", "subnet"))).order_by(Entity.name).all()
    rows = guide.in_site(rows, scope) if scope is not None else rows
    on_vlan = {d.entity_id for d in NetworkDetail.query.filter(
        NetworkDetail.entity_id.in_([e.id for e in rows if e.type == "subnet"]), NetworkDetail.vlan.isnot(None))}
    return [e for e in rows if e.id not in on_vlan]


def network_devices(segment: Entity) -> set[int]:
    """The devices on a VLAN or a subnet (and a VLAN's subnets)."""
    ids = {segment.id}
    if segment.type == "vlan":
        ids |= {e.id for e in Entity.live().join(NetworkDetail, NetworkDetail.entity_id == Entity.id)
                .filter(Entity.type == "subnet", NetworkDetail.vlan == segment.id)}
    out = set(carriers_of(ids))
    for _, d, _ in addresses.all_ips():
        if d.assigned:
            held = addresses.subnet_of_ip(d)
            if held is not None and held.id in ids:
                out.add(d.assigned)
    if segment.type == "vlan":
        out |= {p.device_id for p in Port.query.filter(Port.vlan_id == segment.id)}
    wifi = [d.entity_id for d in NetworkDetail.query.filter(NetworkDetail.vlan.in_(ids) | NetworkDetail.subnet.in_(ids))]
    if wifi:
        out |= {r.target_id for r in Relationship.query.filter(Relationship.kind == "broadcast_by",
                                                               Relationship.source_id.in_(wifi))}
    return out


def page() -> str:
    from .views import draw
    sites = _sites()
    chosen = request.args.get("site", type=int)
    scope = next((s for s in sites if s.id == chosen), None)
    if scope is None and chosen != 0 and sites:
        scope = sites[0]                  # the first site, unless All sites (0) is chosen
    choices, where = [], {}
    if scope is not None:
        held = cabling.parts(scope)
        # Each building with equipment, and what is in no building, when there is more than one.
        for key, name in cabling.units(scope):
            if key != "all":
                choices.append(("b" + key if key != "rest" else "rest", name, "place"))
        names = present.choice_labels(_networks(scope))
        for e in _networks(scope):
            choices.append((f"n{e.id}", names[e.id], "network"))
        where = held
    part = request.args.get("part", "all")
    keys = {k for k, _, _ in choices}
    if part not in keys:
        part = "all"
    only, strict = None, False
    if part.startswith("b") or part == "rest":
        key = part[1:] if part.startswith("b") else "rest"
        only = {i for i, p in where.items() if p == key}
    elif part.startswith("n"):
        segment = db.session.get(Entity, int(part[1:]))
        only, strict = (network_devices(segment) if segment is not None else set()), True
    elif scope is not None:
        only = set(where)
    args = {"site": scope.id} if scope is not None else {"site": 0}
    links = [{"key": k, "label": label, "group": group,
              "href": url_for("main.module_page", module_id="diagram", key="network", part=k, **args)}
             for k, label, group in choices]
    whole = url_for("main.module_page", module_id="diagram", key="network", **args)
    sites_menu = [{"id": s.id, "name": s.name,
                   "href": url_for("main.module_page", module_id="diagram", key="network", site=s.id)}
                  for s in sites] if len(sites) > 1 else []
    return render_template("diagram/view.html", diagram=Markup(draw(only, strict)), links=links, part=part,
                           whole=whole, scope=scope, sites=sites_menu,
                           everywhere=url_for("main.module_page", module_id="diagram", key="network", site=0))
