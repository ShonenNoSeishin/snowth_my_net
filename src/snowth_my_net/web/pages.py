"""What each page shows: plain data, built from the same views as the exports.

Nothing here writes: the state is opened read-only, no request changes anything, and the
interface offers no action. Use the CLI or the terminal interface to collect or export.
"""

from __future__ import annotations

import calendar
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from snowth_my_net.clock import iso_z, local_time
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.export.run import exported_devices
from snowth_my_net.merge.nodes import is_link_local
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
    tone: str = ""                          # "", "ok", "bad", "warn" or "dim": how it reads
    more: tuple[str, ...] = ()              # folded away behind a "+n": they would widen the row
    href: str = ""                          # makes the text a link


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
    disagreeing: int = 0                    # rows where two sources name the same thing twice


def help_for(t, page: str, columns: list[tuple[str, str]], keys: list[str | None],
             extra: list[str] = ()) -> list[tuple[str, str]]:
    """Pair each column with its explanation; ``extra`` keys are notes without a column."""
    pairs = [(label, t(f"hint.{page}.{key}"))
             for (label, _kind), key in zip(columns, keys, strict=True) if key]
    return pairs + [("", t(key)) for key in extra]


TONES = {"ok": "ok", "failed": "bad", "never": "bad", "partial": "warn"}


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
            Cell(name, href="/ports?device=" + quote(name, safe="")),
            split_host_port(device["mgmt_address"])[0], device["vendor"] or "",
            device["model"] or "",
            f"{device['os_name'] or ''} {device['os_version'] or ''}".strip(),
            t(f"type.{device['device_type']}") if device["device_type"] else "",
            Cell(device["base_mac"] or "",
                 t("web.more_macs", count=others) if others > 0 else ""),
            _status_cell(status, "" if status == "ok" else errors.get(device["mgmt_address"], "")),
            When(device["last_seen"]),
        ])
    rows += _never_collected(loaded, repo, targets, {d["id"] for d in found}, t)
    rows.sort(key=lambda row: text_of(row[0]).casefold())
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
          live_only: bool = False, disagreeing_only: bool = False,
          local_macs: str = "", churn_only: bool = False, switch: str = "",
          port: str = "") -> Table:
    """``local_macs``: ``hide`` or ``only`` filters the locally administered MACs; nodes are
    never grouped or merged on a guess, a rotated MAC is just another MAC."""
    view = build_view(loaded, repo, now)
    cfg = loaded.cfg.nodes
    rows = []
    stale = sum(1 for node in view.nodes if not node.live)
    disagreeing = sum(1 for node in view.nodes if view.hostnames_disagree(node))
    for node in view.nodes:
        if live_only and not node.live:
            continue
        if disagreeing_only and not view.hostnames_disagree(node):
            continue
        if churn_only and not view.ip_churn(node):
            continue
        if (local_macs == "hide" and node.random_mac) or (
                local_macs == "only" and not node.random_mac):
            continue
        vendor = view.vendor(node)
        if node.random_mac:
            vendor = Cell("", note=t("web.random.badge"), title=t("web.random.title"))
        current = node.current_ip.ip if node.current_ip else ""
        # Link-local addresses are not folded away either: a bare "+1" promised something to
        # read and held an address nothing can be reached by.
        others = [ip.ip for ip in node.ips if node.current_ip is not ip
                  and not is_link_local(ip.ip)]
        address = Cell(current, more=tuple(others))
        dns = view.dns_name(current) if current else ""
        positions = node.positions if cfg.positions == "all" else node.positions[:1]
        if switch:                       # only where it was heard on that device (and port)
            positions = [p for p in positions if view.device_name(p.device_id) == switch
                         and (not port or view.port_name(p.device_id, p.ifindex) == port)]
            if not positions:
                continue
        roaming = t("web.positions", count=len(positions)) if len(positions) > 1 else ""
        tone = "warn" if view.hostnames_disagree(node) else ""
        given = Editable(node.mac, view.given_name(node.mac))
        probed = Cell(view.probed_name(node), tone=tone)
        about = Editable(node.mac, view.given_description(node.mac), "description")
        named = Cell(dns.text if isinstance(dns, Cell) else str(dns), tone=tone)
        for p in positions:
            rows.append([given, named, probed, about, Cell(node.mac, roaming), vendor, address,
                         view.device_name(p.device_id),
                         view.port_name(p.device_id, p.ifindex), str(p.vlan or ""),
                         When(p.last_seen)])
        if not positions and cfg.include_unlocated:
            rows.append([given, named, probed, about, Cell(node.mac), vendor, address, "", "",
                         "", When(node.last_seen)])
    rows.sort(key=lambda row: (str(row[10]), text_of(row[4]), str(row[7]), str(row[8])))
    rows.sort(key=lambda row: str(row[10]), reverse=True)
    if local_macs == "only":      # read side by side, by where they were heard
        rows.sort(key=lambda row: (str(row[7]), str(row[8]), vlan_key(row[9])))
    columns = [(t("col.hostname.manual"), "text"), (t("col.hostname.dns"), "text"),
               (t("col.hostname.probe"), "text"), (t("col.description"), "text"),
               (t("col.mac"), "text"), (t("col.vendor"), "text"), (t("col.ip"), "text"),
               (t("col.switch"), "text"), (t("col.port"), "text"), (t("col.vlan"), "number"),
               (t("col.seen"), "text")]
    keys = ["hostname_manual", "hostname_dns", "hostname_probe", "description", "mac", "vendor",
            "ip", "switch", "port", "vlan", "seen"]
    live = len(view.nodes) - stale
    randoms = sum(1 for node in view.nodes if node.random_mac)
    churning = sum(1 for node in view.nodes if view.ip_churn(node))
    plain = not local_macs and not churn_only
    views = [(t("web.view.live", count=live), "/nodes?live=1", live_only and plain),
             (t("web.view.all", count=len(view.nodes)), "/nodes", not live_only and plain)]
    if churning:
        views.append((t("web.view.churn", count=churning), "/nodes?churn=1", churn_only))
    if randoms:
        views += [(t("web.view.norandom", count=len(view.nodes) - randoms), "/nodes?local=hide",
                   local_macs == "hide"),
                  (t("web.view.random", count=randoms), "/nodes?local=only",
                   local_macs == "only")]
    note = t("web.view.stale", count=stale) if stale and not live_only else ""
    if local_macs == "only":
        note = t("web.random.note")
    if churn_only:
        note = t("web.churn.note", days=cfg.ip_churn_days // 86400, count=cfg.ip_churn_min)
    if switch:
        note = t("web.nodes.on_port", switch=switch, port=port or "*")
    return Table(columns, rows[:limit], len(rows), t("web.no_nodes"),
                 help_for(t, "nodes", columns, keys,
                          extra=["hint.nodes.live", "hint.nodes.click"]), keys, views, note,
                 disagreeing)


def text_of(value) -> str:
    return value.text if isinstance(value, Cell) else str(value)


def vlan_key(value) -> tuple[int, int, str]:
    """VLAN 20 before VLAN 100; what is not a number, then nothing, after."""
    text = str(value.text if isinstance(value, Cell) else value)
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def links(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    view = build_view(loaded, repo, now)
    rows = view.link_rows()
    polled = set(view.names.values())
    for row in rows:                       # the same local time as every other page
        row[5] = When(calendar.timegm(time.strptime(row[5], "%Y-%m-%dT%H:%M:%SZ")))
        for end in (0, 2):                 # a polled device opens its ports
            if row[end] in polled:
                row[end] = Cell(row[end], href="/ports?device=" + quote(row[end], safe=""))
    columns = [(t("col.local_device"), "text"), (t("col.local_port"), "text"),
               (t("col.remote_device"), "text"), (t("col.remote_port"), "text"),
               (t("col.protocol"), "text"), (t("col.seen"), "text")]
    keys = ["devices", None, None, None, "protocol", "seen"]
    return Table(columns, rows, len(rows), t("web.no_links"),
                 help_for(t, "links", columns, keys), keys)


KINDS = ("snmp", "neighbor", "names")


def _mac_of(text: str) -> str:
    from snowth_my_net.snmp.values import normalize_mac

    return normalize_mac(text) or ""


def unreachable(loaded: LoadedConfig, repo: Repo, now: int, t, limit: int,
                kind: str | None = None) -> Table:
    """What cannot be polled, and what cannot be joined: three kinds of silence, one table.

    Each row says what was tried and, in the words of the rule that decided it, why it does not
    work — an address outside the allowed range, a phone, a host that answered with another
    adapter's MAC. Some of these are things to fix and some are on purpose; the page does not
    pretend to know which, it makes every one visible.
    """
    from snowth_my_net.collect.discovery import unpolled_reason
    from snowth_my_net.web import snmp

    view = build_view(loaded, repo, now)
    manual = repo.manual_settings()
    found: dict[str, list[list]] = {name: [] for name in KINDS}
    label = {name: t(f"kind.{name}") for name in KINDS}

    # --- polled addresses that do not answer
    targets = snmp.connections(loaded, repo)
    for row in targets:
        if row.status == "ok":
            continue
        why = row.error or t("unreach.snmp.never")
        if row.failures:
            why += f" · {t('unreach.snmp.failures', count=row.failures)}"
        tried = t("unreach.snmp.tried", credential=row.credential or t("unreach.snmp.every"))
        found["snmp"].append([label["snmp"], row.host, row.device_name, "", tried,
                              Cell(why, tone="bad"), When(row.last_attempt)])

    # --- neighbours announced and not polled (a neighbour that is a target is a row above)
    polled = {row.host for row in targets}
    device_macs = view.ctx.inputs.device_macs
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for rn in view.neighbors:
        if rn.remote_device_id is not None:
            continue
        addresses = tuple(rn.obs.mgmt_addresses)
        # A device that is polled is never "unreachable": one that hears itself, or is heard
        # through a chassis address, is recognised by its MAC even when the link did not resolve.
        if _mac_of(rn.obs.chassis_id) in device_macs:
            continue
        if (rn.remote_name, addresses) in seen or any(a in polled for a in addresses):
            continue
        seen.add((rn.remote_name, addresses))
        why = unpolled_reason(loaded.cfg, rn.obs, manual) or t("unreach.neighbor.pending")
        found["neighbor"].append([label["neighbor"], addresses[0] if addresses else "",
                                  rn.remote_name, _mac_of(rn.obs.chassis_id),
                                  t("unreach.neighbor.tried"), why, When(rn.obs.last_seen)])

    # --- nodes that stated no name when asked
    cfg = loaded.cfg.names
    if cfg.probe:
        from snowth_my_net.enrich.probe import in_networks

        outcomes = repo.probe_outcomes(now)
        for node in view.nodes:
            if not node.live or not node.current_ip or view.probed_name(node):
                continue
            ip = node.current_ip.ip
            asked = outcomes.get(ip, {})
            if not in_networks(ip, cfg.networks):
                tried, why, when = "", t("unreach.names.outside"), None
            elif not asked:
                tried, why, when = "", t("unreach.names.pending"), None
            else:
                tried = ", ".join(sorted(asked))
                when = max(at for _status, _mac, at in asked.values())
                claimed = next((mac for status, mac, _at in asked.values()
                                if status == "ok" and mac and mac != node.mac), "")
                why = (t("unreach.names.dropped", mac=claimed) if claimed
                       else t("unreach.names.silent"))
            found["names"].append([label["names"], ip, view.hostname(node)[0], node.mac,
                                   tried, why, When(when)])

    counts = {name: len(found[name]) for name in KINDS}
    chosen = [name for name in KINDS if kind in (None, "", name)]
    rows = [row for name in chosen for row in found[name]]
    columns = [(t("col.kind"), "text"), (t("col.address"), "text"), (t("col.name"), "text"),
               (t("col.mac"), "text"), (t("col.tried"), "text"), (t("col.why"), "text"),
               (t("col.attempt"), "text")]
    keys = ["kind", None, None, None, "tried", "why", None]
    views = [(t("web.kind.all", count=sum(counts.values())), "/unreachable", not kind)]
    views += [(t(f"web.kind.{name}", count=counts[name]), f"/unreachable?kind={name}",
               kind == name) for name in KINDS]
    note = t("unreach.count", **counts)
    if not cfg.probe:
        note += " · " + t("unreach.names.off")
    return Table(columns, rows[:limit], len(rows), t("web.no_unreachable"),
                 help_for(t, "unreachable", columns, keys), keys, views, note)


def runs(repo: Repo, t, limit: int = 50) -> Table:
    import json

    rows = []
    for run in repo.recent_runs(limit):
        stats = json.loads(run["stats"] or "{}")
        duration = f"{run['finished_at'] - run['started_at']} s" if run["finished_at"] else "…"
        rows.append([str(run["id"]), run["command"], When(run["started_at"]), duration,
                     Cell(run["status"] or "running", tone=TONES.get(run["status"] or "", "")),
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
             status=t("st." + last["status"]) if last["status"] in ("ok", "partial", "failed")
             else (last["status"] or "?"), ok=stats.get("reachable", "—"),
             total=stats.get("devices", "—"))


def explain_lines(loaded: LoadedConfig, repo: Repo, now: int, query: str, t,
                  addresses: list[str] | None = None):
    """The lines of ``explain``; ``addresses``, when given, is filled with the elected address
    of each node found, for the page to link to what can be done with it."""
    from snowth_my_net.merge.explain import explain

    view = build_view(loaded, repo, now)
    if addresses is not None:
        addresses += [n.current_ip.ip for n in view.find(query) if n.current_ip]
    return explain(view, query, t)
