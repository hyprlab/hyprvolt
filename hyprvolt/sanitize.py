"""Allowlist HTML sanitizer (stdlib only).

Any HTML the app did not write itself goes through ``sanitize_html()`` before a
template renders it with ``|safe``. Tags outside ``ALLOWED`` are dropped,
attributes are cut down to the listed ones, and script-bearing containers go
with their contents.
"""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {
    "p": (), "br": (), "hr": (),
    "a": ("href",),
    "strong": (), "b": (), "em": (), "i": (), "u": (), "s": (), "mark": (), "small": (),
    "blockquote": (), "q": (),
    "ul": (), "ol": (), "li": (),
    "h1": ("id",), "h2": ("id",), "h3": ("id",), "h4": ("id",), "h5": ("id",), "h6": ("id",),
    "pre": (), "code": ("class",),
    "img": ("src", "alt", "title"),
    "figure": (), "figcaption": (),
    "table": (), "thead": (), "tbody": (), "tr": (), "th": ("colspan", "rowspan"), "td": ("colspan", "rowspan"),
    "sup": (), "sub": (),
}
VOID = {"br", "hr", "img"}
# Some attributes are allowed only with values of one shape, so nothing typed
# into a document can reuse the app's own ids or classes: a heading's anchor
# carries the h- prefix the Markdown renderer gives it, code only names its
# language, and a table cell spans a few rows or columns.
VALUES = {
    "id": re.compile(r"^h-[a-z0-9_-]{1,80}$"),
    "class": re.compile(r"^language-[A-Za-z0-9_+#.-]{1,30}$"),
    "colspan": re.compile(r"^[1-9][0-9]?$"),
    "rowspan": re.compile(r"^[1-9][0-9]?$"),
}
# An h1 in a body becomes an h2, under the page's own title; the rest keep
# their level, so sections and subsections still look different.
DEMOTE = {"h1": "h2"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "form", "svg", "video", "audio", "noscript"}

_SAFE_URL = re.compile(r"^(https?:)?//|^https?:|^/|^#|^mailto:", re.I)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag in DROP_WITH_CONTENT:
                self.skip_depth += 1
            return
        if tag in DROP_WITH_CONTENT:
            self.skip_depth = 1
            return
        if tag not in ALLOWED:
            return
        allowed_attrs = ALLOWED[tag]
        parts = []
        for name, value in attrs:
            if name in allowed_attrs and value:
                if name in ("href", "src") and not _SAFE_URL.match(value.strip()):
                    continue
                if name in VALUES and not VALUES[name].match(value.strip()):
                    continue
                parts.append(f' {name}="{escape(value.strip() if name in VALUES else value, quote=True)}"')
        if tag == "a" and not (dict(attrs).get("href") or "").startswith("#"):
            # A link to a place on the same page stays in it.
            parts.append(' target="_blank" rel="noopener noreferrer"')
        if tag == "img":
            parts.append(' loading="lazy"')
        out_tag = DEMOTE.get(tag, tag)
        self.out.append(f"<{out_tag}{''.join(parts)}{' /' if tag in VOID else ''}>")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag in DROP_WITH_CONTENT:
                self.skip_depth -= 1
            return
        if tag in ALLOWED and tag not in VOID:
            self.out.append(f"</{DEMOTE.get(tag, tag)}>")

    def handle_data(self, data):
        if not self.skip_depth and data:
            self.out.append(escape(data))


def sanitize_html(html: str) -> str:
    if not html:
        return ""
    s = _Sanitizer()
    try:
        s.feed(html)
        s.close()
    except Exception:
        return escape(strip_tags(html))
    return "".join(s.out)


# Only block-level tags separate words; inline tags must not, or stylised markup
# such as The Atlantic's drop caps (<p>W<span>hen ...</span>) turns into "W hen".
BLOCK = {
    "p", "br", "hr", "div", "section", "article", "header", "footer", "aside",
    "ul", "ol", "li", "dl", "dt", "dd",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "figure", "figcaption",
    "table", "thead", "tbody", "tr", "th", "td",
}


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip_depth += 1
            self.chunks.append(" ")
        elif tag in BLOCK:
            self.chunks.append(" ")

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            if self.skip_depth:
                self.skip_depth -= 1
            self.chunks.append(" ")
        elif tag in BLOCK:
            self.chunks.append(" ")

    def handle_data(self, data):
        if not self.skip_depth:
            self.chunks.append(data)


def strip_tags(html: str) -> str:
    """Plain text from HTML, whitespace collapsed."""
    if not html:
        return ""
    s = _Stripper()
    try:
        s.feed(html)
        s.close()
    except Exception:
        pass
    return re.sub(r"\s+", " ", "".join(s.chunks)).strip()


_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def first_image(html: str) -> str | None:
    if not html:
        return None
    m = _IMG_SRC.search(html)
    if m and _SAFE_URL.match(m.group(1).strip()):
        return m.group(1).strip()
    return None
