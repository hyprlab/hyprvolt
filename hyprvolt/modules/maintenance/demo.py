"""The demo homelab's maintenance: the cluster's upgrade this weekend, a UPS
battery swap that is done, and a few changes, one of them rolled back."""
from datetime import timedelta

from hyprvolt.core import clock
from hyprvolt.models import utcnow


def seed(demo):
    local_now = clock.to_local(utcnow()).replace(minute=0, second=0, microsecond=0)

    def at(days, hour, minute=0):
        return (local_now + timedelta(days=days)).replace(hour=hour, minute=minute).isoformat(timespec="minutes")

    saturday = (5 - local_now.weekday()) % 7 or 7
    upgrade = demo.add("maintenance", "Proxmox 8 to 9 upgrade", key="mw-pve", starts=at(saturday, 22),
                       ends=at(saturday + 1, 1), impact="outage", owner="Ada", announced=True,
                       plan="1. Back up every VM to PBS and check the job succeeded.\n"
                            "2. Upgrade pve2, move the guests back, then upgrade pve1.\n"
                            "3. Check Home Assistant, DNS and Jellyfin.\n\n"
                            "**Roll back:** restore from last night's backups.")
    demo.add("maintenance", "UPS battery swap", key="mw-ups", status="done", starts=at(-24, 9),
             ends=at(-24, 10, 30), impact="none", owner="Ada",
             notes="Hot-swapped; the rack stayed on mains the whole time.")
    for window, target in (("mw-pve", "pve1"), ("mw-pve", "pve2"), ("mw-ups", "ups1")):
        demo.link("affects", window, target)

    def change(key, name, when, targets, **fields):
        entity = demo.add("change", name, key=key, at=when, **fields)
        for target in targets:
            demo.link("affects", entity, target)

    change("ch-ups", "Replaced the UPS batteries", at(-24, 10), ["ups1"], kind="hardware", done_by="Ada",
           window="mw-ups", details="Two new 12 V 9 Ah cells. Runtime at load went from 6 to 21 minutes.")
    change("ch-pihole", "Upgraded Pi-hole to v6", at(-9, 20, 30), ["pihole", "svc-dns"], kind="upgrade",
           done_by="Ada", details="The admin page moved to /admin/. Blocklists kept.")
    change("ch-ipv6", "Turned on IPv6 on the IoT VLAN", at(-5, 21), ["edge-fw"], kind="config", done_by="Ada",
           status="rolled_back", details="Two smart plugs stopped reporting. Turned off again; to retry with "
                                         "the plugs' firmware updated.")
    change("ch-jellyfin", "Moved Jellyfin's cache to the SSD", at(-2, 19, 15), ["jellyfin"], kind="config",
           done_by="Ada")
