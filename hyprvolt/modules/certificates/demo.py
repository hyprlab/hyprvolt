"""The demo homelab's certificates: a wildcard from its own CA, a public one
that renews by itself, and two self-signed ones, one of them lapsed, so the
dashboard has something to remind of."""
from datetime import date, timedelta


def seed(demo):
    today = date.today()

    def day(offset):
        return (today + timedelta(days=offset)).isoformat()

    def cert(key, name, **fields):
        return demo.add("certificate", name, key=key, **fields)

    cert("cert-lab", "*.lab.home", names="lab.home\n*.lab.home", secures=demo.get("svc-ha"),
         issuer="Lab Root CA", issued=day(-120), expires=day(245), key_type="ECDSA P-256",
         notes="Issued by the step-ca instance on docker1. The root is installed on every laptop and phone.")
    cert("cert-web", "example.net", names="example.net\nwww.example.net", secures=demo.get("svc-website"),
         issuer="Google Trust Services WE1", issued=day(-40), expires=day(50), auto_renew=True,
         key_type="ECDSA P-256", notes="Cloudflare issues and renews it.")
    cert("cert-pve1", "pve1.lab.home", names="pve1.lab.home\npve1\n10.0.20.11", issuer="Self-signed", secures="pve1",
         issued=day(-710), expires=day(20), key_type="RSA 2048",
         notes="Proxmox's own. Replace it with one from the lab CA before it lapses.")
    cert("cert-nas1", "nas1.lab.home", names="nas1.lab.home", issuer="Self-signed", secures="nas1", issued=day(-375),
         expires=day(-10), key_type="RSA 2048", notes="Synology's default. Expired: browsers warn on DSM.")
    demo.link("secures", "cert-lab", "svc-jellyfin")
    demo.link("secures", "cert-lab", "svc-grafana")
