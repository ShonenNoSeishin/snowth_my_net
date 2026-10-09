# TODO — reliability findings (audit of 2026-10-09)

Source: a code-reading audit (nothing was executed), then each fix confirmed by a test that
fails without it. "Done" items are in commit `1a07b93`.

## Done
- A MAC that moved takes its new port (election no longer prefers a port it left).
- ARP states `invalid` / `unknown` are not bindings.
- Probe order is fixed: netbios, mdns, llmnr.
- A scan "down" never replaces a scan that found the host.

## Done (second batch, decided by the user)
- Current IP: an address older than `nodes.current_ip_max_age` (7 d, relative to the node's own
  freshest sighting) is not elected; two addresses seen at the same instant, or more than
  `nodes.max_ips_per_mac` (3), elect none (`Node.ip_ambiguous` says why).
  Refinement of the decision: the age bound is its own key, not `current_ip_window` (24 h),
  so a quiet printer ARPed every two days keeps its address.
- `export.nodes.live_only` (default true): nodes.csv and the map carry live nodes only.
- VLAN column empty unless the MAC table or a VLAN context stated it (golden file updated).
- `export.csv.formula_safe` (default true): leading apostrophe on `=`, `+`, `-`, `@` cells.
- A bridge port absent from a non-empty dot1dBasePortIfIndex table is no longer taken for an
  ifIndex; the collect warns. Cisco per-VLAN instances still fall back to the default table.

## Open
7. A newer sighting behind an uplink does not supersede an older access position (`current`
   stays on the old port, `live` is true).
8. DNS name beats a verified self-stated name with no disagreement flag.
9. IP supersession ignores the VRF (`latest_by_ip` keyed by IP only).
10. `positions: all` exports one row per historical port for the same MAC.
11. Minor: HSRP IPv6 / GLBP virtual MAC prefixes; `is_live` and long ARP caches; LLDP guessed
    local-port mappings as HARD uplink reason; `AIR-` regex matches wireless controllers;
    NetBIOS UDP replies not checked for transaction id / source.

## Not audited
`web/*`, `tui/*`, `collect/tables/entity.py`, `collect/tables/system.py`, `merge/explain.py`.

## Next axes
Security scan (`/claude-security`), then the UI/UX rework with `frontend-design` and
`ui-screenshot`.
