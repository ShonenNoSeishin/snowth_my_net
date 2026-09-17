# snowth_my_net

Lightweight, **read-only** SNMP network mapper. It discovers switches, access points, firewalls
and routers, merges their ARP and MAC tables, and tells you which devices exist, who is plugged
where, and how the devices are connected. Output: fixed-format CSV, JSON and maps, optionally
pushed over HTTP on a schedule.

> Status: under development. Phase 1 (inventory, `devices.csv`) and the terminal management
> interface are available. See [DESIGN.md](DESIGN.md) (in French) for the architecture and the
> decisions. Full documentation comes with phase 4.

## Quick look

```bash
snowth_my_net init            # commented example configuration
snowth_my_net check           # diagnose credentials and MIB support, device by device
snowth_my_net collect         # poll the devices
snowth_my_net export          # write devices.csv
snowth_my_net                 # open the terminal interface (or: snowth_my_net tui)
snowth_my_net probe 192.0.2.254 arp-media    # test OIDs by hand
snowth_my_net device set 192.0.2.254 type=firewall features.arp=force
```

The device type is only a label: it never prevents a collection. ARP tables, MAC tables, LLDP
and CDP are attempted on every device unless you switch a function `off`.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Provided "as is", without warranty
and without liability.
