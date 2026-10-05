"""Crontab generation from ``schedule:`` and the health check."""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.schedule.cron import longest_gap, parse_cron

DEFAULT_MAX_AGE = 24 * 3600


def executable(explicit: str | None = None) -> str:
    """Absolute path of the snowth_my_net command (cron's PATH rarely contains pipx's)."""
    if explicit:
        return explicit
    argv0 = Path(sys.argv[0])
    if argv0.name == "snowth_my_net" and argv0.exists():
        return str(argv0.resolve())
    found = shutil.which("snowth_my_net")
    return str(Path(found).resolve()) if found else "snowth_my_net"


@dataclass
class CronLine:
    schedule: str
    command: list[str]
    comment: str


def cron_lines(loaded: LoadedConfig, binary: str | None = None,
               config_path: str | None = None, quiet: bool = True,
               reports: list | None = None) -> list[CronLine]:
    """``reports``: LoadedReport list (files + TUI); default: the extension files only."""
    cfg = loaded.cfg.schedule
    base = [executable(binary), "--config",
            config_path or str(loaded.paths.config_file.resolve())]
    if quiet:
        base.append("-q")      # cron mails any output; supercronic forwards logs instead
    lines = []
    if cfg.collect:
        lines.append(CronLine(cfg.collect, [*base, "collect"],
                              "poll the devices (ARP entries expire quickly)"))
    if cfg.export_push:
        command = [*base, "run", "--no-collect"]
        if not loaded.cfg.push.targets:
            command.append("--no-push")
        lines.append(CronLine(cfg.export_push, command, "export the files and push them"))
    if cfg.names and loaded.cfg.names.probe:
        lines.append(CronLine(cfg.names, [*base, "names", "ask"],
                              "ask the hosts their own names (answers are cached)"))
    for report in loaded.reports if reports is None else reports:
        if report.cfg.schedule:
            lines.append(CronLine(report.cfg.schedule, [*base, "report", "run", report.cfg.name],
                                  f"report {report.cfg.name} ({report.origin})"))
    return lines


def render_crontab(loaded: LoadedConfig, fmt: str = "crontab", user: str = "snowth",
                   binary: str | None = None, config_path: str | None = None,
                   reports: list | None = None) -> str:
    out = [f"# snowth_my_net — generated from {loaded.paths.config_file} (schedule:)",
           "# Regenerate after changing the schedule: snowth_my_net cron print"]
    if fmt == "cron.d":
        out += ["SHELL=/bin/sh",
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
    timezone = loaded.cfg.schedule.timezone
    if timezone:
        out.append(f"CRON_TZ={timezone}")
    for line in cron_lines(loaded, binary, config_path, quiet=fmt != "supercronic",
                           reports=reports):
        out.append(f"# {line.comment}")
        command = shlex.join(line.command)
        who = f" {user}" if fmt == "cron.d" else ""
        out.append(f"{line.schedule}{who} {command}")
    return "\n".join(out) + "\n"


def max_collect_age(loaded: LoadedConfig) -> tuple[int, str]:
    """Allowed age of the last successful collect, and how it was decided."""
    schedule = loaded.cfg.schedule
    if schedule.health_max_age != "auto":
        return int(schedule.health_max_age), "schedule.health_max_age"
    if not schedule.collect:
        return DEFAULT_MAX_AGE, "no schedule.collect: default 24h"
    zone = ZoneInfo(schedule.timezone) if schedule.timezone else None
    gap = longest_gap(parse_cron(schedule.collect), zone)
    if gap is None:
        gap = timedelta(days=14)
    return int(gap.total_seconds() * 2), f"2 x longest gap of {schedule.collect!r}"
