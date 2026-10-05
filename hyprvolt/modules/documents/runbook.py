"""The knowledge base's part in the site setup guide: once a site is set up,
its runbook. The document links to what the guide recorded in the site with
[[slug]], so it stays right as those records change, and has headings with
prompts for what only a person can write: who to call, what to check first,
how to get it back."""
from hyprvolt.core import records, relations
from hyprvolt.core.models import Relationship

#: What a runbook asks of its writer, a heading and a prompt each.
PROMPTS = (
    ("Who to call", "The internet provider's and vendors' support lines are on their records above. Add anyone "
                    "else worth calling: the landlord, an electrician, a colleague with the keys."),
    ("When the internet is down", "What to check, in order: the modem's lights, then the router, then the "
                                  "provider's status page. Where the equipment is and how to restart it."),
    ("When something else breaks", "For each thing that matters: how you know it is down, what to try first, "
                                   "and who to tell."),
    ("Backups and recovery", "Where the backups are, how a restore is done, and when one was last tested."),
)


def title(site) -> str:
    return f"{site.name} runbook"


def made(site):
    """The site's runbook, if the guide made one that is still there."""
    for rel in Relationship.query.filter_by(kind="documented_by", source_id=site.id):
        doc = records.live(rel.target_id)
        if doc is not None and doc.type == "document" and doc.name == title(site):
            return doc
    return None


def body(site, found) -> str:
    lines = [f"How {site.name} is put together, and how to get it back when something breaks. Each link opens "
             "its record. The parts in italics are prompts: replace them with what is true here.", ""]
    group = None
    for part in found:
        if part["group"] != group:
            group = part["group"]
            lines += ["", f"## {group or 'Records'}", ""]
        lines.append(f"- {part['title']}: " + ", ".join(f"[[{e.slug}]]" for e in part["records"]))
    for heading, prompt in PROMPTS:
        lines += ["", f"## {heading}", "", f"_{prompt}_"]
    return "\n".join(lines).replace("\n\n\n", "\n\n").strip() + "\n"


def make(site, found, user):
    """A draft document, attached to the site (its Documents tab lists it)."""
    doc = records.create("document", {"name": title(site), "status": "draft", "f.body": body(site, found)}, user)
    relations.link("documented_by", site, doc, user=user)
    return doc
