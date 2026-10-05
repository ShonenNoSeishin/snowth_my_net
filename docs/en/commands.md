# Commands

Every command of `snowth_my_net`, what it does and its options. The options come from the
program's own help, and a test fails when a command is missing from this page. The keys they read
are in the [configuration reference](config.md); what to type when something is missing is in
[diagnostics](diagnostics.md).

## Running a command

With Docker Compose, type it in the `web` or the `snowth` container, which share their files:

```bash
docker compose exec web snowth_my_net <command>        # a command that prints
docker compose exec -T web snowth_my_net <command>     # inside a pipe or a script: no terminal
docker compose exec -it web snowth_my_net tui          # the terminal interface needs one
```

Without Docker, it is the same command without the prefix. These options belong to every command
and go before its name:

| Option | Effect |
|---|---|
| `-c`, `--config` | the configuration file; default `$SNOWTH_CONFIG`, `./snowth_my_net.yml`, then `/etc/snowth_my_net/config.yml` |
| `--state-dir`, `--output-dir` | override `general.state_dir` and `general.output_dir` |
| `--json` | print machine-readable output on stdout |
| `--log-level` | `debug`, `info`, `warning` or `error` |
| `--log-file` | also write the log to this file |
| `-q`, `--quiet` | only warnings and errors on stderr |

The exit code is 0 when all went well, 1 when something partly failed, 2 for a configuration
problem, 3 when the state is locked by another writer, and 130 when interrupted. A command that
writes waits for the state lock, up to `general.lock_wait`.

## Setting up

| Command | What it does | Options |
|---|---|---|
| `init` | write a commented example configuration | `--output`, `--force` |
| `check` | diagnose the configuration, the credentials and the MIB support of each device; it polls them | `--quick` (one request per MIB), `--save` (remember the credentials that work), addresses |
| `version` | print the version | |

## Collecting and exporting

| Command | What it does | Options |
|---|---|---|
| `discover` | identify devices, from the seeds and the sweep, without collecting their tables | `--device`, `--dry-run` |
| `collect` | poll every device and update the state | `--device` (one address), `--no-hooks` |
| `export` | write the CSV, JSON and map files | `--only devices,nodes,links,snapshot,map`, `--no-hooks` |
| `push` | send the exported files to the push targets | `--target`, `--file`, `--wait`, `--dry-run`, `--no-hooks` |
| `run` | collect, export and push in one go | `--no-collect`, `--no-push`, `--wait`, `--no-hooks` |
| `names ask` | ask every node its own name over `names.probe`, answers cached | `--force` (ask again whatever the cache says) |
| `cron print` | print the crontab lines generated from `schedule:` | `--format` (`crontab`, `cron.d`, `supercronic`) |
| `health` | fail when the last successful collect is too old | `--max-age` (for example `30m`) |

## Looking at what it knows

| Command | What it does | Options |
|---|---|---|
| `show devices` | the inventory, with its type and the rule that decided it | |
| `show nodes` | the MAC addresses and where they are | `--limit`, `--filter` |
| `show links` | the physical links found by LLDP and CDP | `--filter` |
| `show runs` | the last runs and their status | `--limit` |
| `show uplinks` | the ports held as uplinks, by proof or by guess, and the MACs each one leaves without a position | `--filter` |
| `show excluded` | the MACs the node list leaves out, and why | `--filter` |
| `show tables` | what every SNMP table returned on every device at the last collect | `--filter` |
| `explain` | why a MAC, or the MACs of an IP, are where they are: every sighting, the ports discarded, the three hostnames | a MAC or an IP |
| `tui` | open the terminal management interface | |

## Diagnosing

| Command | What it does | Options |
|---|---|---|
| `probe` | test OIDs by hand on one device: presets, or numeric OIDs | `--get`, `--walk`, `--limit`, `--all` |
| `dns check` | ask the configured resolvers for a reverse lookup and say which one answered | addresses |
| `dns probe` | ask a host its own name, over NetBIOS, LLMNR and mDNS, and show each answer | addresses |

## Changing what it knows

| Command | What it does | Options |
|---|---|---|
| `node name` | give a MAC a name, kept across collects; no text forgets it | a MAC, then the text |
| `node describe` | give a MAC a description | a MAC, then the text |
| `node reset` | forget every MAC and ARP observation; devices, links and names stay | `--yes` is required |
| `dns flush` | forget the cached name lookups | `--misses-only` keeps the names already found |
| `device` | add or remove a polled address; `set`, `unset` and `show` its settings; `export-settings` and `import-settings` carry them elsewhere | |
| `custom` | custom collectors: `list`, `show`, `test`, `import`, `export`, `delete` | |
| `report` | custom reports: `list`, `fields`, `show`, `preview`, `run`, `export`, `import`, `delete` | |
| `hooks` | programs run after a collect, an export, a push or a report: `list`, `test` | |

## Serving and maintaining

| Command | What it does | Options |
|---|---|---|
| `web` | serve the web interface | `--bind`, `--port`, `--trusted-proxy`, `--hash-password` (print the hash of a password, for an account whose password lives in a file) |
| `web passwd` | set the password of a web account in place | the account, if there are several |
| `oui-update` | refresh the vendor database from the IEEE | `--from-file` (CSV files fetched beforehand) |
