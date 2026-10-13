"""Credential selection and probing.

Order of attempts for an address: the credential forced by ``devices[].credential`` (and only
that one), else the credential remembered in the state for this address, then every credential
whose ``scope`` contains the address, in configuration order. An address that only a
neighbour announced (``scoped_only``) is tried with the credentials that name a scope, never
with the unscoped ones: a device cannot make us send a secret where nobody chose to.
A wrong SNMPv3 user or key is reported immediately by the agent; a wrong v2c community is
silence, i.e. a timeout — hence the short ``probe_timeout`` and the value of narrow scopes.
"""

from __future__ import annotations

import dataclasses
import ipaddress
from dataclasses import dataclass, field

from snowth_my_net.config.loader import ResolvedCredential
from snowth_my_net.snmp.client import EnginePool, SnmpClient, SnmpError, SnmpParams, Value
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import Oid


def candidates_for(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    credentials: list[ResolvedCredential],
    remembered: str | None = None,
    forced: str | None = None,
    scoped_only: bool = False,
) -> list[ResolvedCredential]:
    if ip.version == 6 and ip.ipv4_mapped is not None:      # the same host, the same scope rules
        ip = ip.ipv4_mapped
    def covers(c: ResolvedCredential) -> bool:
        if not c.cfg.scope:
            return not scoped_only
        return any(n and ip.version == n.version and ip in n for n in c.cfg.scope)

    in_scope = [c for c in credentials if covers(c)]
    if forced:
        # Pinned by hand, but still only where its scope says it may be sent: a credential that
        # the configuration confines to some networks never leaves them, whoever pinned it.
        return [c for c in in_scope if c.name == forced]
    ordered = [c for c in in_scope if c.name == remembered]
    ordered += [c for c in in_scope if c.name != remembered]
    return ordered


@dataclass
class ProbeResult:
    credential: ResolvedCredential | None = None
    values: dict[Oid, Value] = field(default_factory=dict)
    attempts: list[tuple[str, str]] = field(default_factory=list)  # (credential, outcome)

    @property
    def ok(self) -> bool:
        return self.credential is not None

    def summary(self) -> str:
        if not self.attempts:
            return "no credential in scope for this address"
        return "; ".join(f"{name}: {outcome}" for name, outcome in self.attempts)


async def probe(
    pool: EnginePool,
    target: Target,
    candidates: list[ResolvedCredential],
    params: SnmpParams,
    probe_timeout: float,
    oids: tuple[Oid, ...],
) -> ProbeResult:
    """Try each candidate with one GET of ``oids``; stop at the first one that answers."""
    result = ProbeResult()
    probe_params = dataclasses.replace(params, timeout=probe_timeout, retries=0)
    for cred in candidates:
        client = SnmpClient(pool.get(cred.name), cred, target, probe_params)
        try:
            values = await client.get(list(oids))
        except SnmpError as exc:
            result.attempts.append((cred.name, exc.kind if exc.kind == "timeout" else str(exc)))
            continue
        result.attempts.append((cred.name, "ok"))
        result.credential = cred
        result.values = values
        return result
    return result
