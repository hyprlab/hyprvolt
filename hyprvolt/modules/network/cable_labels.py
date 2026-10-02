"""Cable labels worked out from the network each cable is on, for the site
setup guide's Cables step.

A cable to a device takes the number of its network and a running number:
"20-03" is the third cable on VLAN 20. The network is the VLAN of the
switch port it plugs into, if that port has one, otherwise the subnet of
the device's address (one the switch carries, of several), by the VLAN's
number or, with no VLAN, the subnet's third number (192.168.50.0/24 is
50). A cable between two pieces of network gear is an uplink, "UP-01";
from a modem to the gateway, "WAN-01"; and one whose network isn't known,
"C-01". Through a patch panel, the devices at the ends of the path count.
"""
import ipaddress
import re

from hyprvolt.core import records
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from . import addresses, ports
from .models import Cable, NetworkDetail, Port

#: Network gear: a cable between two of these is an uplink.
GEAR = {"modem", "router", "firewall", "switch", "moca", "bridge", "patch_panel", "extender"}


def taken() -> set[str]:
    """Every cable label in use, upper case."""
    return {label.upper() for (label,) in db.session.query(Cable.label) if label}


def next_label(prefix: str, used: set[str]) -> str:
    """The prefix's next free number: "20-04" after "20-01" to "20-03"
    (and any gap left by a cable removed stays a gap)."""
    pattern = re.compile(rf"^{re.escape(prefix.upper())}-(\d+)$")
    numbers = [int(m.group(1)) for m in map(pattern.match, used) if m]
    label = f"{prefix}-{(max(numbers) + 1 if numbers else 1):02d}"
    used.add(label.upper())
    return label


def _far_side(end) -> tuple[Entity, Port | None]:
    """The device at the end of the path on this side of a cable, through
    any patch panels, and the port it ends at."""
    if isinstance(end, Entity):
        return end, None
    p, seen = end, set()
    while p.pair is not None and p.id not in seen:
        seen.add(p.id)
        cable = ports.cable_of(p.pair)
        if cable is None:
            break
        p = cable.other(p.pair)
    return p.device, p


def _prefix_of(subnet: Entity | None) -> str | None:
    """A subnet's number: its VLAN's, or its range's third number."""
    if subnet is None:
        return None
    detail = db.session.get(NetworkDetail, subnet.id)
    if detail is None:
        return None
    vlan = db.session.get(NetworkDetail, detail.vlan) if detail.vlan else None
    if vlan is not None and vlan.vid and records.live(vlan.entity_id) is not None:
        return str(vlan.vid)
    try:
        net = ipaddress.ip_network(detail.cidr or "")
    except ValueError:
        return None
    return str(net.network_address.packed[2]) if net.version == 4 else None


def _subnets(device: Entity) -> list[Entity]:
    found = [addresses.subnet_of(d.address) for _, d in addresses.addresses_of(device)]
    return [s for s in dict.fromkeys(found) if s is not None]


def label_for(a, b, used: set[str]) -> str:
    """The label for a cable between two ends (each a port, or a device
    cabled as a whole), taken from ``used`` and added to it."""
    from .views import carriers_of
    (da, pa), (db_, pb) = _far_side(a), _far_side(b)
    roles = {da.id: ports.role(da), db_.id: ports.role(db_)}
    gear = [d for d in (da, db_) if roles[d.id] in GEAR]
    if len(gear) == 2:
        if "modem" in roles.values():
            return next_label("WAN", used)
        # A trunk carries several: an uplink, unless one end is set to one VLAN.
        vlan = next((p.vlan for p in (pa, pb) if p is not None and p.vlan is not None and not p.tagged), None)
        if vlan is None:
            return next_label("UP", used)
    # The VLAN set on the gear's port, else the device's own subnet.
    for p in (pa, pb):
        if p is not None and p.vlan is not None and p.vlan.deleted_at is None:
            vid = db.session.get(NetworkDetail, p.vlan.id)
            if vid is not None and vid.vid:
                return next_label(str(vid.vid), used)
    device = next((d for d in (da, db_) if roles[d.id] not in GEAR), None) or da
    other = db_ if device is da else da
    subnets = _subnets(device)
    subnet = next((s for s in subnets if other.id in carriers_of([s.id])), None)
    if subnet is None and subnets:
        subnet = min(subnets, key=lambda s: addresses.ip_key((db.session.get(NetworkDetail, s.id).cidr or "")
                                                             .split("/")[0]))
    return next_label(_prefix_of(subnet) or "C", used)


def end_of(value):
    """A cable end as the guide's choices name it: "port:12", "device:3"."""
    kind, _, raw = str(value or "").partition(":")
    if not raw.isdigit():
        return None
    return db.session.get(Port, int(raw)) if kind == "port" else records.live(int(raw)) if kind == "device" else None


def label_unlabeled(device_ids, user=None) -> int:
    """Give every cable with no label, between these devices, one of its
    own. How many were labeled."""
    used, n = taken(), 0
    ids = set(device_ids)
    for cable in Cable.query.filter(Cable.label == "").order_by(Cable.id).all():
        if cable.a.device_id not in ids and cable.b.device_id not in ids:
            continue
        if cable.a.device.deleted_at is not None or cable.b.device.deleted_at is not None:
            continue
        a = cable.a if cable.a.name else cable.a.device
        b = cable.b if cable.b.name else cable.b.device
        ports.relabel(cable, label_for(a, b, used), user)
        n += 1
    return n
