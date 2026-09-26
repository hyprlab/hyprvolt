"""Contacts' tabs, filter and the Supplier section other records get: who
supplies a thing and which contract covers it, kept as links."""
from datetime import date, timedelta

from flask import render_template

from hyprvolt.core import present, records, relations
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db

from .models import ContactDetail

#: How far ahead "ending soon" looks.
SOON_DAYS = 90


def _children(field, parent_id, type_key):
    return (Entity.live().join(ContactDetail, ContactDetail.entity_id == Entity.id)
            .filter(Entity.type == type_key, getattr(ContactDetail, field) == parent_id)
            .order_by(Entity.name).all())


def _linked(kind, target_id=None, source_id=None, types=None):
    """Live records at the other end of ``kind`` links."""
    q = Relationship.query.filter(Relationship.kind == kind)
    if target_id is not None:
        q = q.filter(Relationship.target_id == target_id)
        ids = [r.source_id for r in q]
    else:
        q = q.filter(Relationship.source_id == source_id)
        ids = [r.target_id for r in q]
    if not ids:
        return []
    rows = Entity.live().filter(Entity.id.in_(ids))
    if types:
        rows = rows.filter(Entity.type.in_(types))
    return rows.order_by(Entity.name).all()


# ———— Tabs ————

def vendor_tab(vendor: Entity) -> str:
    return render_template("contacts/vendor.html", vendor=vendor,
                           people=present.views(_children("organization", vendor.id, "person")),
                           contracts=present.views(_children("vendor", vendor.id, "contract")),
                           supplies=present.views(_linked("supplied_by", target_id=vendor.id)))


def vendor_count(vendor: Entity):
    return len(_linked("supplied_by", target_id=vendor.id)) or None


def contract_tab(contract: Entity) -> str:
    d = db.session.get(ContactDetail, contract.id)
    left = (d.ends - date.today()).days if d and d.ends else None
    notice = d.ends - timedelta(days=d.notice_days) if d and d.ends and d.notice_days else None
    return render_template("contacts/contract.html", contract=contract, d=d, left=left, notice=notice,
                           covers=present.views(_linked("covered_by", target_id=contract.id)))


def contract_count(contract: Entity):
    return len(_linked("covered_by", target_id=contract.id)) or None


# ———— The Supplier section in other records' forms ————

def is_supplied(etype) -> bool:
    return "supplied" in etype.traits


def supplier_form(etype, entity) -> str:
    vendor = _linked("supplied_by", source_id=entity.id, types=("vendor",)) if entity is not None else []
    contract = _linked("covered_by", source_id=entity.id, types=("contract",)) if entity is not None else []
    vendors = Entity.live().filter(Entity.type == "vendor").order_by(Entity.name).all()
    contracts = []
    for c in Entity.live().filter(Entity.type == "contract").order_by(Entity.name):
        d = db.session.get(ContactDetail, c.id)
        by = records.live(d.vendor) if d and d.vendor else None
        contracts.append((c.id, f"{c.name} · {by.name}" if by else c.name))
    return render_template("contacts/supplier_form.html", vendors=vendors, contracts=contracts,
                           vendor_id=vendor[0].id if vendor else None, contract_id=contract[0].id if contract else None)


def _relink(entity, kind, type_key, raw, label, user) -> list[dict]:
    current = _linked(kind, source_id=entity.id, types=(type_key,))
    new = None
    if raw not in (None, "", 0, "0"):
        new = records.live(raw)
        if new is None or new.type != type_key:
            raise Invalid(f"Choose a {label.lower()} that exists.")
    old = current[0] if current else None
    if (old.id if old else None) == (new.id if new else None):
        return []
    for other in current:
        for rel in Relationship.query.filter_by(kind=kind, source_id=entity.id, target_id=other.id):
            relations.unlink(rel, user, audit_source=False)
    if new is not None:
        relations.link(kind, entity, new, user=user, audit_source=False)
    return [{"field": kind, "label": label, "old": old.name if old else "", "new": new.name if new else ""}]


def supplier_save(entity, values, user) -> list[dict]:
    changes = []
    if "vendor_id" in values:
        changes += _relink(entity, "supplied_by", "vendor", values["vendor_id"], "Supplier", user)
    if "contract_id" in values:
        changes += _relink(entity, "covered_by", "contract", values["contract_id"], "Contract", user)
    return changes


# ———— The sidebar ————

def ending_soon(query):
    due = db.session.query(ContactDetail.entity_id).filter(
        ContactDetail.ends <= date.today() + timedelta(days=SOON_DAYS))
    return query.filter(Entity.type == "contract", Entity.status == "active", Entity.id.in_(due))
