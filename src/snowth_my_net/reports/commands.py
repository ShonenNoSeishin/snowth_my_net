"""``report`` commands: list, fields, show, preview, run, export, import, delete."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from snowth_my_net.clock import Clock
from snowth_my_net.config.manual import ManualError
from snowth_my_net.config.reports import FilterCfg, ReportCfg
from snowth_my_net.config.validate import ConfigError, build
from snowth_my_net.logs import get_logger
from snowth_my_net.reports.engine import ReportError, display

log = get_logger("cli")
PREVIEW_ROWS = 20
TEXT_CELL = 60


def _cli():
    from snowth_my_net import cli

    return cli


def _catalog(loaded, repo):
    from snowth_my_net.reports.service import all_reports

    reports, warnings = all_reports(loaded, repo.reports_stored() if repo else {})
    for warning in warnings:
        log.warning("%s", warning)
    return reports


def _find(loaded, repo, name: str):
    reports = {r.cfg.name: r for r in _catalog(loaded, repo)}
    if name not in reports:
        raise ManualError(f"unknown report {name!r} "
                          f"({', '.join(reports) or 'none defined'}; see 'report list')")
    return reports[name]


def _state(loaded):
    from snowth_my_net.state.db import StateError

    repo = _cli()._state_readonly(loaded)
    if repo is None:
        raise StateError("no state yet (run collect first)")
    return repo


def parse_filter(text: str) -> FilterCfg:
    """``"field op value"``; ``in``/``not_in`` take a comma-separated list."""
    parts = text.split(None, 2)
    if len(parts) < 2:
        raise ManualError(f"--filter {text!r}: expected 'FIELD OP [VALUE]' "
                          "(e.g. 'vendor eq Cisco', 'last_seen older_than 7d', 'ip empty')")
    value: object = parts[2] if len(parts) == 3 else None
    if parts[1] in ("in", "not_in") and isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    try:
        flt = build(FilterCfg, {"field": parts[0], "op": parts[1], "value": value})
    except ConfigError as exc:
        raise ManualError(f"--filter {text!r}: {'; '.join(exc.errors)}") from None
    problems = flt.check()
    if problems:
        raise ManualError("; ".join(problems))
    return flt


def _adhoc(args) -> ReportCfg | None:
    if not (args.dataset or args.sql):
        if args.columns or args.filter or args.sort:
            raise ManualError("--columns, --filter and --sort need --dataset")
        return None
    data: dict = {"name": "adhoc", "title": args.dataset or "SQL query",
                  "format": args.format or "csv", "allow_empty": True}
    if args.sql:
        data["sql"] = args.sql
    else:
        data["dataset"] = args.dataset
        data["columns"] = [c.strip() for c in (args.columns or "").split(",") if c.strip()]
        data["sort"] = [c.strip() for c in (args.sort or "").split(",") if c.strip()]
    try:
        cfg = build(ReportCfg, data)
    except ConfigError as exc:
        raise ManualError("; ".join(e.removeprefix("<config>: ") for e in exc.errors)) from None
    cfg.filters = [parse_filter(f) for f in args.filter or []]
    problems = cfg.check()
    if problems:
        raise ManualError("; ".join(problems))
    return cfg


def _cell(value, type_: str) -> str:
    text = display(value, type_)
    return text if len(text) <= TEXT_CELL else text[:TEXT_CELL - 1] + "…"


# --------------------------------------------------------------------------- commands


def cmd_list(args) -> int:
    cli = _cli()
    loaded = cli.load(args)
    repo = cli._state_readonly(loaded)
    try:
        reports = _catalog(loaded, repo)
    finally:
        if repo:
            repo.conn.close()
    rows = [[r.cfg.name, r.cfg.source, r.cfg.format, r.cfg.schedule or "-",
             ",".join(r.cfg.push) or "-", r.origin, r.cfg.title] for r in reports]
    if args.json:
        cli.out_json([dict(zip(("name", "source", "format", "schedule", "push", "origin",
                                "title"), r, strict=True)) for r in rows])
    else:
        cli.out(cli.table(["NAME", "SOURCE", "FORMAT", "SCHEDULE", "PUSH", "ORIGIN", "TITLE"],
                          rows) if rows else
                "no report defined (extensions/*.yml reports:, or the Reports tab of the TUI)")
    return cli.EXIT_OK


def cmd_fields(args) -> int:
    from snowth_my_net.reports.datasets import all_datasets
    from snowth_my_net.reports.engine import sql_table_name

    cli = _cli()
    loaded = cli.load(args)
    repo = cli._state_readonly(loaded)
    from snowth_my_net.collect.custom import all_collectors

    collectors, _w = all_collectors(loaded.collectors, repo.custom_stored() if repo else {})
    if repo:
        repo.conn.close()
    datasets = all_datasets(collectors)
    if args.dataset:
        if args.dataset not in datasets:
            raise ManualError(f"unknown dataset {args.dataset!r} ({', '.join(datasets)})")
        ds = datasets[args.dataset]
        if args.json:
            cli.out_json({"dataset": ds.name, "sql_table": sql_table_name(ds.name),
                          "description": ds.description,
                          "fields": [{"name": f.name, "type": f.type, "default": f.default,
                                      "description": f.description} for f in ds.fields]})
        else:
            cli.out(f"{ds.name} — {ds.description} (SQL table: {sql_table_name(ds.name)})")
            cli.out(cli.table(["FIELD", "TYPE", "DEFAULT", "DESCRIPTION"],
                              [[f.name, f.type, "yes" if f.default else "", f.description]
                               for f in ds.fields]))
        return cli.EXIT_OK
    rows = [[ds.name, sql_table_name(ds.name), str(len(ds.fields)), ds.description]
            for ds in datasets.values()]
    if args.json:
        cli.out_json([dict(zip(("dataset", "sql_table", "fields", "description"), r,
                               strict=True)) for r in rows])
    else:
        cli.out(cli.table(["DATASET", "SQL TABLE", "FIELDS", "DESCRIPTION"], rows))
    return cli.EXIT_OK


def cmd_show(args) -> int:
    from snowth_my_net.reports.service import report_definition

    cli = _cli()
    loaded = cli.load(args)
    repo = cli._state_readonly(loaded)
    try:
        report = _find(loaded, repo, args.name)
    finally:
        if repo:
            repo.conn.close()
    definition = report_definition(report.cfg)
    if args.json:
        cli.out_json({"origin": report.origin, "definition": definition})
    else:
        cli.out(f"# origin: {report.origin}")
        cli.out(yaml.safe_dump(definition, sort_keys=False, allow_unicode=True).rstrip())
    return cli.EXIT_OK


def cmd_preview(args) -> int:
    from snowth_my_net.reports.engine import run_report
    from snowth_my_net.reports.service import context

    cli = _cli()
    loaded = cli.load(args)
    repo = _state(loaded)
    try:
        cfg = _adhoc(args)
        if cfg is None:
            if not args.name:
                raise ManualError("give a report name, or --dataset / --sql")
            cfg = _find(loaded, repo, args.name).cfg
        elif args.name:
            raise ManualError("give a report name or --dataset / --sql, not both")
        ctx = context(loaded, repo, Clock().now())
        try:
            table = run_report(cfg, ctx)
        except ReportError as exc:
            raise ManualError(str(exc)) from None
    finally:
        repo.conn.close()
    limit = args.limit if args.limit and args.limit > 0 else PREVIEW_ROWS
    rows = table.rows[:limit]
    if args.json:
        cli.out_json({"columns": table.labels, "row_count": len(table.rows),
                      "rows": [[display(v, t) for v, (_l, t) in zip(r, table.columns,
                                                                     strict=True)]
                               for r in rows]})
        return cli.EXIT_OK
    if not table.rows:
        cli.out("no row")
        return cli.EXIT_OK
    cli.out(cli.table(table.labels, [[_cell(v, t) for v, (_l, t)
                                      in zip(r, table.columns, strict=True)] for r in rows]))
    more = len(table.rows) - len(rows)
    cli.out(f"{len(table.rows)} row(s)" + (f", first {len(rows)} shown (--limit)" if more else ""))
    return cli.EXIT_OK


def cmd_run(args) -> int:
    from snowth_my_net.push.http import PushError
    from snowth_my_net.reports.service import EmptyReport, context, generate, push_report

    cli = _cli()
    loaded = cli.load(args)
    repo = _state(loaded)
    results, outcomes, warnings, failed = [], [], [], []
    try:
        adhoc = _adhoc(args)
        if adhoc is not None:
            if args.names or args.all:
                raise ManualError("give report names or --dataset / --sql, not both")
            if args.output is None:
                args.output = "-"
            reports = [adhoc]
        elif args.all:
            reports = [r.cfg for r in _catalog(loaded, repo)]
        elif args.names:
            reports = [_find(loaded, repo, name).cfg for name in args.names]
        else:
            raise ManualError("give report names, --all, or --dataset / --sql")
        if args.output and len(reports) > 1:
            raise ManualError("--output needs exactly one report")
        ctx = context(loaded, repo, Clock().now())
        for cfg in reports:
            to_stdout = args.output == "-"
            output = None if to_stdout or not args.output else Path(args.output)
            try:
                generated = generate(loaded, ctx, cfg, fmt=args.format, output=output,
                                     write=not to_stdout)
            except EmptyReport as exc:
                log.warning("%s", exc)
                failed.append((cfg.name, str(exc)))
                continue
            except ReportError as exc:
                log.error("report %s: %s", cfg.name, exc)
                failed.append((cfg.name, str(exc)))
                continue
            if to_stdout:
                sys.stdout.flush()
                sys.stdout.buffer.write(generated.data)
                sys.stdout.buffer.flush()
                continue
            results.append(generated)
            targets = [args.target] if args.target else None
            if not args.no_push and (targets or cfg.push):
                try:
                    pushed, push_warnings = push_report(loaded, generated, targets,
                                                        args.wait, args.dry_run)
                except PushError as exc:
                    raise ManualError(str(exc)) from None
                outcomes += pushed
                warnings += push_warnings
    finally:
        repo.conn.close()
    if args.output == "-":
        return cli.EXIT_PARTIAL if failed else cli.EXIT_OK
    for warning in warnings:
        log.warning("%s", warning)
    code = cli.EXIT_PARTIAL if failed or any(not o.ok for o in outcomes) else cli.EXIT_OK
    if args.json:
        cli.out_json({"written": [{"report": g.cfg.name, "path": str(g.path),
                                   "rows": len(g.table.rows)} for g in results],
                      "failed": [{"report": n, "reason": r} for n, r in failed],
                      "push": [o.as_dict() for o in outcomes], "exit_code": code})
        return code
    for g in results:
        cli.out(f"wrote {g.path} ({len(g.table.rows)} row(s))")
    for name, reason in failed:
        cli.out(f"FAILED {name}: {reason}")
    if outcomes:
        cli._push_summary(outcomes, [], False)
    return code


def cmd_export(args) -> int:
    from snowth_my_net.reports.service import report_definition

    cli = _cli()
    loaded = cli.load(args)
    repo = cli._state_readonly(loaded)
    try:
        reports = [r for r in _catalog(loaded, repo)
                   if (args.names and r.cfg.name in args.names)
                   or (not args.names and r.origin == "tui")]
    finally:
        if repo:
            repo.conn.close()
    missing = set(args.names or ()) - {r.cfg.name for r in reports}
    if missing:
        raise ManualError(f"unknown report(s): {', '.join(sorted(missing))}")
    cli.out("# Reports; can be saved as extensions/<name>.yml")
    cli.out(yaml.safe_dump({"version": 1, "reports": [report_definition(r.cfg)
                                                      for r in reports]},
                           sort_keys=False, allow_unicode=True).rstrip())
    return cli.EXIT_OK


def cmd_import(args) -> int:
    from snowth_my_net.reports.service import parse_report, report_definition

    cli = _cli()
    loaded = cli.load(args)
    try:
        data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ManualError(f"cannot read {args.file}: {exc}") from None
    items = data.get("reports", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ManualError("expected a reports: list")
    parsed = [parse_report(item) for item in items]
    file_names = {r.cfg.name for r in loaded.reports}
    shadowed = [cfg.name for cfg in parsed if cfg.name in file_names]
    if shadowed:
        raise ManualError(f"defined in an extension file already: {', '.join(shadowed)}")
    repo = cli._state_rw(loaded)
    try:
        for cfg in parsed:
            repo.save_report(cfg.name, report_definition(cfg), Clock().now())
    finally:
        repo.conn.close()
    cli.out(f"imported {len(parsed)} report(s)")
    return cli.EXIT_OK


def cmd_delete(args) -> int:
    cli = _cli()
    loaded = cli.load(args)
    if any(r.cfg.name == args.name for r in loaded.reports):
        raise ManualError(f"{args.name!r} comes from an extension file; delete it there")
    repo = cli._state_rw(loaded)
    try:
        deleted = repo.delete_report(args.name)
    finally:
        repo.conn.close()
    cli.out(f"{args.name}: {'deleted' if deleted else 'not found'}")
    return cli.EXIT_OK if deleted else cli.EXIT_PARTIAL


# --------------------------------------------------------------------------- parser


def _adhoc_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("ad-hoc report (instead of a name)")
    group.add_argument("--dataset", help="dataset to read (see 'report fields')")
    group.add_argument("--columns", help="comma-separated fields (default: the dataset's)")
    group.add_argument("--filter", action="append", metavar="'FIELD OP [VALUE]'",
                       help="e.g. 'vendor eq Cisco', 'last_seen older_than 7d' (repeatable)")
    group.add_argument("--sort", help="comma-separated fields, '-field' for descending")
    group.add_argument("--sql", help="read-only SELECT over the dataset tables")


def add_parser(sub, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("report", parents=[common],
                       help="custom reports: datasets, filters, SQL; CSV/JSON/Markdown/HTML")
    rsub = p.add_subparsers(title="report commands", metavar="ACTION", required=True)
    r = rsub.add_parser("list", parents=[common], help="reports and where they come from")
    r.set_defaults(func=cmd_list)
    r = rsub.add_parser("fields", parents=[common], help="datasets, or the fields of one")
    r.add_argument("dataset", nargs="?")
    r.set_defaults(func=cmd_fields)
    r = rsub.add_parser("show", parents=[common], help="print a report definition")
    r.add_argument("name")
    r.set_defaults(func=cmd_show)
    r = rsub.add_parser("preview", parents=[common], help="print the first rows in the terminal")
    r.add_argument("name", nargs="?")
    r.add_argument("--limit", type=int, default=PREVIEW_ROWS,
                   help=f"rows shown (default {PREVIEW_ROWS})")
    r.add_argument("--format", help=argparse.SUPPRESS)
    _adhoc_arguments(r)
    r.set_defaults(func=cmd_preview)
    r = rsub.add_parser("run", parents=[common],
                        help="write reports (output/reports/) and push them to their targets")
    r.add_argument("names", nargs="*", metavar="NAME")
    r.add_argument("--all", action="store_true", help="every report")
    r.add_argument("--format", choices=["csv", "json", "markdown", "html"],
                   help="override the report format")
    r.add_argument("--output", "-o", help="destination file, '-' for stdout")
    r.add_argument("--no-push", action="store_true", help="do not push")
    r.add_argument("--target", help="push to this target (instead of the report's push:)")
    r.add_argument("--wait", action="store_true", default=None,
                   help="wait for 202 jobs to finish (poll:)")
    r.add_argument("--dry-run", action="store_true", help="show what would be pushed")
    _adhoc_arguments(r)
    r.set_defaults(func=cmd_run)
    r = rsub.add_parser("export", parents=[common],
                        help="print reports as YAML (default: those created in the TUI)")
    r.add_argument("names", nargs="*", metavar="NAME")
    r.set_defaults(func=cmd_export)
    r = rsub.add_parser("import", parents=[common], help="store reports from a YAML file")
    r.add_argument("file")
    r.set_defaults(func=cmd_import)
    r = rsub.add_parser("delete", parents=[common], help="delete a report created in the TUI")
    r.add_argument("name")
    r.set_defaults(func=cmd_delete)
