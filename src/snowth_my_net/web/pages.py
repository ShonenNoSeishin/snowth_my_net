"""What each page shows: plain data, built from the same views as the exports.

Nothing here writes: the state is opened read-only, no request changes anything, and the
interface offers no action. Use the CLI or the terminal interface to collect or export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from snowth_my_net.clock import iso_z, local_time
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.nodes import derived_link_local
from snowth_my_net.merge.view import build_view
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo

DOWNLOADS = ("devices.csv", "nodes.csv", "links.csv", "snapshot.json", "map.html", "map.dot",
             "map.mmd")


@dataclass(frozen=True)
class Cell:
    """A value plus a muted note beside it (other addresses, how many positions…)."""

    text: str
    note: str = ""
    title: str = ""                         # shown on hover: the exact stored value
    tone: str = ""                          # "", "bad" or "warn": how the cell reads at a glance
    more: tuple[str, ...] = ()              # folded away behind a "+n": they would widen the row


def When(epoch: int | None) -> Cell:
    """A moment as the reader counts them, with the stored UTC value one hover away."""
    return Cell(local_time(epoch), title=iso_z(epoch))


@dataclass(frozen=True)
class Editable:
    """A value the reader may write straight in the table, for the row keyed by ``key``."""

    key: str                                # what the value belongs to: a MAC address
    text: str = ""
    field: str = "name"                     # which field of that key is being written


@dataclass
class Table:
    columns: list[tuple[str, str]]          # (label, "text" | "number")
    rows: list[list[str]] = field(default_factory=list)
    total: int = 0                          # rows before the display limit
    empty: str = ""                         # what to say when there is nothing
    help: list[tuple[str, str]] = field(default_factory=list)   # (label, where it comes from)
    keys: list[str | None] = field(default_factory=list)        # one per column, for its width
    views: list[tuple[str, str, bool]] = field(default_factory=list)   # (label, href, active)
    note: str = ""                          # one line under the controls


def help_for(t, page: str, columns: list[tuple[str, str]], keys: list[str | None],
             extra: list[str] = ()) -> list[tuple[str, str]]:
    """Pair each column with its explanation; ``extra`` keys are notes without a column."""
    pairs = [(label, t(f"hint.{page}.{key}"))
             for (label, _kind), key in zip(columns, keys, strict=True) if key]
    return pairs + [("", t(key)) for key in extra]


TONES = {"failed": "bad", "never": "bad", "partial": "warn"}


def _status_cell(status: str, error: str) -> Cell:
    """The status, and beside it the reason when there is one: an address that never answered
    is the first thing a reader looks for, and it must not be a silent empty row."""
    return Cell(status, error, error, TONES.get(status, ""))


def devices(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    found, names = _devices_and_names(loaded, repo, now)
    macs = {row[0]: row[1] for row in repo.conn.execute(
        "SELECT device_id, COUNT(*) FROM device_macs GROUP BY device_id")}
    targets = repo.targets()
    errors = {target["address"]: target["last_error"] or "" for target in targets}
    rows = []
    for device, name in zip(found, names, strict=True):
        others = macs.get(device["id"], 0) - (1 if device["base_mac"] else 0)
        status = device["last_collect_status"] or ""
        rows.append([
            name, split_host_port(device["mgmt_address"])[0], device["vendor"] or "",
            device["model"] or "",
            f"{device['os_name'] or ''} {device['os_version'] or ''}".strip(),
            t(f"type.{device['device_type']}") if device["device_type"] else "",
            Cell(device["base_mac"] or "",
                 t("web.more_macs", count=others) if others > 0 else ""),
            _status_cell(status, "" if status == "ok" else errors.get(device["mgmt_address"], "")),
            When(device["last_seen"]),
        ])
    rows += _never_collected(loaded, repo, targets, {d["id"] for d in found}, t)
    rows.sort(key=lambda row: str(row[0]).casefold())
    columns = [(t("col.name"), "text"), (t("col.ip"), "text"), (t("col.vendor"), "text"),
               (t("col.model"), "text"), (t("col.os"), "text"), (t("col.type"), "text"),
               (t("col.mac"), "text"), (t("col.status"), "text"), (t("col.seen"), "text")]
    keys = ["name", "ip", "vendor", "model", "os", "type", "mac", "status", "seen"]
    return Table(columns, rows, len(rows), t("web.no_devices"),
                 help_for(t, "devices", columns, keys), keys)


def _never_collected(loaded: LoadedConfig, repo: Repo, targets, known: set, t) -> list[list]:
    """Addresses that were polled but never became a device: without them, "11/12 reachable"
    names eleven devices and leaves the twelfth nowhere to be found."""
    from snowth_my_net.config.effective import settings_for

    manual = repo.manual_settings()
    rows = []
    for target in targets:
        if target["device_id"] in known or target["is_alias"]:
            continue
        host = split_host_port(target["address"])[0]
        settings = settings_for(loaded.cfg, host, manual)
        status = "failed" if target["last_error"] else "never"
        rows.append([settings.name or target["address"], host, "", "", "",
                     t(f"type.{settings.type}") if settings.type else "", Cell(""),
                     _status_cell(status, target["last_error"] or ""),
                     When(target["last_ok_at"])])
    return rows


def _devices_and_names(loaded: LoadedConfig, repo: Repo, now: int):
    found, names = exported_devices(loaded, repo, now)
    return found, [names[d["id"]] for d in found]


def nodes(loaded: LoadedConfig, repo: Repo, now: int, t, limit: int,
          live_only: bool = False) -> Table:
    view = build_view(loaded, repo, now)
    cfg = loaded.cfg.nodes
    rows = []
    stale = sum(1 for node in view.nodes if not node.live)
    for node in view.nodes:
        if live_only and not node.live:
            continue
        vendor = view.vendor(node)
        current = node.current_ip.ip if node.current_ip else ""
        # An address that is only the MAC rewritten is not folded away either: a bare "+1"
        # promised something to read and held nothing.
        others = [ip.ip for ip in node.ips if node.current_ip is not ip
                  and not derived_link_local(ip.ip, node.mac)]
        address = Cell(current, more=tuple(others))
        dns = view.dns_name(current) if current else ""
        positions = node.positions if cfg.positions == "all" else node.positions[:1]
        roaming = t("web.positions", count=len(positions)) if len(positions) > 1 else ""
        given = Editable(node.mac, view.given_name(node.mac))
        about = Editable(node.mac, view.given_description(node.mac), "description")
        for p in positions:
            rows.append([given, about, Cell(node.mac, roaming), vendor, address, dns,
                         view.device_name(p.device_id),
                         view.port_name(p.device_id, p.ifindex), str(p.vlan or ""),
                         When(p.last_seen)])
        if not positions and cfg.include_unlocated:
            rows.append([given, about, Cell(node.mac), vendor, address, dns, "", "", "",
                         When(node.last_seen)])
    rows.sort(key=lambda row: (str(row[9]), text_of(row[2]), str(row[6]), str(row[7])))
    rows.sort(key=lambda row: str(row[9]), reverse=True)
    columns = [(t("col.name"), "text"), (t("col.description"), "text"),
               (t("col.mac"), "text"), (t("col.vendor"), "text"),
               (t("col.ip"), "text"), (t("col.dns"), "text"), (t("col.switch"), "text"),
               (t("col.port"), "text"), (t("col.vlan"), "number"), (t("col.seen"), "text")]
    keys = ["name", "description", "mac", "vendor", "ip", "dns", "switch", "port", "vlan",
            "seen"]
    live = len(view.nodes) - stale
    views = [(t("web.view.live", count=live), "/nodes?live=1", live_only),
             (t("web.view.all", count=len(view.nodes)), "/nodes", not live_only)]
    return Table(columns, rows[:limit], len(rows), t("web.no_nodes"),
                 help_for(t, "nodes", columns, keys,
                          extra=["hint.nodes.live", "hint.nodes.click"]), keys, views,
                 t("web.view.stale", count=stale) if stale and not live_only else "")


def text_of(value) -> str:
    return value.text if isinstance(value, Cell) else str(value)


def links(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    rows = build_view(loaded, repo, now).link_rows()
    columns = [(t("col.local_device"), "text"), (t("col.local_port"), "text"),
               (t("col.remote_device"), "text"), (t("col.remote_port"), "text"),
               (t("col.protocol"), "text"), (t("col.seen"), "text")]
    keys = ["devices", None, None, None, "protocol", "seen"]
    return Table(columns, rows, len(rows), t("web.no_links"),
                 help_for(t, "links", columns, keys), keys)


def runs(repo: Repo, t, limit: int = 50) -> Table:
    import json

    rows = []
    for run in repo.recent_runs(limit):
        stats = json.loads(run["stats"] or "{}")
        duration = f"{run['finished_at'] - run['started_at']} s" if run["finished_at"] else "…"
        rows.append([str(run["id"]), run["command"], When(run["started_at"]), duration,
                     run["status"] or "running",
                     f"{stats.get('reachable', '—')}/{stats.get('devices', '—')}"])
    columns = [(t("col.run"), "number"), (t("col.command"), "text"),
               (t("col.started"), "text"), (t("col.duration"), "text"),
               (t("col.result"), "text"), (t("col.devices"), "text")]
    keys = [None, None, None, None, "result", "devices"]
    return Table(columns, rows, len(rows), t("web.no_runs"),
                 help_for(t, "runs", columns, keys), keys)


def files(output_dir: Path, t) -> Table:
    rows = []
    for name in DOWNLOADS:
        path = output_dir / name
        if not path.is_file():
            continue
        info = path.stat()
        rows.append([name, f"{info.st_size:,}".replace(",", " "),
                     When(int(info.st_mtime))])
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
    return t("status.last", when=local_time(last["finished_at"] or last["started_at"]),
             status=last["status"] or "?", ok=stats.get("reachable", "—"),
             total=stats.get("devices", "—"))


def explain_lines(loaded: LoadedConfig, repo: Repo, now: int, query: str, t):
    from snowth_my_net.merge.explain import explain

    return explain(build_view(loaded, repo, now), query, t)
