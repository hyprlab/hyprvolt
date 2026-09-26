"""The secrets vault: passwords, keys and license keys attached to any
record, encrypted with a key kept outside the database (crypto.py).

Built in, because a record's Secrets tab is part of every record, as its
Documents tab is. Only accounts an admin has granted access to secrets see
the tab, the pane or any route; the role decides only whether they may also
change them.
"""
from hyprvolt.manifest import Job, Module, Pane, Tab

from . import demo, views
from .models import Secret

ICON = '<circle cx="8" cy="15.5" r="4"/><path d="M10.8 12.7 20.5 3M16 7.5l3 3M18.5 5l2 2"/>'

module = Module(
    id="vault",
    name="Secrets",
    icon=ICON,
    description="Passwords, keys and license keys on any record, encrypted, each reveal in the history.",
    group="Knowledge",
    order=950,
    core=True,
    models=(Secret,),
    blueprint=views.bp,
    sheet_tabs=(Tab("secrets", "Secrets", views.tab, when=views.shows, count=views.count),),
    settings_pane=Pane("vault", "Secrets", views.pane, icon=ICON),
    jobs=(Job("purge", views.purge, minutes=60),),
    seed=demo.seed,
)
