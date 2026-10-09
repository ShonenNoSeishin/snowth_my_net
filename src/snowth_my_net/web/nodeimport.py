"""Giving names to many MACs from a CSV: the three screens, in the order a person uses them.

1. Choose: download the list of the nodes (MAC and current name), fill the names in a
   spreadsheet, send the file back.
2. Check: nothing is written yet. What would be added, changed, left alone or refused, line by
   line, and a button to apply it.
3. Done: the same table with what happened, and the log to keep.

No state is held between the screens: the file travels in the page (a hidden field), so a
reload or a second reader cannot apply something nobody has seen.
"""

from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from html import escape as esc

from snowth_my_net.names import ERROR, RESULTS, ImportLine, counts

SHOWN = 1000                  # lines of the table; the log always holds all of them


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


DETAILS = {                  # what names.py says (kept English in the log) -> the key to show
    "not a MAC address": "web.import.d.mac",
    "no second column: the name": "web.import.d.column",
    "no name on this line: nothing is changed": "web.import.d.empty",
    "already named so": "web.import.d.same",
    "not seen on the network yet": "web.import.d.unseen",
}


def _detail(t, text: str) -> str:
    if text in DETAILS:
        return t(DETAILS[text])
    if found := re.fullmatch(r"MAC already on line (\d+), this line is ignored", text):
        return t("web.import.d.dup", line=found.group(1))
    if found := re.fullmatch(r"a name is at most (\d+) characters", text):
        return t("web.import.d.long", size=found.group(1))
    return text


def _chips(t, total: dict[str, int]) -> str:
    return '<p class="chips">' + " ".join(
        f'<span class="chip {kind}">{total[kind]} {esc(t("web.import.r." + kind))}</span>'
        for kind in RESULTS if total[kind]) + "</p>"


def _table(t, lines: list[ImportLine]) -> str:
    order = {kind: i for i, kind in enumerate(RESULTS)}
    shown = sorted(lines, key=lambda x: (order[x.result], x.line))[:SHOWN]
    head = "".join(f"<th>{esc(t(key))}</th>" for key in (
        "web.import.c.line", "col.mac", "web.import.c.before", "web.import.c.name",
        "web.import.c.result", "web.import.c.detail"))
    rows = "".join(
        f'<tr><td>{x.line}</td><td>{esc(x.mac)}</td><td>{esc(x.before)}</td><td>{esc(x.name)}</td>'
        f'<td class="r-{x.result}">{esc(t("web.import.r." + x.result))}</td>'
        f"<td>{esc(_detail(t, x.detail))}</td></tr>" for x in shown)
    more = (f'<p class="note">{esc(t("web.import.more", shown=SHOWN, total=len(lines)))}</p>'
            if len(lines) > SHOWN else "")
    return (f'<div class="wrap"><table class="plain"><thead><tr>{head}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div>{more}")


def _carry(name: str, text: str) -> str:
    """The text of a file, carried in the page for the next step."""
    return f'<textarea name="{name}" hidden>{esc(text)}</textarea>'


def choose(t, template_path: str, nodes: int, message: str, max_bytes: int) -> str:
    error = f'<p class="error">{esc(message)}</p>' if message else ""
    return (
        f"{error}<ol class=\"steps\">"
        f'<li><b>{esc(t("web.import.s1"))}</b> '
        f'<a class="btn" href="{esc(template_path)}">'
        f'{esc(t("web.import.template", count=nodes))}</a>'
        f'<span class="note"> {esc(t("web.import.s1.note"))}</span></li>'
        f'<li><b>{esc(t("web.import.s2"))}</b>'
        f'<span class="note"> {esc(t("web.import.s2.note"))}</span></li>'
        f'<li><b>{esc(t("web.import.s3"))}</b>'
        '<form class="actions" method="post" action="/import" enctype="multipart/form-data">'
        '<input type="file" name="file" accept=".csv,text/csv,text/plain" required>'
        f'<button type="submit" class="primary">{esc(t("web.import.check"))}</button>'
        f'<span class="note">{esc(t("web.import.file", size=max_bytes // 1024))}</span></form>'
        f"</li></ol>"
        f'<p class="note">{esc(t("web.import.hint"))}</p>')


def check(t, lines: list[ImportLine], text: str) -> str:
    total = counts(lines)
    changes = total["added"] + total["updated"]
    if changes:
        action = (
            '<form class="actions" method="post" action="/import">'
            f'{_carry("csv", text)}<input type="hidden" name="apply" value="1">'
            '<button type="submit" class="primary">'
            f'{esc(t("web.import.apply", count=changes))}</button>'
            f'<a class="btn" href="/import">{esc(t("web.import.other"))}</a></form>')
    else:
        action = (f'<p class="empty">{esc(t("web.import.nothing"))} '
                  f'<a href="/import">{esc(t("web.import.other"))}</a></p>')
    wrong = (f'<p class="error">{esc(t("web.import.errors", count=total[ERROR]))}</p>'
             if total[ERROR] else "")
    return (f'<p class="note">{esc(t("web.import.preview"))}</p>{_chips(t, total)}{wrong}'
            f"{action}{_table(t, lines)}")


def done(t, lines: list[ImportLine], log: str) -> str:
    total = counts(lines)
    return (f'<p class="state ok">{esc(t("web.import.done"))}</p>{_chips(t, total)}'
            '<form class="actions" method="post" action="/import/log">'
            f'{_carry("log", log)}'
            f'<button type="submit">{esc(t("web.import.log"))}</button>'
            f'<a class="btn" href="/nodes">{esc(t("web.import.back"))}</a></form>'
            f"{_table(t, lines)}")
