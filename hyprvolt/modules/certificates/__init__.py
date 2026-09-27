"""Certificates: TLS certificates, what they secure, and when they expire.

The expiry is an ``expires`` date, so the dashboard's Coming up card and the
sidebar badge remind of it with no job of this module's. One that renews by
itself (ACME) is reminded of only when it is late: ``views.lead``. Given an
address to check, the worker reads the certificate served there each day
and keeps the record current. "Used by" points at anything with the ``tls``
trait (services, and hosts that serve their own) and is kept as a "secures" link, so the
dependency view of a certificate lists what breaks when it expires.
"""
from hyprvolt.manifest import EntityType, Field, Job, ListFilter, Module, RelationKind, Tab

from . import demo, views
from .models import CertificateDetail

STATUSES = (("active", "In use"), ("planned", "Not in use yet"), ("retired", "Replaced"))

ICON = ('<rect x="3.5" y="4.5" width="17" height="12" rx="1.5"/><path d="M7 8.5h7M7 11.5h4"/>'
        '<circle cx="16" cy="14.5" r="2.5"/><path d="m14.6 16.6-.9 3.9 2.3-1.2 2.3 1.2-.9-3.9"/>')

module = Module(
    id="certificates",
    name="Certificates",
    icon=ICON,
    description="TLS certificates: the names they cover, who issued them, what uses them and when they expire.",
    group="Operations",
    order=52,
    models=(CertificateDetail,),
    blueprint=views.bp,
    relation_kinds=(RelationKind("secures", "secures", "secured by", impact="target"),),
    types=(
        EntityType("certificate", "Certificate", "Certificates", detail=CertificateDetail, located_in=(), icon=ICON,
                   statuses=STATUSES, check=views.check_fields,
                   fields=(Field("names", "Names", "longtext",
                                 help="The names it covers, one to a line: lab.home, *.lab.home."),
                           Field("secures", "Used by", "ref", trait="tls", relation="secures", card=True,
                                 help="The service or host that serves it. More than one: link the rest in "
                                      "Relationships."),
                           Field("issuer", "Issued by", card=True, list=True,
                                 help="Let's Encrypt R11, an internal CA, self-signed."),
                           Field("issued", "Valid from", "date", group="Validity"),
                           Field("expires", "Expires", "date", card=True, list=True, group="Validity", expires=True,
                                 remind=views.lead),
                           Field("auto_renew", "Renews by itself", "boolean", group="Validity",
                                 help=f"Renewed by ACME or the like. Reminded of only once it is {views.LATE_DAYS} "
                                      "days from its end, when the renewal has plainly failed."),
                           Field("endpoint", "Check at", group="Live check",
                                 help="A host and port that serves it, such as nas1.lab.home:443. The app reads the "
                                      "certificate there once a day and keeps these details current."),
                           Field("key_type", "Key", group="Details", help="RSA 2048, ECDSA P-256."),
                           Field("serial", "Serial number", group="Details"),
                           Field("fingerprint", "SHA-256 fingerprint", group="Details")),
                   tabs=(Tab("check", "Check", views.check_tab),)),
    ),
    filters=(ListFilter("expiring", "Expiring soon", views.expiring),
             ListFilter("check_failed", "Check failed", views.check_failed)),
    jobs=(Job("check", views.check_due, minutes=60),),
    seed=demo.seed,
)
