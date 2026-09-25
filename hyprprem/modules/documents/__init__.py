"""The knowledge base: Markdown documents that stand alone or attach to any
record ("documented by"), and link to records with ``[[slug]]``.

Built in (``core=True``): the Documents tab every record has comes from here,
so it can't be turned off.
"""
from hyprprem.core.models import EntityDetail
from hyprprem.manifest import EntityType, Field, Module, Tab
from hyprprem.models import db

ICON = '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V3.5Z"/><path d="M14 3.5V8h4M10 12h5M10 15.5h5"/>'


class DocumentBody(EntityDetail, db.Model):
    __tablename__ = "document_bodies"
    body = db.Column(db.Text, nullable=False, default="")


module = Module(
    id="documents",
    name="Knowledge base",
    icon=ICON,
    description="Runbooks, how-tos and notes in Markdown, linked to the records they describe.",
    group="Knowledge",
    order=900,
    core=True,
    types=(
        EntityType(
            "document", "Document", "Documents", detail=DocumentBody, located_in=(),
            statuses=(("current", "Current"), ("draft", "Draft"), ("outdated", "Outdated")),
            fields=(Field("body", "Body", "markdown",
                          help="Markdown. Link to a record with [[its-slug]]."),),
        ),
    ),
    sheet_tabs=(
        Tab("documents", "Documents", lambda e: views.documents_tab(e),
            when=lambda e: e.type != "document", count=lambda e: views.count(e)),
    ),
)

from . import views  # noqa: E402  (after DocumentBody, which it imports)
