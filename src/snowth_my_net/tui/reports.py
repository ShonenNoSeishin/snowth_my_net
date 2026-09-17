"""Reports in the terminal interface: the builder screen (dataset, columns, filters, sort, SQL,
format, schedule, push) with a live preview, and the export action."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    Select,
    SelectionList,
    Static,
    Switch,
    TextArea,
)

from snowth_my_net.config.reports import NO_VALUE_OPS, LoadedReport, ReportCfg
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.reports.datasets import Dataset, all_datasets
from snowth_my_net.reports.engine import ReportError, display, run_report, sql_tables
from snowth_my_net.reports.service import (
    EmptyReport,
    all_reports,
    context,
    generate,
    parse_report,
    push_report,
    report_definition,
)

SQL_SOURCE = "__sql__"
PREVIEW_ROWS = 200
CELL = 48
FORMATS = ("csv", "json", "markdown", "html")
OPS = ("eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex", "gt", "ge",
       "lt", "le", "empty", "not_empty", "in", "not_in", "older_than", "newer_than")


def catalog(ctx) -> list[LoadedReport]:
    return all_reports(ctx.loaded, ctx.repo.reports_stored())[0]


def export_report(ctx, report: ReportCfg):
    """Write a report with its default path; raises ReportError (EmptyReport included)."""
    report_ctx = context(ctx.loaded, ctx.repo, ctx.clock.now())
    return generate(ctx.loaded, report_ctx, report)


class FilterRow(Horizontal):
    """One filter: field, operator, value, remove."""

    def __init__(self, t, fields: list[str], values: dict | None = None) -> None:
        super().__init__(classes="filter-row")
        self.t, self.fields, self.values = t, fields, values or {}

    def compose(self) -> ComposeResult:
        field = self.values.get("field")
        yield Select([(f, f) for f in self.fields], value=field if field in self.fields
                     else Select.BLANK, prompt=self.t("rep.field"), compact=True,
                     classes="f-field")
        yield Select([(self.t(f"op.{op}"), op) for op in OPS],
                     value=self.values.get("op", "eq"), allow_blank=False, compact=True,
                     classes="f-op")
        value = self.values.get("value")
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        yield Input("" if value is None else str(value), placeholder=self.t("rep.value"),
                    compact=True, classes="f-value")
        yield Button("✕", classes="f-remove", compact=True)

    def definition(self) -> dict | None:
        field = self.query_one(".f-field", Select).value
        if field is Select.BLANK:
            return None
        op = str(self.query_one(".f-op", Select).value)
        item: dict[str, Any] = {"field": str(field), "op": op}
        if op not in NO_VALUE_OPS:
            text = self.query_one(".f-value", Input).value.strip()
            item["value"] = ([v.strip() for v in text.split(",") if v.strip()]
                             if op in ("in", "not_in") else text)
        return item

    @on(Button.Pressed, ".f-remove")
    def remove_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        parent = self.screen
        self.remove()
        if isinstance(parent, ReportScreen):
            parent.schedule_preview()


class ReportScreen(Screen):
    SPECS: ClassVar = [
        ("escape", "back", "key.back", True, False),
        ("ctrl+s", "save", "key.save", True, True),
        ("ctrl+e", "export", "key.export", True, True),
        ("ctrl+r", "reload", "key.reload", True, True),
    ]

    def __init__(self, ctx, report: LoadedReport | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.report = report
        self.report_ctx = context(ctx.loaded, ctx.repo, ctx.clock.now())
        self.datasets: dict[str, Dataset] = all_datasets(self.report_ctx.collectors)
        cfg = report.cfg if report else None
        self.labels = {c.field: c.label for c in (cfg.column_specs() if cfg else []) if c.label}
        self._timer = None
        self._loading = True

    # ----------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        from snowth_my_net.tui.app import TopBar

        t = self.ctx.t
        cfg = self.report.cfg if self.report else None
        source = (SQL_SOURCE if cfg and cfg.sql else (cfg.dataset if cfg else "devices"))
        sources = [(f"{name} — {ds.description}", name) for name, ds in self.datasets.items()]
        sources.append((t("rep.sql_source"), SQL_SOURCE))
        if source not in {v for _l, v in sources}:
            sources.insert(0, (f"{source} ({t('rep.unknown')})", source))
        yield TopBar(self.ctx, t("rep.title_edit", name=cfg.name) if cfg else t("rep.title_new"))
        with Horizontal(id="builder"):
            with VerticalScroll(id="builder-form"):
                if self.report and self.report.origin != "tui":
                    yield Static(t("rep.from_file", origin=self.report.origin), classes="intro")
                with Grid(classes="bform"):
                    yield Label(t("rep.name"))
                    yield Input(cfg.name if cfg else "", id="b-name", compact=True,
                                placeholder="unknown-types")
                    yield Label(t("rep.report_title"))
                    yield Input(cfg.title if cfg else "", id="b-title", compact=True)
                    yield Label(t("rep.source"))
                    yield Select(sources, value=source, allow_blank=False, id="b-source",
                                 compact=True)
                    yield Label(t("rep.format"))
                    yield Select([(f, f) for f in FORMATS], value=cfg.format if cfg else "csv",
                                 allow_blank=False, id="b-format", compact=True)
                    yield Label(t("rep.limit"))
                    yield Input(str(cfg.limit) if cfg and cfg.limit else "", id="b-limit",
                                compact=True, type="integer", placeholder=t("rep.no_limit"))
                    yield Label(t("rep.schedule"))
                    yield Input(cfg.schedule or "" if cfg else "", id="b-schedule",
                                compact=True, placeholder="0 7 * * 1")
                    yield Label(t("rep.allow_empty"))
                    yield Switch(cfg.allow_empty if cfg else False, id="b-allow-empty")
                with Vertical(id="b-dataset-part"):
                    yield Label(t("rep.columns"), classes="section")
                    yield SelectionList(id="b-columns", compact=True)
                    yield Label(t("rep.filters"), classes="section")
                    yield Vertical(id="b-filters")
                    yield Button(t("rep.add_filter"), id="b-add-filter", compact=True)
                    yield Label(t("rep.sort"), classes="section")
                    yield Input(", ".join(cfg.sort) if cfg else "", id="b-sort", compact=True,
                                placeholder=t("rep.sort_placeholder"))
                with Vertical(id="b-sql-part"):
                    yield Label(t("rep.sql"), classes="section")
                    yield TextArea(cfg.sql or "" if cfg else "", id="b-sql",
                                   language=None, soft_wrap=True, compact=True)
                    yield Static(t("rep.sql_tables", tables=", ".join(
                        sql_tables(self.report_ctx.collectors))), classes="hint")
                if self.ctx.cfg.push.targets:
                    yield Label(t("rep.push"), classes="section")
                    yield SelectionList(*[(target.name, target.name, target.name in
                                           (cfg.push if cfg else []))
                                          for target in self.ctx.cfg.push.targets],
                                        id="b-push", compact=True)
                yield Static("", id="b-message", classes="hint")
                with Horizontal(classes="form-buttons"):
                    yield Button(t("rep.export"), id="b-export", compact=True)
                    yield Button(t("set.save"), id="b-save", variant="primary", compact=True)
            with Vertical(id="builder-preview"):
                yield Static("", id="b-status")
                yield DataTable(id="b-preview", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        cfg = self.report.cfg if self.report else None
        self.fill_columns(cfg)
        if cfg and cfg.dataset:
            for flt in cfg.filters:
                self.add_filter({"field": flt.field, "op": flt.op, "value": flt.value})
        self.toggle_source()
        self.query_one("#b-name", Input).focus()
        self.call_after_refresh(self._loaded)

    def _loaded(self) -> None:
        self._loading = False
        self.refresh_preview()

    def source(self) -> str:
        return str(self.query_one("#b-source", Select).value)

    def fill_columns(self, cfg: ReportCfg | None = None) -> None:
        columns = self.query_one("#b-columns", SelectionList)
        columns.clear_options()
        dataset = self.datasets.get(self.source())
        if dataset is None:
            return
        chosen = ({c.field for c in cfg.column_specs()} if cfg and cfg.columns and
                  cfg.dataset == dataset.name else set(dataset.default_columns))
        columns.add_options([(f"{f.name}  [dim]{f.type}[/]", f.name, f.name in chosen)
                             for f in dataset.fields])

    def toggle_source(self) -> None:
        sql = self.source() == SQL_SOURCE
        self.query_one("#b-dataset-part").display = not sql
        self.query_one("#b-sql-part").display = sql

    def add_filter(self, values: dict | None = None) -> None:
        dataset = self.datasets.get(self.source())
        fields = [f.name for f in dataset.fields] if dataset else []
        self.query_one("#b-filters", Vertical).mount(FilterRow(self.ctx.t, fields, values))

    # ----------------------------------------------------------------- definition

    def definition(self) -> dict:
        name = self.query_one("#b-name", Input).value.strip()
        data: dict[str, Any] = {"name": name or "preview"}
        title = self.query_one("#b-title", Input).value.strip()
        if title:
            data["title"] = title
        if self.report and self.report.cfg.description:
            data["description"] = self.report.cfg.description
        if self.report and self.report.cfg.output:
            data["output"] = self.report.cfg.output
        source = self.source()
        if source == SQL_SOURCE:
            data["sql"] = self.query_one("#b-sql", TextArea).text.strip()
        else:
            data["dataset"] = source
            dataset = self.datasets.get(source)
            selected = list(self.query_one("#b-columns", SelectionList).selected)
            if dataset is not None:
                order = [f.name for f in dataset.fields]
                selected.sort(key=order.index)
                if selected != dataset.default_columns:
                    data["columns"] = [{"field": f, "label": self.labels[f]}
                                       if f in self.labels else f for f in selected]
            filters = [d for d in (row.definition() for row in self.query(FilterRow)) if d]
            if filters:
                data["filters"] = filters
            sort = [s.strip() for s in self.query_one("#b-sort", Input).value.split(",")
                    if s.strip()]
            if sort:
                data["sort"] = sort
        limit = self.query_one("#b-limit", Input).value.strip()
        if limit:
            data["limit"] = int(limit) if limit.lstrip("-").isdigit() else limit
        data["format"] = str(self.query_one("#b-format", Select).value)
        schedule = self.query_one("#b-schedule", Input).value.strip()
        if schedule:
            data["schedule"] = schedule
        if self.ctx.cfg.push.targets:
            push = list(self.query_one("#b-push", SelectionList).selected)
            if push:
                data["push"] = push
        if self.query_one("#b-allow-empty", Switch).value:
            data["allow_empty"] = True
        return data

    def parsed(self) -> ReportCfg | None:
        message = self.query_one("#b-message", Static)
        try:
            cfg = parse_report(self.definition())
        except ConfigError as exc:
            message.update(f"[$error]{escape('; '.join(exc.errors))}[/]")
            return None
        message.update("")
        return cfg

    # ----------------------------------------------------------------- preview

    def schedule_preview(self) -> None:
        if self._loading:
            return
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(0.5, self.refresh_preview)

    def refresh_preview(self) -> None:
        t = self.ctx.t
        status = self.query_one("#b-status", Static)
        table = self.query_one("#b-preview", DataTable)
        cfg = self.parsed()
        if cfg is None:
            status.update(f"[$warning]{escape(t('rep.preview_invalid'))}[/]")
            return
        try:
            result = run_report(cfg, self.report_ctx)
        except ReportError as exc:
            status.update(f"[$error]{escape(str(exc))}[/]")
            table.clear(columns=True)
            return
        table.clear(columns=True)
        for label, _type in result.columns:
            table.add_column(label)
        for row in result.rows[:PREVIEW_ROWS]:
            cells = []
            for value, (_label, type_) in zip(row, result.columns, strict=True):
                text = display(value, type_)
                if len(text) > CELL:
                    text = text[:CELL - 1] + "…"
                cells.append(Text(text, justify="right") if type_ == "integer" else text)
            table.add_row(*cells)
        shown = min(len(result.rows), PREVIEW_ROWS)
        text = t("rep.preview_count", shown=shown, total=result.total)
        if cfg.limit is not None and result.total > len(result.rows):
            text += " · " + t("rep.preview_limited", limit=cfg.limit)
        status.update(text)

    @on(Select.Changed, "#b-source")
    def source_changed(self) -> None:
        if self._loading:
            return
        self.fill_columns()
        for row in list(self.query(FilterRow)):
            row.remove()
        self.toggle_source()
        self.schedule_preview()

    @on(Input.Changed)
    @on(Select.Changed, ".f-field, .f-op, #b-format")
    @on(SelectionList.SelectedChanged)
    @on(TextArea.Changed)
    @on(Switch.Changed)
    def changed(self) -> None:
        self.schedule_preview()

    @on(Button.Pressed, "#b-add-filter")
    def add_filter_pressed(self) -> None:
        self.add_filter()

    # ----------------------------------------------------------------- actions

    @on(Button.Pressed, "#b-save")
    def action_save(self) -> None:
        t = self.ctx.t
        message = self.query_one("#b-message", Static)
        if not self.query_one("#b-name", Input).value.strip():
            message.update(f"[$error]{escape(t('rep.name_required'))}[/]")
            return
        cfg = self.parsed()
        if cfg is None:
            return
        existing = {r.cfg.name: r for r in catalog(self.ctx)}
        editing = self.report.cfg.name if self.report and self.report.origin == "tui" else None
        other = existing.get(cfg.name)
        if other is not None and other.origin != "tui":
            message.update(f"[$error]{escape(t('rep.file_name', name=cfg.name))}[/]")
            return
        if other is not None and cfg.name != editing:
            message.update(f"[$error]{escape(t('rep.exists', name=cfg.name))}[/]")
            return
        definition = report_definition(cfg)
        self.ctx.repo.save_report(cfg.name, definition, self.ctx.clock.now())
        if editing and editing != cfg.name:
            self.ctx.repo.delete_report(editing)
        self.report = LoadedReport(cfg, "tui")
        text = t("rep.saved", name=cfg.name)
        if cfg.schedule:
            text += " " + t("rep.schedule_hint")
        self.notify(text, timeout=8)

    @on(Button.Pressed, "#b-export")
    @work(group="report-export", exclusive=True)
    async def action_export(self) -> None:
        from snowth_my_net.tui.app import ConfirmModal

        t = self.ctx.t
        cfg = self.parsed()
        if cfg is None:
            return
        if not self.query_one("#b-name", Input).value.strip():
            self.query_one("#b-message", Static).update(
                f"[$error]{escape(t('rep.name_required'))}[/]")
            return
        try:
            generated = generate(self.ctx.loaded, self.report_ctx, cfg)
        except EmptyReport:
            self.notify(t("rep.empty", name=cfg.name), severity="warning", timeout=8)
            return
        except (ReportError, OSError) as exc:
            self.notify(str(exc), severity="error", timeout=10)
            return
        self.notify(t("rep.written", path=str(generated.path), rows=len(generated.table.rows)),
                    timeout=8)
        if cfg.push and await self.app.push_screen_wait(ConfirmModal(
                self.ctx, t("rep.confirm_push", targets=", ".join(cfg.push)), danger=False)):
            self.push(generated)

    @work(thread=True, group="report-push")
    def push(self, generated) -> None:
        outcomes, warnings = push_report(self.ctx.loaded, generated)
        for warning in warnings:
            self.app.call_from_thread(self.notify, warning, severity="warning")
        for outcome in outcomes:
            text = (f"{outcome.target}: " + ("OK" if outcome.ok else "FAILED")
                    + (f" — {outcome.detail}" if outcome.detail else ""))
            self.app.call_from_thread(self.notify, text,
                                      severity="information" if outcome.ok else "error",
                                      timeout=10)

    def action_reload(self) -> None:
        self.report_ctx = context(self.ctx.loaded, self.ctx.repo, self.ctx.clock.now())
        self.refresh_preview()

    def action_back(self) -> None:
        self.app.pop_screen()
