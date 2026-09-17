# Extensions

snowth_my_net can read more than the standard MIBs without touching its code. Everything stays
read-only (GET/GETNEXT/GETBULK, same timeouts and pacing), and an extension only **adds** data: it
never switches a standard collection off.

## Custom collectors (extra OIDs)

A collector says what to read, on which devices, and how to interpret the values. Two ways to
create one:

1. **From the terminal interface:** device → *OID tester* → test a preset or an OID → *Save as
   custom OID* → choose a name, how to interpret the value, and where to read it (this device,
   this vendor, this type, every device). It is read at the next collect.
2. **In YAML:** files `*.yml` in `general.extensions_dir` (default: `extensions/` next to the
   configuration file; `config/extensions/` with Docker). A broken file is a configuration error
   (exit 2) naming the file. Start from [`examples/extensions/examples.yml`](../examples/extensions/examples.yml).

```yaml
version: 1
collectors:
  - name: fortigate-version              # lowercase, digits, - and _
    description: FortiOS version
    applies_to:                          # all criteria must match; omit to read everywhere
      vendors: [Fortinet]
      # types: [firewall]
      # addresses: [192.0.2.0/24]
      # sys_object_ids: [1.3.6.1.4.1.12356.101.1]
    get:                                 # scalars…
      version: {oid: 1.3.6.1.4.1.12356.101.4.1.1.0, type: text}
    fills: {os_version: version}         # fill an empty standard field
    # fill_override: true                # …even when it is not empty
    every: 6h                            # default: at every collect
    # mode: force                        # no value = error (exit 1)

  - name: poe-ports
    applies_to: {types: [switch]}
    walk:                                # …or tables (columns aligned by index)
      index: raw                         # or "port" when the index is an ifIndex
      columns:
        detection: {oid: 1.3.6.1.2.1.105.1.1.1.6, type: enum,
                    values: {1: disabled, 2: searching, 3: delivering, 4: fault}}
    limit: 10000                         # rows per column
```

**Value types:** `auto` (default: text, MAC, number or hex, guessed), `text`, `integer` (with
`scale` and `unit`), `enum` (`values`), `bits` (`values` = bit number → name), `mac`, `ip`, `hex`,
`oid`, `timeticks`, `lldp_caps`.

**Fills:** `os_name`, `os_version`, `model`, `serial`, `location`, `device_type` (one of the
device types; the type rule becomes `custom`).

### Commands

```bash
snowth_my_net custom list                          # collectors and their origin
snowth_my_net custom test fortigate-version 192.0.2.1   # run now on one device, nothing stored
snowth_my_net custom show 192.0.2.1                # values read at the last collect
snowth_my_net custom export > extensions/from-tui.yml   # collectors created in the interface
snowth_my_net custom import extensions/from-tui.yml
snowth_my_net custom delete fortigate-version      # only for collectors created in the interface
```

`check` runs the collectors that apply to each device, and `snapshot.json` contains the values
under `devices[].custom`.

## Custom reports

A report turns the state into a file of your choice: a **dataset**, the **columns** you want,
**filters**, a **sort**, and a **format** (CSV, JSON, Markdown, or a standalone HTML page that
sorts and filters in the browser). When filters are not enough, a report can be a **read-only
SQL query** over the same datasets. Reports never write to the state and never talk to devices,
so they can run at any time, even during a collect.

Two ways to create one:

1. **From the terminal interface:** *Reports* tab → `n`. Pick the data, tick the columns, add
   filters, type the sort, and watch the preview update as you go. `ctrl+s` saves it (in the
   state), `ctrl+e` writes the file now. `x` on the list exports a report, `del` deletes one
   created in the interface.
2. **In YAML:** a `reports:` list in the same `extensions/*.yml` files as collectors. Start from
   [`examples/extensions/reports.yml`](../examples/extensions/reports.yml).

```yaml
version: 1
reports:
  - name: stale-nodes                    # lowercase, digits, - and _
    title: Nodes not seen for a week     # optional, used by Markdown/HTML/JSON
    description: To clean the IPAM       # optional
    dataset: nodes                       # see "Datasets" below
    columns:                             # default: the dataset's default columns
      - mac
      - ip
      - {field: last_seen, label: Last Seen}   # rename a column
    filters:                             # all must match
      - {field: current, op: eq, value: true}
      - {field: last_seen, op: older_than, value: 7d}
    sort: [last_seen, -ip]               # "-" = descending; empty values always last
    limit: 500                           # optional
    format: csv                          # csv | json | markdown | html
    output: reports/stale-nodes.csv      # optional, relative to general.output_dir
    schedule: "0 7 * * 1"                # optional: a line in "cron print"
    push: [cmdb]                         # optional: targets of push.targets
    allow_empty: true                    # default false: an empty report is not written
```

The default file is `output/reports/<name>.<csv|json|md|html>`, written atomically. CSV files
follow `export.csv.line_terminator`; values are the ones of the standard exports (UTC times as
`2026-09-17T10:00:00Z`, device names as in `devices.csv`).

### Datasets

`snowth_my_net report fields` lists them, `snowth_my_net report fields <dataset>` lists the
fields with their type and whether they are shown by default.

| Dataset | One row per |
|---|---|
| `devices` | device within the retention window (as `devices.csv`, plus type rule and reason, sysObjectID, credential name, uptime, interface counts, last collect…) |
| `interfaces` | interface: port name, alias, status, speed, PVID, role (`access`/`uplink`, as used for `nodes.csv`) and why, MAC count, LLDP/CDP neighbours |
| `nodes` | position of a node (as `nodes.csv`), plus `current`, verdict, randomised MAC, IP count |
| `ip_history` | IP address seen for a node, with `current` and `superseded_by` |
| `vlans` | VLAN declared on a device |
| `links` | link (as `links.csv`, endpoints included, with `endpoint`) |
| `neighbors` | current LLDP/CDP neighbour as announced, resolved to a managed device or not |
| `runs` | run (collect, export…), with duration and device counts |
| `custom` | value of any custom collector (device, collector, index, column, value) |
| `custom:<collector>` | device (`get:`) or table row (`walk:`) of one collector, one column per value |

### Filters

Field types are `text`, `integer`, `time` and `bool`. Text comparisons ignore case. A comparison
never matches an empty value: use `empty` / `not_empty` for those.

| `op` | Value | Meaning |
|---|---|---|
| `eq`, `ne` | one value | equal / different (`ne` also keeps empty values) |
| `contains`, `not_contains`, `startswith`, `endswith` | text | substring tests |
| `regex` | regular expression | Python syntax, case-insensitive |
| `gt`, `ge`, `lt`, `le` | number, or date for times (`2026-09-01`, `2026-09-01T10:00:00Z`) | comparisons |
| `in`, `not_in` | list | one of / none of |
| `empty`, `not_empty` | — | no value / a value |
| `older_than`, `newer_than` | duration (`30m`, `12h`, `7d`) | time fields only, relative to now |

Booleans accept `true`/`false` (also `yes`/`no`).

### SQL reports

```yaml
  - name: vendors-per-switch
    sql: >
      SELECT device, vendor, count(*) AS nodes, iso(max(last_seen)) AS last_seen
      FROM nodes WHERE current AND device <> ''
      GROUP BY device, vendor ORDER BY device, nodes DESC
    format: json
```

* Each dataset is a table of the same name (`custom:poe-ports` becomes `custom_poe_ports`).
  Times are integers (seconds since 1970, UTC), booleans are 0/1.
* Helpers: `iso(time)` formats a time, `age_days(time)` gives its age in days, `now()` is the
  current time.
* The query runs in a private in-memory SQLite database holding copies of the datasets it names,
  never on the state file. Only one `SELECT` (or `WITH … SELECT`) is accepted; an authorizer
  refuses everything else (`ATTACH`, `PRAGMA`, writes, loading extensions), and a query is stopped
  after 20 seconds or 200 000 rows.
* `columns`, `filters` and `sort` do not apply: write them in the query.

### Commands

```bash
snowth_my_net report list                        # reports, source, format, schedule, origin
snowth_my_net report fields [DATASET]            # datasets, or the fields of one
snowth_my_net report show stale-nodes            # the definition, as YAML
snowth_my_net report preview stale-nodes         # first rows in the terminal (--limit N)
snowth_my_net report run stale-nodes [--format html] [--output FILE|-] [--no-push]
snowth_my_net report run --all                   # every report
snowth_my_net report export > extensions/from-tui.yml   # reports created in the interface
snowth_my_net report import extensions/from-tui.yml
snowth_my_net report delete stale-nodes          # only for reports created in the interface
```

Ad-hoc reports, handy in scripts (the result goes to stdout unless `--output` is given):

```bash
snowth_my_net report run --dataset interfaces --columns device,port,mac_count \
    --filter "role eq access" --filter "mac_count gt 1" --sort=-mac_count --format csv
snowth_my_net report preview --sql "SELECT vendor, count(*) FROM devices GROUP BY vendor"
```

Write `--sort=-field` with an equals sign when the first field is descending, otherwise the shell
parser takes `-field` for an option.

**Exit codes:** 0 when every report was written (and pushed), 1 when one was empty (without
`allow_empty`), invalid at run time, or failed to push, 2 for a definition error.

### Schedule and push

* `schedule:` adds `report run <name>` to `snowth_my_net cron print`, for reports of files and of
  the interface alike. Regenerate the crontab after adding or changing a schedule (with Docker
  Compose, restart the `snowth` service: the entrypoint regenerates it).
* `push:` sends the written file to push targets, with their authentication, TLS and retry rules;
  the result names the file `report:<name>`. `report run --target NAME` pushes to another target,
  `--no-push` skips it, `--dry-run` shows what would be sent.
* `check` warns about reports naming an unknown push target.

## Coming next

Python extensions (a small read-only API for collectors that need code) and hooks after collect,
export and push — see DESIGN.md §21.
