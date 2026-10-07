"""Network: networks, VLANs, subnets and IP addresses, and the wireless
networks access points and other gear broadcast; the ports on devices
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
from hyprvolt.manifest import (EntityType, Field, FormSection, ListFilter, Module, RelationKind, SetupField, SetupKind,
                               SetupStep,
                               Step, Tab, Widget)
from hyprvolt.models import db

from . import addresses, cabling, demo, dns, impact, ports, views
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


SPEED_IN_TEXT = r"(\d+(?:[.,]\d+)?)\s*(g|m)?(?:b(?:it)?(?:ps|/s|s)?)?\s*(down|up|download|upload)?"


def _speeds_of(text):
    """(download, upload, whole) in megabits from text such as "1 Gb/s down,
    40 Mb/s up" or "940/40 Mbps"; a speed that can't be read for sure is
    None. ``whole`` is False when the text says more than the speeds."""
    import re
    found = [(float(n.replace(",", ".")), (u or "").lower(), (w or "").lower())
             for n, u, w in re.findall(SPEED_IN_TEXT, text, re.I)]
    rest = re.sub(SPEED_IN_TEXT, " ", text, flags=re.I)
    symmetric = bool(re.search(r"symmetric", rest, re.I))
    rest = re.sub(r"symmetric(al)?|\band\b|[\s,/;&+-]", "", rest, flags=re.I)
    tagged = [w for _, _, w in found if w]
    # Directions written but not after the speeds ("up 50, down 500"): unsure.
    if not found or len(found) > 2 or (re.search(r"\b(down|up)", rest, re.I) and not tagged):
        return None, None, False
    whole = not re.search(r"[a-z]", rest, re.I)
    unit = next((u for _, u, _ in reversed(found) if u), "m")      # 940/40 Mbps: the unit written last
    mbps = [round(n * (1000 if (u or unit) == "g" else 1)) for n, u, _ in found]
    if len(found) == 1:
        if symmetric:
            return mbps[0], mbps[0], whole
        return ((None, mbps[0]) if found[0][2].startswith("up") else (mbps[0], None)) + (whole,)
    if found[0][2].startswith("up") and not found[1][2].startswith("up"):
        return mbps[1], mbps[0], whole
    return mbps[0], mbps[1], whole


def _bandwidth_speeds(m):
    """Bandwidth was one line of text. It is a download and an upload speed
    now, each chosen in Mb/s or Gb/s: what can be read goes to them, and text
    that can't is kept at the end of the notes."""
    m.add_column("network_details", "download", "INTEGER")
    m.add_column("network_details", "upload", "INTEGER")
    if not m.has_column("network_details", "bandwidth"):
        return

    def move():
        rows = db.session.execute(db.text(
            "SELECT entity_id, bandwidth FROM network_details WHERE bandwidth IS NOT NULL AND bandwidth != ''")).all()
        for entity_id, text in rows:
            down, up, whole = _speeds_of(text)
            if not whole:
                entity = db.session.get(Entity, entity_id)
                if entity is not None:
                    line = f"Bandwidth: {text}"
                    entity.notes = f"{entity.notes.rstrip()}\n\n{line}" if entity.notes.strip() else line
            db.session.execute(db.text("UPDATE network_details SET download = :d, upload = :u, bandwidth = NULL "
                                       "WHERE entity_id = :id"), {"d": down, "u": up, "id": entity_id})
    m.once("bandwidth-speeds", move)


#: The fields only an internet connection has, and those of a static line.
WAN = ("kind", "wan")
STATIC = ("static_ip", True)


def _static_ip(m):
    """A line with public addresses written down was a static one: it is
    marked Static, so its addresses stay in view."""
    m.add_column("network_details", "static_ip", "BOOLEAN")
    m.add_column("network_details", "netmask", "VARCHAR(45)")
    m.once("static-ip", lambda: db.session.execute(db.text(
        "UPDATE network_details SET static_ip = 1 WHERE public_ips IS NOT NULL AND public_ips != ''")))


def _wan_subnet(m):
    """A static line's subnet mask was a line of text. The line has a Subnet
    now, kept in the column subnets use: its static address with the mask
    is its block, 203.0.113.26 and 255.255.255.248 being 203.0.113.24/29."""
    import ipaddress

    def move():
        rows = db.session.execute(db.text(
            "SELECT entity_id, public_ips, netmask FROM network_details WHERE kind = 'wan' "
            "AND netmask IS NOT NULL AND netmask != '' AND (cidr IS NULL OR cidr = '')")).all()
        for entity_id, address, mask in rows:
            try:
                net = ipaddress.ip_interface(f"{(address or '').strip()}/{mask.lstrip('/')}").network
            except ValueError:
                continue                 # no single address to place it: left for the line's form
            db.session.execute(db.text("UPDATE network_details SET cidr = :c WHERE entity_id = :id"),
                               {"c": str(net), "id": entity_id})
    m.once("wan-subnet", move)


def _segments_placed(m):
    """A building's VLANs and subnets were once in a local network placed in
    it. They are placed in the building themselves now, which is what the
    local network said; the local network stays, a network like any other."""
    def move():
        db.session.execute(db.text(
            "UPDATE entities SET location_id = (SELECT n.location_id FROM network_details d "
            "JOIN entities n ON n.id = d.network JOIN network_details nd ON nd.entity_id = n.id "
            "JOIN entities p ON p.id = n.location_id "
            "WHERE d.entity_id = entities.id AND nd.kind = 'lan' AND n.deleted_at IS NULL "
            "AND p.type IN ('site', 'building')) "
            "WHERE type IN ('vlan', 'subnet') AND location_id IS NULL AND EXISTS (SELECT 1 FROM network_details d "
            "JOIN entities n ON n.id = d.network JOIN network_details nd ON nd.entity_id = n.id "
            "JOIN entities p ON p.id = n.location_id "
            "WHERE d.entity_id = entities.id AND nd.kind = 'lan' AND n.deleted_at IS NULL "
            "AND p.type IN ('site', 'building'))"))
    m.once("segments-placed", move)


def _wifi(m):
    """Wireless networks: their security, bands, and the subnet they hand
    out addresses in."""
    m.add_column("network_details", "security", "VARCHAR(12)")
    m.add_column("network_details", "bands", "VARCHAR(10)")
    m.add_column("network_details", "hidden_ssid", "BOOLEAN")
    m.add_column("network_details", "subnet", "INTEGER REFERENCES entities(id) ON DELETE SET NULL")
    m.add_index("ix_network_details_subnet", "network_details", ["subnet"])


WIFI_SECURITY = (("wpa3", "WPA3 Personal"), ("wpa2_wpa3", "WPA2/WPA3 Personal"), ("wpa2", "WPA2 Personal"),
                 ("enterprise", "Enterprise (802.1X)"), ("open", "Open"))
WIFI_BANDS = (("2.4", "2.4 GHz"), ("5", "5 GHz"), ("6", "6 GHz"), ("2.4_5", "2.4 and 5 GHz"),
              ("5_6", "5 and 6 GHz"), ("2.4_5_6", "2.4, 5 and 6 GHz"))

#: Where a VLAN or subnet can be: the site, or a building that is a network
#: of its own (its own internet line, router and addresses).
SEGMENT_PLACES = ("site", "building")

#: A VLAN's or subnet's network: a local one (or a VPN), never an internet
#: connection, whose own addresses are recorded on it.
NETWORK_REF = Field("network", "Network", "ref", types=("network",), list=True,
                    only=("kind", ("lan", "vpn", "other", None),
                          "Choose a local network: an internet connection's subnet is recorded on the connection."))

ICON = ('<circle cx="12" cy="5.5" r="2"/><circle cx="5.5" cy="18.5" r="2"/><circle cx="18.5" cy="18.5" r="2"/>'
        '<path d="M12 7.5v4.5M12 12l-5.2 4.8M12 12l5.2 4.8"/>')
NETWORK = ICON
VLAN = '<path d="M4 7h16M4 12h16M4 17h16"/><path d="M8 4.5v5M16 9.5v5M11 14.5v5"/>'
SUBNET = '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/><path d="M3.5 12h17M12 3.5v17"/>'
IP = '<path d="M5 6.5h14M5 17.5h14"/><path d="M8.5 9.5v5M11.5 9.5v5h1.8a1.8 1.8 0 0 0 0-3.6h-1.8"/>'
WIFI = ('<path d="M2.5 9.2a13.5 13.5 0 0 1 19 0M5.6 12.6a9 9 0 0 1 12.8 0M8.7 16a4.6 4.6 0 0 1 6.6 0"/>'
        '<path d="M12 19.3h.1"/>')
DOMAIN = ('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.3 3.5 5.2 3.5 8.5s-1.1 6.2-3.5 8.5'
          'c-2.4-2.3-3.5-5.2-3.5-8.5s1.1-6.2 3.5-8.5Z"/>')

#: What goes in each of the module's steps of the site setup guide, and
#: why: the paragraphs behind the step's info button.
SETUP_HELP = {
    "internet": (
        "An internet connection is one line from an ISP: fiber, cable, a mobile backup. It holds the download "
        "and upload speeds, the circuit ID the ISP asks for when you report a fault, and, for a static line, "
        "its address, subnet, gateway and DNS servers. They are not a subnet of their own.",
        "The ISP itself is a vendor, chosen here as Provider, so its support number is a click away. The "
        "modem or ONT is network gear, a later step.",
        "A site with more than one ISP, or a mobile backup, records each line here. In the Network gear "
        "step, tick every line that plugs into the router or firewall: it can have several.",
        "A building with its own line chooses that building as Where. If it is its own network as well, "
        "with its own router and addresses, its VLANs and subnets choose it as Where too, in the next steps.",
    ),
    "vlans": (
        "A VLAN splits one physical network into separate ones, each with a number from 1 to 4094, such as "
        "Servers or IoT. Record them if your switches and router use them; skip this for one flat network.",
        "The address range each VLAN uses is a subnet, the next step, which names its VLAN.",
        "Where is the site, or a building that is a network of its own, with its own internet line, router "
        "and addresses. Two such buildings can both have a VLAN 10.",
    ),
    "subnets": (
        "A subnet is an address range in use, such as 192.168.1.0/24, with its gateway and DHCP range. Each "
        "IP address recorded later is placed in the subnet that holds it, and the subnet shows which "
        "addresses are used and which are free.",
        "Only your own networks' ranges go here. An internet connection's static address, subnet and "
        "gateway from the ISP are recorded on the connection, in the Internet connection step.",
        "Where is the site, or a building that is a network of its own. Two such buildings can both use "
        "192.168.1.0/24: an address goes to the subnet of the building its device is in, and a subnet on "
        "a building's VLAN is in that building.",
    ),
    "wifi": (
        "A wireless network is one Wi-Fi network name (SSID) your devices join, such as home, iot or guest, "
        "with its security and bands. Record each one once, even when several access points broadcast it.",
        "The access points, extenders, bridges and Wi-Fi routers that broadcast it are ticked on each of "
        "them in the network gear step, next. Choose the VLAN or subnet it puts devices on.",
        "Its password goes on the record's Secrets tab, where it is encrypted, not here.",
    ),
    "cables": (
        "A cable connects two devices. A device is cabled as a whole unless its ports are recorded one by one "
        "(Record each port, on its Cabling tab), as a switch or patch panel usually is; then its free ports "
        "are offered here.",
        "Cables draw the network diagram, and a trace follows a port through patch panels to the far end. To "
        "move a cable, choose another From or To in its row: it keeps its label.",
        "A cable left without a label is given one from its network: the VLAN's number, or the subnet's "
        "third number with no VLAN, and a running number, so 20-03 is the third cable on VLAN 20. A cable "
        "between two pieces of network gear is an uplink, UP-01, and from the modem, WAN-01.",
        "Suggest cables works the cabling out from the steps before: the modem to the router or firewall, that "
        "to the core switch, other switches to the core, and each device to the switch nearest it by rack, "
        "room and building. Each suggestion is checked before it is added.",
    ),
}


module = Module(
    id="network",
    name="Network",
    icon=ICON,
    description="Networks, VLANs, subnets and IP addresses, ports and cables, domains and DNS records.",
    group="Infrastructure",
    order=40,
    requires=("hardware",),
    models=(NetworkDetail, Port, Cable, DnsRecord, PortsRecorded),
    migrations=(Step("provider-to-notes", _provider_to_notes), Step("ports-recorded", _ports_recorded),
                Step("bandwidth-speeds", _bandwidth_speeds), Step("static-ip", _static_ip), Step("wifi", _wifi),
                Step("wan-subnet", _wan_subnet), Step("segments-placed", _segments_placed)),
    blueprint=views.bp,
    types=(
        EntityType("network", "Network", "Networks", detail=NetworkDetail, located_in=None, icon=NETWORK,
                   traits=("supplied",), check=addresses.check_network,
                   fields=(Field("kind", "Kind", "select", options=NETWORK_KINDS, card=True, list=True),
                           Field("download", "Download", "speed", shown_when=WAN,
                                 help="The speed the ISP sells, toward you: 1 Gb/s, or 940 Mb/s."),
                           Field("upload", "Upload", "speed", shown_when=WAN, help="The speed away from you: 40 Mb/s."),
                           Field("static_ip", "IP address", "boolean", switch=("Dynamic", "Static"), shown_when=WAN,
                                 help="Static: the ISP gave the line a fixed address, with its subnet mask, gateway "
                                      "and DNS servers, to set on your router. Dynamic: the router is given an "
                                      "address by the ISP, and it can change; there is nothing more to record."),
                           Field("public_ips", "Static IP", shown_when=STATIC,
                                 help="The address the ISP gave the line: 203.0.113.26, or a range for a block."),
                           Field("cidr", "Subnet", "cidr", shown_when=STATIC, prefills=("gateway",),
                                 help="The line's block of addresses from the ISP, with the subnet mask chosen "
                                      "beside it: 203.0.113.24 and /29 for a mask of 255.255.255.248. It is "
                                      "recorded here, not as a subnet."),
                           Field("gateway", "Gateway", "ip", shown_when=STATIC,
                                 help="The ISP's side of the line, which your router sends everything to."),
                           Field("dns_servers", "DNS servers", shown_when=STATIC,
                                 help="The ISP's, if it gave any. Separated by commas."),
                           Field("comes_in_at", "Comes in at", "ref", types=views.GATEWAY_TYPES,
                                 relation="comes_in_at", shown_when=WAN,
                                 help="The modem, router or firewall the line plugs into. If it goes down, so "
                                      "does the line."),
                           Field("circuit_id", "Circuit ID", shown_when=WAN,
                                 help="For an internet connection: what the ISP calls this line when you report "
                                      "a fault. The ISP itself goes in Supplier, as a vendor.")),
                   tabs=(Tab("contents", "VLANs and subnets", views.network_tab, when=views.has_contents,
                             count=views.network_count),)),
        EntityType("vlan", "VLAN", "VLANs", detail=NetworkDetail, located_in=SEGMENT_PLACES, icon=VLAN,
                   named_with="location_id",
                   check=addresses.check_vlan,
                   fields=(Field("vid", "VLAN ID", "integer", required=True, min=1, max=4094, card=True, list=True),
                           NETWORK_REF),
                   tabs=(Tab("subnets", "Subnets", views.vlan_tab, count=views.vlan_count),)),
        EntityType("subnet", "Subnet", "Subnets", detail=NetworkDetail, located_in=SEGMENT_PLACES, icon=SUBNET,
                   named_with="location_id",
                   check=addresses.check_subnet,
                   fields=(Field("cidr", "Range", "cidr", required=True, card=True, list=True,
                                 prefills=("gateway", "dhcp_range")),
                           Field("vlan", "VLAN", "ref", types=("vlan",), card=True, list=True),
                           NETWORK_REF,
                           Field("gateway", "Gateway", "ip"),
                           Field("dns_servers", "DNS servers", help="Separated by commas."),
                           Field("dhcp_range", "DHCP range", "iprange",
                                 help="The first and the last address the DHCP server hands out.")),
                   tabs=(Tab("addresses", "Addresses", views.subnet_tab, count=views.subnet_count),)),
        EntityType("ip_address", "IP address", "IP addresses", detail=NetworkDetail, located_in=(), icon=IP,
                   statuses=IP_STATUSES, name_from="address", check=addresses.check_ip,
                   fields=(Field("address", "Address", "ip", required=True),
                           Field("assigned", "Assigned to", "ref", trait="addressable", card=True, list=True),
                           Field("mac", "MAC address", help="aa:bb:cc:dd:ee:ff")),
                   tabs=(Tab("network", "Subnet", views.ip_tab),)),
        EntityType("wifi", "Wireless network", "Wireless networks", detail=NetworkDetail, located_in=(), icon=WIFI,
                   fields=(Field("security", "Security", "select", options=WIFI_SECURITY, card=True, list=True),
                           Field("bands", "Bands", "select", options=WIFI_BANDS, card=True, list=True),
                           Field("hidden_ssid", "Hidden", "boolean",
                                 help="Not broadcast by name: a device joins by typing the name in."),
                           Field("vlan", "VLAN", "ref", types=("vlan",), list=True),
                           Field("subnet", "Subnet", "ref", types=("subnet",),
                                 help="Where the devices that join it get their addresses."))),
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
                               when=addresses.is_addressable, values=addresses.section_values),
                   FormSection("internet", "Internet connections", views.internet_form, views.internet_save,
                               when=views.is_gateway_gear, values=views.internet_values,
                               choices=views.internet_choices),
                   FormSection("wifi", "Wireless networks", views.wifi_form, views.wifi_save,
                               when=views.is_wireless_gear, values=views.wifi_values, choices=views.wifi_choices),
                   FormSection("broadcast", "Broadcast by", views.broadcast_form, views.broadcast_save,
                               when=views.is_wifi, values=views.broadcast_values, choices=views.broadcast_choices),
                   FormSection("networks", "Networks", views.networks_form, views.networks_save,
                               when=views.is_carrier_gear, values=views.networks_values,
                               choices=views.networks_choices),
                   FormSection("carriers", "Carried by", views.carriers_form, views.carriers_save,
                               when=views.is_segment, values=views.carriers_values, choices=views.carriers_choices)),
    impact_edges=impact.impact_edges,
    derived_links=impact.derived_links,
    relation_kinds=(RelationKind("comes_in_at", "comes in at", "brings in", impact="source"),
                    RelationKind("broadcast_by", "is broadcast by", "broadcasts", impact="source"),
                    RelationKind("carried_by", "is carried by", "carries", impact="source")),
    before_retype=ports.before_retype,
    setup=(
        SetupStep("internet", "Internet connection", "How the site reaches the internet: each line from an "
                  "ISP, with the provider chosen from the vendors. Most places have one.", 40,
                  group="Network",
                  help=SETUP_HELP["internet"], plan="internet connections",
                  kinds=(SetupKind("Internet connection", "network", {"f.kind": "wan"}),),
                  fields=(SetupField("name", placeholder="Fiber"), SetupField("location_id"),
                          SetupField("s.supplier.vendor_id", "Provider", types=("vendor",)), SetupField("f.circuit_id"),
                          SetupField("f.download", newline=True), SetupField("f.upload"),
                          SetupField("f.static_ip", newline=True),
                          SetupField("f.public_ips", newline=True, placeholder="203.0.113.26"),
                          SetupField("f.cidr", placeholder="203.0.113.24"), SetupField("f.gateway"),
                          SetupField("f.dns_servers"))),
        SetupStep("vlans", "VLANs", "The VLANs the network is split into, each with its number. Skip this if "
                  "the network is one flat LAN.", 45, group="Network",
                  help=SETUP_HELP["vlans"], plan="VLANs",
                  kinds=(SetupKind("VLAN", "vlan"),),
                  fields=(SetupField("name", placeholder="Servers"), SetupField("f.vid"),
                          SetupField("location_id"))),
        SetupStep("subnets", "Subnets", "The address ranges in use, such as 192.168.1.0/24, with their gateway. "
                  "Addresses recorded in the later steps are found in these.", 50, group="Network",
                  help=SETUP_HELP["subnets"], plan="subnets",
                  kinds=(SetupKind("Subnet", "subnet"),),
                  fields=(SetupField("name", placeholder="Servers"), SetupField("f.cidr", placeholder="10.0.20.0/24"),
                          SetupField("f.gateway", placeholder="10.0.20.1"),
                          SetupField("f.vlan", newline=True), SetupField("location_id"),
                          SetupField("f.dhcp_range"))),
        SetupStep("wifi", "Wireless networks", "The Wi-Fi networks devices join, one row each, with the "
                  "VLAN or subnet each puts them on. Which gear broadcasts them comes next.", 55, group="Network",
                  help=SETUP_HELP["wifi"], plan="wireless networks",
                  kinds=(SetupKind("Wireless network", "wifi"),),
                  fields=(SetupField("name", "Network name (SSID)", placeholder="home"), SetupField("f.security"),
                          SetupField("f.bands"), SetupField("f.vlan", newline=True), SetupField("f.subnet"))),
        SetupStep("cables", "Cables", "What plugs into what, from each endpoint back to the switch. A device "
                  "is cabled as a whole; one with its ports recorded offers its free ports.", 110,
                  group="Endpoints",
                  help=SETUP_HELP["cables"], plan="cables",
                  save=views.setup_cable, rows=views.setup_rows, update=views.setup_update,
                  delete=views.setup_delete, extra=cabling.setup_extra, after=cabling.setup_after,
                  fields=(SetupField("from", "From", choices=views.setup_ends),
                          SetupField("to", "To", choices=views.setup_ends),
                          SetupField("label", "Label", placeholder="Automatic"))),
    ),
    seed=demo.seed,
)
