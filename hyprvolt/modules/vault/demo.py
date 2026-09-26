"""The demo homelab's secrets: made-up values, so the vault has something
to show and hide."""
from hyprvolt.core import records
from hyprvolt.models import db

from . import crypto
from .models import Secret


def seed(demo):
    for key, name, kind, username, value, url in (
            ("srv1", "iDRAC", "password", "root", "correct-horse-battery-staple", "https://10.0.10.5"),
            ("edge-fw", "Web admin", "password", "admin", "Tr0ub4dor&3-not-really", "https://10.0.10.1"),
            ("pve1", "root@pam", "password", "root", "demo-only-7Hq2vX9p", "https://pve1.lab.home:8006"),
            ("ap-office", "Wi-Fi, main network", "password", "Birch Lane", "a-long-passphrase-for-guests", ""),
            ("windows-license", "Product key", "license_key", "", "XXXXX-XXXXX-XXXXX-XXXXX-DEMO1", ""),
            ("nas1", "Backup user API key", "api_key", "backup", "hv-demo-5f0c2a7e91b34d8c", "")):
        entity = demo.get(key)
        if entity is None:
            continue
        s = Secret(entity_id=entity.id, name=name, kind=kind, username=username, url=url,
                   ciphertext=crypto.encrypt(value),
                   created_by_id=demo.user.id if demo.user else None,
                   updated_by_id=demo.user.id if demo.user else None)
        db.session.add(s)
        db.session.flush()
        records.audit(entity, "added a secret", [{"field": "secret", "label": "Secret", "old": "", "new": name}],
                      demo.user)
