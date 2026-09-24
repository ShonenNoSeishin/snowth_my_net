# Configuration reference

One YAML file (`snowth_my_net init` writes a commented example). Unknown keys are errors, with a
suggestion when a key looks like a typo; `snowth_my_net check` validates the file and tests every
device. Every default is generic: nothing is tuned for a particular network.

**Where the file is looked for:** `--config` > `$SNOWTH_CONFIG` > `./snowth_my_net.yml` >
`/etc/snowth_my_net/config.yml`.

**Durations** are seconds or `30s`, `10m`, `24h`, `7d`. **Addresses** accept an IP or a CIDR.

**Secrets never go in this file.** Communities, SNMPv3 keys, tokens and passwords are read from a
file (`*_file`, relative paths are relative to `general.secrets_dir`) or an environment variable
(`*_env`). Writing `community:`, `auth_key:`, `token:`… is refused (exit code 2). A secret file
readable by group or others triggers a warning; BOM and trailing CR/LF are removed.

**Paths precedence** (`state_dir`, `output_dir`, `secrets_dir`, `extensions_dir`): command-line
option > environment variable (`SNOWTH_STATE_DIR`, `SNOWTH_OUTPUT_DIR`, `SNOWTH_SECRETS_DIR`,
`SNOWTH_EXTENSIONS_DIR`) > this file > default. Relative paths in the file are relative to the
file's directory. This lets one file serve a host installation and the container.

**Manual settings** made in the terminal interface or with `snowth_my_net device set` take
precedence over `devices:` entries, key by key (see `devices`).

## `version`

| Key | Default | Description |
|---|---|---|
| `version` | `1` | Format version of this file. |

## `general`

| Key | Default | Description |
|---|---|---|
| `general.state_dir` | `/var/lib/snowth_my_net` | State: `state.sqlite`, `state.lock`, updated vendor database. Must be on a local disk (the lock uses `flock`). |
| `general.output_dir` | `<state_dir>/output` | CSV, JSON and map outputs. |
| `general.secrets_dir` | `/etc/snowth_my_net/secrets` | Base of relative `*_file` secret paths. |
| `general.extensions_dir` | `<config dir>/extensions` | Custom collectors and reports (`*.yml`), Python extensions (`*.py`), see [extensions](extensions.md). |
| `general.python_extensions` | `[]` | Python extensions to load, by name: `<extensions_dir>/<name>.py` or an installed entry point. Nothing is imported unless listed. |
| `general.log_file` | none | Also log to this file (rotated 10 MB × 5). Logs always go to stderr. |
| `general.log_level` | `info` | `debug`, `info`, `warning`, `error`. |
| `general.language` | `auto` | Language of the terminal interface, and of the explanation it shows for a node: `auto` (from `LANG`), `fr`, `en`. The CLI (`explain`, logs, `--json`) stays in English. |
| `general.device_name.strip_domain` | `first_dot` | Device names: `first_dot` keeps what precedes the first dot (unless the sysName is an IP), `suffixes` removes `domain_suffixes`, `none` keeps the sysName. |
| `general.device_name.domain_suffixes` | `[]` | Suffixes removed when `strip_domain: suffixes`. |
| `general.device_name.duplicate_names` | `suffix_ip` | Two devices with the same name get ` (IP)` appended (`keep` disables it). The name is the join key of `nodes.csv` and `links.csv`. |
| `general.lock_wait.collect` | `60` | How long a `collect` waits for another run before exiting with code 3. |
| `general.lock_wait.default` | `900` | Same for `export`, `push`, `run`, `discover` (they often start at the same minute as a collect). |
| `general.run_timeout` | `3000` | Budget of a whole collect. |
| `general.retention_days` | `90` | Devices, neighbours, custom values and runs not seen for that long are forgotten. |
| `general.snmp.port` | `161` | UDP port for seeds without a port, explored neighbours and sweeps. |
| `general.snmp.timeout` | `3` | Per request, seconds. |
| `general.snmp.retries` | `1` | Retries per request. |
| `general.snmp.probe_timeout` | `2` | Timeout when trying credentials (no retry). A wrong v2c community is silence, so keep it short and use `credentials[].scope`. |
| `general.snmp.max_repetitions` | `25` | GETBULK size. Lower it for fragile agents. |
| `general.snmp.use_bulk` | `true` | `false`: GETNEXT only (agents with broken GETBULK). |
| `general.snmp.concurrency` | `16` | Devices polled in parallel. |
| `general.snmp.per_device_concurrency` | `1` | Simultaneous requests to one device (1 = never a burst). |
| `general.snmp.pace_ms` | `0` | Minimum pause between two requests to the same device. |
| `general.snmp.table_timeout` | `180` | Budget per table; rows received before the timeout are kept (status `partial`). |
| `general.snmp.device_timeout` | `600` | Budget per device. |
| `general.snmp.max_rows_per_table` | `500000` | Safety stop against agents looping forever. |

## `credentials`

An ordered list. For each address, the credential that worked last time is tried first, then
every credential whose `scope` contains the address, in order. SNMPv3 authPriv is recommended:
v2c sends its community in clear text (`check` warns about it).

| Key | Default | Description |
|---|---|---|
| `credentials[].name` | required | Name shown in logs and outputs (never the secret). |
| `credentials[].version` | required | `2c` or `3`. |
| `credentials[].scope` | `[]` (all) | Addresses/CIDRs where this credential is tried. |
| `credentials[].community_file` | | v2c community, from a file. |
| `credentials[].community_env` | | v2c community, from an environment variable. |
| `credentials[].username` | | SNMPv3 user. |
| `credentials[].auth_protocol` | | `md5`, `sha`, `sha224`, `sha256`, `sha384`, `sha512`. |
| `credentials[].auth_key_file` | | SNMPv3 authentication key (at least 8 characters). |
| `credentials[].auth_key_env` | | Same, from the environment. |
| `credentials[].priv_protocol` | | `des`, `3des`, `aes128`, `aes192`, `aes256` (Blumenthal), `aes192c`, `aes256c` (Cisco key extension). Requires `auth_protocol`. |
| `credentials[].priv_key_file` | | SNMPv3 privacy key. |
| `credentials[].priv_key_env` | | Same, from the environment. |

## `discovery`

| Key | Default | Description |
|---|---|---|
| `discovery.seeds` | `[]` | Starting points: IPs, host names (resolved at every run), `host:port`. Seeds may be outside `allowed`, never inside `exclude`. |
| `discovery.allowed` | `[]` | Ranges where devices may be queried (neighbours, sweeps, known devices). |
| `discovery.exclude` | `[]` | Addresses/ranges never queried. |
| `discovery.follow_neighbors` | `true` | Explore LLDP/CDP neighbours (breadth-first) during `collect` and `discover`. |
| `discovery.max_depth` | `3` | Hops from a seed. |
| `discovery.follow_capabilities` | `[bridge, router, wlan_ap]` | Only neighbours announcing one of these are probed; phones and stations never are. |
| `discovery.sweep` | `[]` | Ranges probed actively (inside `allowed`, at most 65536 addresses). |
| `discovery.sweep_rate` | `50` | Probes per second during a sweep. |
| `discovery.sweep_interval` | `86400` | Minimum time between two sweeps (a `collect` sweeps only when due; `discover` always). |
| `discovery.forget_after_days` | `90` | Discovered addresses that never answer again are forgotten (seeds and addresses added by hand are kept). |

## `devices`

Per-device settings, by IP or CIDR. Every entry containing the address applies; the most
specific wins key by key (a /32 beats a /24). Manual settings (TUI, `device set`) win over this
section. **The type never prevents a collection**: standard MIBs are always attempted unless a
function is `off`.

| Key | Default | Description |
|---|---|---|
| `devices[].address` | required | IP or CIDR. |
| `devices[].name` | sysName | Name in every output. |
| `devices[].type` | detected | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility`, `other`. A label only. |
| `devices[].credential` | automatic | Use only this credential. |
| `devices[].features.entity` | `auto` | ENTITY-MIB (model, serial). `auto`: try, silent if absent; `force`: absence is an error (exit 1); `off`: never query. |
| `devices[].features.interfaces` | `auto` | IF-MIB. |
| `devices[].features.ipaddr` | `auto` | Device addresses (IP-MIB). |
| `devices[].features.fdb` | `auto` | MAC tables (Q-BRIDGE, BRIDGE, Cisco per-VLAN). |
| `devices[].features.arp` | `auto` | ARP/NDP tables (both IP-MIB tables, always). |
| `devices[].features.lldp` | `auto` | LLDP neighbours: LLDP-MIB, or LLDP-V2-MIB (802.1AB-2009) when the agent serves that one instead. |
| `devices[].features.cdp` | `auto` | CDP neighbours. |
| `devices[].vlan_indexing` | `auto` | Cisco per-VLAN bridge instances (`community@vlan`, SNMPv3 context `vlan-N`): `auto` uses them when CISCO-VTP-MIB answers and Q-BRIDGE is empty; `cisco` always; `off` never. |
| `devices[].vrfs` | `auto` | ARP caches of non-global VRFs, read in their own SNMP context: `auto` reads the VRFs the device lists (CISCO-VRF-MIB, then MPLS-L3VPN-STD-MIB), `off` reads only the global table, or give the context names to read (`[blue, dmz]`). The context name must match the VRF name; with SNMPv2c the community `community@vrf` is used. |
| `devices[].uplinks` | `[]` | Ports (by name) always treated as uplinks. |
| `devices[].access_ports` | `[]` | Ports always treated as access ports (e.g. a server LACP bond). |
| `devices[].uplink_mac_threshold` | `nodes.uplink_mac_threshold` | Per-device threshold. |
| `devices[].snmp.timeout` | global | Per-device override of `general.snmp.timeout`. |
| `devices[].snmp.retries` | global | Override. |
| `devices[].snmp.max_repetitions` | global | Override (lower it for firewalls). |
| `devices[].snmp.use_bulk` | global | Override. |
| `devices[].snmp.per_device_concurrency` | global | Override. |
| `devices[].snmp.pace_ms` | global | Override (spare a firewall CPU). |
| `devices[].snmp.table_timeout` | global | Override. |
| `devices[].snmp.device_timeout` | global | Override. |
| `devices[].snmp.max_rows_per_table` | global | Override. |
| `devices[].driver` | `auto` | Vendor driver: `auto` (chosen by sysObjectID), `none`, or a driver name (`fortinet`, `sophos`, `mikrotik`, `cisco-wlc`, or one of a Python extension) to use it whatever the device announces. See [drivers](drivers.md). |
| `devices[].tolerate_failure` | `false` | The device stays in the outputs; its failure does not set exit code 1. |
| `devices[].ha_mode` | members | On a cluster virtual IP: `members` polls the member addresses (the VIP becomes an alias), `vip` polls the VIP. |
| `devices[].disabled` | `false` | Never poll this address. |

## `nodes`

How MAC and ARP observations become node positions (see `explain`).

| Key | Default | Description |
|---|---|---|
| `nodes.uplink_mac_threshold` | `50` | A port with more learned MACs in the last walk is a (soft) uplink: a safety net for uplinks without LLDP. High on purpose: an AP, a hypervisor or a desk switch legitimately carries many MACs. |
| `nodes.lag_is_uplink` | `false` | Treat link aggregations as uplinks (LAGs to servers are access ports; LAGs between switches are already found by LLDP/CDP and transit detection). |
| `nodes.ap_ports_are_access` | `true` | A port leading to an unpolled access point is an access port (Wi-Fi clients are located there). |
| `nodes.uplink_fallback` | `false` | A MAC seen only behind soft uplinks (threshold, unpolled bridge) is placed on the one with the fewest MACs (`position_kind: behind_uplink`). Default: no position. |
| `nodes.include_unlocated` | `true` | Rows without switch/port in `nodes.csv` (ARP only, or only behind uplinks). |
| `nodes.include_device_macs` | `false` | Keep the MACs of polled devices as nodes. |
| `nodes.positions` | `all` | `all`: one row per known position (roaming history, most recent first); `current`: only the latest. |
| `nodes.retention_days` | `30` | MAC/ARP observations older than that are purged. |
| `nodes.prefer_ipv4` | `true` | The current IP is IPv4 when one was seen recently. |
| `nodes.current_ip_window` | `86400` | Candidates for the current IP: seen within this window of the newest one. |
| `nodes.transit_window` | `1800` | A MAC seen on two access ports within this window stays on the port with the fewest MACs; the other is transit. |
| `nodes.ignore_macs` | `[]` | MACs never reported. |
| `nodes.ignore_mac_prefixes` | VRRP, HSRP | Prefixes never reported (nibble precision): `00:00:5e:00:01`, `00:00:5e:00:02`, `00:00:0c:07:ac`, `00:00:0c:9f:f`. |

## `dns`

| Key | Default | Description |
|---|---|---|
| `dns.enabled` | `true` | Reverse (PTR) lookups of node IPs at export time. |
| `dns.resolvers` | system | Resolver IPs (a container can query the internal DNS directly). |
| `dns.timeout` | `2` | Per lookup. |
| `dns.concurrency` | `20` | Parallel lookups. |
| `dns.cache_ttl` | `86400` | Lifetime of a found name. |
| `dns.negative_ttl` | `3600` | Lifetime of "no name" / timeout. |
| `dns.budget` | `120` | Total time for lookups per export; the rest waits for the next export. |
| `dns.strip_domain` | `false` | Keep only the host part in `DNS Name`. |

## `oui`

| Key | Default | Description |
|---|---|---|
| `oui.file` | embedded | Explicit vendor database (TSV.gz produced by `oui-update`). |
| `oui.clean_names` | `true` | `Cisco Systems, Inc` → `Cisco Systems`. |
| `oui.urls` | IEEE MA-L, MA-M, MA-S | Sources of `oui-update` (HTTPS only). |

## `export`

| Key | Default | Description |
|---|---|---|
| `export.files` | all | `devices`, `nodes`, `links`, `snapshot`, `map`. |
| `export.allow_empty` | `[]` | CSV files allowed to have no data row. Otherwise an empty CSV is neither written over the previous one nor pushed, and the command exits 1. |
| `export.csv.line_terminator` | `crlf` | `crlf` (RFC 4180) or `lf`. |
| `export.devices.include_type` | `true` | Trailing `"Device Type"` column. |
| `export.links.include_endpoints` | `false` | Include phones and stations in `links.csv` and the map. |
| `export.map.formats` | `[dot, mmd, html]` | Map files. |
| `export.map.endpoints` | `none` | End hosts on the map: `none`, `grouped` (one bubble per port), `all` (grouped above 2000 hosts). |

## `push`

See [formats](formats.md#http-push) for the protocol.

| Key | Default | Description |
|---|---|---|
| `push.targets[].name` | required | Target name (`push --target`). |
| `push.targets[].url` | required | `https://…` (or `http://`, warned). |
| `push.targets[].files` | `[devices, nodes]` | Files sent one by one, in this order. |
| `push.targets[].auth.bearer_token_file` | | `Authorization: Bearer …`, token from a file. |
| `push.targets[].auth.bearer_token_env` | | Same, from the environment. |
| `push.targets[].auth.basic.username` | | Basic authentication user. |
| `push.targets[].auth.basic.password_file` | | Basic password from a file. |
| `push.targets[].auth.basic.password_env` | | Same, from the environment. |
| `push.targets[].headers.<name>.file` | | Extra header whose value comes from a file (e.g. an API key). |
| `push.targets[].headers.<name>.env` | | Same, from the environment. |
| `push.targets[].multipart_field` | `file` | Form field of the file. |
| `push.targets[].extra_fields` | `{}` | Additional (non-secret) form fields. |
| `push.targets[].tls_verify` | `true` | `false` accepts any certificate (warned at every push). Prefer `ca_bundle`. |
| `push.targets[].ca_bundle` | system | CA file for an internal or self-signed certificate. |
| `push.targets[].timeout` | `120` | Per request. |
| `push.targets[].retries` | `0` | Retries on network errors, 429 (`Retry-After`), 502, 503, 504 only. Never on 413 or other 4xx. |
| `push.targets[].wait` | `false` | Wait for 202 jobs (as `--wait`), for scheduled runs. |
| `push.targets[].poll.url` | required | Job URL with `{id}`. |
| `push.targets[].poll.id_field` | `id` | Dotted path of the job id in the 202 JSON body. |
| `push.targets[].poll.status_field` | `status` | Dotted path of the status in the job JSON. |
| `push.targets[].poll.pending` | `[queued, running]` | Keep polling. |
| `push.targets[].poll.success` | `[done]` | Success; any other status is a failure. |
| `push.targets[].poll.interval` | `5` | Between polls. |
| `push.targets[].poll.timeout` | `1800` | Give up after. |

## `schedule`

Declared once, used by both deployments: `snowth_my_net cron print` for the host cron, the
container's scheduler at start-up.

| Key | Default | Description |
|---|---|---|
| `schedule.collect` | `*/10 * * * *` | Frequent: firewalls expire ARP entries within minutes, and the state accumulates observations between exports. `null` disables it. |
| `schedule.export_push` | `0 11,18 * * *` | `run --no-collect` (export, then push when targets exist). |
| `schedule.timezone` | process time zone | Only used to interpret the schedule (`CRON_TZ`); every output is UTC. |
| `schedule.health_max_age` | `auto` | Allowed age of the last successful collect for `health`; `auto` = twice the longest gap of `schedule.collect`. |

## `web`

Read-only web interface (`snowth_my_net web`, or the `web` service of Compose), see
[web](web.md).

| Key | Default | Description |
|---|---|---|
| `web.bind` | `127.0.0.1` | Address it listens on. Use `0.0.0.0` only with accounts, behind a TLS reverse proxy. |
| `web.port` | `8080` | Port it listens on. In Docker the container always listens on 8080 and `SNOWTH_WEB_PORT` chooses the host port. |
| `web.node_limit` | `2000` | Rows sent to the browser on the Nodes page; the page says when it truncates. |
| `web.auth.users` | `[]` | Accounts of the interface. Empty: no login, which is only safe on the loopback. |
| `web.auth.users[].name` | required | User name typed in the login form. A name alone is enough: the first password is invented and logged, then `web passwd` changes it. |
| `web.auth.users[].password_file` | | Optional: a file holding the hash printed by `snowth_my_net web --hash-password` (relative to `general.secrets_dir`), for a password managed outside the tool. |
| `web.auth.users[].password_env` | | The same hash, from an environment variable. Never both forms at once. |
| `web.trusted_proxies` | `[]` | Networks of the reverse proxies allowed to state the reader's address in `X-Forwarded-For` (and `X-Forwarded-Proto`). Anyone else is ignored. `--trusted-proxy CIDR` overrides it for one run. |
| `web.auth.session_hours` | `12` | Lifetime of a session; sessions live in the process and are lost on restart. |

## `hooks`

External programs run after a command, for anything snowth_my_net does not do itself (notify, copy
files, feed another tool). See [extensions](extensions.md#hooks).

```yaml
hooks:
  after_export:
    - name: copy-to-share
      command: [/usr/local/bin/publish-inventory, "{devices}", "{nodes}"]
      timeout: 120
```

| Key | Default | Description |
|---|---|---|
| `hooks.after_collect` | `[]` | After `collect` and the collect stage of `run`. |
| `hooks.after_export` | `[]` | After `export` and the export stage of `run`. |
| `hooks.after_push` | `[]` | After `push` and the push stage of `run` (not after `--dry-run`). |
| `hooks.after_report` | `[]` | After each report written by `report run` (and after each failed one). |
| `hooks.after_collect[].name` | required | Unique within the event; shown in logs and `--json`. |
| `hooks.after_collect[].command` | required | Program and arguments as a **list**; never run through a shell. Placeholders `{event}`, `{status}`, `{run_id}`, `{output_dir}`, `{state_dir}`, `{summary}`; `{devices}`, `{nodes}`, `{links}`, `{snapshot}` after export and push; `{report}`, `{report_file}` after a report. `{{` and `}}` are literal braces. |
| `hooks.after_collect[].timeout` | `60` | Then the process group is terminated, and killed 5 s later. |
| `hooks.after_collect[].when` | `always` | `ok`: only when the stage succeeded; `failed`: only when it did not (`partial` or `failed`). |
| `hooks.after_collect[].env` | `{}` | Literal variables for the program (never secrets). |
| `hooks.after_collect[].pass_env` | `[]` | Variables copied from snowth_my_net's environment (e.g. `HTTPS_PROXY`). `check` warns when one is a secret used by the configuration. |

The other events take the same keys: `hooks.after_export[].name`, `hooks.after_export[].command`, `hooks.after_export[].timeout`, `hooks.after_export[].when`, `hooks.after_export[].env`, `hooks.after_export[].pass_env`, `hooks.after_push[].name`, `hooks.after_push[].command`, `hooks.after_push[].timeout`, `hooks.after_push[].when`, `hooks.after_push[].env`, `hooks.after_push[].pass_env`, `hooks.after_report[].name`, `hooks.after_report[].command`, `hooks.after_report[].timeout`, `hooks.after_report[].when`, `hooks.after_report[].env`, `hooks.after_report[].pass_env`.
