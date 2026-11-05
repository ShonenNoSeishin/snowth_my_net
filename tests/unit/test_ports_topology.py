"""The Ports and Topology pages: what each port shows, how the drawing is laid out, and what
the pages refuse to claim."""

from __future__ import annotations

import itertools
import json
import re

import pytest

from snowth_my_net.merge import layout
from snowth_my_net.merge.ports import device_ports, natural_key, speed_text, totals
from snowth_my_net.merge.view import build_view
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.web import topology
from snowth_my_net.web.server import NAV, Site
from tests.unit.test_cov_views import NOW, FixedClock, build_state, make_loaded


@pytest.fixture
def site(tmp_path):
    build_state(tmp_path).conn.close()
    return Site(make_loaded(tmp_path), FixedClock(NOW))


def get(site: Site, path: str, **query):
    status, _type, body = site.respond(path, {k: [v] for k, v in query.items()})
    return int(status), body.decode("utf-8", errors="replace")


def topo_data(body: str) -> dict:
    found = re.search(r'<script type="application/json" id="topo-data">(.*?)</script>', body,
                      re.S)
    assert found
    return json.loads(found.group(1))


# ------------------------------------------------------------------ layout


def test_the_root_is_on_top_and_every_hop_is_a_row():
    labels = {n: n for n in "abcdefgh"}
    edges = [("a", "b"), ("a", "c"), ("a", "g"), ("a", "h"), ("b", "d"), ("b", "e"),
             ("c", "f")]
    placed = layout.layered(labels, edges)            # a has the most links: it is the top
    assert placed["a"].layer == 0 and placed["a"].y == 0
    assert {placed[n].layer for n in "bcgh"} == {1}
    assert {placed[n].layer for n in "def"} == {2}
    assert placed["b"].y == placed["c"].y == layout.DY


def test_a_chosen_root_replaces_the_best_connected_one():
    labels = {n: n for n in "abcd"}
    edges = [("a", "b"), ("a", "c"), ("a", "d")]
    assert layout.layered(labels, edges)["a"].layer == 0
    assert layout.layered(labels, edges, root="d")["d"].layer == 0


def test_the_drawing_is_the_same_every_time_and_nothing_overlaps():
    labels = {f"n{i}": f"n{i}" for i in range(30)}
    edges = [(f"n{i}", f"n{(i * 3 + 1) % 30}") for i in range(30)] + [
        ("n0", f"n{i}") for i in range(1, 12)]
    first = layout.layered(labels, edges)
    assert first == layout.layered(labels, edges)
    rows: dict[int, list[float]] = {}
    for p in first.values():
        rows.setdefault(p.layer, []).append(p.x)
    for xs in rows.values():
        xs.sort()
        assert all(b - a >= layout.DX - 1e-6 for a, b in itertools.pairwise(xs))


def test_children_sit_under_their_parent():
    labels = {n: n for n in ("root", "a", "b", "a1", "a2", "b1")}
    edges = [("root", "a"), ("root", "b"), ("a", "a1"), ("a", "a2"), ("b", "b1")]
    placed = layout.layered(labels, edges)
    assert placed["a"].x == pytest.approx((placed["a1"].x + placed["a2"].x) / 2)
    assert abs(placed["b"].x - placed["b1"].x) < layout.DX


def test_separate_networks_do_not_share_a_row_slot_and_isolated_nodes_go_below():
    labels = {n: n for n in "abcdxy"}
    placed = layout.layered(labels, [("a", "b"), ("c", "d")])
    assert placed["x"].layer == placed["y"].layer == -1
    assert placed["x"].y > max(placed[n].y for n in "abcd")
    assert {placed["a"].network, placed["c"].network} == {0, 1}
    left, right = sorted(("a", "c"), key=lambda n: placed[n].x)
    assert placed[right].x - placed[left].x >= layout.DX


def test_a_link_to_an_unknown_node_or_to_itself_is_ignored():
    placed = layout.layered({"a": "a", "b": "b"}, [("a", "a"), ("a", "zzz")])
    assert placed["a"].layer == placed["b"].layer == -1


# ------------------------------------------------------------------ ports


def test_ports_are_in_natural_order_and_speeds_are_readable():
    names = ["Gi1/0/10", "Gi1/0/2", "Gi1/0/1", "Po1", "Gi1/0/24"]
    assert sorted(names, key=natural_key) == ["Gi1/0/1", "Gi1/0/2", "Gi1/0/10", "Gi1/0/24",
                                              "Po1"]
    assert (speed_text(None), speed_text(100), speed_text(1000), speed_text(2500),
            speed_text(10000)) == ("", "100 Mb/s", "1 Gb/s", "2.5 Gb/s", "10 Gb/s")


def test_a_port_carries_what_its_device_announced_on_it(tmp_path):
    repo = build_state(tmp_path)
    view = build_view(make_loaded(tmp_path), repo, NOW)
    sw1 = next(i for i, name in view.names.items() if name == "sw1")
    ports = {p.name: p for p in device_ports(view, repo, sw1)}
    uplink = ports["Gi1/0/24"]
    assert uplink.status == "up" and uplink.speed_mbps == 1000
    assert uplink.role == "uplink" and uplink.macs >= 3
    (neighbor,) = uplink.neighbors                       # LLDP and CDP agree: one neighbour
    assert (neighbor.name, neighbor.port, neighbor.protocol) == ("sw2", "Gi0/5", "LLDP+CDP")
    assert neighbor.device_id is not None and not neighbor.endpoint
    phone = ports["Gi1/0/2"].neighbors[0]
    assert phone.endpoint and phone.device_id is None
    assert ports["Gi1/0/1"].neighbors == [] and ports["Gi1/0/1"].descr == "users"
    unplaced = [p for p in device_ports(view, repo, sw1) if p.ifindex is None]
    assert [n.name for p in unplaced for n in p.neighbors] == ["00:00:5e:00:53:88"]
    summary = totals(device_ports(view, repo, sw1))
    assert (summary.ports, summary.up, summary.with_neighbor) == (3, 1, 2)


def test_a_port_that_is_down_or_shut_is_told_apart(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.execute("UPDATE interfaces SET oper_status = 2, admin_status = 1 "
                      "WHERE ifindex = 24")
    repo.conn.execute("UPDATE interfaces SET admin_status = 2 WHERE ifindex = 1")
    repo.conn.commit()
    view = build_view(make_loaded(tmp_path), repo, NOW)
    sw1 = next(i for i, name in view.names.items() if name == "sw1")
    ports = {p.name: p for p in device_ports(view, repo, sw1)}
    assert ports["Gi1/0/24"].status == "down" and ports["Gi1/0/1"].status == "disabled"


def test_virtual_interfaces_are_hidden_unless_something_was_heard_on_them(tmp_path):
    repo = build_state(tmp_path)
    sw1 = repo.conn.execute("SELECT id FROM devices WHERE sys_name LIKE 'sw1%'").fetchone()[0]
    repo.conn.execute("INSERT INTO interfaces(device_id, ifindex, name, if_type, oper_status) "
                      "VALUES (?, 99, 'Loopback0', 24, 1)", (sw1,))
    repo.conn.execute("UPDATE interfaces SET if_type = 24 WHERE ifindex = 2")
    repo.conn.commit()
    view = build_view(make_loaded(tmp_path), repo, NOW)
    ports = {p.name: p for p in device_ports(view, repo, sw1)}
    assert ports["Loopback0"].virtual                  # nothing on it: not a cable
    assert not ports["Gi1/0/2"].virtual                # a MAC and a neighbour are evidence
    assert totals(list(ports.values())).ports == 3
    repo.conn.close()
    site = Site(make_loaded(tmp_path), FixedClock(NOW))
    assert "Loopback0" not in get(site, "/ports", device="sw1")[1]
    assert "Loopback0" in get(site, "/ports", device="sw1", show="virtual")[1]


# ------------------------------------------------------------------ pages


def test_the_tabs_are_there_in_both_languages(site):
    paths = [page.path for page in NAV]
    assert "/ports" in paths and "/topology" in paths
    for path in ("/ports", "/topology"):
        for lang in ("en", "fr"):
            status, _type, body = site.respond(path, {}, lang=lang)
            assert status == 200 and f'href="{path}" class="on"' in body.decode()


def test_the_ports_index_leads_to_each_device(site):
    status, body = get(site, "/ports")
    assert status == 200
    for name in ("sw1", "sw2", "fw"):
        assert f'href="/ports?device={name}"' in body


def test_a_device_page_links_its_neighbour_and_its_nodes(site):
    status, body = get(site, "/ports", device="sw1")
    assert status == 200
    assert 'href="/ports?device=sw2"' in body                 # a polled neighbour opens its ports
    assert "Gi0/5" in body and "LLDP+CDP" in body
    assert 'href="/nodes?switch=sw1&amp;port=Gi1/0/24"' in body or \
        'href="/nodes?switch=sw1&amp;port=Gi1%2F0%2F24"' in body
    assert 'id="device"' in body and "<option" in body       # the chooser works without script


def test_the_views_of_the_ports_page_filter_and_keep_their_pills(site):
    _s, everything = get(site, "/ports", device="sw1")
    _s, with_neighbor = get(site, "/ports", device="sw1", show="neighbors")
    assert "Gi1/0/1<" in everything and "Gi1/0/1<" not in with_neighbor
    assert "Gi1/0/24" in with_neighbor
    _s, uplinks = get(site, "/ports", device="sw1", show="uplinks")
    assert "Gi1/0/24" in uplinks and "Gi1/0/2<" not in uplinks


def test_an_empty_view_still_shows_the_way_back(site, tmp_path):
    _s, body = get(site, "/ports", device="fw", show="uplinks")
    assert 'class="view' in body and "/ports?device=fw" in body


def test_an_unknown_device_is_a_404_with_the_way_in(site):
    status, body = get(site, "/ports", device="nope")
    assert status == 404 and "nope" in body and 'href="/ports?device=sw1"' in body


def test_a_device_name_is_escaped_on_the_ports_page(site):
    status, body = get(site, "/ports", device='"><script>alert(1)</script>')
    assert status == 404 and "<script>alert(1)" not in body


def test_nodes_can_be_filtered_by_port(site):
    _s, body = get(site, "/nodes", switch="sw1", port="Gi1/0/1")
    assert "00:00:5e:00:53:a0" in body                        # A sits on Gi1/0/1
    assert "00:00:5e:00:53:b0" not in body                    # B is on Gi1/0/24
    assert "Gi1/0/1" in body


def test_devices_and_links_open_ports(site):
    _s, devices = get(site, "/")
    assert 'href="/ports?device=sw1"' in devices
    _s, links = get(site, "/links")
    assert 'href="/ports?device=sw2"' in links


# ------------------------------------------------------------------ topology


def test_the_topology_draws_the_announced_links_only(site):
    status, body = get(site, "/topology")
    assert status == 200
    data = topo_data(body)
    labels = {n["label"]: n for n in data["nodes"]}
    assert {"sw1", "sw2", "fw", "core-rtr"} <= set(labels)
    assert labels["core-rtr"]["kind"] == "external" and labels["sw1"]["kind"] == "device"
    pair = {frozenset((labels["sw1"]["id"], labels["sw2"]["id"]))}
    assert pair <= {frozenset((e["a"], e["b"])) for e in data["edges"]}
    sw1_sw2 = next(e for e in data["edges"] if {e["a"], e["b"]} == set(next(iter(pair))))
    assert sw1_sw2["proto"] == "LLDP+CDP" and {sw1_sw2["ap"], sw1_sw2["bp"]} == {"Gi1/0/24",
                                                                                "Gi0/5"}
    assert labels["sw1"]["href"] == "/ports?device=sw1" and labels["core-rtr"]["href"] == ""


def test_a_device_seeing_itself_is_not_a_link(site):
    data = topo_data(get(site, "/topology")[1])
    assert all(e["a"] != e["b"] for e in data["edges"])


def test_end_hosts_appear_only_when_asked_for(site):
    data = topo_data(get(site, "/topology")[1])
    assert not any(n["label"].startswith("SEP") for n in data["nodes"])
    _s, plain = get(site, "/topology")
    assert "endpoints=1" in plain                                # the way to ask
    data = topo_data(get(site, "/topology", endpoints="1")[1])
    assert any(n["label"].startswith("SEP") and n["endpoint"] for n in data["nodes"])


def test_the_root_can_be_chosen_by_name(site):
    data = topo_data(get(site, "/topology", root="fw")[1])
    fw = next(n for n in data["nodes"] if n["label"] == "fw")
    assert fw["layer"] == 0 and data["root"] == fw["id"]
    unknown = topo_data(get(site, "/topology", root="nope")[1])
    assert unknown["root"]                                        # falls back to the best one


def test_every_device_is_drawn_even_without_a_link(site, tmp_path):
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite"))
    repo.conn.execute("DELETE FROM neighbors")
    repo.conn.commit()
    repo.conn.close()
    data = topo_data(get(site, "/topology")[1])
    assert {n["label"] for n in data["nodes"]} == {"sw1", "sw2", "fw"}
    assert {n["layer"] for n in data["nodes"]} == {-1}


def test_the_data_cannot_close_its_script_block():
    out = topology._json({"label": "</script><script>alert(1)</script>", "a": "&"})
    assert "<" not in out and ">" not in out
    assert json.loads(out)["label"] == "</script><script>alert(1)</script>"


def test_the_page_runs_no_inline_script_and_the_script_is_served(site):
    _s, body = get(site, "/topology")
    scripts = re.findall(r"<script([^>]*)>", body)
    assert scripts and all('src="' in s or 'type="application/json"' in s for s in scripts)
    assert 'src="/static/topology.js"' in body
    status, content_type, data = site.respond("/static/topology.js", {})
    assert status == 200 and content_type.startswith("text/javascript") and data
    assert b"innerHTML" not in data and b"eval(" not in data


def test_the_topology_with_no_device_says_so(tmp_path):
    Repo(open_db(tmp_path / "state" / "state.sqlite")).conn.close()
    status, _type, body = Site(make_loaded(tmp_path), FixedClock(NOW)).respond("/topology", {})
    assert status == 200
    assert b"No device yet" in body or "Aucun équipement".encode() in body


# ------------------------------------------------------------------ ports.csv


def exported(tmp_path, only, **cfg):
    from snowth_my_net.export.run import export

    repo = build_state(tmp_path)
    loaded = make_loaded(tmp_path)
    loaded.cfg.export.links.include_endpoints = cfg.get("endpoints", False)
    result = export(loaded, repo, FixedClock(NOW), only=only)
    assert not result.failed
    return loaded, result


def test_ports_csv_is_opt_in_and_the_default_files_are_untouched(tmp_path):
    from snowth_my_net.config.schema import ExportCfg

    assert "ports" not in ExportCfg().files
    loaded, _ = exported(tmp_path, ["devices", "nodes", "links"])
    assert not (loaded.paths.output_dir / "ports.csv").exists()


def test_ports_csv_has_a_row_per_port_with_its_infrastructure_neighbour(tmp_path):
    import csv

    loaded, _ = exported(tmp_path, ["ports"])
    text = (loaded.paths.output_dir / "ports.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0] == (
        'Device Name,Port,Description,Status,Speed,VLAN,Aggregate,Role,MACs,Neighbor,'
        '"Remote Port",Protocol')
    rows = [r for r in csv.DictReader(text.splitlines()) if r["Device Name"] == "sw1"]
    by_port = {r["Port"]: r for r in rows}
    up = by_port["Gi1/0/24"]
    assert (up["Status"], up["Speed"], up["Role"]) == ("up", "1000", "uplink")
    assert (up["Neighbor"], up["Remote Port"], up["Protocol"]) == ("sw2", "Gi0/5", "LLDP+CDP")
    assert by_port["Gi1/0/2"]["Neighbor"] == ""              # a phone is not infrastructure
    assert by_port["Gi1/0/1"]["Description"] == "users"
    assert all(r["Port"] != "?" for r in rows)               # no row for an unplaced neighbour
    assert len({(r["Device Name"], r["Port"]) for r in csv.DictReader(text.splitlines())}) == len(
        list(csv.DictReader(text.splitlines())))             # (device, port) is a key


def test_ports_csv_shows_the_phone_when_endpoints_are_asked_for(tmp_path):
    import csv

    loaded, _ = exported(tmp_path, ["ports"], endpoints=True)
    text = (loaded.paths.output_dir / "ports.csv").read_text(encoding="utf-8")
    rows = {r["Port"]: r for r in csv.DictReader(text.splitlines())
            if r["Device Name"] == "sw1"}
    assert rows["Gi1/0/2"]["Neighbor"] != ""


def test_the_snapshot_says_what_a_port_is_without_changing_the_rest(tmp_path):
    loaded, _ = exported(tmp_path, ["snapshot"])
    data = json.loads((loaded.paths.output_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert data["schema"] == "snowth_my_net/snapshot/1"
    sw1 = next(d for d in data["devices"] if d["name"] == "sw1")
    assert sw1["ports"] == {"ports": 3, "up": 1, "with_neighbor": 2, "uplinks": 1}
    gi24 = next(i for i in sw1["interfaces"] if i["name"] == "Gi1/0/24")
    assert gi24["status"] == "up" and gi24["virtual"] is False and gi24["role"] == "uplink"
