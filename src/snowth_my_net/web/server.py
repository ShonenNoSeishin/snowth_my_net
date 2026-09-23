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

log = get_logger("web")
ASSETS = {"style.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
CONTENT_TYPES = {".csv": "text/csv; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".html": "text/html; charset=utf-8", ".dot": "text/plain; charset=utf-8",
                 ".mmd": "text/plain; charset=utf-8"}
DOWNLOAD_CHUNK = 64 * 1024


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

    def state(self) -> Repo:
        """A fresh read-only connection: every page sees the state as it is now."""
        return Repo(open_db(self.loaded.paths.state_file, readonly=True))

    # ----------------------------------------------------------------- rendering

    def shell(self, active: str, title: str, body: str, subtitle: str = "") -> bytes:
        t = self.t
        nav = "".join(
            '<a href="{}" class="{}">{}</a>'.format(
                page.path, "on" if page.path == active else "", esc(t(page.label_key)))
            for page in NAV)
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
                   link_first: str = "") -> bytes:
        t = self.t
        if not table.rows:
            return self.shell(active, title, f'<p class="empty">{esc(table.empty)}</p>',
                              subtitle)
        head = "".join(f'<th class="{kind}"><button type="button">{esc(label)}'
                       '<span class="arrow"></span></button></th>'
                       for label, kind in table.columns)
        body = []
        for row in table.rows:
            cells = []
            for index, (value, (_label, kind)) in enumerate(zip(row, table.columns,
                                                                strict=True)):
                text = esc(value)
                if index == 0 and link_first and value:
                    text = f'<a href="{link_first}{quote(value, safe=":")}">{text}</a>'
                cells.append(f'<td class="{kind}">{text}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        shown = len(table.rows)
        count = t("web.count", total=table.total)
        if shown < table.total:
            count = (t("web.shown", shown=shown, total=table.total) + " · "
                     + t("web.truncated", limit=shown))
        controls = (f'<div class="bar"><input type="search" id="q" '
                    f'placeholder="{esc(t("web.search"))}" aria-label="{esc(t("web.search"))}">'
                    f'<span class="count" id="count">{esc(count)}</span></div>')
        table_html = (f'<div class="wrap"><table id="rows"><thead><tr>{head}</tr></thead>'
                      f'<tbody>{"".join(body)}</tbody></table></div>')
        return self.shell(active, title, controls + table_html, subtitle)

    def node_page(self, mac: str) -> bytes:
        t = self.t
        with closing(self.state()) as repo:
            lines = pages.explain_lines(self.loaded, repo, self.clock.now(), mac, t)
        rendered = "\n".join(
            f'<span class="{kind}">{esc(text)}</span>' if text else "" for text, kind in lines)
        body = (f'<p><a class="back" href="/nodes">← {esc(t("web.back"))}</a></p>'
                f'<pre class="explain">{rendered}</pre>')
        return self.shell("/nodes", t("web.node_title", mac=mac), body)

    # ----------------------------------------------------------------- routing

    def respond(self, path: str, query: dict) -> tuple[int, str, bytes]:
        """``(status, content type, body)`` for a GET; never touches the state otherwise."""
        t = self.t
        now = self.clock.now()
        html_type = "text/html; charset=utf-8"
        if path.startswith("/static/"):
            return self.asset(path.removeprefix("/static/"))
        if path == "/healthz":
            return HTTPStatus.OK, "text/plain; charset=utf-8", b"ok\n"
        if path.startswith("/download/"):
            return self.download(path.removeprefix("/download/"))
        if path == "/node":
            mac = (query.get("mac") or [""])[0]
            return HTTPStatus.OK, html_type, self.node_page(mac)
        if path not in {page.path for page in NAV}:
            return (HTTPStatus.NOT_FOUND, html_type,
                    self.shell("/", t("web.not_found"), ""))
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
        return HTTPStatus.OK, html_type, self.table_page(path, title, table, subtitle, link)

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
        try:
            status, content_type, body = self.server.site.respond(
                parsed.path, parse_qs(parsed.query))
        except StateError as exc:
            status, content_type = HTTPStatus.SERVICE_UNAVAILABLE, "text/plain; charset=utf-8"
            body = f"{exc}\n".encode()
        except Exception:                  # a bug must not kill the server thread
            log.exception("%s failed", parsed.path)
            status, content_type = HTTPStatus.INTERNAL_SERVER_ERROR, "text/plain; charset=utf-8"
            body = b"internal error; see the logs\n"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'self'; script-src 'self'; "
                         "img-src 'self' data:; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

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
