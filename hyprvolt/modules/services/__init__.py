"""Services: what people actually use. A web app, a mail server, a reverse
proxy, with its address, ports, who uses it, how much it matters, and what
it runs on. A Homepage dashboard's services can be read in, each matched to
what it runs on (homepage.py).

"Runs on" points at anything with the ``host`` trait and "Domain" at
anything with the ``domain`` trait (Network's domains), and both are kept as
links: runs on and depends on. So the dependency view of a server lists the
services that go down with it, and a domain's lists what breaks if it
lapses, without Services needing either module. The ``tls`` trait lets
Certificates say which certificate a service serves.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, Page, SetupField, SetupKind, SetupStep, Widget

from . import demo, homepage, views
from .models import ServiceDetail

#: What a service is, under headings in the list (KIND_GROUPS); Other last.
KINDS = (
    ("dhcp", "DHCP"), ("dns", "DNS"), ("ddns", "Dynamic DNS"), ("vpn", "VPN"), ("proxy", "Reverse proxy"),
    ("loadbalancer", "Load balancer"), ("routing", "Routing and firewall"), ("tunnel", "Tunnel"),
    ("controller", "Network controller"), ("ntp", "Time (NTP)"),
    ("directory", "Directory (LDAP)"), ("sso", "Single sign-on"), ("passwords", "Password manager"),
    ("ca", "Certificate authority"), ("security", "Security monitoring"),
    ("monitoring", "Monitoring"), ("logging", "Logging"), ("backup", "Backup"),
    ("containers", "Container management"), ("git", "Code hosting"), ("cicd", "CI/CD"),
    ("registry", "Image registry"), ("automation", "Automation"), ("broker", "Message broker"),
    ("files", "File sharing"), ("objects", "Object storage"), ("database", "Database"),
    ("documents", "Document management"),
    ("web", "Web app"), ("dashboard", "Dashboard"), ("mail", "Mail"), ("chat", "Chat"), ("wiki", "Wiki"),
    ("media", "Media"), ("downloads", "Downloads"), ("photos", "Photos"), ("smarthome", "Home automation"),
    ("nvr", "Cameras (NVR)"), ("pbx", "Phone system (PBX)"), ("print", "Printing"),
    ("remote", "Remote access"), ("ai", "AI"), ("games", "Game server"),
    ("other", "Other"),
)
KIND_GROUPS = (
    ("Network", ("dhcp", "dns", "ddns", "vpn", "proxy", "loadbalancer", "routing", "tunnel", "controller", "ntp")),
    ("Security and identity", ("directory", "sso", "passwords", "ca", "security")),
    ("Operations", ("monitoring", "logging", "backup", "containers", "git", "cicd", "registry", "automation",
                    "broker")),
    ("Storage and data", ("files", "objects", "database", "documents")),
    ("Apps", ("web", "dashboard", "mail", "chat", "wiki", "media", "downloads", "photos", "smarthome", "nvr",
              "pbx", "print", "remote", "ai", "games")),
)
CRITICALITY = (("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical"))
STATUSES = (("running", "Running"), ("degraded", "Degraded"), ("down", "Down"), ("planned", "Planned"),
            ("retired", "Retired"))

ICON = ('<path d="M12 3.5 4.5 7.5v4.2c0 4.3 3.1 7.7 7.5 8.8 4.4-1.1 7.5-4.5 7.5-8.8V7.5L12 3.5Z"/>'
        '<path d="m8.8 12.2 2.2 2.2 4.2-4.4"/>')

#: What goes in each of the module's steps of the site setup guide, and
#: why: the paragraphs behind the step's info button.
SETUP_HELP = {
    "services": (
        "A service is something people use that you run: a website, file sharing, a media server, DNS, "
        "SABnzbd. Say what it runs on (a server, a VM or a container), so the dependency view shows what "
        "breaks when that host goes down.",
        "An outside company it relies on, such as a Usenet provider or a cloud host, is a vendor, linked in "
        "the service's Supplier section.",
    ),
}


module = Module(
    id="services",
    name="Services",
    icon=ICON,
    description="What people use: web apps, mail, DNS, VPN and the rest, with what each runs on.",
    group="Operations",
    order=50,
    models=(ServiceDetail,),
    blueprint=homepage.bp,
    pages=(Page("homepage", "Import from Homepage", homepage.page),),
    types=(
        EntityType("service", "Service", "Services", detail=ServiceDetail, located_in=(), icon=ICON,
                   statuses=STATUSES, traits=("supplied", "tls"),
                   fields=(Field("kind", "Kind", "select", options=KINDS, groups=KIND_GROUPS, list=True),
                           Field("url", "Address", "url", card=True,
                                 help="Where people reach it: a web address, or an IP address or hostname with "
                                      "a port if it has one, such as 192.168.1.1 for DHCP on the router."),
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
                     group="What runs",
                     help=SETUP_HELP["services"], plan="services", kinds=(SetupKind("Service", "service"),),
                     extra=homepage.setup_extra,
                     fields=(SetupField("name", placeholder="Jellyfin"), SetupField("f.kind"), SetupField("f.host"),
                             SetupField("f.url"))),),
    seed=demo.seed,
)
