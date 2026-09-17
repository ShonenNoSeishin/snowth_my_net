"""Report catalog (extension files + TUI), generation to files, and push."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.reports import LoadedReport, ReportCfg
from snowth_my_net.config.validate import build
from snowth_my_net.export.atomic import atomic_write
from snowth_my_net.logs import get_logger
from snowth_my_net.reports.datasets import ReportContext
from snowth_my_net.reports.engine import ReportError, ReportTable, run_report
from snowth_my_net.reports.render import render
from snowth_my_net.state.repo import Repo

log = get_logger("reports")


class EmptyReport(ReportError):
    """The report has no row and allow_empty is false: nothing is written or pushed."""


def parse_report(data) -> ReportCfg:
    """Validate one report definition (from the TUI or an import); raises ConfigError."""
    from snowth_my_net.config.validate import ConfigError

    cfg = build(ReportCfg, data)
    problems = cfg.check()
    if problems:
        raise ConfigError(problems)
    return cfg


def report_definition(cfg: ReportCfg) -> dict:
    """The YAML/JSON shape of a report, without default values."""
    data: dict = {"name": cfg.name}
    for key in ("title", "description", "dataset", "sql"):
        if getattr(cfg, key):
            data[key] = getattr(cfg, key)
    if cfg.columns:
        data["columns"] = [c if isinstance(c, str) else
                           ({"field": c.field, "label": c.label} if c.label else c.field)
                           for c in cfg.columns]
    if cfg.filters:
        data["filters"] = [{"field": f.field, "op": f.op} | ({"value": f.value}
                                                             if f.value is not None else {})
                           for f in cfg.filters]
    if cfg.sort:
        data["sort"] = list(cfg.sort)
    if cfg.limit is not None:
        data["limit"] = cfg.limit
    data["format"] = cfg.format
    for key in ("output", "schedule"):
        if getattr(cfg, key):
            data[key] = getattr(cfg, key)
    if cfg.push:
        data["push"] = list(cfg.push)
    if cfg.allow_empty:
        data["allow_empty"] = True
    return data


def all_reports(loaded: LoadedConfig, stored: dict[str, dict]
                ) -> tuple[list[LoadedReport], list[str]]:
    """Reports from extension files, plus the valid ones created in the TUI (a file wins)."""
    result = list(loaded.reports)
    names = {r.cfg.name for r in result}
    warnings = []
    for name, definition in sorted(stored.items()):
        if name in names:
            warnings.append(f"report {name!r} from the state is shadowed by an extension file")
            continue
        try:
            result.append(LoadedReport(parse_report(definition), "tui"))
        except Exception as exc:    # a broken stored definition must not hide the others
            warnings.append(f"report {name!r} from the state is invalid: {exc}")
    for report in result:
        unknown = [t for t in report.cfg.push
                   if t not in {target.name for target in loaded.cfg.push.targets}]
        if unknown:
            warnings.append(f"report {report.cfg.name!r}: unknown push target(s) "
                            f"{', '.join(unknown)}")
    return result, warnings


def context(loaded: LoadedConfig, repo: Repo, now: int) -> ReportContext:
    from snowth_my_net.collect.custom import all_collectors

    collectors, _warnings = all_collectors(loaded.collectors, repo.custom_stored())
    return ReportContext(loaded, repo, now, collectors, list(loaded.datasets))


@dataclass
class Generated:
    cfg: ReportCfg
    table: ReportTable
    data: bytes
    path: Path | None = None
    push: list = field(default_factory=list)       # PushOutcome


def generate(loaded: LoadedConfig, ctx: ReportContext, cfg: ReportCfg, *,
             fmt: str | None = None, output: Path | None = None, write: bool = True
             ) -> Generated:
    """Run and render a report; write it atomically (default path under output/reports/)."""
    table = run_report(cfg, ctx)
    if not table.rows and not cfg.allow_empty:
        raise EmptyReport(f"report {cfg.name!r} has no row (allow_empty: true to write it "
                          "anyway)")
    data = render(table, cfg, ctx.now, fmt, loaded.cfg.export.csv.line_terminator)
    result = Generated(cfg, table, data)
    if write:
        if output is None:
            output = cfg.output_path(loaded.paths.output_dir)
            if fmt and fmt != cfg.format:
                from snowth_my_net.config.reports import EXTENSIONS

                output = output.with_suffix("." + EXTENSIONS[fmt])
        atomic_write(output, data)
        result.path = output
    return result


def push_report(loaded: LoadedConfig, generated: Generated, targets: list[str] | None = None,
                wait: bool | None = None, dry_run: bool = False) -> tuple[list, list[str]]:
    """Send a written report to its push targets (or ``targets``)."""
    from snowth_my_net.push.http import PushError, PushOutcome, build_client, push_file

    names = targets if targets is not None else generated.cfg.push
    configured = {t.name: t for t in loaded.cfg.push.targets}
    label = f"report:{generated.cfg.name}"
    outcomes, warnings = [], []
    for name in names:
        target = configured.get(name)
        if target is None:
            outcomes.append(PushOutcome(name, label, False, detail="unknown push target"))
            continue
        if generated.path is None:
            raise PushError("the report was not written")
        if dry_run:
            outcomes.append(PushOutcome(name, label, True, detail=(
                f"dry run: would POST {generated.path} ({len(generated.data)} bytes)")))
            continue
        try:
            client, target_warnings = build_client(loaded, target)
        except Exception as exc:                 # secrets or TLS: this target only
            warnings.append(str(exc))
            outcomes.append(PushOutcome(name, label, False, detail=str(exc)))
            continue
        warnings += target_warnings
        outcomes.append(push_file(client, label, generated.path,
                                  target.wait if wait is None else wait))
    return outcomes, warnings
