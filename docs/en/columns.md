# Columns

What every table of the [web interface](web.md) shows, where each value comes from, and what an
empty cell means. The same explanations sit in the **How to read this table** panel above each
table, in the language of the interface; this page adds the rules behind them. Headings are
written here as words; the interface prints them in capitals. For the columns of the exported
files, see [formats](formats.md).

## Reading any table

* **Filter**: the box above the table, and the `/` key to reach it. It searches every column,
  hidden ones included, so hiding a column never makes a row impossible to find.
* **Sort**: click a heading, click again to reverse. Filtering and sorting happen in the browser,
  on the rows already sent.
* **Columns**: the *Columns* pill chooses which ones to show; dragging the right edge of a heading
  sets its width; hovering a value that had to be cut shows all of it. The browser keeps these
  three, per page, and nothing of them reaches the server.
* **Times** are in the time zone of the machine that serves the page (`TZ`), named in the footer;
  hovering one shows the UTC value that is stored. The exported files stay in UTC.
* **Size**: the Nodes table shows at most `web.node_limit` rows (2000 by default) and says so
  when it cuts; `nodes.csv` always holds all of them.

## Devices

The inventory: one row per address that is polled, whether or not it answered.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Name | the join key of the Nodes and Links tables | the name set by hand, else `sysName` cut at the first dot, else the IP; ` (IP)` is added when two devices share a name | never empty |
| IP | the address polled | the configuration, or a neighbour that announced it | never empty |
| Vendor | who makes it | the IANA enterprise number of `sysObjectID`, else `sysDescr`, else the MAC address | nothing identified it |
| Model | the chassis | ENTITY-MIB, else a pattern on `sysDescr`, else a vendor driver | nothing identified it |
| OS | system and version | `sysDescr` or `sysObjectID`; a driver fills the version when the standard MIBs do not | not recognised |
| Type | `switch`, `router`, `firewall`, `wireless`, `server`, `printer`, `facility` or `other` | only on sure evidence: LLDP capabilities, a function MIB (printer, UPS), the `sysObjectID` catalogue, the OS, or set by hand | nothing proved it; the type never decides what is collected |
| MAC | the base MAC of the device | the bridge address, else the LLDP chassis; `+n MAC` means n more addresses are known, one per interface | none was read |
| Status | the result of the last collect of that device | `ok`, `partial` (a table failed), `failed`, or `never` for an address that has never answered | not collected yet |
| Last seen | the last time it answered | the collect | it never answered |

* An address that never answered is a row too, in red, with the reason beside the status: it is
  counted in "11/12 reachable" and this is where to find the twelfth.
* A node seen with any MAC of a polled device is not listed as a node: it is the device.

## Nodes

One row per MAC address and per place it was seen.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Manual hostname | a name you wrote, which wins over the other two | you, in the cell or with `node name`; kept with the MAC | nothing written |
| DNS hostname | the reverse lookup (PTR) of the address in the IP column | the DNS, asked at export time and cached | no zone holds that address: `dns check IP` says which resolver answered |
| NetBIOS hostname | what the host answered when asked its own name | `names.probe`, off by default; also fills with LLMNR and mDNS answers | not asked, the host is silent, or the MAC it stated is not this row's |
| Description | a line you wrote: what it is for, where it hangs, whom to call | you, in the cell or with `node describe`; kept with the MAC | nothing written |
| MAC | the address | the MAC table of a switch, or the ARP/NDP cache of a router or firewall | never empty |
| Vendor | who made the adapter | the IEEE registry, from the first half of the MAC | a randomised address, which phones and laptops now use by default |
| IP | the elected address | the ARP/NDP caches, see below | no usable address was seen |
| Switch | the device whose MAC table holds that address on an access port | the MAC tables | the MAC is only known from an ARP cache, every port that saw it is an uplink, or the switch holding it is not polled |
| Port | the port of that switch | the MAC tables | same as Switch |
| VLAN | the VLAN it was learned in | the MAC table, else the PVID of the port | same as Switch |
| Last seen | the last observation of that position | the collect | never empty |

### The three hostnames

A name can be written by hand, held by a zone, or stated by the host itself. They stay apart in
the table and are merged only where a single value is needed, in the order of trust:

1. **Manual** — someone wrote it down, so it wins.
2. **DNS** — the network says it.
3. **SNMP** — the `sysName` of a polled device, when the row is that device: its address is the
   one polled, and the MACs known for it include the row's. A device answering a credentialed
   query is better evidence than a name it volunteers.
4. **The host's own claim** — what a machine says about itself is the weakest evidence, and a
   NetBIOS answer is dropped when the adapter address it states is not the MAC of the row.

When the DNS name differs from the hand-written one or from the one the host states about itself (NetBIOS cut at 15 characters still matches the longer name it starts), a banner above the table counts the rows and
offers to show only those. Case and domain are ignored, so `poste-julie` and
`poste-julie.example.net` agree. One of the two is wrong and which one is not for the tool to
decide. `explain <mac>` lists the three and names the one it kept, and `snapshot.json` records its
source.

### The IP column

The elected address comes first, and the other addresses known for that MAC are behind a `+n`
that opens a list. The election goes in four steps:

1. addresses that no other MAC claimed later — only when the same device listed both MACs for
   that address: the VRF of an ARP entry is not collected, so two routers giving one address to
   two MACs may be two routing contexts, and nobody is said to have replaced anybody;
2. among them, those seen within `nodes.current_ip_window` (24 hours) of the most recent;
3. IPv4 first (`nodes.prefer_ipv4`);
4. then the most recent.

A link-local address (`fe80::`) is never elected (`nodes.elect_link_local`): nothing routes to it,
and the one a host builds from its own MAC says nothing the MAC column does not. An empty cell
therefore means no usable address was seen, and it says so honestly.

An address is also left out of the election when it is older than `nodes.current_ip_max_age` (7 days) next to the node's own freshest sighting. And the cell stays empty when the MAC has more than `nodes.max_ips_per_mac` addresses (a gateway answering proxy-ARP, a hypervisor), or two addresses seen at the same instant: the address cannot be told from the right one, and a wrong name attached to it would be worse than none. The addresses stay in `snapshot.json`.

### Inventory or memory

A MAC table keeps what it learned for `nodes.retention_days` (30 days), so the list is part
inventory and part memory. Two pills above the table tell them apart: *Seen at the last collect*,
and *Everything, history included*, each with its count. The reference is the last **full**
collect: testing one address alone never makes the rest of the network look gone. To empty the
memory and let the next collect fill it again, `node reset --yes`.

### One MAC on several rows

A row says `N positions` when the same MAC was seen in several places: its roaming history, most
recent first. `nodes.positions: current` keeps only the latest. A MAC seen on two access ports
within `nodes.transit_window` (30 minutes) stays on the port that carries the fewest MACs; the
other was transit.

### What the list leaves out

`show excluded` says which MACs are left out, and why:

| Reason | What it is |
|---|---|
| `multicast` | a multicast or broadcast address |
| `device_mac` | the address of a polled device |
| `ignored_mac`, `ignored_prefix` | listed in `nodes.ignore_macs` or `nodes.ignore_mac_prefixes` (VRRP and HSRP virtual MACs by default) |
| `link_local_only` | known only by a link-local address in a neighbour cache: no port, nothing to reach it by (`nodes.include_link_local_only`) |

A MAC seen only behind uplinks is kept with an empty Switch and Port (`nodes.include_unlocated`),
or placed on the port that learned it with `nodes.uplink_fallback`, marked `behind_uplink`.

### Names written in the table

The *Manual hostname* and *Description* cells are fields: type, then leave the cell or press
`Enter` to save it, `Escape` to put back what was there. The page does not reload and keeps your
filter and your place. With accounts configured you must be signed in. A name is at most 60
characters, a description 200.

## Links

One row per physical link announced by LLDP or CDP.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Local device | the polled device that heard the neighbour | the collect | never empty |
| Local port | its port | the collect | never empty |
| Remote device | the neighbour as it announced itself | LLDP or CDP; a name that is not in Devices is a neighbour that is not polled | never empty |
| Remote port | the port at the other end | LLDP or CDP | the neighbour announced none |
| Protocol | `LLDP`, `CDP`, or `LLDP+CDP` when both agree on the same link | the collect | never empty |
| Last seen | the last collect where both ends still announced each other | the collect | never empty |

* A port that hears several neighbours leads to something unmanaged: a switch or a hub that does
  not speak either protocol.
* A remote port such as `BRIDGE-VOIP/VOIP-280-VLAN` is a logical interface of the neighbour (a
  bridge, a VLAN): one cable can be announced under several names.
* Phones and stations are left out unless `export.links.include_endpoints` is on.
* An identifier that is raw bytes is shown in hexadecimal, and recognised as a MAC when it is one.

## Unreachable

What cannot be polled and what cannot be joined, in one table with three kinds of rows. Some of
these are things to fix and some are on purpose: the page does not pretend to know which, it makes
each one visible, with the rule that decided it. A polled device is never listed here.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Kind | *SNMP*, *Neighbour* or *Name probe* | the page | never empty |
| Address | the address concerned | the address polled; the first management address a neighbour announced; the IP of a node | a neighbour that announces none |
| Name | the device, the neighbour as it announced itself, or the best hostname known for a node | the last collect | nothing is known |
| MAC | the chassis address of a neighbour, the MAC of a node | LLDP, CDP, the MAC tables | not announced |
| Tried | what was attempted | SNMP with the credential chosen, or every one; the protocols asked of a node | a neighbour was never attempted, a node never asked |
| Why not | the reason, in the words of the rule | the collect, the configuration | never empty |
| Last attempt | when it was last tried | the collect, the last question | never tried |

Pills above the table isolate each kind and count it. The reasons, and what each one asks of you:

| Kind | Reason | What it asks of you |
|---|---|---|
| SNMP | the error of the last attempt, such as `no answer (v3: timeout)`, or `never answered` | the community, the ACL of the device (the address of the host, since a container is NATed), the address itself; `check` tests it |
| Neighbour | `discovery.follow_neighbors is off` | nothing, unless you want neighbours explored |
| Neighbour | `it announces no management address` | nothing: there is nothing to poll, as for most phones |
| Neighbour | `capabilities …: a phone, a station or an endpoint is never polled` | nothing: by design, see `discovery.follow_capabilities` |
| Neighbour | `outside discovery.allowed` or `excluded` | add its network to `discovery.allowed` (or `all`), or leave it out on purpose |
| Neighbour | `disabled by the configuration` | `devices[].disabled` says so |
| Neighbour | `nothing stops it: the next collect will try it` | wait for the next collect |
| Name probe | `outside names.networks, so never asked` | widen `names.networks` where the firewall allows UDP/137 |
| Name probe | `no answer` | the host speaks none of the protocols asked, or a firewall drops the question |
| Name probe | `answered, but states the MAC …` | nothing: another device answered for that address, and its name was dropped |
| Name probe | `not asked yet: run 'names ask'` | `names ask`, or the *Ask names* button |

The Name probe rows exist only when `names.probe` lists a protocol, and only for nodes seen at the
last collect.

## Runs

The last 50 runs.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Run | the run number | the state | never empty |
| Command | `collect`, `discover`, `run`… | the state | never empty |
| Started | when it began | the state | never empty |
| Duration | how long it took | the state | an ellipsis while it is still running |
| Result | `ok`, `partial` (a device or a table failed) or `failed` | the run | it reads `running` until the run ends |
| Devices | the devices that answered out of those polled | the run | dashes: that run did not poll devices |

A device marked `devices[].tolerate_failure` never turns a run `partial`. The buttons above the
table start `collect`, `discover`, `export`, with push targets `push`, and with `names.probe`
*Ask names* (`names ask`, ignoring the cache): one at a time, as the same commands a shell would
run.

## Files

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| File | an exported file | the output directory | never empty |
| Bytes | the size of the file | the file | never empty |
| Written | when the last export wrote it | the file | never empty |

Click a name to download it. Only the known export names are served; no path from a request ever
reaches the file system.

## SNMP

This tab exists only when an account is configured, and it asks for that password again before it
opens. A community is never shown: the state holds the name of a credential, never its value.

| Column | What it holds | Where it comes from | Empty means |
|---|---|---|---|
| Address | an address that is polled | the state | never empty |
| Name | the device found there | the last collect | it never answered |
| Origin | how it came to be polled: `seed`, `manual`, `neighbor`, `sweep` or `state` | the state | never empty |
| Credential | the credential chosen for it | a setting made by hand | none chosen: whichever answers is used |
| Status | the result of the last attempt, and the reason when it failed | the last collect | never tried |
| Failures | consecutive failed attempts | the state | zero |

From this tab you can add an address, remove one, choose a credential by name, test one address
(a collect for that address alone), and forget the MAC and ARP memory. It cannot create a
credential.
