# Getting started: declare your devices and run a scan

Follow the steps in order. Each one ends with a command that tells you whether you can move on.
Nothing here ever writes to a device: snowth_my_net only sends SNMP reads.

## 1. Install

```bash
pipx install git+https://github.com/ShonenNoSeishin/snowth_my_net.git
snowth_my_net version
```

With Docker Compose instead, see [deployment](deployment.md#2-docker-compose); every command
below becomes `docker compose run --rm snowth <command>`.

## 2. Create the configuration

```bash
snowth_my_net init -o snowth_my_net.yml
```

The file is commented and every key is listed in the [configuration reference](config.md).
Point the tool at it with `--config snowth_my_net.yml`, or set `SNOWTH_CONFIG` once:

```bash
export SNOWTH_CONFIG=$PWD/snowth_my_net.yml
```

## 3. Put the SNMP secrets in files

Secrets never go in the YAML: the tool refuses them there. Write one file per secret, readable
only by you (`check` warns when a file is readable by the group or by everyone).

```bash
mkdir -p secrets && chmod 700 secrets
printf '%s' 'the-authentication-key' > secrets/v3_auth
printf '%s' 'the-privacy-key'        > secrets/v3_priv
printf '%s' 'the-read-community'     > secrets/community
chmod 600 secrets/*
```

An environment variable works too (`community_env: SNMP_COMMUNITY`), which is what the Docker
deployment uses.

## 4. Declare the credentials

In `snowth_my_net.yml`, list the credentials the tool may try. `scope` limits a credential to a
range of addresses, so a wrong community is never tried on a device that does not expect it
(with SNMPv2c a wrong community is silence, which costs a timeout).

```yaml
general:
  state_dir: ./data
  output_dir: ./output
  secrets_dir: ./secrets           # base of the relative paths below

credentials:
  - name: v3-main                  # SNMPv3 authPriv: recommended
    version: 3
    username: snowth
    auth_protocol: sha256
    auth_key_file: v3_auth
    priv_protocol: aes128
    priv_key_file: v3_priv
  - name: v2c-old-switches         # only where v3 is not available
    version: 2c
    community_file: community
    scope: [192.0.2.0/24]
```

The device side must allow read-only access for that user or community, from the address of the
machine running snowth_my_net.

## 5. Declare the devices

There are three ways, and they add up.

**a. Seeds and exploration** — the usual way. Give a few well-connected devices (core switches,
firewalls); their LLDP/CDP neighbours are followed inside `allowed`.

```yaml
discovery:
  seeds: [192.0.2.1, 192.0.2.11, sw-core-01.example.net]
  allowed: [192.0.2.0/24, 198.51.100.0/24]   # nothing outside is ever polled
  exclude: [192.0.2.99]                      # never poll this one
  follow_neighbors: true
  max_depth: 3
```

**b. One device at a time** — added to the state, kept across runs:

```bash
snowth_my_net device add 192.0.2.42
snowth_my_net device remove 192.0.2.42       # forget it and its history
```

In the terminal interface (`snowth_my_net tui`), the same thing is the `a` key on the Devices
tab, and `del` removes.

**c. Per-device settings** — only when a device needs something different. Nothing here is
required for a scan to work:

```yaml
devices:
  - address: 192.0.2.1
    type: firewall                 # only if the automatic type is wrong or empty
    features: {arp: force}         # auto | force | off, per function
    snmp: {pace_ms: 50}            # spare a small CPU
    tolerate_failure: true         # its failure must not fail the whole run
  - address: 192.0.2.0/24          # a range: the most specific entry wins
    uplinks: [Te1/1/1]
```

## 6. Check before scanning

`check` polls each target once and prints, per device: whether it answers, which credential
worked, which MIBs have rows, the identity and the type, plus warnings.

```bash
snowth_my_net check                       # every target
snowth_my_net check 192.0.2.1 --quick     # one device, one request per MIB
```

Read the `mibs` line: `ok(1834)` means the MIB answered with that many rows, `absent` means the
device serves nothing there, `timeout` means it did not answer in time. A device that answers
`system` but nothing else is usually a credential with a restricted view.

To try an OID by hand, with suggestions for the device type:

```bash
snowth_my_net probe 192.0.2.1                  # list the presets
snowth_my_net probe 192.0.2.1 arp-media        # a preset
snowth_my_net probe 192.0.2.1 1.3.6.1.2.1.1.5.0
```

## 7. Run the scan

```bash
snowth_my_net discover        # identity only: who answers, what it is, who its neighbours are
snowth_my_net collect         # the real scan: interfaces, MAC tables, ARP, LLDP/CDP
```

`discover` is the dry run of the exploration and writes little; `collect` is what you schedule.
Both print one line per device and a summary. The exit code is **0** when everything went well,
**1** when a device or a function failed, **2** for a configuration error, **3** when another
run holds the state lock.

Scan one device only (handy after changing its settings):

```bash
snowth_my_net collect --device 192.0.2.11
```

## 8. Look at what was collected

```bash
snowth_my_net show devices                 # inventory, type and how it was decided
snowth_my_net show nodes --filter 192.0.2  # MAC addresses and where they are
snowth_my_net show uplinks                 # ports held as uplinks, and what each one costs
snowth_my_net show excluded                # MACs the node list leaves out, and why
snowth_my_net show tables                  # what every SNMP table returned on every device
snowth_my_net dns check 192.0.2.121       # is the resolver right, and is there a reverse zone?
snowth_my_net dns probe 192.0.2.121       # ask the host itself: NetBIOS, LLMNR, mDNS
snowth_my_net show links                   # the physical links found
snowth_my_net show runs                    # the last runs and their status
snowth_my_net explain 00:00:5e:00:53:a0    # why this MAC is on this port
```

`explain` also takes an IP address. It shows every sighting, the ports discarded as uplinks or
transit, and the ARP entries behind the current IP.

## 9. Produce the files

```bash
snowth_my_net export
```

It writes `devices.csv`, `nodes.csv`, `links.csv`, `snapshot.json` and the maps into the output
directory (see [formats](formats.md)). An empty CSV is never written over a previous one.
Open `map.html` in a browser: it works offline.

## 10. Repeat it automatically

Set the schedule in the configuration, then generate the scheduler lines:

```yaml
schedule:
  collect: "*/10 * * * *"        # ARP entries expire within minutes
  export_push: "0 11,18 * * *"
```

```bash
snowth_my_net cron print --format cron.d --user snowth | sudo tee /etc/cron.d/snowth_my_net
snowth_my_net health             # exits 1 when the last successful collect is too old
```

With Docker Compose the container's scheduler reads the same `schedule:` at start-up. Details
and systemd units: [deployment](deployment.md).

## 11. Work day to day in the interface

```bash
snowth_my_net tui
```

Devices, Nodes, Links, Topology, Reports, Extensions and Runs are tabs (and a device sheet
has a Ports tab); `?` shows the keys. You can
collect one device or everything with a live log, set a type or a per-device setting by hand,
test an OID, and build a report. Nothing there ever shows a secret.

## 12. Or in a browser

```bash
snowth_my_net web                # http://127.0.0.1:8080
```

The same four views, read-only, with a filter and sortable columns; a MAC opens its
explanation. Details: [web interface](web.md).

## If something does not work

* `check` says `no answer`: the credential, an ACL on the device, or a firewall on the way.
* The type is empty: that is deliberate when nothing proves it; set it by hand in the interface
  or with `devices[].type`.
* A MAC is on a trunk instead of its access port: `explain` shows the rule that decided.

More cases, and vendor notes: [troubleshooting](troubleshooting.md).
