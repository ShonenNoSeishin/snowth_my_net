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

## Done (fifth batch, 2026-10-16)
- 11. `nodes.live_port_max_age` (7 d): a MAC once heard on a port that no switch has listed for that
  long before the last full collect is memory even when an ARP cache still holds it. A MAC never
  heard on a port is not concerned.
- 12. The Nodes tab of the TUI cycles all / without / only the locally administered MACs (`m`).
  Grouping by announced hostname is abandoned: it is a guess, and nodes are never merged on one.
  Found on the way: with `include_name` the TUI rows started with the name, not the MAC.
- 13. Several web processes can share `web_sessions.json` (file lock, read again before each change,
  every authorization decision reads the file). The login limiter and the log's refusal reason stay
  per process, documented.
- Audit of the zones listed below (read by three independent reviewers, each finding checked in the
  code before any fix, each fix pinned by a test): explain no longer states a cause the merge did not
  use; POST /snmp waits for the state lock; a failing POST answers 500; POSTs wait for the chosen
  password; socket timeout; off-site redirect and login redirect; the import log quotes the MAC cell;
  TUI Delete only on the Devices tab; ENTITY-MIB modules in slots and placeholder models; and smaller
  items (maxlength, VLAN sort, link times, translated status).
- Open-source preparation: https install, no site-specific names or addresses, project URLs,
  copyright line.

## Known, decided not to change
- `decode_text`: six bytes that are not UTF-8 are read as a MAC (a device puts one in a name field);
  a six-byte Latin-1 name such as `Hôtel1` is shown as a MAC. The two cannot be told apart.
- `decode_text`: one control character sends the whole OctetString to hex (a sysDescr with a stray
  `\x01` is not identified). Rare; a hex string is at least honest.
- ENTITY-MIB with no class-3 (chassis) row records nothing (stack-only or container-only roots) and
  for a stack the lowest-index member gives the serial. Not seen on a real device; unverified.
- TUI: heavy work (a full merge when a device is opened, report previews) runs on the UI thread; a
  device screen keeps the connection it first opened until a collect. Fine at the sizes seen so far.
- Web: a scan stopped by its timeout may leave its `nmap` child running.

## Open
- Wording: the scan refusal reason (`outside discovery.allowed`) is still an English config key.

## Not audited
Nothing left in the list of 2026-10-09 (`web/*`, `tui/*`, `entity.py`, `system.py`, `explain.py` were
read on 2026-10-16). `snmp/values.py` was read where those files lead to it.

## Next axes
The UI/UX rework with `frontend-design` and `ui-screenshot`; making the repository public.
