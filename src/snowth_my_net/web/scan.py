"""The page of one address's port scan: what was found, a button, and the shell for the rest.

A scan is asked of one address at a time from here, by an account, when ``web.nmap`` is on. A
whole network is a command to type: the page prints it, ready to paste, so that the choice to
scan many hosts is made where the shell's own history and access rules apply.
"""

from __future__ import annotations

import ipaddress
import shutil
from html import escape as esc

from snowth_my_net.clock import local_time
from snowth_my_net.enrich import scan as engine

PROFILES = tuple(engine.PROFILES)


def parse_address(text: str) -> str | None:
    """The address as ``ipaddress`` writes it, or nothing: never a name, never an option."""
    try:
        return str(ipaddress.ip_address((text or "").strip()))
    except ValueError:
        return None


def refusal(cfg, address: str) -> str:
    """Why this address may not be scanned, or an empty string."""
    _allowed, skipped = engine.in_scope(cfg, [address])
    return skipped[0].reason if skipped else ""


def network_of(address: str) -> str:
    """A /24 (or /64) around the address: a sensible first thing to paste for a larger scan."""
    ip = ipaddress.ip_address(address)
    return str(ipaddress.ip_network(f"{address}/{24 if ip.version == 4 else 64}", strict=False))


def installed() -> bool:
    return shutil.which("nmap") is not None


def body(t, address: str, stored: dict | None, job, message: str, can_scan: bool,
         now: float, busy: bool) -> str:
    """The page under the title. ``job`` is the running or last scan job of this address, else
    ``None``; ``busy`` is any job at all, since two at once would only fight over the state."""
    parts = [f'<p><a class="back" href="/">← {esc(t("web.back"))}</a></p>']
    error = f'<p class="error">{esc(message)}</p>' if message else ""
    if can_scan:
        options = "".join(
            f'<option value="{p}"{" selected" if p == engine.DEFAULT_PROFILE else ""}>'
            f'{esc(t(f"web.scan.profile.{p}"))}</option>' for p in PROFILES)
        state = ""
        if job is not None and job.running:
            said = t("web.do.running", what=t("web.do.scan"), seconds=job.seconds(now))
            state = f'<p class="state running">{esc(said)}</p>'
        elif job is not None:
            said = t("web.do.last", what=t("web.do.scan"), status=t(f"web.do.{job.status}"),
                     seconds=job.seconds(now), detail=job.summary or "-")
            state = f'<p class="state {esc(job.status)}">{esc(said)}</p>'
        warning = "" if installed() else f'<p class="error">{esc(t("web.scan.no_nmap"))}</p>'
        parts.append(
            f'<form class="actions" method="post" action="/scan">'
            f'<input type="hidden" name="address" value="{esc(address)}">'
            f'<span class="what">{esc(t("web.scan.profile"))}</span>'
            f'<select name="profile">{options}</select>'
            f'<button type="submit"{" disabled" if busy else ""}>{esc(t("web.scan.start"))}'
            f"</button>"
            f'<span class="note">{esc(t("web.scan.hint"))}</span>{state}{warning}{error}</form>')
    elif error:
        parts.append(error)
    parts.append(_result(t, stored))
    command = f"docker compose exec web snowth_my_net scan {network_of(address)} --profile common"
    parts.append(f'<h2>{esc(t("web.scan.mass.title"))}</h2>'
                 f'<p class="note">{esc(t("web.scan.mass.hint"))}</p>'
                 f'<pre class="explain"><span class="ok">{esc(command)}</span></pre>')
    return "".join(parts)


def _result(t, stored: dict | None) -> str:
    if stored is None:
        return f'<p class="empty">{esc(t("web.scan.none"))}</p>'
    took = f", {stored['seconds']:g} s" if stored["seconds"] else ""
    said = t("web.scan.last", when=local_time(stored["scanned_at"]), profile=stored["profile"])
    head = f'<p class="note">{esc(said + took)}</p>'
    if stored["status"] == "down":
        return head + f'<p class="empty">{esc(t("web.scan.down"))}</p>'
    if stored["status"] == "suspect":
        return head + f'<p class="error">{esc(t("web.scan.suspect"))} {esc(stored["detail"])}</p>'
    if not stored["ports"]:
        why = f" ({stored['detail']})" if stored["detail"] else ""
        return head + f'<p class="empty">{esc(t("web.scan.nothing_open"))}{esc(why)}</p>'
    rows = "".join(
        "<tr>" + "".join(f"<td>{esc(str(cell))}</td>" for cell in (
            p["port"], p["proto"], p["service"], p["product"], p["version"])) + "</tr>"
        for p in stored["ports"])
    cols = "".join(f"<th>{esc(t(key))}</th>" for key in (
        "col.port", "col.proto", "col.service", "col.product", "col.version"))
    return (head + f'<div class="wrap"><table class="plain"><thead><tr>{cols}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")
