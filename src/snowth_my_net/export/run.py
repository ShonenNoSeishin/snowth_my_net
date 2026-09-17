"""``export``: build every configured output from the state, atomically."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from snowth_my_net.clock import Clock
from snowth_my_net.collect.identify import effective_type
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.export.atomic import atomic_write
from snowth_my_net.export.csvout import NODES_HEADER, EmptyExport, devices_csv, render_csv
from snowth_my_net.export.naming import NameInput, assign_names
from snowth_my_net.logs import get_logger
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import DAY, Repo

log = get_logger("export")

# Outputs implemented so far; the others arrive with their phase.
IMPLEMENTED = {"devices", "nodes"}


@dataclass
class ExportResult:
    written: list[Path] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def exported_devices(loaded: LoadedConfig, repo: Repo, now: int) -> tuple[list, dict[int, str]]:
    """Devices inside the retention window and their final names (the join key)."""
    cfg = loaded.cfg
    manual = repo.manual_settings()
    devices = []
    settings = {}
    for row in repo.devices(since=now - cfg.general.retention_days * DAY):
        d = dict(row)
        host = split_host_port(d["mgmt_address"])[0]
        s = settings[d["id"]] = settings_for(cfg, host, manual)
        d["detected_type"] = d["device_type"] or ""
        d["device_type"], d["type_rule"], d["type_reason"] = effective_type(
            d["device_type"] or "", d["type_rule"] or "", d["type_reason"] or "", s.type,
            s.source("type"))
        devices.append(d)
    names = assign_names(
        (NameInput(d["id"], d["sys_name"] or "", split_host_port(d["mgmt_address"])[0],
                   settings[d["id"]].name) for d in devices),
        cfg.general.device_name,
    )
    return devices, names


def refresh_dns(loaded: LoadedConfig, repo: Repo, ips: list[str], now: int,
                ptr_lookup=None) -> int:
    """Look up the PTR names missing from (or expired in) the cache. Returns the count."""
    import asyncio

    from snowth_my_net.enrich.dns import dnspython_ptr, resolve_ptrs

    dns_cfg = loaded.cfg.dns
    if not dns_cfg.enabled:
        return 0
    fresh = repo.dns_fresh(now)
    wanted = sorted({ip for ip in ips if ip and ip not in fresh})
    if not wanted:
        return 0
    lookup = ptr_lookup or dnspython_ptr(dns_cfg)
    results = asyncio.run(resolve_ptrs(wanted, dns_cfg, lookup, dns_cfg.budget))
    repo.save_dns(results, now, dns_cfg.cache_ttl, dns_cfg.negative_ttl)
    if len(results) < len(wanted):
        log.warning("DNS budget spent: %d of %d PTR lookups done, the rest at the next export",
                    len(results), len(wanted))
    return len(results)


def nodes_csv(loaded: LoadedConfig, repo: Repo, now: int, ptr_lookup=None) -> bytes:
    from snowth_my_net.merge.view import build_view

    cfg = loaded.cfg
    view = build_view(loaded, repo, now)
    ips = [n.current_ip.ip for n in view.nodes if n.current_ip]
    if refresh_dns(loaded, repo, ips, now, ptr_lookup):
        view.dns = repo.dns_names(now)
    rows = view.rows()
    if not rows and "nodes" not in cfg.export.allow_empty:
        raise EmptyExport("nodes.csv would have no data row")
    return render_csv(NODES_HEADER, rows, cfg.export.csv.line_terminator)


def export(loaded: LoadedConfig, repo: Repo, clock: Clock,
           only: list[str] | None = None, ptr_lookup=None) -> ExportResult:
    cfg = loaded.cfg
    out_dir = loaded.paths.output_dir
    result = ExportResult()
    now = clock.now()
    devices, names = exported_devices(loaded, repo, now)
    for name in only or cfg.export.files:
        if name not in IMPLEMENTED:
            result.pending.append(name)
            continue
        try:
            if name == "devices":
                data = devices_csv(devices, names, cfg.export.devices.include_type,
                                   cfg.export.csv.line_terminator,
                                   allow_empty="devices" in cfg.export.allow_empty)
                path = out_dir / "devices.csv"
            elif name == "nodes":
                data = nodes_csv(loaded, repo, now, ptr_lookup)
                path = out_dir / "nodes.csv"
            else:  # pragma: no cover - guarded by IMPLEMENTED
                continue
        except EmptyExport as exc:
            log.error("%s; the previous file is kept and will not be pushed", exc)
            result.failed.append((name, str(exc)))
            continue
        atomic_write(path, data)
        log.info("wrote %s (%d bytes)", path, len(data))
        result.written.append(path)
    if result.pending:
        log.info("not produced yet (later phases): %s", ", ".join(result.pending))
    return result
