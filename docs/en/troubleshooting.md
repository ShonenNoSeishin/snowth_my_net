# Troubleshooting

Always start with `snowth_my_net check` (per device: credential used, round-trip time, which MIBs
answer and how many rows), then `snowth_my_net probe <address>` to test OIDs by hand, and
`snowth_my_net explain <mac|ip>` for positions.

## Nothing answers

* `no answer (v3-main: timeout; …)`: SNMP ACL on the device (with Docker, allow the **host**
  address), wrong port, or a wrong v2c community — v2c failures are silent, so they look like
  timeouts. Narrow `credentials[].scope`.
* `unknown user` / `wrong digest`: SNMPv3 user or key mismatch (reported immediately).
* AES-192/256 on Cisco: use `aes192c` / `aes256c` (Cisco key extension).
* `no credential in scope for this address`: no credential's `scope` contains the address.

## The type is empty

That is on purpose: a type is only set on sure evidence. Set it by hand (terminal interface,
Settings tab, or `snowth_my_net device set 192.0.2.1 type=firewall`). **The type never prevents a
collection**: ARP, MAC tables, LLDP and CDP are always attempted.

## A firewall's ARP table is missing

Nothing depends on what the device announces (sysServices, type). Check `check`: `ipNetToMedia` and
`ipNetToPhysical`. If they answer `absent`, the SNMP view of the firewall may exclude IP-MIB. Set
`features.arp: force` on it so that a future absence is reported as an error (exit 1).

## No MAC table on a Cisco switch

Cisco IOS serves the bridge tables per VLAN. snowth_my_net uses the per-VLAN instances when
CISCO-VTP-MIB answers (`vlan_indexing: auto`); force them with `vlan_indexing: cisco`.
With SNMPv3, the group needs the VLAN contexts:

```
snmp-server group SNOWTH v3 priv context vlan- match prefix
```

With v2c, `community@vlan` must be allowed by the community's view/ACL.

## Every MAC of a floor is on the trunk

Positions are only kept on access ports. A port is an uplink when an LLDP/CDP neighbour is a polled
switch (or an unpolled bridge/router), when it is declared (`uplinks`), when it carries more than
`uplink_mac_threshold` MACs, or (optionally) when it is a LAG. When LLDP is disabled between two
switches, declare the port in `uplinks`, lower the device's `uplink_mac_threshold`, or rely on
transit detection (the same MAC on a port with fewer MACs wins). `explain` shows the reasons.

## A server or hypervisor lost its positions

Many MACs on a port make it a soft uplink above the threshold (50). Declare the port in
`access_ports`, or raise `uplink_mac_threshold` for that device.

## IP phones

Phones announce `bridge` + `telephone`: that never makes a port an uplink, and the PC behind the
phone keeps its position. Phones are never probed during exploration and are not in `links.csv`
(unless `include_endpoints`).

## Wi-Fi clients

* Local bridging: clients are in the switch MAC table on the AP's port (`ap_ports_are_access`).
* Tunnelled to a controller: clients appear on the controller's port, which becomes an uplink.
  For Cisco AireOS the `cisco-wlc` driver publishes the APs and positions the clients on their
  radios; other controllers need a Python driver. See [drivers](drivers.md).

## Vendor notes

| Vendor | Note |
|---|---|
| Cisco IOS/IOS-XE | Per-VLAN bridge instances (above); `lldpLocPortNum` is not the ifIndex (mapped by name); HSRP virtual MACs ignored. |
| Cisco NX-OS | CDP device IDs `hostname(SERIAL)` are cleaned. |
| Cisco, VRFs | The default context only shows the global routing table. The VRFs the device lists are read in their own SNMP context (`devices[].vrfs`); the context name must match the VRF name on the device. |
| Juniper EX/QFX | FDB ids are not VLAN numbers: `dot1qVlanFdbId` is used. MACs learnt on logical units (`ge-0/0/5.0`) are attributed to the physical port. |
| HPE Aruba AOS-CX, ProVision | Standard MIBs; bridge ports equal ifIndexes on ProVision. |
| Fortinet, Sophos | ARP through IP-MIB; ENTITY-MIB often absent: the `fortinet` and `sophos` drivers read serial, version (and model for Sophos) from the private MIBs. |
| Palo Alto | ARP through IP-MIB; ENTITY-MIB usually present. No driver. |
| MikroTik RouterOS | Partial BRIDGE-MIB depending on the version; the `mikrotik` driver adds identity and the stations of its wireless interfaces. |
| Cisco AireOS controllers | `cisco-wlc` driver: synthetic APs and client positions. |
| Ubiquiti UniFi/EdgeSwitch | Generic SNMP stack identifiers: vendor from the MAC OUI. |
| Agents serving LLDP-V2-MIB | Read as a fallback when LLDP-MIB answers nothing; its index names the local ifIndex, so ports need no mapping. |
