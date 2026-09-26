"""Virtual's tabs, filter and widget: what runs on a hypervisor, a cluster
or a Docker host, and how much of the hardware underneath it is handed out."""
from flask import render_template
from sqlalchemy.orm import aliased

from hyprvolt.core import present
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.modules.hardware.models import HardwareDetail

from .models import VirtualDetail

GUESTS = ("vm", "lxc")
#: Types whose host is a field kept as a "runs on" link.
HOSTED = ("vm", "lxc", "docker_host", "stack", "container")


def _sources(target_ids, kind, types) -> list[Entity]:
    """Live records of ``types`` linked by ``kind`` to any of ``target_ids``."""
    if not target_ids:
        return []
    return (Entity.live().join(Relationship, Relationship.source_id == Entity.id)
            .filter(Relationship.kind == kind, Relationship.target_id.in_(target_ids), Entity.type.in_(types))
            .order_by(Entity.name).distinct().all())


def _target(entity_id, kind, types) -> Entity | None:
    target = aliased(Entity)
    return (db.session.query(target).join(Relationship, Relationship.target_id == target.id)
            .filter(Relationship.source_id == entity_id, Relationship.kind == kind,
                    target.type.in_(types), target.deleted_at.is_(None))
            .order_by(Relationship.id).first())


def _details(entities) -> dict[int, VirtualDetail]:
    ids = [e.id for e in entities]
    return {d.entity_id: d for d in VirtualDetail.query.filter(VirtualDetail.entity_id.in_(ids))} if ids else {}


def _num(value) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def capacity(hosts: list[Entity]) -> dict:
    """What the guests of ``hosts`` are given, against the cores and memory
    of the hardware the hosts run on. Only running guests count: a stopped
    VM or a template holds no memory."""
    guests = _sources([h.id for h in hosts], "runs_on", GUESTS)
    details = _details(guests)
    running = [g for g in guests if g.status == "running"]
    vcpus = sum(details[g.id].vcpus or 0 for g in running if g.id in details)
    memory = sum(details[g.id].memory_gb or 0 for g in running if g.id in details)
    cores = ram = 0
    for host in hosts:
        machine = _target(host.id, "runs_on", ("server", "workstation", "nas"))
        spec = db.session.get(HardwareDetail, machine.id) if machine else None
        cores += (spec.cpu_cores or 0) if spec else 0
        ram += (spec.ram_gb or 0) if spec else 0

    def meter(label, used, total, unit):
        return {"label": label, "used": _num(used), "total": _num(total) if total else "", "unit": unit,
                "percent": min(100, round(100 * used / total)) if total else 0, "over": bool(total) and used > total}
    return {"guests": guests, "details": details, "running": len(running),
            "meters": [meter("vCPUs", vcpus, cores, "cores"), meter("Memory", memory, ram, "GB")]}


def _guest_rows(guests, details, hosts_by_guest=None) -> list[dict]:
    rows = []
    for v in present.views(guests):
        d = details.get(v.id)
        facts = []
        if d is not None:
            if d.vcpus:
                unit = "vCPU" if v.entity.type == "vm" else ("core" if d.vcpus == 1 else "cores")
                facts.append(f"{d.vcpus} {unit}")
            if d.memory_gb:
                facts.append(f"{_num(d.memory_gb)} GB")
            if d.disk_gb:
                facts.append(f"{_num(d.disk_gb)} GB disk")
        rows.append({"view": v, "facts": facts, "host": (hosts_by_guest or {}).get(v.id)})
    return rows


# ———— Tabs ————

def guests_tab(host: Entity) -> str:
    cap = capacity([host])
    return render_template("virtual/guests.html", host=host, cap=cap, rows=_guest_rows(cap["guests"], cap["details"]),
                           machine=_target(host.id, "runs_on", ("server", "workstation", "nas")), cluster=False)


def guest_count(host: Entity):
    return len(_sources([host.id], "runs_on", GUESTS)) or None


def cluster_tab(cluster: Entity) -> str:
    hosts = _sources([cluster.id], "part_of", ("hypervisor",))
    cap = capacity(hosts)
    where = {}
    for g in cap["guests"]:
        host = _target(g.id, "runs_on", ("hypervisor",))
        where[g.id] = host
    return render_template("virtual/guests.html", host=cluster, cap=cap, hosts=present.views(hosts),
                           rows=_guest_rows(cap["guests"], cap["details"], where), machine=None, cluster=True)


def cluster_count(cluster: Entity):
    hosts = _sources([cluster.id], "part_of", ("hypervisor",))
    return len(_sources([h.id for h in hosts], "runs_on", GUESTS)) or None


def containers_tab(entity: Entity) -> str:
    """A Docker host's stacks and containers, or a stack's containers."""
    if entity.type == "stack":
        containers = _sources([entity.id], "part_of", ("container",))
        stacks = []
    else:
        containers = _sources([entity.id], "runs_on", ("container",))
        stacks = _sources([entity.id], "runs_on", ("stack",))
    details = _details(containers)
    in_stack = {}
    for c in containers:
        stack = _target(c.id, "part_of", ("stack",))
        in_stack.setdefault(stack.id if stack else None, []).append(c)
    groups = [{"stack": s, "items": _container_rows(in_stack.get(s.id, []), details)} for s in stacks]
    loose = [c for c in containers if not any(c in in_stack.get(s.id, []) for s in stacks)]
    if entity.type == "stack":
        groups = [{"stack": None, "items": _container_rows(containers, details)}]
    elif loose:
        groups.append({"stack": None, "items": _container_rows(loose, details)})
    if entity.type == "stack":
        docker = _target(entity.id, "runs_on", ("docker_host",))
        preset = {"stack": entity.id, **({"host": docker.id} if docker else {})}
    else:
        preset = {"host": entity.id}
    return render_template("virtual/containers.html", entity=entity, groups=groups, total=len(containers),
                           preset=preset)


def _container_rows(containers, details) -> list[dict]:
    out = []
    for v in present.views(containers):
        d = details.get(v.id)
        out.append({"view": v, "facts": [x for x in ((d.image, d.ports) if d else ()) if x]})
    return out


def container_count(entity: Entity):
    kind = "part_of" if entity.type == "stack" else "runs_on"
    return len(_sources([entity.id], kind, ("container",))) or None


# ———— The sidebar and the dashboard ————

def no_host(query):
    """Hosted records with no host to run on: something to fill in."""
    target = aliased(Entity)
    hosted = (db.session.query(Relationship.source_id).join(target, target.id == Relationship.target_id)
              .filter(Relationship.kind == "runs_on", target.deleted_at.is_(None)))
    return query.filter(Entity.type.in_(HOSTED), Entity.status.notin_(("planned", "retired", "template")),
                        Entity.id.notin_(hosted))


def hypervisor_widget() -> str:
    rows = []
    for host in Entity.live().filter(Entity.type == "hypervisor", Entity.archived.is_(False)).order_by(Entity.name).limit(12):
        cap = capacity([host])
        rows.append({"host": host, "guests": len(cap["guests"]), "memory": cap["meters"][1]})
    return render_template("virtual/widget.html", rows=rows)
