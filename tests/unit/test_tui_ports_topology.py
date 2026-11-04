"""The terminal's Ports tab (one device) and Topology tab (the whole network, as a tree)."""

from __future__ import annotations

from textual.widgets import DataTable, Static, Tree

from snowth_my_net.merge.tree import Edge, build_tree
from snowth_my_net.state.db import open_db
from snowth_my_net.tui.app import DeviceScreen
from tests.unit.test_cov_tui_screens import (
    NOW,
    cells,
    make_app,  # noqa: F401  (a fixture)
    open_device,
    settle,
    tab,
)


def add_links(app) -> None:
    """sw1 port 3 faces fw1 (polled); port 4 faces a router that is not polled."""
    conn = open_db(app.ctx.loaded.paths.state_file)
    with conn:
        conn.execute("UPDATE interfaces SET oper_status = 1, admin_status = 1, speed_mbps = 1000, "
                     "alias = 'to firewall' WHERE device_id = 1 AND ifindex = 3")
        conn.execute("INSERT INTO interfaces(device_id, ifindex, name, descr, if_type, "
                     "oper_status, admin_status, last_seen) "
                     "VALUES (1, 4, 'Gi1/0/4', 'Gi1/0/4', 6, 2, 1, ?)", (NOW,))
        conn.execute("INSERT INTO interfaces(device_id, ifindex, name, descr, if_type, "
                     "oper_status, admin_status, last_seen) "
                     "VALUES (2, 1, 'eth1', 'eth1', 6, 1, 1, ?)", (NOW,))
        conn.executemany(
            "INSERT INTO neighbors(device_id, ifindex, protocol, remote_key, remote_chassis_id, "
            "remote_sys_name, remote_port_id, remote_port_desc, remote_mgmt_address, "
            "remote_caps, remote_platform, first_seen, last_seen, last_run_id) "
            "VALUES (1, ?, 'lldp', ?, '', ?, ?, '', ?, ?, '', ?, ?, 1)",
            [(3, "fw1", "fw1", "eth1", "192.0.2.2", "bridge,router", NOW, NOW),
             (4, "edge", "edge-rtr", "ge-0/0/1", "203.0.113.9", "router", NOW, NOW)])
    conn.close()


async def test_the_ports_tab_lists_every_port_with_its_neighbor(make_app):  # noqa: F811
    app = make_app()
    add_links(app)
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        device = await open_device(app, pilot, "sw1")
        rows = {r[0]: r for r in cells(device.query_one("#ports", DataTable))}
        assert set(rows) == {"Gi1/0/3", "Gi1/0/4"}
        up = rows["Gi1/0/3"]
        assert up[1] == "to firewall" and up[2] == "up" and up[3] == "1 Gb/s"
        assert up[7] == "fw1" and up[8] == "eth1" and up[9] == "LLDP"
        assert rows["Gi1/0/4"][2] == "down" and rows["Gi1/0/4"][7] == "edge-rtr"
        totals = str(device.query_one("#ports-totals", Static).render())
        assert "2 ports, 1 up, 2 with a neighbor" in totals


async def test_a_device_without_ports_says_so(make_app):  # noqa: F811
    app = make_app()
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        device = await open_device(app, pilot, "fw1")
        assert str(device.query_one("#ports-empty", Static).render()) == app.ctx.t(
            "tui.ports.none")


async def test_the_topology_tab_hangs_each_device_under_its_parent(make_app):  # noqa: F811
    app = make_app()
    add_links(app)
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        tab(app, "topology")
        await settle(app, pilot)
        tree = screen.query_one("#topology", Tree)

        def lines(node, depth=0):
            yield depth, str(node.label)
            for child in node.children:
                yield from lines(child, depth + 1)

        text = list(lines(tree.root))
        root = next(depth_label for depth_label in text if depth_label[1].startswith("sw1"))
        assert root[0] == 1
        assert any(d == 2 and "Gi1/0/3" in label and "fw1" in label for d, label in text)
        assert any(d == 2 and "Gi1/0/4" in label and "edge-rtr" in label
                   and "not polled" in label for d, label in text)
        count = str(screen.query_one("#topology-count", Static).render())
        assert "2 link(s)" in count


async def test_enter_on_a_polled_device_opens_it(make_app):  # noqa: F811
    app = make_app()
    add_links(app)
    async with app.run_test(size=(170, 48)) as pilot:
        await settle(app, pilot)
        screen = app.screen
        tab(app, "topology")
        await settle(app, pilot)
        tree = screen.query_one("#topology", Tree)
        tree.focus()
        node = next(n for n in tree.root.children if n.data == "sw1")
        tree.select_node(node)
        await settle(app, pilot)
        assert isinstance(app.screen, DeviceScreen)


def test_a_tree_puts_a_loop_in_the_also_list_and_keeps_isolated_names():
    edges = [Edge("core", "1", "dist", "1", "LLDP"), Edge("core", "2", "dist", "2", "LLDP"),
             Edge("dist", "5", "acc", "1", "LLDP"), Edge("core", "9", "acc", "9", "CDP")]
    roots, isolated = build_tree(["core", "dist", "acc", "lonely"], edges)
    assert isolated == ["lonely"]
    (root,) = roots
    assert root.name == "core"
    assert [c.name for c in root.children] == ["acc", "dist"]
    # the 2nd cable core-dist and the link acc-dist (which closes a loop) are not branches
    extras = {(n.name, e.other) for n in (root, *root.children) for e in n.extras}
    assert extras == {("core", "dist"), ("acc", "dist")}


def test_a_name_that_is_not_known_or_a_link_to_itself_is_ignored():
    roots, isolated = build_tree(["a", "b"], [Edge("a", "1", "a", "2"), Edge("a", "1", "zz", "1")])
    assert roots == [] and isolated == ["a", "b"]
