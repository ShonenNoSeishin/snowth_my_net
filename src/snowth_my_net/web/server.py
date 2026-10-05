"""Read-only web interface: a small HTTP server over the state, no dependency beyond Python.

Design, on purpose:

* **Nothing can change the state.** Only GET is answered, the database is opened read-only,
  and no page offers an action: collecting and exporting stay in the CLI and in the terminal
  interface, where the state lock lives.
* **No secret is ever rendered** — the state only holds credential names, never their values.
* **It binds to the loopback by default** (``web.bind``). There is no login: put a reverse
  proxy in front of it if you expose it beyond the machine.
"""

from __future__ import annotations

import html
import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from snowth_my_net import __version__
from snowth_my_net.clock import Clock, local_zone
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.manual import ManualError, normalize_address
from snowth_my_net.config.schema import LOOPBACK
from snowth_my_net.i18n import Translator, detect_language
from snowth_my_net.logs import get_logger
from snowth_my_net.names import MAX_LENGTH, NameError_, clean_mac, store_for
from snowth_my_net.state.db import StateError, open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import pages, snmp
from snowth_my_net.web.accounts import (
    MIN_LENGTH,
    STORE_NAME,
    Account,
    Store,
    initial_password,
)
from snowth_my_net.web.auth import (
    COOKIE,
    SCHEME,
    LoginLimiter,
    Sessions,
    hash_password,
    parse_cookie,
    parse_hash,
    verify_password,
)
from snowth_my_net.web.jobs import ACTIONS, Runner
from snowth_my_net.web.pages import Cell, Editable

LANGUAGES = ("en", "fr")
LANG_COOKIE = "snowth_lang"

log = get_logger("web")
ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
CONTENT_TYPES = {".csv": "text/csv; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".html": "text/html; charset=utf-8", ".dot": "text/plain; charset=utf-8",
                 ".mmd": "text/plain; charset=utf-8"}
MAX_FORM_BYTES = 4096
JSON = "application/json; charset=utf-8"


@dataclass(frozen=True)
class Page:
    path: str
    label_key: str


NAV = (Page("/", "tab.devices"), Page("/nodes", "tab.nodes"), Page("/links", "tab.links"),
       Page("/runs", "tab.runs"), Page("/files", "web.tab.files"))
SNMP_PAGE = Page("/snmp", "web.snmp.tab")


class Site:
    """Everything a request needs; one instance is shared by the server threads."""

    def __init__(self, loaded: LoadedConfig, clock: Clock | None = None) -> None:
        self.loaded = loaded
        self.clock = clock or Clock()
        self.t = Translator(detect_language(loaded.cfg.general.language))
        self.names = [user.name for user in loaded.cfg.web.auth.users]
        self.fixed = load_accounts(loaded)          # password_file / password_env accounts
        self.store = Store(loaded.paths.state_dir / STORE_NAME)
        self.labels = store_for(loaded.paths)      # MAC -> name given by hand
        self.jobs = Runner(str(loaded.paths.config_file), loaded.cfg.general.run_timeout)
        self.writing = threading.Lock()
        self.sessions = Sessions(lifetime=loaded.cfg.web.auth.session_hours * 3600)
        self.logins = LoginLimiter()
        self.proxies = list(loaded.cfg.web.trusted_proxies)
        self.bootstrap()

    def caller(self, peer: str, forwarded: str | None) -> str:
        """The reader's address: the peer, unless a trusted proxy stated another one.

        Behind the bundled TLS front every request comes from the same container. Without this,
        one address would be logged for everybody and five wrong passwords would lock out
        everybody; with it, a header from anyone else is still ignored.
        """
        if not (self.proxies and forwarded and self.trusts(peer)):
            return peer
        for candidate in reversed([part.strip() for part in forwarded.split(",")]):
            if candidate and not self.trusts(candidate):
                return candidate
        return peer

    def trusts(self, address: str) -> bool:
        try:
            parsed = ip_address(address)
        except ValueError:
            return False
        return any(parsed in network for network in self.proxies
                   if parsed.version == network.version)

    @property
    def guarded(self) -> bool:
        """True when accounts are configured: every page then needs a session."""
        return bool(self.names)

    @property
    def manageable(self) -> bool:
        """The SNMP page exists only with an account: it asks for that password again."""
        return self.guarded and self.loaded.cfg.web.actions

    def bootstrap(self) -> None:
        """Give every declared account without a password a first one, and log it.

        Logged, not written into the configuration: whoever reads the log already administers
        the machine, and this way nothing has to be pasted anywhere. It is asked for at the
        first sign-in and replaced there; 'web passwd' sets another one at any time.
        """
        known = self.store.read()
        for name in self.names:
            if name in self.fixed or name in known:
                continue
            password = initial_password()
            with self.writing:
                self.store.set(name, hash_password(password), must_change=True)
            log.warning("web user %r has no password yet - sign in once with: %s "
                        "(the interface then asks you to choose your own)", name, password)

    def account_of(self, name: str) -> Account | None:
        """The account as it stands now; the store is re-read so that 'web passwd' in a
        shell reaches the running interface without a restart."""
        if name not in self.names:
            return None
        if name in self.fixed:
            return Account(name, self.fixed[name], must_change=False, from_file=True)
        return self.store.read().get(name)

    def set_password(self, name: str, password: str) -> None:
        with self.writing:
            self.store.set(name, hash_password(password), must_change=False)

    # ----------------------------------------------------------------- login

    def login_page(self, message: str = "", target: str = "/", t=None) -> bytes:
        t = t or self.t
        error = f'<p class="error">{esc(message)}</p>' if message else ""
        body = (f'<form class="login" method="post" action="/login">'
                f'<input type="hidden" name="next" value="{esc(target)}">'
                f'<label for="user">{esc(t("web.user"))}</label>'
                f'<input id="user" name="user" autocomplete="username" autofocus required>'
                f'<label for="password">{esc(t("web.password"))}</label>'
                f'<input id="password" name="password" type="password" '
                f'autocomplete="current-password" required>'
                f'{error}<button type="submit">{esc(t("web.sign_in"))}</button></form>')
        return self.shell("", t("web.sign_in"), body, logged_in=False, t=t)

    def sign_in(self, form: dict, address: str, t=None
                ) -> tuple[int, str, bytes, str | None]:
        """``(status, content type, body, new session token)`` for POST /login."""
        t = t or self.t
        target = safe_target((form.get("next") or ["/"])[0])
        waiting = self.logins.locked_for(address)
        if waiting > 0:
            log.warning("login refused for %s: too many failures", address)
            return (HTTPStatus.TOO_MANY_REQUESTS, "text/html; charset=utf-8",
                    self.login_page(t("web.too_many", seconds=int(waiting) + 1), target, t),
                    None)
        user = (form.get("user") or [""])[0]
        password = (form.get("password") or [""])[0]
        account = self.account_of(user)
        if account is None or not verify_password(password, account.hash):
            self.logins.failed(address)
            reason = "no such account" if account is None else "wrong password"
            log.warning("failed login for %r from %s: %s", user[:40], address, reason)
            return (HTTPStatus.UNAUTHORIZED, "text/html; charset=utf-8",
                    self.login_page(t("web.bad_login"), target, t), None)
        self.logins.succeeded(address)
        log.info("%s signed in from %s", user, address)
        where = "/password" if account.must_change else target
        return HTTPStatus.SEE_OTHER, where, b"", self.sessions.open(user)

    # ----------------------------------------------------------------- password

    def password_page(self, user: str, message: str = "", t=None) -> bytes:
        """Where a reader chooses their own password; the only form that writes anything."""
        t = t or self.t
        account = self.account_of(user)
        if account is not None and account.from_file:
            body = f'<p class="empty">{esc(t("web.password.from_file"))}</p>'
            return self.shell("", t("web.password.title"), body, t=t)
        forced = t("web.password.forced") if account is not None and account.must_change else ""
        error = f'<p class="error">{esc(message)}</p>' if message else ""
        body = (f'<form class="login" method="post" action="/password">'
                f'<label for="current">{esc(t("web.password.current"))}</label>'
                f'<input id="current" name="current" type="password" '
                f'autocomplete="current-password" autofocus required>'
                f'<label for="new">{esc(t("web.password.new"))}</label>'
                f'<input id="new" name="new" type="password" '
                f'autocomplete="new-password" required>'
                f'<label for="again">{esc(t("web.password.again"))}</label>'
                f'<input id="again" name="again" type="password" '
                f'autocomplete="new-password" required>'
                f'<p class="note">{esc(t("web.password.rule", min=MIN_LENGTH))}</p>'
                f'{error}<button type="submit">{esc(t("web.password.save"))}</button></form>')
        return self.shell("", t("web.password.title"), body, forced, t=t)

    def change_password(self, user: str, form: dict, t=None, address: str = ""
                        ) -> tuple[int, str, bytes]:
        """``(status, content type or target, body)`` for POST /password.

        The current password is asked for again: a session left open on an unlocked screen
        must not be enough to take the account over.
        """
        t = t or self.t
        account = self.account_of(user)
        if account is None or account.from_file:
            return (HTTPStatus.OK, "text/html; charset=utf-8",
                    self.password_page(user, t=t))
        waiting = self.logins.locked_for(address) if address else 0.0
        if waiting > 0:
            return (HTTPStatus.TOO_MANY_REQUESTS, "text/html; charset=utf-8",
                    self.password_page(user, t("web.too_many", seconds=int(waiting) + 1), t))
        current = (form.get("current") or [""])[0]
        if not verify_password(current, account.hash):
            if address:
                self.logins.failed(address)
            log.warning("%s gave the wrong current password from %s", user, address or "?")
            return (HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8",
                    self.password_page(user, t("web.password.wrong"), t))
        new = (form.get("new") or [""])[0]
        again = (form.get("again") or [""])[0]
        if len(new) < MIN_LENGTH:
            return (HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8",
                    self.password_page(user, t("web.password.rule", min=MIN_LENGTH), t))
        if new != again:
            return (HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8",
                    self.password_page(user, t("web.password.mismatch"), t))
        self.set_password(user, new)
        if address:
            self.logins.succeeded(address)
        log.info("%s changed their password", user)
        return HTTPStatus.SEE_OTHER, "/", b""

    def must_change(self, user: str | None) -> bool:
        account = self.account_of(user) if user else None
        return bool(account and account.must_change)

    def translator(self, lang: str | None) -> Translator:
        """The language of this request: the reader's choice, else the configured one."""
        return Translator(lang) if lang in LANGUAGES else self.t

    def state(self) -> Repo:
        """A fresh read-only connection: every page sees the state as it is now."""
        return Repo(open_db(self.loaded.paths.state_file, readonly=True))

    # ----------------------------------------------------------------- rendering

    def shell(self, active: str, title: str, body: str, subtitle: str = "",
              logged_in: bool = True, t=None, refresh: int = 0) -> bytes:
        t = t or self.t
        pages_shown = (*NAV, SNMP_PAGE) if self.manageable else NAV
        nav = "".join(
            '<a href="{}" class="{}">{}</a>'.format(
                page.path, "on" if page.path == active else "", esc(t(page.label_key)))
            for page in pages_shown) if logged_in else ""
        tools = (f'<button type="button" id="theme" class="icon" '
                 f'title="{esc(t("web.theme"))}" aria-label="{esc(t("web.theme"))}"></button>'
                 + "".join(
                     '<a class="lang{}" href="?lang={}">{}</a>'.format(
                         " on" if code == t.lang else "", code, code.upper())
                     for code in LANGUAGES))
        if logged_in and self.guarded:
            tools += (f'<a class="lang" href="/password">{esc(t("web.password"))}</a>'
                      f'<form class="out" method="post" action="/logout">'
                      f'<button type="submit">{esc(t("web.sign_out"))}</button></form>')
        nav += f'<span class="tools">{tools}</span>'
        return f"""<!doctype html>
<html lang="{t.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""}
<title>{esc(title)} — snowth_my_net</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <a class="brand" href="/">snowth_my_net</a>
  <nav>{nav}</nav>
</header>
<main>
  <h1>{esc(title)}</h1>
  <p class="subtitle">{esc(subtitle)}</p>
  {body}
</main>
<footer>{esc(t("web.read_only"))} · {esc(t("web.times", zone=local_zone()))}
 · snowth_my_net {esc(__version__)}</footer>
<script src="/static/app.js"></script>
</body>
</html>
""".encode()

    def table_page(self, active: str, title: str, table: pages.Table, subtitle: str,
                   link_first: str = "", t=None, link_column: int = 0, before: str = "",
                   refresh: int = 0, disagreeing_only: bool = False) -> bytes:
        t = t or self.t
        if not table.rows:
            return self.shell(active, title, before + f'<p class="empty">{esc(table.empty)}</p>',
                              subtitle, t=t, refresh=refresh)
        keys = table.keys or [None] * len(table.columns)
        classes = [f"{kind} col-{key}" if key else kind
                   for (_label, kind), key in zip(table.columns, keys, strict=True)]
        head = "".join(f'<th class="{css}"><button type="button">{esc(label)}'
                       '<span class="arrow"></span></button></th>'
                       for (label, _kind), css in zip(table.columns, classes, strict=True))
        body = []
        for row in table.rows:
            cells = []
            for index, (value, kind) in enumerate(zip(row, classes, strict=True)):
                title = ""
                if isinstance(value, Cell | Editable):
                    main, note = value.text, getattr(value, "note", "")
                    title = getattr(value, "title", "")
                else:
                    main, note = str(value), ""
                if isinstance(value, Editable):
                    cells.append(f'<td class="{kind} write">'
                                 f'{self.name_field(value, t)}</td>')
                    continue
                text = esc(main)
                if index == link_column and link_first and main:
                    text = f'<a href="{link_first}{quote(main, safe=":")}">{text}</a>'
                if note:
                    text += f' <span class="note">{esc(note)}</span>'
                more = getattr(value, "more", ())
                if more:
                    items = "".join(f"<li>{esc(one)}</li>" for one in more)
                    text += (f'<details class="more"><summary>+{len(more)}</summary>'
                             f"<ul>{items}</ul></details>")
                hover = f' title="{esc(title)}"' if title else ""
                tone = f" {value.tone}" if getattr(value, "tone", "") else ""
                cells.append(f'<td class="{kind}{tone}"{hover}>{text}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        shown = len(table.rows)
        count = t("web.count", total=table.total)
        if shown < table.total:
            count = (t("web.shown", shown=shown, total=table.total) + " · "
                     + t("web.truncated", limit=shown))
        hints = "".join(f"<dt>{esc(label)}</dt><dd>{esc(text)}</dd>"
                        for label, text in table.help)
        panel = (f'<details class="hint"><summary>{esc(t("web.how"))}</summary>'
                 f"<dl>{hints}</dl></details>") if table.help else ""
        warning = ""
        if table.disagreeing:
            where = "/nodes" if disagreeing_only else "/nodes?disagree=1"
            label = t("web.disagree.all") if disagreeing_only else t("web.disagree.show")
            warning = (f'<p class="disagree">{esc(t("web.disagree", count=table.disagreeing))} '
                       f'<a href="{where}">{esc(label)}</a></p>')
        views = "".join(
            '<a class="view{}" href="{}">{}</a>'.format(" on" if active else "", href,
                                                        esc(label))
            for label, href, active in table.views)
        # The chooser and the drag handles are the browser's work; the page only names them,
        # and stays whole without a script (hidden until one fills it).
        columns = (f'<details class="cols" id="cols" hidden>'
                   f'<summary>{esc(t("web.columns"))}</summary>'
                   f'<div class="pick"><button type="button" class="reset">'
                   f'{esc(t("web.columns.reset"))}</button></div>'
                   f"</details>")
        controls = (f'<div class="bar"><input type="search" id="q" '
                    f'placeholder="{esc(t("web.search"))}" aria-label="{esc(t("web.search"))}">'
                    f'<span class="count" id="count">{esc(count)}</span>'
                    f'{columns}<span class="views">{views}</span></div>'
                    + (f'<p class="note">{esc(table.note)}</p>' if table.note else ""))
        table_html = (f'<div class="wrap"><table id="rows"><thead><tr>{head}</tr></thead>'
                      f'<tbody>{"".join(body)}</tbody></table></div>')
        return self.shell(active, title, before + warning + panel + controls + table_html,
                          subtitle, t=t, refresh=refresh)

    def actions_panel(self, t, message: str = "") -> str:
        """The buttons above the runs, and what the last one did."""
        if not self.loaded.cfg.web.actions:
            return ""
        now = self.clock.now()
        current = self.jobs.current
        busy = "" if current is None else " disabled"
        buttons = "".join(
            f'<button type="submit" name="what" value="{what}"{busy}>'
            f'{esc(t(f"web.do.{what}"))}</button>'
            for what in ACTIONS if what != "push" or self.loaded.cfg.push.targets)
        state = ""
        if current is not None:
            said = t("web.do.running", what=t(f"web.do.{current.what}"),
                     seconds=current.seconds(now))
            state = f'<p class="state running">{esc(said)}</p>'
        elif self.jobs.last is not None:
            last = self.jobs.last
            said = t("web.do.last", what=t(f"web.do.{last.what}"),
                     status=t(f"web.do.{last.status}"), seconds=last.seconds(now),
                     detail=last.summary or "-")
            state = f'<p class="state {esc(last.status)}">{esc(said)}</p>'
        error = f'<p class="error">{esc(message)}</p>' if message else ""
        return (f'<form class="actions" method="post" action="/action">'
                f'<span class="what">{esc(t("web.do.title"))}</span>{buttons}'
                f'<span class="note">{esc(t("web.do.hint"))}</span>{state}{error}</form>')

    def start_job(self, what: str, user: str, t=None) -> tuple[int, str, bytes]:
        """``(status, target, body)`` for POST /action: start it, then show the runs."""
        t = t or self.t
        if not self.loaded.cfg.web.actions or what not in ACTIONS:
            return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        if self.jobs.start(what, user) is None:
            return (HTTPStatus.CONFLICT, "text/html; charset=utf-8",
                    self.runs_page(t, t("web.do.busy")))
        return HTTPStatus.SEE_OTHER, "/runs", b""

    def runs_page(self, t=None, message: str = "") -> bytes:
        t = t or self.t
        with closing(self.state()) as repo:
            table = pages.runs(repo, t)
            subtitle = pages.summary(self.loaded, repo, self.clock.now(), t)
        # While something runs, the page comes back on its own: no button to press to see it end.
        refresh = 5 if self.jobs.current is not None else 0
        return self.table_page("/runs", t("tab.runs"), table, subtitle, "", t, 0,
                               before=self.actions_panel(t, message), refresh=refresh)

    # ----------------------------------------------------------------- SNMP connections

    def confirm_page(self, t, message: str = "") -> bytes:
        """The password again, before anything that changes what the tool talks to."""
        error = f'<p class="error">{esc(message)}</p>' if message else ""
        body = (f'<form class="login" method="post" action="/confirm">'
                f'<p class="note">{esc(t("web.snmp.locked"))}</p>'
                f'<label for="password">{esc(t("web.password"))}</label>'
                f'<input id="password" name="password" type="password" '
                f'autocomplete="current-password" autofocus required>'
                f'{error}<button type="submit">{esc(t("web.snmp.open"))}</button></form>')
        return self.shell("/snmp", t("web.snmp.title"), body, t=t)

    def snmp_page(self, t=None, message: str = "", tone: str = "") -> bytes:
        t = t or self.t
        names = snmp.credential_names(self.loaded)
        with closing(self.state()) as repo:
            rows = snmp.connections(self.loaded, repo)
        body = [f'<p class="intro">{esc(t("web.snmp.intro"))}</p>']
        if message:
            body.append(f'<p class="state {esc(tone or "ok")}">{esc(message)}</p>')
        body.append(
            f'<form class="actions" method="post" action="/snmp">'
            f'<input type="hidden" name="do" value="add">'
            f'<span class="what">{esc(t("web.snmp.add"))}</span>'
            f'<input name="address" placeholder="192.0.2.42" required>'
            f'<button type="submit">{esc(t("web.snmp.add"))}</button>'
            f'<span class="note">{esc(t("web.snmp.credentials_from", count=len(names)))}</span>'
            f"</form>")
        head = "".join(f"<th>{esc(t(key)) if key else ''}</th>" for key in
                       ("col.address", "col.name", "col.origin", "col.credential",
                        "col.status", "col.failures", ""))
        lines = []
        for row in rows:
            chosen = "".join(
                f'<option value="{esc(name)}"{" selected" if name == row.credential else ""}>'
                f"{esc(name)}</option>" for name in names)
            tone_class = {"ok": "", "failed": " bad", "never": " bad"}[row.status]
            detail = f' <span class="note">{esc(row.error)}</span>' if row.error else ""
            lines.append(
                f"<tr><td>{esc(row.host)}</td><td>{esc(row.device_name)}</td>"
                f"<td>{esc(row.origin)}</td>"
                f'<td><form class="inline" method="post" action="/snmp">'
                f'<input type="hidden" name="do" value="credential">'
                f'<input type="hidden" name="address" value="{esc(row.host)}">'
                f'<select name="credential">'
                f'<option value="">{esc(t("web.snmp.any"))}</option>{chosen}</select>'
                f'<button type="submit">{esc(t("web.snmp.save"))}</button></form></td>'
                f'<td class="text{tone_class}">{esc(row.status)}{detail}</td>'
                f"<td>{row.failures}</td>"
                f'<td class="doing">'
                f'<form class="inline" method="post" action="/snmp">'
                f'<input type="hidden" name="do" value="test">'
                f'<input type="hidden" name="address" value="{esc(row.host)}">'
                f'<button type="submit">{esc(t("web.snmp.test"))}</button></form>'
                f'<form class="inline" method="post" action="/snmp">'
                f'<input type="hidden" name="do" value="remove">'
                f'<input type="hidden" name="address" value="{esc(row.host)}">'
                f'<button type="submit">{esc(t("web.snmp.remove"))}</button></form></td></tr>')
        body.append(f'<div class="wrap"><table class="plain"><thead><tr>{head}</tr></thead>'
                    f'<tbody>{"".join(lines)}</tbody></table></div>')
        body.append(
            f'<details class="danger"><summary>{esc(t("web.snmp.forget"))}</summary>'
            f'<p class="note">{esc(t("web.snmp.forget_why"))}</p>'
            f'<form method="post" action="/snmp">'
            f'<input type="hidden" name="do" value="forget">'
            f'<button type="submit">{esc(t("web.snmp.forget_do"))}</button></form></details>')
        return self.shell("/snmp", t("web.snmp.title"), "".join(body), t=t)

    def confirm(self, user: str, password: str, token: str | None, address: str, t=None
                ) -> tuple[int, str, bytes]:
        """POST /confirm: the password again, counted by the same limiter as a login."""
        t = t or self.t
        waiting = self.logins.locked_for(address)
        if waiting > 0:
            return (HTTPStatus.TOO_MANY_REQUESTS, "text/html; charset=utf-8",
                    self.confirm_page(t, t("web.too_many", seconds=int(waiting) + 1)))
        account = self.account_of(user)
        if account is None or not verify_password(password, account.hash):
            self.logins.failed(address)
            log.warning("failed confirmation for %r from %s", user[:40], address)
            return (HTTPStatus.UNAUTHORIZED, "text/html; charset=utf-8",
                    self.confirm_page(t, t("web.bad_login")))
        self.logins.succeeded(address)
        self.sessions.confirm(token)
        log.info("%s opened the SNMP page from %s", user, address)
        return HTTPStatus.SEE_OTHER, "/snmp", b""

    def manage_snmp(self, form: dict, user: str, t=None) -> tuple[int, str, bytes]:
        """``(status, target or content type, body)`` for POST /snmp."""
        t = t or self.t
        what = (form.get("do") or [""])[0]
        address = (form.get("address") or [""])[0]
        if what not in snmp.ACTIONS:
            return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        try:
            if what == "test":
                host = normalize_address(address)
                if self.jobs.start("collect", user, extra=("--device", host)) is None:
                    return self._snmp_answer(t, t("web.do.busy"), "failed")
                return self._snmp_answer(t, t("web.snmp.testing", address=host))
            with closing(self.state_rw()) as repo:
                now = self.clock.now()
                if what == "add":
                    host = snmp.add_target(repo, address, now)
                    said = t("web.snmp.added", address=host)
                elif what == "remove":
                    host = snmp.remove_target(repo, address)
                    said = t("web.snmp.removed", address=host)
                elif what == "forget":
                    counts = repo.forget_nodes()
                    log.warning("the MAC and ARP memory was emptied from the web interface "
                                "by %s: %s + %s rows", user or "an anonymous reader",
                                counts["fdb"], counts["arp"])
                    said = t("web.snmp.forgotten", fdb=counts["fdb"], arp=counts["arp"])
                else:
                    name = (form.get("credential") or [""])[0]
                    chosen = snmp.set_credential(self.loaded, repo, address, name, now)
                    said = f"{normalize_address(address)}: {chosen or t('web.snmp.any')}"
        except ManualError as exc:
            return self._snmp_answer(t, str(exc), "failed")
        log.info("snmp: %s %s by %s", what, address, user or "an anonymous reader")
        return self._snmp_answer(t, said)

    def _snmp_answer(self, t, message: str, tone: str = "ok") -> tuple[int, str, bytes]:
        status = HTTPStatus.OK if tone == "ok" else HTTPStatus.BAD_REQUEST
        return status, "text/html; charset=utf-8", self.snmp_page(t, message, tone)

    def state_rw(self) -> Repo:
        """A writing connection, for the few things this page changes (never the inventory)."""
        return Repo(open_db(self.loaded.paths.state_file))

    def node_page(self, mac: str, t=None, message: str = "") -> bytes:
        t = t or self.t
        with closing(self.state()) as repo:
            lines = pages.explain_lines(self.loaded, repo, self.clock.now(), mac, t)
        rendered = "\n".join(
            f'<span class="{kind}">{esc(text)}</span>' if text else "" for text, kind in lines)
        body = (f'<p><a class="back" href="/nodes">← {esc(t("web.back"))}</a></p>'
                f'{self.name_form(mac, t, message)}'
                f'<pre class="explain">{rendered}</pre>')
        return self.shell("/nodes", t("web.node_title", mac=mac), body, t=t)

    def name_field(self, cell: Editable, t) -> str:
        """The same form as on the MAC's own page, in the cell: a name is one keystroke away.

        A real form, so that it works with no script at all; app.js sends it without reloading.
        """
        label = esc(t(f"web.{cell.field}.title"))
        return (f'<form class="cell" method="post" action="/name">'
                f'<input type="hidden" name="mac" value="{esc(cell.key)}">'
                f'<input type="hidden" name="field" value="{esc(cell.field)}">'
                f'<input name="name" value="{esc(cell.text)}" '
                f'maxlength="{MAX_LENGTH[cell.field]}" '
                f'aria-label="{label}" title="{label}" autocomplete="off"></form>')

    def name_form(self, mac: str, t, message: str = "") -> str:
        """Naming a MAC is the one thing a reader may write, and it is theirs, not collected."""
        error = f'<p class="error">{esc(message)}</p>' if message else ""
        try:
            given = self.labels.get(clean_mac(mac))
        except NameError_:
            return error         # nothing to name here, but the reason must still be readable
        return (f'<form class="rename" method="post" action="/name">'
                f'<input type="hidden" name="mac" value="{esc(mac)}">'
                f'<label for="given">{esc(t("web.name.title"))}</label>'
                f'<input id="given" name="name" value="{esc(given)}" maxlength="{MAX_LENGTH}" '
                f'placeholder="{esc(t("web.name.placeholder"))}">'
                f'<button type="submit">{esc(t("web.name.save"))}</button>'
                f'<span class="note">{esc(t("web.name.hint"))} '
                f'{esc(t("web.name.empty_clears"))}</span>{error}</form>')

    def set_name(self, mac: str, name: str, t=None, as_json: bool = False,
                 field: str = "name") -> tuple[int, str, bytes]:
        """``(status, content type or target, body)`` for POST /name.

        ``as_json`` answers the table's own script, which saves a cell without reloading the
        page; the plain form answer is a redirect, so the page works with no script at all.
        """
        t = t or self.t
        try:
            stored = clean_mac(mac)
            with self.writing:
                given = self.labels.set(stored, name, field)
        except NameError_ as exc:
            if as_json:
                return (HTTPStatus.BAD_REQUEST, JSON,
                        json.dumps({"error": str(exc)}).encode())
            return (HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8",
                    self.node_page(mac, t, str(exc)))
        log.info("node %s: %s = %r", stored, field, given)
        if as_json:
            return HTTPStatus.OK, JSON, json.dumps({"mac": stored, "name": given,
                                                    "field": field}).encode()
        return HTTPStatus.SEE_OTHER, "/node?mac=" + quote(stored, safe=":"), b""

    # ----------------------------------------------------------------- routing

    def respond(self, path: str, query: dict, token: str | None = None,
                lang: str | None = None) -> tuple[int, str, bytes]:
        """``(status, content type, body)`` for a GET; never touches the state otherwise."""
        t = self.translator(lang)
        now = self.clock.now()
        html_type = "text/html; charset=utf-8"
        if path.startswith("/static/"):
            return self.asset(path.removeprefix("/static/"))
        if path == "/healthz":
            return HTTPStatus.OK, "text/plain; charset=utf-8", b"ok\n"
        if self.guarded and self.sessions.user_of(token) is None:
            if path == "/login":
                return HTTPStatus.OK, html_type, self.login_page(t=t)
            target = path + (("?" + "&".join(f"{k}={v[0]}" for k, v in query.items()))
                             if query else "")
            return HTTPStatus.SEE_OTHER, "/login?next=" + quote(safe_target(target), safe=""), b""
        if path == "/login":
            return HTTPStatus.SEE_OTHER, "/", b""       # already signed in
        who = self.sessions.user_of(token)
        if path == "/snmp":
            if not self.manageable:
                return (HTTPStatus.NOT_FOUND, html_type,
                        self.shell("/", t("web.not_found"), "", t=t))
            if not self.sessions.confirmed(token):
                return HTTPStatus.OK, html_type, self.confirm_page(t)
            return HTTPStatus.OK, html_type, self.snmp_page(t)
        if path == "/password":
            if not self.guarded:
                return (HTTPStatus.NOT_FOUND, html_type,
                        self.shell("/", t("web.not_found"), "", t=t))
            return HTTPStatus.OK, html_type, self.password_page(who, t=t)
        if self.must_change(who):                       # nothing else until it is chosen
            return HTTPStatus.SEE_OTHER, "/password", b""
        if path.startswith("/download/"):
            return self.download(path.removeprefix("/download/"))
        if path == "/node":
            mac = (query.get("mac") or [""])[0]
            return HTTPStatus.OK, html_type, self.node_page(mac, t)
        if path not in {page.path for page in NAV}:
            return (HTTPStatus.NOT_FOUND, html_type,
                    self.shell("/", t("web.not_found"), "", t=t))
        if path == "/runs":
            return HTTPStatus.OK, html_type, self.runs_page(t)
        with closing(self.state()) as repo:
            subtitle = pages.summary(self.loaded, repo, now, t)
            if path == "/":
                table = pages.devices(self.loaded, repo, now, t)
                title = t("tab.devices")
            elif path == "/nodes":
                table = pages.nodes(self.loaded, repo, now, t, self.loaded.cfg.web.node_limit,
                                    live_only=bool(query.get("live")),
                                    disagreeing_only=bool(query.get("disagree")))
                title = t("tab.nodes")
            elif path == "/links":
                table = pages.links(self.loaded, repo, now, t)
                title = t("tab.links")
            else:
                table = pages.files(self.loaded.paths.output_dir, t)
                title = t("web.tab.files")
        link = "/node?mac=" if path == "/nodes" else ("/download/" if path == "/files" else "")
        column = 4 if path == "/nodes" else 0    # the MAC: three hostnames and a description first
        return (HTTPStatus.OK, html_type,
                self.table_page(path, title, table, subtitle, link, t, column,
                                disagreeing_only=bool(query.get("disagree"))))

    def asset(self, name: str) -> tuple[int, str, bytes]:
        if name not in ASSETS:
            return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        data = resources.files("snowth_my_net.web.assets").joinpath(name).read_bytes()
        return HTTPStatus.OK, ASSETS[name], data

    def download(self, name: str) -> tuple[int, str, bytes]:
        """One of the exported files, by name only: no path is ever taken from the request."""
        if name not in pages.DOWNLOADS:
            return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        path = self.loaded.paths.output_dir / name
        try:
            data = path.read_bytes()
        except OSError:
            return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
        return HTTPStatus.OK, CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream"), data


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def safe_target(target: str) -> str:
    """Only a path of this site: never redirect a browser somewhere else after a login."""
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def load_accounts(loaded: LoadedConfig) -> dict[str, str]:
    """``{user: password hash}`` for the accounts whose password comes from a file or the
    environment; an unreadable one is refused, not silently skipped. Every other account keeps
    its password in the store, where the tool itself writes it."""
    from snowth_my_net.config.secrets import SecretError, resolve_secret
    from snowth_my_net.config.validate import ConfigError

    accounts, errors = {}, []
    for user in loaded.cfg.web.auth.users:
        if not (user.password_file or user.password_env):
            continue                     # its password lives in the store, written by the tool
        try:
            secret, warnings = resolve_secret(user.password_file, user.password_env,
                                              loaded.paths.secrets_dir,
                                              f"web user '{user.name}' password")
        except SecretError as exc:
            errors.append(str(exc))
            continue
        for warning in warnings:
            log.warning("%s", warning)
        value = secret.reveal()
        if parse_hash(value) is None:
            errors.append(f"web user '{user.name}': the password source does not hold a hash "
                          "produced by 'snowth_my_net web --hash-password' (one line starting "
                          f"with '{SCHEME}$', nothing else)")
            continue
        accounts[user.name] = value
    if errors:
        raise ConfigError(errors)
    return accounts


class closing:
    """``contextlib.closing`` for a Repo, which closes its connection."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    def __enter__(self) -> Repo:
        return self.repo

    def __exit__(self, *exc: object) -> None:
        self.repo.conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = f"snowth_my_net/{__version__}"
    sys_version = ""                       # do not advertise the Python version
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:              # name imposed by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        cookies = self.headers.get("Cookie")
        token = parse_cookie(cookies)
        query = parse_qs(parsed.query)
        chosen = (query.pop("lang", [""]) or [""])[0]
        if chosen in LANGUAGES:            # the reader picked a language: remember it
            rest = "&".join(f"{k}={v[0]}" for k, v in query.items())
            self.finish_response(HTTPStatus.SEE_OTHER,
                                 parsed.path + (f"?{rest}" if rest else ""), b"",
                                 lang_cookie=chosen)
            return
        try:
            status, content_type, body = self.server.site.respond(
                parsed.path, query, token, parse_cookie(cookies, LANG_COOKIE))
        except StateError as exc:
            status, content_type = HTTPStatus.SERVICE_UNAVAILABLE, "text/plain; charset=utf-8"
            body = f"{exc}\n".encode()
        except Exception:                  # a bug must not kill the server thread
            log.exception("%s failed", parsed.path)
            status, content_type = HTTPStatus.INTERNAL_SERVER_ERROR, "text/plain; charset=utf-8"
            body = b"internal error; see the logs\n"
        self.finish_response(status, content_type, body)

    def do_POST(self) -> None:             # name imposed by BaseHTTPRequestHandler
        """Only the login and logout forms; every page itself stays a GET."""
        site = self.server.site
        parsed = urlparse(self.path)
        token = parse_cookie(self.headers.get("Cookie"))
        if parsed.path not in ("/login", "/logout", "/password", "/name", "/action",
                               "/snmp", "/confirm"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path in ("/snmp", "/confirm"):
            self.manage(parsed.path, token)
            return
        if parsed.path not in ("/name", "/action") and not site.guarded:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path in ("/name", "/action") and site.guarded and (
                site.sessions.user_of(token) is None):
            if "application/json" in (self.headers.get("Accept") or ""):
                self.finish_response(HTTPStatus.UNAUTHORIZED, JSON,
                                     json.dumps({"error": "sign in again"}).encode())
                return
            self.finish_response(HTTPStatus.SEE_OTHER, "/login", b"")
            return
        form = self.read_form()
        if parsed.path == "/logout":
            site.sessions.close(token)
            self.finish_response(HTTPStatus.SEE_OTHER, "/login", b"", clear_cookie=True)
            return
        lang = site.translator(parse_cookie(self.headers.get("Cookie"), LANG_COOKIE))
        if parsed.path == "/action":
            status, where, body = site.start_job((form.get("what") or [""])[0],
                                                 site.sessions.user_of(token) or "", lang)
            self.finish_response(status, where, body)
            return
        if parsed.path == "/name":
            wants_json = "application/json" in (self.headers.get("Accept") or "")
            status, where, body = site.set_name((form.get("mac") or [""])[0],
                                                (form.get("name") or [""])[0], lang, wants_json,
                                                (form.get("field") or ["name"])[0])
            self.finish_response(status, where, body)
            return
        if parsed.path == "/password":
            user = site.sessions.user_of(token)
            if user is None:
                self.finish_response(HTTPStatus.SEE_OTHER, "/login", b"")
                return
            status, where, body = site.change_password(user, form, lang, self.caller())
            self.finish_response(status, where, body)
            return
        status, where, body, new_token = site.sign_in(form, self.caller(), lang)
        self.finish_response(status, where, body, set_cookie=new_token)

    def manage(self, path: str, token: str | None) -> None:
        """POST /confirm and POST /snmp: an account, its password again, then the change."""
        site = self.server.site
        lang = site.translator(parse_cookie(self.headers.get("Cookie"), LANG_COOKIE))
        user = site.sessions.user_of(token)
        if not site.manageable:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if user is None:
            self.finish_response(HTTPStatus.SEE_OTHER, "/login", b"")
            return
        form = self.read_form()
        if path == "/confirm":
            status, where, body = site.confirm(user, (form.get("password") or [""])[0],
                                               token, self.caller(), lang)
            self.finish_response(status, where, body)
            return
        if not site.sessions.confirmed(token):
            self.finish_response(HTTPStatus.SEE_OTHER, "/snmp", b"")   # ask again first
            return
        status, where, body = site.manage_snmp(form, user, lang)
        self.finish_response(status, where, body)

    def read_form(self) -> dict:
        length = min(int(self.headers.get("Content-Length") or 0), MAX_FORM_BYTES)
        if length <= 0:
            return {}
        return parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))

    def finish_response(self, status: int, content_type: str, body: bytes,
                        set_cookie: str | None = None, clear_cookie: bool = False,
                        lang_cookie: str | None = None) -> None:
        """A 303 puts the target in ``content_type``; anything else is a normal answer."""
        self.send_response(status)
        if status == HTTPStatus.SEE_OTHER:
            self.send_header("Location", content_type)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        else:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if set_cookie or clear_cookie:
            flags = "Path=/; HttpOnly; SameSite=Strict"
            if self.secure_request():
                flags += "; Secure"        # behind a TLS proxy the cookie never leaves it
            value = f"{COOKIE}={set_cookie}; {flags}" if set_cookie else (
                f"{COOKIE}=; Max-Age=0; {flags}")
            self.send_header("Set-Cookie", value)
        if lang_cookie:
            self.send_header("Set-Cookie", f"{LANG_COOKIE}={lang_cookie}; Path=/; Max-Age=31536000"
                                           "; SameSite=Lax")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_security_headers(self) -> None:
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'self'; script-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
                         "frame-ancestors 'none'")

    def caller(self) -> str:
        site = self.server.site
        return site.caller(self.address_string(), self.headers.get("X-Forwarded-For"))

    def secure_request(self) -> bool:
        """True when the reader's own connection was TLS, as a trusted proxy states it."""
        site = self.server.site
        return (self.headers.get("X-Forwarded-Proto") == "https"
                and site.trusts(self.address_string()))

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("%s %s", self.caller(), fmt % args)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], site: Site) -> None:
        super().__init__(address, Handler)
        self.site = site


def build(loaded: LoadedConfig, bind: str | None = None, port: int | None = None,
          clock: Clock | None = None) -> WebServer:
    cfg = loaded.cfg.web
    return WebServer((bind or cfg.bind, port if port is not None else cfg.port),
                     Site(loaded, clock))


def serve(loaded: LoadedConfig, bind: str | None = None, port: int | None = None) -> int:
    """Serve until interrupted. Returns the exit code."""
    server = build(loaded, bind, port)
    host, listening = server.server_address[:2]
    log.info("web interface on http://%s:%s (read-only; Ctrl+C to stop)", host, listening)
    if not server.site.guarded and str(host) not in LOOPBACK:
        log.warning("listening on %s with no account in web.auth.users: everyone who reaches "
                    "this address sees the whole inventory", host)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        server.shutdown()
        server.server_close()
    return 0
