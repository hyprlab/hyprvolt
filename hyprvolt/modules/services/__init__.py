"""Services: what people actually use. A web app, a mail server, a reverse
proxy, with its address, ports, who uses it, how much it matters, and what
it runs on.

"Runs on" points at anything with the ``host`` trait and "Domain" at
anything with the ``domain`` trait (Network's domains), and both are kept as
links: runs on and depends on. So the dependency view of a server lists the
services that go down with it, and a domain's lists what breaks if it
lapses, without Services needing either module. The ``tls`` trait lets
Certificates say which certificate a service serves.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, SetupField, SetupKind, SetupStep, Widget

from . import demo, views
from .models import ServiceDetail

KINDS = (("web", "Web app"), ("files", "File sharing"), ("mail", "Mail"), ("dns", "DNS"), ("vpn", "VPN"),
         ("proxy", "Reverse proxy"), ("database", "Database"), ("monitoring", "Monitoring"),
         ("backup", "Backup"), ("media", "Media"), ("automation", "Automation"), ("other", "Other"))
CRITICALITY = (("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical"))
STATUSES = (("running", "Running"), ("degraded", "Degraded"), ("down", "Down"), ("planned", "Planned"),
            ("retired", "Retired"))

ICON = ('<path d="M12 3.5 4.5 7.5v4.2c0 4.3 3.1 7.7 7.5 8.8 4.4-1.1 7.5-4.5 7.5-8.8V7.5L12 3.5Z"/>'
        '<path d="m8.8 12.2 2.2 2.2 4.2-4.4"/>')

module = Module(
    id="services",
    name="Services",
    icon=ICON,
    description="What people use: web apps, mail, DNS, VPN and the rest, with what each runs on.",
    group="Operations",
    order=50,
    models=(ServiceDetail,),
    types=(
        EntityType("service", "Service", "Services", detail=ServiceDetail, located_in=(), icon=ICON,
                   statuses=STATUSES, traits=("supplied", "tls"),
                   fields=(Field("kind", "Kind", "select", options=KINDS, list=True),
                           Field("url", "Address", "url", card=True, help="Where people reach it."),
                           Field("host", "Runs on", "ref", trait="host", relation="runs_on", card=True, list=True,
                                 help="A server, VM, container or stack. More than one: link the rest in "
                                      "Relationships."),
                           Field("domain", "Domain", "ref", trait="domain", relation="depends_on",
                                 help="The domain its address is under."),
                           Field("ports", "Ports", help="443/tcp, 51820/udp"),
                           Field("users", "Used by", help="Everyone at home, the office, the public."),
                           Field("criticality", "Importance", "select", options=CRITICALITY, default="normal",
                                 card=True, list=True))),
    ),
    filters=(ListFilter("important", "High and critical", views.important),
             ListFilter("trouble", "Degraded or down", views.not_running)),
    widgets=(Widget("services", "Services", views.services_widget),),
    setup=(SetupStep("services", "Services", "What people use: a website, file sharing, a media server, "
                     "DNS. Say what each runs on, so a host going down shows what goes with it.", 90,
                     kinds=(SetupKind("Service", "service"),),
                     fields=(SetupField("name", placeholder="Jellyfin"), SetupField("f.kind"), SetupField("f.host"),
                             SetupField("f.url"))),),
    seed=demo.seed,
)
