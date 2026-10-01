"""Services from a Homepage dashboard (gethomepage.dev): its services.yaml,
and its docker.yaml if given, read; each service matched to what it runs on;
then made or updated once the person has checked the matches.

Homepage says where a service is in several ways, and each is a clue:

- ``server`` and ``container``: a Docker server named in docker.yaml (its
  host's address) and the container's name on it.
- ``proxmoxNode``, ``proxmoxVMID``: the Proxmox node and the VM or LXC's id.
- ``widget.url``, ``siteMonitor``, ``ping`` and ``href``: addresses, whose
  host is an IP (an IP address record says whose it is), a name in a DNS
  record written down in Network, or a name like a record's own.

Every clue gives the records it points at a score; the best is proposed. A
service is matched when one record is clearly best, to be checked when the
best is only likely, and to be chosen when there is none or a tie. Nothing is
saved until the person imports what they reviewed. Homepage's API keys and
passwords are never read into Hyprvolt.
"""
import ipaddress
import json
import re
from urllib.parse import urlsplit

import yaml
from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup

from hyprvolt.core import records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.permissions import role
from hyprvolt.registry import current as registry

bp = Blueprint("services", __name__)

MAX_BYTES = 1024 * 1024
MAX_SERVICES = 500

#: A service's kind, from words in its widget type, icon and name.
KIND_WORDS = {
    "media": ("sonarr", "radarr", "lidarr", "readarr", "bazarr", "prowlarr", "jackett", "sabnzbd", "nzbget",
              "qbittorrent", "transmission", "deluge", "jellyfin", "plex", "emby", "jellyseerr", "overseerr",
              "ombi", "tautulli", "navidrome", "audiobookshelf", "immich", "photoprism", "kavita", "komga",
              "calibre", "tdarr", "unmanic", "frigate"),
    "dns": ("pihole", "adguard", "technitium", "unbound", "bind9"),
    "proxy": ("traefik", "npm", "nginxproxymanager", "caddy", "haproxy", "swag", "cloudflared", "nginx"),
    "monitoring": ("uptimekuma", "grafana", "prometheus", "glances", "netdata", "scrutiny", "healthchecks",
                   "gatus", "beszel", "dozzle", "loki", "zabbix", "checkmk", "librenms"),
    "automation": ("homeassistant", "nodered", "n8n", "esphome", "zigbee2mqtt", "mosquitto"),
    "files": ("nextcloud", "syncthing", "seafile", "filebrowser", "paperless", "owncloud", "minio"),
    "vpn": ("wireguard", "wgeasy", "tailscale", "headscale", "netbird", "openvpn", "zerotier"),
    "backup": ("proxmoxbackupserver", "duplicati", "kopia", "restic", "urbackup", "borg", "veeam"),
    "database": ("mariadb", "mysql", "postgres", "postgresql", "redis", "mongodb", "influxdb", "couchdb"),
    "mail": ("mailcow", "mailu", "stalwart", "roundcube"),
}

#: How sure a clue is, out of 100. Matched: the best at least SURE and
#: clear of the next by MARGIN; to check: at least LIKELY.
SURE, LIKELY, MARGIN = 80, 50, 15


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _text(value) -> str:
    """A value from the file as text, or "" for one Homepage fills in itself
    ({{HOMEPAGE_VAR_...}}) or that isn't a plain value."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = str(value).strip()
    return "" if "{{" in text else text[:500]


# ———— Reading the files ————

def _yaml(raw: bytes, what: str):
    try:
        return yaml.safe_load(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise Invalid(f"The {what} isn't a text file.") from None
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark is not None else ""
        raise Invalid(f"The {what} isn't valid YAML{where}.") from None


def read_services(raw: bytes) -> list[dict]:
    """Every service in a services.yaml, in order, each with its group: the
    file is a list of groups, each a list of services, where a group may
    hold groups of its own."""
    data = _yaml(raw, "services file")
    found = []

    def walk(items, group):
        for item in items if isinstance(items, list) else ():
            if not isinstance(item, dict) or len(item) != 1:
                continue
            name, value = next(iter(item.items()))
            if isinstance(value, list):
                walk(value, _text(name) or group)
            elif isinstance(value, dict) or value is None:
                found.append(_service(_text(name), value or {}, group))

    for entry in data if isinstance(data, list) else ():
        if isinstance(entry, dict):
            for group, items in entry.items():
                walk(items, _text(group))
    found = [s for s in found if s["name"]]
    if not found:
        raise Invalid("No services found. Choose Homepage's services.yaml, not settings.yaml or bookmarks.yaml.")
    if len(found) > MAX_SERVICES:
        raise Invalid(f"An import takes at most {MAX_SERVICES} services at a time; this file has {len(found)}.")
    return found


def read_docker(raw: bytes) -> dict[str, str]:
    """docker.yaml's servers: name -> the host it reaches them at ("" for a
    local socket)."""
    data = _yaml(raw, "docker file")
    if not isinstance(data, dict):
        raise Invalid("The docker file should list Docker servers by name, as Homepage's docker.yaml does.")
    return {_text(name): _text(conf.get("host")) if isinstance(conf, dict) else ""
            for name, conf in data.items() if _text(name)}


def _service(name: str, props: dict, group: str) -> dict:
    widget = props.get("widget")
    if not isinstance(widget, dict):
        widgets = props.get("widgets")
        widget = widgets[0] if isinstance(widgets, list) and widgets and isinstance(widgets[0], dict) else {}
    href = _text(props.get("href"))
    return {"name": name[:200], "group": group[:60], "href": href if _web(href) else "",
            "description": _text(props.get("description")), "icon": _text(props.get("icon")),
            "server": _text(props.get("server")), "container": _text(props.get("container")),
            "node": _text(props.get("proxmoxNode")), "vmid": _text(props.get("proxmoxVMID")),
            "widget": _text(widget.get("type")),
            # Where it is, the most telling first: the address its widget talks to is the
            # service itself; the link people click may go through a reverse proxy.
            "addresses": [(src, v) for src, v in (("widget", _text(widget.get("url"))),
                                                  ("monitor", _text(props.get("siteMonitor"))),
                                                  ("ping", _text(props.get("ping"))), ("link", href)) if v]}


def _web(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def _host_and_port(address: str) -> tuple[str, int | None]:
    try:
        parts = urlsplit(address if "://" in address else "//" + address)
        return (parts.hostname or "").lower(), parts.port
    except ValueError:
        return "", None


def guess_kind(s: dict) -> str:
    words = {_norm(s["widget"]), _norm(re.sub(r"\.(png|svg|webp|jpe?g)$", "", s["icon"].split("/")[-1])
                                       .removeprefix("si-").removeprefix("mdi-")), _norm(s["name"])}
    words |= {_norm(w) for w in re.split(r"[\s_-]+", s["name"])}
    for kind, names in KIND_WORDS.items():
        if any(n in words for n in names):
            return kind
    return "web"


def ports_of(s: dict) -> str:
    for _, address in s["addresses"]:
        host, port = _host_and_port(address)
        if port:
            return f"{port}/tcp"
    return ""


# ———— What a service runs on ————

class Hosts:
    """Everything a service can run on (types with the ``host`` trait), with
    what the matching looks things up by: names, addresses, what runs on
    what, and a VM's or LXC's id."""

    def __init__(self):
        reg = registry()
        self.types = {t.key: t for t in reg.types.values() if "host" in t.traits and reg.is_enabled(t.module)}
        self.all = Entity.live().filter(Entity.type.in_(list(self.types))).order_by(Entity.name).all() \
            if self.types else []
        self.by_id = {e.id: e for e in self.all}
        self.by_name = {}
        for e in self.all:
            for key in {_norm(e.name), _norm(e.slug)}:
                if key:
                    self.by_name.setdefault(key, []).append(e)
        self.parent = {}
        for rel in Relationship.query.filter(Relationship.kind == "runs_on",
                                             Relationship.source_id.in_(list(self.by_id))):
            if rel.target_id in self.by_id:
                self.parent[rel.source_id] = rel.target_id
        self.children = {}
        for child, parent in self.parent.items():
            self.children.setdefault(parent, []).append(self.by_id[child])
        self.ip = {}
        for e in self.all:
            section = next((s for s in reg.form_sections(self.types[e.type]) if s.key == "addresses"), None)
            if section is not None and section.values is not None:
                for text in str((section.values(e) or {}).get("list", "")).split(","):
                    if text.strip():
                        self.ip.setdefault(text.strip(), e)
        self.dns = _dns_names()

    def named(self, name, types=None) -> list[Entity]:
        return [e for e in self.by_name.get(_norm(name), []) if types is None or e.type in types]

    def on(self, parent, types=None) -> list[Entity]:
        return [e for e in self.children.get(parent.id, []) if types is None or e.type in types]

    def holder(self, host: str):
        """The record an address or a host name points at, and how it was
        found: an IP's record, a DNS record's address, or a name alike."""
        try:
            ip = str(ipaddress.ip_address(host))
            return (self.ip.get(ip), f"{ip} is its address") if ip in self.ip else (None, "")
        except ValueError:
            pass
        target = self.dns.get(host)
        for _ in range(3):                      # a CNAME, followed a little way
            if target in self.dns:
                target = self.dns[target]
        if target and target in self.ip:
            return self.ip[target], f"{host} points at {target}, its address"
        first = host.split(".")[0]
        alike = self.named(first)
        if len(alike) == 1:
            return alike[0], f"the host name {host}"
        return None, ""

    def choices(self) -> list[dict]:
        """Every host to choose from, under its type's name."""
        groups = {}
        for e in self.all:
            groups.setdefault(e.type, []).append((e.id, e.name))
        return [{"label": self.types[k].plural, "options": v} for k, v in groups.items()]


def _dns_names() -> dict[str, str]:
    """Names written down in Network's DNS records: full name -> the
    address (A, AAAA) or the name (CNAME) it points at."""
    if not registry().is_enabled("network"):
        return {}
    try:
        from hyprvolt.modules.network.models import DnsRecord
    except ImportError:
        return {}
    out = {}
    for r in DnsRecord.query.join(Entity, Entity.id == DnsRecord.domain_id).filter(Entity.deleted_at.is_(None)):
        if r.type not in ("A", "AAAA", "CNAME"):
            continue
        full = r.domain.name.lower() if r.name in ("@", "") else f"{r.name.lower()}.{r.domain.name.lower()}"
        out.setdefault(full.rstrip("."), r.value.strip().rstrip(".").lower())
    return out


def match(s: dict, hosts: Hosts, docker: dict) -> list[dict]:
    """The records a service may run on, best first: [{"entity", "score",
    "why"}], one each."""
    found = {}

    def add(entity, score, why):
        if entity is None:
            return
        have = found.get(entity.id)
        if have is None or score > have["score"]:
            found[entity.id] = {"entity": entity, "score": score, "why": why}

    container_types = {"container", "lxc"}
    # Proxmox: the VM or LXC with that id on that node.
    if s["vmid"].isdigit():
        guests = [e for e in hosts.all if e.type in ("vm", "lxc")
                  and str(records.own_values(e).get("vmid") or "") == s["vmid"]]
        on_node = [e for e in guests if s["node"] and hosts.parent.get(e.id)
                   and _norm(hosts.by_id[hosts.parent[e.id]].name) == _norm(s["node"])]
        if len(on_node) == 1:
            add(on_node[0], 100, f"Proxmox node {s['node']}, ID {s['vmid']}")
        elif len(guests) == 1:
            add(guests[0], 85, f"Proxmox ID {s['vmid']}")
        else:
            for g in guests:
                add(g, 60, f"Proxmox ID {s['vmid']}, on more than one node")
    # Docker: the server by its name or its address, then the container on it.
    if s["server"]:
        servers = hosts.named(s["server"], {"docker_host"})
        if not servers and docker.get(s["server"]):
            where, why = hosts.holder(_host_and_port(docker[s["server"]])[0] or docker[s["server"]])
            if where is not None:
                servers = hosts.on(where, {"docker_host"}) or [where]
        for d in servers:
            on_it = [c for c in hosts.on(d, container_types) if s["container"] and _norm(c.name) == _norm(s["container"])]
            if on_it:
                add(on_it[0], 100, f"the container {s['container']} on {d.name}")
            else:
                note = f", where the container {s['container']} isn't recorded" if s["container"] else ""
                add(d, 90 if len(servers) == 1 else 60, f"the Docker server {s['server']}{note}")
        if not servers:
            # A host named like the Docker server: a VM called docker1.
            for e in hosts.named(s["server"]):
                add(e, 70, f"named like the Docker server {s['server']}")
        if not servers and s["container"]:
            alike = hosts.named(s["container"], container_types)
            if len(alike) == 1:
                add(alike[0], 80, f"the container {s['container']}")
    # Addresses: the widget's, the monitor's and the ping's are the service's own;
    # the link may be a reverse proxy's, so it counts for less.
    for source, address in s["addresses"]:
        host, _ = _host_and_port(address)
        where, why = hosts.holder(host) if host else (None, "")
        if where is None:
            continue
        base = 55 if source == "link" else 85
        if why.startswith("the host name"):
            base -= 10
        # A container named like the service on the Docker host at that address is more exact.
        alike = [c for d in hosts.on(where, {"docker_host"}) for c in hosts.on(d, container_types)
                 if _norm(c.name) in (_norm(s["name"]), _norm(s["container"]))]
        if len(alike) == 1:
            add(alike[0], base + 5, f"{why}, and its container is named like it")
        add(where, base, why)
    # A record named like the service: a container, an LXC, a VM.
    for e in hosts.named(s["name"]) + (hosts.named(s["container"]) if s["container"] else []):
        add(e, 60, f"a {hosts.types[e.type].text()} named like it")
    return sorted(found.values(), key=lambda c: (-c["score"], c["entity"].name.lower()))


def verdict(candidates: list[dict]) -> str:
    """"matched", "check" or "choose"."""
    if not candidates:
        return "choose"
    best = candidates[0]["score"]
    second = candidates[1]["score"] if len(candidates) > 1 else 0
    if best >= SURE and best - second >= MARGIN:
        return "matched"
    if best >= LIKELY and best > second:
        return "check"
    return "choose"


def _existing() -> dict[str, Entity]:
    return {_norm(e.name): e for e in Entity.live().filter(Entity.type == "service")}


def clues(s: dict) -> str:
    """What the file says about where a service is, for one with no match."""
    out = []
    if s["server"]:
        out.append(f"the Docker server {s['server']}" + (f" and container {s['container']}" if s["container"] else ""))
    if s["node"] or s["vmid"]:
        out.append(f"Proxmox {' '.join(x for x in (s['node'], s['vmid']) if x)}")
    hosts = sorted({_host_and_port(a)[0] for _, a in s["addresses"]} - {""})
    if hosts:
        out.append("the address " + ", ".join(hosts) if len(hosts) == 1 else "the addresses " + ", ".join(hosts))
    return ", ".join(out[:-1]) + " and " + out[-1] if len(out) > 1 else (out[0] if out else "")


def review(services: list[dict], docker: dict, hosts: "Hosts") -> list[dict]:
    """Each service as the review shows it: what was read, what it is
    proposed to run on, and whether that is matched, to check or to choose."""
    existing = _existing()
    out = []
    for i, s in enumerate(services):
        candidates = match(s, hosts, docker)
        state = verdict(candidates)
        known = existing.get(_norm(s["name"]))
        current = None
        if known is not None:
            host_id = records.own_values(known).get("host")
            current = hosts.by_id.get(host_id) if host_id else None
        proposed = candidates[0]["entity"].id if candidates and state != "choose" else (current.id if current else "")
        out.append({"i": i, "s": s, "kind": guess_kind(s), "ports": ports_of(s), "state": state, "clues": clues(s),
                    "candidates": candidates[:4], "proposed": proposed, "existing": known, "current": current,
                    "data": json.dumps({k: s[k] for k in ("name", "group", "href", "description")})})
    return out


# ———— Importing what was reviewed ————

def import_reviewed(form: dict, user=None) -> dict:
    """Make or update each service as reviewed: ``data<i>`` what was read,
    ``use<i>`` add, update or skip, ``host<i>`` what it runs on, ``kind<i>``
    its kind. One that fails is left out and said why; the rest are kept."""
    kinds = {v for v, _ in _service_kinds()}
    existing, done = _existing(), {"added": [], "updated": [], "skipped": [], "failed": []}
    tag_groups = form.get("tag_groups") in (True, "1", "on", "true")
    count = int(form.get("count") or 0)
    for i in range(min(count, MAX_SERVICES)):
        try:
            data = json.loads(form.get(f"data{i}") or "{}")
        except ValueError:
            continue
        name = str(data.get("name") or "").strip()[:200]
        use = form.get(f"use{i}") or "skip"
        if not name or use == "skip":
            if name:
                done["skipped"].append({"name": name})
            continue
        values = {}
        if form.get(f"kind{i}") in kinds:
            values["f.kind"] = form[f"kind{i}"]
        if _web(str(data.get("href") or "")):
            values["f.url"] = data["href"]
        if form.get(f"ports{i}"):
            values["f.ports"] = str(form[f"ports{i}"])[:300]
        host = str(form.get(f"host{i}") or "")
        if host.isdigit():
            values["f.host"] = int(host)
        group = str(data.get("group") or "").strip()
        nested = db.session.begin_nested()
        try:
            known = existing.get(_norm(name)) if use == "update" else None
            if known is not None:
                if tag_groups and group:
                    values["tags"] = [t.name for t in known.tags] + [group]
                records.update(known, values, user)
                done["updated"].append({"name": name, "entity": known})
            else:
                values.update(name=name, notes=str(data.get("description") or "")[:2000])
                if tag_groups and group:
                    values["tags"] = [group]
                made = records.create("service", values, user)
                done["added"].append({"name": name, "entity": made})
            nested.commit()
        except Invalid as err:
            nested.rollback()
            done["failed"].append({"name": name, "error": str(err)})
    return done


def _service_kinds():
    etype = registry().type("service")
    return next((f.options for f in etype.fields if f.key == "kind"), ())


# ———— The routes and the page ————

def _back() -> str:
    """Where Done goes: the page the import was started from, on this site."""
    back = str(request.values.get("back") or "")
    return back if back.startswith("/") and not back.startswith("//") else url_for("main.module_list",
                                                                                     module_id="services")


def start_html(back: str, dialog: bool = False) -> str:
    """The first step: the files. ``back`` is where Done goes."""
    return render_template("services/homepage.html", back=back, dialog=dialog)


def page() -> str:
    """Import from Homepage, a page of its own under Services."""
    return start_html(url_for("main.module_list", module_id="services"))


def setup_extra(scope) -> str:
    """The guide's Services step: a way to fill it from Homepage."""
    if not current_user.can_edit:
        return ""
    return render_template("services/homepage_guide.html",
                           start=Markup(start_html(request.full_path.rstrip("?"), dialog=True)))


def _file(name, required=True) -> bytes | None:
    upload = request.files.get(name)
    if upload is None or not upload.filename:
        if required:
            raise Invalid("Choose Homepage's services.yaml.")
        return None
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise Invalid(f"A Homepage file to import is limited to {MAX_BYTES // 1024} KB.")
    return raw


@bp.route("/homepage/read", methods=["POST"])
@role("editor")
def homepage_read():
    """Step 2: the services read, each with what it would run on, to check."""
    try:
        services = read_services(_file("services"))
        docker_raw = _file("docker", required=False)
        docker = read_docker(docker_raw) if docker_raw else {}
    except Invalid as err:
        return jsonify(error=str(err)), 400
    hosts = Hosts()
    rows = review(services, docker, hosts)
    counts = {k: sum(1 for r in rows if r["state"] == k) for k in ("matched", "check", "choose")}
    return jsonify(ok=True, html=render_template(
        "services/homepage_review.html", rows=rows, counts=counts, choices=hosts.choices(),
        kinds=_service_kinds(), back=_back(), docker=bool(docker), groups=any(r["s"]["group"] for r in rows)))


@bp.route("/homepage/import", methods=["POST"])
@role("editor")
def homepage_import():
    """Step 3: what was reviewed, made and updated."""
    form = request.get_json(silent=True) or {}
    done = import_reviewed(form)
    db.session.commit()
    return jsonify(ok=True, html=render_template("services/homepage_done.html", done=done,
                                                 back=_back_of(form)))


def _back_of(form) -> str:
    back = str(form.get("back") or "")
    return back if back.startswith("/") and not back.startswith("//") else url_for("main.module_list",
                                                                                     module_id="services")
