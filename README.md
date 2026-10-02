# snowth_my_net

*[Français](README.fr.md)*

A lightweight, **read-only** SNMP network mapper. snowth_my_net polls your switches, routers,
firewalls and access points, merges their MAC and ARP tables, follows LLDP/CDP, and answers three
questions:

* **Which devices exist?** Model, serial number, OS and version, management IP, type.
* **Who is plugged where?** MAC, IP, DNS name, switch, port, VLAN, last seen, roaming history.
* **How are the devices connected?** Links from LLDP and CDP, as CSV and as maps.

Everything is exported as fixed-format CSV, JSON and maps, and can be pushed over HTTP on a
schedule to any tool. A terminal interface lets you browse, set things by hand and test OIDs.

## Why another tool

* **Strictly read-only.** Only SNMP GET, GETNEXT and GETBULK exist in the code; a test proves it
  on the wire.
* **It never trusts what a device announces.** A firewall that does not advertise layer 3 still
  gets its ARP table read: every standard MIB is attempted on every device, and you can force or
  disable each function per device. The device **type is only a label**, never a gate.
* **Positions you can trust.** A MAC is placed on an access port, never on an uplink (LLDP/CDP
  neighbour, declared port, too many MACs, optional LAG), IP phones and access points are handled,
  simultaneous sightings are resolved, and `explain` tells you why a MAC is where it is.
* **Light.** One process per run, a SQLite file, four runtime dependencies (plus Textual for the
  interface), no web server, no database server.

## Quick start

Step by step, from an empty directory to the first scan:
[docs/en/getting-started.md](docs/en/getting-started.md).

### With pipx (host cron or systemd)

```bash
pipx install git+ssh://git@github.com/ShonenNoSeishin/snowth_my_net.git
snowth_my_net init --output snowth_my_net.yml     # commented example, then edit it
mkdir -p secrets && printf '%s' 'the-v3-auth-key' > secrets/snmp_v3_auth && chmod 600 secrets/*
snowth_my_net check                               # the first diagnostic to run
snowth_my_net collect
snowth_my_net export                              # ./output or general.output_dir
snowth_my_net                                     # terminal interface
snowth_my_net cron print                          # crontab lines from schedule:
```

### With Docker Compose

```bash
cp .env.example .env && mkdir -p config/extensions data output secrets
docker compose build
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/config:/work" snowth_my_net:latest \
  init --output /work/snowth_my_net.yml
# put the secrets in ./secrets (chmod 600), edit config/snowth_my_net.yml
docker compose run --rm snowth check
docker compose up -d
docker compose logs -f snowth
```

Details, systemd units, hardening and networking: [docs/en/deployment.md](docs/en/deployment.md).

## Terminal interface

`snowth_my_net` (or `snowth_my_net tui`, `docker compose run --rm snowth tui`):

* **Devices**: filterable list, type set by hand marked ✎. A device sheet shows its identity and
  **why it has this type**. The *Settings* tab uses guided lists for the type, the functions
  (`auto` / `force` / `off`) and SNMP tuning, and the source of every value is shown. The sheet
  also has an *OID tester* (presets suggested for the type, or any OID), *Neighbors*, *Custom*
  values and *Last collect*.
* **Nodes**: search a MAC, IP, DNS name, port… Enter explains the position, in the interface's
  language.
* **Reports**: build a report with a live preview (dataset, columns, filters, sort, format),
  save it, export it.
* **Links**, **Extensions** (custom collectors), **Runs**.
* Collect a device or everything with a live log. Nothing ever shows a secret.

## Commands

| Command | Purpose |
|---|---|
| `init` | Write a commented example configuration |
| `check [ADDR…] [--quick]` | Per device: reachable, credential, MIBs answering, identity and type, warnings |
| `discover [--dry-run]` | Identify seeds and explore LLDP/CDP neighbours without collecting tables |
| `collect [--device ADDR]` | Poll devices and update the state |
| `export [--only …]` | Write `devices.csv`, `nodes.csv`, `links.csv`, `snapshot.json`, maps |
| `push [--target] [--file] [--wait] [--dry-run]` | Send the exported files |
| `run [--no-collect] [--no-push] [--wait]` | Collect, export and push in one go |
| `show devices\|nodes\|links\|runs [--filter]` | Browse the state |
| `explain <mac\|ip>` | Why a MAC is on a port (sightings, discarded uplinks, transit, ARP) |
| `probe ADDR [PRESET\|OID…]` | Test OIDs by hand (presets suggested for the device type) |
| `device show\|set\|unset\|add\|remove\|export-settings\|import-settings` | Manual settings |
| `custom list\|show\|test\|export\|import\|delete` | Custom collectors (extra OIDs) |
| `report list\|fields\|show\|preview\|run\|export\|import\|delete` | Custom reports (CSV, JSON, Markdown, HTML; read-only SQL) |
| `hooks list\|test` | External programs run after collect, export, push, report |
| `oui-update [--from-file DIR]` | Refresh the IEEE vendor database |
| `cron print [--format crontab\|cron.d\|supercronic]` | Scheduler lines from `schedule:` |
| `health [--max-age]` | Exit 1 when the last successful collect is too old |
| `tui` | Terminal interface |
| `show uplinks` | Ports treated as uplinks, whether by proof (LLDP/CDP) or by the MAC count alone, and how many MACs each one leaves without a position |
| `node reset --yes` | Forget every MAC and ARP observation; the devices, links and names stay |
| `node [name\|describe MAC [TEXT]]` | Name or describe a MAC address by hand, or list what was given (kept across collects) |
| `web [--bind] [--port]`, `web passwd [USER]` | Read-only web interface (devices, nodes, links, runs, files), with optional accounts |

Every command accepts `--json` (scripts), `--config`, `--log-level`, `--log-file`, `-q`. Logs go
to stderr. Exit codes: **0** OK, **1** partial failure, **2** configuration error, **3** state
locked by another run.

## Outputs

| File | Content |
|---|---|
| `devices.csv` | One device per line; `Device Name` is the join key |
| `nodes.csv` | One line per (MAC, position), most recent first; `Switch` = a `Device Name` |
| `links.csv` | One line per physical link (`LLDP`, `CDP`, `LLDP+CDP`) |
| `snapshot.json` | Everything, versioned schema, for scripts |
| `map.dot`, `map.mmd`, `map.html` | Graphviz, Mermaid, and an offline interactive page |

Column by column: [docs/en/formats.md](docs/en/formats.md). Every time is UTC; empty CSV files are never
written over previous ones nor pushed.

## Extending it

Read more OIDs without writing code: create a custom collector from the OID tester, or in
`extensions/*.yml`. Values can fill standard fields such as the OS version.

Build your own reports: pick a dataset (devices, interfaces, nodes, IP history, VLANs, links,
neighbours, runs, custom values), columns, filters and sort, or write a read-only SQL query; get
CSV, JSON, Markdown or a standalone HTML page, on demand, on a schedule, or pushed to a target.

Vendor drivers fill what standard MIBs cannot say (Fortinet, Sophos and MikroTik identity,
MikroTik Wi-Fi stations, access points and clients of Cisco AireOS controllers), without ever
replacing the standard collection.

For the rest, Python extensions add collectors, report datasets, exporters and drivers through a small
read-only API (with a test harness), and hooks run your own programs after a collect, an export,
a push or a report.
See [docs/en/extensions.md](docs/en/extensions.md) and [examples/extensions](examples/extensions/).

## Documentation

Detailed documentation exists in English (`docs/en/`) and French (`docs/fr/`):

* [Getting started](docs/en/getting-started.md): declare your devices and run a scan, step by step
* [Configuration reference](docs/en/config.md), with every key and its default
* [Output formats and HTTP push](docs/en/formats.md)
* [Deployment: pipx + cron/systemd, Docker Compose](docs/en/deployment.md)
* [Troubleshooting and vendor notes](docs/en/troubleshooting.md)
* [Web interface](docs/en/web.md)
* [Vendor drivers](docs/en/drivers.md)
* [Extensions](docs/en/extensions.md)
* [Design notes](DESIGN.md) (in French)

## Security

* Read-only by construction: no SNMP SET code path and no shell. The only process ever started
  is a hook you configure (argument list, timeout, clean environment); Python extensions run
  only when listed by name.
* Secrets only from files or environment variables. The YAML refuses them, logs mask them, and
  the state stores credential names only.
* SNMPv3 authPriv recommended (`check` warns about v2c); TLS verified by default for pushes, no
  redirects followed.
* Timeouts everywhere; the container runs non-root on a read-only file system with no capability.

## Development

```bash
uv venv --python 3.13 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest          # unit + integration (SNMP simulators on 127.0.0.x)
.venv/bin/python -m pytest --cov=snowth_my_net   # with coverage (fails under 99%)
.venv/bin/ruff check src tests
docker compose --profile test run --rm tests
python -m tests.support.lab         # a local lab of simulated devices, prints a configuration
```

The test suite covers every module (100% of lines, 99% of branches): unit tests with fakes for
SNMP, HTTP, DNS and processes, Textual pilot tests for the interface, integration tests against
SNMP simulators, golden files for the CSV outputs, and checks that the French and English
documentation stay in step (same pages, same structure, every configuration key, no broken
link).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Provided "as is", without warranty
and without liability.
