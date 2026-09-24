"""What each page shows: plain data, built from the same views as the exports.

Nothing here writes: the state is opened read-only, no request changes anything, and the
interface offers no action. Use the CLI or the terminal interface to collect or export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from snowth_my_net.clock import iso_z
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.view import build_view
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo

DOWNLOADS = ("devices.csv", "nodes.csv", "links.csv", "snapshot.json", "map.html", "map.dot",
             "map.mmd")


@dataclass
class Table:
    columns: list[tuple[str, str]]          # (label, "text" | "number")
    rows: list[list[str]] = field(default_factory=list)
    total: int = 0                          # rows before the display limit
    empty: str = ""                         # what to say when there is nothing
    help: list[tuple[str, str]] = field(default_factory=list)   # (label, where it comes from)


def help_for(t, page: str, columns: list[tuple[str, str]], keys: list[str | None],
             extra: list[str] = ()) -> list[tuple[str, str]]:
    """Pair each column with its explanation; ``extra`` keys are notes without a column."""
    pairs = [(label, t(f"hint.{page}.{key}"))
             for (label, _kind), key in zip(columns, keys, strict=True) if key]
    return pairs + [("", t(key)) for key in extra]


def devices(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    rows = []
    for device, name in zip(*_devices_and_names(loaded, repo, now), strict=True):
        rows.append([
            name, split_host_port(device["mgmt_address"])[0], device["vendor"] or "",
            device["model"] or "",
            f"{device['os_name'] or ''} {device['os_version'] or ''}".strip(),
            t(f"type.{device['device_type']}") if device["device_type"] else "",
            device["last_collect_status"] or "", iso_z(device["last_seen"]),
        ])
    rows.sort(key=lambda row: row[0].casefold())
    columns = [(t("col.name"), "text"), (t("col.ip"), "text"), (t("col.vendor"), "text"),
               (t("col.model"), "text"), (t("col.os"), "text"), (t("col.type"), "text"),
               (t("col.status"), "text"), (t("col.seen"), "text")]
    keys = ["name", "ip", "vendor", "model", "os", "type", "status", "seen"]
    return Table(columns, rows, len(rows), t("web.no_devices"),
                 help_for(t, "devices", columns, keys))


def _devices_and_names(loaded: LoadedConfig, repo: Repo, now: int):
    found, names = exported_devices(loaded, repo, now)
    return found, [names[d["id"]] for d in found]


def nodes(loaded: LoadedConfig, repo: Repo, now: int, t, limit: int) -> Table:
    all_rows = build_view(loaded, repo, now).rows()
    columns = [(t("col.mac"), "text"), (t("col.vendor"), "text"), (t("col.ip"), "text"),
               (t("col.dns"), "text"), (t("col.switch"), "text"), (t("col.port"), "text"),
               (t("col.vlan"), "number"), (t("col.seen"), "text")]
    keys = ["mac", "vendor", "ip", "dns", "switch", "port", "vlan", "seen"]
    return Table(columns, all_rows[:limit], len(all_rows), t("web.no_nodes"),
                 help_for(t, "nodes", columns, keys, extra=["hint.nodes.click"]))


def links(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    rows = build_view(loaded, repo, now).link_rows()
    columns = [(t("col.local_device"), "text"), (t("col.local_port"), "text"),
               (t("col.remote_device"), "text"), (t("col.remote_port"), "text"),
               (t("col.protocol"), "text"), (t("col.seen"), "text")]
    keys = ["devices", None, None, None, "protocol", "seen"]
    return Table(columns, rows, len(rows), t("web.no_links"),
                 help_for(t, "links", columns, keys))


def runs(repo: Repo, t, limit: int = 50) -> Table:
    import json

    rows = []
    for run in repo.recent_runs(limit):
        stats = json.loads(run["stats"] or "{}")
        duration = f"{run['finished_at'] - run['started_at']} s" if run["finished_at"] else "…"
        rows.append([str(run["id"]), run["command"], iso_z(run["started_at"]), duration,
                     run["status"] or "running",
                     f"{stats.get('reachable', '—')}/{stats.get('devices', '—')}"])
    columns = [(t("col.run"), "number"), (t("col.command"), "text"),
               (t("col.started"), "text"), (t("col.duration"), "text"),
               (t("col.result"), "text"), (t("col.devices"), "text")]
    keys = [None, None, None, None, "result", "devices"]
    return Table(columns, rows, len(rows), t("web.no_runs"), help_for(t, "runs", columns, keys))


def files(output_dir: Path, t) -> Table:
    rows = []
    for name in DOWNLOADS:
        path = output_dir / name
        if not path.is_file():
            continue
        info = path.stat()
        rows.append([name, f"{info.st_size:,}".replace(",", " "), iso_z(int(info.st_mtime))])
    columns = [(t("col.file"), "text"), (t("col.size"), "number"), (t("col.written"), "text")]
    return Table(columns, rows, len(rows), t("web.no_files"),
                 help_for(t, "files", columns, ["file", None, None]))


def summary(loaded: LoadedConfig, repo: Repo, now: int, t) -> str:
    """One line under the title: when the last collect ran and how it went."""
    last = repo.last_successful_collect()
    if last is None:
        return t("status.never")
    import json

    stats = json.loads(last["stats"] or "{}")
    return t("status.last", when=iso_z(last["finished_at"] or last["started_at"]),
             status=last["status"] or "?", ok=stats.get("reachable", "—"),
             total=stats.get("devices", "—"))


def explain_lines(loaded: LoadedConfig, repo: Repo, now: int, query: str, t):
    from snowth_my_net.merge.explain import explain

    return explain(build_view(loaded, repo, now), query, t)
