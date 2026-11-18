"""Which devices still answer to a well-known community ("public"), so the manager can change it.

This is a check, not a credential: the communities tried here are never used to collect, and
are never kept as a secret (they are the very words everybody knows). Each address is asked one
SNMPv2c GET of the identity OIDs per community, with the short ``probe_timeout`` and no retry.
The result is a small JSON file next to the state, replaced as a whole: the web interface reads
it, a collect never depends on it.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from snowth_my_net.config.loader import ResolvedCredential
from snowth_my_net.config.schema import CredentialCfg
from snowth_my_net.snmp.client import EnginePool, SnmpParams
from snowth_my_net.snmp.credentials import probe
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import Oid

FORMAT = 1


class _Word:
    """A community that is not a secret: nothing to hide from the logs, and nothing to leak."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value


@dataclass(frozen=True)
class Finding:
    address: str
    answers: tuple[str, ...]           # the communities that got an answer, in the order asked


def _credential(community: str) -> ResolvedCredential:
    return ResolvedCredential(CredentialCfg(name=f"audit:{community}", version="2c"),
                              community=_Word(community))      # type: ignore[arg-type]


async def audit(targets: list[Target], communities: list[str], params: SnmpParams,
                probe_timeout: float, oids: tuple[Oid, ...],
                concurrency: int = 16) -> list[Finding]:
    """One finding per target, with an empty ``answers`` when it keeps quiet."""
    pool = EnginePool()
    gate = asyncio.Semaphore(max(1, concurrency))
    creds = [_credential(c) for c in communities]

    async def one(target: Target) -> Finding:
        answered = []
        async with gate:
            for cred, community in zip(creds, communities, strict=True):
                result = await probe(pool, target, [cred], params, probe_timeout, oids)
                if result.ok:
                    answered.append(community)
        return Finding(str(target), tuple(answered))

    try:
        return list(await asyncio.gather(*(one(t) for t in targets)))
    finally:
        pool.close()


def save(path: Path, payload: dict) -> None:
    """Replace the file whole: a reader never sees half of one."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": FORMAT, **payload}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path) -> dict | None:
    """The last audit, or ``None`` when there is none (or it is not one we wrote)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    if not isinstance(data.get("exposed"), list):
        return None
    return data
