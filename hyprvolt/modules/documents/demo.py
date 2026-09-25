"""The demo homelab's knowledge base."""

OVERVIEW = """The lab lives in [[rack-1]] in the basement. Everything else is on the \
[[storage-shelf]] or in the office.

## Power

The {ups} at the bottom of the rack carries everything for about 20 minutes. \
See the [[power-outage-checklist]] for what to shut down first.

## Backups

The {nas} keeps nightly snapshots. The [[restore-runbook]] says how to get a \
file or a whole VM back.
"""

RESTORE = """1. Find the snapshot: `zfs list -t snapshot tank/vms`.
2. Clone it next to the original: `zfs clone tank/vms@nightly-2026-09-24 tank/restore`.
3. Point the VM's disk at the clone, start it, check it, then promote the clone.

Test a restore once a quarter. The last test is noted in the History tab.
"""

OUTAGE = """When the UPS starts beeping:

- [ ] Shut down the VMs on {pve}, largest first
- [ ] Shut down {pve}
- [ ] Leave {fw}, {sw} and {nas} on until the UPS says 5 minutes

Afterwards, check [[rack-1]] for anything that did not come back.
"""


def seed(demo):
    def ref(key, words):
        # A [[link]] where the record exists (its module may be off).
        return f"[[{key}]]" if demo.get(key) else words
    names = {"ups": ref("ups1", "UPS"), "nas": ref("nas1", "NAS"), "pve": ref("pve1", "the hypervisor"),
             "fw": ref("edge-fw", "the firewall"), "sw": ref("sw-core", "the switch")}
    demo.add("document", "Lab overview", key="lab-overview", tags=["lab"], body=OVERVIEW.format(**names))
    restore = demo.add("document", "Restore runbook", key="restore-runbook", tags=["backup"], body=RESTORE)
    outage = demo.add("document", "Power outage checklist", key="power-outage-checklist", tags=["power"],
                      body=OUTAGE.format(**names))
    demo.add("document", "Offsite backup plan", key="offsite-plan", tags=["backup"], status="draft",
             body="Replicate the NAS snapshots to [[offsite-backup]] over the VPN once it exists.")
    demo.link("documented_by", "rack-1", outage)
    demo.link("documented_by", "rack-1", "lab-overview")
    demo.link("documented_by", "offsite", "offsite-plan")
    demo.link("documented_by", "ups1", outage)
    demo.link("documented_by", "nas1", restore)
    if demo.get("nas1"):
        demo.link("depends_on", restore, "nas1", "The snapshots are on it")
    else:
        demo.link("depends_on", restore, "rack-1", "The NAS is in this rack")
