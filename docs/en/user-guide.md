# User guide

snowth_my_net maps a network without touching it. It asks your switches, routers and firewalls
what they know over SNMP — which MAC address is on which port, which neighbour is on the other end
of a cable, which IP belongs to which MAC — and turns that into an inventory, a map and files an
importer can read.

This guide is the daily-use half of the documentation: how to run it, how to make a change take
effect, what every column means, and what to do when something is missing. The
[configuration reference](config.md) and the [file formats](formats.md) stay the place to look up a
key or a column of a file.

## What it does, and what it never does

* **It never writes to a device.** Every SNMP request is a read; there is no SNMP SET anywhere in
  the code, and a test keeps it that way.
* **It never shows a secret.** The state holds the *name* of a credential, never its value; a
  community or a key lives in a file under `secrets/` and nowhere else.
* **It does not guess.** A MAC whose port is doubtful gets no position rather than a wrong one,
  an address that only repeats the MAC is not offered as an address, and every silence can be
  explained by a command: see [diagnostics](diagnostics.md).
* **It stays small.** A SQLite file, a few CSV files, a web page. Nothing else has to run.

## Where to start

| I want to | Read |
|---|---|
| install it and get a first result | [Getting started](getting-started.md) |
| run it with Docker and keep it running | [Running it](operations.md) |
| make a change to the configuration take effect | [Making a change take effect](operations.md#making-a-change-take-effect) |
| know what a column of the web interface means | [Columns](columns.md) |
| understand why a node has no port, no name or no address | [Diagnostics](diagnostics.md) |
| feed a CMDB or an importer | [Exports](exports.md) |
| look up a command | [Commands](commands.md) |
| look up a configuration key | [Configuration reference](config.md) |
| use or expose the web interface | [Web interface](web.md) |
| fix something that does not work | [Troubleshooting](troubleshooting.md) |

## A day with it

```bash
docker compose up -d                                # start everything
docker compose exec web snowth_my_net collect       # poll now instead of waiting ten minutes
docker compose exec web snowth_my_net show devices  # who answered, and who did not
docker compose exec web snowth_my_net export        # write the files
```

The scheduler does the same on its own: it collects every ten minutes and exports twice a day
(`schedule:` in the configuration). The web interface shows what the last collect found.

## Vocabulary

| Term | Meaning |
|---|---|
| device | a switch, router, firewall or access point that snowth_my_net polls over SNMP |
| node | a MAC address seen on the network — a PC, a phone, a printer — and where it was seen |
| position | the port of a polled switch where a node was learned, when that port is an access port |
| uplink | a port that leads to another switch: the MACs behind it are not placed on it |
| collect | one pass over every device: it reads their tables and updates the state |
| state | the SQLite database holding what was collected (`state.sqlite`) |
| export | the files written from the state: CSV, JSON and maps |
| seed | an address listed in `discovery.seeds`, where a collect starts |
| credential | a named SNMP community or v3 user, whose value is a file under `secrets/` |
