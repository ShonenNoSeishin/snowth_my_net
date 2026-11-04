"""The Ports page: every port of one device, with what sits at the other end of it.

Without a device it is the list of devices, each with how many of its ports are up and how many
carry a neighbour: the way in. With one, it is the ports, as a table that can be filtered and
sorted like every other.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.merge.ports import (
    DISABLED,
    DOWN,
    UP,
    PortRow,
    device_ports,
    speed_text,
    totals,
)
from snowth_my_net.merge.view import NodeView, build_view
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo
from snowth_my_net.web.pages import Cell, Table, When, _devices_and_names, help_for

SHOWS = ("", "up", "neighbors", "uplinks", "virtual")
STATUS_TONE = {UP: "ok", DISABLED: "dim", DOWN: ""}


def ports_href(name: str, show: str = "") -> str:
    return "/ports?device=" + quote(name, safe="") + (f"&show={show}" if show else "")


def nodes_href(device: str, port: str) -> str:
    return f"/nodes?switch={quote(device, safe='')}&port={quote(port, safe='')}"


@dataclass
class DevicePorts:
    table: Table
    name: str
    subtitle: str
    show: str


def device_names(loaded: LoadedConfig, repo: Repo, now: int) -> list[str]:
    _found, names = _devices_and_names(loaded, repo, now)
    return sorted(names, key=str.casefold)


def _device_id(view: NodeView, name: str) -> int | None:
    for device_id, known in view.names.items():
        if known == name:
            return device_id
    for device_id, known in view.names.items():       # the case is not part of a name
        if known.casefold() == name.casefold():
            return device_id
    return None


def _neighbor_cells(row: PortRow, t) -> tuple[Cell, Cell, str]:
    """Neighbour, its port, and the protocol(s): the first one is shown, the others folded."""
    if not row.neighbors:
        return Cell(""), Cell(""), ""
    first, *rest = row.neighbors

    def describe(n) -> str:
        return f"{n.name} · {n.port}" if n.port else n.name

    note = ""
    if first.device_id is None:
        note = t("web.ports.endpoint") if first.endpoint else t("web.ports.not_polled")
    href = ports_href(first.name) if first.device_id is not None else ""
    title = first.platform
    cell = Cell(first.name, note, title, href=href, more=tuple(describe(n) for n in rest))
    return cell, Cell(first.port), first.protocol


def _role_cell(row: PortRow, t) -> Cell:
    if row.role == "uplink":
        note = t("web.ports.guess") if row.strength == "soft" else ""
        return Cell(t("port.uplink"), note, row.reason)
    if row.role == "access":
        return Cell(t("port.access"))
    return Cell("")


def device_table(loaded: LoadedConfig, repo: Repo, now: int, t, name: str,
                 show: str = "") -> DevicePorts | None:
    view = build_view(loaded, repo, now)
    device_id = _device_id(view, name)
    if device_id is None:
        return None
    name = view.names[device_id]
    ports = device_ports(view, repo, device_id)
    total = totals(ports)
    real = [p for p in ports if not p.virtual or p.neighbors]
    chosen = {
        "": [p for p in ports if not p.virtual],
        "up": [p for p in ports if p.status == UP and not p.virtual],
        "neighbors": [p for p in ports if p.neighbors],
        "uplinks": [p for p in ports if p.role == "uplink"],
        "virtual": ports,
    }.get(show, [p for p in ports if not p.virtual])
    rows = []
    for p in chosen:
        neighbor, remote, via = _neighbor_cells(p, t)
        status = Cell(t(f"port.{p.status}") if p.status else "",
                      tone=STATUS_TONE.get(p.status, ""))
        descr = p.descr or (t("web.ports.unplaced") if p.ifindex is None else "")
        macs = (Cell(str(p.macs), href=nodes_href(name, p.name)) if p.macs else Cell(""))
        rows.append([
            p.name, status, neighbor, remote, descr,
            _role_cell(p, t), speed_text(p.speed_mbps) if p.status == UP else "",
            str(p.vlan or ""), macs, p.lag, via])
    # what a reader came for first (the neighbour), then the rest: on a phone the table scrolls
    columns = [(t("col.port"), "text"), (t("col.status"), "text"), (t("col.neighbor"), "text"),
               (t("col.remote_port"), "text"), (t("col.description"), "text"),
               (t("col.role"), "text"), (t("col.speed"), "text"), (t("col.vlan"), "number"),
               (t("col.macs"), "number"), (t("col.lag"), "text"), (t("col.protocol"), "text")]
    keys = ["port", "status", "neighbor", "remote_port", "description", "role", "speed", "vlan",
            "macs", "lag", "protocol"]
    views = [(t("web.ports.view.all", count=total.ports), ports_href(name), show == ""),
             (t("web.ports.view.up", count=total.up), ports_href(name, "up"), show == "up"),
             (t("web.ports.view.neighbors", count=total.with_neighbor),
              ports_href(name, "neighbors"), show == "neighbors"),
             (t("web.ports.view.uplinks", count=total.uplinks), ports_href(name, "uplinks"),
              show == "uplinks")]
    virtual = len(ports) - len([p for p in ports if not p.virtual])
    if virtual:
        views.append((t("web.ports.view.virtual", count=virtual), ports_href(name, "virtual"),
                      show == "virtual"))
    device = next((d for d in repo.devices() if d["id"] == device_id), None)
    about = [name]
    if device is not None:
        about += [x for x in (split_host_port(device["mgmt_address"])[0], device["vendor"],
                              device["model"]) if x]
    subtitle = " · ".join(about) + " — " + t("web.ports.totals", ports=total.ports, up=total.up,
                                              neighbors=total.with_neighbor)
    note = t("web.ports.nolink") if not any(p.neighbors for p in real) else ""
    table = Table(columns, rows, len(rows), t("web.ports.none"),
                  help_for(t, "ports", columns, keys), keys, views, note)
    return DevicePorts(table, name, subtitle, show)


def index(loaded: LoadedConfig, repo: Repo, now: int, t) -> Table:
    """One row per device: the way into its ports."""
    view = build_view(loaded, repo, now)
    found, _names = _devices_and_names(loaded, repo, now)
    rows = []
    for d in found:
        ports = device_ports(view, repo, d["id"])
        total = totals(ports)
        name = view.names[d["id"]]
        rows.append([
            Cell(name, href=ports_href(name)), split_host_port(d["mgmt_address"])[0],
            t(f"type.{d['device_type']}") if d["device_type"] else "",
            str(total.ports), str(total.up), str(total.with_neighbor), str(total.uplinks),
            When(d["last_seen"])])
    rows.sort(key=lambda row: row[0].text.casefold())
    columns = [(t("col.name"), "text"), (t("col.ip"), "text"), (t("col.type"), "text"),
               (t("col.ports"), "number"), (t("col.up"), "number"),
               (t("col.neighbors"), "number"), (t("col.uplinks"), "number"),
               (t("col.seen"), "text")]
    keys = ["name", "ip", "type", "ports", "up", "neighbors", "uplinks", "seen"]
    return Table(columns, rows, len(rows), t("web.no_devices"),
                 help_for(t, "portsindex", columns, keys), keys)
