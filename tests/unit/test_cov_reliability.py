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


def _random_fixture(tmp_path):
    from snowth_my_net.state.db import open_db
    from snowth_my_net.state.repo import Repo
    from tests.unit.test_cov_views import build_state, make_loaded

    build_state(tmp_path).conn.close()
    loaded = make_loaded(tmp_path)
    return loaded, Repo(open_db(tmp_path / "state" / "state.sqlite", readonly=True))


def test_local_macs_can_be_left_out_of_the_export_and_are_never_merged(tmp_path):
    from snowth_my_net.merge.view import build_view
    from tests.unit.test_cov_views import NOW, RANDOM

    loaded, repo = _random_fixture(tmp_path)
    loaded.cfg.export.nodes.live_only = False
    view = build_view(loaded, repo, NOW)
    assert RANDOM in [n.mac for n in view.exported_nodes()]          # kept by default
    before = len(view.nodes)
    loaded.cfg.export.nodes.local_macs = "skip"
    kept = view.exported_nodes()
    assert RANDOM not in [n.mac for n in kept] and not any(n.random_mac for n in kept)
    assert len(view.nodes) == before                                  # nothing merged or dropped
    repo.conn.close()


def test_the_nodes_page_filters_and_labels_local_macs(tmp_path):
    from snowth_my_net.i18n import Translator
    from snowth_my_net.web import pages
    from tests.unit.test_cov_views import NOW, RANDOM

    loaded, repo = _random_fixture(tmp_path)
    t = Translator("en")
    everything = pages.nodes(loaded, repo, NOW, t, 2000)
    only = pages.nodes(loaded, repo, NOW, t, 2000, local_macs="only")
    hidden = pages.nodes(loaded, repo, NOW, t, 2000, local_macs="hide")
    macs = lambda table: {pages.text_of(row[4]) for row in table.rows}   # noqa: E731
    assert macs(only) == {RANDOM}
    assert RANDOM not in macs(hidden) and macs(hidden) | macs(only) == macs(everything)
    for row in only.rows:
        assert row[5].note == t("web.random.badge") and row[5].text == ""
    assert only.note == t("web.random.note")
    assert [label for label, _href, _on in only.views if "Local MACs" in label]
    repo.conn.close()


def test_the_nodes_page_filters_the_macs_whose_address_changes_often(tmp_path):
    from snowth_my_net.i18n import Translator
    from snowth_my_net.merge.view import build_view
    from snowth_my_net.web import pages
    from tests.unit.test_cov_views import NOW

    loaded, repo = _random_fixture(tmp_path)
    t = Translator("en")
    view = build_view(loaded, repo, NOW)
    loaded.cfg.nodes.ip_churn_min = 1                          # every node with an IPv4 counts
    flagged = {n.mac for n in view.nodes if view.ip_churn(n)}
    assert flagged
    only = pages.nodes(loaded, repo, NOW, t, 2000, churn_only=True)
    assert {pages.text_of(row[4]) for row in only.rows} <= flagged
    assert only.note == t("web.churn.note", days=7, count=1)
    assert any("changes often" in label for label, _h, _on in only.views)
    loaded.cfg.nodes.ip_churn_min = 99
    assert not pages.nodes(loaded, repo, NOW, t, 2000, churn_only=True).rows
    repo.conn.close()
