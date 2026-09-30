"""Contacts and vendors: the companies that supply things, the people there,
and the contracts that cover what they supply.

Anything with the ``supplied`` trait (hardware, software, a domain, a
service) gets a Supplier section in its form: its vendor and the contract
that covers it, kept as "supplied by" and "covered by" links, so a vendor's
Supplies tab and a contract's Covers tab list them.
"""
from hyprvolt.manifest import (EntityType, Field, FormSection, ListFilter, Module, RelationKind, SetupField, SetupKind,
                               SetupStep, Tab)

from . import demo, views
from .models import ContactDetail

VENDOR_STATUSES = (("active", "Current"), ("retired", "Former"))
PERSON_STATUSES = (("active", "Current"), ("retired", "Moved on"))
CONTRACT_STATUSES = (("active", "In force"), ("planned", "Not started"), ("retired", "Ended"))
CONTRACT_KINDS = (("support", "Support"), ("maintenance", "Maintenance"), ("warranty", "Extended warranty"),
                  ("subscription", "Subscription"), ("service", "Service"), ("lease", "Lease"), ("other", "Other"))
BILLING = (("monthly", "Monthly"), ("quarterly", "Quarterly"), ("yearly", "Yearly"), ("once", "Once"))

ICON = ('<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.6-3.2 2.7-5 5.5-5s4.9 1.8 5.5 5"/>'
        '<path d="M15.5 5.6a3.2 3.2 0 0 1 0 5.8M17.5 14.8c1.6.7 2.7 2.3 3 4.7"/>')
VENDOR = '<path d="M4 20.5V9l8-5 8 5v11.5M4 20.5h16M9 20.5v-6h6v6"/>'
PERSON = '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.8 3.4-6 7-6s6.2 2.2 7 6"/>'
CONTRACT = '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V3.5Z"/><path d="M14 3.5V8h4M9.5 12.5h5M9.5 16c1-.8 1.8-.8 2.6 0s1.6.8 2.4 0"/>'

module = Module(
    id="contacts",
    name="Contacts and vendors",
    icon=ICON,
    description="Vendors with their support numbers and account numbers, the people there, and contracts.",
    group="Operations",
    order=70,
    models=(ContactDetail,),
    relation_kinds=(RelationKind("supplied_by", "supplied by", "supplies", impact="none"),
                    RelationKind("covered_by", "covered by", "covers", impact="none")),
    types=(
        EntityType("vendor", "Vendor", "Vendors", detail=ContactDetail, located_in=(), icon=VENDOR,
                   statuses=VENDOR_STATUSES,
                   fields=(Field("website", "Website", "url"),
                           Field("support_phone", "Support phone", "phone", card=True, list=True, group="Support"),
                           Field("support_email", "Support email", "email", group="Support"),
                           Field("support_url", "Support site", "url", group="Support"),
                           Field("account_number", "Account number", card=True, group="Support",
                                 help="What support asks for: a customer or account number."),
                           Field("address", "Address", "longtext")),
                   tabs=(Tab("supplies", "Supplies", views.vendor_tab, count=views.vendor_count),)),
        EntityType("person", "Person", "People", detail=ContactDetail, located_in=(), icon=PERSON,
                   statuses=PERSON_STATUSES,
                   fields=(Field("organization", "Works at", "ref", types=("vendor",), card=True, list=True),
                           Field("role", "Role", list=True, help="Account manager, on-call engineer."),
                           Field("email", "Email", "email", card=True),
                           Field("phone", "Phone", "phone", card=True),
                           Field("mobile", "Mobile", "phone"))),
        EntityType("contract", "Contract", "Contracts", detail=ContactDetail, located_in=(), icon=CONTRACT,
                   statuses=CONTRACT_STATUSES,
                   fields=(Field("vendor", "With", "ref", types=("vendor",), card=True, list=True),
                           Field("kind", "Kind", "select", options=CONTRACT_KINDS, list=True),
                           Field("number", "Contract number"),
                           Field("starts", "Starts", "date", group="Term"),
                           Field("ends", "Ends or renews", "date", card=True, list=True, group="Term", expires=True),
                           Field("auto_renew", "Renews by itself", "boolean", group="Term"),
                           Field("notice_days", "Notice period", "integer", min=0, max=3650, unit="days",
                                 group="Term", help="How long before the end it must be canceled."),
                           Field("cost", "Cost", "number", min=0, group="Cost"),
                           Field("billing", "Billed", "select", options=BILLING, group="Cost")),
                   tabs=(Tab("covers", "Covers", views.contract_tab, count=views.contract_count),)),
    ),
    filters=(ListFilter("ending", "Contracts ending soon", views.ending_soon),),
    form_sections=(FormSection("supplier", "Supplier", views.supplier_form, views.supplier_save,
                               when=views.is_supplied),),
    setup=(SetupStep("vendors", "Vendors", "Who you buy from and call when something breaks: your internet "
                     "provider first, then the makers and shops behind your equipment.", 35,
                     group="Network", plan="vendors",
                     kinds=(SetupKind("Vendor", "vendor"),),
                     fields=(SetupField("name", placeholder="Springfield Cable"), SetupField("f.support_phone"),
                             SetupField("f.website"), SetupField("f.account_number"))),),
    seed=demo.seed,
)
