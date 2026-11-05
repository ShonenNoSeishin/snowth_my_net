"""Configuration schema — the single source of truth for every key of the YAML file.

Defaults are generic (never tuned for a particular site); the reasoning behind each default is
documented in ``docs/en/config.md`` and ``docs/fr/config.md``.
"""

from __future__ import annotations

import re
import zoneinfo
from dataclasses import dataclass, field
from typing import Literal

from snowth_my_net.config.validate import Duration, Network, Networks

DeviceType = Literal[
    "switch", "router", "firewall", "wireless", "server", "printer", "facility", "other"
]
FeatureMode = Literal["auto", "force", "off"]
Capability = Literal[
    "other", "repeater", "bridge", "wlan_ap", "router", "telephone", "docsis", "station"
]
AuthProtocol = Literal["md5", "sha", "sha224", "sha256", "sha384", "sha512"]
PrivProtocol = Literal["des", "3des", "aes128", "aes192", "aes256", "aes192c", "aes256c"]

_SECRET_HINT = "secrets are never written in the YAML; use {0}_file (path) or {0}_env (variable)"


def _positive(name: str, value: float | int | None, allow_zero: bool = False) -> list[str]:
    if value is None:
        return []
    if value < 0 or (value == 0 and not allow_zero):
        return [f"{name} must be {'>= 0' if allow_zero else '> 0'}, got {value}"]
    return []


# --------------------------------------------------------------------------- general


@dataclass
class DeviceNameCfg:
    strip_domain: Literal["first_dot", "suffixes", "none"] = "first_dot"
    domain_suffixes: list[str] = field(default_factory=list)
    duplicate_names: Literal["suffix_ip", "keep"] = "suffix_ip"


@dataclass
class SnmpCfg:
    port: int = 161                         # for seeds without a port, neighbours and sweeps
    timeout: float = 3.0
    retries: int = 1
    probe_timeout: float = 2.0
    max_repetitions: int = 25
    use_bulk: bool = True
    concurrency: int = 16
    per_device_concurrency: int = 1
    pace_ms: int = 0
    table_timeout: Duration = 180
    device_timeout: Duration = 600
    max_rows_per_table: int = 500_000

    def check(self) -> list[str]:
        errs = _positive("timeout", self.timeout) + _positive("probe_timeout", self.probe_timeout)
        errs += _positive("retries", self.retries, allow_zero=True)
        errs += _positive("pace_ms", self.pace_ms, allow_zero=True)
        for name in ("concurrency", "per_device_concurrency", "table_timeout", "device_timeout",
                     "max_rows_per_table"):
            errs += _positive(name, getattr(self, name))
        if not 1 <= self.max_repetitions <= 200:
            errs.append(f"max_repetitions must be between 1 and 200, got {self.max_repetitions}")
        if not 1 <= self.port <= 65535:
            errs.append(f"port must be between 1 and 65535, got {self.port}")
        return errs


@dataclass
class SnmpOverride:
    """Per-device overrides of :class:`SnmpCfg` (unset keys inherit the global value)."""

    timeout: float | None = None
    retries: int | None = None
    max_repetitions: int | None = None
    use_bulk: bool | None = None
    per_device_concurrency: int | None = None
    pace_ms: int | None = None
    table_timeout: Duration | None = None
    device_timeout: Duration | None = None
    max_rows_per_table: int | None = None

    def check(self) -> list[str]:
        errs = _positive("timeout", self.timeout)
        errs += _positive("retries", self.retries, allow_zero=True)
        errs += _positive("pace_ms", self.pace_ms, allow_zero=True)
        for name in ("per_device_concurrency", "table_timeout", "device_timeout",
                     "max_rows_per_table"):
            errs += _positive(name, getattr(self, name))
        if self.max_repetitions is not None and not 1 <= self.max_repetitions <= 200:
            errs.append(f"max_repetitions must be between 1 and 200, got {self.max_repetitions}")
        return errs


@dataclass
class LockWaitCfg:
    collect: Duration = 60
    default: Duration = 900


@dataclass
class GeneralCfg:
    state_dir: str | None = None
    output_dir: str | None = None
    secrets_dir: str | None = None
    extensions_dir: str | None = None       # default: <config directory>/extensions
    python_extensions: list[str] = field(default_factory=list)   # loaded by name only
    log_file: str | None = None
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    language: Literal["auto", "en", "fr"] = "auto"     # terminal interface only
    device_name: DeviceNameCfg = field(default_factory=DeviceNameCfg)
    lock_wait: LockWaitCfg = field(default_factory=LockWaitCfg)
    run_timeout: Duration = 3000
    retention_days: int = 90
    snmp: SnmpCfg = field(default_factory=SnmpCfg)

    def check(self) -> list[str]:
        return _positive("retention_days", self.retention_days) + _positive(
            "run_timeout", self.run_timeout
        )


# --------------------------------------------------------------------------- credentials


@dataclass
class CredentialCfg:
    __forbidden_keys__ = {
        "community": _SECRET_HINT.format("community"),
        "auth_key": _SECRET_HINT.format("auth_key"),
        "priv_key": _SECRET_HINT.format("priv_key"),
        "password": _SECRET_HINT.format("auth_key"),
    }

    name: str
    version: Literal["2c", "3"]
    scope: list[Network] = field(default_factory=list)
    community_file: str | None = None
    community_env: str | None = None
    username: str | None = None
    auth_protocol: AuthProtocol | None = None
    auth_key_file: str | None = None
    auth_key_env: str | None = None
    priv_protocol: PrivProtocol | None = None
    priv_key_file: str | None = None
    priv_key_env: str | None = None

    def check(self) -> list[str]:
        errs: list[str] = []
        who = f"credential '{self.name}'"
        community = bool(self.community_file or self.community_env)
        v3_keys = [k for k in ("username", "auth_protocol", "auth_key_file", "auth_key_env",
                               "priv_protocol", "priv_key_file", "priv_key_env")
                   if getattr(self, k) is not None]
        if self.version == "2c":
            if not community:
                errs.append(f"{who}: v2c needs community_file or community_env")
            if v3_keys:
                errs.append(f"{who}: v2c does not use {', '.join(v3_keys)}")
            return errs
        if community:
            errs.append(f"{who}: SNMPv3 does not use a community")
        if not self.username:
            errs.append(f"{who}: SNMPv3 needs a username")
        has_auth_key = bool(self.auth_key_file or self.auth_key_env)
        has_priv_key = bool(self.priv_key_file or self.priv_key_env)
        if self.auth_protocol and not has_auth_key:
            errs.append(f"{who}: auth_protocol needs auth_key_file or auth_key_env")
        if has_auth_key and not self.auth_protocol:
            errs.append(f"{who}: an auth key is set but auth_protocol is missing")
        if self.priv_protocol and not self.auth_protocol:
            errs.append(f"{who}: privacy (priv_protocol) requires authentication (auth_protocol)")
        if self.priv_protocol and not has_priv_key:
            errs.append(f"{who}: priv_protocol needs priv_key_file or priv_key_env")
        if has_priv_key and not self.priv_protocol:
            errs.append(f"{who}: a privacy key is set but priv_protocol is missing")
        return errs

    @property
    def security_level(self) -> str:
        if self.version == "2c":
            return "v2c"
        if self.priv_protocol:
            return "authPriv"
        return "authNoPriv" if self.auth_protocol else "noAuthNoPriv"


# --------------------------------------------------------------------------- discovery


@dataclass
class DiscoveryCfg:
    seeds: list[str] = field(default_factory=list)
    allowed: Networks = field(default_factory=list)      # a list, or the word "all"
    exclude: list[Network] = field(default_factory=list)
    follow_neighbors: bool = True
    max_depth: int = 3
    follow_capabilities: list[Capability] = field(
        default_factory=lambda: ["bridge", "router", "wlan_ap"]
    )
    sweep: list[Network] = field(default_factory=list)
    sweep_rate: int = 50
    sweep_interval: Duration = 86400
    forget_after_days: int = 90

    def check(self) -> list[str]:
        errs = _positive("max_depth", self.max_depth, allow_zero=True)
        errs += _positive("sweep_rate", self.sweep_rate)
        errs += _positive("forget_after_days", self.forget_after_days)
        for net in self.sweep:
            if net is not None and not any(
                net.version == a.version and net.subnet_of(a) for a in self.allowed if a
            ):
                errs.append(f"sweep range {net} is not inside discovery.allowed")
        total = sum(n.num_addresses for n in self.sweep if n is not None)
        if total > 65536:
            errs.append(f"sweep covers {total} addresses; the limit is 65536 per run")
        return errs


# --------------------------------------------------------------------------- devices


@dataclass
class FeaturesCfg:
    entity: FeatureMode | None = None
    interfaces: FeatureMode | None = None
    ipaddr: FeatureMode | None = None
    fdb: FeatureMode | None = None
    arp: FeatureMode | None = None
    lldp: FeatureMode | None = None
    cdp: FeatureMode | None = None


@dataclass
class DeviceOverride:
    address: Network
    name: str | None = None
    type: DeviceType | None = None
    credential: str | None = None
    features: FeaturesCfg = field(default_factory=FeaturesCfg)
    vlan_indexing: Literal["auto", "cisco", "off"] | None = None
    vrfs: Literal["auto", "off"] | list[str] | None = None
    uplinks: list[str] | None = None
    access_ports: list[str] | None = None
    uplink_mac_threshold: int | None = None
    snmp: SnmpOverride = field(default_factory=SnmpOverride)
    driver: str | None = None
    tolerate_failure: bool | None = None
    ha_mode: Literal["members", "vip"] | None = None
    disabled: bool | None = None

    def check(self) -> list[str]:
        errs = _positive("uplink_mac_threshold", self.uplink_mac_threshold)
        if isinstance(self.vrfs, list):
            from snowth_my_net.collect.functions import VRF_NAME_RE

            errs += [f"vrfs: {name!r} is not a VRF name" for name in self.vrfs
                     if not VRF_NAME_RE.match(name)]
        if self.driver is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.driver):
            errs.append(f"driver: {self.driver!r} is not a driver name")
        return errs   # names are checked once Python extensions are loaded (loader)


# --------------------------------------------------------------------------- nodes / dns / oui


DEFAULT_IGNORED_PREFIXES = [
    "00:00:5e:00:01",  # VRRP IPv4 virtual router MAC (RFC 5798)
    "00:00:5e:00:02",  # VRRP IPv6 virtual router MAC
    "00:00:0c:07:ac",  # HSRPv1 virtual MAC
    "00:00:0c:9f:f",   # HSRPv2 virtual MAC
    "00:05:73:a0",     # HSRP IPv6 virtual MAC (00:05:73:a0:00:00 to 00:05:73:a0:0f:ff)
    "00:07:b4:00",     # GLBP virtual MAC
]


@dataclass
class NodesCfg:
    uplink_mac_threshold: int = 50
    lag_is_uplink: bool = False
    ap_ports_are_access: bool = True
    uplink_fallback: bool = False
    include_unlocated: bool = True
    include_device_macs: bool = False
    positions: Literal["all", "current"] = "all"
    retention_days: int = 30
    prefer_ipv4: bool = True
    elect_link_local: bool = False        # an fe80:: is not an answer to "which address is it?"
    include_link_local_only: bool = False    # a MAC known by nothing else at all: no row
    current_ip_window: Duration = 86400
    # An address this far behind the node's own freshest sighting is not elected, and a MAC with
    # more distinct addresses than max_ips_per_mac (proxy-ARP, gateway) is given none.
    current_ip_max_age: Duration = 604800
    max_ips_per_mac: int = 3
    # A MAC once heard on a switch port that no switch has listed for this long, while an ARP
    # cache still holds it, is memory and not live. 0 turns the rule off.
    live_port_max_age: Duration = 604800
    # "Changes address often": this many distinct IPv4 addresses seen for one MAC within this
    # window of its own freshest sighting. A flag to filter on, never a claim about DHCP.
    ip_churn_min: int = 3
    ip_churn_days: Duration = 604800
    transit_window: Duration = 1800
    ignore_macs: list[str] = field(default_factory=list)
    ignore_mac_prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORED_PREFIXES))

    def check(self) -> list[str]:
        from snowth_my_net.snmp.values import normalize_mac, normalize_mac_prefix

        errs = _positive("uplink_mac_threshold", self.uplink_mac_threshold)
        errs += _positive("retention_days", self.retention_days)
        errs += _positive("ip_churn_min", self.ip_churn_min)
        errs += [f"ignore_macs: invalid MAC {m!r}" for m in self.ignore_macs
                 if normalize_mac(m) is None]
        errs += [f"ignore_mac_prefixes: invalid prefix {p!r}" for p in self.ignore_mac_prefixes
                 if normalize_mac_prefix(p) is None]
        return errs


@dataclass
class DnsCfg:
    enabled: bool = True
    resolvers: list[str] = field(default_factory=list)
    timeout: float = 2.0
    concurrency: int = 20
    cache_ttl: Duration = 86400
    negative_ttl: Duration = 3600
    budget: Duration = 120                  # total time allowed for lookups per export
    strip_domain: bool = False

    def check(self) -> list[str]:
        import ipaddress

        errs = _positive("timeout", self.timeout) + _positive("concurrency", self.concurrency)
        for r in self.resolvers:
            try:
                ipaddress.ip_address(r)
            except ValueError:
                errs.append(f"resolvers: {r!r} is not an IP address")
        return errs


@dataclass
class NamesCfg:
    """Asking a host its own name, when no DNS zone holds it.

    Off by default: it sends a packet to every node rather than to the devices being polled, a
    NetBIOS sweep looks like reconnaissance to an IPS, and a name a host declares about itself is
    weaker evidence than one a zone holds. ``networks`` keeps the questions where they are
    allowed and where they can be answered.
    """

    probe: list[Literal["netbios", "llmnr", "mdns"]] = field(default_factory=list)
    at_export: bool = True              # also ask while exporting; off: only 'names ask' does
    networks: Networks = field(default_factory=list)   # a list, or "all"; empty: every node
    timeout: float = 1.0
    budget: Duration = 60                   # total time per export, like dns.budget
    cache_ttl: Duration = 86400
    negative_ttl: Duration = 3600

    def check(self) -> list[str]:
        errs = _positive("names.timeout", self.timeout) + _positive("names.budget", self.budget)
        duplicates = sorted({p for p in self.probe if self.probe.count(p) > 1})
        errs += [f"names.probe: {p} listed twice" for p in duplicates]
        return errs


@dataclass
class OuiCfg:
    file: str | None = None
    clean_names: bool = True
    urls: list[str] = field(
        default_factory=lambda: [
            "https://standards-oui.ieee.org/oui/oui.csv",
            "https://standards-oui.ieee.org/oui28/mam.csv",
            "https://standards-oui.ieee.org/oui36/oui36.csv",
        ]
    )


# --------------------------------------------------------------------------- export


@dataclass
class CsvCfg:
    line_terminator: Literal["crlf", "lf"] = "crlf"
    formula_safe: bool = True        # a cell starting with = + - @ gets a leading apostrophe


@dataclass
class DevicesExportCfg:
    include_type: bool = True


@dataclass
class NodesExportCfg:
    include_name: bool = False       # a "Name" column: off, so that nodes.csv keeps its shape
    include_description: bool = False
    merge_hostnames: bool = True     # "DNS Name" carries the best of the three, in that order
    live_only: bool = True           # nodes.csv and the map: nodes seen at the last full collect
    local_macs: Literal["keep", "skip"] = "keep"   # skip: no locally administered MAC exported


@dataclass
class LinksExportCfg:
    include_endpoints: bool = False


@dataclass
class MapCfg:
    formats: list[Literal["dot", "mmd", "html"]] = field(
        default_factory=lambda: ["dot", "mmd", "html"]
    )
    endpoints: Literal["none", "grouped", "all"] = "none"


ExportFile = Literal["devices", "nodes", "links", "ports", "snapshot", "map"]


@dataclass
class ExportCfg:
    files: list[ExportFile] = field(
        default_factory=lambda: ["devices", "nodes", "links", "snapshot", "map"]
    )
    allow_empty: list[Literal["devices", "nodes", "links", "ports"]] = field(default_factory=list)
    csv: CsvCfg = field(default_factory=CsvCfg)
    devices: DevicesExportCfg = field(default_factory=DevicesExportCfg)
    nodes: NodesExportCfg = field(default_factory=NodesExportCfg)
    links: LinksExportCfg = field(default_factory=LinksExportCfg)
    map: MapCfg = field(default_factory=MapCfg)


# --------------------------------------------------------------------------- push


@dataclass
class SecretRefCfg:
    file: str | None = None
    env: str | None = None

    def check(self) -> list[str]:
        if bool(self.file) == bool(self.env):
            return ["set exactly one of file or env"]
        return []


@dataclass
class BasicAuthCfg:
    __forbidden_keys__ = {"password": _SECRET_HINT.format("password")}

    username: str
    password_file: str | None = None
    password_env: str | None = None

    def check(self) -> list[str]:
        if bool(self.password_file) == bool(self.password_env):
            return ["basic auth needs exactly one of password_file or password_env"]
        return []


@dataclass
class PushAuthCfg:
    __forbidden_keys__ = {
        "bearer_token": _SECRET_HINT.format("bearer_token"),
        "token": _SECRET_HINT.format("bearer_token"),
    }

    bearer_token_file: str | None = None
    bearer_token_env: str | None = None
    basic: BasicAuthCfg | None = None

    def check(self) -> list[str]:
        if self.bearer_token_file and self.bearer_token_env:
            return ["set either bearer_token_file or bearer_token_env, not both"]
        if (self.bearer_token_file or self.bearer_token_env) and self.basic:
            return ["choose bearer or basic authentication, not both"]
        return []


@dataclass
class PollCfg:
    url: str
    id_field: str = "id"
    status_field: str = "status"
    pending: list[str] = field(default_factory=lambda: ["queued", "running"])
    success: list[str] = field(default_factory=lambda: ["done"])
    interval: Duration = 5
    timeout: Duration = 1800

    def check(self) -> list[str]:
        return [] if "{id}" in self.url else ["poll.url must contain the {id} placeholder"]


PushFile = Literal["devices", "nodes", "links", "ports", "snapshot"]


@dataclass
class PushTargetCfg:
    name: str
    url: str
    files: list[PushFile] = field(default_factory=lambda: ["devices", "nodes"])
    auth: PushAuthCfg = field(default_factory=PushAuthCfg)
    headers: dict[str, SecretRefCfg] = field(default_factory=dict)
    multipart_field: str = "file"
    extra_fields: dict[str, str] = field(default_factory=dict)
    tls_verify: bool = True
    ca_bundle: str | None = None
    timeout: Duration = 120
    retries: int = 0
    wait: bool = False
    poll: PollCfg | None = None

    def check(self) -> list[str]:
        errs = []
        if not self.url.startswith(("https://", "http://")):
            errs.append(f"target '{self.name}': url must start with https:// or http://")
        if not self.files:
            errs.append(f"target '{self.name}': files must not be empty")
        if len(set(self.files)) != len(self.files):
            errs.append(f"target '{self.name}': files contains duplicates")
        errs += _positive("retries", self.retries, allow_zero=True)
        return errs


@dataclass
class PushCfg:
    targets: list[PushTargetCfg] = field(default_factory=list)

    def check(self) -> list[str]:
        names = [t.name for t in self.targets if t]
        dup = sorted({n for n in names if names.count(n) > 1})
        return [f"duplicate push target name(s): {', '.join(dup)}"] if dup else []


# --------------------------------------------------------------------------- schedule


@dataclass
class ScheduleCfg:
    collect: str | None = "*/10 * * * *"
    export_push: str | None = "0 11,18 * * *"
    names: str | None = None         # ask every node its own name (needs names.probe)
    timezone: str | None = None
    health_max_age: Duration | Literal["auto"] = "auto"

    def check(self) -> list[str]:
        from snowth_my_net.schedule.cron import CronError, parse_cron

        errs = []
        if self.timezone:
            try:
                zoneinfo.ZoneInfo(self.timezone)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                errs.append(f"schedule.timezone: unknown time zone {self.timezone!r}")
        for name in ("collect", "export_push", "names"):
            expression = getattr(self, name)
            if expression:
                try:
                    parse_cron(expression)
                except CronError as exc:
                    errs.append(f"schedule.{name}: {exc}")
        return errs


# --------------------------------------------------------------------------- web


@dataclass
class WebUserCfg:
    """One account of the web interface. The file holds a hash, never a password."""

    __forbidden_keys__ = {
        "password": "put a hash in a file: snowth_my_net web --hash-password > FILE, then "
                    "password_file: FILE",
        "password_hash": _SECRET_HINT.format("password"),
    }

    name: str
    password_file: str | None = None
    password_env: str | None = None

    def check(self) -> list[str]:
        """Neither is the usual case: the interface then invents a first password and
        'web passwd' changes it. Both at once is a contradiction."""
        if self.password_file and self.password_env:
            return [f"web user '{self.name}': set password_file or password_env, not both"]
        return []


@dataclass
class WebAuthCfg:
    users: list[WebUserCfg] = field(default_factory=list)   # empty: no login at all
    session_hours: int = 12          # idle time before a session ends; use renews it
    session_max_hours: int = 168     # absolute cap since the login (7 days)

    def check(self) -> list[str]:
        errs = _positive("web.auth.session_hours", self.session_hours)
        errs += _positive("web.auth.session_max_hours", self.session_max_hours)
        names = [u.name for u in self.users if u]
        for name in sorted({n for n in names if names.count(n) > 1}):
            errs.append(f"web.auth: duplicate user name '{name}'")
        errs += ["web.auth: a user name must not be empty" for n in names if not n.strip()]
        return errs


LOOPBACK = ("127.0.0.1", "::1", "localhost")   # addresses only this machine can reach


@dataclass
class WebCfg:
    """Web interface (``snowth_my_net web``): it never writes to a device."""

    bind: str = "127.0.0.1"          # loopback unless there are accounts (see auth)
    port: int = 8080
    node_limit: int = 2000           # rows sent to the browser on the Nodes page
    auth: WebAuthCfg = field(default_factory=WebAuthCfg)
    trusted_proxies: list[Network] = field(default_factory=list)   # who may set X-Forwarded-For
    actions: bool = True             # the buttons that start a collect, a discovery, an export
    nmap: bool = False               # a port scan of one address, from its page (needs an account)

    def check(self) -> list[str]:
        errs = []
        if not 1 <= self.port <= 65535:
            errs.append(f"web.port: {self.port} is not a port number")
        errs += _positive("web.node_limit", self.node_limit)
        return errs


# --------------------------------------------------------------------------- hooks

HOOK_COMMON_FIELDS = ("event", "status", "run_id", "output_dir", "state_dir", "summary")
HOOK_EVENT_FIELDS = {
    "after_collect": (),
    "after_export": ("devices", "nodes", "links", "snapshot"),
    "after_push": ("devices", "nodes", "links", "snapshot"),
    "after_report": ("report", "report_file"),
}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def hook_placeholders(argument: str) -> list[str]:
    """Names between single braces; ``{{`` and ``}}`` are literal braces."""
    return _PLACEHOLDER.findall(argument.replace("{{", "").replace("}}", ""))


@dataclass
class HookCfg:
    name: str
    command: list[str]                       # argv, never a shell line
    timeout: Duration = 60
    when: Literal["always", "ok", "failed"] = "always"
    env: dict[str, str] = field(default_factory=dict)     # literal, non-secret values
    pass_env: list[str] = field(default_factory=list)     # variables copied from the caller

    def check(self) -> list[str]:
        errs = []
        if not self.command or not self.command[0].strip():
            errs.append(f"hook '{self.name}': command must be a non-empty list (program first)")
        if len(self.command) == 1 and " " in self.command[0].strip():
            errs.append(f"hook '{self.name}': command is a list of arguments, not a shell line "
                        f"(write [{', '.join(repr(a) for a in self.command[0].split())}])")
        errs += _positive(f"hook '{self.name}' timeout", self.timeout)
        for key in [*self.env, *self.pass_env]:
            if not _ENV_NAME.match(key):
                errs.append(f"hook '{self.name}': {key!r} is not a variable name")
            elif key.upper().startswith("SNOWTH_"):
                errs.append(f"hook '{self.name}': {key} is reserved (SNOWTH_* are set by the "
                            "tool)")
        return errs


@dataclass
class HooksCfg:
    after_collect: list[HookCfg] = field(default_factory=list)
    after_export: list[HookCfg] = field(default_factory=list)
    after_push: list[HookCfg] = field(default_factory=list)
    after_report: list[HookCfg] = field(default_factory=list)

    def events(self) -> dict[str, list[HookCfg]]:
        return {event: getattr(self, event) for event in HOOK_EVENT_FIELDS}

    def check(self) -> list[str]:
        errs = []
        for event, hooks in self.events().items():
            names = [h.name for h in hooks if h]
            for name in sorted({n for n in names if names.count(n) > 1}):
                errs.append(f"hooks.{event}: duplicate hook name '{name}'")
            allowed = set(HOOK_COMMON_FIELDS) | set(HOOK_EVENT_FIELDS[event])
            for hook in hooks:
                if not hook:
                    continue
                for argument in hook.command:
                    for name in hook_placeholders(argument):
                        if name not in allowed:
                            errs.append(f"hooks.{event}.{hook.name}: unknown placeholder "
                                        f"{{{name}}} (available: "
                                        f"{', '.join('{' + a + '}' for a in sorted(allowed))})")
        return errs


# --------------------------------------------------------------------------- root


@dataclass
class Config:
    version: Literal[1] = 1
    general: GeneralCfg = field(default_factory=GeneralCfg)
    credentials: list[CredentialCfg] = field(default_factory=list)
    discovery: DiscoveryCfg = field(default_factory=DiscoveryCfg)
    devices: list[DeviceOverride] = field(default_factory=list)
    nodes: NodesCfg = field(default_factory=NodesCfg)
    dns: DnsCfg = field(default_factory=DnsCfg)
    names: NamesCfg = field(default_factory=NamesCfg)
    oui: OuiCfg = field(default_factory=OuiCfg)
    export: ExportCfg = field(default_factory=ExportCfg)
    push: PushCfg = field(default_factory=PushCfg)
    schedule: ScheduleCfg = field(default_factory=ScheduleCfg)
    web: WebCfg = field(default_factory=WebCfg)
    hooks: HooksCfg = field(default_factory=HooksCfg)

    def check(self) -> list[str]:
        errs = []
        names = [c.name for c in self.credentials if c]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            errs.append(f"duplicate credential name(s): {', '.join(dup)}")
        for i, dev in enumerate(self.devices):
            if dev and dev.credential and dev.credential not in names:
                errs.append(f"devices[{i}].credential: unknown credential '{dev.credential}'")
        return errs
