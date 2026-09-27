"""The demo homelab's backup jobs: nightly VM backups that work, an offsite
copy that has started failing (the Nightly backups service's trouble), and
Home Assistant's own backups, which quietly stopped."""
from datetime import date, timedelta

from hyprvolt.models import db, utcnow

from . import views
from .models import BackupRun


def seed(demo):
    today, now = date.today(), utcnow().replace(minute=0, second=0, microsecond=0)

    def job(key, name, runs=(), **fields):
        entity = demo.add("backup_job", name, key=key, **fields)
        if entity is None:
            return None
        for days_ago, hour, result, note in runs:
            at = (now - timedelta(days=days_ago)).replace(hour=hour, minute=14)
            db.session.add(BackupRun(job_id=entity.id, at=min(at, now), result=result, note=note,
                                     by_name="backup script"))
        db.session.flush()
        views.sync_status(entity, demo.user)
        return entity

    nightly = [(n, 2, "success", f"{11 + n % 4}.{n % 10} GB") for n in range(1, 15)]
    job("bk-pbs", "VMs to Proxmox Backup Server", tool="pbs", backs_up="docker1", saved_to="nas1",
        schedule="Nightly at 02:00", interval_hours=24, retention="7 daily, 4 weekly, 6 monthly", encrypted=True,
        restore_tested=(today - timedelta(days=160)).isoformat(),
        restore_due=(today + timedelta(days=20)).isoformat(), runs=nightly,
        notes="Every VM and container on the cluster. The datastore is an NFS share on nas1.")
    offsite = [(n, 4, "success", "") for n in range(3, 10)] + [(2, 4, "failed", "Upload stopped: quota exceeded"),
                                                                  (1, 4, "failed", "Upload stopped: quota exceeded")]
    job("bk-offsite", "nas1 to Backblaze B2", tool="hyper_backup", backs_up="nas1", offsite="Backblaze B2",
        schedule="Nightly at 04:00", interval_hours=24, retention="30 versions", encrypted=True, runs=offsite,
        notes="The copy that survives the house. The bucket's cap needs raising.")
    job("bk-ha", "Home Assistant backups", tool="snapshots", backs_up="homeassistant", saved_to="nas1",
        schedule="Weekly, Sunday 03:00", interval_hours=168, retention="4 weekly",
        runs=[(n, 3, "success", "") for n in (12, 19, 26)],
        notes="Home Assistant's own backups, copied to nas1 by its Samba add-on.")
    for vm in ("homeassistant", "pihole", "unifi", "win11"):
        demo.link("backs_up", "bk-pbs", vm)
