# Exports

The files are what other tools read: an importer, a script, a person with a map. This page says
which file is for what, when each is written, which settings shape them, and how to feed an
importer without importing the past. The column-by-column reference is in
[formats](formats.md), every key in the [configuration reference](config.md).

## The files

| File | What it holds | Who reads it |
|---|---|---|
| `devices.csv` | one row per polled device | an importer, as assets |
| `nodes.csv` | one row per MAC address and position | an importer, as hosts and where they are |
| `links.csv` | one row per physical link | a mapping tool |
| `ports.csv` | one row per port, with its neighbour (off by default: list `ports` in `export.files`) | an importer that models ports |
| `snapshot.json` | everything, with a versioned schema and the reasons behind each value | scripts |
| `map.html`, `map.dot`, `map.mmd` | an interactive page that works offline, Graphviz, Mermaid | people |

The default headers of `devices.csv` and `nodes.csv` are the ones the `netdisco` profile of
Inventory Manager reads, and they do not change when you upgrade. Every time in a file is UTC.

## When they are written

* **On a schedule**: `schedule.export_push` (11:00 and 18:00 by default) runs `run --no-collect`,
  and pushes too when push targets are configured.
* **By hand**: `export`, or `export --only devices,nodes` for a subset; the *Export* button of the
  Runs page; or `run`, which collects, exports and pushes in one go.
* **Which files**: `export.files`, all of them by default.
* **Never half a file**: a file is written beside its destination and renamed into place, so a
  reader never sees a partial one.
* **Never an empty one by accident**: a CSV with no data row is neither written over the previous
  file nor pushed, unless it is listed in `export.allow_empty`.
* **DNS is asked now**: names are resolved at export time and cached, within `dns.budget` and
  `names.budget`. The first export after turning either on may leave addresses for the next one.
* **Asking the hosts can be separate**: `names ask`, scheduled with `schedule.names` or started
  from the *Ask names* button, asks every node its own name on its own. With
  `names.at_export: false` an export then only reads what was already answered, and stays fast.

## What shapes nodes.csv

| Key | Effect | Default |
|---|---|---|
| `nodes.positions` | `current` writes one row per MAC with its latest position; `all` writes one row per position, the roaming history | `all` |
| `nodes.retention_days` | observations older than this are forgotten | `30` |
| `nodes.uplink_fallback` | a MAC seen only behind weakly held uplinks gets the port that learned it, marked `behind_uplink` | `false` |
| `nodes.include_unlocated` | keep the rows that have no switch and port | `true` |
| `nodes.include_link_local_only` | keep MACs known only by a link-local address | `false` |
| `nodes.elect_link_local` | allow a link-local address as the IP of a row | `false` |
| `nodes.current_ip_window` | how far from the most recent address another one may be and still be elected | `86400` |
| `export.nodes.merge_hostnames` | `DNS Name` carries the best of the three hostnames | `true` |
| `export.nodes.include_name`, `export.nodes.include_description` | add a first column with the name, the description | `false` |
| `dns.strip_domain` | keep only the host part of a DNS name | `false` |
| `export.csv.line_terminator` | `crlf` (RFC 4180) or `lf` | `crlf` |

The two `include_` keys add columns *in front of* the others. An importer that reads columns by
their header is unaffected; one that reads them by position is not, which is why they are off.

## Hostnames in the export

`DNS Name` carries one value, chosen in the order of trust: the name written by hand, else the
reverse lookup, else what the host stated about itself (`names.probe`). The CSV has no room to say
which of the three it was without breaking the header an importer expects, so `snapshot.json`
records it for every node:

```json
"hostname": { "name": "poste-de-frank", "source": "manual" }
```

With `export.nodes.merge_hostnames: false`, `DNS Name` is the reverse lookup alone.

## Feeding an importer

An importer deduplicates what it receives. If it receives thirty days of positions for one MAC, it
may keep any of them, including a port that is three weeks old. These settings send the present
and lose nothing an unmanaged switch hides:

```yaml
nodes:
  positions: current          # one row per MAC: its latest position, not its history
  uplink_fallback: true       # devices behind an unmanaged switch keep the port that learned them
export:
  nodes:
    merge_hostnames: true     # the best hostname known goes in DNS Name
```

Before turning `uplink_fallback` on, ask what it would change:

```bash
docker compose exec web snowth_my_net show uplinks
```

The last line counts the MACs that would get a position. A MAC behind a switch that *is* polled
never gets one this way: its real port comes from that switch.

## Pushing

Sending the files to an HTTP endpoint, with its authentication and its job polling, is described
in [HTTP push](formats.md#http-push). From the command line:

```bash
docker compose exec web snowth_my_net push --dry-run              # what would be sent, nowhere sent
docker compose exec web snowth_my_net push --target my-cmdb       # one target
docker compose exec web snowth_my_net run --wait                  # collect, export, push, wait for the jobs
```

## Checking an export

```bash
ls -l output/                                                         # what was written, and when
tail -n +2 output/nodes.csv | cut -d, -f1 | tr -d '"' | sort -u | wc -l   # distinct MACs
docker compose exec web snowth_my_net show nodes --filter 192.0.2       # the same, from the state
```

The count of distinct MACs should be close to what the *Seen at the last collect* pill shows. If
it is far above it, the file still holds memory: `nodes.positions: current` does not shorten that
memory, `node reset --yes` followed by a collect does. See [diagnostics](diagnostics.md) when a
node is missing from the file.
