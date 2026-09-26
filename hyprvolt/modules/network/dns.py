"""DNS records written down by hand under a domain, what they point at in
the documentation, and the palette search over names and MAC addresses."""
import ipaddress
import re

from hyprvolt.core import records
from hyprvolt.core.api import like
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.manifest import SearchResult
from hyprvolt.models import db

from .models import DNS_TYPES, DnsRecord, NetworkDetail, Port

NAME_RE = re.compile(r"^(@|\*|(\*\.)?[a-z0-9_]([a-z0-9_-]{0,62})(\.[a-z0-9_]([a-z0-9_-]{0,62}))*)$")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62})(\.[a-z0-9]([a-z0-9-]{0,62}))+$|^[a-z0-9-]{1,63}$")


def check_domain(entity, detail):
    name = entity.name.strip().lower().rstrip(".")
    if not DOMAIN_RE.match(name):
        raise Invalid("A domain's name is the domain itself, such as example.net or lab.home.")
    entity.name = name


def records_of(domain_id: int) -> list[DnsRecord]:
    rows = DnsRecord.query.filter_by(domain_id=domain_id).all()
    order = {t: i for i, t in enumerate(DNS_TYPES)}
    return sorted(rows, key=lambda r: (r.name != "@", r.name, order.get(r.type, 99), r.value))


def _int(data, key, label, low, high):
    raw = data.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise Invalid(f"{label} must be a whole number.") from None
    if not low <= value <= high:
        raise Invalid(f"{label} must be between {low:,} and {high:,}.")
    return value


def add_record(domain: Entity, data: dict) -> DnsRecord:
    name = str(data.get("name") or "@").strip().lower().rstrip(".")
    if name.endswith("." + domain.name):
        name = name[: -len(domain.name) - 1]
    elif name == domain.name:
        name = "@"
    if not NAME_RE.match(name) or len(name) > 253:
        raise Invalid("The name is @ for the domain itself, or the part before it: www, mail, _dmarc.")
    rtype = str(data.get("type") or "").upper()
    if rtype not in DNS_TYPES:
        raise Invalid("Choose the record's type.")
    value = " ".join(str(data.get("value") or "").split())
    if not value:
        raise Invalid("Give the record a value.")
    if len(value) > 1000:
        raise Invalid("A value is limited to 1,000 characters.")
    if rtype in ("A", "AAAA"):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise Invalid(f"An {rtype} record points at an IP address.") from None
        if (address.version == 4) != (rtype == "A"):
            raise Invalid("An A record takes an IPv4 address, an AAAA record an IPv6 one.")
        value = str(address)
    priority = _int(data, "priority", "The priority", 0, 65535)
    if rtype in ("MX", "SRV") and priority is None:
        raise Invalid(f"An {rtype} record needs a priority.")
    record = DnsRecord(domain_id=domain.id, name=name, type=rtype, value=value,
                       ttl=_int(data, "ttl", "The TTL", 1, 2_147_483_647), priority=priority,
                       note=" ".join(str(data.get("note") or "").split())[:200])
    db.session.add(record)
    db.session.flush()
    records.audit(domain, "added a DNS record", [{"field": "dns", "label": "DNS record", "old": "",
                                                  "new": describe(record)}])
    return record


def remove_record(record: DnsRecord) -> dict:
    snapshot = {"name": record.name, "type": record.type, "value": record.value, "ttl": record.ttl,
                "priority": record.priority, "note": record.note}
    records.audit(record.domain, "removed a DNS record", [{"field": "dns", "label": "DNS record",
                                                           "old": describe(record), "new": ""}])
    db.session.delete(record)
    return snapshot


def describe(r: DnsRecord) -> str:
    return f"{r.fqdn} {r.type} {str(r.priority) + ' ' if r.priority is not None else ''}{r.value}"


def record_json(r: DnsRecord) -> dict:
    return {"id": r.id, "domain_id": r.domain_id, "name": r.name, "fqdn": r.fqdn, "type": r.type,
            "value": r.value, "ttl": r.ttl, "priority": r.priority, "note": r.note}


def targets(rows: list[DnsRecord]) -> dict[int, Entity]:
    """record id -> the documented record it points at: an A or AAAA to the
    device holding the address, a CNAME to the device its name's A record
    points at (one step)."""
    ip_owner = {}
    for e, d in (db.session.query(Entity, NetworkDetail).join(NetworkDetail, NetworkDetail.entity_id == Entity.id)
                 .filter(Entity.type == "ip_address", Entity.deleted_at.is_(None))):
        owner = records.live(d.assigned) if d.assigned else None
        ip_owner[d.address] = owner or e
    by_name = {}
    cnames = [r for r in rows if r.type == "CNAME"]
    if cnames:
        wanted = {r.value.lower().rstrip(".") for r in cnames}
        for other in DnsRecord.query.filter(DnsRecord.type.in_(("A", "AAAA"))):
            if other.domain.deleted_at is None and other.fqdn in wanted:
                by_name.setdefault(other.fqdn, other.value)
    out = {}
    for r in rows:
        value = by_name.get(r.value.lower().rstrip(".")) if r.type == "CNAME" else r.value
        if r.type in ("A", "AAAA", "CNAME") and value in ip_owner:
            out[r.id] = ip_owner[value]
    return out


def search(query: str, limit: int) -> list[SearchResult]:
    """DNS names and values, and MAC addresses of ports: what isn't a
    record of its own but is worth finding."""
    q = query.lower().strip()
    out = []
    rows = (DnsRecord.query.join(Entity, Entity.id == DnsRecord.domain_id).filter(Entity.deleted_at.is_(None))
            .all())
    for r in rows:
        if q in r.fqdn or q in r.value.lower():
            out.append(SearchResult(title=r.fqdn, meta=f"{r.type} {r.value}", entity_id=r.domain_id))
            if len(out) >= limit:
                return out
    if len(q.replace(":", "").replace("-", "")) >= 4:
        needle = q.replace("-", ":")
        for p in (Port.query.join(Entity, Entity.id == Port.device_id).filter(Entity.deleted_at.is_(None))
                  .filter(Port.mac.like(like(needle), escape="\\")).limit(limit - len(out))):
            out.append(SearchResult(title=p.mac, meta=f"{p.label}", entity_id=p.device_id))
    return out
