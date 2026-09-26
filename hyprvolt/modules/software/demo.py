"""The demo homelab's software: what runs on the hosts, two of them a
version behind, and two licenses, one of them over its seats."""
from datetime import date, timedelta

from .views import add_install


def seed(demo):
    today = date.today()

    def title(key, name, **fields):
        return demo.add("software", name, key=key, **fields)

    title("proxmox", "Proxmox VE", category="os", current_version="8.2.4", license_model="open_source",
          website="https://www.proxmox.com")
    title("debian", "Debian", category="os", current_version="12.7", license_model="open_source",
          website="https://www.debian.org")
    title("docker-engine", "Docker Engine", category="server", current_version="27.1", license_model="open_source")
    title("dsm", "Synology DSM", category="os", current_version="7.2.2", license_model="free")
    title("pfsense", "pfSense Plus", category="os", current_version="24.03", license_model="free")
    title("fedora", "Fedora Linux", category="os", current_version="40", license_model="open_source")
    title("windows", "Windows 11 Pro", category="os", license_model="perpetual")
    title("m365", "Microsoft 365 Apps", category="application", license_model="subscription",
          website="https://www.microsoft.com/microsoft-365")
    windows_key = demo.add("license", "Windows 11 Pro retail key", key="windows-license", software="windows",
                           kind="perpetual", seats=1, purchased=date(2024, 2, 10), cost=199,
                           notes="spare-pc came with its own OEM key, which isn't written down yet.")
    m365 = demo.add("license", "Microsoft 365 Family", key="m365-license", software="m365", kind="subscription",
                    seats=6, extra_seats=3, renews=today + timedelta(days=40), cost=99.99,
                    notes="The other seats are the phones and tablets.")

    def on(software, host, version="", license_=None):
        if demo.get(software) is None or demo.get(host) is None:
            return
        add_install({"software_id": demo.get(software).id, "host_id": demo.get(host).id, "version": version,
                     "license_id": license_.id if license_ is not None else None}, demo.user)

    on("proxmox", "srv1", "8.2.4")
    on("proxmox", "nuc1", "8.2.2")
    on("dsm", "nas1", "7.2.1")
    on("pfsense", "edge-fw", "24.03")
    on("fedora", "desk-pc", "40")
    for host in ("docker1", "pihole", "unifi"):
        on("debian", host, "12.7")
    on("docker-engine", "docker1", "27.1")
    on("windows", "win11", "23H2", windows_key)
    on("windows", "spare-pc", "22H2", windows_key)
    on("m365", "win11", "2408", m365)
