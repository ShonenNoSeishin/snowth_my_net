"""What the exports state must be what was observed: fresh, unambiguous, never a guess."""

from __future__ import annotations


def test_a_csv_cell_a_spreadsheet_would_run_gets_an_apostrophe_when_asked():
    from snowth_my_net.export.csvout import render_csv
    rows = [["=HYPERLINK(1)", "+1", "-x", "@a", "10", "", "plain=ok"]]
    assert render_csv("h", rows, "lf") == b"h\n=HYPERLINK(1),+1,-x,@a,10,,plain=ok\n"
    safe = render_csv("h", rows, "lf", safe=True)
    assert safe == b"h\n'=HYPERLINK(1),'+1,'-x,'@a,10,,plain=ok\n"


def test_the_export_lists_live_nodes_and_exports_only_observed_vlans(tmp_path):
    from snowth_my_net.merge.nodes import Sighting
    from snowth_my_net.merge.view import NodeView, build_view
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo
    from tests.unit.test_cov_views import NOW, build_state, make_loaded

    build_state(tmp_path).conn.close()
    loaded = make_loaded(tmp_path)
    repo = Repo(open_db(tmp_path / "state" / "state.sqlite", readonly=True))
    view = build_view(loaded, repo, NOW)
    assert [n.mac for n in view.exported_nodes()] == [n.mac for n in view.nodes if n.live]
    assert len(view.exported_nodes()) < len(view.nodes) or all(n.live for n in view.nodes)
    loaded.cfg.export.nodes.live_only = False
    assert view.exported_nodes() == view.nodes
    for source, shown in (("fdb", "10"), ("context", "10"), ("pvid", ""), ("fdb_assumed", ""),
                          ("none", "")):
        position = Sighting(1, 1, 10, source, 0, 0, 0, 0, None)
        assert NodeView.observed_vlan(position) == shown
    repo.conn.close()
