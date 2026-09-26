"""Virtual's one detail table, shared by every virtual type. Hosts, clusters
and stacks are not columns: they are fields kept as links (runs on, part of),
so the dependency view follows them."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class VirtualDetail(EntityDetail, db.Model):
    __tablename__ = "virtual_details"

    platform = db.Column(db.String(20))        # clusters and hypervisors
    version = db.Column(db.String(80))         # the platform's, or Docker's
    management_url = db.Column(db.String(500))
    vmid = db.Column(db.Integer)               # the hypervisor's own id: Proxmox 101
    os = db.Column(db.String(120))
    vcpus = db.Column(db.Integer)
    memory_gb = db.Column(db.Float)
    disk_gb = db.Column(db.Float)
    autostart = db.Column(db.Boolean)
    image = db.Column(db.String(300))          # containers
    ports = db.Column(db.String(300))          # containers: published ports
    path = db.Column(db.String(300))           # stacks: where the compose file is
    repo_url = db.Column(db.String(500))
    compose = db.Column(db.Text)
