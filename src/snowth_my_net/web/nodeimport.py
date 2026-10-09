"""The page that gives names to many MACs from one uploaded CSV, and its file upload."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from html import escape as esc


def upload_text(content_type: str, data: bytes) -> str | None:
    """The text of the first file of a ``multipart/form-data`` body, or nothing."""
    if not content_type.lower().startswith("multipart/form-data"):
        return None
    message = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n" + data)
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == "file" and (
                part.get_filename() is not None):
            raw = part.get_payload(decode=True) or b""
            return raw.decode("utf-8-sig", errors="replace") if raw.strip() else None
    return None


def body(t, template_path: str, message: str, max_bytes: int) -> str:
    """The form: the file, the button, and the template to start from."""
    error = f'<p class="error">{esc(message)}</p>' if message else ""
    return (f'<p class="note">{esc(t("web.import.hint"))}</p>{error}'
            '<form class="actions" method="post" action="/import" enctype="multipart/form-data">'
            f'<label>{esc(t("web.import.file", size=max_bytes // 1024))} '
            '<input type="file" name="file" accept=".csv,text/csv,text/plain" required></label>'
            f'<button type="submit">{esc(t("web.import.send"))}</button></form>'
            f'<p><a href="{esc(template_path)}">{esc(t("web.import.template"))}</a></p>')
