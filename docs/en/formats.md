# Output formats

All files are written atomically in `general.output_dir` (temporary file, `fsync`, rename): a
reader sees the previous file or the new one, never half of one. CSV files are UTF-8 without BOM,
RFC 4180 (CRLF by default, fields quoted only when needed). Their **headers are fixed byte for
byte** (golden-file tested). Every time is UTC, `YYYY-MM-DDTHH:MM:SSZ`, to the second, so the
strings compare correctly.

**Empty-file guard:** a CSV without any data row is neither written over the previous file nor
pushed, and the command exits with code 1 (unless listed in `export.allow_empty`).

## `devices.csv`

```
"Device Name","Device Details","IP Address",Location,Model,Serial,Vendor,"Operating System","OS Version","MAC Address","Device Type"
```

One device per line, sorted by name.

| Column | Content |
|---|---|
| Device Name | `devices[].name` or manual name, else sysName without its domain (`general.device_name`), else the IP. Duplicates get ` (IP)`. **The join key** of `nodes.csv` and `links.csv`. |
| Device Details | sysDescr on a single line. |
| IP Address | Management address that was polled (without port). |
| Location | sysLocation. |
| Model | ENTITY-MIB model of the main chassis (or the vendor-specific sysDescr pattern). |
| Serial | ENTITY-MIB serial of the main chassis (placeholders such as `0` or `N/A` are dropped). All stack members are in `snapshot.json`. |
| Vendor | From the IANA enterprise number of sysObjectID (vendor OUI of the base MAC for generic SNMP stacks). |
| Operating System | e.g. `IOS-XE`, `AOS-CX`, `Junos`, `SFOS`, `FortiOS`. |
| OS Version | From sysDescr, or ENTITY-MIB software revision, or a custom collector fill. |
| MAC Address | `dot1dBaseBridgeAddress`, else the LLDP chassis MAC, else empty. |
| Device Type | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility`, `other` — **or empty when there is no sure evidence**. Set by hand, from config, or detected (own LLDP capabilities, Printer-MIB/UPS-MIB, vendor product identifiers, single-purpose OS or vendor). `snapshot.json` gives the rule and the reason. Can be disabled (`export.devices.include_type`). |

## `nodes.csv`

```
"MAC Address",Vendor,"IP Address","DNS Name",Switch,Port,VLAN,"Last Seen"
```

One line per (MAC, position), sorted by `Last Seen` descending. A consumer grouping by MAC takes
the most recent line as the current position; the other lines are its roaming history.

| Column | Content |
|---|---|
| Name | Only with `export.nodes.include_name: true`: the name given by hand to that MAC (`node name`), empty otherwise. The column is absent by default, so as not to change the columns an importer reads. |
| MAC Address | Lowercase with colons. Broadcast, multicast, zero, VRRP/HSRP virtual MACs and MACs of polled devices are excluded. |
| Vendor | IEEE registry (MA-L/MA-M/MA-S), cleaned; empty for locally administered (random) MACs. |
| IP Address | Current IP of the MAC: among the addresses no other MAC claimed since, those seen within `nodes.current_ip_window` (24 h) of the most recent one, IPv4 first. An IPv6 alone means no recent IPv4 is known: raise `current_ip_window` (say `30d`) so that an IPv4 wins whenever one exists within the retention. Every address of a MAC stays in `snapshot.json` and in the web interface. |
| DNS Name | PTR name of that IP (cached). |
| Switch | Exactly a `Device Name` of `devices.csv`; empty when no access port is known. |
| Port | Short interface name (`Gi1/0/5`, `1/1/12`, `ge-0/0/3`). |
| VLAN | From the MAC table (Q-BRIDGE FDB or Cisco per-VLAN instance), else the port VLAN (PVID). |
| Last Seen | Last observation of this position (not the export time). For a line without position: last observation of the MAC. |

Why a MAC is (or is not) on a port: `snowth_my_net explain <mac|ip>`.

## `links.csv`

```
Local Device,Local Port,Remote Device,Remote Port,Protocol,Last Seen
```

One physical link per line, even when seen from both ends and by both protocols. When both ends
are polled devices, `Local Device` is the one whose name sorts first. `Protocol` is `LLDP`, `CDP`
or `LLDP+CDP`. Phones and stations are excluded unless `export.links.include_endpoints`.

## `snapshot.json`

Everything known, for scripts. `schema` is versioned (`snowth_my_net/snapshot/1`); fields are only
added within a version.

```json
{
  "schema": "snowth_my_net/snapshot/1",
  "generated_at": "2026-09-17T11:00:04Z",
  "tool_version": "…",
  "last_collect": {"run_id": 812, "finished_at": "…", "status": "partial", "stats": {}},
  "devices": [{
    "name": "…", "ip": "…", "address": "…", "sys_name": "…", "description": "…",
    "location": "…", "contact": "…", "object_id": "…", "vendor": "…", "model": "…",
    "serial": "…", "os": "…", "os_version": "…", "base_mac": "…",
    "device_type": "…", "type_rule": "…", "type_reason": "…", "detected_type": "…",
    "credential": "v3-main", "driver": "sophos", "first_seen": "…", "last_seen": "…", "last_collect_status": "ok",
    "chassis": [], "addresses": [], "vlans": [],
    "interfaces": [{"ifindex": 8, "name": "Gi1/0/1", "role": "access", "role_reasons": [],
                    "mac_count": 1, "…": "…"}],
    "neighbors": [{"protocol": "lldp", "local_port": "…", "remote_device": "…",
                   "remote_port": "…", "remote_polled": true, "capabilities": ["bridge"]}],
    "custom": {"collector": {"status": "ok", "values": {}, "table": []}},
    "collection": {"fdb": {"status": "ok", "rows": 1834, "duration_ms": 900, "detail": ""}}
  }],
  "nodes": [{"mac": "…", "vendor": "…", "random_mac": false, "position_kind": "access",
             "current_ip": "…", "dns_name": "…", "first_seen": "…", "last_seen": "…",
             "positions": [], "sightings": [], "ips": []}],
  "links": [{"a": {"device": "…", "port": "…"}, "b": {"device": "…", "port": "…"},
             "protocols": ["LLDP", "CDP"], "endpoint": false, "last_seen": "…"}],
  "errors": [{"device": "…", "function": "arp", "status": "timeout", "detail": "…"}]
}
```

## Maps

* `map.dot` — Graphviz (`dot -Tsvg map.dot > map.svg`); shapes and colours by type, unpolled
  neighbours dashed.
* `map.mmd` — Mermaid (`graph LR`), renders in GitLab, GitHub, Obsidian…
* `map.html` — one self-contained page (no external resource, works offline): zoom, pan,
  drag, search, details on click, light and dark themes.

End hosts are added with `export.map.endpoints: grouped` (one bubble per port) or `all`.

## HTTP push

For each target, each file of `files` is sent **separately, in order**:

```
POST <url>
Authorization: Bearer <token>            (or Basic, or custom headers)
Content-Type: multipart/form-data; boundary=…

--boundary
Content-Disposition: form-data; name="<extra field>"      (optional extra_fields)

value
--boundary
Content-Disposition: form-data; name="file"; filename="devices.csv"
Content-Type: text/csv            (application/json: snapshot, JSON reports; text/markdown, text/html: reports)

<file content>
--boundary--
```

* 2xx is a success; the response body is logged (truncated to 4 KB).
* 202 with `--wait` (or `wait: true`): the job id is read at `poll.id_field` in the JSON body,
  then `GET poll.url` every `poll.interval` until `poll.status_field` is in `success` (OK), is not
  in `pending` (FAILED), or `poll.timeout` expires (FAILED).
* A failed file never prevents the next one. The summary lists `OK`/`FAILED` per file; the exit
  code is 1 when anything failed.
* Redirects are not followed; TLS is verified unless `tls_verify: false`; retries only on network
  errors, 429 (honouring `Retry-After`), 502, 503, 504.
* In `run`, a file whose export failed is reported `FAILED` and the previous file on disk is not
  sent instead.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Partial failure: a device or a forced function failed, an export was empty, a push failed, `health` is stale |
| 2 | Configuration or usage error (invalid YAML, unknown key, unreadable secret, invalid extension or schedule) |
| 3 | The state is locked by another run for longer than `general.lock_wait` |
| 130 | Interrupted; results already committed are kept |
