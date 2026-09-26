"""The demo homelab's virtual side: a two-node Proxmox cluster on srv1 and
nuc1, a few VMs and LXC containers, and a Docker VM with two stacks."""

COMPOSE = """services:
  jellyfin:
    image: jellyfin/jellyfin:10.9
    ports: ["8096:8096"]
    volumes: [/srv/media:/media:ro, ./config:/config]
    restart: unless-stopped
  audiobookshelf:
    image: ghcr.io/advplyr/audiobookshelf:2.12
    ports: ["13378:80"]
    restart: unless-stopped
"""


def addresses(ip):
    """The Network module's form section, if it is on."""
    return {"addresses": {"list": ip}} if ip else None


def seed(demo):
    demo.add("cluster", "homelab", key="cluster", platform="proxmox", version="8.2",
             management_url="https://pve1.lab.home:8006")
    demo.add("hypervisor", "pve1", tags=["lab"], platform="proxmox", version="8.2.4", host="srv1",
             cluster="cluster", management_url="https://pve1.lab.home:8006", sections=addresses("10.0.20.5"),
             notes="Runs NUT for the UPS: at 5 minutes left it shuts the guests down, then itself.")
    demo.add("hypervisor", "pve2", tags=["lab"], platform="proxmox", version="8.2.4", host="nuc1",
             cluster="cluster", management_url="https://pve2.lab.home:8006", sections=addresses("10.0.20.6"))

    def guest(type_key, name, on, ip=None, **fields):
        return demo.add(type_key, name, host=on, sections=addresses(ip), **fields)

    guest("vm", "docker1", "pve1", tags=["lab"], os="Debian 12", vmid=101, autostart=True, vcpus=6, memory_gb=24,
          disk_gb=200, ip="10.0.20.11")
    guest("vm", "homeassistant", "pve1", os="Home Assistant OS 13", vmid=102, autostart=True, vcpus=2,
          memory_gb=4, disk_gb=32, ip="10.0.20.12")
    guest("vm", "win11", "pve1", status="stopped", os="Windows 11 Pro", vmid=103, vcpus=4, memory_gb=8,
          disk_gb=80, notes="Started when a Windows-only tool is needed.")
    guest("vm", "debian-12-template", "pve1", status="template", os="Debian 12, cloud-init", vmid=9000,
          vcpus=2, memory_gb=2, disk_gb=16)
    guest("lxc", "pihole", "pve2", tags=["network"], os="Debian 12", vmid=200, autostart=True, vcpus=1,
          memory_gb=0.5, disk_gb=8, ip="10.0.20.2")
    guest("lxc", "unifi", "pve2", tags=["network"], os="Debian 12", vmid=201, autostart=True, vcpus=2,
          memory_gb=2, disk_gb=16, ip="10.0.20.3", notes="The controller for sw-core and ap-office.")

    demo.add("docker_host", "Docker on docker1", key="docker", host="docker1", version="27.1",
             management_url="https://docker1.lab.home:9443")
    demo.add("stack", "media", host="docker", path="/opt/stacks/media/compose.yaml", compose=COMPOSE)
    demo.add("stack", "monitoring", host="docker", path="/opt/stacks/monitoring/compose.yaml",
             repo_url="https://git.lab.home/lab/monitoring")
    for name, stack, image, ports in (
            ("jellyfin", "media", "jellyfin/jellyfin:10.9", "8096:8096"),
            ("audiobookshelf", "media", "ghcr.io/advplyr/audiobookshelf:2.12", "13378:80"),
            ("grafana", "monitoring", "grafana/grafana:11.1", "3000:3000"),
            ("prometheus", "monitoring", "prom/prometheus:v2.53", "9090:9090"),
            ("portainer", None, "portainer/portainer-ce:2.21", "9443:9443")):
        demo.add("container", name, host="docker", stack=stack, image=image, ports=ports)

    demo.link("managed_by", "sw-core", "unifi")
    demo.link("managed_by", "ap-office", "unifi")
    demo.link("backs_up", "nas1", "docker1", "Nightly vzdump")
    demo.link("backs_up", "nas1", "homeassistant", "Nightly vzdump")
