"""Collection engine: one asyncio process, bounded concurrency, partial results kept.

* A global semaphore bounds the number of devices polled at once; per-device concurrency and
  pacing are enforced by the SNMP client.
* Each device has a time budget (``device_timeout``, capped by what is left of ``run_timeout``)
  and each table its own (``table_timeout``). Rows received before a timeout are kept and the
  function is marked ``partial``.
* Every device is committed to the state in its own transaction as soon as it finishes, so a
  slow or silent device never delays or loses the others.
* Standard MIBs are always attempted (``auto``); only the configuration may switch a function
  ``off``. What a device announces (sysServices, guessed class) never decides anything.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from snowth_my_net import drivers
from snowth_my_net.clock import Clock
from snowth_my_net.collect import custom, functions, identify
from snowth_my_net.collect.discovery import (
    PlannedTarget,
    neighbor_targets,
    plan_targets,
    resolve_seeds,
    sweep_addresses,
)
from snowth_my_net.collect.functions import Rows
from snowth_my_net.collect.model import (
    ABSENT,
    FORCED_ABSENT,
    OK,
    PARTIAL,
    SKIPPED,
    TIMEOUT,
    DeviceResult,
    Outcome,
)
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.collect.tables.system import IDENTITY_OIDS, parse_system
from snowth_my_net.config.effective import FEATURES, DeviceSettings, settings_for
from snowth_my_net.config.loader import LoadedConfig, ResolvedCredential
from snowth_my_net.drivers.base import fill_identity
from snowth_my_net.logs import get_logger
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import EnginePool, SnmpClient, SnmpError, SnmpParams
from snowth_my_net.snmp.credentials import candidates_for, probe
from snowth_my_net.state.repo import Repo

log = get_logger("collect")

DEVICE_TYPES = ("switch", "router", "firewall", "wireless", "server", "printer", "facility",
                "other")

Function = Callable[[SnmpClient, DeviceResult, Rows], Awaitable[None]]


def snmp_params(settings: DeviceSettings) -> SnmpParams:
    s = settings.snmp
    return SnmpParams(
        timeout=s.timeout, retries=s.retries, max_repetitions=s.max_repetitions,
        use_bulk=s.use_bulk, per_device_concurrency=s.per_device_concurrency,
        pace_ms=s.pace_ms, max_rows=s.max_rows_per_table,
    )


def driver_identity(driver: drivers.Driver) -> Function:
    """The ``driver`` function: private identity objects, applied to empty fields only."""

    async def func(client: SnmpClient, r: DeviceResult, rows: Rows) -> None:
        assert r.ident is not None and r.system is not None
        found = await driver.identify(client, r)
        values = rows.column("values")
        for key, value in found.items():
            if value:
                values[(len(values),)] = key
        if not driver.identity_requests() and not found:
            values[(0,)] = driver.name          # nothing to read: the driver still applies
        filled = fill_identity(r.ident, found)
        if not r.ident.device_type and "model" in filled:
            vendor = r.ident.vendor
            _os, _version, rule = identify.os_of(r.system, vendor)
            r.ident.device_type, r.ident.type_rule, r.ident.type_reason = identify.decide_type(
                r.system, r.evidence, vendor, r.ident.model, rule)

    return func


def fold_subinterfaces(r: DeviceResult) -> None:
    """Sightings on a logical unit (``ge-0/0/5.0``) belong to its physical port, where LLDP,
    the port role and the operator's port names live."""
    parents = {i.ifindex: i.parent_ifindex for i in r.interfaces.values() if i.parent_ifindex}
    if not parents:
        return
    folded: dict[tuple[str, int, int], FdbEntry] = {}
    for entry in r.fdb:
        if entry.ifindex in parents:
            entry = dataclasses.replace(entry, ifindex=parents[entry.ifindex])
        folded.setdefault((entry.mac, entry.ifindex, entry.vlan), entry)
    r.fdb = list(folded.values())
    for unit, port in parents.items():
        if unit in r.pvid and port not in r.pvid:
            r.pvid[port] = r.pvid[unit]


async def run_function(r: DeviceResult, name: str, client: SnmpClient, deadline: float,
                       func: Function, mode: str | None = None) -> None:
    """Run one collection function under its time budget and record its outcome."""
    if mode is None:
        mode = r.settings.feature(name) if name in FEATURES else "auto"
    if mode == "off":
        r.outcomes[name] = Outcome(name, SKIPPED, detail="off in configuration")
        return
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    if remaining <= 0:
        r.outcomes[name] = Outcome(name, TIMEOUT, detail="device_timeout exhausted")
        return
    limit = min(float(r.settings.snmp.table_timeout), remaining)
    rows = Rows()
    start = loop.time()
    status, detail = OK, ""
    try:
        async with asyncio.timeout(limit):
            await func(client, r, rows)
    except TimeoutError:
        status, detail = TIMEOUT, f"no complete answer within {limit:.0f}s"
    except SnmpError as exc:
        status, detail = (TIMEOUT if exc.kind == TIMEOUT else "error"), str(exc)
    if status != OK and rows.count:
        status = PARTIAL
    if status == OK and rows.count == 0:
        status = FORCED_ABSENT if mode == "force" else ABSENT
        if mode == "force":
            detail = "no data although the function is forced"
    r.outcomes[name] = Outcome(name, status, rows.count, int((loop.time() - start) * 1000),
                               detail)


# --------------------------------------------------------------------------- identity


def same_device(a: DeviceResult, b: DeviceResult) -> bool:
    if a.device_id is not None and a.device_id == b.device_id:
        return True
    ia, ib = a.ident, b.ident
    if ia and ib and ia.serial and ia.serial == ib.serial and ia.pen == ib.pen:
        return True
    sa, sb = a.system, b.system
    if sa is None or sb is None:
        return False
    if sa.base_mac and sa.base_mac == sb.base_mac:
        return True
    return bool(
        sa.name and sa.name == sb.name and sa.object_id == sb.object_id
        and sa.uptime is not None and sb.uptime is not None
        and abs(sa.uptime - sb.uptime) < 6000  # 60 s, in TimeTicks
    )


def preference(r: DeviceResult) -> tuple:
    """Lower wins. ``ha_mode`` is set on a cluster's virtual IP: ``vip`` makes that address
    the preferred one, ``members`` makes the member addresses win over it."""
    ha = {"vip": 0, "members": 2}.get(r.settings.ha_mode or "", 1)
    return (ha, 0 if r.is_current_mgmt else 1, r.seed_rank, r.target.sort_key())


class IdentityRegistry:
    """In-run de-duplication: a device reachable through several addresses is polled once."""

    def __init__(self) -> None:
        self._owners: list[DeviceResult] = []

    def claim(self, r: DeviceResult) -> DeviceResult:
        for other in self._owners:
            if not same_device(r, other):
                continue
            if preference(r) < preference(other):
                other.superseded = True
                other.alias_of = r
                if other.device_id is not None:
                    r.device_id = other.device_id
                self._owners.remove(other)
                self._owners.append(r)
                return r
            r.alias_of = other
            return other
        self._owners.append(r)
        return r


def final_owner(r: DeviceResult) -> DeviceResult:
    while r.alias_of is not None:
        r = r.alias_of
    return r


# --------------------------------------------------------------------------- run


@dataclass
class RunReport:
    run_id: int | None
    command: str
    status: str
    results: list[DeviceResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "ok" else 1


class Collector:
    def __init__(self, loaded: LoadedConfig, repo: Repo | None,
                 credentials: list[ResolvedCredential], clock: Clock,
                 mode: str = "collect", manual: dict | None = None) -> None:
        assert mode in ("collect", "discover")
        self.loaded = loaded
        self.cfg = loaded.cfg
        self.repo = repo          # None = dry run: nothing is persisted
        self.credentials = credentials
        self.clock = clock
        self.mode = mode
        self.manual = manual if manual is not None else (repo.manual_settings() if repo else {})
        self.pool = EnginePool()
        self.registry = IdentityRegistry()
        self.collectors, warnings = custom.all_collectors(
            loaded.collectors, repo.custom_stored() if repo else {})
        for warning in warnings:
            log.warning("%s", warning)
        self._run_deadline = 0.0

    # ------------------------------------------------------------------ orchestration

    async def run(self, only: set[str] | None = None) -> RunReport:
        now = self.clock.now()
        repo = self.repo
        run_id = repo.start_run(self.mode, now) if repo else None
        report = RunReport(run_id, self.mode, "ok")
        loop = asyncio.get_running_loop()
        started = loop.time()
        self._run_deadline = started + self.cfg.general.run_timeout
        try:
            seeds = await resolve_seeds(self.cfg)
            report.errors += seeds.errors
            known = []
            if repo:
                repo.demote_seeds({str(t) for t, _ in seeds.targets})
                for target, _ in seeds.targets:
                    repo.ensure_target(str(target), "seed", 0, now)
                known = repo.targets()
            planned, notes = plan_targets(self.cfg, seeds.targets, known, only, self.manual)
            report.notes += notes
            if only is None and self._sweep_due(now):
                seen = {p.target.host for p in planned} | {row["address"] for row in known}
                planned += await self._sweep(seen, now)
            if not planned:
                report.errors.append("nothing to poll: no seed and no known device in scope")
            report.results = await self._collect_all(planned, run_id, now, report.notes,
                                                     explore=only is None)
        finally:
            self.pool.close()

        if repo:
            report.stats["purged"] = repo.purge(now, self.cfg.general.retention_days,
                                                self.cfg.discovery.forget_after_days,
                                                self.cfg.nodes.retention_days)
        owners = [r for r in report.results if r.alias_of is None]
        failing = [r for r in owners if r.status != "ok" and not r.settings.tolerate_failure]
        reachable = [r for r in owners if r.reachable]
        if not reachable:
            report.status = "failed"
        elif failing or report.errors:
            report.status = "partial"
        if only is not None:
            report.stats["only"] = sorted(only)
        report.stats.update(
            targets=len(report.results), devices=len(owners), reachable=len(reachable),
            failing=len(failing), aliases=len(report.results) - len(owners),
            duration_s=round(loop.time() - started, 1),
        )
        if repo and run_id is not None:
            repo.finish_run(run_id, report.status, self.clock.now(), report.stats)
        return report

    def _sweep_due(self, now: int) -> bool:
        if not self.cfg.discovery.sweep:
            return False
        if self.mode == "discover" or self.repo is None:
            return True
        last = self.repo.get_meta("last_sweep")
        return last is None or now - int(last) >= self.cfg.discovery.sweep_interval

    async def _sweep(self, known: set[str], now: int) -> list[PlannedTarget]:
        addresses = sweep_addresses(self.cfg, known)
        rate = self.cfg.discovery.sweep_rate
        log.info("sweep: probing %d address(es) at %d/s", len(addresses), rate)
        found: list[PlannedTarget] = []
        gate = asyncio.Semaphore(max(1, self.cfg.general.snmp.concurrency))

        async def one(target) -> None:
            async with gate:
                settings = settings_for(self.cfg, target.host, self.manual)
                cands = candidates_for(target.ip, self.credentials, None, settings.credential)
                res = await probe(self.pool, target, cands, snmp_params(settings),
                                  settings.snmp.probe_timeout, (oids.SYS_OBJECT_ID,))
                if res.ok and res.credential is not None:
                    found.append(PlannedTarget(target, "sweep", 0,
                                               remembered_credential=res.credential.name))

        tasks = []
        for target in addresses:
            tasks.append(asyncio.create_task(one(target)))
            await asyncio.sleep(1 / rate)
        await asyncio.gather(*tasks)
        if self.repo:
            for p in found:
                self.repo.ensure_target(str(p.target), "sweep", 0, now)
            self.repo.set_meta("last_sweep", str(now))
        log.info("sweep: %d device(s) answered", len(found))
        return found

    async def _collect_all(self, planned: list[PlannedTarget], run_id: int | None,
                           now: int, notes: list[str] | None = None,
                           explore: bool = True) -> list[DeviceResult]:
        """Poll every planned target; neighbours found on the way are explored (BFS)."""
        gate = asyncio.Semaphore(self.cfg.general.snmp.concurrency)
        known_hosts = {p.target.host for p in planned}
        if self.repo:
            known_hosts |= {row[0] for row in self.repo.conn.execute(
                "SELECT address FROM device_addresses")}
        pending = {asyncio.create_task(self._guarded(p, gate)) for p in planned}
        results: list[DeviceResult] = []
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                r = task.result()
                results.append(r)
                if r.system is not None:
                    known_hosts |= {a.address for a in r.addresses}
                if self.repo and run_id is not None and r.alias_of is None:
                    try:
                        if r.reachable:
                            r.device_id = self.repo.save_device(r, now, run_id)
                        else:
                            self.repo.save_failure(r, now, run_id, r.device_id)
                    except (OverflowError, ValueError, sqlite3.Error) as exc:
                        # What a device answered cannot be stored (an integer beyond 64 bits,
                        # say): that device is left out of this run, not the whole run.
                        message = f"{r.target}: not saved ({type(exc).__name__}: {exc})"
                        log.warning("%s", message)
                        if notes is not None:
                            notes.append(message)
                if explore and r.alias_of is None and r.neighbors:
                    found, skipped = neighbor_targets(self.cfg, r.neighbors, r.depth,
                                                      known_hosts, self.manual)
                    if notes is not None:
                        notes.extend(skipped)
                    for p in found:
                        log.info("%s: exploring neighbor %s (depth %d)", r.target, p.target,
                                 p.depth)
                        if self.repo:
                            self.repo.ensure_target(str(p.target), "neighbor", p.depth, now)
                        pending.add(asyncio.create_task(self._guarded(p, gate)))
        if self.repo:
            for r in results:
                owner = final_owner(r)
                if owner is not r and owner.device_id is not None:
                    self.repo.save_alias(r, owner.device_id, now)
        return results

    async def _guarded(self, planned: PlannedTarget, gate: asyncio.Semaphore) -> DeviceResult:
        settings = settings_for(self.cfg, planned.target.host, self.manual)
        r = DeviceResult(planned.target, planned.origin, planned.depth, settings,
                         seed_rank=planned.seed_rank, is_current_mgmt=planned.is_current_mgmt,
                         device_id=planned.device_id)
        loop = asyncio.get_running_loop()
        async with gate:
            start = loop.time()
            remaining = self._run_deadline - start
            if remaining <= 1:
                r.error = "run_timeout reached before this device could be polled"
                return r
            budget = min(float(settings.snmp.device_timeout), remaining)
            try:
                await self._collect_device(r, planned, start + budget)
            except Exception as exc:  # a bug must never abort the whole run
                log.exception("%s: unexpected error", r.target)
                if r.reachable:
                    r.outcomes["internal"] = Outcome("internal", "error", detail=repr(exc))
                else:
                    r.error = f"internal error: {exc!r}"
            finally:
                r.duration_s = round(loop.time() - start, 2)
        if r.alias_of is None:
            level = log.info if r.status == "ok" else log.warning
            level("%s: %s in %.1fs%s", r.target, r.status, r.duration_s,
                  f" ({r.error})" if r.error else "")
        return r

    # ------------------------------------------------------------------ one device

    async def _collect_device(self, r: DeviceResult, planned: PlannedTarget,
                              deadline: float) -> None:
        settings = r.settings
        params = snmp_params(settings)
        cands = candidates_for(r.target.ip, self.credentials, planned.remembered_credential,
                               settings.credential)
        if not cands:
            r.error = "no credential in scope for this address"
            return
        result = await probe(self.pool, r.target, cands, params, settings.snmp.probe_timeout,
                             IDENTITY_OIDS)
        r.attempts = result.attempts
        if not result.ok or result.credential is None:
            r.error = f"no answer ({result.summary()})"
            return
        r.credential = result.credential.name
        r.system = parse_system(result.values)
        r.outcomes["system"] = Outcome(
            "system", OK, rows=sum(v is not None for v in result.values.values()))
        client = SnmpClient(self.pool.get(result.credential.name), result.credential, r.target,
                            params)

        await run_function(r, "entity", client, deadline, functions.entity)
        await run_function(r, "type_evidence", client, deadline, functions.type_evidence)
        # The state keeps the DETECTED type; declared types (config.yml, manual) are applied
        # when reading, so that changing them takes effect at once and "back to automatic"
        # shows what the evidence says.
        r.ident = identify.identify(r.system, r.chassis, r.evidence)
        driver = drivers.select(r.settings.driver, r.system.object_id, self.loaded.drivers)
        if driver is not None:
            r.driver = driver.name
            await run_function(r, "driver", client, deadline, driver_identity(driver),
                               mode="auto")
        if self.repo is not None:
            matched, warnings = self.repo.match_device(
                serial=r.ident.serial, pen=r.ident.pen, base_mac=r.system.base_mac,
                sys_name=r.system.name, address=str(r.target))
            if matched is not None:
                r.device_id = matched
            r.warnings += warnings
            for warning in warnings:
                log.warning("%s: %s", r.target, warning)
        if self.registry.claim(r) is not r:
            log.info("%s: same device as %s, recorded as an alias", r.target,
                     final_owner(r).target)
            return
        if self.mode == "discover":
            steps = (("interfaces", functions.interfaces), ("lldp", functions.lldp),
                     ("cdp", functions.cdp))
        else:
            steps = (("interfaces", functions.interfaces), ("ipaddr", functions.ipaddr),
                     ("fdb", functions.fdb), ("arp", functions.arp), ("lldp", functions.lldp),
                     ("cdp", functions.cdp))
        for name, func in steps:
            if r.superseded:
                return
            await run_function(r, name, client, deadline, func)
        fold_subinterfaces(r)
        if (self.mode == "collect" and driver is not None and driver.has_extra
                and not r.superseded):
            await run_function(r, f"driver:{driver.name}", client, deadline, driver.extra,
                               mode="auto")
        if self.mode == "collect" and not r.superseded:
            await self._custom(r, client, deadline)

    async def _custom(self, r: DeviceResult, client: SnmpClient, deadline: float) -> None:
        """Custom collectors applicable to this device, then their fills of standard fields."""
        if not self.collectors or r.ident is None or r.system is None:
            return
        declared = r.settings.type
        facts = custom.DeviceFacts(r.target.host, r.ident.vendor,
                                   declared or r.ident.device_type, r.system.object_id,
                                   r.system.name, r.ident.model, r.ident.os_name,
                                   r.ident.os_version)
        previous = (self.repo.custom_current(r.device_id)
                    if self.repo is not None and r.device_id is not None else {})
        now = self.clock.now()
        for loaded in self.collectors:
            collector = loaded.cfg
            if not custom.applies(collector, facts):
                continue
            last = previous.get(collector.name)
            if collector.every and last and now - last["run_at"] < collector.every:
                self._apply_fills(r, collector, last["values"])
                continue
            result = custom.CustomResult()

            async def func(client, r, rows, collector=collector, result=result):
                rows.key = "entries"
                try:
                    await custom.run_collector(client, collector, result, facts)
                finally:
                    rows.columns["entries"] = {(i,): row for i, row in enumerate(result.rows)}

            name = f"custom:{collector.name}"
            await run_function(r, name, client, deadline, func, mode=collector.mode)
            outcome = r.outcomes.pop(name)
            r.custom[collector.name] = (outcome, result)
            self._apply_fills(r, collector, result.values())

    @staticmethod
    def _apply_fills(r: DeviceResult, collector, values: dict[str, str]) -> None:
        assert r.ident is not None and r.system is not None
        for target, value in custom.fills_for(collector, values).items():
            if target == "location":
                if collector.fill_override or not r.system.location:
                    r.system.location = value
                continue
            if target == "device_type" and value not in DEVICE_TYPES:
                r.warnings.append(f"collector {collector.name}: {value!r} is not a device type")
                continue
            if collector.fill_override or not getattr(r.ident, target):
                setattr(r.ident, target, value)
                if target == "device_type":
                    r.ident.type_rule = "custom"
                    r.ident.type_reason = f"custom collector {collector.name}"
