"""The demo homelab's network: four VLANs and their subnets behind edge-fw,
the switch's ports, a patch panel between the office and the rack, and two
domains. The devices' addresses come from Hardware's and Virtual's demos,
through the IP addresses form section."""
from datetime import date, timedelta

from . import dns, ports


def seed(demo):
    home = demo.add("network", "Home LAN", key="home-lan", location="home", kind="lan")
    demo.add("network", "Internet", key="wan", location="home", kind="wan", circuit_id="SC-88213-HFC",
             public_ips="203.0.113.24", bandwidth="1 Gb/s down, 40 Mb/s up",
             notes="The modem is in bridge mode; edge-fw holds the public address.")
    vlans = {}
    for vid, name, cidr, extra in (
            (10, "Management", "10.0.10.0/24", {}),
            (20, "Servers", "10.0.20.0/24", {"dns_servers": "10.0.20.2"}),
            (30, "Clients", "10.0.30.0/24", {"dns_servers": "10.0.20.2", "dhcp_range": "10.0.30.100-10.0.30.199"}),
            (40, "IoT", "10.0.40.0/24", {"dns_servers": "10.0.20.2", "dhcp_range": "10.0.40.100-10.0.40.199"})):
        vlan = demo.add("vlan", name, key=f"vlan-{vid}", vid=vid, network=home)
        vlans[vid] = vlan
        demo.add("subnet", f"{name} {cidr}", key=f"net-{vid}", cidr=cidr, vlan=vlan, network=home,
                 gateway=cidr.replace("0/24", "1"), **extra)
    demo.add("ip_address", "10.0.20.250", status="reserved", address="10.0.20.250",
             notes="Held for a floating address when the cluster gets a third node.")

    def device(key):
        return demo.get(key)

    def add(key, **data):
        if device(key) is not None:
            ports.add_ports(device(key), data, demo.user)

    add("sw-core", first=1, last=24, kind="rj45", speed_mbps=1000, poe=True)
    add("sw-core", first=25, last=26, kind="sfp_plus", speed_mbps=10000)
    add("pp1", first=1, last=24, rear=True, kind="rj45", speed_mbps=1000)
    add("srv1", prefix="eth", first=0, last=3, kind="rj45", speed_mbps=1000)
    add("srv1", prefix="sfp", first=0, last=1, kind="sfp_plus", speed_mbps=10000)
    add("srv1", prefix="", first=0, last=0)                       # renamed to iDRAC below
    add("nas1", prefix="LAN ", first=1, last=4, kind="rj45", speed_mbps=1000)
    add("nuc1", prefix="eth", first=0, last=0, kind="rj45", speed_mbps=2500)
    add("edge-fw", prefix="igc", first=0, last=3, kind="rj45", speed_mbps=2500)
    add("edge-fw", prefix="ix", first=0, last=1, kind="sfp_plus", speed_mbps=10000)
    add("modem", prefix="LAN ", first=1, last=1, kind="rj45", speed_mbps=1000)
    add("ups1", prefix="NMC ", first=1, last=1, kind="rj45", speed_mbps=100)
    add("ap-office", prefix="eth", first=0, last=0, kind="rj45", speed_mbps=1000)
    add("desk-pc", prefix="eth", first=0, last=0, kind="rj45", speed_mbps=1000)
    add("printer", prefix="eth", first=0, last=0, kind="rj45", speed_mbps=100)

    def port(key, name):
        if device(key) is None:
            return None
        return next((p for p in ports.ports_of(device(key).id) if p.name == name), None)

    idrac = port("srv1", "0")
    if idrac is not None:
        ports.edit_port(idrac, {"name": "iDRAC"}, demo.user)

    def vlan_id(vid):
        return vlans[vid].id if vlans.get(vid) else None

    for name, vid, tagged in (("Port 2", 10, ""), ("Port 3", 20, ""), ("Port 4", 20, ""), ("Port 5", 30, ""),
                              ("Port 6", 10, ""), ("Port 8", 10, "20, 30, 40"), ("Port 24", None, "10, 20, 30, 40"),
                              ("Port 25", 20, "10")):
        p = port("sw-core", name)
        if p is not None:
            ports.edit_port(p, {"vlan_id": vlan_id(vid) or "", "tagged": tagged,
                                "description": "Trunk to edge-fw" if name == "Port 24" else ""}, demo.user)

    for (a, an), (b, bn), extra in (
            (("srv1", "sfp0"), ("sw-core", "Port 25"), {"label": "DAC1", "length_m": 1}),
            (("srv1", "iDRAC"), ("sw-core", "Port 2"), {"label": "C02", "color": "gray"}),
            (("nas1", "LAN 1"), ("sw-core", "Port 3"), {"label": "C03", "color": "blue"}),
            (("nuc1", "eth0"), ("sw-core", "Port 4"), {"label": "C04", "color": "blue"}),
            (("ups1", "NMC 1"), ("sw-core", "Port 6"), {"label": "C06", "color": "gray"}),
            (("edge-fw", "igc1"), ("sw-core", "Port 24"), {"label": "C24", "color": "yellow"}),
            (("edge-fw", "igc0"), ("modem", "LAN 1"), {"label": "WAN", "color": "red"}),
            (("desk-pc", "eth0"), ("pp1", "Rear 1"), {"label": "Office jack 1", "length_m": 18}),
            (("pp1", "Front 1"), ("sw-core", "Port 5"), {"label": "P01", "length_m": 0.3}),
            (("ap-office", "eth0"), ("pp1", "Rear 4"), {"label": "Office ceiling", "length_m": 22}),
            (("pp1", "Front 4"), ("sw-core", "Port 8"), {"label": "P04", "length_m": 0.3})):
        pa, pb = port(a, an), port(b, bn)
        if pa is not None and pb is not None:
            ports.connect(pa, pb, extra, demo.user)

    today = date.today()
    lab = demo.add("domain", "lab.home", key="lab-home", dns_provider="pihole", status="active",
                   notes="The internal zone. pihole answers for it; nothing outside can see it.")
    for name, rtype, value in (("pve1", "A", "10.0.20.5"), ("pve2", "A", "10.0.20.6"), ("nas1", "A", "10.0.20.10"),
                               ("docker1", "A", "10.0.20.11"), ("ha", "A", "10.0.20.12"),
                               ("pihole", "A", "10.0.20.2"), ("unifi", "A", "10.0.20.3"),
                               ("grafana", "CNAME", "docker1.lab.home"), ("jellyfin", "CNAME", "docker1.lab.home")):
        dns.add_record(lab, {"name": name, "type": rtype, "value": value})
    net = demo.add("domain", "example.net", key="example-net", registrar="Cloudflare Registrar",
                   dns_provider="Cloudflare", expires=today + timedelta(days=50), auto_renew=False,
                   nameservers="ada.ns.cloudflare.com\nbob.ns.cloudflare.com",
                   notes="Auto-renew is off since the card on file expired. Renew by hand.")
    for name, rtype, value, extra in (("@", "A", "203.0.113.24", {}), ("www", "CNAME", "example.net", {}),
                                      ("vpn", "A", "203.0.113.24", {}),
                                      ("@", "MX", "mx.mailhost.example", {"priority": 10}),
                                      ("@", "TXT", "v=spf1 mx -all", {})):
        dns.add_record(net, {"name": name, "type": rtype, "value": value, **extra})
    demo.link("depends_on", "vlan-20", "edge-fw", "Routes between the VLANs")
