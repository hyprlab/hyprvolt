"""Backup jobs: what is backed up, by what, to where, and whether it still
works.

"Backs up" and "Saved to" point at anything with the ``host`` trait and are
kept as links: the core's "backs up", and "depends on" for where it writes,
so the dependency view of a NAS lists the jobs that stop with it. Each
backed-up record gets a Backups tab. The status follows the runs the backup
script reports (views.py); the worker marks jobs that fall behind. The next
restore test is an ``expires`` date, reminded of like a warranty.
"""
from hyprvolt.manifest import EntityType, Field, Job, ListFilter, Module, Tab, Widget

from . import demo, views
from .models import BackupJobDetail, BackupRun

TOOLS = (("pbs", "Proxmox Backup Server"), ("vzdump", "Proxmox vzdump"), ("veeam", "Veeam"),
         ("restic", "restic"), ("borg", "Borg"), ("kopia", "Kopia"), ("duplicati", "Duplicati"),
         ("rsync", "rsync"), ("hyper_backup", "Synology Hyper Backup"), ("time_machine", "Time Machine"),
         ("windows", "Windows Backup"), ("snapshots", "Snapshots"), ("other", "Other"))

ICON = ('<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v3.2h3.2"/><path d="M12 8v4.2l2.8 1.8"/>')

module = Module(
    id="backup_jobs",
    name="Backup jobs",
    icon=ICON,
    description="Backup jobs: what each backs up, where to, how often, and whether its last run worked.",
    group="Operations",
    order=54,
    models=(BackupJobDetail, BackupRun),
    blueprint=views.bp,
    types=(
        EntityType("backup_job", "Backup job", "Backup jobs", detail=BackupJobDetail, located_in=(), icon=ICON,
                   statuses=views.STATUSES, inactive=views.HELD,
                   fields=(Field("tool", "Tool", "select", options=TOOLS, card=True, list=True),
                           Field("backs_up", "Backs up", "ref", trait="host", relation="backs_up", card=True,
                                 list=True, help="A server, VM, container or NAS. More than one: link the rest in "
                                                 "Relationships."),
                           Field("saved_to", "Saved to", "ref", trait="host", relation="depends_on",
                                 help="The NAS or backup server it writes to."),
                           Field("offsite", "Offsite copy",
                                 help="Where a second copy goes, if one does: Backblaze B2, a disk kept elsewhere."),
                           Field("schedule", "Schedule", help="Nightly at 02:00, every six hours."),
                           Field("interval_hours", "Should succeed every", "integer", min=1, max=8784, unit="hours",
                                 default=views.DEFAULT_HOURS,
                                 help="Overdue once half as long again passes without a success."),
                           Field("retention", "Keeps", help="7 daily, 4 weekly, 6 monthly."),
                           Field("encrypted", "Encrypted", "boolean"),
                           Field("restore_tested", "Last restore test", "date", group="Restores"),
                           Field("restore_due", "Next restore test", "date", group="Restores", expires=True,
                                 help="Reminded of like an expiry date: a backup is only as good as a restore.")),
                   tabs=(Tab("runs", "Runs", views.runs_tab),)),
    ),
    filters=(ListFilter("trouble", "Failing or overdue", views.trouble),
             ListFilter("never", "Not run yet", views.never_run)),
    widgets=(Widget("backups", "Backups", views.widget),),
    sheet_tabs=(Tab("backups", "Backups", views.backups_tab, when=views.backed_up, count=views.backups_count),),
    jobs=(Job("refresh", views.refresh, minutes=60),),
    seed=demo.seed,
)
