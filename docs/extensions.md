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

## Coming next

Custom reports (datasets, columns, filters, CSV/JSON/Markdown/HTML, a builder in the terminal
interface, read-only SQL on stable views) and Python extensions with hooks — see DESIGN.md §21.
