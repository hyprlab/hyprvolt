"""The demo homelab's services, from the media server to the website, one of
them in trouble so the dashboard has something to say."""


def seed(demo):
    def service(key, name, **fields):
        return demo.add("service", name, key=key, **fields)

    service("svc-dns", "DNS and ad blocking", kind="dns", host="pihole", domain="lab-home", ports="53/udp, 53/tcp",
            users="Everything on the network", criticality="critical", url="https://pihole.lab.home/admin",
            notes="If it is down, nothing resolves. The fallback is edge-fw's own resolver at 10.0.20.1.")
    service("svc-ha", "Home Assistant", kind="smarthome", host="homeassistant", domain="lab-home",
            url="https://ha.lab.home:8123", ports="8123/tcp", users="Everyone at home", criticality="high")
    service("svc-vpn", "VPN", kind="vpn", host="edge-fw", domain="example-net", ports="51820/udp",
            users="Family phones and laptops", criticality="high", notes="WireGuard at vpn.example.net.")
    service("svc-backups", "Nightly backups", kind="backup", host="nas1", status="degraded", criticality="high",
            notes="Two nights failed last week: the snapshot space on nas1 ran out. Pruned; watching it.")
    service("svc-jellyfin", "Jellyfin", kind="media", host="jellyfin", domain="lab-home",
            url="https://jellyfin.lab.home", ports="8096/tcp", users="Everyone at home")
    service("svc-grafana", "Grafana", kind="monitoring", host="grafana", domain="lab-home",
            url="https://grafana.lab.home", ports="3000/tcp", users="Admins", criticality="low")
    service("svc-website", "Website", kind="web", host="cloud", domain="example-net", url="https://example.net",
            users="The public", notes="A static site on Cloudflare Pages.")
    demo.link("depends_on", "svc-jellyfin", "nas1", "The media library is an NFS share on nas1")
    demo.link("depends_on", "svc-backups", "svc-dns")
