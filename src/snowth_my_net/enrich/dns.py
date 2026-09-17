"""DNS with configurable resolvers and timeouts (dnspython, asyncio).

Used to resolve seed host names and, at export time, the PTR names of node IP addresses
(cached in the state with separate positive and negative lifetimes).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import dns.asyncresolver
import dns.exception
import dns.resolver

from snowth_my_net.config.schema import DnsCfg


def make_resolver(cfg: DnsCfg) -> dns.asyncresolver.Resolver:
    if cfg.resolvers:
        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = list(cfg.resolvers)
    else:
        try:
            resolver = dns.asyncresolver.Resolver()
        except dns.resolver.NoResolverConfiguration:
            resolver = dns.asyncresolver.Resolver(configure=False)
            resolver.nameservers = ["127.0.0.1"]
    resolver.timeout = cfg.timeout
    resolver.lifetime = cfg.timeout
    return resolver


async def resolve_host(resolver: dns.asyncresolver.Resolver, host: str) -> str:
    """First IPv4 address of ``host``, else its first IPv6 address. Raises LookupError."""
    errors = []
    for rdtype in ("A", "AAAA"):
        try:
            answer = await resolver.resolve(host, rdtype)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers,
                dns.exception.Timeout) as exc:
            errors.append(f"{rdtype}: {exc.__class__.__name__}")
            continue
        for record in answer:
            return record.to_text()
    raise LookupError(f"cannot resolve {host!r} ({', '.join(errors)})")


# --------------------------------------------------------------------------- reverse lookups

PtrResult = tuple[str | None, str]          # (name, status: ok | nxdomain | timeout | error)
PtrLookup = Callable[[str], Awaitable[PtrResult]]


def dnspython_ptr(cfg: DnsCfg) -> PtrLookup:
    resolver = make_resolver(cfg)

    async def lookup(ip: str) -> PtrResult:
        try:
            answer = await resolver.resolve_address(ip)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return None, "nxdomain"
        except dns.exception.Timeout:
            return None, "timeout"
        except (dns.resolver.NoNameservers, dns.exception.DNSException):
            return None, "error"
        for record in answer:
            return record.to_text().rstrip("."), "ok"
        return None, "nxdomain"

    return lookup


async def resolve_ptrs(ips: list[str], cfg: DnsCfg, lookup: PtrLookup,
                       budget: float) -> dict[str, PtrResult]:
    """PTR names of ``ips``, bounded by ``cfg.concurrency`` and a global time ``budget``.

    Addresses not looked up before the budget is spent are simply absent from the result and
    will be tried at the next export.
    """
    results: dict[str, PtrResult] = {}
    gate = asyncio.Semaphore(cfg.concurrency)

    async def one(ip: str) -> None:
        async with gate:
            results[ip] = await lookup(ip)

    tasks = [asyncio.create_task(one(ip)) for ip in ips]
    if not tasks:
        return results
    _done, pending = await asyncio.wait(tasks, timeout=budget)
    for task in pending:
        task.cancel()
    return results
