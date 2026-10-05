# Diagnostics

An inventory that must carry no false positive has to prefer silence to a guess. A node with no
port, a column left empty, a device missing: each is the tool declining to assert something it
could not prove. The point of this page is that **every silence has an explanation, and a command
that gives it**. Find the symptom, run the command, read what it says.

## What explains what

| It explains | Where |
|---|---|
| what could not be polled or joined, and why | the *Unreachable* tab of the web interface |
| what every SNMP table returned on every device | `show tables` |
| which ports are held as uplinks, by proof or by guess, and what each costs | `show uplinks` |
| which MACs the list leaves out, and why | `show excluded` |
| everything about one MAC: its sightings, the ports discarded, its addresses, its three hostnames | `explain` |
| which resolver answers, and whether a zone holds an address | `dns check` |
| whether a host states its own name | `dns probe` |

## Where to look first

| Symptom | First step | What it tells you |
|---|---|---|
| a device is missing from the inventory | the *Unreachable* tab, kind *SNMP* | the error of the last attempt; then `check` with its address |
| "11/12 reachable" and you want the twelfth | the Devices tab, rows in red | which address, and the reason beside it |
| a node has no port | `explain <mac>` | every sighting, and the reason each port was discarded |
| a node appears twice, on a port and on a trunk | `explain <mac>` then `show uplinks` | a trunk taken for an access port, or a move |
| a MAC is not in the list at all | `show excluded` | the rule that left it out |
| a node has no IP | `explain <mac>` | its ARP sightings; a link-local address is never elected |
| a node has no hostname | `dns check <ip>` | the resolver that answered, and `nxdomain` when no zone holds the address |
| the nodes of one VLAN are missing | the `note:` lines of a `collect`, then `show tables` | a VLAN whose MAC table was not read |
| a MAC table came back empty or short | `show tables` | its status, its rows and its time |
| too many rows, old ones among them | the *Seen at the last collect* pill | what is memory and what is inventory |
| the interface answers 503 | `collect` | the state is older than the tool and needs its first write |

## A node has no port, or the wrong one

```bash
docker compose exec web snowth_my_net explain 80:5e:c0:3b:1f:4f
docker compose exec web snowth_my_net show uplinks
```

`explain` lists every place the MAC was seen in a MAC table, marks the one it kept with a tick,
and gives the reason for each port it set aside. The reasons, as printed:

| Reason | What it means | What to do |
|---|---|---|
| `neighbor …` with a polled switch | LLDP or CDP shows a polled switch on that port: proof | nothing: the MAC is behind it, and its real port is on that switch |
| `neighbor …` with a bridge or a router | an LLDP or CDP neighbour that is not polled sits on that port: a guess | poll that device, or accept `nodes.uplink_fallback` |
| `61 MACs > 50` | the port carries more than `nodes.uplink_mac_threshold`: a guess | raise it for that device, or list the port in `devices[].access_ports` |
| `declared in uplinks` | you said so | `devices[].uplinks` |
| `declared in access_ports` | you said the opposite | `devices[].access_ports` |
| `link aggregation` | `nodes.lag_is_uplink` is on | |

A trunk inherits the neighbours of its member ports, so a switch-to-switch trunk is recognised
even when it carries few MACs; the reason then reads *a member of this trunk*.

`show uplinks` ends with a count: how many MACs would get a position with `nodes.uplink_fallback`,
which gives them the port that learned them, marked `behind_uplink`. A device behind a switch that
**is** polled never gets one this way, because its real port comes from that switch.

## A device does not answer

The *Unreachable* tab says what was tried and what came back. Then:

```bash
docker compose exec web snowth_my_net check 192.0.2.12
docker compose exec web snowth_my_net probe 192.0.2.12 system
```

| Check | Why |
|---|---|
| the community, or the v3 user and keys | a wrong one looks exactly like a timeout |
| the SNMP ACL of the device | it must allow the address of the **host**: a container leaves through it |
| the port, `general.snmp.port` | or `address:port` in the configuration |
| the version of the credential | a v2c community against a v3-only agent is silence |
| `general.snmp.timeout` and `retries` | a slow agent can be answered too late |

An address that answers for some tables and not others is `partial` in the Devices tab, and
`show tables` says which table failed and how.

## A node has no hostname

```bash
docker compose exec web snowth_my_net dns check 192.0.2.121
```

| Answer | What it means |
|---|---|
| `ok` | a name was found, and `ANSWERED BY` says by which resolver |
| `nxdomain` | the resolver answered "no such name": no reverse zone for that subnet, or nothing registered a PTR for that address |
| `timeout` | no resolver answered at all: port 53 closed, in UDP or in TCP, from the host's address, or slower than `dns.timeout` |
| `error` | the resolver refused: check that it serves this client |

A name found once is kept for `dns.cache_ttl`, a "no name" for `dns.negative_ttl`. After fixing a
resolver, `dns flush --misses-only` forgets the refusals so the fix shows at the next export.

When no zone will ever hold the address, a host can be asked its own name:

```bash
docker compose exec web snowth_my_net dns probe 192.0.2.120
```

It tries NetBIOS, LLMNR and mDNS, as `nbtstat -A` and a scanner do. Turn it on for good with
`names.probe`, and see *Name probe* rows in the *Unreachable* tab for the hosts that stay silent.
A name a host states about itself is weaker evidence than one a zone holds, which is why it comes
last when the three are merged.

## Reading the notes of a collect

A collect prints a `note:` line for every decision it made that you may want to know about:

| Note | What it means |
|---|---|
| `neighbor X (a.b.c.d): skipped (capabilities station,telephone)` | a phone or a station is never polled, by design |
| `neighbor X (a.b.c.d): skipped (outside discovery.allowed)` | the address is not in an allowed range: add it, or write `all` |
| `neighbor X (a.b.c.d): skipped (max_depth 3)` | the neighbour is further than `discovery.max_depth` hops |
| `neighbor X (a.b.c.d): skipped (disabled)` | `devices[].disabled` says so |
| `a.b.c.d: VLAN 81, 90: ports live there but the MAC table returned nothing for them` | the bridge instance of those VLANs was not read: `devices[].vlan_indexing: cisco` reads each one |

Nothing is inferred from the VLAN note: no position is invented. It names the gap and the setting
that closes it.

## When the numbers differ from another tool

Two tools rarely count the same thing. A MAC-table-only tool counts what a switch learned; this one
also counts what an ARP cache knows, and leaves out what it cannot place. Compare the same thing:

```bash
tail -n +2 output/nodes.csv | cut -d, -f1 | tr -d '"' | sort -u > /tmp/snowth.macs
# the other tool's active MACs, one per line, lowercase with colons, in /tmp/other.macs
comm -23 /tmp/other.macs /tmp/snowth.macs      # seen by the other tool only
comm -13 /tmp/other.macs /tmp/snowth.macs      # seen here only
```

Run `explain` on a few MACs of the first list: each one has a reason. The usual ones are a MAC
held behind an uplink, a VLAN whose table was not read, a port the other tool reports from an old
reading, and a MAC the other tool lists as active because its last reading is not recent. Compare
with the *Seen at the last collect* count, not with the total.

## The web interface

| Symptom | Cause | What to do |
|---|---|---|
| 503 right after an update | the state is older than the tool | run `collect`; the first write upgrades it |
| the browser warns about the certificate | it is self-signed | accept it once, or replace it, see [web](web.md) |
| a login is refused | the log says `no such account` or `wrong password` | `web passwd` resets it, without a restart |
| the *SNMP* tab is missing | it needs an account, and `web.actions` on | declare an account under `web.auth.users` |
| a button fails | the line under the buttons says how the command ended, with its last message | type the same command in a shell to see all of it |
