"""DNS with configurable resolvers and timeouts (dnspython, asyncio).

Phase 1 uses it to resolve seed host names; PTR lookups with a cache come in phase 2.
"""

from __future__ import annotations

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
