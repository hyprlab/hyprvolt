"""The vault's table: secrets attached to records, the value encrypted."""
from hyprvolt.core.models import Entity
from hyprvolt.models import User, db, utcnow

KINDS = (("password", "Password"), ("api_key", "API key"), ("token", "Token"), ("ssh_key", "SSH key"),
         ("license_key", "License key"), ("certificate", "Certificate or key"), ("other", "Other"))


class Secret(db.Model):
    __tablename__ = "vault_secrets"

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="password")
    username = db.Column(db.String(200), nullable=False, default="")
    ciphertext = db.Column(db.Text, nullable=False)     # the value, encrypted; never shown or exported
    url = db.Column(db.String(500), nullable=False, default="")
    note = db.Column(db.String(500), nullable=False, default="")   # not encrypted, and says so
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # Deleting hides it, so Undo works; the worker purges it with the records.
    deleted_at = db.Column(db.DateTime)

    entity = db.relationship(Entity, foreign_keys=[entity_id])
    updated_by = db.relationship(User, foreign_keys=[updated_by_id])
