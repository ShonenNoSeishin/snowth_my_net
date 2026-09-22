"""The ONLY module that talks SNMP — read-only by construction.

Only GET, GETNEXT and GETBULK exist here: the pysnmp functions able to build any other request
are never imported, and ``tests/unit/test_readonly.py`` fails if they appear anywhere in the
source tree or if pysnmp is imported outside this module.

Values are converted to plain Python types before leaving this module:
``bytes`` (OctetString, Bits, Opaque), ``int`` (all integer types), ``tuple[int, ...]`` (OID),
``str`` (IpAddress, dotted) and ``None`` (noSuchObject / noSuchInstance).
"""

from __future__ import annotations

import asyncio
import ipaddress
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pyasn1.type import univ
from pysnmp.hlapi.v3arch.asyncio import (
    USM_AUTH_HMAC96_MD5,
    USM_AUTH_HMAC96_SHA,
    USM_AUTH_HMAC128_SHA224,
    USM_AUTH_HMAC192_SHA256,
    USM_AUTH_HMAC256_SHA384,
    USM_AUTH_HMAC384_SHA512,
    USM_AUTH_NONE,
    USM_PRIV_CBC56_DES,
    USM_PRIV_CBC168_3DES,
    USM_PRIV_CFB128_AES,
    USM_PRIV_CFB192_AES,
    USM_PRIV_CFB192_AES_BLUMENTHAL,
    USM_PRIV_CFB256_AES,
    USM_PRIV_CFB256_AES_BLUMENTHAL,
    USM_PRIV_NONE,
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    Udp6TransportTarget,
    UdpTransportTarget,
    UsmUserData,
    bulk_cmd,
    get_cmd,
    next_cmd,
)
from pysnmp.proto import errind, rfc1902, rfc1905

from snowth_my_net.config.loader import ResolvedCredential
from snowth_my_net.snmp.target import Target
from snowth_my_net.snmp.values import Oid, has_prefix, oid_str

# pysnmp still imports CFB from its pre-"decrepit" location in cryptography; harmless noise.
warnings.filterwarnings("ignore", message=r"CFB has been moved")

Value = bytes | int | str | tuple[int, ...] | None

AUTH_PROTOCOLS = {
    "md5": USM_AUTH_HMAC96_MD5, "sha": USM_AUTH_HMAC96_SHA, "sha224": USM_AUTH_HMAC128_SHA224,
    "sha256": USM_AUTH_HMAC192_SHA256, "sha384": USM_AUTH_HMAC256_SHA384,
    "sha512": USM_AUTH_HMAC384_SHA512,
}
PRIV_PROTOCOLS = {
    "des": USM_PRIV_CBC56_DES, "3des": USM_PRIV_CBC168_3DES, "aes128": USM_PRIV_CFB128_AES,
    # draft-blumenthal-aes-usm (net-snmp "AES-192"/"AES-256")
    "aes192": USM_PRIV_CFB192_AES_BLUMENTHAL, "aes256": USM_PRIV_CFB256_AES_BLUMENTHAL,
    # Reeder key extension, Cisco-compatible (net-snmp "AES-192-C"/"AES-256-C")
    "aes192c": USM_PRIV_CFB192_AES, "aes256c": USM_PRIV_CFB256_AES,
}

_AUTH_ERRORS = (
    errind.UnknownUserName, errind.WrongDigest, errind.AuthenticationFailure,
    errind.AuthenticationError, errind.DecryptionError, errind.UnknownSecurityName,
    errind.UnsupportedSecurityLevel, errind.UnknownCommunityName,
)
_ERROR_TOO_BIG = 1
_ERROR_NO_SUCH_NAME = 2


class SnmpError(Exception):
    kind = "error"


class SnmpTimeout(SnmpError):
    kind = "timeout"


class SnmpAuthError(SnmpError):
    kind = "auth"


class SnmpAgentError(SnmpError):
    """The agent answered with an error status (genErr, tooBig…)."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SnmpParams:
    timeout: float = 3.0
    retries: int = 1
    max_repetitions: int = 25
    use_bulk: bool = True
    per_device_concurrency: int = 1
    pace_ms: int = 0
    max_rows: int = 500_000


def to_python(value: object) -> Value:
    # Order matters: NoSuch*/EndOfMibView derive from Null, itself an OctetString subclass,
    # and IpAddress is an OctetString too.
    if isinstance(value, rfc1905.NoSuchObject | rfc1905.NoSuchInstance | rfc1905.EndOfMibView):
        return None
    if isinstance(value, rfc1902.IpAddress):
        return str(ipaddress.IPv4Address(bytes(value.asOctets())))
    if isinstance(value, univ.Null):
        return None
    if isinstance(value, univ.OctetString):
        return bytes(value.asOctets())
    if isinstance(value, univ.ObjectIdentifier):
        return tuple(value)
    if isinstance(value, univ.Integer):
        return int(value)
    return None


def _auth_data(credential: ResolvedCredential, community_suffix: str | None) -> object:
    cfg = credential.cfg
    if cfg.version == "2c":
        assert credential.community is not None
        community = credential.community.reveal()
        if community_suffix:
            community = f"{community}@{community_suffix}"
        return CommunityData(community, mpModel=1)
    return UsmUserData(
        cfg.username,
        authKey=credential.auth_key.reveal() if credential.auth_key else None,
        privKey=credential.priv_key.reveal() if credential.priv_key else None,
        authProtocol=AUTH_PROTOCOLS[cfg.auth_protocol] if cfg.auth_protocol else USM_AUTH_NONE,
        privProtocol=PRIV_PROTOCOLS[cfg.priv_protocol] if cfg.priv_protocol else USM_PRIV_NONE,
    )


class EnginePool:
    """One pysnmp engine per credential, so that homonymous SNMPv3 users never clash."""

    def __init__(self) -> None:
        self._engines: dict[str, SnmpEngine] = {}

    def get(self, key: str) -> SnmpEngine:
        if key not in self._engines:
            self._engines[key] = SnmpEngine()
        return self._engines[key]

    def close(self) -> None:
        for engine in self._engines.values():
            engine.close_dispatcher()
        self._engines.clear()


@dataclass
class _DeviceState:
    """Shared by every client talking to one device (including per-VLAN clones)."""

    semaphore: asyncio.Semaphore
    pace: float
    next_at: float = 0.0
    requests: int = 0
    transports: dict[tuple, object] = field(default_factory=dict)

    async def wait_turn(self) -> None:
        if self.pace <= 0:
            return
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now < self.next_at:
            await asyncio.sleep(self.next_at - now)
            now = loop.time()
        self.next_at = now + self.pace


class SnmpClient:
    def __init__(
        self,
        engine: SnmpEngine,
        credential: ResolvedCredential,
        target: Target,
        params: SnmpParams,
        *,
        context_name: str = "",
        community_suffix: str | None = None,
        _state: _DeviceState | None = None,
    ) -> None:
        self.engine = engine
        self.credential = credential
        self.target = target
        self.params = params
        self._context_name = context_name
        self._community_suffix = community_suffix
        self._auth = _auth_data(credential, community_suffix)
        self._context = ContextData(contextName=context_name.encode())
        self._state = _state or _DeviceState(
            semaphore=asyncio.Semaphore(params.per_device_concurrency),
            pace=params.pace_ms / 1000,
        )

    @property
    def requests(self) -> int:
        return self._state.requests

    def for_vlan(self, vlan: int) -> SnmpClient:
        """Client for a Cisco per-VLAN bridge instance: ``community@vlan`` or context ``vlan-N``."""
        return self.for_context(f"vlan-{vlan}", str(vlan))

    def for_context(self, context: str, community_suffix: str | None = None) -> SnmpClient:
        """Same device, same credential, in another SNMP context.

        SNMPv3 names the context directly; v2c has no context, so the agent's convention of a
        ``community@suffix`` is used instead (``suffix`` defaults to the context name).
        """
        v3 = self.credential.cfg.version == "3"
        return SnmpClient(
            self.engine, self.credential, self.target, self.params,
            context_name=context if v3 else "",
            community_suffix=None if v3 else (community_suffix or context),
            _state=self._state,
        )

    async def _transport(self) -> object:
        key = (self.params.timeout, self.params.retries)
        transport = self._state.transports.get(key)
        if transport is None:
            cls = Udp6TransportTarget if self.target.is_ipv6 else UdpTransportTarget
            transport = await cls.create(
                (self.target.host, self.target.port),
                timeout=self.params.timeout, retries=self.params.retries,
            )
            self._state.transports[key] = transport
        return transport

    async def _request(self, func, *args) -> list[tuple[Oid, object]]:
        transport = await self._transport()
        async with self._state.semaphore:
            await self._state.wait_turn()
            self._state.requests += 1
            err_ind, err_status, err_index, var_binds = await func(
                self.engine, self._auth, transport, self._context, *args, lookupMib=False
            )
        if err_ind:
            if isinstance(err_ind, errind.RequestTimedOut):
                raise SnmpTimeout(f"no response from {self.target} within "
                                  f"{self.params.timeout:g}s x {self.params.retries + 1}")
            if isinstance(err_ind, _AUTH_ERRORS):
                raise SnmpAuthError(f"{self.target}: {err_ind}")
            raise SnmpError(f"{self.target}: {err_ind}")
        status = int(err_status or 0)
        if status:
            label = err_status.prettyPrint() if hasattr(err_status, "prettyPrint") else status
            raise SnmpAgentError(f"{self.target}: agent error {label} at index "
                                 f"{int(err_index or 0)}", status)
        return [(tuple(oid), value) for oid, value in var_binds]

    async def get(self, oids: list[Oid] | tuple[Oid, ...]) -> dict[Oid, Value]:
        """GET several scalars; missing ones come back as None."""
        objects = [ObjectType(ObjectIdentity(oid_str(o))) for o in oids]
        try:
            rows = await self._request(get_cmd, *objects)
        except SnmpAgentError as exc:
            # Some agents answer noSuchName for the whole PDU instead of per-varbind
            # exceptions: fall back to one GET per OID.
            if exc.status != _ERROR_NO_SUCH_NAME or len(oids) == 1:
                raise
            result: dict[Oid, Value] = {}
            for oid in oids:
                try:
                    result.update(await self.get([oid]))
                except SnmpAgentError:
                    result[oid] = None
            return result
        return {oid: to_python(value) for oid, value in rows}

    async def walk(self, base: Oid) -> AsyncIterator[tuple[Oid, Value]]:
        """Walk a subtree with GETBULK (or GETNEXT). Stops at the end of the subtree."""
        current, last, rows = base, None, 0
        repetitions = self.params.max_repetitions
        while True:
            start = ObjectType(ObjectIdentity(oid_str(current)))
            try:
                if self.params.use_bulk:
                    batch = await self._request(bulk_cmd, 0, repetitions, start)
                else:
                    batch = await self._request(next_cmd, start)
            except SnmpAgentError as exc:
                if exc.status == _ERROR_TOO_BIG and self.params.use_bulk and repetitions > 1:
                    repetitions = max(1, repetitions // 2)
                    continue
                if exc.status == _ERROR_NO_SUCH_NAME:
                    return  # SNMPv1-style end of MIB view
                raise
            if not batch:
                return
            for oid, value in batch:
                if isinstance(value, rfc1905.EndOfMibView) or not has_prefix(oid, base):
                    return
                if last is not None and oid <= last:
                    raise SnmpError(f"{self.target}: agent returned a non-increasing OID "
                                    f"({oid_str(oid)} after {oid_str(last)}); try use_bulk: false")
                last = oid
                rows += 1
                if rows > self.params.max_rows:
                    raise SnmpError(f"{self.target}: more than {self.params.max_rows} rows under "
                                    f"{oid_str(base)}; stopping (max_rows_per_table)")
                yield oid, to_python(value)
            current = last
