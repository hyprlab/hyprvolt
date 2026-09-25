"""Markdown for documents and notes, with links between records.

``[[pve1]]`` links to the record whose slug is ``pve1``, showing its name;
``[[pve1|the main host]]`` shows other words. A slug that matches nothing is
struck through, so a broken link is visible rather than silently plain text.

The Markdown is converted, then passed through ``sanitize_html()`` like any
HTML the app did not write itself: raw HTML typed into a document can't run.
"""
import re
from html import escape

import markdown as md_lib
from markupsafe import Markup

from ..sanitize import sanitize_html

WIKI_LINK = re.compile(r"\[\[([a-z0-9][a-z0-9-]{0,118})(?:\|([^\]\n]{1,200}))?\]\]")
EXTENSIONS = ["extra", "sane_lists"]


def _md_text(text: str) -> str:
    """Words safe inside a Markdown link: HTML-escaped, brackets escaped."""
    return escape(text).replace("[", "\\[").replace("]", "\\]")


def slugs_in(text: str) -> set[str]:
    return {m.group(1) for m in WIKI_LINK.finditer(text or "")}


def render(text: str) -> Markup:
    if not (text or "").strip():
        return Markup("")
    from ..registry import current as registry
    from .models import Entity
    wanted = slugs_in(text)
    found = {}
    if wanted:
        keys = registry().enabled_type_keys()
        found = {e.slug: e for e in Entity.live().filter(Entity.slug.in_(wanted), Entity.type.in_(keys))}

    def link(m):
        entity = found.get(m.group(1))
        label = m.group(2) or (entity.name if entity else m.group(1))
        if entity:
            return f"[{_md_text(label)}](/e/{entity.id})"
        return f"<s>{escape(label)}</s>"

    html = md_lib.markdown(WIKI_LINK.sub(link, text), extensions=EXTENSIONS, output_format="html")
    return Markup(sanitize_html(html))


def excerpt(text: str, length: int = 180) -> str:
    """The first words of a document, without its Markdown."""
    plain = WIKI_LINK.sub(lambda m: m.group(2) or m.group(1), text or "")
    plain = re.sub(r"```.*?```", " ", plain, flags=re.S)
    plain = re.sub(r"[#>*_`\[\]()|-]+", " ", plain)
    plain = " ".join(plain.split())
    return plain if len(plain) <= length else plain[:length].rsplit(" ", 1)[0] + "…"
