"""Terminal management interface (Textual).

Guided and "closed": choices come from lists, values are validated before being stored,
sensitive actions ask for confirmation. The interface never holds the state lock except while
running a collect it started, and never shows a secret.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from snowth_my_net.clock import Clock
from snowth_my_net.collect.discovery import resolve_seeds
from snowth_my_net.collect.engine import Collector
from snowth_my_net.collect.presets import get_preset, suggestions
from snowth_my_net.collect.probe import (
    Connection,
    ProbeInputError,
    connect,
    parse_oid_input,
    run_oid,
    run_preset,
)
from snowth_my_net.config.effective import FEATURES, baseline_for, settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.manual import ManualError
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.lock import LockBusy, StateLock
from snowth_my_net.logs import LOGGER_NAME, RedactingFormatter
from snowth_my_net.snmp.client import EnginePool
from snowth_my_net.snmp.target import AddressError, parse_target
from snowth_my_net.snmp.values import is_locally_administered
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.tui.data import DeviceRow, list_devices, plan_form_change
from snowth_my_net.tui.i18n import Translator, detect_language
from snowth_my_net.tui.safe import SafeTable as DataTable
from snowth_my_net.tui.safe import escape

DEVICE_TYPES = ("switch", "router", "firewall", "wireless", "server", "printer", "facility",
                "other")
STATUS_STYLE = {"ok": ("●", "green"), "partial": ("◐", "yellow"), "failed": ("✖", "red"),
                "never": ("○", "grey50")}


class TuiContext:
    """Everything the screens share: configuration, state, translations."""

    def __init__(self, loaded: LoadedConfig, clock: Clock | None = None) -> None:
        self.loaded = loaded
        self.cfg = loaded.cfg
        self.clock = clock or Clock()
        self.t = Translator(detect_language(loaded.cfg.general.language))
        self.conn = open_db(loaded.paths.state_file)
        self.repo = Repo(self.conn)
        self.credentials: list = []
        self.credentials_error: str | None = None
        try:
            self.credentials, _warnings = loaded.resolve_credentials()
        except ConfigError as exc:
            self.credentials_error = "; ".join(exc.errors)

    def local_time(self, epoch: int | None) -> str:
        if not epoch:
            return "—"
        moment = datetime.fromtimestamp(epoch)
        if moment.date() == datetime.now().date():
            return moment.strftime("%H:%M")
        return moment.strftime("%d/%m %H:%M")

    def local_time_iso(self, iso: str) -> str:
        if not iso:
            return "—"
        moment = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return self.local_time(int(moment.timestamp()))

    def status_text(self, status: str) -> Text:
        symbol, style = STATUS_STYLE.get(status, ("?", "grey50"))
        return Text(f"{symbol} {self.t('st.' + status)}", style=style)

    def type_label(self, device_type: str) -> str:
        return self.t(f"type.{device_type}") if device_type else ""

    def close(self) -> None:
        self.conn.close()


def localized_bindings(t: Translator, specs: list[tuple]) -> list[Binding]:
    return [Binding(key, action, t(label), show=show, priority=priority)
            for key, action, label, show, priority in specs]


# --------------------------------------------------------------------------- common widgets


class TopBar(Horizontal):
    def __init__(self, ctx: TuiContext, title: str = "") -> None:
        super().__init__(id="topbar")
        self.ctx = ctx
        self.title_text = title

    def compose(self) -> ComposeResult:
        brand = Text.assemble(("◆ snowth_my_net", "bold"), ("  " + self.ctx.t("app.subtitle"),
                                                              "dim"))
        if self.title_text:
            brand.append(f"  ›  {self.title_text}", style="bold")
        yield Label(brand, id="brand")
        yield Label("", id="runstatus")

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        t, repo = self.ctx.t, self.ctx.repo
        last = repo.last_successful_collect()
        if last is None:
            text = Text(t("status.never"), style="dim")
        else:
            import json

            stats = json.loads(last["stats"] or "{}")
            text = Text(t("status.last", when=self.ctx.local_time(last["finished_at"]),
                          status=t("st." + ("ok" if last["status"] == "ok" else "partial")),
                          ok=stats.get("reachable", 0), total=stats.get("devices", 0)))
        self.query_one("#runstatus", Label).update(text)


class ConfirmModal(ModalScreen[bool]):
    BINDINGS: ClassVar = [Binding("escape", "cancel", show=False)]

    def __init__(self, ctx: TuiContext, message: str, danger: bool = True) -> None:
        super().__init__()
        self.ctx, self.message, self.danger = ctx, message, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(self.message), classes="dialog-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.ctx.t("no"), id="no")
                yield Button(self.ctx.t("yes"), id="yes",
                             variant="error" if self.danger else "primary")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpModal(ModalScreen[None]):
    BINDINGS: ClassVar = [Binding("escape,question_mark,q", "close", show=False)]

    def __init__(self, ctx: TuiContext) -> None:
        super().__init__()
        self.ctx = ctx

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label(self.ctx.t("help.title"), classes="dialog-title")
            yield Static(self.ctx.t("help.body"), classes="dialog-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.ctx.t("ok"), id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    @on(Button.Pressed)
    def pressed(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class AddDeviceModal(ModalScreen[str | None]):
    BINDINGS: ClassVar = [Binding("escape", "cancel", show=False)]

    def __init__(self, ctx: TuiContext) -> None:
        super().__init__()
        self.ctx = ctx

    def compose(self) -> ComposeResult:
        t = self.ctx.t
        with Vertical(classes="dialog"):
            yield Label(t("add.title"), classes="dialog-title")
            yield Input(placeholder=t("add.placeholder"), id="address")
            yield Static(t("add.hint"), classes="hint", id="add-message")
            with Horizontal(classes="dialog-buttons"):
                yield Button(t("no"), id="cancel")
                yield Button(t("add.title"), id="add", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#address", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#add")
    def submit(self) -> None:
        t = self.ctx.t
        text = self.query_one("#address", Input).value
        message = self.query_one("#add-message", Static)
        try:
            target = parse_target(text, self.ctx.cfg.general.snmp.port)
        except AddressError as exc:
            message.update(Text(t("add.invalid", error=exc), style="red"))
            return
        if any(n and n.version == target.ip.version and target.ip in n
               for n in self.ctx.cfg.discovery.exclude):
            message.update(Text(t("add.excluded", target=target), style="red"))
            return
        self.ctx.repo.ensure_target(str(target), "manual", 0, self.ctx.clock.now())
        self.dismiss(str(target))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ExplainModal(ModalScreen[None]):
    BINDINGS: ClassVar = [Binding("escape,q", "close", show=False)]
    STYLES: ClassVar = {"title": "bold", "ok": "$success", "bad": "$error",
                        "transit": "$warning", "dim": "$text-muted", "text": ""}

    def __init__(self, ctx: TuiContext, view, query: str) -> None:
        super().__init__()
        self.ctx, self.view, self.query_text = ctx, view, query

    def compose(self) -> ComposeResult:
        from snowth_my_net.merge.explain import explain

        parts = []
        for text, kind in explain(self.view, self.query_text, self.ctx.t):
            style = self.STYLES.get(kind, "")
            parts.append(f"[{style}]{escape(text)}[/]" if style and text else escape(text))
        with Vertical(classes="dialog wide tall explain"):
            yield Label(self.ctx.t("explain.title", mac=self.query_text), classes="dialog-title")
            with VerticalScroll(id="explain-body"):
                yield Static("\n".join(parts), id="explain-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.ctx.t("collect.close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


def scope_text(collector, t) -> str:
    scope = collector.applies_to
    parts = []
    if scope.vendors:
        parts.append(", ".join(scope.vendors))
    if scope.types:
        parts.append(", ".join(t(f"type.{x}") for x in scope.types))
    if scope.addresses:
        parts.append(", ".join(str(a) for a in scope.addresses))
    if scope.sys_object_ids:
        parts.append(", ".join(scope.sys_object_ids))
    return " · ".join(parts) or t("ext.all")


class CollectorModal(ModalScreen[None]):
    BINDINGS: ClassVar = [Binding("escape,q", "close", show=False)]

    def __init__(self, ctx: TuiContext, loaded) -> None:
        super().__init__()
        self.ctx, self.loaded = ctx, loaded

    def compose(self) -> ComposeResult:
        import dataclasses

        import yaml

        cfg = self.loaded.cfg
        if cfg.kind == "python":
            definition = _definition({
                "name": cfg.name, "python_extension": cfg.extension,
                "function": getattr(cfg.func, "__qualname__", ""), "description": cfg.description,
                "applies_to": dataclasses.asdict(cfg.applies_to), "columns": cfg.columns,
                "table": cfg.table or None, "index": cfg.walk.index if cfg.walk else None,
                "fills": cfg.fills, "every": cfg.every, "mode": cfg.mode})
        else:
            definition = _definition(dataclasses.asdict(cfg))
        text = yaml.safe_dump(definition, sort_keys=False, allow_unicode=True)
        with Vertical(classes="dialog wide tall"):
            yield Label(self.loaded.cfg.name, classes="dialog-title")
            with VerticalScroll(id="explain-body"):
                yield Static(escape(text), id="collector-yaml")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.ctx.t("collect.close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)


def _definition(data):
    """Drop empty values so that a collector reads like hand-written YAML."""
    if isinstance(data, dict):
        cleaned = {k: _definition(v) for k, v in data.items()}
        return {k: v for k, v in cleaned.items()
                if v not in (None, "", [], {}) and not (k == "every" and v == 0)
                and not (k == "mode" and v == "auto") and not (k == "limit" and v == 10_000)
                and not (k == "fill_override" and v is False)
                and not (k == "type" and v == "auto") and not (k == "index" and v == "raw")}
    if isinstance(data, list):
        return [_definition(v) for v in data]
    return str(data) if hasattr(data, "compressed") else data


class SaveCollectorModal(ModalScreen[str | None]):
    """Turn the last successful OID test into a custom collector."""

    BINDINGS: ClassVar = [Binding("escape", "cancel", show=False)]
    VALUE_TYPES = ("auto", "text", "integer", "mac", "ip", "hex", "timeticks", "oid")

    def __init__(self, ctx: TuiContext, row: DeviceRow, columns: dict[str, str], kind: str,
                 default_name: str, vendor: str, device_type: str) -> None:
        super().__init__()
        self.ctx, self.row, self.columns, self.kind = ctx, row, columns, kind
        self.default_name, self.vendor, self.device_type = default_name, vendor, device_type

    def compose(self) -> ComposeResult:
        t = self.ctx.t
        scopes = [(t("save.scope_device", address=self.row.host), "device")]
        if self.vendor:
            scopes.append((t("save.scope_vendor", vendor=self.vendor), "vendor"))
        if self.device_type:
            scopes.append((t("save.scope_type", type=self.ctx.type_label(self.device_type)),
                           "type"))
        scopes.append((t("save.scope_all"), "all"))
        with Vertical(classes="dialog wide"):
            yield Label(t("save.title"), classes="dialog-title")
            yield Static(t("save.what", kind=self.kind, count=len(self.columns),
                           oids=", ".join(self.columns.values())), classes="hint")
            with Grid(classes="form"):
                yield Label(t("save.name"))
                yield Input(self.default_name, id="c-name", compact=True)
                yield Static("")
                if len(self.columns) == 1:
                    yield Label(t("save.column"))
                    yield Input(next(iter(self.columns)), id="c-column", compact=True)
                    yield Static("")
                    yield Label(t("save.type"))
                    yield Select([(v, v) for v in self.VALUE_TYPES], value="auto",
                                 allow_blank=False, id="c-type", compact=True)
                    yield Static("")
                yield Label(t("save.scope"))
                yield Select(scopes, value="device", allow_blank=False, id="c-scope",
                             compact=True)
                yield Static("")
                yield Label(t("save.description"))
                yield Input(id="c-description", compact=True)
                yield Static("")
            yield Static("", id="c-message", classes="hint")
            with Horizontal(classes="dialog-buttons"):
                yield Button(t("no"), id="cancel")
                yield Button(t("set.save"), id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#c-name", Input).focus()

    def definition(self) -> dict:
        columns = dict(self.columns)
        specs: dict = {}
        if len(columns) == 1:
            column = self.query_one("#c-column", Input).value.strip() or "value"
            value_type = str(self.query_one("#c-type", Select).value)
            oid = next(iter(columns.values()))
            specs[column] = oid if value_type == "auto" else {"oid": oid, "type": value_type}
        else:
            specs = columns
        scope = str(self.query_one("#c-scope", Select).value)
        applies_to = {"device": {"addresses": [self.row.host]},
                      "vendor": {"vendors": [self.vendor]},
                      "type": {"types": [self.device_type]}, "all": {}}[scope]
        definition: dict = {"name": self.query_one("#c-name", Input).value.strip()}
        description = self.query_one("#c-description", Input).value.strip()
        if description:
            definition["description"] = description
        if applies_to:
            definition["applies_to"] = applies_to
        if self.kind == "walk":
            definition["walk"] = {"columns": specs}
        else:
            definition["get"] = specs
        return definition

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        from snowth_my_net.collect.custom import all_collectors
        from snowth_my_net.config.extensions import parse_collector

        t = self.ctx.t
        message = self.query_one("#c-message", Static)
        definition = self.definition()
        try:
            collector = parse_collector(definition)
        except ConfigError as exc:
            message.update(f"[$error]{escape('; '.join(exc.errors))}[/]")
            return
        existing = all_collectors(self.ctx.loaded.collectors, self.ctx.repo.custom_stored())[0]
        if any(c.cfg.name == collector.name for c in existing):
            message.update(f"[$error]{escape(t('save.exists', name=collector.name))}[/]")
            return
        self.ctx.repo.save_custom_collector(collector.name, definition, self.ctx.clock.now())
        self.dismiss(collector.name)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class TuiLogHandler(logging.Handler):
    STYLES: ClassVar = {logging.WARNING: "yellow", logging.ERROR: "bold red",
                        logging.CRITICAL: "bold red"}

    def __init__(self, widget: RichLog) -> None:
        super().__init__(logging.INFO)
        self.widget = widget
        self.setFormatter(RedactingFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self.widget.write(Text(line, style=self.STYLES.get(record.levelno, "")))
        except Exception:  # never let logging break the interface
            self.handleError(record)


class CollectModal(ModalScreen[bool]):
    BINDINGS: ClassVar = [Binding("escape", "close", show=False)]

    def __init__(self, ctx: TuiContext, only: set[str] | None, title: str) -> None:
        super().__init__()
        self.ctx, self.only, self.title_text = ctx, only, title
        self.finished = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide tall"):
            yield Label(self.title_text, classes="dialog-title")
            yield Static(self.ctx.t("collect.running"), id="collect-status")
            yield RichLog(id="collect-log", wrap=True, markup=False, highlight=False)
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.ctx.t("collect.close"), id="close", variant="primary",
                             disabled=True)

    def on_mount(self) -> None:
        self.run_collect()

    @work(exclusive=True, group="collect")
    async def run_collect(self) -> None:
        ctx, t = self.ctx, self.ctx.t
        status = self.query_one("#collect-status", Static)
        log_widget = self.query_one("#collect-log", RichLog)
        lock = StateLock(ctx.loaded.paths.lock_file, "collect (tui)")
        try:
            lock.acquire(0)
        except LockBusy as exc:
            status.update(f"[$warning]{escape(t('collect.busy', error=exc))}[/]")
            self._done()
            return
        handler = TuiLogHandler(log_widget)
        logger = logging.getLogger(LOGGER_NAME)
        logger.addHandler(handler)
        conn = open_db(ctx.loaded.paths.state_file)
        try:
            report = await Collector(ctx.loaded, Repo(conn), ctx.credentials, ctx.clock).run(
                self.only)
            s = report.stats
            color = {"ok": "$success", "partial": "$warning"}.get(report.status, "$error")
            message = t("collect.done", status=report.status, devices=s.get("devices", 0),
                        reachable=s.get("reachable", 0), failing=s.get("failing", 0),
                        duration=s.get("duration_s", 0))
            status.update(f"[b {color}]{escape(message)}[/]")
            for error in report.errors:
                log_widget.write(Text(error, style="red"))
        except Exception as exc:  # shown, never raised into the interface
            status.update(f"[$error]{escape(repr(exc))}[/]")
        finally:
            logger.removeHandler(handler)
            conn.close()
            lock.release()
            self._done()

    def _done(self) -> None:
        self.finished = True
        button = self.query_one("#close", Button)
        button.disabled = False
        button.focus()

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        if self.finished:
            self.dismiss(True)


# --------------------------------------------------------------------------- main screen


class MainScreen(Screen):
    SPECS: ClassVar = [
        ("enter", "open", "key.open", True, False),
        ("slash", "focus_filter", "key.filter", True, False),
        ("c", "collect_all", "key.collect_all", True, False),
        ("a", "add", "key.add", True, False),
        ("n", "new_report", "key.new_report", True, False),
        ("x", "export_report", "key.export_report", True, False),
        ("delete", "remove", "key.remove", True, False),
        ("r", "refresh", "key.refresh", True, False),
        ("m", "local_macs", "key.local_macs", True, False),
        ("question_mark", "help", "key.help", True, False),
        ("q", "quit", "key.quit", True, False),
    ]

    def __init__(self, ctx: TuiContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.rows: list[DeviceRow] = []
        self.local_macs = ""          # "", "hide" or "only": the locally administered MACs

    def compose(self) -> ComposeResult:
        t = self.ctx.t
        yield TopBar(self.ctx)
        if self.ctx.credentials_error:
            yield Static(Text(t("creds.error", error=self.ctx.credentials_error)),
                         classes="banner-error")
        with TabbedContent(id="main-tabs"):
            with TabPane(t("tab.devices"), id="tab-devices"):
                yield Input(placeholder=t("filter.placeholder"), id="filter")
                yield DataTable(id="devices", cursor_type="row", zebra_stripes=True)
                yield Static(t("devices.empty"), id="devices-empty", classes="empty")
                yield Static(t("devices.legend"), classes="legend")
            with TabPane(t("tab.nodes"), id="tab-nodes"):
                yield Input(placeholder=t("nodes.placeholder"), id="node-filter")
                yield DataTable(id="nodes", cursor_type="row", zebra_stripes=True)
                yield Static("", id="nodes-count", classes="legend")
            with TabPane(t("tab.links"), id="tab-links"):
                yield DataTable(id="links", cursor_type="row", zebra_stripes=True)
                yield Static("", id="links-count", classes="legend")
            with TabPane(t("tab.reports"), id="tab-reports"):
                yield DataTable(id="reports", cursor_type="row", zebra_stripes=True)
                yield Static("", id="reports-empty", classes="empty")
                yield Static("", id="reports-count", classes="legend")
            with TabPane(t("tab.extensions"), id="tab-extensions"):
                yield DataTable(id="extensions", cursor_type="row", zebra_stripes=True)
                yield Static("", id="extensions-count", classes="legend")
            with TabPane(t("tab.runs"), id="tab-runs"):
                yield DataTable(id="runs", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        t = self.ctx.t
        devices = self.query_one("#devices", DataTable)
        for key, label in (("name", "col.name"), ("ip", "col.ip"), ("type", "col.type"),
                           ("vendor", "col.vendor"), ("model", "col.model"),
                           ("status", "col.status"), ("seen", "col.seen")):
            devices.add_column(t(label), key=key)
        nodes = self.query_one("#nodes", DataTable)
        for key, label in (("mac", "col.mac"), ("vendor", "col.vendor"), ("ip", "col.ip"),
                           ("dns", "col.dns"), ("switch", "col.switch"), ("port", "col.port"),
                           ("vlan", "col.vlan"), ("seen", "col.seen")):
            nodes.add_column(t(label), key=key)
        extensions = self.query_one("#extensions", DataTable)
        for key, label in (("name", "col.name"), ("kind", "col.kind"), ("scope", "col.scope"),
                           ("origin", "col.origin"), ("description", "col.description")):
            extensions.add_column(t(label), key=key)
        reports = self.query_one("#reports", DataTable)
        for key, label in (("name", "col.name"), ("source", "col.source"),
                           ("format", "col.format"), ("schedule", "col.schedule"),
                           ("push", "col.push"), ("origin", "col.origin"),
                           ("title", "col.title")):
            reports.add_column(t(label), key=key)
        links = self.query_one("#links", DataTable)
        for key, label in (("a", "col.local_device"), ("ap", "col.local_port"),
                           ("b", "col.remote_device"), ("bp", "col.remote_port"),
                           ("proto", "col.protocol"), ("seen", "col.seen")):
            links.add_column(t(label), key=key)
        runs = self.query_one("#runs", DataTable)
        for key, label in (("id", "col.run"), ("command", "col.command"),
                           ("started", "col.started"), ("duration", "col.duration"),
                           ("result", "col.result"), ("devices", "col.devices")):
            runs.add_column(t(label), key=key)
        self.action_refresh()
        devices.focus()

    def on_screen_resume(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.rows = list_devices(self.ctx.loaded, self.ctx.repo, self.ctx.clock.now())
        self.fill_devices()
        self.fill_runs()
        self.view = None
        self.node_rows = None
        active = self.query_one("#main-tabs", TabbedContent).active
        if active == "tab-nodes":
            self.fill_nodes()
        elif active == "tab-links":
            self.fill_links()
        elif active == "tab-extensions":
            self.fill_extensions()
        elif active == "tab-reports":
            self.fill_reports()
        self.query_one(TopBar).refresh_status()

    NODE_LIMIT: ClassVar[int] = 2000

    def ensure_view(self):
        if getattr(self, "view", None) is None:
            from snowth_my_net.merge.view import build_view

            self.view = build_view(self.ctx.loaded, self.ctx.repo, self.ctx.clock.now())
            self.node_rows = self.view.rows(given_columns=False)
        return self.view

    def fill_nodes(self) -> None:
        self.ensure_view()
        table = self.query_one("#nodes", DataTable)
        needle = self.query_one("#node-filter", Input).value.strip().casefold()
        rows = [r for r in self.node_rows if not needle or any(needle in c.casefold() for c in r)]
        if self.local_macs:        # a MAC whose locally administered bit is set (a private address)
            rows = [r for r in rows if is_locally_administered(r[0]) == (self.local_macs == "only")]
        table.clear()
        for i, r in enumerate(rows[:self.NODE_LIMIT]):
            cells = [Text(r[0], style="bold"), r[1] or "—", r[2] or "—", r[3] or "—",
                     r[4] or Text("—", style="dim"), r[5] or "", r[6] or "",
                     self.ctx.local_time_iso(r[7])]
            table.add_row(*cells, key=f"{i}:{r[0]}")
        text = self.ctx.t("nodes.count", shown=min(len(rows), self.NODE_LIMIT),
                          total=len(self.node_rows))
        if len(rows) > self.NODE_LIMIT:
            text += " · " + self.ctx.t("nodes.truncated", limit=self.NODE_LIMIT)
        if self.local_macs:
            text += " · " + self.ctx.t(f"nodes.local.{self.local_macs}")
        self.query_one("#nodes-count", Static).update(text)

    def action_local_macs(self) -> None:
        """All, then without, then only the locally administered MACs. Nothing is merged."""
        if self.query_one("#main-tabs", TabbedContent).active != "tab-nodes":
            return
        self.local_macs = {"": "hide", "hide": "only", "only": ""}[self.local_macs]
        self.fill_nodes()

    def collectors(self):
        from snowth_my_net.collect.custom import all_collectors

        return all_collectors(self.ctx.loaded.collectors, self.ctx.repo.custom_stored())[0]

    def fill_extensions(self) -> None:
        t = self.ctx.t
        table = self.query_one("#extensions", DataTable)
        table.clear()
        items = self.collectors()
        for loaded in items:
            c = loaded.cfg
            origin = t("ext.origin_tui") if loaded.origin == "tui" else loaded.origin
            table.add_row(Text(c.name, style="bold"), c.kind, scope_text(c, t), origin,
                          c.description or "", key=c.name)
        self.query_one("#extensions-count", Static).update(t("ext.count", count=len(items)))

    def selected_collector(self):
        table = self.query_one("#extensions", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((c for c in self.collectors() if c.cfg.name == key), None)

    @on(DataTable.RowSelected, "#extensions")
    def extension_selected(self) -> None:
        loaded = self.selected_collector()
        if loaded is not None:
            self.app.push_screen(CollectorModal(self.ctx, loaded))

    def fill_links(self) -> None:
        view = self.ensure_view()
        table = self.query_one("#links", DataTable)
        table.clear()
        rows = view.link_rows()
        for i, r in enumerate(rows):
            table.add_row(Text(r[0], style="bold"), r[1], Text(r[2], style="bold"), r[3], r[4],
                          self.ctx.local_time_iso(r[5]), key=str(i))
        self.query_one("#links-count", Static).update(self.ctx.t("links.count", count=len(rows)))

    @on(TabbedContent.TabActivated, "#main-tabs")
    def tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-nodes":
            self.fill_nodes()
        elif event.pane.id == "tab-links":
            self.fill_links()
        elif event.pane.id == "tab-extensions":
            self.fill_extensions()
        elif event.pane.id == "tab-reports":
            self.fill_reports()
            self.query_one("#reports", DataTable).focus()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("new_report", "export_report"):
            with contextlib.suppress(Exception):
                return self.query_one("#main-tabs", TabbedContent).active == "tab-reports"
            return False
        return True

    # reports ------------------------------------------------------------------------------

    def reports(self):
        from snowth_my_net.tui.reports import catalog

        return catalog(self.ctx)

    def fill_reports(self) -> None:
        t = self.ctx.t
        table = self.query_one("#reports", DataTable)
        table.clear()
        items = self.reports()
        for loaded in items:
            r = loaded.cfg
            origin = t("ext.origin_tui") if loaded.origin == "tui" else loaded.origin
            table.add_row(Text(r.name, style="bold"), r.source, r.format, r.schedule or "—",
                          ", ".join(r.push) or "—", origin, r.title, key=r.name)
        self.query_one("#reports-empty", Static).update(t("rep.none") if not items else "")
        self.query_one("#reports-empty", Static).display = not items
        self.query_one("#reports-count", Static).update(t("rep.count", count=len(items)))

    def selected_report(self):
        table = self.query_one("#reports", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((r for r in self.reports() if r.cfg.name == key), None)

    @on(DataTable.RowSelected, "#reports")
    def report_selected(self) -> None:
        loaded = self.selected_report()
        if loaded is not None:
            self.app.push_screen(self.app.report_screen(loaded))

    def action_new_report(self) -> None:
        self.app.push_screen(self.app.report_screen(None))

    def action_export_report(self) -> None:
        from snowth_my_net.reports.engine import ReportError
        from snowth_my_net.reports.service import EmptyReport
        from snowth_my_net.tui.reports import export_report

        t = self.ctx.t
        loaded = self.selected_report()
        if loaded is None:
            return
        try:
            generated = export_report(self.ctx, loaded.cfg)
        except EmptyReport:
            self.notify(t("rep.empty", name=loaded.cfg.name), severity="warning", timeout=8)
            return
        except (ReportError, OSError) as exc:
            self.notify(str(exc), severity="error", timeout=10)
            return
        self.notify(t("rep.written", path=str(generated.path), rows=len(generated.table.rows)),
                    timeout=8)

    @on(Input.Changed, "#node-filter")
    def node_filter_changed(self) -> None:
        self.fill_nodes()

    @on(DataTable.RowSelected, "#nodes")
    def node_selected(self, event: DataTable.RowSelected) -> None:
        mac = str(event.row_key.value).split(":", 1)[1]
        self.app.push_screen(ExplainModal(self.ctx, self.ensure_view(), mac))

    def fill_devices(self) -> None:
        table = self.query_one("#devices", DataTable)
        needle = self.query_one("#filter", Input).value
        selected = self.selected_row()
        table.clear()
        shown = [r for r in self.rows if r.matches(needle)]
        for r in shown:
            type_cell = Text(self.ctx.type_label(r.device_type) or "?",
                             style="" if r.device_type else "dim")
            if r.type_mark and r.device_type:
                type_cell.append(f" {r.type_mark}", style="bold cyan")
            table.add_row(Text(r.name, style="bold"), r.host, type_cell, r.vendor or "—",
                          r.model or "—", self.ctx.status_text(r.status),
                          self.ctx.local_time(r.last_seen), key=r.target)
        if selected is not None and selected.target in {r.target for r in shown}:
            table.move_cursor(row=table.get_row_index(selected.target))
        self.query_one("#devices-empty", Static).display = not self.rows

    def fill_runs(self) -> None:
        import json

        table = self.query_one("#runs", DataTable)
        table.clear()
        for run in self.ctx.repo.recent_runs(100):
            stats = json.loads(run["stats"] or "{}")
            duration = (f"{run['finished_at'] - run['started_at']} s" if run["finished_at"]
                        else "…")
            status = run["status"] or "running"
            style = {"ok": "green", "partial": "yellow", "failed": "red"}.get(status, "")
            table.add_row(str(run["id"]), run["command"], self.ctx.local_time(run["started_at"]),
                          duration, Text(status, style=style),
                          f"{stats.get('reachable', '—')}/{stats.get('devices', '—')}",
                          key=str(run["id"]))

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.fill_devices()

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.query_one("#devices", DataTable).focus()

    def selected_row(self) -> DeviceRow | None:
        table = self.query_one("#devices", DataTable)
        if table.row_count == 0:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None
        return next((r for r in self.rows if r.target == key), None)

    @on(DataTable.RowSelected, "#devices")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        row = next((r for r in self.rows if r.target == event.row_key.value), None)
        if row is not None:
            self.app.push_screen(self.app.device_screen(row))

    def action_open(self) -> None:
        row = self.selected_row()
        if row is not None:
            self.app.push_screen(self.app.device_screen(row))

    def action_focus_filter(self) -> None:
        self.query_one("#main-tabs", TabbedContent).active = "tab-devices"
        self.query_one("#filter", Input).focus()

    def action_collect_all(self) -> None:
        if self.ctx.credentials_error:
            self.notify(self.ctx.t("tester.no_creds"), severity="error")
            return
        self.app.push_screen(CollectModal(self.ctx, None, self.ctx.t("collect.title_all")),
                             lambda _result: self.action_refresh())

    def action_add(self) -> None:
        def added(target: str | None) -> None:
            if target:
                self.notify(self.ctx.t("add.done", target=target))
                self.action_refresh()

        self.app.push_screen(AddDeviceModal(self.ctx), added)

    @work(group="remove")
    async def action_remove(self) -> None:
        t = self.ctx.t
        if self.query_one("#main-tabs", TabbedContent).active == "tab-reports":
            report = self.selected_report()
            if report is None:
                return
            if report.origin != "tui":
                self.notify(t("rep.file_delete", name=report.cfg.name, origin=report.origin),
                            severity="warning", timeout=8)
                return
            if await self.app.push_screen_wait(
                    ConfirmModal(self.ctx, t("rep.confirm_delete", name=report.cfg.name))):
                self.ctx.repo.delete_report(report.cfg.name)
                self.notify(t("ext.deleted", name=report.cfg.name))
                self.fill_reports()
            return
        if self.query_one("#main-tabs", TabbedContent).active == "tab-extensions":
            loaded = self.selected_collector()
            if loaded is None:
                return
            if loaded.origin != "tui":
                self.notify(t("ext.file_delete", name=loaded.cfg.name, origin=loaded.origin),
                            severity="warning", timeout=8)
                return
            if await self.app.push_screen_wait(
                    ConfirmModal(self.ctx, t("ext.confirm_delete", name=loaded.cfg.name))):
                self.ctx.repo.delete_custom_collector(loaded.cfg.name)
                self.notify(t("ext.deleted", name=loaded.cfg.name))
                self.fill_extensions()
            return
        row = self.selected_row()
        if row is None:
            return
        t = self.ctx.t
        seeds = (await resolve_seeds(self.ctx.cfg)).targets
        message = t("remove.confirm", name=row.name)
        if any(str(target) == row.target for target, _ in seeds):
            message += "\n\n" + t("remove.seed", name=row.name)
        if await self.app.push_screen_wait(ConfirmModal(self.ctx, message)):
            self.ctx.repo.remove_target(row.target)
            self.notify(t("remove.done", name=row.name))
            self.action_refresh()

    def action_help(self) -> None:
        self.app.push_screen(HelpModal(self.ctx))

    async def action_quit(self) -> None:
        await self.app.action_quit()


# --------------------------------------------------------------------------- device screen


class DeviceScreen(Screen):
    SPECS: ClassVar = [
        ("escape", "back", "key.back", True, False),
        ("c", "collect", "key.collect_one", True, False),
        ("ctrl+s", "save", "key.save", True, True),
        ("question_mark", "help", "key.help", True, False),
    ]

    def __init__(self, ctx: TuiContext, row: DeviceRow) -> None:
        super().__init__()
        self.ctx, self.row = ctx, row
        self.pool: EnginePool | None = None
        self.connection: Connection | None = None
        self._loading_form = False
        self._auto_label = ""

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        t = self.ctx.t
        yield TopBar(self.ctx, self.row.name)
        with TabbedContent(id="device-tabs"):
            with TabPane(t("tab.identity"), id="tab-identity"), VerticalScroll():
                yield Static(id="identity")
            with TabPane(t("tab.settings"), id="tab-settings"), VerticalScroll():
                yield Static(t("set.intro"), classes="intro")
                yield from self.compose_form()
            with TabPane(t("tab.tester"), id="tab-tester"), Horizontal(id="tester"):
                with Vertical(id="presets-pane"):
                    yield Label(t("tester.presets"), classes="section")
                    yield OptionList(id="presets")
                with Vertical(id="results-pane"):
                    with Horizontal(id="oid-bar"):
                        yield Input(placeholder=t("tester.oid_placeholder"), id="oid",
                                    compact=True)
                        yield Select([(t("tester.mode_auto"), "auto"), ("GET", "get"),
                                      ("walk", "walk")], value="auto", allow_blank=False,
                                     id="oid-mode", compact=True)
                        yield Input("50", type="integer", id="limit", compact=True,
                                    tooltip=t("tester.limit"))
                        yield Button(t("tester.run"), id="run-oid", variant="primary",
                                     compact=True)
                        yield Button(t("save.button"), id="save-oid", compact=True,
                                     disabled=True)
                    yield Static(t("tester.hint"), id="tester-status")
                    yield DataTable(id="results", zebra_stripes=True)
            with TabPane(t("tab.neighbors"), id="tab-neighbors"), Vertical():
                yield Static("", id="neighbors-empty", classes="empty")
                yield DataTable(id="neighbors", zebra_stripes=True)
            with TabPane(t("tab.custom"), id="tab-custom"), Vertical():
                yield Static("", id="custom-empty", classes="empty")
                yield DataTable(id="custom", zebra_stripes=True)
            with TabPane(t("tab.last"), id="tab-last"), Vertical():
                yield Static(id="last-when")
                yield DataTable(id="last", zebra_stripes=True)
        yield Footer()

    def compose_form(self) -> ComposeResult:
        t = self.ctx.t
        with Grid(classes="form"):
            yield Label(t("set.type"))
            self._auto_label = self.auto_type_label()
            yield Select([(self._auto_label, "")]
                         + [(self.ctx.type_label(v), v) for v in DEVICE_TYPES],
                         allow_blank=False, value="", id="f-type", compact=True)
            yield Static(id="s-type", classes="source")

            yield Label(t("set.name"))
            yield Input(placeholder=t("set.name_placeholder"), id="f-name", compact=True)
            yield Static(id="s-name", classes="source")

            yield Label(t("set.credential"))
            yield Select([(t("set.cred_order"), "")]
                         + [(c.name, c.name) for c in self.ctx.cfg.credentials],
                         allow_blank=False, value="", id="f-credential", compact=True)
            yield Static(id="s-credential", classes="source")

            yield Label(t("set.disabled"))
            yield Switch(id="f-disabled")
            yield Static(id="s-disabled", classes="source")

            yield Label(t("set.tolerate"))
            yield Switch(id="f-tolerate_failure")
            yield Static(id="s-tolerate_failure", classes="source")

        yield Label(t("set.functions"), classes="section")
        modes = [(t("mode.auto"), "auto"), (t("mode.force"), "force"), (t("mode.off"), "off")]
        with Grid(classes="form"):
            for feature in FEATURES:
                yield Label(t(f"feat.{feature}"))
                yield Select(modes, allow_blank=False, value="auto", id=f"f-features-{feature}",
                             compact=True)
                yield Static(id=f"s-features-{feature}", classes="source")

        yield Label(t("set.snmp"), classes="section")
        with Grid(classes="form"):
            yield Label(t("set.max_repetitions"))
            yield Input(type="integer", id="f-snmp-max_repetitions", compact=True)
            yield Static(id="s-snmp-max_repetitions", classes="source")
            yield Label(t("set.pace_ms"))
            yield Input(type="integer", id="f-snmp-pace_ms", compact=True)
            yield Static(id="s-snmp-pace_ms", classes="source")
            yield Label(t("set.use_bulk"))
            yield Switch(id="f-snmp-use_bulk")
            yield Static(id="s-snmp-use_bulk", classes="source")

        with Horizontal(classes="form-buttons"):
            yield Button(t("set.reset"), id="reset")
            yield Button(t("set.save"), id="save", variant="primary")

    def auto_type_label(self) -> str:
        t = self.ctx.t
        baseline = baseline_for(self.ctx.cfg, self.row.host)
        device = self.device()
        if baseline.type:
            return t("set.auto_config", value=self.ctx.type_label(baseline.type))
        if device and device["device_type"]:
            return t("set.auto_detected", value=self.ctx.type_label(device["device_type"]))
        return t("set.auto")

    @staticmethod
    def widget_id(key: str) -> str:
        return key.replace(".", "-")

    # ------------------------------------------------------------------ lifecycle

    def on_mount(self) -> None:
        self.load_identity()
        self.load_form()
        self.load_presets()
        self.load_last()
        self.load_neighbors()
        self.load_custom()

    async def on_unmount(self) -> None:
        if self.pool is not None:
            self.pool.close()

    def device(self) -> dict | None:
        if self.row.device_id is None:
            return None
        row = self.ctx.repo.device(self.row.device_id)
        return dict(row) if row else None

    def effective_type(self) -> tuple[str, str, str]:
        rows = list_devices(self.ctx.loaded, self.ctx.repo, self.ctx.clock.now())
        current = next((r for r in rows if r.target == self.row.target), self.row)
        self.row = current
        device = self.device()
        reason = device["type_reason"] if device else ""
        settings = settings_for(self.ctx.cfg, self.row.host, self.ctx.repo.manual_settings())
        if settings.type:
            reason = ("set by hand (TUI or 'device set')" if settings.source("type") == "manual"
                      else "declared in config.yml devices[].type")
        return current.device_type, current.type_rule, reason or ""

    def load_identity(self) -> None:
        t = self.ctx.t
        device = self.device()
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", no_wrap=True)
        grid.add_column()
        device_type, rule, reason = self.effective_type()
        type_text = Text(self.ctx.type_label(device_type) or t("id.no_type"),
                         style="bold" if device_type else "dim")
        if device is None:
            grid.add_row(t("id.address"), self.row.target)
            grid.add_row(t("id.type"), type_text)
            grid.add_row("", Text(t("id.never"), style="yellow"))
            if self.row.error:
                grid.add_row(t("id.last_error"), Text(self.row.error, style="red"))
        else:
            os_text = " ".join(x for x in (device["os_name"], device["os_version"]) if x)
            for label, value in (
                (t("id.name"), Text(self.row.name, style="bold")),
                (t("id.address"), device["mgmt_address"]),
                (t("id.sysname"), device["sys_name"] or "—"),
                (t("id.descr"), device["sys_descr"] or "—"),
                (t("id.vendor"), device["vendor"] or "—"),
                (t("id.model"), device["model"] or "—"),
                (t("id.serial"), device["serial"] or "—"),
                (t("id.os"), os_text or "—"),
                (t("id.mac"), device["base_mac"] or "—"),
                (t("id.location"), device["sys_location"] or "—"),
                (t("id.contact"), device["sys_contact"] or "—"),
                (t("id.credential"), device["credential"] or "—"),
                (t("id.driver"), device["driver"] or "—"),
                (t("id.type"), type_text),
                (t("id.why"), Text(f"{rule} — {reason}" if rule else "—", style="italic")),
                (t("id.seen"), self.ctx.local_time(device["last_seen"])),
            ):
                grid.add_row(label, Text(value) if isinstance(value, str) else value)
        self.query_one("#identity", Static).update(grid)

    def load_form(self) -> None:
        t = self.ctx.t
        self._loading_form = True
        manual = self.ctx.repo.manual_settings()
        settings = settings_for(self.ctx.cfg, self.row.host, manual)
        baseline = baseline_for(self.ctx.cfg, self.row.host)
        mine = manual.get(self.row.host, {})

        type_select = self.query_one("#f-type", Select)
        auto_label = self.auto_type_label()
        if auto_label != self._auto_label:
            self._auto_label = auto_label
            type_select.set_options([(auto_label, "")]
                                    + [(self.ctx.type_label(v), v) for v in DEVICE_TYPES])
        type_select.value = mine.get("type", "")
        self.query_one("#f-name", Input).value = mine.get("name", "")
        name_input = self.query_one("#f-name", Input)
        name_input.placeholder = baseline.name or t("set.name_placeholder")
        self.query_one("#f-credential", Select).value = mine.get("credential", "")
        for key in ("disabled", "tolerate_failure", "snmp.use_bulk"):
            self.query_one(f"#f-{self.widget_id(key)}", Switch).value = bool(settings.get(key))
        for feature in FEATURES:
            self.query_one(f"#f-features-{feature}", Select).value = settings.feature(feature)
        for key in ("snmp.max_repetitions", "snmp.pace_ms"):
            widget = self.query_one(f"#f-{self.widget_id(key)}", Input)
            widget.value = str(mine[key]) if key in mine else ""
            widget.placeholder = str(baseline.get(key))

        for key in ("type", "name", "credential", "disabled", "tolerate_failure",
                    *(f"features.{f}" for f in FEATURES), "snmp.max_repetitions",
                    "snmp.pace_ms", "snmp.use_bulk"):
            source = settings.source(key)
            style = {"manual": "bold cyan", "config": "magenta"}.get(source, "dim")
            self.query_one(f"#s-{self.widget_id(key)}", Static).update(
                Text(t(f"src.{source}"), style=style))
        self._loading_form = False

    def form_values(self) -> dict[str, Any]:
        def text(key: str) -> str:
            return self.query_one(f"#f-{self.widget_id(key)}", Input).value.strip()

        values: dict[str, Any] = {
            "type": self.query_one("#f-type", Select).value or None,
            "name": text("name") or None,
            "credential": self.query_one("#f-credential", Select).value or None,
        }
        for key in ("disabled", "tolerate_failure", "snmp.use_bulk"):
            values[key] = self.query_one(f"#f-{self.widget_id(key)}", Switch).value
        for feature in FEATURES:
            values[f"features.{feature}"] = self.query_one(f"#f-features-{feature}", Select).value
        for key in ("snmp.max_repetitions", "snmp.pace_ms"):
            raw = text(key)
            values[key] = int(raw) if raw.lstrip("-").isdigit() else (raw or None)
        return values

    def load_presets(self) -> None:
        device_type, _rule, _reason = self.effective_type()
        options = self.query_one("#presets", OptionList)
        options.clear_options()
        lang = self.ctx.t.lang
        for preset, suggested in suggestions(device_type):
            label = Text("★ " if suggested else "  ", style="bold yellow")
            label.append(preset.title(lang), style="" if suggested else "dim")
            label.append(f"  {preset.name}", style="dim italic")
            options.add_option(Option(label, id=preset.name))

    def load_last(self) -> None:
        t = self.ctx.t
        table = self.query_one("#last", DataTable)
        table.clear(columns=True)
        when = self.query_one("#last-when", Static)
        if self.row.device_id is None:
            when.update(Text(t("last.none"), style="dim"))
            return
        outcomes = self.ctx.repo.last_outcomes(self.row.device_id)
        if not outcomes:
            when.update(Text(t("last.none"), style="dim"))
            return
        when.update(Text(t("last.when", when=self.ctx.local_time(outcomes[0]["started_at"])),
                         style="bold"))
        for label in ("last.function", "last.status", "last.rows", "last.time", "last.detail"):
            table.add_column(t(label))
        styles = {"ok": "green", "absent": "dim", "skipped": "dim", "partial": "yellow",
                  "timeout": "red", "error": "red", "forced_absent": "red"}
        for o in outcomes:
            table.add_row(o["function"], Text(o["status"], style=styles.get(o["status"], "")),
                          str(o["rows"] or 0), f"{o['duration_ms'] or 0} ms", o["detail"] or "")

    def load_custom(self) -> None:
        t = self.ctx.t
        table = self.query_one("#custom", DataTable)
        table.clear(columns=True)
        empty = self.query_one("#custom-empty", Static)
        current = (self.ctx.repo.custom_current(self.row.device_id)
                   if self.row.device_id is not None else {})
        empty.update("" if current else t("custom.none"))
        empty.display = not current
        if not current:
            return
        for label in ("col.collector", "col.index", "col.column", "col.value", "col.seen"):
            table.add_column(t(label))
        for name, entry in sorted(current.items()):
            header = Text(name, style="bold")
            last = t("ext.last_pass", when=self.ctx.local_time(entry["run_at"]),
                     status=entry["status"])
            header.append(f"  {last}", style="dim")
            table.add_row(header, "", "", "", "")
            for column, value in entry["values"].items():
                table.add_row("", "", column, value or "", self.ctx.local_time(entry["run_at"]))
            for index, column, value in entry["table"]:
                table.add_row("", index, column, value or "", self.ctx.local_time(entry["run_at"]))

    def load_neighbors(self) -> None:
        from snowth_my_net.merge.view import build_view

        t = self.ctx.t
        table = self.query_one("#neighbors", DataTable)
        table.clear(columns=True)
        empty = self.query_one("#neighbors-empty", Static)
        if self.row.device_id is None:
            empty.update(t("neighbors.none"))
            return
        view = build_view(self.ctx.loaded, self.ctx.repo, self.ctx.clock.now())
        mine = [rn for rn in view.neighbors if rn.obs.device_id == self.row.device_id]
        empty.update("" if mine else t("neighbors.none"))
        empty.display = not mine
        for label in ("col.local_port", "col.remote_device", "col.remote_port", "col.protocol",
                      "col.caps", "col.role", "col.seen"):
            table.add_column(t(label))
        for rn in sorted(mine, key=lambda x: (x.obs.ifindex or 0, x.obs.protocol)):
            port = view.port_name(rn.obs.device_id, rn.obs.ifindex) if rn.obs.ifindex else "?"
            role = view.ctx.role(rn.obs.device_id, rn.obs.ifindex) if rn.obs.ifindex else None
            remote = Text(rn.remote_name, style="bold" if rn.remote_device_id else "")
            polled = "remote.polled" if rn.remote_device_id else "remote.not_polled"
            remote.append(f"  ({t(polled)})", style="dim")
            role_text = Text(t(f"role.{role.role}") if role else "—",
                             style="yellow" if role and role.uplink else "green")
            table.add_row(port, remote, rn.remote_port, rn.obs.protocol.upper(),
                          ", ".join(sorted(rn.obs.caps)) or "—", role_text,
                          self.ctx.local_time(rn.obs.last_seen))

    def refresh_all(self) -> None:
        self.load_custom()
        self.load_neighbors()
        self.load_identity()
        self.load_form()
        self.load_presets()
        self.load_last()
        self.query_one(TopBar).refresh_status()

    # ------------------------------------------------------------------ settings actions

    @on(Button.Pressed, "#save")
    def save_pressed(self) -> None:
        self.action_save()

    @work(group="save", exclusive=True)
    async def action_save(self) -> None:
        t = self.ctx.t
        manual = self.ctx.repo.manual_settings()
        values = self.form_values()
        try:
            change = plan_form_change(self.ctx.loaded, self.row.host, manual, values)
        except ManualError as exc:
            self.notify(str(exc), severity="error", timeout=8)
            return
        if change.empty:
            self.notify(t("set.nothing"))
            return
        was_disabled = settings_for(self.ctx.cfg, self.row.host, manual).disabled
        if values.get("disabled") and not was_disabled and not await self.app.push_screen_wait(
                ConfirmModal(self.ctx, t("confirm.disable", name=self.row.name))):
            return
        repo = self.ctx.repo
        if change.to_unset:
            repo.unset_manual(self.row.host, change.to_unset)
        if change.to_set:
            repo.set_manual(self.row.host, change.to_set, self.ctx.clock.now())
        self.notify(t("set.saved"), severity="information")
        self.refresh_all()

    @on(Button.Pressed, "#reset")
    def reset_pressed(self) -> None:
        self.ctx.repo.unset_manual(self.row.host)
        self.notify(self.ctx.t("set.reset_done"))
        self.refresh_all()

    # ------------------------------------------------------------------ tester actions

    @on(OptionList.OptionSelected, "#presets")
    def preset_selected(self, event: OptionList.OptionSelected) -> None:
        self.run_probe(event.option.id or "")

    @on(Input.Submitted, "#oid")
    @on(Button.Pressed, "#run-oid")
    def oid_submitted(self) -> None:
        text = self.query_one("#oid", Input).value.strip()
        if text:
            self.run_probe(text)

    def limit(self) -> int:
        raw = self.query_one("#limit", Input).value
        return max(1, min(10_000, int(raw))) if raw.isdigit() else 50

    @work(exclusive=True, group="probe")
    async def run_probe(self, item: str) -> None:
        t = self.ctx.t
        status = self.query_one("#tester-status", Static)
        table = self.query_one("#results", DataTable)
        if self.ctx.credentials_error:
            status.update(Text(t("tester.no_creds"), style="red"))
            return
        preset = get_preset(item)
        oid = None
        if preset is None:
            try:
                oid = parse_oid_input(item)
            except ProbeInputError:
                status.update(Text(t("tester.bad_oid", text=item), style="red"))
                return
        if self.connection is None or not self.connection.ok:
            status.update(Text(t("tester.connecting", target=self.row.target), style="dim"))
            if self.pool is None:
                self.pool = EnginePool()
            try:
                target = parse_target(self.row.target)
            except AddressError as exc:
                status.update(Text(str(exc), style="red"))
                return
            self.connection = await connect(self.ctx.loaded, self.ctx.credentials, target,
                                            self.pool, self.ctx.repo.manual_settings())
            if not self.connection.ok:
                status.update(Text(t("tester.unreachable", error=self.connection.error),
                                   style="red"))
                return
        conn = self.connection
        assert conn.client is not None and conn.system is not None
        what = preset.title(t.lang) if preset else item
        status.update(Text(t("tester.running", what=what), style="dim"))
        limit = self.limit()
        timeout = float(conn.settings.snmp.table_timeout)
        if preset is not None:
            result = await run_preset(conn.client, preset, t.lang, limit, conn.system.pen,
                                      timeout)
        else:
            mode = str(self.query_one("#oid-mode", Select).value)
            result = await run_oid(conn.client, oid, mode, limit, timeout)
        table.clear(columns=True)
        for header in result.headers:
            table.add_column(header)
        for row in result.rows:
            table.add_row(*row)
        color = {"ok": "$success", "absent": "$warning"}.get(result.status, "$error")
        line = t("tester.result", title=result.title, status=result.status,
                 rows=len(result.rows), requests=result.requests, ms=result.duration_ms)
        if result.detail:
            line += f" — {result.detail}"
        markup = f"[b {color}]{escape(line)}[/]"
        if result.truncated:
            markup += f" [$text-muted]({escape(t('tester.truncated', limit=limit))})[/]"
        status.update(markup)
        self.last_probe = (item, preset, oid, result)
        self.query_one("#save-oid", Button).disabled = result.status != "ok"

    @on(Button.Pressed, "#save-oid")
    def save_oid_pressed(self) -> None:
        from snowth_my_net.snmp.values import oid_str

        t = self.ctx.t
        probe = getattr(self, "last_probe", None)
        if probe is None or probe[3].status != "ok":
            self.notify(t("save.nothing"), severity="warning")
            return
        _item, preset, oid, result = probe
        if preset is not None:
            if preset.mode == "enterprise":
                self.notify(t("save.enterprise"), severity="warning")
                return
            columns = {c.label: oid_str(c.oid) for c in preset.columns}
            kind = "get" if preset.mode == "get" else "walk"
            default = preset.name
        else:
            columns = {"value": oid_str(oid)}
            single_get = len(result.rows) == 1 and result.rows[0][0] == oid_str(oid)
            kind = "get" if single_get else "walk"
            default = "oid-" + oid_str(oid).replace("1.3.6.1.4.1.", "e").replace(".", "-")[:40]
        device = self.device()
        device_type, _rule, _reason = self.effective_type()

        def saved(name: str | None) -> None:
            if name:
                self.notify(t("save.done", name=name), timeout=8)

        self.app.push_screen(SaveCollectorModal(
            self.ctx, self.row, columns, kind, default, (device or {}).get("vendor") or "",
            device_type), saved)

    # ------------------------------------------------------------------ other actions

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_collect(self) -> None:
        if self.ctx.credentials_error:
            self.notify(self.ctx.t("tester.no_creds"), severity="error")
            return

        def done(_result: bool | None) -> None:
            self.connection = None
            self.refresh_all()

        self.app.push_screen(
            CollectModal(self.ctx, {self.row.target},
                         self.ctx.t("collect.title_one", target=self.row.target)), done)

    def action_help(self) -> None:
        self.app.push_screen(HelpModal(self.ctx))


# --------------------------------------------------------------------------- application


class SnowthApp(App):
    def notify(self, message, *, title="", severity="information", timeout=None, markup=False):
        """Notifications carry device and host text: markup is off unless asked for."""
        return super().notify(message, title=title, severity=severity, timeout=timeout,
                              markup=markup)

    CSS_PATH = "app.tcss"
    TITLE = "snowth_my_net"
    ENABLE_COMMAND_PALETTE = True

    def __init__(self, ctx: TuiContext) -> None:
        super().__init__()
        self.ctx = ctx
        t = ctx.t
        self._main_cls = type("MainScreenL10n", (MainScreen,),
                              {"BINDINGS": localized_bindings(t, MainScreen.SPECS)})
        self._device_cls = type("DeviceScreenL10n", (DeviceScreen,),
                                {"BINDINGS": localized_bindings(t, DeviceScreen.SPECS)})
        self._report_cls = None

    def device_screen(self, row: DeviceRow) -> DeviceScreen:
        return self._device_cls(self.ctx, row)

    def report_screen(self, report):
        from snowth_my_net.tui.reports import ReportScreen

        if self._report_cls is None:
            self._report_cls = type("ReportScreenL10n", (ReportScreen,), {
                "BINDINGS": localized_bindings(self.ctx.t, ReportScreen.SPECS)})
        return self._report_cls(self.ctx, report)

    def on_mount(self) -> None:
        saved = self.ctx.repo.get_meta("tui_theme")
        if saved and saved in self.available_themes:
            self.theme = saved
        else:
            self.theme = "nord"
        self.push_screen(self._main_cls(self.ctx))

    async def action_quit(self) -> None:
        with contextlib.suppress(Exception):  # the theme preference is a convenience only
            self.ctx.repo.set_meta("tui_theme", self.theme)
        self.exit(0)


def run_tui(loaded: LoadedConfig) -> int:
    ctx = TuiContext(loaded)
    try:
        SnowthApp(ctx).run()
    finally:
        ctx.close()
    return 0
