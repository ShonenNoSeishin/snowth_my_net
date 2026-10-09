# TODO — reliability findings (audit of 2026-10-09)

Source: a code-reading audit (nothing was executed), then each fix confirmed by a test that
fails without it. "Done" items are in commit `1a07b93`.

## Done
- A MAC that moved takes its new port (election no longer prefers a port it left).
- ARP states `invalid` / `unknown` are not bindings.
- Probe order is fixed: netbios, mdns, llmnr.
- A scan "down" never replaces a scan that found the host.

## Open, waiting for a decision
1. **Stale or tied current IP** (`merge/nodes.py`, IP election). The window is relative to the MAC's
   own newest ARP row, never to now: an IP last seen 25 days ago can be printed as the IP, and
   two IPs with the same timestamp tie on the lowest address. Rule to choose.
2. **MAC with many IPs** (proxy-ARP, gateway, hypervisor): one IP is picked as "its" IP, so a PTR
   or probe name of another machine can be attributed to it. Needs a threshold.
3. **Nodes not seen for days exported as current** (`merge/view.py rows()`, `export/maps.py`):
   `live` is ignored by `nodes.csv` and the map. Behaviour change.
4. **VLAN column guessed** (`pvid`, `fdb_assumed` sources written as if observed).
5. **Partial dot1dBasePortIfIndex table**: a missing bridge port is taken as an ifIndex
   (`collect/tables/bridge.py:97`, `collect/functions.py:163`). Dropping could lose valid MACs.
6. **CSV formula injection** in exports (cells starting with `=`, `+`, `-`, `@`).
7. **A newer sighting behind an uplink** does not supersede an older access position
   (`merge/nodes.py`): `current` stays on the old port and `live` is true.
8. **DNS name beats a verified self-stated name** with no disagreement flag
   (`merge/view.py hostname()`, `hostnames_disagree`).
9. **IP supersession ignores the VRF** (`latest_by_ip` keyed by IP only).
10. `positions: all` exports one row per historical port for the same MAC.
11. Minor: virtual MAC prefixes for HSRP IPv6 / GLBP not ignored by default; the ARP-fresh rule
    in `is_live` keeps a gone host "live" behind a router with long ARP caches; LLDP
    guessed local-port mappings can create a HARD uplink reason; `AIR-` regex also matches
    wireless controllers; NetBIOS UDP replies are not checked for transaction id / source.

## Not audited
`web/*`, `tui/*`, `collect/tables/entity.py`, `collect/tables/system.py`, `merge/explain.py`.

## Next axes
Security scan (`/claude-security`), then the UI/UX rework with `frontend-design` and
`ui-screenshot`.
