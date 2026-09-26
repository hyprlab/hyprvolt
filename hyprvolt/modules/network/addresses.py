"""IP addresses, subnets and VLANs: the checks across their fields, which
addresses of a subnet are used, reserved, handed out by DHCP or free, and
the IP addresses section other records get in their form."""
import ipaddress

from flask import render_template

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db

from .models import DnsRecord, NetworkDetail

#: The largest IPv4 subnet drawn as a grid, one cell per address.
GRID_MAX = 1024


def ip_key(text: str):
    """Sort addresses by number, not as text: .9 before .10."""
    try:
        a = ipaddress.ip_address(text)
        return (a.version, int(a))
    except ValueError:
        return (9, 0)


def _live_details(type_key):
    return (db.session.query(Entity, NetworkDetail).join(NetworkDetail, NetworkDetail.entity_id == Entity.id)
            .filter(Entity.type == type_key, Entity.deleted_at.is_(None)))


def dhcp_bounds(text: str):
    """(first, last) of "10.0.30.100-10.0.30.199", or None."""
    if not text:
        return None
    first, sep, last = text.replace("–", "-").partition("-")
    if not sep:
        raise ValueError
    a, b = ipaddress.ip_address(first.strip()), ipaddress.ip_address(last.strip())
    if a.version != b.version or a > b:
        raise ValueError
    return a, b


# ———— Checks (EntityType.check) ————

def check_ip(entity, detail):
    if not detail or not detail.address:
        return
    clash = (_live_details("ip_address").filter(NetworkDetail.address == detail.address, Entity.id != entity.id)
             .first())
    if clash:
        where = records.live(clash[1].assigned) if clash[1].assigned else None
        raise Invalid(f"{detail.address} is already recorded" + (f", assigned to {where.name}." if where else "."))


def check_subnet(entity, detail):
    if not detail or not detail.cidr:
        return
    net = ipaddress.ip_network(detail.cidr)
    if detail.gateway:
        try:
            gw = ipaddress.ip_address(detail.gateway)
        except ValueError:
            raise Invalid("The gateway must be an IP address.") from None
        if gw not in net:
            raise Invalid(f"The gateway {gw} is outside {net}.")
    if detail.dhcp_range:
        try:
            first, last = dhcp_bounds(detail.dhcp_range)
        except ValueError:
            raise Invalid("The DHCP range is two addresses with a dash: 10.0.30.100-10.0.30.199.") from None
        if first not in net or last not in net:
            raise Invalid(f"The DHCP range must be inside {net}.")
        detail.dhcp_range = f"{first}-{last}"
    same = (_live_details("subnet").filter(NetworkDetail.cidr == detail.cidr, Entity.id != entity.id)
            .filter(NetworkDetail.network.is_(detail.network) if detail.network is None
                    else NetworkDetail.network == detail.network).first())
    if same:
        raise Invalid(f"{detail.cidr} is already recorded as {same[0].name}.")


def check_vlan(entity, detail):
    if not detail or detail.vid is None:
        return
    query = _live_details("vlan").filter(NetworkDetail.vid == detail.vid, Entity.id != entity.id)
    query = query.filter(NetworkDetail.network.is_(None) if detail.network is None
                         else NetworkDetail.network == detail.network)
    clash = query.first()
    if clash:
        raise Invalid(f"VLAN {detail.vid} is already {clash[0].name}" +
                      (" in this network." if detail.network else "."))


# ———— Subnets ————

def all_ips():
    """[(ip entity, detail, address)] for every live IP address record."""
    out = []
    for e, d in _live_details("ip_address"):
        try:
            out.append((e, d, ipaddress.ip_address(d.address)))
        except (TypeError, ValueError):
            continue
    return out


def dns_names(addresses) -> dict[str, list[str]]:
    """address -> the names of A and AAAA records that point at it."""
    wanted = set(addresses)
    out: dict[str, list[str]] = {}
    if not wanted:
        return out
    rows = (DnsRecord.query.join(Entity, Entity.id == DnsRecord.domain_id)
            .filter(Entity.deleted_at.is_(None), DnsRecord.type.in_(("A", "AAAA")), DnsRecord.value.in_(wanted)))
    for r in rows:
        out.setdefault(r.value, []).append(r.fqdn)
    return out


def usage(subnet: Entity) -> dict | None:
    detail = db.session.get(NetworkDetail, subnet.id)
    if not detail or not detail.cidr:
        return None
    net = ipaddress.ip_network(detail.cidr)
    hosts = net.num_addresses - (2 if net.version == 4 and net.prefixlen <= 30 else 0)
    documented = sorted(((e, d, a) for e, d, a in all_ips() if a in net), key=lambda x: (x[2].version, int(x[2])))
    try:
        dhcp = dhcp_bounds(detail.dhcp_range or "")
    except ValueError:
        dhcp = None
    gateway = ipaddress.ip_address(detail.gateway) if detail.gateway else None
    by_address = {a: (e, d) for e, d, a in documented}
    assigned = {d.assigned for _, d, _ in documented if d.assigned}
    owners = {e.id: e for e in Entity.live().filter(Entity.id.in_(assigned))} if assigned else {}
    names = dns_names([str(a) for _, _, a in documented])

    def state(a):
        if a in by_address:
            e, _ = by_address[a]
            return "reserved" if e.status == "reserved" else ("retired" if e.status == "retired" else "used")
        if gateway is not None and a == gateway:
            return "gateway"
        if dhcp and dhcp[0] <= a <= dhcp[1]:
            return "dhcp"
        return "free"

    rows = []
    for e, d, a in documented:
        rows.append({"ip": e, "address": str(a), "state": state(a), "owner": owners.get(d.assigned),
                     "names": names.get(str(a), [])})
    grid = None
    if net.version == 4 and net.num_addresses <= GRID_MAX:
        cells = []
        for a in (net.hosts() if net.prefixlen <= 30 else net):
            s = state(a)
            e = by_address.get(a, (None, None))[0]
            owner = owners.get(by_address[a][1].assigned) if a in by_address else None
            cells.append({"address": str(a), "last": str(a).rsplit(".", 1)[1], "state": s, "ip": e, "owner": owner})
        grid = cells
    used = sum(1 for r in rows if r["state"] in ("used", "reserved")) + \
        (1 if gateway is not None and gateway in net and gateway not in by_address else 0)
    pool = int(dhcp[1]) - int(dhcp[0]) + 1 if dhcp else 0
    return {"net": net, "detail": detail, "hosts": hosts, "rows": rows, "grid": grid, "used": used,
            "pool": pool, "free": max(hosts - used - pool, 0),
            "percent": min(100, round(100 * (used + pool) / hosts)) if hosts else 0}


def subnet_of(address: str) -> Entity | None:
    """The most specific live subnet holding ``address``."""
    try:
        a = ipaddress.ip_address(address)
    except ValueError:
        return None
    best = None
    for e, d in _live_details("subnet"):
        try:
            net = ipaddress.ip_network(d.cidr)
        except (TypeError, ValueError):
            continue
        if a in net and (best is None or net.prefixlen > best[1].prefixlen):
            best = (e, net)
    return best[0] if best else None


# ———— The IP addresses section in other records' forms ————

def is_addressable(etype) -> bool:
    return "addressable" in etype.traits


def addresses_of(entity) -> list[tuple[Entity, NetworkDetail]]:
    rows = _live_details("ip_address").filter(NetworkDetail.assigned == entity.id).all()
    return sorted(rows, key=lambda r: ip_key(r[1].address or ""))


def section_form(etype, entity) -> str:
    current = ", ".join(d.address for _, d in addresses_of(entity)) if entity is not None else ""
    return render_template("network/addresses_form.html", current=current)


def section_save(entity, values, user) -> list[dict]:
    """Make the record's addresses the ones listed: new ones become IP
    address records assigned to it, and one taken off the list is deleted
    (Undo in Recently deleted), or only unassigned if it has notes or tags."""
    wanted = []
    for raw in str(values.get("list") or "").replace(";", ",").replace("\n", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            text = str(ipaddress.ip_address(raw.split("/")[0]))
        except ValueError:
            raise Invalid(f"{raw} is not an IP address.") from None
        if text not in wanted:
            wanted.append(text)
    have = {d.address: e for e, d in addresses_of(entity)}
    old = ", ".join(sorted(have, key=ip_key))
    for text in wanted:
        if text in have:
            continue
        found = _live_details("ip_address").filter(NetworkDetail.address == text).first()
        if found:
            ip, d = found
            if d.assigned and d.assigned != entity.id and records.live(d.assigned):
                raise Invalid(f"{text} is assigned to {records.live(d.assigned).name}. Change it there first.")
            records.update(ip, {"fields": {"assigned": entity.id}}, user)
        else:
            records.create("ip_address", {"fields": {"address": text, "assigned": entity.id}}, user)
    for text, ip in have.items():
        if text in wanted:
            continue
        if ip.notes or ip.tags:
            records.update(ip, {"fields": {"assigned": None}}, user)
        else:
            records.delete(ip, user)
    new = ", ".join(sorted(wanted, key=ip_key))
    return [{"field": "addresses", "label": "IP addresses", "old": old, "new": new}] if old != new else []
