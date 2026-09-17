"""DNS (fake resolvers, no network) and OUI database: every outcome."""

from __future__ import annotations

import asyncio
import gzip
import io

import dns.exception
import dns.resolver
import pytest

from snowth_my_net.config.schema import DnsCfg
from snowth_my_net.enrich import dns as dns_module
from snowth_my_net.enrich import oui


class Record:
    def __init__(self, text: str) -> None:
        self.text = text

    def to_text(self) -> str:
        return self.text


class FakeResolver:
    """``answers`` maps (name, rdtype) or ip -> list of texts, or an exception to raise."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def resolve(self, name, rdtype):
        self.calls.append((name, rdtype))
        answer = self.answers.get((name, rdtype), dns.resolver.NoAnswer())
        if isinstance(answer, Exception):
            raise answer
        return [Record(t) for t in answer]

    async def resolve_address(self, ip):
        answer = self.answers[ip]
        if isinstance(answer, Exception):
            raise answer
        return [Record(t) for t in answer]


def test_make_resolver_uses_configured_servers_and_timeouts(monkeypatch):
    resolver = dns_module.make_resolver(DnsCfg(resolvers=["192.0.2.53"], timeout=1.5))
    assert resolver.nameservers == ["192.0.2.53"] and resolver.lifetime == 1.5

    real = dns_module.dns.asyncresolver.Resolver

    def no_system_config(configure=True):
        if configure:
            raise dns.resolver.NoResolverConfiguration("none")
        return real(configure=False)

    monkeypatch.setattr(dns_module.dns.asyncresolver, "Resolver", no_system_config)
    fallback = dns_module.make_resolver(DnsCfg(timeout=2))
    assert fallback.nameservers == ["127.0.0.1"] and fallback.timeout == 2
    monkeypatch.setattr(dns_module.dns.asyncresolver, "Resolver",
                        lambda configure=True: real(configure=False))
    assert dns_module.make_resolver(DnsCfg()).timeout == DnsCfg().timeout


def test_resolve_host_prefers_ipv4_then_ipv6():
    fake = FakeResolver({("a.example", "A"): ["192.0.2.1", "192.0.2.2"],
                         ("six.example", "A"): dns.resolver.NXDOMAIN(),
                         ("six.example", "AAAA"): ["2001:db8::1"],
                         ("gone.example", "A"): dns.exception.Timeout(),
                         ("gone.example", "AAAA"): dns.resolver.NoNameservers()})
    assert asyncio.run(dns_module.resolve_host(fake, "a.example")) == "192.0.2.1"
    assert asyncio.run(dns_module.resolve_host(fake, "six.example")) == "2001:db8::1"
    with pytest.raises(LookupError, match=r"cannot resolve 'gone.example' \(A: Timeout, "
                                          r"AAAA: NoNameservers\)"):
        asyncio.run(dns_module.resolve_host(fake, "gone.example"))
    empty = FakeResolver({("e.example", "A"): [], ("e.example", "AAAA"): []})
    with pytest.raises(LookupError):
        asyncio.run(dns_module.resolve_host(empty, "e.example"))


def test_ptr_lookup_statuses(monkeypatch):
    fake = FakeResolver({"192.0.2.1": ["host.example.net."], "192.0.2.2": dns.resolver.NXDOMAIN(),
                         "192.0.2.3": dns.resolver.NoAnswer(), "192.0.2.4": dns.exception.Timeout(),
                         "192.0.2.5": dns.resolver.NoNameservers(),
                         "192.0.2.6": dns.exception.SyntaxError(), "192.0.2.7": []})
    monkeypatch.setattr(dns_module, "make_resolver", lambda cfg: fake)
    lookup = dns_module.dnspython_ptr(DnsCfg())

    async def all_results():
        return {ip: await lookup(ip) for ip in fake.answers}

    assert asyncio.run(all_results()) == {
        "192.0.2.1": ("host.example.net", "ok"), "192.0.2.2": (None, "nxdomain"),
        "192.0.2.3": (None, "nxdomain"), "192.0.2.4": (None, "timeout"),
        "192.0.2.5": (None, "error"), "192.0.2.6": (None, "error"),
        "192.0.2.7": (None, "nxdomain")}


def test_resolve_ptrs_without_addresses():
    async def never(ip):
        raise AssertionError(ip)

    assert asyncio.run(dns_module.resolve_ptrs([], DnsCfg(), never, 1)) == {}


# --------------------------------------------------------------------------- OUI


def registry(count: int, header="Registry,Assignment,Organization Name,Organization Address"):
    rows = [header] + [f"MA-L,{i:06X},Vendor {i} Inc.,Somewhere" for i in range(count)]
    rows += ["MA-L,short", "MA-L,ZZZZZZ,Bad prefix,x", "MA-S,00000A000,  Many   spaces  ,x",
             "MA-L,FFFFFE,,empty name"]
    return "\n".join(rows) + "\n"


def test_database_lookup_and_tsv_parsing():
    data = gzip.compress(b"00005e\tICANN, IANA Department\n\n000000a\tpartial-only\nbad line\n")
    db = oui.OuiDatabase.from_tsv(data)
    assert len(db) == 2
    assert db.lookup("00:00:5e:00:53:01") == "ICANN, IANA Department"
    assert db.lookup("00:00:5e:00:53:01", clean=False) == "ICANN, IANA Department"
    assert db.lookup("") == "" and db.lookup("02:00:00:00:00:01") == ""
    assert db.lookup("11:22:33:44:55:66") == ""


def test_parse_registries_and_update(tmp_path, monkeypatch):
    entries = oui.parse_registries([registry(1000)])
    assert entries["00000a000"] == "Many spaces" and "fffffe" not in entries
    with pytest.raises(ValueError, match="unexpected header"):
        oui.parse_registries(["a,b,c\n"])
    with pytest.raises(ValueError, match="unexpected header"):
        oui.parse_registries([""])
    with pytest.raises(ValueError, match="only 2 registry entries"):
        oui.parse_registries([registry(1)])
    with pytest.raises(ValueError, match=r"no oui\.csv"):
        oui.update_database(tmp_path / "db.tsv.gz", [], tmp_path)

    with pytest.raises(ValueError, match="refusing a non-HTTPS"):
        oui.download_registries(["http://standards-oui.ieee.org/oui/oui.csv"])

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, request.get_header("User-agent"), timeout))
        return Response(registry(1000).encode())

    monkeypatch.setattr(oui.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "state" / "oui.tsv.gz"
    count = oui.update_database(dest, ["https://example.invalid/oui.csv"])
    assert count == 1001 and seen[0][0] == "https://example.invalid/oui.csv" and seen[0][1]
    assert oui.load_database(dest).lookup("00:00:0a:10:00:01") == "Vendor 10"
    explicit = tmp_path / "explicit.tsv.gz"
    explicit.write_bytes(oui.to_tsv({"00005e": "Explicit"}))
    assert oui.load_database(dest, explicit).lookup("00:00:5e:00:00:01") == "Explicit"
    assert oui.load_database(tmp_path / "absent", None).lookup("00:00:5e:00:53:01")
