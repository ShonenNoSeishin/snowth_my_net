---
name: export-compat
description: Check that nodes.csv (and devices.csv, links.csv) still fit what inventory_manager reads from netdisco, and that every exported row comes from an observation. Use before a release or after touching merge/, export/, reports/ or the nodes/export config keys.
---

# export-compat

The point of snowth_my_net: its nodes go to inventory_manager, replacing netdisco in that integration. An export that changes shape, or states something nobody observed, breaks the integration silently. Run these checks, stop at the first failure and report it with its output.

1. **Shape unchanged by default.** `tests/golden/{nodes,devices,links}.csv` are the contract: header, column order, separators, empty-cell conventions. They must pass untouched: `.venv/bin/pytest -q tests/integration -k "golden or csv or phase"`. Never edit a golden file to make a test pass; a change to one needs the user's explicit decision, stated in the commit message.
2. **Nothing new in the default export.** A new column or field is opt-in (config key off by default) or lives in `snapshot.json` / report datasets. Check with `git diff -- tests/golden src/snowth_my_net/export`: the default `nodes.csv` header must not move.
3. **Every row is an observation.** Read the diff of `merge/` and `export/` for: nodes merged on a guess (random MACs, same hostname, same port), an IP that is elected without a fresh ARP sighting (`nodes.current_ip_max_age`, `max_ips_per_mac`), a VLAN that was not stated by the MAC table or a VLAN context, a position taken from a port the MAC left. Each such rule needs a test that fails without it.
4. **Live by default.** `export.nodes.live_only` stays `true` and `export.nodes.random_macs` stays `keep` unless the user decided otherwise.
5. **Formula-safe.** `export.csv.formula_safe` stays `true`; a hostname such as `=cmd` must reach the file with a leading apostrophe.
6. Then run `release-check`. Report to the user in French: which of the six held, which could not be checked (no inventory_manager here: say so), and any default that moved.
