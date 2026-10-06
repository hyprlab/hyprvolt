"""IP addresses, subnets and VLANs: the checks across their fields, which
addresses of a subnet are used, reserved, handed out by DHCP or free, and
the IP addresses section other records get in their form.

A site can be more than one network: a local network (a network of the
kind lan) placed in a building is that building's, and its VLANs and
subnets say so in their Network field. An address belongs to the network
of the place its device is in, the nearest local network at or above it,
so two buildings can both use 192.168.1.0/24, and the same address in each.
An address with no device, or whose device is in no local network's place,
takes the network of the subnet that holds it."""
import ipaddress

from flask import g, render_template

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db
from hyprvolt.registry import current as registry

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
    mine = ip_network(detail, fresh=True)
    for _, other in _live_details("ip_address").filter(NetworkDetail.address == detail.address,
                                                        Entity.id != entity.id):
        if not _meets(ip_network(other, fresh=True), mine, detail.address, fresh=True):
            continue                     # the same address in another building's network
        where = records.live(other.assigned) if other.assigned else None
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
    if detail.network is None and detail.vlan:
        # On a VLAN of a building's network: in that network too.
        vd = db.session.get(NetworkDetail, detail.vlan)
        detail.network = vd.network if vd else None
    same = (_live_details("subnet").filter(NetworkDetail.cidr == detail.cidr, Entity.id != entity.id)
            .filter(NetworkDetail.network.is_(detail.network) if detail.network is None
                    else NetworkDetail.network == detail.network).first())
    if same:
        raise Invalid(f"{detail.cidr} is already recorded as {same[0].name}.")


def _netmask(raw: str) -> str:
    """255.255.255.248 from "255.255.255.248", "/29" or "29"; "/64" for an
    IPv6 prefix, which has no dotted form."""
    text = raw.strip().lstrip("/")
    try:
        if text.isdigit():
            n = int(text)
            if n <= 32:
                return str(ipaddress.IPv4Network(f"0.0.0.0/{n}").netmask)
            if n <= 128:
                return f"/{n}"
            raise ValueError
        return str(ipaddress.IPv4Network(f"0.0.0.0/{text}").netmask)
    except ValueError:
        raise Invalid("The subnet mask is written as 255.255.255.248, or /29.") from None


def check_network(entity, detail):
    """A static line's subnet mask, written one way; its gateway inside the
    network of its address, when that is one address."""
    if not detail:
        return
    if detail.netmask:
        detail.netmask = _netmask(detail.netmask)
    if not (detail.static_ip and detail.netmask and detail.gateway and detail.public_ips):
        return
    try:
        address = ipaddress.ip_address(detail.public_ips.strip())
        mask = detail.netmask.lstrip("/") if detail.netmask.startswith("/") else detail.netmask
        net = ipaddress.ip_interface(f"{address}/{mask}").network
    except ValueError:
        return                          # a range or a list: nothing to check it against
    if ipaddress.ip_address(detail.gateway) not in net:
        raise Invalid(f"The gateway {detail.gateway} is outside {net}, the network of {address}.")


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


# ———— Which network ————

def _lans(fresh: bool = False) -> dict[int, int]:
    """place id -> the local network placed there (the first, if several),
    once per request unless ``fresh``: a check runs while records change."""
    if fresh or "_lan_places" not in g:
        rows = (db.session.query(Entity.location_id, Entity.id)
                .join(NetworkDetail, NetworkDetail.entity_id == Entity.id)
                .filter(Entity.type == "network", Entity.deleted_at.is_(None), NetworkDetail.kind == "lan",
                        Entity.location_id.isnot(None)).order_by(Entity.id).all())
        out = {}
        for place, lan in rows:
            out.setdefault(place, lan)
        if fresh:
            return out
        g._lan_places = out
    return g._lan_places


def _parent(entity_id, fresh: bool):
    if fresh:
        return db.session.query(Entity.location_id).filter(Entity.id == entity_id).scalar()
    if "_parents" not in g:
        g._parents = dict(db.session.query(Entity.id, Entity.location_id).filter(Entity.deleted_at.is_(None)))
    return g._parents.get(entity_id)


def network_at(location_id, fresh: bool = False) -> int | None:
    """The local network of a place: one placed there, or at the nearest
    place above it. None where there is none, as in a site that is one
    network."""
    lans = _lans(fresh)
    seen = set()
    while lans and location_id is not None and location_id not in seen:
        if location_id in lans:
            return lans[location_id]
        seen.add(location_id)
        location_id = _parent(location_id, fresh)
    return None


def network_of(entity, fresh: bool = False) -> int | None:
    """The local network of the place a record (a device) is in."""
    return network_at(entity.location_id, fresh) if entity is not None else None


def _network_for(address, location_id, fresh: bool = False) -> int | None:
    """The network of an address on a device in this place: the place's,
    else that of the subnet holding it."""
    found = network_at(location_id, fresh) if location_id is not None else None
    if found is not None:
        return found
    subnet = _holding(address, None, fresh)
    return subnet[2] if subnet else None


def ip_network(detail, fresh: bool = False) -> int | None:
    """The network an address record is in: its device's, else its subnet's."""
    place = _parent(detail.assigned, fresh) if detail.assigned and _lans(fresh) else None
    return _network_for(detail.address, place, fresh)


def _meets(one, other, address, fresh: bool = False) -> bool:
    """Whether two networks are the same for an address: the same one, or
    no network and one with no subnet of its own holding it (a site with a
    local network whose subnets don't name it)."""
    if one == other:
        return True
    if one is not None and other is not None:
        return False
    named = one if other is None else other
    a = ipaddress.ip_address(address)
    return not any(a in net and n == named for _, net, n in _subnets(fresh))


def subnet_of_ip(detail) -> Entity | None:
    """The subnet an address record is in, in its own network."""
    return subnet_of(detail.address, ip_network(detail)) if detail and detail.address else None


# ———— Subnets ————

def all_ips():
    """[(ip entity, detail, address)] for every live IP address record, read
    once per request: a page of subnets shares it."""
    if "_all_ips" in g:
        return g._all_ips
    out = []
    for e, d in _live_details("ip_address"):
        try:
            out.append((e, d, ipaddress.ip_address(d.address)))
        except (TypeError, ValueError):
            continue
    g._all_ips = out
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


def _states():
    """[(address, status, detail)] of every live IP address record, once
    per request: what a count needs, without loading the records."""
    if "_ip_states" not in g:
        out = []
        for d, status in (db.session.query(NetworkDetail, Entity.status)
                          .join(Entity, Entity.id == NetworkDetail.entity_id)
                          .filter(Entity.type == "ip_address", Entity.deleted_at.is_(None))):
            try:
                out.append((ipaddress.ip_address(d.address), status, d))
            except (TypeError, ValueError):
                continue
        g._ip_states = out
    return g._ip_states


def _summary(net, detail, hosts) -> dict:
    """The counts of a subnet, for a card or a row: no records loaded."""
    taken = {a: status for a, status, d in _states() if a in net and _belongs(detail.network, a, d)}
    try:
        dhcp = dhcp_bounds(detail.dhcp_range or "")
    except ValueError:
        dhcp = None
    gateway = ipaddress.ip_address(detail.gateway) if detail.gateway else None
    used = sum(1 for s in taken.values() if s in ("active", "reserved")) + \
        (1 if gateway is not None and gateway in net and gateway not in taken else 0)
    pool = int(dhcp[1]) - int(dhcp[0]) + 1 if dhcp else 0
    return {"net": net, "detail": detail, "hosts": hosts, "rows": None, "grid": None, "documented": len(taken),
            "used": used, "pool": pool, "free": max(hosts - used - pool, 0),
            "percent": min(100, round(100 * (used + pool) / hosts)) if hosts else 0}


def usage(subnet: Entity, grid: bool = True) -> dict | None:
    """What is used, reserved, held for DHCP and free in a subnet. ``grid``
    also lists and lays out every address, for the subnet's own tab; a card
    that only counts leaves it out, and loads no records."""
    detail = db.session.get(NetworkDetail, subnet.id)
    if not detail or not detail.cidr:
        return None
    net = ipaddress.ip_network(detail.cidr)
    hosts = net.num_addresses - (2 if net.version == 4 and net.prefixlen <= 30 else 0)
    if not grid:
        return _summary(net, detail, hosts)
    documented = sorted(((e, d, a) for e, d, a in all_ips() if a in net and _belongs(detail.network, a, d)),
                        key=lambda x: (x[2].version, int(x[2])))
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
    cells_out = None
    if net.version == 4 and net.num_addresses <= GRID_MAX:
        cells = []
        for a in (net.hosts() if net.prefixlen <= 30 else net):
            s = state(a)
            e = by_address.get(a, (None, None))[0]
            owner = owners.get(by_address[a][1].assigned) if a in by_address else None
            cells.append({"address": str(a), "last": str(a).rsplit(".", 1)[1], "state": s, "ip": e, "owner": owner})
        cells_out = cells
    used = sum(1 for r in rows if r["state"] in ("used", "reserved")) + \
        (1 if gateway is not None and gateway in net and gateway not in by_address else 0)
    pool = int(dhcp[1]) - int(dhcp[0]) + 1 if dhcp else 0
    return {"net": net, "detail": detail, "hosts": hosts, "rows": rows, "grid": cells_out,
            "documented": len(rows), "used": used,
            "pool": pool, "free": max(hosts - used - pool, 0),
            "percent": min(100, round(100 * (used + pool) / hosts)) if hosts else 0}


def _subnets(fresh: bool = False) -> list[tuple[int, object, int | None]]:
    """(id, range, network) of every live subnet, once per request."""
    if fresh or "_subnet_rows" not in g:
        out = []
        for e, d in _live_details("subnet"):
            try:
                out.append((e.id, ipaddress.ip_network(d.cidr), d.network))
            except (TypeError, ValueError):
                continue
        if fresh:
            return out
        g._subnet_rows = out
    return g._subnet_rows


def _holding(address, network, fresh: bool = False):
    """The (id, range, network) of the most specific subnet holding
    ``address``: in ``network``, or else in none; with no network given,
    one in none before any other."""
    try:
        a = ipaddress.ip_address(address)
    except (TypeError, ValueError):
        return None
    best = None
    for row in _subnets(fresh):
        if a not in row[1] or (network is not None and row[2] not in (network, None)):
            continue
        key = (row[2] == network, row[1].prefixlen)
        if best is None or key > best[0]:
            best = (key, row)
    return best[1] if best else None


def subnet_of(address: str, network: int | None = None) -> Entity | None:
    """The most specific live subnet holding ``address``, in ``network``
    (or in none) when it is given."""
    found = _holding(address, network)
    return db.session.get(Entity, found[0]) if found else None


def _belongs(subnet_network, a, detail) -> bool:
    """Whether an address in a subnet's range is one of its own, in its
    network (``_meets``). A wider subnet still counts those of the narrower
    ones inside it."""
    if "_ip_networks" not in g:
        g._ip_networks = {}
    if detail.entity_id not in g._ip_networks:
        g._ip_networks[detail.entity_id] = ip_network(detail)
    return _meets(subnet_network, g._ip_networks[detail.entity_id], a)


# ———— The IP addresses section in other records' forms ————

def is_addressable(etype) -> bool:
    return "addressable" in etype.traits


def addresses_of(entity) -> list[tuple[Entity, NetworkDetail]]:
    rows = _live_details("ip_address").filter(NetworkDetail.assigned == entity.id).all()
    return sorted(rows, key=lambda r: ip_key(r[1].address or ""))


def section_form(etype, entity) -> str:
    current = ", ".join(d.address for _, d in addresses_of(entity)) if entity is not None else ""
    return render_template("network/addresses_form.html", current=current)


def section_values(entity) -> dict:
    return {"list": ", ".join(d.address for _, d in addresses_of(entity))}


def _takes_from(entity, holder) -> bool:
    """A hypervisor (a type with the ``takes_host_address`` trait) takes an
    address from the machine it runs on: it is that machine's operating
    system, and the address is where it is reached. The other way round, an
    address the hypervisor has is left with it when its machine lists it
    too, as a server's form saved with its new hypervisor does."""
    from hyprvolt.core import relations
    etype = registry().type(entity.type)
    return (etype is not None and "takes_host_address" in etype.traits
            and any(e.id == holder.id for e in relations.linked("runs_on", entity, "source")))


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
    for text in list(wanted):
        if text in have:
            continue
        # The record of this address in the device's network, not another building's.
        mine = _network_for(text, entity.location_id, fresh=True)
        found = next(((ip, d) for ip, d in _live_details("ip_address").filter(NetworkDetail.address == text)
                      if _meets(ip_network(d, fresh=True), mine, text, fresh=True)), None)
        if found:
            ip, d = found
            holder = records.live(d.assigned) if d.assigned and d.assigned != entity.id else None
            if holder is not None and _takes_from(holder, entity):
                wanted.remove(text)      # the hypervisor on this server has it: it stays there
                continue
            if holder is not None and not _takes_from(entity, holder):
                raise Invalid(f"{text} is assigned to {holder.name}. Change it there first.")
            records.update(ip, {"fields": {"assigned": entity.id}}, user)
            if holder is not None:
                records.audit(holder, "edited", [{"field": "addresses", "label": "IP addresses", "old": text,
                                                  "new": f"moved to {entity.name}"}], user)
                # Named with what each is: a server and its hypervisor often share a name.
                kind = {e.id: registry().type(e.type).text() for e in (holder, entity)}
                records.notice(f"{text} moved from the {kind[holder.id]} {holder.name} to the "
                               f"{kind[entity.id]} {entity.name} running on it.")
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
