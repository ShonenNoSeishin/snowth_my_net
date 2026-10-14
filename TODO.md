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

## Done (third batch)
- 7. A MAC heard later on a hard uplink leaves an access port its device no longer lists it on
  (verdict `left`, no position rather than a stale one). Soft uplinks (MAC-count threshold only)
  do not trigger it: a busy access port is not proof the host went elsewhere.
- 11 (part). HSRP IPv6 and GLBP virtual MACs are ignored by default; `AIR-CT*` / `AIR-WLC*` CDP
  platforms (wireless controllers) are no longer taken for access points. The NetBIOS reply check
  was done with the security batch.

## Open (each needs data the collect does not hold, or a decision)
8. DNS name beats a verified self-stated name with no disagreement flag.
9. IP supersession ignores the VRF (`latest_by_ip` keyed by IP only): needs the VRF of an ARP
   entry, which is not collected.
10. `positions: all` exports one row per historical port for the same MAC (opt-in; a port the
    MAC left is now dropped when an uplink heard it later, see 7).
11. Left: `is_live` and long ARP caches; LLDP guessed local-port mappings as HARD uplink reason.

## To investigate (asked 2026-10-14)
12. **Random (locally administered) MACs.** Phones and laptops rotate them, so one device shows up
    as many nodes and `live_only` hides none of it. Decide how to treat them: a column or filter
    (`random_mac` already exists on `Node`), grouping by port/VLAN/hostname, a separate view, an
    export option, and what never to claim (a rotated MAC is not "the same device"). No false
    positive: do not merge nodes on a guess.
13. **Login TTL: being signed out in the middle of a session.** Things to check in
    `web/auth.py` / `web/server.py`: the expiry is fixed (`session_hours`, 12 h from login), not
    renewed by activity; sessions live in memory, so a restart, a redeploy or a Docker
    restart signs everyone out; the clock is `time.monotonic`; `change_password` closes the other
    sessions; the cookie's `Max-Age`/flags; several processes or workers behind nginx; the
    "password again" confirmation window (`CONFIRM_SECONDS`). Reproduce first (log the reason a
    token is refused: expired, unknown, closed), then choose between a sliding expiry with an
    absolute cap and persisting sessions.

## Not audited
`web/*`, `tui/*`, `collect/tables/entity.py`, `collect/tables/system.py`, `merge/explain.py`.

## Next axes
Security scan (`/claude-security`), then the UI/UX rework with `frontend-design` and
`ui-screenshot`.
