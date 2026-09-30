"""Network: networks, VLANs, subnets and IP addresses; the ports on devices
and the cables between them; domains with the DNS records written down by
hand.

Other modules' types take part through traits: ``addressable`` ones (a
server, a VM) get an IP addresses section in their form and an Addresses
tab, ``cabled`` ones (anything with network ports) a Cabling tab. A cable
goes to a device as a whole unless its ports are recorded. An IP
address is a record of its own, named by its address, and belongs to the
most specific subnet that holds it; which addresses of a subnet are free is
worked out, not stored.
"""
from hyprvolt.core.models import Entity
from hyprvolt.manifest import (EntityType, Field, FormSection, ListFilter, Module, SetupField, SetupKind, SetupStep,
                               Step, Tab, Widget)
from hyprvolt.models import db

from . import addresses, demo, dns, ports, views
from .models import Cable, DnsRecord, NetworkDetail, Port, PortsRecorded

NETWORK_KINDS = (("lan", "Local network"), ("wan", "Internet connection"), ("vpn", "VPN"), ("other", "Other"))
IP_STATUSES = (("active", "In use"), ("reserved", "Reserved"), ("retired", "Retired"))
DOMAIN_STATUSES = (("active", "Active"), ("planned", "Planned"), ("retired", "Expired or given up"))



def _provider_to_notes(m):
    """The ISP was once a line of text on a network. It is a vendor now, in
    the Supplier section, and a vendor can't be guessed from text: what was
    typed goes to the end of the network's notes, where it can still be
    read and searched."""
    m.add_column("network_details", "circuit_id", "VARCHAR(120)")
    if not m.has_column("network_details", "provider"):
        return

    def move():
        rows = db.session.execute(db.text(
            "SELECT entity_id, provider FROM network_details WHERE provider IS NOT NULL AND provider != ''")).all()
        for entity_id, provider in rows:
            entity = db.session.get(Entity, entity_id)
            if entity is not None:
                line = f"Provider: {provider}"
                entity.notes = f"{entity.notes.rstrip()}\n\n{line}" if entity.notes.strip() else line
        db.session.execute(db.text("UPDATE network_details SET provider = NULL"))
    m.once("provider-to-notes", move)


def _ports_recorded(m):
    """Cables once needed a port at each end. A device that has ports keeps
    them on show; any other is cabled as a whole."""
    m.once("ports-recorded", lambda: db.session.execute(db.text(
        "INSERT OR IGNORE INTO network_ports_recorded (device_id) SELECT DISTINCT device_id FROM network_ports")))


NETWORK_REF = Field("network", "Network", "ref", types=("network",), list=True)

ICON = ('<circle cx="12" cy="5.5" r="2"/><circle cx="5.5" cy="18.5" r="2"/><circle cx="18.5" cy="18.5" r="2"/>'
        '<path d="M12 7.5v4.5M12 12l-5.2 4.8M12 12l5.2 4.8"/>')
NETWORK = ICON
VLAN = '<path d="M4 7h16M4 12h16M4 17h16"/><path d="M8 4.5v5M16 9.5v5M11 14.5v5"/>'
SUBNET = '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/><path d="M3.5 12h17M12 3.5v17"/>'
IP = '<path d="M5 6.5h14M5 17.5h14"/><path d="M8.5 9.5v5M11.5 9.5v5h1.8a1.8 1.8 0 0 0 0-3.6h-1.8"/>'
DOMAIN = ('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.3 3.5 5.2 3.5 8.5s-1.1 6.2-3.5 8.5'
          'c-2.4-2.3-3.5-5.2-3.5-8.5s1.1-6.2 3.5-8.5Z"/>')

module = Module(
    id="network",
    name="Network",
    icon=ICON,
    description="Networks, VLANs, subnets and IP addresses, ports and cables, domains and DNS records.",
    group="Infrastructure",
    order=40,
    requires=("hardware",),
    models=(NetworkDetail, Port, Cable, DnsRecord, PortsRecorded),
    migrations=(Step("provider-to-notes", _provider_to_notes), Step("ports-recorded", _ports_recorded)),
    blueprint=views.bp,
    types=(
        EntityType("network", "Network", "Networks", detail=NetworkDetail, located_in=None, icon=NETWORK,
                   traits=("supplied",),
                   fields=(Field("kind", "Kind", "select", options=NETWORK_KINDS, card=True, list=True),
                           Field("public_ips", "Public addresses", help="203.0.113.24, or a range."),
                           Field("bandwidth", "Bandwidth", help="1 Gb/s down, 40 Mb/s up."),
                           Field("circuit_id", "Circuit ID",
                                 help="For an internet connection: what the ISP calls this line when you report "
                                      "a fault. The ISP itself goes in Supplier, as a vendor.")),
                   tabs=(Tab("contents", "VLANs and subnets", views.network_tab, count=views.network_count),)),
        EntityType("vlan", "VLAN", "VLANs", detail=NetworkDetail, located_in=(), icon=VLAN,
                   check=addresses.check_vlan,
                   fields=(Field("vid", "VLAN ID", "integer", required=True, min=1, max=4094, card=True, list=True),
                           NETWORK_REF),
                   tabs=(Tab("subnets", "Subnets", views.vlan_tab, count=views.vlan_count),)),
        EntityType("subnet", "Subnet", "Subnets", detail=NetworkDetail, located_in=(), icon=SUBNET,
                   check=addresses.check_subnet,
                   fields=(Field("cidr", "Range", "cidr", required=True, card=True, list=True),
                           Field("vlan", "VLAN", "ref", types=("vlan",), card=True, list=True),
                           NETWORK_REF,
                           Field("gateway", "Gateway", "ip"),
                           Field("dns_servers", "DNS servers", help="Separated by commas."),
                           Field("dhcp_range", "DHCP range", help="10.0.30.100-10.0.30.199")),
                   tabs=(Tab("addresses", "Addresses", views.subnet_tab, count=views.subnet_count),)),
        EntityType("ip_address", "IP address", "IP addresses", detail=NetworkDetail, located_in=(), icon=IP,
                   statuses=IP_STATUSES, name_from="address", check=addresses.check_ip,
                   fields=(Field("address", "Address", "ip", required=True),
                           Field("assigned", "Assigned to", "ref", trait="addressable", card=True, list=True),
                           Field("mac", "MAC address", help="aa:bb:cc:dd:ee:ff")),
                   tabs=(Tab("network", "Subnet", views.ip_tab),)),
        EntityType("domain", "Domain", "Domains", detail=NetworkDetail, located_in=(), icon=DOMAIN,
                   traits=("domain", "supplied"),
                   statuses=DOMAIN_STATUSES, check=dns.check_domain,
                   fields=(Field("registrar", "Registrar", list=True),
                           Field("dns_provider", "DNS hosted at"),
                           Field("expires", "Renewal due", "date", card=True, list=True, expires=True),
                           Field("auto_renew", "Renews by itself", "boolean"),
                           Field("nameservers", "Name servers", "longtext")),
                   tabs=(Tab("records", "DNS records", views.records_tab, count=views.records_count),)),
    ),
    search=dns.search,
    filters=(ListFilter("internet", "Internet connections", views.internet_connections, alert=False),
             ListFilter("unassigned", "Addresses without a device", views.ips_without_device),
             ListFilter("renewal", "Domain renewal soon", views.renewal_soon)),
    widgets=(Widget("subnets", "Subnets", views.subnets_widget),),
    sheet_tabs=(Tab("addresses", "Addresses", views.addresses_tab, when=views.has_addresses_tab,
                    count=views.addresses_count),
                Tab("ports", "Cabling", views.ports_tab, when=views.has_ports_tab, count=views.ports_count)),
    form_sections=(FormSection("addresses", "IP addresses", addresses.section_form, addresses.section_save,
                               when=addresses.is_addressable),),
    before_retype=ports.before_retype,
    setup=(
        SetupStep("internet", "Internet connection", "How the site reaches the internet: each line from an "
                  "ISP, with the provider chosen from the vendors. Most places have one.", 40,
                  group="Network", plan="internet connections",
                  kinds=(SetupKind("Internet connection", "network", {"f.kind": "wan"}),),
                  fields=(SetupField("name", placeholder="Fiber"), SetupField("location_id"),
                          SetupField("s.supplier.vendor_id", "Provider", types=("vendor",)),
                          SetupField("f.bandwidth", placeholder="1 Gb/s"), SetupField("f.public_ips"),
                          SetupField("f.circuit_id"))),
        SetupStep("vlans", "VLANs", "The VLANs the network is split into, each with its number. Skip this if "
                  "the network is one flat LAN.", 45, group="Network", plan="VLANs",
                  kinds=(SetupKind("VLAN", "vlan"),),
                  fields=(SetupField("name", placeholder="Servers"), SetupField("f.vid"))),
        SetupStep("subnets", "Subnets", "The address ranges in use, such as 192.168.1.0/24, with their gateway. "
                  "Addresses recorded in the later steps are found in these.", 50, group="Network", plan="subnets",
                  kinds=(SetupKind("Subnet", "subnet"),),
                  fields=(SetupField("name", placeholder="Servers"), SetupField("f.cidr", placeholder="10.0.20.0/24"),
                          SetupField("f.gateway", placeholder="10.0.20.1"), SetupField("f.vlan"),
                          SetupField("f.dhcp_range"))),
        SetupStep("cables", "Cables", "What plugs into what, from each endpoint back to the switch. A device "
                  "is cabled as a whole; one with its ports recorded offers its free ports.", 110,
                  group="Endpoints", plan="cables",
                  save=views.setup_cable, existing=views.setup_cables,
                  fields=(SetupField("from", "From", choices=views.setup_ends),
                          SetupField("to", "To", choices=views.setup_ends),
                          SetupField("label", "Label", placeholder="C12"))),
    ),
    seed=demo.seed,
)
