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
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from snowth_my_net import __version__
from snowth_my_net.clock import Clock
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.i18n import Translator, detect_language
from snowth_my_net.logs import get_logger
from snowth_my_net.state.db import StateError, open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import pages
from snowth_my_net.web.auth import (
    COOKIE,
    SCHEME,
    LoginLimiter,
    Sessions,
    parse_cookie,
    parse_hash,
    verify_password,
)
from snowth_my_net.web.pages import Cell

LANGUAGES = ("en", "fr")
LANG_COOKIE = "snowth_lang"

log = get_logger("web")
ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
CONTENT_TYPES = {".csv": "text/csv; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".html": "text/html; charset=utf-8", ".dot": "text/plain; charset=utf-8",
                 ".mmd": "text/plain; charset=utf-8"}
MAX_FORM_BYTES = 4096


@dataclass(frozen=True)
class Page:
    path: str
    label_key: str


NAV = (Page("/", "tab.devices"), Page("/nodes", "tab.nodes"), Page("/links", "tab.links"),
       Page("/runs", "tab.runs"), Page("/files", "web.tab.files"))


class Site:
    """Everything a request needs; one instance is shared by the server threads."""

    def __init__(self, loaded: LoadedConfig, clock: Clock | None = None) -> None:
        self.loaded = loaded
        self.clock = clock or Clock()
        self.t = Translator(detect_language(loaded.cfg.general.language))
        self.accounts = load_accounts(loaded)
        self.sessions = Sessions(lifetime=loaded.cfg.web.auth.session_hours * 3600)
        self.logins = LoginLimiter()

    @property
    def guarded(self) -> bool:
        """True when accounts are configured: every page then needs a session."""
        return bool(self.accounts)

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
        stored = self.accounts.get(user)
        if stored is None or not verify_password(password, stored):
            self.logins.failed(address)
            reason = "no such account" if stored is None else "wrong password"
            log.warning("failed login for %r from %s: %s", user[:40], address, reason)
            return (HTTPStatus.UNAUTHORIZED, "text/html; charset=utf-8",
                    self.login_page(t("web.bad_login"), target, t), None)
        self.logins.succeeded(address)
        log.info("%s signed in from %s", user, address)
        return HTTPStatus.SEE_OTHER, target, b"", self.sessions.open(user)

    def translator(self, lang: str | None) -> Translator:
        """The language of this request: the reader's choice, else the configured one."""
        return Translator(lang) if lang in LANGUAGES else self.t

    def state(self) -> Repo:
        """A fresh read-only connection: every page sees the state as it is now."""
        return Repo(open_db(self.loaded.paths.state_file, readonly=True))

    # ----------------------------------------------------------------- rendering

    def shell(self, active: str, title: str, body: str, subtitle: str = "",
              logged_in: bool = True, t=None) -> bytes:
        t = t or self.t
        nav = "".join(
            '<a href="{}" class="{}">{}</a>'.format(
                page.path, "on" if page.path == active else "", esc(t(page.label_key)))
            for page in NAV) if logged_in else ""
        tools = (f'<button type="button" id="theme" class="icon" '
                 f'title="{esc(t("web.theme"))}" aria-label="{esc(t("web.theme"))}"></button>'
                 + "".join(
                     '<a class="lang{}" href="?lang={}">{}</a>'.format(
                         " on" if code == t.lang else "", code, code.upper())
                     for code in LANGUAGES))
        if logged_in and self.guarded:
            tools += (f'<form class="out" method="post" action="/logout">'
                      f'<button type="submit">{esc(t("web.sign_out"))}</button></form>')
        nav += f'<span class="tools">{tools}</span>'
        return f"""<!doctype html>
<html lang="{t.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
<footer>{esc(t("web.read_only"))} · snowth_my_net {esc(__version__)}</footer>
<script src="/static/app.js"></script>
</body>
</html>
""".encode()

    def table_page(self, active: str, title: str, table: pages.Table, subtitle: str,
                   link_first: str = "", t=None) -> bytes:
        t = t or self.t
        if not table.rows:
            return self.shell(active, title, f'<p class="empty">{esc(table.empty)}</p>',
                              subtitle, t=t)
        head = "".join(f'<th class="{kind}"><button type="button">{esc(label)}'
                       '<span class="arrow"></span></button></th>'
                       for label, kind in table.columns)
        body = []
        for row in table.rows:
            cells = []
            for index, (value, (_label, kind)) in enumerate(zip(row, table.columns,
                                                                strict=True)):
                main = value.text if isinstance(value, Cell) else str(value)
                note = value.note if isinstance(value, Cell) else ""
                text = esc(main)
                if index == 0 and link_first and main:
                    text = f'<a href="{link_first}{quote(main, safe=":")}">{text}</a>'
                if note:
                    text += f' <span class="note">{esc(note)}</span>'
                cells.append(f'<td class="{kind}">{text}</td>')
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
        controls = (f'<div class="bar"><input type="search" id="q" '
                    f'placeholder="{esc(t("web.search"))}" aria-label="{esc(t("web.search"))}">'
                    f'<span class="count" id="count">{esc(count)}</span></div>')
        table_html = (f'<div class="wrap"><table id="rows"><thead><tr>{head}</tr></thead>'
                      f'<tbody>{"".join(body)}</tbody></table></div>')
        return self.shell(active, title, panel + controls + table_html, subtitle, t=t)

    def node_page(self, mac: str, t=None) -> bytes:
        t = t or self.t
        with closing(self.state()) as repo:
            lines = pages.explain_lines(self.loaded, repo, self.clock.now(), mac, t)
        rendered = "\n".join(
            f'<span class="{kind}">{esc(text)}</span>' if text else "" for text, kind in lines)
        body = (f'<p><a class="back" href="/nodes">← {esc(t("web.back"))}</a></p>'
                f'<pre class="explain">{rendered}</pre>')
        return self.shell("/nodes", t("web.node_title", mac=mac), body, t=t)

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
        if path.startswith("/download/"):
            return self.download(path.removeprefix("/download/"))
        if path == "/node":
            mac = (query.get("mac") or [""])[0]
            return HTTPStatus.OK, html_type, self.node_page(mac, t)
        if path not in {page.path for page in NAV}:
            return (HTTPStatus.NOT_FOUND, html_type,
                    self.shell("/", t("web.not_found"), "", t=t))
        with closing(self.state()) as repo:
            subtitle = pages.summary(self.loaded, repo, now, t)
            if path == "/":
                table = pages.devices(self.loaded, repo, now, t)
                title = t("tab.devices")
            elif path == "/nodes":
                table = pages.nodes(self.loaded, repo, now, t, self.loaded.cfg.web.node_limit)
                title = t("tab.nodes")
            elif path == "/links":
                table = pages.links(self.loaded, repo, now, t)
                title = t("tab.links")
            elif path == "/runs":
                table = pages.runs(repo, t)
                title = t("tab.runs")
            else:
                table = pages.files(self.loaded.paths.output_dir, t)
                title = t("web.tab.files")
        link = "/node?mac=" if path == "/nodes" else ("/download/" if path == "/files" else "")
        return (HTTPStatus.OK, html_type,
                self.table_page(path, title, table, subtitle, link, t))

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
    """``{user: password hash}``; an unreadable account is refused, not silently skipped."""
    from snowth_my_net.config.secrets import SecretError, resolve_secret
    from snowth_my_net.config.validate import ConfigError

    accounts, errors = {}, []
    for user in loaded.cfg.web.auth.users:
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
        if parsed.path not in ("/login", "/logout") or not site.guarded:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        form = self.read_form()
        if parsed.path == "/logout":
            site.sessions.close(token)
            self.finish_response(HTTPStatus.SEE_OTHER, "/login", b"", clear_cookie=True)
            return
        status, where, body, new_token = site.sign_in(
            form, self.address_string(),
            site.translator(parse_cookie(self.headers.get("Cookie"), LANG_COOKIE)))
        self.finish_response(status, where, body, set_cookie=new_token)

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
            if self.headers.get("X-Forwarded-Proto") == "https":
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
                         "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), fmt % args)


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
