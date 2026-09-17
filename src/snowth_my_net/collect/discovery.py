"""Which addresses to poll: seeds, known targets, sweep ranges — always inside the scope."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.schema import Config
from snowth_my_net.enrich.dns import make_resolver, resolve_host
from snowth_my_net.logs import get_logger
from snowth_my_net.snmp.target import AddressError, Target, has_explicit_port, split_host_port

log = get_logger("discovery")

IpAddr = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass
class Scope:
    allowed: list
    exclude: list
    seeds: set[str]

    def check(self, ip: IpAddr) -> str | None:
        """None if the address may be queried, else the reason why not."""
        if any(n and ip.version == n.version and ip in n for n in self.exclude):
            return "excluded"
        if str(ip) in self.seeds:
            return None
        if any(n and ip.version == n.version and ip in n for n in self.allowed):
            return None
        return "outside discovery.allowed"


@dataclass
class PlannedTarget:
    target: Target
    origin: str            # seed | state | sweep | neighbor
    depth: int = 0
    seed_rank: int = 1_000_000
    remembered_credential: str | None = None
    device_id: int | None = None
    is_current_mgmt: bool = False


@dataclass
class SeedResolution:
    targets: list[tuple[Target, int]]
    errors: list[str]


async def resolve_seeds(cfg: Config) -> SeedResolution:
    """Seeds as Targets, keeping their rank; host names are resolved on every run."""
    resolver = None
    targets, errors = [], []
    for rank, seed in enumerate(cfg.discovery.seeds):
        try:
            host, port = split_host_port(seed)
        except AddressError as exc:
            errors.append(f"seed {seed!r}: {exc}")
            continue
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            resolver = resolver or make_resolver(cfg.dns)
            try:
                ip = ipaddress.ip_address(await resolve_host(resolver, host))
            except LookupError as exc:
                errors.append(f"seed {seed!r}: {exc}")
                continue
        if not has_explicit_port(seed):
            port = cfg.general.snmp.port
        targets.append((Target(str(ip), port), rank))
    return SeedResolution(targets, errors)


def plan_targets(
    cfg: Config,
    seeds: list[tuple[Target, int]],
    known: list,
    only: set[str] | None = None,
    manual: dict | None = None,
) -> tuple[list[PlannedTarget], list[str]]:
    """Merge seeds and known targets; returns ``(targets, notes)`` (skipped addresses).

    Seeds and addresses added by hand may lie outside ``discovery.allowed`` (explicit human
    intent) but never inside ``discovery.exclude``.
    """
    explicit = {t.host for t, _ in seeds}
    explicit |= {split_host_port(r["address"])[0] for r in known if r["origin"] == "manual"}
    scope = Scope(cfg.discovery.allowed, cfg.discovery.exclude, explicit)
    planned: dict[str, PlannedTarget] = {}
    notes: list[str] = []

    for target, rank in seeds:
        planned.setdefault(str(target), PlannedTarget(target, "seed", 0, rank))

    for row in known:
        address = row["address"]
        failed_primary = row["device_status"] == "failed"
        if row["is_alias"] and not failed_primary:
            continue  # the device is polled through its management address
        try:
            host, port = split_host_port(address)
            target = Target(str(ipaddress.ip_address(host)), port)
        except (AddressError, ValueError):
            notes.append(f"{address}: invalid address in state, ignored")
            continue
        entry = planned.get(str(target))
        if entry is None:
            origin = row["origin"] if row["origin"] != "seed" else "state"
            entry = PlannedTarget(target, origin, row["depth"])
            planned[str(target)] = entry
        entry.remembered_credential = row["credential"]
        entry.device_id = row["device_id"]
        entry.is_current_mgmt = row["device_mgmt"] == address

    result = []
    for key, entry in planned.items():
        if only is not None and key not in only and entry.target.host not in only:
            continue
        reason = scope.check(entry.target.ip)
        if reason:
            notes.append(f"{key}: skipped ({reason})")
            continue
        if settings_for(cfg, entry.target.host, manual).disabled:
            notes.append(f"{key}: skipped (disabled in devices:)")
            continue
        result.append(entry)
    result.sort(key=lambda p: (p.seed_rank, p.target.sort_key()))
    return result, notes


def sweep_addresses(cfg: Config, known: set[str]) -> list[Target]:
    """Host addresses of the sweep ranges that are not known yet (inside scope)."""
    scope = Scope(cfg.discovery.allowed, cfg.discovery.exclude, set())
    result = []
    for net in cfg.discovery.sweep:
        hosts = net.hosts() if net.num_addresses > 2 else iter(net)
        for ip in hosts:
            if str(ip) not in known and scope.check(ip) is None:
                result.append(Target(str(ip), cfg.general.snmp.port))
    return result


def neighbor_targets(cfg: Config, neighbors: list, depth: int, known_hosts: set[str],
                     manual: dict | None = None) -> tuple[list[PlannedTarget], list[str]]:
    """Addresses to explore from the LLDP/CDP neighbours of a device polled at ``depth``.

    Bounded by ``discovery.allowed`` / ``exclude``, ``max_depth`` and the neighbour's
    announced capabilities (phones and stations are never probed). ``known_hosts`` is updated.
    """
    notes: list[str] = []
    result: list[PlannedTarget] = []
    d = cfg.discovery
    if not d.follow_neighbors:
        return result, notes
    wanted = set(d.follow_capabilities)
    scope = Scope(d.allowed, d.exclude, set())
    for n in neighbors:
        label = n.sys_name or n.chassis_id or "?"
        addresses = []
        for text in n.mgmt_addresses:
            try:
                addresses.append(ipaddress.ip_address(text))
            except ValueError:
                continue
        if not addresses:
            continue
        # A neighbour may announce several addresses (loopback, out-of-band, IPv6): explore the
        # first one that is in scope, IPv4 before IPv6, in numeric order.
        addresses.sort(key=lambda ip: (ip.version, ip))
        if any(str(ip) in known_hosts for ip in addresses):
            continue
        in_scope = [ip for ip in addresses if scope.check(ip) is None]
        address = str(in_scope[0] if in_scope else addresses[0])
        if depth + 1 > d.max_depth:
            notes.append(f"neighbor {label} ({address}): skipped (max_depth {d.max_depth})")
            continue
        if not (set(n.caps) & wanted) or "telephone" in n.caps:
            caps = ",".join(sorted(n.caps)) or "none"
            notes.append(f"neighbor {label} ({address}): skipped (capabilities {caps})")
            continue
        if not in_scope:
            reasons = sorted({str(scope.check(ip)) for ip in addresses})
            notes.append(f"neighbor {label} ({', '.join(map(str, addresses))}): skipped "
                         f"({'; '.join(reasons)})")
            continue
        if settings_for(cfg, address, manual).disabled:
            notes.append(f"neighbor {label} ({address}): skipped (disabled)")
            continue
        known_hosts.add(address)
        result.append(PlannedTarget(Target(address, cfg.general.snmp.port), "neighbor",
                                    depth + 1))
    return result, notes
