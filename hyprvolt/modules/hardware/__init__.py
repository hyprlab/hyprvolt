"""Hardware: the physical things. Servers, network gear, firewalls, access
points, UPSes, NAS boxes, workstations, printers and peripherals, each with
its make, serial, asset tag, purchase, warranty and specs, and a lifecycle
status from ordered to disposed.

Where a device is comes from the core's location, and its rack position
from Locations' form section: the types that go in a rack carry the
``rackmount`` trait. Hardware needs Locations for both.
"""
from hyprvolt.manifest import (EntityType, Field, FormSection, ListFilter, Module, RelationKind, SetupField, SetupKind,
                               SetupStep)

from . import demo, views
from .models import HardwareDetail

#: The lifecycle. The first is what a new record starts as: most hardware
#: is written down once it is in use.
STATUSES = (("deployed", "Deployed"), ("ordered", "Ordered"), ("in_stock", "In stock"),
            ("in_repair", "In repair"), ("retired", "Retired"), ("disposed", "Disposed"))

# ———— Fields, shared by the types that use them ————

MANUFACTURER = Field("manufacturer", "Manufacturer", list=True)
MODEL = Field("model", "Model", card=True, list=True)
SERIAL = Field("serial", "Serial number")
ASSET_TAG = Field("asset_tag", "Asset tag", card=True)
IDENTITY = (MANUFACTURER, MODEL, SERIAL, ASSET_TAG)

PURCHASE = (
    Field("purchase_date", "Purchased", "date", group="Purchase"),
    Field("price", "Price", "number", min=0, group="Purchase"),
    Field("vendor", "Bought from", group="Purchase"),
    Field("warranty_until", "Warranty ends", "date", group="Purchase", expires=True),
)

CPU = Field("cpu", "CPU", group="Specs", help="As many as it has: 2 × Xeon E5-2680 v4.")
CORES = Field("cpu_cores", "CPU cores", "integer", min=1, max=4096, group="Specs")
RAM = Field("ram_gb", "Memory", "integer", min=0, max=1_000_000, unit="GB", card=True, group="Specs")
STORAGE = Field("storage", "Disks", "longtext", group="Specs", help="One per line: 2 × 960 GB SSD, mirror.")
NICS = Field("nics", "Network ports", "longtext", group="Specs", help="One per line: 4 × 1 GbE, 2 × 10 GbE SFP+.")
POWER = Field("power_w", "Power draw", "integer", min=0, max=100_000, unit="W", group="Specs")
OS = Field("os", "Operating system", group="Specs")
FIRMWARE = Field("os", "Firmware", group="Specs")
PORTS = Field("ports", "Ports", "integer", min=0, max=1000, card=True, group="Specs")

FORM_FACTORS = (("rack", "Rack mount"), ("tower", "Tower"), ("mini", "Mini PC"), ("blade", "Blade"),
                ("sbc", "Single-board computer"), ("other", "Other"))
NETWORK_KINDS = (("switch", "Switch"), ("router", "Router"), ("modem", "Modem"),
                 ("patch_panel", "Patch panel"), ("extender", "Wireless extender"), ("bridge", "Wireless bridge"),
                 ("other", "Other"))
#: Kinds of network gear with no wireless link to another: all but a bridge.
NOT_BRIDGES = tuple(v for v, _ in NETWORK_KINDS if v != "bridge") + ("",)
#: Kinds of network gear that can broadcast wireless networks (Network's
#: Wireless networks section), as an access point does: a router or an
#: ISP's gateway with Wi-Fi built in, an extender, a bridge.
WIRELESS_KINDS = ("modem", "router", "extender", "bridge")
NOT_WIRELESS = tuple(v for v, _ in NETWORK_KINDS if v not in WIRELESS_KINDS) + ("",)

# ———— Icons, 24×24 stroked paths ————

ICON = '<rect x="3.5" y="4.5" width="17" height="6" rx="1"/><rect x="3.5" y="13.5" width="17" height="6" rx="1"/><path d="M7 7.5h.1M7 16.5h.1M11 7.5h6M11 16.5h6"/>'
SERVER = ICON
NETWORK = '<rect x="2.5" y="8" width="19" height="8" rx="1.2"/><path d="M6 12h.1M9 12h.1M12 12h.1M15 12h.1M18 12h.1"/>'
FIREWALL = '<path d="M12 3.5 5 6v5.5c0 4.2 3 7.8 7 9 4-1.2 7-4.8 7-9V6l-7-2.5Z"/><path d="M8.5 11h7M8.5 14.5h7M12 11v3.5"/>'
ACCESS_POINT = '<path d="M5 9.5a10 10 0 0 1 14 0M7.8 12.5a6 6 0 0 1 8.4 0M10.6 15.5a2 2 0 0 1 2.8 0"/><path d="M12 18.5h.1"/>'
UPS = '<rect x="6.5" y="3.5" width="11" height="17" rx="1.5"/><path d="m12.8 7.5-2.6 4.5h3.6l-2.6 4.5"/>'
NAS = '<rect x="5" y="3.5" width="14" height="17" rx="1.5"/><path d="M8.5 7.5h7M8.5 11h7M8.5 14.5h7M12 17.5h.1"/>'
WORKSTATION = '<rect x="3.5" y="4.5" width="17" height="11" rx="1"/><path d="M9 19.5h6M12 15.5v4"/>'
PRINTER = '<path d="M7 9V4.5h10V9"/><rect x="3.5" y="9" width="17" height="7" rx="1"/><path d="M7 14h10v5.5H7z"/>'
PERIPHERAL = '<rect x="3" y="8" width="18" height="9" rx="1.2"/><path d="M6.5 11h.1M9.5 11h.1M12.5 11h.1M15.5 11h.1M8 14h8"/>'

#: Traits other modules look for. Every hardware type has network ports,
#: can hold an IP address (Network) and has a supplier (Contacts); those
#: that go in a rack say so (Locations), and those that run software or
#: services are hosts (Software, Services) and may serve a certificate.
NET = ("addressable", "cabled", "supplied")
RACK = ("rackmount",) + NET
HOST = ("host", "tls")


KINDS = ("server", "network_device", "firewall", "access_point", "ups", "nas", "workstation", "printer",
         "peripheral")


def hardware(key, label, plural, icon, specs=(), traits=()):
    # Any device can be made another kind: a server recorded as a NAS.
    return EntityType(key, label, plural, detail=HardwareDetail, statuses=STATUSES, icon=icon, traits=traits,
                      inactive=views.GONE, becomes=tuple(k for k in KINDS if k != key),
                      fields=IDENTITY + tuple(specs) + PURCHASE)


#: What goes in each of the module's steps of the site setup guide, and
#: why: the paragraphs behind the step's info button.
SETUP_HELP = {
    "gear": (
        "Network gear is what moves traffic: the modem or ONT, the router or firewall, switches, access "
        "points and patch panels. Give each its management address; it is recorded as an IP address in its "
        "subnet.",
        "The device the ISP's line plugs into gets that line as its Internet connection, so a line that "
        "goes down points straight at it.",
        "A modem in bridge mode passes the internet through to your router, which gets the public address; "
        "the modem has no address on your network, so leave its IP address empty (or give its status page's "
        "address, such as 192.168.100.1). A modem that is the gateway, the ISP's own router, has an address "
        "on your network, usually 192.168.1.1, which is also your subnet's gateway.",
        "A wireless bridge links two places over the air, such as the house and a garage. Add each end as "
        "its own Wireless bridge, with its own location and IP address, and choose the bridge at the other "
        "end as its Other end: the link reads the same from both.",
        "A wireless extender repeats an access point's signal further out. An access point, an extender, a "
        "bridge, and a router or modem with Wi-Fi built in each tick the wireless networks it broadcasts, "
        "from those recorded in the Wireless networks step.",
        "Public addresses belong to the internet connection, not to the device. Computers and storage come "
        "next, and cabling everything together is the last step.",
    ),
    "ups": (
        "A UPS keeps equipment running through a power outage, long enough to ride it out or shut down "
        "cleanly. Record its capacity and runtime, and give it an IP address if it has a network card.",
        "Tick what each one powers, from the network gear, servers and storage recorded in the steps before. "
        "Each is then powered by the UPS, so a UPS that fails shows everything that goes down with it. "
        "Endpoints come later; link one to its UPS from its own record.",
        "A PDU is a peripheral, recorded with the endpoints.",
    ),
    "servers": (
        "Servers and NAS boxes: the machines that run things and keep data. A server that runs virtual "
        "machines is recorded here as hardware; its hypervisor (Proxmox, ESXi) is a later step, running on "
        "it.",
        "Desktops, laptops and printers are endpoints, a later step. The UPS each one is plugged into is the "
        "next step.",
    ),
    "endpoints": (
        "Endpoints are what people use at the edge of the network: workstations and laptops, printers, and "
        "peripherals such as a monitor, a KVM or a PDU. Say who uses a computer and where it is.",
        "Phones and tablets that only join the Wi-Fi rarely need a record; add them if you keep track of "
        "them.",
    ),
}


module = Module(
    id="hardware",
    name="Hardware",
    icon=ICON,
    description="Servers, network gear, UPSes, storage and desks: make, serial, warranty, specs and lifecycle.",
    group="Infrastructure",
    order=20,
    requires=("locations",),
    models=(HardwareDetail,),
    types=(
        hardware("server", "Server", "Servers", SERVER, traits=RACK + HOST, specs=(
            Field("kind", "Form factor", "select", options=FORM_FACTORS, group="Specs",
                  hides=("rack",), hides_when=("tower",)),
            CPU, CORES, RAM, STORAGE, NICS, POWER, OS)),
        hardware("network_device", "Network device", "Network gear", NETWORK, traits=RACK + HOST, specs=(
            Field("kind", "Kind", "select", options=NETWORK_KINDS, list=True, group="Specs",
                  hides=(("bridge", NOT_BRIDGES), ("wifi", NOT_WIRELESS))),
            PORTS, Field("managed", "Managed", "boolean", group="Specs"), FIRMWARE, POWER)),
        hardware("firewall", "Firewall", "Firewalls", FIREWALL, traits=RACK + HOST, specs=(
            PORTS, FIRMWARE, CPU, RAM, POWER)),
        hardware("access_point", "Access point", "Access points", ACCESS_POINT, traits=NET, specs=(
            Field("wifi", "Wi-Fi", group="Specs", help="The standard and bands: Wi-Fi 6, 2.4 and 5 GHz."),
            FIRMWARE, POWER)),
        hardware("ups", "UPS", "UPSes", UPS, traits=RACK, specs=(
            Field("capacity_va", "Capacity", "integer", min=0, max=1_000_000, unit="VA", card=True, group="Specs"),
            Field("runtime_min", "Runtime at load", "integer", min=0, max=10_000, unit="min", group="Specs"),
            Field("battery_due", "Battery due", "date", group="Specs", expires=True,
                  help="When the batteries should be replaced."),
            Field("power_w", "Rated output", "integer", min=0, max=1_000_000, unit="W", group="Specs"))),
        hardware("nas", "NAS", "NAS", NAS, traits=RACK + HOST, specs=(
            Field("drive_bays", "Drive bays", "integer", min=0, max=500, group="Specs"),
            Field("capacity_tb", "Usable capacity", "number", min=0, unit="TB", card=True, group="Specs"),
            STORAGE, CPU, RAM, NICS, POWER, OS)),
        hardware("workstation", "Workstation", "Workstations", WORKSTATION, traits=NET + HOST, specs=(
            Field("assigned_to", "Used by", list=True, group="Specs"),
            CPU, CORES, RAM, STORAGE, OS)),
        hardware("printer", "Printer", "Printers", PRINTER, traits=NET, specs=(FIRMWARE, POWER)),
        hardware("peripheral", "Peripheral", "Peripherals", PERIPHERAL, traits=RACK, specs=(
            Field("category", "What it is", list=True, group="Specs",
                  help="A monitor, a KVM switch, a PDU, a dock."), POWER)),
    ),
    filters=(ListFilter("warranty_soon", "Warranty ending soon", views.warranty_soon),
             ListFilter("warranty_over", "Out of warranty", views.warranty_over)),
    relation_kinds=(RelationKind("wireless_link", "has a wireless link to", "has a wireless link to"),),
    form_sections=(FormSection("bridge", "Wireless link", views.bridge_form, views.bridge_save,
                               when=views.is_bridge_gear, values=views.bridge_values,
                               choices=views.bridge_choices),
                   FormSection("powers", "Powers", views.powers_form, views.powers_save, when=views.is_ups,
                               values=views.powers_values, choices=views.powers_choices)),
    setup=(
        SetupStep("gear", "Network gear", "The equipment that ties your network together. Start where the "
                  "internet comes in, with the modem and the router or firewall, then add your switches, access "
                  "points, extenders and patch panels.", 60,
                  group="Equipment",
                  help=SETUP_HELP["gear"], plan="network gear",
                  kinds=(SetupKind("Modem", "network_device", {"f.kind": "modem"}),
                         SetupKind("Router", "network_device", {"f.kind": "router"}),
                         SetupKind("Firewall", "firewall"),
                         SetupKind("Switch", "network_device", {"f.kind": "switch"}),
                         SetupKind("Access point", "access_point"),
                         SetupKind("Wireless extender", "network_device", {"f.kind": "extender"}),
                         SetupKind("Wireless bridge", "network_device", {"f.kind": "bridge"}),
                         SetupKind("Patch panel", "network_device", {"f.kind": "patch_panel"})),
                  fields=(SetupField("name", placeholder="sw-core"), SetupField("location_id"), SetupField("f.model"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.20.11"),
                          SetupField("s.internet.line", "Internet connection",
                                     kinds=("Modem", "Router", "Firewall")),
                          SetupField("s.bridge.other", "Other end", kinds=("Wireless bridge",)),
                          SetupField("s.wifi.list", "Wireless networks", kind="multi", newline=True,
                                     kinds=("Modem", "Router", "Access point", "Wireless extender",
                                            "Wireless bridge")))),
        SetupStep("servers", "Servers and storage", "Physical machines that store and serve data. A server "
                  "that runs virtual machines is recorded here as hardware; its hypervisor is added in a later "
                  "step.", 70, group="Equipment",
                  help=SETUP_HELP["servers"], plan="servers, storage",
                  kinds=(SetupKind("Server", "server"), SetupKind("NAS", "nas")),
                  fields=(SetupField("name", placeholder="srv1"), SetupField("location_id"), SetupField("f.model"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.20.11"))),
        SetupStep("ups", "UPSes", "The battery backups that keep everything running through a power "
                  "outage, with their capacity, how long they last, and the equipment each one powers.", 75,
                  group="Equipment", help=SETUP_HELP["ups"], plan="UPSes",
                  kinds=(SetupKind("UPS", "ups"),),
                  fields=(SetupField("name", placeholder="ups1"), SetupField("location_id"), SetupField("f.model"),
                          SetupField("f.capacity_va"), SetupField("f.runtime_min"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.10.30"),
                          SetupField("s.powers.list", "Powers", kind="multi", newline=True))),
        SetupStep("endpoints", "Endpoints", "What people use at the edge of the network: computers, printers "
                  "and other devices. Add them all here, one row each.", 100, group="Endpoints",
                  help=SETUP_HELP["endpoints"], plan="endpoints",
                  kinds=(SetupKind("Workstation", "workstation"), SetupKind("Printer", "printer"),
                         SetupKind("Peripheral", "peripheral")),
                  fields=(SetupField("name", placeholder="desk-pc"), SetupField("location_id"),
                          SetupField("f.assigned_to"),
                          SetupField("s.addresses.list", "IP address", placeholder="10.0.20.11"))),
    ),
    seed=demo.seed,
)
