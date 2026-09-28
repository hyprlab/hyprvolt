"""Markdown for documents and notes, with links between records.

``[[pve1]]`` links to the record whose slug is ``pve1``, showing its name;
``[[pve1|the main host]]`` shows other words. A slug that matches nothing is
struck through, so a broken link is visible rather than silently plain text.

The Markdown is converted, then passed through ``sanitize_html()`` like any
HTML the app did not write itself: raw HTML typed into a document can't run.
What the app adds afterwards it writes itself, escaping what it takes from
the text: headings get anchors (``h-`` ids) and, on a longer page, a
contents list; fenced code is colored by Pygments for its language; and
``- [ ]`` and ``- [x]`` list items become checkboxes.
"""
import re
from html import escape, unescape

import markdown as md_lib
from markdown.extensions.toc import slugify_unicode
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from ..sanitize import sanitize_html

WIKI_LINK = re.compile(r"\[\[([a-z0-9][a-z0-9-]{0,118})(?:\|([^\]\n]{1,200}))?\]\]")
EXTENSIONS = ["extra", "sane_lists", "toc"]
#: A page with this many headings gets a contents list at the top.
CONTENTS_AT = 3
CODE_BLOCK = re.compile(r'<pre><code class="language-([A-Za-z0-9_+#.-]{1,30})">(.*?)</code></pre>', re.S)
TASK = re.compile(r"<li>(<p>)?\[([ xX])\] ")
FORMATTER = HtmlFormatter(nowrap=True, classprefix="hl-")


def _anchor(value: str, separator: str) -> str:
    """Heading ids the sanitizer lets through: h-, then the words."""
    return "h-" + (slugify_unicode(value, separator)[:78] or "section")


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

    md = md_lib.Markdown(extensions=EXTENSIONS, output_format="html",
                         extension_configs={"toc": {"slugify": _anchor, "toc_depth": "1-4"}})
    html = sanitize_html(md.convert(WIKI_LINK.sub(link, text)))
    html = CODE_BLOCK.sub(_highlight, html)
    html = TASK.sub(_task, html)
    return Markup(_contents(md.toc_tokens) + html)


def _highlight(m) -> str:
    """A fenced block colored for its language; one Pygments doesn't know
    stays plain. Its text was escaped by the sanitizer, so it is unescaped
    for Pygments, which escapes it again."""
    lang = m.group(1)
    try:
        lexer = get_lexer_by_name(lang.lower())
    except ClassNotFound:
        return f'<pre data-lang="{escape(lang)}"><code class="language-{escape(lang)}">{m.group(2)}</code></pre>'
    code = highlight(unescape(m.group(2)), lexer, FORMATTER)
    return f'<pre data-lang="{escape(lang)}"><code class="language-{escape(lang)}">{code}</code></pre>'


def _task(m) -> str:
    done = m.group(2) != " "
    box = f'<input type="checkbox" disabled{" checked" if done else ""} aria-label="{"Done" if done else "Not done"}"> '
    return f'<li class="task">{m.group(1) or ""}{box}'


def _contents(tokens) -> str:
    """A contents list for a page with enough headings, linking to their
    anchors. Built here, with every name escaped."""
    def count(items):
        return sum(1 + count(t["children"]) for t in items)

    def items(nodes):
        return "".join(f'<li><a href="#{escape(t["id"])}">{escape(unescape(t["name"]))}</a>'
                       f'{"<ol>" + items(t["children"]) + "</ol>" if t["children"] else ""}</li>'
                       for t in nodes)
    if count(tokens) < CONTENTS_AT:
        return ""
    return f'<nav class="doc-contents" aria-label="Contents"><p class="setting-label">Contents</p><ol>{items(tokens)}</ol></nav>'



def excerpt(text: str, length: int = 180) -> str:
    """The first words of a document, without its Markdown."""
    plain = WIKI_LINK.sub(lambda m: m.group(2) or m.group(1), text or "")
    plain = re.sub(r"```.*?```", " ", plain, flags=re.S)
    plain = re.sub(r"[#>*_`\[\]()|-]+", " ", plain)
    plain = " ".join(plain.split())
    return plain if len(plain) <= length else plain[:length].rsplit(" ", 1)[0] + "…"
