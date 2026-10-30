"""A document as a printed copy, or a PDF: a page of its own, laid out as
paper, with no app around it. The browser prints it, or saves it from its
print dialog; Download PDF has the server make the PDF from the same page
with WeasyPrint (``pdf()``, core/pdf.py), which also fills in what browsers can't yet:
the title in the margin, page numbers in the contents, and bookmarks.

``?pages=1`` takes in every page under the document as well, in their
order, each starting on a new sheet, behind one contents list: a manual
printed whole. A link in the text to a page in the same copy then leads
to that page in the copy, and every heading id is made the page's own, so
two pages with the same heading keep their own anchors.

The layout is a shared component in app.css (``.printdoc``): real units,
``@page`` margins and the page numbers in the margin.
"""
import re
from html import unescape

from flask import abort, render_template, request, url_for
from markupsafe import Markup

from hyprvolt.core import access, clock, markdown, records
from hyprvolt.core import pdf as pdf_
from hyprvolt.models import utcnow

from . import views

#: The most documents one copy takes in.
LIMIT = 200
#: The paper it is laid out for (``?paper=``), the first unless another is
#: chosen: each a named @page in app.css, so a browser prints on it too.
PAPERS = (("letter", "Letter"), ("a4", "A4"))

HEADING_REF = re.compile(r'(id="|href="#)h-')
RECORD_REF = re.compile(r'href="/e/([0-9]+)"')


def tree(doc) -> list[tuple]:
    """The document, then every page under it the reader may see, depth
    first in their order, each with how deep it sits."""
    out, seen = [], set()

    def walk(e, depth):
        if e.id in seen or len(out) >= LIMIT:
            return
        seen.add(e.id)
        out.append((e, depth))
        if depth < views.MAX_DEPTH:
            for page in views.pages(e.id):
                walk(page, depth + 1)
    walk(doc, 0)
    return out


def _own(html: str, doc_id: int, included: set) -> Markup:
    """A page's HTML with its heading anchors made its own, and its links to
    documents in the same copy pointed at them there."""
    html = HEADING_REF.sub(lambda m: f"{m.group(1)}d{doc_id}-h-", html)
    html = RECORD_REF.sub(lambda m: f'href="#doc-{m.group(1)}"' if int(m.group(1)) in included else m.group(0), html)
    return Markup(html)


def _headings(tokens, doc_id: int) -> list[dict]:
    return [{"id": f"d{doc_id}-{t['id']}", "name": unescape(t["name"]),
             "children": _headings(t["children"], doc_id)} for t in tokens]


def _count(tokens) -> int:
    return sum(1 + _count(t["children"]) for t in tokens)


def _date(dt) -> str:
    """"October 3, 2026", in the instance's time zone."""
    return clock.to_local(dt).strftime("%B %-d, %Y")


def _context(entity_id) -> dict:
    doc = records.live(entity_id)
    if doc is None or doc.type != "document":
        abort(404)
    docs = tree(doc)
    under = len(docs) - 1
    whole = bool(under) and request.args.get("pages") == "1"
    if not whole:
        docs = docs[:1]
    included = {e.id for e, _ in docs}
    parts = []
    for e, depth in docs:
        html, tokens = markdown.parts(views._text(e.id))
        parts.append({"entity": e, "depth": depth, "status": records.status_label(e),
                      "access": access.SHORT.get(e.access or ""), "html": _own(html, e.id, included),
                      "headings": _headings(tokens, e.id), "count": _count(tokens)})
    first = parts[0]
    # One document: its headings, once there are enough of them, as on
    # screen. A manual: every page, each with its own top headings.
    contents = whole or first["count"] >= markdown.CONTENTS_AT
    trail = views.path(doc)
    paper = request.args.get("paper") if request.args.get("paper") in dict(PAPERS) else PAPERS[0][0]

    def url(endpoint="documents.print_copy", **changes):
        args = {"pages": 1 if whole else None, "paper": paper if paper != PAPERS[0][0] else None} | changes
        return url_for(endpoint, entity_id=doc.id, **{k: v for k, v in args.items() if v is not None})
    return dict(
        doc=doc, parts=parts, whole=whole, under=under, contents=contents, paper=paper, papers=PAPERS,
        trail=[e.name for e in trail], updated=_date(doc.updated_at), printed=_date(utcnow()),
        source=request.host_url.rstrip("/") + f"/e/{doc.id}",
        this_url=url(pages=None), whole_url=url(pages=1),
        paper_urls={key: url(paper=key if key != PAPERS[0][0] else None) for key, _ in PAPERS},
        pdf_url=url("documents.pdf_copy"))


def page(entity_id) -> str:
    return render_template("documents/print.html", **_context(entity_id))


# ———— The PDF ————

def pdf(entity_id):
    """The printed copy as a PDF file, named after the document."""
    context = _context(entity_id)
    html = render_template("documents/print.html", pdf=True, **context)
    return pdf_.download(pdf_.render(html), context["doc"].name or "Document")
