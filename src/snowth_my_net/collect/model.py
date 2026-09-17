"""Data produced by one collection of one device (shared by engine, state and exporters)."""

from __future__ import annotations

from dataclasses import dataclass, field

from snowth_my_net.collect.tables.arp import ArpEntry
from snowth_my_net.collect.tables.bridge import FdbEntry
from snowth_my_net.collect.tables.entity import Chassis
from snowth_my_net.collect.tables.interfaces import Interface
from snowth_my_net.collect.tables.ipaddr import DeviceAddress
from snowth_my_net.collect.tables.neighbors import Neighbor
from snowth_my_net.collect.tables.system import SystemInfo
from snowth_my_net.config.effective import DeviceSettings
from snowth_my_net.snmp.target import Target

# Per-function statuses. "absent" = the agent has no rows for this MIB (not an error in
# ``auto`` mode); "forced_absent" = same, but the function is ``force``d (an error).
OK, ABSENT, PARTIAL, TIMEOUT, ERROR, SKIPPED, FORCED_ABSENT = (
    "ok", "absent", "partial", "timeout", "error", "skipped", "forced_absent")
FAILURE_STATUSES = frozenset({PARTIAL, TIMEOUT, ERROR, FORCED_ABSENT})


@dataclass
class Outcome:
    function: str
    status: str
    rows: int = 0
    duration_ms: int = 0
    detail: str = ""


@dataclass
class TypeEvidence:
    """Vendor-neutral function MIBs answered by the device."""

    printer_mib: bool = False
    ups_mib: bool = False


@dataclass
class Identification:
    vendor: str = ""
    pen: int | None = None
    model: str = ""
    serial: str = ""
    os_name: str = ""
    os_version: str = ""
    device_type: str = ""      # "" = no sure evidence
    type_rule: str = ""
    type_reason: str = ""


@dataclass
class DeviceResult:
    target: Target
    origin: str
    depth: int
    settings: DeviceSettings
    credential: str | None = None
    attempts: list[tuple[str, str]] = field(default_factory=list)
    system: SystemInfo | None = None
    chassis: list[Chassis] = field(default_factory=list)
    interfaces: dict[int, Interface] = field(default_factory=dict)
    addresses: list[DeviceAddress] = field(default_factory=list)
    evidence: TypeEvidence = field(default_factory=TypeEvidence)
    fdb: list[FdbEntry] = field(default_factory=list)
    arp: list[ArpEntry] = field(default_factory=list)
    vlans: dict[int, str] = field(default_factory=dict)          # vlan -> name
    pvid: dict[int, int] = field(default_factory=dict)           # ifIndex -> access/PVID vlan
    bridge_ports: dict[int, int] = field(default_factory=dict)   # bridge port -> ifIndex
    neighbors: list[Neighbor] = field(default_factory=list)
    ident: Identification | None = None
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    error: str | None = None
    seed_rank: int = 1_000_000            # position in discovery.seeds (lower is preferred)
    is_current_mgmt: bool = False         # this address is the stored management address
    device_id: int | None = None          # existing state row this result belongs to
    alias_of: DeviceResult | None = None  # set when another address of the same device won
    superseded: bool = False              # another address won while this one was running
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def reachable(self) -> bool:
        return self.system is not None

    @property
    def status(self) -> str:
        if not self.reachable:
            return "failed"
        if any(o.status in FAILURE_STATUSES for o in self.outcomes.values()):
            return "partial"
        return "ok"

    def outcome_status(self, function: str) -> str | None:
        o = self.outcomes.get(function)
        return o.status if o else None
