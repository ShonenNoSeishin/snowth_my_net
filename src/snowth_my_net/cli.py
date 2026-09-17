"""Command-line interface.

Exit codes: 0 OK · 1 partial failure · 2 configuration or usage error ·
3 the state is locked by another run beyond the allowed wait · 130 interrupted.
Human-readable output on stdout (``--json`` for scripts), logs on stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import tempfile
from importlib import resources
from pathlib import Path

from snowth_my_net import __version__
from snowth_my_net.clock import Clock, iso_z
from snowth_my_net.collect.check import check_devices, config_warnings, secret_warnings
from snowth_my_net.collect.discovery import PlannedTarget, plan_targets, resolve_seeds
from snowth_my_net.collect.engine import Collector, RunReport
from snowth_my_net.collect.identify import effective_type
from snowth_my_net.collect.probe import ProbeInputError
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig, find_config, load_config
from snowth_my_net.config.manual import ManualError, normalize_address
from snowth_my_net.config.validate import ConfigError
from snowth_my_net.export.atomic import atomic_write
from snowth_my_net.export.naming import base_name
from snowth_my_net.export.run import export, exported_devices
from snowth_my_net.lock import LockBusy, StateLock
from snowth_my_net.logs import REDACTOR, get_logger, setup_logging
from snowth_my_net.snmp.target import AddressError, parse_target, split_host_port
from snowth_my_net.state.db import StateError, open_db
from snowth_my_net.state.repo import Repo

EXIT_OK, EXIT_PARTIAL, EXIT_CONFIG, EXIT_LOCKED, EXIT_INTERRUPTED = 0, 1, 2, 3, 130

log = get_logger("cli")


# --------------------------------------------------------------------------- output helpers


def out(text: str = "") -> None:
    sys.stdout.write(REDACTOR.redact(text) + "\n")


def out_json(data: object) -> None:
    out(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def table(headers: list[str], rows: list[list[object]]) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
              for r in cells]
    return "\n".join(lines)


# --------------------------------------------------------------------------- common plumbing


def load(args: argparse.Namespace) -> LoadedConfig:
    loaded = load_config(find_config(args.config), state_dir=args.state_dir,
                         output_dir=args.output_dir)
    general = loaded.cfg.general
    setup_logging(args.log_level or general.log_level, args.log_file or general.log_file,
                  args.quiet)
    return loaded


class Locked:
    """Hold the state lock for the duration of a writing command."""

    def __init__(self, loaded: LoadedConfig, command: str, wait: float) -> None:
        self.lock = StateLock(loaded.paths.lock_file, command)
        self.wait = wait

    def __enter__(self) -> Locked:
        self.lock.acquire(self.wait)
        return self

    def __exit__(self, *exc: object) -> None:
        self.lock.release()


def resolved_credentials(loaded: LoadedConfig):
    creds, warnings = loaded.resolve_credentials()
    for warning in warnings:
        log.warning("%s", warning)
    return creds


# --------------------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    dest = Path(args.output or args.config or "snowth_my_net.yml")
    if dest.exists() and not args.force:
        log.error("%s already exists (use --force to overwrite)", dest)
        return EXIT_CONFIG
    text = resources.files("snowth_my_net.config").joinpath("example.yml").read_text("utf-8")
    atomic_write(dest, text.encode("utf-8"), mode=0o640)
    out(f"Wrote {dest}.")
    out("Next steps:")
    out("  1. put each secret in its own file under general.secrets_dir, chmod 600")
    out("     (e.g. /etc/snowth_my_net/secrets/snmp_v3_auth), or use *_env variables;")
    out("  2. edit discovery.seeds / discovery.allowed;")
    out(f"  3. run: snowth_my_net --config {dest} check")
    return EXIT_OK


def _report_dict(report: RunReport) -> dict:
    devices = []
    for r in report.results:
        ident = r.ident
        if ident is not None:
            ident = dataclasses.replace(ident)
            ident.device_type, ident.type_rule, ident.type_reason = effective_type(
                ident.device_type, ident.type_rule, ident.type_reason, r.settings.type,
                r.settings.source("type"))
        devices.append({
            "address": str(r.target), "origin": r.origin, "status": r.status,
            "alias_of": str(r.alias_of.target) if r.alias_of else None,
            "credential": r.credential, "attempts": [list(a) for a in r.attempts],
            "error": r.error, "sys_name": r.system.name if r.system else None,
            "vendor": ident.vendor if ident else None, "model": ident.model if ident else None,
            "serial": ident.serial if ident else None,
            "os": ident.os_name if ident else None,
            "os_version": ident.os_version if ident else None,
            "device_type": ident.device_type if ident else None,
            "type_rule": ident.type_rule if ident else None,
            "type_reason": ident.type_reason if ident else None,
            "base_mac": r.system.base_mac if r.system else None,
            "duration_s": r.duration_s, "warnings": r.warnings,
            "functions": {name: {"status": o.status, "rows": o.rows, "ms": o.duration_ms,
                                 "detail": o.detail} for name, o in r.outcomes.items()},
        })
    return {"run_id": report.run_id, "command": report.command, "status": report.status,
            "exit_code": report.exit_code, "stats": report.stats, "errors": report.errors,
            "notes": report.notes, "devices": devices}


def _render_report(report: RunReport, loaded: LoadedConfig) -> str:
    rows = []
    for r in sorted(report.results, key=lambda x: x.target.sort_key()):
        name = base_name(r.system.name if r.system else "", r.target.host, r.settings.name,
                         loaded.cfg.general.device_name) if r.system else "-"
        ident = r.ident
        if ident is not None:
            ident = dataclasses.replace(ident, device_type=effective_type(
                ident.device_type, ident.type_rule, ident.type_reason, r.settings.type,
                r.settings.source("type"))[0])
        if r.alias_of is not None:
            status = f"alias of {r.alias_of.target}"
        else:
            status = r.status
            bad = [f"{o.function}:{o.status}" for o in r.outcomes.values()
                   if o.status not in ("ok", "absent", "skipped")]
            if bad:
                status += f" ({', '.join(bad)})"
        rows.append([name, str(r.target), status, r.credential or "-",
                     (ident.device_type or "-") if ident else "-",
                     (ident.vendor or "-") if ident else "-",
                     (ident.model or "-") if ident else "-", f"{r.duration_s:.1f}s"])
    lines = [table(["DEVICE", "ADDRESS", "STATUS", "CREDENTIAL", "TYPE", "VENDOR", "MODEL",
                    "TIME"], rows)] if rows else []
    for r in report.results:
        if r.error:
            lines.append(f"{r.target}: {r.error}")
    s = report.stats
    lines.append(f"{report.command} run {report.run_id or '(dry run)'}: {report.status} — "
                 f"{s.get('devices', 0)} device(s), {s.get('reachable', 0)} reachable, "
                 f"{s.get('failing', 0)} failing, {s.get('aliases', 0)} alias(es), "
                 f"{s.get('duration_s', 0)}s")
    lines += [f"note: {n}" for n in report.notes]
    lines += [f"error: {e}" for e in report.errors]
    return "\n".join(lines)


def cmd_collect(args: argparse.Namespace, mode: str = "collect") -> int:
    loaded = load(args)
    cfg = loaded.cfg
    creds = resolved_credentials(loaded)
    only = set(args.device) if args.device else None
    wait = cfg.general.lock_wait.collect if mode == "collect" else cfg.general.lock_wait.default
    if getattr(args, "dry_run", False):
        report = asyncio.run(Collector(loaded, None, creds, Clock(), mode).run(only))
    else:
        with Locked(loaded, mode, wait):
            conn = open_db(loaded.paths.state_file)
            try:
                report = asyncio.run(Collector(loaded, Repo(conn), creds, Clock(), mode).run(only))
            finally:
                conn.close()
    if args.json:
        out_json(_report_dict(report))
    else:
        out(_render_report(report, loaded))
    return report.exit_code


def cmd_discover(args: argparse.Namespace) -> int:
    return cmd_collect(args, mode="discover")


def cmd_export(args: argparse.Namespace) -> int:
    loaded = load(args)
    only = [f.strip() for f in args.only.split(",")] if args.only else None
    with Locked(loaded, "export", loaded.cfg.general.lock_wait.default):
        conn = open_db(loaded.paths.state_file)
        try:
            result = export(loaded, Repo(conn), Clock(), only)
        finally:
            conn.close()
    if args.json:
        out_json({"written": [str(p) for p in result.written], "failed": result.failed,
                  "pending": result.pending, "exit_code": result.exit_code})
    else:
        for path in result.written:
            out(f"wrote {path}")
        for name, reason in result.failed:
            out(f"FAILED {name}: {reason}")
    return result.exit_code


def cmd_show(args: argparse.Namespace) -> int:
    loaded = load(args)
    conn = open_db(loaded.paths.state_file, readonly=True)
    try:
        repo = Repo(conn)
        if args.what == "devices":
            devices, names = exported_devices(loaded, repo, Clock().now())
            data = [{
                "name": names[d["id"]], "ip": split_host_port(d["mgmt_address"])[0],
                "address": d["mgmt_address"], "vendor": d["vendor"], "model": d["model"],
                "serial": d["serial"], "os": d["os_name"], "os_version": d["os_version"],
                "device_type": d["device_type"], "type_rule": d["type_rule"],
                "type_reason": d["type_reason"], "base_mac": d["base_mac"],
                "location": d["sys_location"], "credential": d["credential"],
                "last_seen": iso_z(d["last_seen"]), "last_collect": d["last_collect_status"],
            } for d in devices]
            data.sort(key=lambda x: x["name"].casefold())
            if args.json:
                out_json(data)
            else:
                out(table(["NAME", "IP", "VENDOR", "MODEL", "OS", "TYPE", "TYPE RULE", "STATUS",
                           "LAST SEEN"],
                          [[x["name"], x["ip"], x["vendor"] or "", x["model"] or "",
                            f"{x['os'] or ''} {x['os_version'] or ''}".strip(),
                            x["device_type"] or "", x["type_rule"] or "",
                            x["last_collect"] or "", x["last_seen"]] for x in data]))
        elif args.what == "nodes":
            from snowth_my_net.merge.view import build_view

            headers = ["MAC", "VENDOR", "IP", "DNS", "SWITCH", "PORT", "VLAN", "LAST SEEN"]
            rows = build_view(loaded, repo, Clock().now()).rows()
            if args.filter:
                needle = args.filter.casefold()
                rows = [r for r in rows if any(needle in c.casefold() for c in r)]
            if args.limit:
                rows = rows[:args.limit]
            if args.json:
                keys = ["mac", "vendor", "ip", "dns_name", "switch", "port", "vlan", "last_seen"]
                out_json([dict(zip(keys, r, strict=True)) for r in rows])
            else:
                out(table(headers, rows))
                out(f"{len(rows)} row(s)")
        else:
            runs = [dict(r) for r in repo.recent_runs(args.limit or 20)]
            if args.json:
                out_json(runs)
            else:
                out(table(["ID", "COMMAND", "STARTED", "FINISHED", "STATUS"],
                          [[r["id"], r["command"], iso_z(r["started_at"]),
                            iso_z(r["finished_at"]), r["status"] or "running"] for r in runs]))
    finally:
        conn.close()
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    loaded = load(args)
    cfg, paths = loaded.cfg, loaded.paths
    creds = resolved_credentials(loaded)
    warnings = config_warnings(loaded) + secret_warnings(creds)

    known = []
    state_line = f"no state yet at {paths.state_file}"
    if paths.state_file.exists():
        try:
            conn = open_db(paths.state_file, readonly=True)
            repo = Repo(conn)
            known = repo.targets()
            last = repo.last_successful_collect()
            state_line = (f"{paths.state_file}: last successful collect "
                          f"{iso_z(last['finished_at'])} ({last['status']})" if last
                          else f"{paths.state_file}: no successful collect yet")
            conn.close()
        except StateError as exc:
            state_line = f"{paths.state_file}: {exc}"
    try:
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=paths.output_dir, prefix=".check-"):
            pass
        output_line = f"{paths.output_dir}: writable"
    except OSError as exc:
        output_line = f"{paths.output_dir}: NOT writable ({exc.strerror})"
        warnings.append(f"output directory {paths.output_dir} is not writable")

    seeds = asyncio.run(resolve_seeds(cfg))
    only = set(args.addresses) if args.addresses else None
    planned, notes = plan_targets(cfg, seeds.targets, known, only)
    if only:
        listed = {str(p.target) for p in planned}
        for address in args.addresses:
            target = parse_target(address)
            if str(target) not in listed:
                planned.append(PlannedTarget(target, "cli"))
    results = asyncio.run(check_devices(loaded, creds, planned, args.quick))

    if args.save:
        with Locked(loaded, "check", cfg.general.lock_wait.default):
            conn = open_db(paths.state_file)
            try:
                repo = Repo(conn)
                now = Clock().now()
                for dc in results:
                    if dc.reachable:
                        repo.remember_credential(dc.address, dc.credential, now)
            finally:
                conn.close()

    failed = [dc for dc in results if dc.failed and not dc.tolerated]
    if args.json:
        out_json({
            "config": str(paths.config_file), "state": state_line, "output": output_line,
            "warnings": warnings, "seed_errors": seeds.errors, "notes": notes,
            "devices": [{
                "address": dc.address, "reachable": dc.reachable, "credential": dc.credential,
                "attempts": [list(a) for a in dc.attempts], "rtt_ms": dc.rtt_ms,
                "sys_name": dc.sys_name, "sys_object_id": dc.object_id,
                "vendor": dc.ident.vendor if dc.ident else None,
                "model": dc.ident.model if dc.ident else None,
                "os": dc.ident.os_name if dc.ident else None,
                "os_version": dc.ident.os_version if dc.ident else None,
                "device_type": dc.ident.device_type if dc.ident else None,
                "type_rule": dc.ident.type_rule if dc.ident else None,
                "type_reason": dc.ident.type_reason if dc.ident else None,
                "mibs": dc.mibs, "warnings": dc.warnings, "error": dc.error,
            } for dc in results],
            "exit_code": EXIT_PARTIAL if failed or seeds.errors else EXIT_OK,
        })
    else:
        out(f"config   {paths.config_file}: OK ({len(cfg.credentials)} credential(s), "
            f"{len(cfg.discovery.seeds)} seed(s))")
        out(f"state    {state_line}")
        out(f"output   {output_line}")
        for w in warnings:
            out(f"warning  {w}")
        for e in seeds.errors:
            out(f"error    {e}")
        for n in notes:
            out(f"note     {n}")
        for dc in sorted(results, key=lambda d: d.address):
            out("")
            if not dc.reachable:
                out(f"{dc.address}  UNREACHABLE — {dc.error}"
                    + ("  (tolerate_failure)" if dc.tolerated else ""))
                continue
            ident = dc.ident
            out(f"{dc.address}  {dc.sys_name or '(no sysName)'}  credential {dc.credential}  "
                f"{dc.rtt_ms} ms")
            if ident:
                typ = (f"{ident.device_type} ({ident.type_rule}: {ident.type_reason})"
                       if ident.device_type else "(empty: no sure evidence)")
                out(f"  identity  {ident.vendor or '?'} {ident.model or '?'}  "
                    f"{ident.os_name or '?'} {ident.os_version or ''}".rstrip())
                out(f"  type      {typ}")
            out("  mibs      " + "  ".join(f"{k} {v}" for k, v in dc.mibs.items()))
            for w in dc.warnings:
                out(f"  warning   {w}")
    return EXIT_PARTIAL if failed or seeds.errors else EXIT_OK


def _state_readonly(loaded: LoadedConfig) -> Repo | None:
    if not loaded.paths.state_file.exists():
        return None
    try:
        return Repo(open_db(loaded.paths.state_file, readonly=True))
    except StateError as exc:
        log.warning("state: %s", exc)
        return None


def _state_facts(repo: Repo | None, target) -> tuple[dict, str | None, dict | None]:
    """(manual settings, remembered credential, stored device row) for one address."""
    if repo is None:
        return {}, None, None
    manual = repo.manual_settings()
    row = repo.conn.execute("SELECT credential, device_id FROM targets WHERE address = ?",
                            (str(target),)).fetchone()
    device = repo.find_device(str(target))
    if row is None and device is not None:
        row = repo.conn.execute("SELECT credential, device_id FROM targets WHERE device_id = ? "
                                "AND is_alias = 0", (device["id"],)).fetchone()
    return manual, row["credential"] if row else None, dict(device) if device else None


def cmd_probe(args: argparse.Namespace) -> int:
    from snowth_my_net.collect.identify import identify
    from snowth_my_net.collect.model import TypeEvidence
    from snowth_my_net.collect.presets import get_preset, suggestions
    from snowth_my_net.collect.probe import connect, parse_oid_input, run_oid, run_preset
    from snowth_my_net.snmp.client import EnginePool

    loaded = load(args)
    creds = resolved_credentials(loaded)
    target = parse_target(args.address)
    repo = _state_readonly(loaded)
    manual, remembered, stored = _state_facts(repo, target)
    if repo:
        repo.conn.close()
    items = []
    for item in args.items:
        preset = get_preset(item)
        items.append(preset if preset else parse_oid_input(item))
    if args.limit < 1:
        raise ProbeInputError("--limit must be at least 1")

    async def go():
        pool = EnginePool()
        try:
            conn = await connect(loaded, creds, target, pool, manual, remembered)
            if not conn.ok:
                return conn, None, "", []
            ident = identify(conn.system, [], TypeEvidence(), conn.settings.type,
                             override_source=conn.settings.source("type"))
            device_type, rule = ident.device_type, ident.type_rule
            if not device_type and stored and stored["device_type"]:
                device_type, rule = stored["device_type"], stored["type_rule"]
            timeout = float(conn.settings.snmp.table_timeout)
            pen = conn.system.pen
            results = []
            if not items:
                for preset, suggested in suggestions(device_type):
                    if suggested or args.all:
                        table = await run_preset(conn.client, preset, "en", 1, pen, timeout)
                        results.append((preset, suggested, table))
            else:
                for item in items:
                    if isinstance(item, tuple):
                        table = await run_oid(conn.client, item, args.mode, args.limit, timeout)
                    else:
                        table = await run_preset(conn.client, item, "en", args.limit, pen,
                                                 timeout)
                    results.append((item, None, table))
            return conn, device_type, rule, results
        finally:
            pool.close()

    conn, device_type, rule, results = asyncio.run(go())
    if not conn.ok:
        if args.json:
            out_json({"address": str(target), "reachable": False, "error": conn.error,
                      "attempts": [list(a) for a in conn.attempts]})
        else:
            out(f"{target}: UNREACHABLE — {conn.error}")
        return EXIT_PARTIAL
    failed = any(t.status in ("error", "timeout") for _i, _s, t in results) if items else False
    header = (f"{target}  {conn.system.name or '(no sysName)'} — type "
              f"{device_type or '(empty)'}{f' ({rule})' if rule else ''} — credential "
              f"{conn.credential} — {conn.rtt_ms} ms")
    if args.json:
        payload = {"address": str(target), "reachable": True, "sys_name": conn.system.name,
                   "credential": conn.credential, "device_type": device_type or "",
                   "type_rule": rule}
        if items:
            payload["results"] = [t.as_dict() for _i, _s, t in results]
        else:
            payload["presets"] = [{"name": p.name, "suggested": s, "status": t.status,
                                   "title": p.title_en, "detail": t.detail}
                                  for p, s, t in results]
        out_json(payload)
        return EXIT_PARTIAL if failed else EXIT_OK
    out(header)
    if not items:
        out("")
        out(table(["PRESET", "", "STATUS", "DESCRIPTION"],
                  [[p.name, "*" if s else "", t.status, p.title_en] for p, s, t in results]))
        out("")
        hidden = "" if args.all else "; --all also tries the presets not suggested for this type"
        out(f"* suggested for the type. Run: snowth_my_net probe {target} PRESET{hidden}")
        return EXIT_OK
    for _item, _s, t in results:
        out("")
        out(f"{t.title} — {t.status}, {len(t.rows)} row(s), {t.requests} request(s), "
            f"{t.duration_ms} ms" + (f" — {t.detail}" if t.detail else ""))
        if t.rows:
            out(table(t.headers, t.rows))
        if t.truncated:
            out(f"(stopped at {args.limit} rows per column; use --limit)")
    return EXIT_PARTIAL if failed else EXIT_OK


def _settings_rows(loaded: LoadedConfig, host: str, manual: dict) -> list[list[str]]:
    from snowth_my_net.config.manual import MANUAL_KEYS

    effective = settings_for(loaded.cfg, host, manual)
    rows = []
    for key in MANUAL_KEYS:
        value = effective.get(key)
        shown = ",".join(value) if isinstance(value, list) else ("" if value is None else value)
        rows.append([key, str(shown), effective.source(key)])
    return rows


def cmd_device_show(args: argparse.Namespace) -> int:
    loaded = load(args)
    host = normalize_address(args.address)
    repo = _state_readonly(loaded)
    manual, _cred, stored = _state_facts(repo, parse_target(args.address))
    if repo:
        repo.conn.close()
    rows = _settings_rows(loaded, host, manual)
    if args.json:
        out_json({"address": host, "settings": [dict(zip(("key", "value", "source"), r,
                                                         strict=True)) for r in rows],
                  "detected_type": stored["device_type"] if stored else None,
                  "detected_rule": stored["type_rule"] if stored else None})
        return EXIT_OK
    if stored:
        out(f"{host}  {stored['sys_name'] or ''} — detected type "
            f"{stored['device_type'] or '(empty)'} ({stored['type_rule'] or 'no evidence'})")
    else:
        out(f"{host}  (never collected)")
    out(table(["SETTING", "VALUE", "SOURCE"], rows))
    out("Sources: manual = set by hand (wins), config = config.yml, default = built-in.")
    return EXIT_OK


def _state_rw(loaded: LoadedConfig) -> Repo:
    return Repo(open_db(loaded.paths.state_file))


def cmd_device_set(args: argparse.Namespace) -> int:
    from snowth_my_net.config.manual import parse_assignment

    loaded = load(args)
    host = normalize_address(args.address)
    values = dict(parse_assignment(a, loaded.cfg) for a in args.assignments)
    repo = _state_rw(loaded)
    try:
        repo.set_manual(host, values, Clock().now())
        manual = repo.manual_settings()
    finally:
        repo.conn.close()
    if args.json:
        out_json({"address": host, "set": values})
    else:
        for key, value in values.items():
            out(f"{host}: {key} = {value}  (manual)")
        if "type" in values:
            out("The type is a label: it never prevents a collection (ARP, MAC tables, LLDP "
                "and CDP are always attempted unless a feature is set to off).")
    del manual
    return EXIT_OK


def cmd_device_unset(args: argparse.Namespace) -> int:
    from snowth_my_net.config.manual import check_key

    loaded = load(args)
    host = normalize_address(args.address)
    if not args.keys and not args.all:
        raise ManualError("give the keys to remove, or --all")
    keys = None if args.all else [check_key(k) for k in args.keys]
    repo = _state_rw(loaded)
    try:
        removed = repo.unset_manual(host, keys)
    finally:
        repo.conn.close()
    out(f"{host}: {removed} manual value(s) removed")
    return EXIT_OK


def cmd_device_add(args: argparse.Namespace) -> int:
    loaded = load(args)
    target = parse_target(args.address)
    excluded = [n for n in loaded.cfg.discovery.exclude
                if n and n.version == target.ip.version and target.ip in n]
    if excluded:
        raise ManualError(f"{target} is inside discovery.exclude ({excluded[0]}); "
                          "remove it from the exclusions first")
    repo = _state_rw(loaded)
    try:
        repo.ensure_target(str(target), "manual", 0, Clock().now())
    finally:
        repo.conn.close()
    out(f"{target} added; it will be polled by the next collect "
        f"(try now: snowth_my_net check {target})")
    return EXIT_OK


def cmd_device_remove(args: argparse.Namespace) -> int:
    loaded = load(args)
    target = parse_target(args.address)
    repo = _state_rw(loaded)
    try:
        repo.remove_target(str(target))
    finally:
        repo.conn.close()
    out(f"{target} forgotten (device, history and manual settings)")
    seeds = asyncio.run(resolve_seeds(loaded.cfg)).targets
    if any(str(t) == str(target) for t, _ in seeds):
        out("Note: it is a seed in config.yml, so the next collect will find it again. "
            "To stop polling it, use: snowth_my_net device set "
            f"{target.host} disabled=true")
    return EXIT_OK


def cmd_device_export(args: argparse.Namespace) -> int:
    import yaml

    from snowth_my_net.config.manual import to_override_entries

    loaded = load(args)
    repo = _state_readonly(loaded)
    manual = repo.manual_settings() if repo else {}
    if repo:
        repo.conn.close()
    entries = to_override_entries(manual)
    if args.json:
        out_json({"devices": entries})
    else:
        out("# Manual settings exported by snowth_my_net; paste under devices: in config.yml")
        out(yaml.safe_dump({"devices": entries}, sort_keys=False, allow_unicode=True).rstrip())
    return EXIT_OK


def cmd_device_import(args: argparse.Namespace) -> int:
    import yaml

    from snowth_my_net.config.manual import from_override_entries

    loaded = load(args)
    try:
        data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManualError(f"cannot read {args.file}: {exc}") from None
    if isinstance(data, dict):
        data = data.get("devices")
    settings = from_override_entries(data, loaded.cfg)
    repo = _state_rw(loaded)
    now = Clock().now()
    try:
        for address, values in settings.items():
            if args.replace:
                repo.unset_manual(address)
            if values:
                repo.set_manual(address, values, now)
    finally:
        repo.conn.close()
    out(f"imported manual settings for {len(settings)} address(es)")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    from snowth_my_net.merge.explain import explain, node_json
    from snowth_my_net.merge.view import build_view

    loaded = load(args)
    conn = open_db(loaded.paths.state_file, readonly=True)
    try:
        view = build_view(loaded, Repo(conn), Clock().now())
        nodes = view.find(args.query)
        if args.json:
            out_json({"query": args.query, "nodes": [node_json(view, n) for n in nodes]})
        else:
            for text, _kind in explain(view, args.query):
                out(text)
    finally:
        conn.close()
    return EXIT_OK if nodes else EXIT_PARTIAL


def cmd_oui_update(args: argparse.Namespace) -> int:
    from snowth_my_net.enrich.oui import update_database

    loaded = load(args)
    source = Path(args.from_file) if args.from_file else None
    try:
        count = update_database(loaded.paths.oui_file, loaded.cfg.oui.urls, source)
    except (OSError, ValueError) as exc:
        log.error("oui-update failed: %s (the current database is kept)", exc)
        return EXIT_PARTIAL
    out(f"{loaded.paths.oui_file}: {count} vendor prefixes")
    return EXIT_OK


def cmd_tui(args: argparse.Namespace) -> int:
    loaded = load(args)
    general = loaded.cfg.general
    setup_logging(args.log_level or general.log_level, args.log_file or general.log_file,
                  args.quiet, stderr_output=False)
    from snowth_my_net.tui.app import run_tui

    return run_tui(loaded)


def cmd_version(args: argparse.Namespace) -> int:
    out(f"snowth_my_net {__version__}")
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def _common(parser: argparse.ArgumentParser, suppress: bool) -> None:
    d = (lambda value: argparse.SUPPRESS) if suppress else (lambda value: value)
    parser.add_argument("-c", "--config", default=d(None),
                        help="configuration file (default: $SNOWTH_CONFIG, ./snowth_my_net.yml, "
                             "/etc/snowth_my_net/config.yml)")
    parser.add_argument("--state-dir", default=d(None), help="override general.state_dir")
    parser.add_argument("--output-dir", default=d(None), help="override general.output_dir")
    parser.add_argument("--json", action="store_true", default=d(False),
                        help="machine-readable output on stdout")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"],
                        default=d(None))
    parser.add_argument("--log-file", default=d(None), help="also log to this file")
    parser.add_argument("-q", "--quiet", action="store_true", default=d(False),
                        help="only warnings and errors on stderr")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snowth_my_net",
        description="Lightweight, read-only SNMP network mapper.",
        epilog="Exit codes: 0 OK, 1 partial failure, 2 configuration error, 3 state locked.",
    )
    _common(parser, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    _common(common, suppress=True)
    sub = parser.add_subparsers(title="commands", metavar="COMMAND")

    p = sub.add_parser("init", parents=[common], help="write a commented example configuration")
    p.add_argument("--output", "-o", help="destination file")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", parents=[common],
                       help="diagnose configuration, credentials and MIB support per device")
    p.add_argument("addresses", nargs="*", help="only these addresses (default: every target)")
    p.add_argument("--quick", action="store_true", help="one request per MIB instead of counting")
    p.add_argument("--save", action="store_true", help="remember working credentials")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("discover", parents=[common],
                       help="identify devices (seeds, sweep) without collecting tables")
    p.add_argument("--device", action="append", metavar="ADDR", help="only this address")
    p.add_argument("--dry-run", action="store_true", help="do not write the state")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("collect", parents=[common], help="poll every device and update the state")
    p.add_argument("--device", action="append", metavar="ADDR", help="only this address")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("export", parents=[common], help="write CSV/JSON/map outputs")
    p.add_argument("--only", help="comma-separated subset: devices,nodes,links,snapshot,map")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("show", parents=[common], help="print what the state knows")
    p.add_argument("what", choices=["devices", "nodes", "runs"])
    p.add_argument("--limit", type=int, default=0,
                   help="maximum rows (default: 20 runs, every device and node)")
    p.add_argument("--filter", help="only rows containing this text (any column)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("probe", parents=[common],
                       help="test OIDs by hand on one device (presets or numeric OIDs)")
    p.add_argument("address", help="device address (IP or IP:port)")
    p.add_argument("items", nargs="*", metavar="PRESET|OID",
                   help="preset names or numeric OIDs; none = list suggested presets")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--get", dest="mode", action="store_const", const="get",
                      help="GET only (numeric OIDs)")
    mode.add_argument("--walk", dest="mode", action="store_const", const="walk",
                      help="walk (numeric OIDs)")
    p.add_argument("--limit", type=int, default=50, help="maximum rows per column (default 50)")
    p.add_argument("--all", action="store_true",
                   help="with no item: also try the presets not suggested for the type")
    p.set_defaults(func=cmd_probe, mode="auto")

    p = sub.add_parser("device", parents=[common],
                       help="manual per-device settings, add or remove a device")
    dsub = p.add_subparsers(title="device commands", metavar="ACTION", required=True)
    d = dsub.add_parser("show", parents=[common], help="effective settings and their source")
    d.add_argument("address")
    d.set_defaults(func=cmd_device_show)
    d = dsub.add_parser("set", parents=[common], help="set values by hand: key=value …")
    d.add_argument("address")
    d.add_argument("assignments", nargs="+", metavar="KEY=VALUE")
    d.set_defaults(func=cmd_device_set)
    d = dsub.add_parser("unset", parents=[common], help="remove manual values")
    d.add_argument("address")
    d.add_argument("keys", nargs="*", metavar="KEY")
    d.add_argument("--all", action="store_true", help="remove every manual value")
    d.set_defaults(func=cmd_device_unset)
    d = dsub.add_parser("add", parents=[common], help="add a device to poll")
    d.add_argument("address")
    d.set_defaults(func=cmd_device_add)
    d = dsub.add_parser("remove", parents=[common], help="forget a device and its settings")
    d.add_argument("address")
    d.set_defaults(func=cmd_device_remove)
    d = dsub.add_parser("export-settings", parents=[common],
                        help="print manual settings as config.yml devices: entries")
    d.set_defaults(func=cmd_device_export)
    d = dsub.add_parser("import-settings", parents=[common],
                        help="load manual settings from a YAML devices: list")
    d.add_argument("file")
    d.add_argument("--replace", action="store_true",
                   help="drop existing manual values of the listed addresses first")
    d.set_defaults(func=cmd_device_import)

    p = sub.add_parser("tui", parents=[common], help="open the terminal management interface")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("explain", parents=[common],
                       help="why a MAC (or the MACs of an IP) is where it is")
    p.add_argument("query", metavar="MAC|IP")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("oui-update", parents=[common],
                       help="refresh the MAC vendor database from the IEEE")
    p.add_argument("--from-file", metavar="DIR",
                   help="use oui.csv, mam.csv and oui36.csv downloaded beforehand")
    p.set_defaults(func=cmd_oui_update)

    p = sub.add_parser("version", parents=[common], help="print the version")
    p.set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        if sys.stdin.isatty() and sys.stdout.isatty():
            args.func = cmd_tui
        else:
            parser.print_help(sys.stderr)
            return EXIT_CONFIG
    setup_logging(args.log_level or "info", args.log_file, args.quiet)
    try:
        return args.func(args)
    except ConfigError as exc:
        for error in exc.errors:
            log.error("configuration: %s", error)
        return EXIT_CONFIG
    except LockBusy as exc:
        log.error("%s", exc)
        return EXIT_LOCKED
    except StateError as exc:
        log.error("state: %s", exc)
        return EXIT_PARTIAL
    except (ManualError, AddressError, ProbeInputError) as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        log.warning("interrupted; results already committed are kept")
        return EXIT_INTERRUPTED


def entry() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
