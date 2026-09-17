"""SNMP client internals with the pysnmp commands replaced by fakes (no network)."""

from __future__ import annotations

import asyncio
import ipaddress
from typing import ClassVar

import pytest
from pyasn1.type import univ
from pysnmp.proto import errind, rfc1902, rfc1905

from snowth_my_net.config.loader import ResolvedCredential
from snowth_my_net.config.schema import CredentialCfg
from snowth_my_net.config.secrets import Secret
from snowth_my_net.config.validate import build
from snowth_my_net.snmp import client as mod
from snowth_my_net.snmp.client import (
    EnginePool,
    SnmpAgentError,
    SnmpAuthError,
    SnmpClient,
    SnmpError,
    SnmpParams,
    SnmpTimeout,
    to_python,
)
from snowth_my_net.snmp.credentials import ProbeResult, candidates_for, probe
from snowth_my_net.snmp.target import AddressError, parse_target, split_host_port
from snowth_my_net.snmp.values import decode_text, is_locally_administered, normalize_mac

BASE = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)


def v2c(name="c1", scope=None):
    cfg = build(CredentialCfg, {"name": name, "version": "2c", "community_file": "x",
                                **({"scope": scope} if scope else {})})
    return ResolvedCredential(cfg, community=Secret("snmp-comm-test", "test"))


def v3(name="u1", auth=True, priv=True):
    data = {"name": name, "version": "3", "username": "snowth"}
    if auth:
        data |= {"auth_protocol": "sha256", "auth_key_file": "a"}
    if priv:
        data |= {"priv_protocol": "aes128", "priv_key_file": "p"}
    cfg = build(CredentialCfg, data)
    return ResolvedCredential(cfg, auth_key=Secret("authkey-test-1", "t") if auth else None,
                              priv_key=Secret("privkey-test-1", "t") if priv else None)


class FakeTransport:
    created: ClassVar[list] = []

    @classmethod
    async def create(cls, address, timeout, retries):
        cls.created.append((cls.__name__, address, timeout, retries))
        return cls()


class FakeTransport6(FakeTransport):
    pass


class Script:
    """Replaces get_cmd/next_cmd/bulk_cmd: pops one scripted answer per request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def factory(self, kind):
        async def cmd(engine, auth, transport, context, *args, lookupMib=False):
            self.calls.append((kind, auth, context, args))
            answer = self.answers.pop(0)
            if callable(answer):
                answer = answer(args)
            return answer
        return cmd


@pytest.fixture
def script(monkeypatch):
    s = Script()
    monkeypatch.setattr(mod, "get_cmd", s.factory("get"))
    monkeypatch.setattr(mod, "next_cmd", s.factory("next"))
    monkeypatch.setattr(mod, "bulk_cmd", s.factory("bulk"))
    monkeypatch.setattr(mod, "UdpTransportTarget", FakeTransport)
    monkeypatch.setattr(mod, "Udp6TransportTarget", FakeTransport6)
    FakeTransport.created = []
    return s


def make_client(cred=None, target="192.0.2.1", **params):
    return SnmpClient(object(), cred or v2c(), parse_target(target), SnmpParams(**params))


def ok(*binds):
    return (None, 0, 0, [(univ.ObjectIdentifier(o), v) for o, v in binds])


async def collect(client, base=BASE):
    return [row async for row in client.walk(base)]


def test_to_python_conversions():
    assert to_python(rfc1905.NoSuchObject()) is None
    assert to_python(rfc1905.EndOfMibView()) is None
    assert to_python(rfc1902.IpAddress("192.0.2.5")) == "192.0.2.5"
    assert to_python(univ.Null()) is None
    assert to_python(rfc1902.OctetString(b"ab")) == b"ab"
    assert to_python(univ.ObjectIdentifier("1.3.6")) == (1, 3, 6)
    assert to_python(rfc1902.Counter64(7)) == 7
    assert to_python(univ.Real(1.5)) is None


async def test_get_and_error_mapping(script):
    c = make_client()
    oid = (1, 3, 6, 1, 2, 1, 1, 5, 0)
    script.answers = [ok((oid, rfc1902.OctetString(b"sw1"))),
                      (errind.requestTimedOut, 0, 0, []),
                      (errind.unknownUserName, 0, 0, []),
                      (errind.unsupportedMsgProcessingModel, 0, 0, []),
                      (None, univ.Integer(5), univ.Integer(1), []),
                      (None, 5, 1, [])]
    assert await c.get([oid]) == {oid: b"sw1"}
    with pytest.raises(SnmpTimeout, match=r"no response from 192\.0\.2\.1 within 3s x 2"):
        await c.get([oid])
    with pytest.raises(SnmpAuthError) as auth:
        await c.get([oid])
    assert auth.value.kind == "auth"
    with pytest.raises(SnmpError) as other:
        await c.get([oid])
    assert type(other.value) is SnmpError
    with pytest.raises(SnmpAgentError, match="agent error 5 at index 1") as agent:
        await c.get([oid])
    assert agent.value.status == 5
    with pytest.raises(SnmpAgentError):
        await c.get([oid])
    assert c.requests == 6
    assert len(FakeTransport.created) == 1        # transport reused


async def test_get_falls_back_to_single_gets_on_nosuchname(script):
    c = make_client()
    a, b = (1, 3, 6, 1, 1), (1, 3, 6, 1, 2)
    script.answers = [(None, 2, 1, []), ok((a, rfc1902.Integer(1))), (None, 2, 1, [])]
    assert await c.get([a, b]) == {a: 1, b: None}
    script.answers = [(None, 2, 1, [])]
    with pytest.raises(SnmpAgentError):
        await c.get([a])                           # a single OID is not retried


async def test_walk_bulk_toobig_nosuchname_loop_and_max_rows(script):
    c = make_client(max_repetitions=8)
    inside = BASE + (1,)
    script.answers = [(None, 1, 0, []), ok((inside, rfc1902.Integer(4)),
                                         (BASE + (2,), rfc1902.Integer(5))),
                      ok((BASE[:-1] + (3, 1), rfc1902.Integer(9)))]
    assert await collect(c) == [(inside, 4), (BASE + (2,), 5)]
    assert [call[3][1] for call in script.calls] == [8, 4, 4]      # repetitions halved

    script.answers = [(None, 2, 0, [])]
    assert await collect(c) == []                  # noSuchName: SNMPv1 end of view
    script.answers = [ok()]
    assert await collect(c) == []
    script.answers = [ok((inside, rfc1905.EndOfMibView()))]
    assert await collect(c) == []
    script.answers = [(None, 5, 0, [])]
    with pytest.raises(SnmpAgentError):
        await collect(c)

    script.answers = [ok((BASE + (2,), rfc1902.Integer(1)), (BASE + (1,), rfc1902.Integer(1)))]
    with pytest.raises(SnmpError, match="non-increasing OID"):
        await collect(c)

    small = make_client(max_rows=1)
    script.answers = [ok((BASE + (1,), rfc1902.Integer(1)), (BASE + (2,), rfc1902.Integer(1)))]
    with pytest.raises(SnmpError, match="more than 1 rows"):
        await collect(small)

    one = make_client(max_repetitions=1)
    script.answers = [(None, 1, 0, [])]
    with pytest.raises(SnmpAgentError):
        await collect(one)                         # tooBig with nothing left to halve


async def test_walk_with_getnext(script):
    c = make_client(use_bulk=False)
    script.answers = [ok((BASE + (1,), rfc1902.OctetString(b"x"))),
                      ok((BASE + (5,), rfc1902.OctetString(b"y"))),
                      ok(((1, 3, 6, 1, 9), rfc1902.OctetString(b"out")))]
    assert await collect(c) == [(BASE + (1,), b"x"), (BASE + (5,), b"y")]
    assert {call[0] for call in script.calls} == {"next"}
    script.answers = [(None, 1, 0, [])]
    with pytest.raises(SnmpAgentError):
        await collect(c)                           # tooBig without bulk is an error


async def test_vlan_contexts_and_auth_data(script):
    community = make_client(v2c()).for_vlan(20)
    assert community._auth.communityName == "snmp-comm-test@20"
    assert community._context_name == ""
    user = make_client(v3()).for_vlan(30)
    assert user._context_name == "vlan-30" and user._community_suffix is None
    bare = make_client(v3(auth=False, priv=False))
    assert bare._auth.authProtocol == mod.USM_AUTH_NONE
    assert bare._auth.privProtocol == mod.USM_PRIV_NONE
    parent = make_client(v2c())
    child = parent.for_vlan(10)
    script.answers = [ok(), ok()]
    await collect(child)
    await collect(parent)
    assert parent.requests == 2 == child.requests   # one shared per-device state


async def test_ipv6_transport_and_pacing(script, monkeypatch):
    c = make_client(target="[2001:db8::1]:1161", pace_ms=40)
    script.answers = [ok(), ok()]
    loop = asyncio.get_running_loop()
    start = loop.time()
    await c.get([(1, 3)])
    await c.get([(1, 3)])
    assert loop.time() - start >= 0.035
    assert FakeTransport.created[-1] == ("FakeTransport6", ("2001:db8::1", 1161), 3.0, 1)


def test_engine_pool_reuses_and_closes():
    pool = EnginePool()
    first = pool.get("a")
    assert pool.get("a") is first and pool.get("b") is not first
    pool.close()
    assert pool.get("a") is not first
    pool.close()


async def test_probe_tries_candidates_in_order(script):
    target = parse_target("192.0.2.9")
    oid = (1, 3, 6, 1, 2, 1, 1, 5, 0)
    script.answers = [(errind.requestTimedOut, 0, 0, []), (errind.unknownCommunityName, 0, 0, []),
                      ok((oid, rfc1902.OctetString(b"fw")))]
    result = await probe(EnginePool(), target, [v2c("a"), v2c("b"), v3("c")], SnmpParams(), 0.5,
                         (oid,))
    assert result.ok and result.credential.name == "c" and result.values == {oid: b"fw"}
    assert result.attempts[0] == ("a", "timeout") and result.attempts[2] == ("c", "ok")
    assert "unknownCommunityName" in result.attempts[1][1] or result.attempts[1][1]
    assert "a: timeout" in result.summary()
    script.answers = [(errind.requestTimedOut, 0, 0, [])]
    failed = await probe(EnginePool(), target, [v2c("a")], SnmpParams(), 0.5, (oid,))
    assert not failed.ok and failed.summary() == "a: timeout"
    assert ProbeResult().summary() == "no credential in scope for this address"


def test_candidates_scope_remembered_and_forced():
    lan = v2c("lan", scope=["192.0.2.0/24"])
    dmz = v2c("dmz", scope=["198.51.100.0/24"])
    anywhere = v3("any")
    ip = ipaddress.ip_address("192.0.2.7")
    assert [c.name for c in candidates_for(ip, [lan, dmz, anywhere])] == ["lan", "any"]
    assert [c.name for c in candidates_for(ip, [lan, dmz, anywhere], "any")] == ["any", "lan"]
    assert [c.name for c in candidates_for(ip, [lan, dmz, anywhere], None, "dmz")] == ["dmz"]
    assert candidates_for(ip, [lan], None, "missing") == []


def test_target_parsing_edges():
    assert split_host_port("[2001:db8::1]:162") == ("2001:db8::1", 162)
    assert split_host_port("2001:db8::1") == ("2001:db8::1", 161)
    for bad in ("", "[2001:db8::1", "host:port", "192.0.2.1:0", "192.0.2.1:70000"):
        with pytest.raises(AddressError):
            parse_target(bad)
    t = parse_target("[2001:db8::2]:1161")
    assert str(t) == "[2001:db8::2]:1161" and t.is_ipv6
    assert str(parse_target("192.0.2.1")) == "192.0.2.1"
    assert parse_target("192.0.2.1").sort_key() < parse_target("192.0.2.1:162").sort_key()


def test_value_helpers_edges():
    assert decode_text(b"caf\xe9\x00") == "café"            # latin-1 fallback, NUL removed
    assert decode_text("x") == "x" and decode_text(None) == ""
    assert normalize_mac(b"not-a-mac") is None
    assert is_locally_administered("02:00:00:00:00:01")
    assert not is_locally_administered("00:00:5e:00:53:01")
