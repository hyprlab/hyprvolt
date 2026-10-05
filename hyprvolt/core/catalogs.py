"""Lists of known names a text field offers as it is typed in (Field
``suggest``), each under group headings: operating systems. Picking one
fills the field in; anything else typed is kept as it is, a custom name.

A catalog is plain data, served once to the page (``/api/catalogs/<key>``)
and searched there. Keep the names as their makers write them, newest
first within a family, and families a homelab meets most near the top.
"""

#: Operating systems, for a VM's, a container's and a machine's OS.
OPERATING_SYSTEMS = (
    ("Linux", (
        "Ubuntu Server 26.04 LTS", "Ubuntu Server 24.04 LTS", "Ubuntu Server 22.04 LTS", "Ubuntu Server 20.04 LTS",
        "Ubuntu Desktop 26.04 LTS", "Ubuntu Desktop 24.04 LTS", "Ubuntu Desktop 22.04 LTS",
        "Debian 13 (Trixie)", "Debian 12 (Bookworm)", "Debian 11 (Bullseye)",
        "Red Hat Enterprise Linux 10", "Red Hat Enterprise Linux 9", "Red Hat Enterprise Linux 8",
        "Rocky Linux 10", "Rocky Linux 9", "Rocky Linux 8",
        "AlmaLinux 10", "AlmaLinux 9", "AlmaLinux 8",
        "CentOS Stream 10", "CentOS Stream 9", "Oracle Linux 9", "Oracle Linux 8",
        "Fedora Server", "Fedora Workstation", "openSUSE Leap 15.6", "openSUSE Tumbleweed",
        "SUSE Linux Enterprise Server 15", "Arch Linux", "Alpine Linux", "NixOS", "Gentoo",
        "Linux Mint 22", "Pop!_OS", "Kali Linux", "Amazon Linux 2023", "Raspberry Pi OS", "DietPi",
        "Talos Linux", "Flatcar Container Linux", "Fedora CoreOS", "Photon OS 5",
    )),
    ("Windows", (
        "Windows Server 2025", "Windows Server 2022", "Windows Server 2019", "Windows Server 2016",
        "Windows Server 2012 R2", "Windows 11", "Windows 11 IoT Enterprise LTSC", "Windows 10",
        "Windows 10 IoT Enterprise LTSC",
    )),
    ("Storage and NAS", (
        "TrueNAS SCALE", "TrueNAS CORE", "Unraid", "OpenMediaVault", "Synology DSM 7", "QNAP QTS",
        "QNAP QuTS hero",
    )),
    ("Firewalls and routers", (
        "pfSense CE", "pfSense Plus", "OPNsense", "OpenWrt", "VyOS", "MikroTik RouterOS 7", "IPFire",
        "Sophos Firewall",
    )),
    ("Hypervisors and appliances", (
        "Proxmox VE 9", "Proxmox VE 8", "Proxmox Backup Server 4", "Proxmox Backup Server 3", "VMware ESXi 8",
        "VMware ESXi 7", "XCP-ng 8", "Home Assistant OS",
    )),
    ("BSD", ("FreeBSD 15", "FreeBSD 14", "FreeBSD 13", "OpenBSD", "NetBSD", "OmniOS")),
    ("macOS", ("macOS 26 Tahoe", "macOS 15 Sequoia", "macOS 14 Sonoma", "macOS 13 Ventura")),
)

CATALOGS = {"os": OPERATING_SYSTEMS}


def catalog(key: str) -> list[dict] | None:
    """A catalog as the page takes it: [{"label", "items"}], or None."""
    groups = CATALOGS.get(key)
    return [{"label": label, "items": list(items)} for label, items in groups] if groups else None
