"""The demo homelab's vendors, a person at the ISP, and two contracts, one
of them the internet service that the whole lab hangs on."""
from datetime import date, timedelta


def seed(demo):
    today = date.today()

    def vendor(key, name, **fields):
        return demo.add("vendor", name, key=key, **fields)

    vendor("isp", "Springfield Cable", website="https://springfieldcable.example", support_phone="+1 555 010 0199",
           support_email="support@springfieldcable.example", account_number="SC-4471-2209")
    vendor("dell", "Dell Technologies", support_phone="+1 555 010 0142", support_url="https://www.dell.com/support",
           notes="Look up srv1 by its service tag, 7XJ2K42.")
    vendor("synology", "Synology", support_url="https://www.synology.com/support", account_number="SYN-88213")
    vendor("ubiquiti", "Ubiquiti", support_url="https://help.ui.com")
    vendor("cloudflare", "Cloudflare", website="https://www.cloudflare.com", account_number="acct 4f1c…9a2e")
    vendor("microsoft", "Microsoft", support_url="https://support.microsoft.com")
    demo.add("person", "Dana Reyes", organization="isp", role="Business account manager",
             email="dana.reyes@springfieldcable.example", phone="+1 555 010 0187 ext 204")
    demo.add("contract", "Internet service", key="isp-contract", vendor="isp", kind="service", number="SC-4471-2209",
             starts=date(2024, 3, 1), ends=today + timedelta(days=160), auto_renew=True, notice_days=30, cost=79,
             billing="monthly", notes="1 Gb/s down, 40 Mb/s up, one static address.")
    demo.add("contract", "Extended Warranty Plus", key="nas-warranty", vendor="synology", kind="warranty",
             status="planned", starts=today + timedelta(days=75), ends=today + timedelta(days=75 + 730), cost=149,
             billing="once", notes="Takes over from nas1's own warranty.")

    for thing, who in (("srv1", "dell"), ("nas1", "synology"), ("sw-core", "ubiquiti"), ("ap-office", "ubiquiti"),
                       ("example-net", "cloudflare"), ("svc-website", "cloudflare"), ("m365", "microsoft"),
                       ("m365-license", "microsoft"), ("windows", "microsoft"), ("wan", "isp")):
        demo.link("supplied_by", thing, who)
    demo.link("covered_by", "wan", "isp-contract")
    demo.link("covered_by", "nas1", "nas-warranty")
