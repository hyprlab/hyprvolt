"""The demo homelab's knowledge base."""

OVERVIEW = """The lab lives in [[rack-1]] in the basement. Everything else is on the \
[[storage-shelf]] or in the office.

## Power

The UPS at the bottom of the rack carries everything for about 25 minutes. \
See the [[power-outage-checklist]] for what to shut down first.

## Backups

The NAS keeps nightly snapshots. The [[restore-runbook]] says how to get a \
file or a whole VM back.
"""

RESTORE = """1. Find the snapshot: `zfs list -t snapshot tank/vms`.
2. Clone it next to the original: `zfs clone tank/vms@nightly-2026-09-24 tank/restore`.
3. Point the VM's disk at the clone, start it, check it, then promote the clone.

Test a restore once a quarter. The last test is noted in the History tab.
"""

OUTAGE = """When the UPS starts beeping:

- [ ] Shut down the VMs on the hypervisor, largest first
- [ ] Shut down the hypervisor
- [ ] Leave the firewall, the switch and the NAS on until the UPS says 5 minutes

Afterwards, check [[rack-1]] for anything that did not come back.
"""


def seed(demo):
    demo.add("document", "Lab overview", key="lab-overview", tags=["lab"], body=OVERVIEW)
    restore = demo.add("document", "Restore runbook", key="restore-runbook", tags=["backup"], body=RESTORE)
    outage = demo.add("document", "Power outage checklist", key="power-outage-checklist", tags=["power"],
                      body=OUTAGE)
    demo.add("document", "Offsite backup plan", key="offsite-plan", tags=["backup"], status="draft",
             body="Replicate the NAS snapshots to [[offsite-backup]] over the VPN once it exists.")
    demo.link("documented_by", "rack-1", outage)
    demo.link("documented_by", "rack-1", "lab-overview")
    demo.link("documented_by", "offsite", "offsite-plan")
    demo.link("depends_on", restore, "rack-1", "The NAS is in this rack")
