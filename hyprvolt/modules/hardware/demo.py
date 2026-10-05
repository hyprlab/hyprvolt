"""The demo homelab's equipment: what fills Rack 1, the mini PC and modem on
its shelf, and the office. Warranty dates are relative to today, so the
Warranties card always has something ending soon and something over."""
from datetime import date, timedelta


def seed(demo):
    today = date.today()

    def days(n):
        return today + timedelta(days=n)

    def at(position=None, height=1, face="front", ip=None):
        """Other modules' form sections: the rack position (Locations) and
        the IP addresses (Network), used when they are on."""
        sections = {}
        if position is not None:
            sections["rack"] = {"rack_id": "rack-1", "position_u": position, "height_u": height, "face": face}
        if ip:
            sections["addresses"] = {"list": ip}
        return sections

    demo.add("ups", "ups1", location="rack-1", tags=["power"], sections=at(1, 2, "full", ip="10.0.10.30"),
             manufacturer="APC", model="Smart-UPS 1500 SMT1500RM2U", serial="AS2231123456", asset_tag="HL-0001",
             purchase_date=date(2022, 3, 14), price=689, vendor="Newegg", warranty_until=days(45),
             capacity_va=1500, power_w=1000, runtime_min=22, battery_due=days(160),
             notes="Feeds everything in the rack. The USB cable goes to pve1, which runs the shutdown script.")
    demo.add("peripheral", "pdu1", location="rack-1", tags=["power"], sections=at(5, 1, "rear"),
             manufacturer="Tripp Lite", model="PDU1215", category="PDU", asset_tag="HL-0002")
    demo.add("network_device", "sw-core", location="rack-1", tags=["network"], sections=at(22, ip="10.0.10.2"),
             manufacturer="Ubiquiti", model="USW-Pro-24-PoE", serial="F4E2C6A1B3D7", asset_tag="HL-0003",
             purchase_date=days(-400), price=699, vendor="Ubiquiti Store", warranty_until=days(330),
             kind="switch", ports=24, managed=True, os="UniFi 7.1", power_w=38,
             notes="Core switch. Ports 1–16 are PoE; 25 and 26 are the 10 GbE uplinks to srv1.")
    demo.add("firewall", "edge-fw", location="rack-1", tags=["network"], sections=at(20, ip="10.0.10.1, 10.0.20.1, 10.0.30.1, 10.0.40.1"),
             manufacturer="Netgate", model="6100", serial="NG6100-2104871", asset_tag="HL-0004",
             purchase_date=date(2023, 1, 20), price=649, vendor="Netgate", warranty_until=days(-30),
             ports=8, os="pfSense Plus 24.03", cpu="Intel Atom C3558", ram_gb=8, power_w=20)
    demo.add("server", "srv1", location="rack-1", tags=["lab"], sections=at(16, 2, "full", ip="10.0.10.5"),
             manufacturer="Dell", model="PowerEdge R730xd", serial="7XJ2K42", asset_tag="HL-0005",
             purchase_date=date(2023, 6, 2), price=850, vendor="eBay, refurbished", warranty_until=date(2024, 6, 2),
             kind="rack", cpu="2 × Xeon E5-2680 v4", cpu_cores=28, ram_gb=128,
             storage="2 × 240 GB SSD, boot mirror\n6 × 1.92 TB SSD, ZFS RAIDZ2",
             nics="4 × 1 GbE\n2 × 10 GbE SFP+", power_w=190, os="Proxmox VE 8.2",
             notes="The main Proxmox host. iDRAC is on port 1 of the management VLAN.")
    demo.add("nas", "nas1", location="rack-1", tags=["storage"], sections=at(12, 2, "full", ip="10.0.20.10"),
             manufacturer="Synology", model="RS1221+", serial="21A0PDN123456", asset_tag="HL-0006",
             purchase_date=days(-1020), price=1299, vendor="B&H", warranty_until=days(75),
             drive_bays=8, capacity_tb=21.8, storage="4 × 8 TB WD Red Plus, SHR-2", cpu="AMD Ryzen V1500B",
             ram_gb=8, nics="4 × 1 GbE", power_w=60, os="DSM 7.2")
    demo.add("server", "nuc1", location="rack-shelf", tags=["lab"],
             manufacturer="Intel", model="NUC 11 Pro NUC11TNHi5", asset_tag="HL-0007", kind="mini",
             purchase_date=days(-700), price=420, vendor="Amazon", warranty_until=days(395),
             cpu="Core i5-1135G7", cpu_cores=4, ram_gb=64, storage="1 TB NVMe", nics="1 × 2.5 GbE",
             power_w=28, os="Proxmox VE 8.2")
    demo.add("network_device", "pp1", location="rack-1", tags=["network"], sections=at(24),
             manufacturer="Monoprice", model="Cat6 patch panel, 24 ports", kind="patch_panel", ports=24,
             notes="The rear is punched down to the wall jacks: 1–4 office, 5–8 living room.")
    demo.add("network_device", "Cable modem", key="modem", location="rack-shelf", tags=["network"],
             manufacturer="Arris", model="SURFboard S33", kind="modem", ports=2, os="Rented from the ISP")
    demo.add("access_point", "ap-office", location="office", tags=["network"], sections=at(ip="10.0.10.20"),
             manufacturer="Ubiquiti", model="U6 Lite", asset_tag="HL-0008", wifi="Wi-Fi 6, 2.4 and 5 GHz",
             os="6.6", power_w=12, warranty_until=days(200))
    demo.add("workstation", "desk-pc", location="office", sections=at(ip="10.0.30.50"),
             manufacturer="Custom build", asset_tag="HL-0009", assigned_to="Sam", cpu="Ryzen 7 7700",
             cpu_cores=8, ram_gb=32, storage="2 TB NVMe", os="Fedora 40", purchase_date=days(-300), price=1150)
    demo.add("printer", "Office printer", key="printer", location="office", sections=at(ip="10.0.30.60"),
             manufacturer="Brother", model="HL-L2350DW", power_w=440)
    demo.add("ip_phone", "office-phone", location="office", sections=at(ip="10.0.30.70"),
             manufacturer="Yealink", model="T54W", assigned_to="Sam", extension="104", power_w=7)
    demo.add("ip_camera", "cam-office", location="office", sections=at(ip="10.0.30.80"),
             manufacturer="Reolink", model="RLC-520A", os="v3.1.0", power_w=6)
    demo.add("server", "Spare mini PC", key="spare-pc", location="storage-shelf", status="in_stock",
             manufacturer="Lenovo", model="ThinkCentre M720q", kind="mini", cpu="Core i5-8500T", cpu_cores=6,
             ram_gb=16, notes="Kept as a replacement for nuc1.")
    demo.add("network_device", "Old router", key="old-router", location="storage-shelf", status="retired",
             manufacturer="TP-Link", model="Archer C7", kind="router", ports=5)

    for thing in ("pdu1", "sw-core", "edge-fw", "srv1", "nas1"):
        demo.link("powered_by", thing, "ups1")
    for thing in ("nuc1", "modem"):
        demo.link("powered_by", thing, "pdu1")
    demo.link("powered_by", "ap-office", "sw-core", "PoE, port 8")
    for thing in ("srv1", "nuc1", "nas1", "ap-office", "edge-fw"):
        demo.link("connected_to", thing, "sw-core")
    demo.link("connected_to", "modem", "edge-fw", "WAN")
