"""``check``: the first diagnostic to run. Read-only towards the devices and the state.

For every device: reachable? which credential? which standard MIBs answer, with how many
rows? what identity and type would be recorded, and why? Plus configuration-level warnings
(v2c credentials, secret permissions, factory sysNames…).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from snowth_my_net.collect import functions, identify
from snowth_my_net.collect.discovery import PlannedTarget
from snowth_my_net.collect.engine import run_function, snmp_params
from snowth_my_net.collect.model import DeviceResult, Identification
from snowth_my_net.collect.tables.system import IDENTITY_OIDS, parse_system
from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig, ResolvedCredential
from snowth_my_net.snmp import oids
from snowth_my_net.snmp.client import EnginePool, SnmpClient, SnmpError
from snowth_my_net.snmp.credentials import candidates_for, probe
from snowth_my_net.snmp.values import Oid


def baseline_sources(cfg, host: str) -> dict[str, str]:
    """Where each non-default value comes from, ignoring manual settings."""
    return settings_for(cfg, host).sources


# (label, column walked to count rows, feature it serves)
CHECK_MIBS: tuple[tuple[str, Oid, str], ...] = (
    ("entity", oids.ENT_PHYSICAL_CLASS, "entity"),
    ("ifTable", oids.IF_DESCR, "interfaces"),
    ("ifXTable", oids.IF_NAME, "interfaces"),
    ("ipAddrTable", oids.IP_AD_ENT_IF_INDEX, "ipaddr"),
    ("ipAddressTable", oids.IP_ADDRESS_IF_INDEX, "ipaddr"),
    ("dot1qTpFdb", oids.DOT1Q_TP_FDB_PORT, "fdb"),
    ("dot1dTpFdb", oids.DOT1D_TP_FDB_PORT, "fdb"),
    ("vtpVlanState", oids.VTP_VLAN_STATE, "fdb"),
    ("ipNetToPhysical", oids.IP_NET_TO_PHYSICAL_PHYS_ADDRESS, "arp"),
    ("ipNetToMedia", oids.IP_NET_TO_MEDIA_PHYS_ADDRESS, "arp"),
    ("lldpRem", oids.LLDP_REM_ENTRY + (9,), "lldp"),
    ("cdpCache", oids.CDP_CACHE_ENTRY + (6,), "cdp"),
    ("printerMib", oids.PRT_GENERAL_ENTRY, ""),
    ("upsMib", oids.UPS_IDENT, ""),
)


@dataclass
class DeviceCheck:
    address: str
    reachable: bool = False
    credential: str | None = None
    attempts: list[tuple[str, str]] = field(default_factory=list)
    rtt_ms: int | None = None
    sys_name: str = ""
    sys_descr: str = ""
    object_id: str = ""
    ident: Identification | None = None
    mibs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    tolerated: bool = False

    @property
    def failed(self) -> bool:
        return (not self.reachable or any(w.startswith("forced ") for w in self.warnings))


async def check_devices(loaded: LoadedConfig, credentials: list[ResolvedCredential],
                        targets: list[PlannedTarget], quick: bool,
                        manual: dict | None = None) -> list[DeviceCheck]:
    cfg = loaded.cfg
    pool = EnginePool()
    gate = asyncio.Semaphore(cfg.general.snmp.concurrency)
    loop = asyncio.get_running_loop()

    async def one(p: PlannedTarget) -> DeviceCheck:
        settings = settings_for(cfg, p.target.host, manual)
        dc = DeviceCheck(str(p.target), tolerated=settings.tolerate_failure)
        async with gate:
            cands = candidates_for(p.target.ip, credentials, p.remembered_credential,
                                   settings.credential)
            if not cands:
                dc.error = "no credential in scope for this address"
                return dc
            params = snmp_params(settings)
            start = loop.time()
            res = await probe(pool, p.target, cands, params, settings.snmp.probe_timeout,
                              IDENTITY_OIDS)
            dc.attempts = res.attempts
            if not res.ok or res.credential is None:
                dc.error = f"no answer ({res.summary()})"
                return dc
            dc.rtt_ms = int((loop.time() - start) * 1000)
            dc.reachable, dc.credential = True, res.credential.name
            system = parse_system(res.values)
            dc.sys_name, dc.sys_descr, dc.object_id = system.name, system.descr, system.object_id
            client = SnmpClient(pool.get(res.credential.name), res.credential, p.target, params)
            r = DeviceResult(p.target, p.origin, p.depth, settings, system=system)
            deadline = loop.time() + settings.snmp.device_timeout
            await run_function(r, "entity", client, deadline, functions.entity)
            await run_function(r, "type_evidence", client, deadline, functions.type_evidence)
            dc.ident = identify.identify(system, r.chassis, r.evidence, settings.type,
                                         override_source=settings.source("type"))
            for key, source in settings.sources.items():
                if source == "manual" and key in baseline_sources(cfg, p.target.host):
                    dc.warnings.append(f"manual setting '{key}' overrides config.yml")
            for label, base, _feature in CHECK_MIBS:
                try:
                    async with asyncio.timeout(settings.snmp.table_timeout):
                        if quick:
                            dc.mibs[label] = "ok" if await functions.has_rows(client, base) \
                                else "absent"
                        else:
                            n = await functions.count_rows(client, base)
                            dc.mibs[label] = f"ok({n})" if n else "absent"
                except TimeoutError:
                    dc.mibs[label] = "timeout"
                except SnmpError as exc:
                    dc.mibs[label] = "timeout" if exc.kind == "timeout" else f"error: {exc}"
            for feature in ("entity", "interfaces", "ipaddr", "fdb", "arp", "lldp", "cdp"):
                if settings.feature(feature) != "force":
                    continue
                answered = [lbl for lbl, _b, f in CHECK_MIBS
                            if f == feature and dc.mibs.get(lbl, "").startswith("ok")]
                if not answered:
                    dc.warnings.append(f"forced function '{feature}' has no data")
            reason = identify.factory_name_reason(system.name, dc.ident.model, system.descr)
            if reason:
                dc.warnings.append(f"{reason}; set a real hostname on the device")
        return dc

    try:
        results = list(await asyncio.gather(*(one(p) for p in targets)))
    finally:
        pool.close()
    names: dict[str, list[DeviceCheck]] = {}
    for dc in results:
        if dc.reachable and dc.sys_name:
            names.setdefault(dc.sys_name.casefold(), []).append(dc)
    for group in names.values():
        if len(group) > 1:
            for dc in group:
                others = ", ".join(o.address for o in group if o is not dc)
                dc.warnings.append(f"sysName {dc.sys_name!r} is also used by {others} "
                                   "(the outputs will add an IP suffix)")
    return results


WELL_KNOWN_COMMUNITIES = frozenset({"public", "private", "community", "snmp", "monitor"})


def secret_warnings(credentials: list[ResolvedCredential]) -> list[str]:
    """Weak secrets, and names that would be masked because they contain their own secret."""
    warnings = []
    for cred in credentials:
        if cred.community is not None:
            value = cred.community.reveal()
            if value.lower() in WELL_KNOWN_COMMUNITIES or len(value) < 8:
                warnings.append(f"credential '{cred.name}': the community is a well-known "
                                "default or shorter than 8 characters")
        for secret in (cred.community, cred.auth_key, cred.priv_key):
            if secret is not None and secret.reveal() in cred.name:
                warnings.append(f"credential '{cred.name}': its name contains its own secret; "
                                "the name will appear masked in logs and outputs")
    return warnings


def config_warnings(loaded: LoadedConfig) -> list[str]:
    cfg = loaded.cfg
    warnings = []
    for cred in cfg.credentials:
        if cred.version == "2c":
            warnings.append(f"credential '{cred.name}' uses SNMPv2c (community in clear text); "
                            "SNMPv3 authPriv is recommended")
        elif cred.security_level != "authPriv":
            warnings.append(f"credential '{cred.name}' is {cred.security_level}; "
                            "authPriv is recommended")
    for target in cfg.push.targets:
        if not target.tls_verify:
            warnings.append(f"push target '{target.name}': TLS verification is disabled")
        if target.url.startswith("http://"):
            warnings.append(f"push target '{target.name}': plain HTTP, the token travels "
                            "in clear text")
    if cfg.discovery.follow_neighbors and not cfg.discovery.allowed:
        warnings.append("discovery.allowed is empty: only the seeds will ever be polled")
    return warnings
