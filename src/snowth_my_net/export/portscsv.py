"""ports.csv: one row per port, with the infrastructure neighbour announced on it.

Opt-in (``export.files: [..., ports]``): the three default files keep their shape. The rows are
the ones the Ports page shows (``merge.ports``), so the web, the terminal and the file agree.
Phones and stations are left out unless ``export.links.include_endpoints``, as in links.csv; a
port with several neighbours carries the first in the columns and all of them in snapshot.json.
"""

from __future__ import annotations

PORTS_HEADER = ("Device Name,Port,Description,Status,Speed,VLAN,Aggregate,Role,MACs,Neighbor,"
                '"Remote Port",Protocol')


def port_rows(view, repo, devices, include_endpoints: bool) -> list[list[str]]:
    """``Speed`` is Mb/s, ``Status`` is up, down or disabled; both empty when not reported."""
    from snowth_my_net.merge.ports import device_ports

    rows = []
    for d in sorted(devices, key=lambda d: view.names[d["id"]].casefold()):
        name = view.names[d["id"]]
        for p in device_ports(view, repo, d["id"]):
            if p.virtual or p.ifindex is None:       # no cable, or a neighbour with no known port
                continue
            first = next((n for n in p.neighbors if include_endpoints or not n.endpoint), None)
            rows.append([
                name, p.name, p.descr, p.status,
                str(p.speed_mbps) if p.speed_mbps and p.status == "up" else "",
                str(p.vlan or ""), p.lag, p.role, str(p.macs) if p.macs else "",
                first.name if first else "", first.port if first else "",
                first.protocol if first else ""])
    return rows
