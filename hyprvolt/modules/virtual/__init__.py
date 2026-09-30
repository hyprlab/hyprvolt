"""Virtual: what runs on the hardware. Clusters and hypervisors, the VMs and
LXC containers on them, and Docker hosts with their compose stacks and
containers.

Every "where does it run" is a field kept as a link: a VM's host is a
"runs on" link to its hypervisor, a hypervisor's hardware one to a server,
a hypervisor's cluster and a container's stack are "part of" links. So the
form, the Relationships tab and the dependency view all say the same thing,
and "what breaks if this server goes down" reaches every container on it.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, SetupField, SetupKind, SetupStep, Tab, Widget

from . import demo, views
from .models import VirtualDetail

PLATFORMS = (("proxmox", "Proxmox VE"), ("vmware", "VMware ESXi"), ("hyperv", "Hyper-V"),
             ("xcpng", "XCP-ng"), ("kvm", "KVM"), ("other", "Other"))
GUEST_STATUSES = (("running", "Running"), ("stopped", "Stopped"), ("template", "Template"),
                  ("planned", "Planned"), ("retired", "Retired"))
RUN_STATUSES = (("running", "Running"), ("stopped", "Stopped"), ("planned", "Planned"), ("retired", "Retired"))
MACHINES = ("server", "workstation", "nas")
#: Traits other modules look for: an IP address (Network), software
#: installed and services run (Software, Services).
ADDRESSABLE = ("addressable", "host", "tls")
HOST = ("host", "tls")

# ———— Fields ————

PLATFORM = Field("platform", "Platform", "select", options=PLATFORMS, card=True, list=True)
VERSION = Field("version", "Version")
MANAGEMENT = Field("management_url", "Management", "url", help="Where its web interface is.")
OS = Field("os", "Operating system", list=True)
MEMORY = Field("memory_gb", "Memory", "number", min=0, max=100_000, unit="GB", card=True, group="Resources")
DISK = Field("disk_gb", "Disk", "number", min=0, max=10_000_000, unit="GB", group="Resources")
AUTOSTART = Field("autostart", "Starts with its host", "boolean")


def host(label, types, **kw):
    return Field("host", label, "ref", types=types, relation="runs_on", **kw)


# ———— Icons ————

ICON = '<rect x="3.5" y="4.5" width="17" height="12" rx="1.2"/><rect x="7" y="8" width="10" height="5" rx=".6"/><path d="M8 20h8M12 16.5V20"/>'
CLUSTER = '<rect x="3.5" y="4" width="7" height="7" rx="1"/><rect x="13.5" y="4" width="7" height="7" rx="1"/><rect x="8.5" y="13" width="7" height="7" rx="1"/>'
HYPERVISOR = '<rect x="3.5" y="4.5" width="17" height="15" rx="1.2"/><path d="M3.5 9h17M7 6.8h.1M9.5 6.8h.1"/><rect x="7" y="12" width="4" height="4.5" rx=".5"/><rect x="13" y="12" width="4" height="4.5" rx=".5"/>'
VM = ICON
LXC = '<path d="M12 3.5 19.5 7.5v9L12 20.5l-7.5-4v-9L12 3.5Z"/><path d="M4.5 7.5 12 11.5l7.5-4M12 11.5v9"/>'
DOCKER = '<rect x="3.5" y="11" width="17" height="6.5" rx="1.5"/><path d="M6.5 11V8h3v3M9.5 11V8h3v3M12.5 11V5h3v6"/>'
STACK = '<path d="m12 4 8.5 4-8.5 4-8.5-4L12 4Z"/><path d="m3.5 12 8.5 4 8.5-4M3.5 16l8.5 4 8.5-4"/>'
CONTAINER = '<rect x="4" y="6.5" width="16" height="11" rx="1"/><path d="M8 6.5v11M12 6.5v11M16 6.5v11"/>'

#: What goes in each of the module's steps of the site setup guide, and
#: why: the paragraphs behind the step's info button.
SETUP_HELP = {
    "hypervisors": (
        "A hypervisor is the software that runs virtual machines, such as Proxmox, ESXi or Hyper-V, on the "
        "server it is installed on. Recorded apart from the server, it lets each VM say which host it runs "
        "on, and shows what stops when that server goes down.",
        "Skip this if nothing is virtualized.",
    ),
    "guests": (
        "Virtual machines and LXC containers, each on its hypervisor, with its operating system and address. "
        "Docker hosts, stacks and containers can be added later in Virtual.",
        "What a VM runs for people, such as a media server or a website, is a service: the next step.",
    ),
}


module = Module(
    id="virtual",
    name="Virtual",
    icon=ICON,
    description="Clusters, hypervisors, VMs, LXC containers, Docker hosts, stacks and containers.",
    group="Infrastructure",
    order=30,
    requires=("hardware",),
    models=(VirtualDetail,),
    types=(
        EntityType("cluster", "Cluster", "Clusters", detail=VirtualDetail, located_in=(), icon=CLUSTER,
                   fields=(PLATFORM, VERSION, MANAGEMENT),
                   tabs=(Tab("guests", "Guests", views.cluster_tab, count=views.cluster_count),)),
        EntityType("hypervisor", "Hypervisor", "Hypervisors", detail=VirtualDetail, located_in=(), icon=HYPERVISOR,
                   traits=ADDRESSABLE,
                   fields=(PLATFORM, VERSION,
                           host("Runs on", MACHINES, card=True, list=True,
                                help="The hardware it is installed on."),
                           Field("cluster", "Cluster", "ref", types=("cluster",), relation="part_of", list=True),
                           MANAGEMENT),
                   tabs=(Tab("guests", "Guests", views.guests_tab, count=views.guest_count),)),
        EntityType("vm", "Virtual machine", "Virtual machines", detail=VirtualDetail, located_in=(), icon=VM,
                   statuses=GUEST_STATUSES, traits=ADDRESSABLE, becomes=("lxc",),
                   fields=(host("Host", ("hypervisor",), card=True, list=True), OS,
                           Field("vmid", "VM ID", "integer", min=0, help="The hypervisor's number for it: 101."),
                           AUTOSTART,
                           Field("vcpus", "vCPUs", "integer", min=1, max=4096, card=True, group="Resources"),
                           MEMORY, DISK)),
        EntityType("lxc", "LXC container", "LXC containers", detail=VirtualDetail, located_in=(), icon=LXC,
                   statuses=GUEST_STATUSES, traits=ADDRESSABLE, becomes=("vm",),
                   fields=(host("Host", ("hypervisor",), card=True, list=True), OS,
                           Field("vmid", "Container ID", "integer", min=0, help="The hypervisor's number for it: 200."),
                           AUTOSTART,
                           Field("vcpus", "Cores", "integer", min=1, max=4096, card=True, group="Resources"),
                           MEMORY, DISK)),
        EntityType("docker_host", "Docker host", "Docker hosts", detail=VirtualDetail, located_in=(), icon=DOCKER,
                   proper=True, traits=HOST,
                   fields=(host("Runs on", ("vm", "lxc") + MACHINES, card=True, list=True),
                           Field("version", "Docker version"),
                           Field("management_url", "Management", "url", help="Portainer or another web interface.")),
                   tabs=(Tab("containers", "Containers", views.containers_tab, count=views.container_count),)),
        EntityType("stack", "Stack", "Stacks", detail=VirtualDetail, located_in=(), icon=STACK,
                   statuses=RUN_STATUSES, traits=HOST,
                   fields=(host("Docker host", ("docker_host",), card=True, list=True),
                           Field("path", "Compose file at", help="/opt/stacks/media/compose.yaml"),
                           Field("repo_url", "Repository", "url"),
                           Field("compose", "Compose file", "longtext")),
                   tabs=(Tab("containers", "Containers", views.containers_tab, count=views.container_count),)),
        EntityType("container", "Container", "Containers", detail=VirtualDetail, located_in=(), icon=CONTAINER,
                   statuses=RUN_STATUSES, traits=ADDRESSABLE,
                   fields=(host("Docker host", ("docker_host",), list=True),
                           Field("stack", "Stack", "ref", types=("stack",), relation="part_of", card=True, list=True),
                           Field("image", "Image", card=True, list=True, help="nginx:1.27"),
                           Field("ports", "Published ports", help="8080:80, 8443:443"))),
    ),
    filters=(ListFilter("no_host", "Without a host", views.no_host),),
    widgets=(Widget("hypervisors", "Hypervisors", views.hypervisor_widget),),
    setup=(
        SetupStep("hypervisors", "Hypervisors", "What runs virtual machines: Proxmox, ESXi or Hyper-V, each on "
                  "the server it is installed on. Skip this if nothing is virtualized.", 80,
                  group="What runs",
                  help=SETUP_HELP["hypervisors"], plan="hypervisors",
                  kinds=(SetupKind("Hypervisor", "hypervisor"),),
                  fields=(SetupField("name", placeholder="pve1"), SetupField("f.platform"), SetupField("f.host"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.20.21"))),
        SetupStep("guests", "Virtual machines and containers", "The virtual machines and LXC containers, each "
                  "on its hypervisor.", 85, group="What runs",
                  help=SETUP_HELP["guests"], plan="virtual machines, containers",
                  kinds=(SetupKind("Virtual machine", "vm"), SetupKind("LXC container", "lxc")),
                  fields=(SetupField("name", placeholder="docker1"), SetupField("f.host"), SetupField("f.os"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.20.21"))),
    ),
    seed=demo.seed,
)
