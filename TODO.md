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

## Done (fourth batch, 2026-10-14)
- 8. A DNS name that differs from the name the host states about itself (NetBIOS cut at 15
  characters allowed for) is flagged like a hand-written/DNS disagreement; the order is unchanged.
- 9. An address is declared taken over by another MAC only when one device listed both MACs for
  it: the VRF of an ARP entry is not collected, so two devices may be two routing contexts.
  Two nodes can now both show the same address (honest) instead of one wrongly losing it.
- 10. `positions: all` kept as is and documented (it is what the option promises).
- 11 (part). A polled neighbour whose local port was guessed from its number
  (`port_num_ifindex`, `port_num_bridge_port`) is a soft uplink reason, not proof.
- 12. Random MACs: badge, "without / only" views on Nodes (sorted by port, never merged),
  `export.nodes.local_macs: skip`. Not done: the same filter in the TUI.
- 13. Sessions: idle expiry renewed by use (`session_hours`) with an absolute cap
  (`session_max_hours`), persisted as token hashes in `web_sessions.json`, bound to the account's
  current password (checked at every request), cookie `Max-Age`, refusal reason logged.
- `/scan` without an address asks for one; the scan refusal reads as one sentence.

## Open
11. Left: `is_live` and long ARP caches (an entry kept for weeks keeps a node live).
12. The local-MAC filter in the TUI; grouping by announced hostname was not done (a guess).
13. Several worker processes would not share `web_sessions.json` writes (one process today).
    The refusal reason `unknown` after a redeploy means a cookie issued before the file existed.
- Wording: the scan refusal reason (`outside discovery.allowed`) is still an English config key.

## Not audited
`web/*`, `tui/*`, `collect/tables/entity.py`, `collect/tables/system.py`, `merge/explain.py`.

## Next axes
Security scan (`/claude-security`), then the UI/UX rework with `frontend-design` and
`ui-screenshot`.
