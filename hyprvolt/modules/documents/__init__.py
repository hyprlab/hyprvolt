"""The knowledge base: Markdown documents that stand alone or attach to any
record ("documented by"), and link to records with ``[[slug]]``.

A document can be a page of another ("Part of"), in an order of its own:
the parent lists its pages, and each page shows its path and the pages
either side of it (views.page_overview). A document's Linked from tab lists
the documents that mention it.

Built in (``core=True``): the Documents tab every record has comes from here,
so it can't be turned off.
"""
from hyprvolt.core.models import EntityDetail
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, SetupFinish, Step, Tab
from hyprvolt.models import db

ICON = '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V3.5Z"/><path d="M14 3.5V8h4M10 12h5M10 15.5h5"/>'


class DocumentBody(EntityDetail, db.Model):
    __tablename__ = "document_bodies"
    body = db.Column(db.Text, nullable=False, default="")
    parent = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    position = db.Column(db.Integer)


def _pages(m):
    m.add_column("document_bodies", "parent", "INTEGER REFERENCES entities(id) ON DELETE SET NULL")
    m.add_column("document_bodies", "position", "INTEGER")
    m.add_index("ix_document_bodies_parent", "document_bodies", ["parent"])


module = Module(
    id="documents",
    name="Knowledge base",
    icon=ICON,
    description="Runbooks, how-tos and notes in Markdown, linked to the records they describe.",
    group="Knowledge",
    order=900,
    core=True,
    migrations=(Step("document-pages", _pages),),
    types=(
        EntityType(
            "document", "Document", "Documents", detail=DocumentBody, located_in=(),
            statuses=(("current", "Current"), ("draft", "Draft"), ("outdated", "Outdated")),
            restrictable=True,
            check=lambda e, d: views.check_parent(e, d),
            overview=lambda e: views.page_overview(e),
            tabs=(Tab("linked", "Linked from", lambda e: views.linked_tab(e), count=lambda e: views.linked_count(e)),),
            fields=(Field("parent", "Part of", "ref", types=("document",), card=True, list=True,
                          help="The document this is a page of, such as a manual's front page. The parent lists "
                               "its pages in order, and each page shows where it sits and links to the pages "
                               "before and after it. Leave it empty for a page that stands alone."),
                    Field("position", "Order", "integer", min=0, max=9999,
                          help="Where it comes among the parent's pages: lower numbers first. Pages with no "
                               "number, or the same one, go by name."),
                    Field("body", "Body", "markdown",
                          help="Markdown. # and ## make headings, and a page with three or more gets a "
                               "contents list. ```bash starts a code block colored for that language; "
                               "- [ ] and - [x] make a task list. Link to a record with [[its-slug]]."),),
        ),
    ),
    filters=(ListFilter("top", "Top-level pages", lambda q: views.top_level(q)),),
    sheet_tabs=(
        Tab("documents", "Documents", lambda e: views.documents_tab(e),
            when=lambda e: e.type != "document", count=lambda e: views.count(e)),
    ),
    setup_finish=(SetupFinish("runbook", "Start the site's runbook",
                              "One document for when something breaks: it links to everything recorded here, "
                              "with headings for who to call, what to check first and how to recover.",
                              make=lambda site, found, user: runbook.make(site, found, user),
                              made=lambda site: runbook.made(site), open_label="Open the site's runbook"),),
    seed=lambda demo_: demo.seed(demo_),
)

from . import demo, runbook, views  # noqa: E402  (after DocumentBody, which views imports)
