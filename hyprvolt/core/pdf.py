"""PDFs made on the server from a page of the app, with WeasyPrint: a
document's printed copy, a sheet of labels.

The page is rendered as HTML and laid out as print media, so the same
template and app.css that a browser prints make the PDF. WeasyPrint asks
for every file the page names; ``_local()`` hands it only the app's own
stylesheet and fonts, pictures attached to records the reader may see, and
the files the caller passes in. Anything else is refused: text in a record
must never make the server fetch an address on its network.
"""
import logging
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flask import current_app, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.security import safe_join

# WeasyPrint reports each CSS property of app.css it doesn't know, on every
# PDF: problems with the PDF itself are still logged.
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

STATIC = re.compile(r"/static/([A-Za-z0-9_./-]{1,200})")
ATTACHMENT = re.compile(r"/attachments/([0-9]{1,12})(?:/.*)?")


def _local(url: str, files: dict | None = None) -> tuple[bytes, str]:
    """A file the PDF asks for, and its type: one of ``files`` (path:
    (bytes, type)), the app's own static files, or a picture attached to a
    record the reader may see. Anything else, another server above all, is
    refused (ValueError, which WeasyPrint reports and leaves out)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.netloc != request.host:
        raise ValueError(f"Not this app's: {url}")
    path = unquote(parts.path)
    if files and path in files:
        return files[path]
    if m := STATIC.fullmatch(path):
        found = safe_join(current_app.static_folder, m.group(1))
        if found is None or not Path(found).is_file():
            raise ValueError(f"No such file: {url}")
        return Path(found).read_bytes(), mimetypes.guess_type(found)[0] or "application/octet-stream"
    if m := ATTACHMENT.fullmatch(path):
        from hyprvolt.core.api import attachment_or_404
        from hyprvolt.core.attachments import path_for
        try:
            att = attachment_or_404(int(m.group(1)))
        except HTTPException:
            raise ValueError(f"No such file: {url}") from None
        found = path_for(att)
        if not att.is_image or not found.is_file():
            raise ValueError(f"Not a picture: {url}")
        return found.read_bytes(), att.content_type
    raise ValueError(f"Not a file the PDF may use: {url}")


def render(html: str, files: dict | None = None) -> bytes:
    """The page's HTML as a PDF. ``files`` maps a path the page names
    (``/labels/logo``) to the (bytes, type) to use for it."""
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    class Fetcher(URLFetcher):
        def fetch(self, url, headers=None):
            body, kind = _local(url, files)
            return URLFetcherResponse(url, body=body, headers={"Content-Type": kind})

    return HTML(string=html, base_url=request.host_url, url_fetcher=Fetcher()).write_pdf()


def download(data: bytes, name: str):
    """The PDF as a download named ``name``.pdf, made safe for a file name."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name).strip() or "Download"
    return send_file(BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{name}.pdf", max_age=0)
