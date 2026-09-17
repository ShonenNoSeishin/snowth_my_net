"""Reports: definitions, filters, sort, columns, renderers and the read-only SQL mode."""

from __future__ import annotations

import json

import pytest

from snowth_my_net.config.extensions import load_extensions
from snowth_my_net.config.reports import FilterCfg, ReportCfg
from snowth_my_net.config.validate import ConfigError, build
from snowth_my_net.reports import datasets as ds_module
from snowth_my_net.reports.datasets import Dataset, Field, ReportContext
from snowth_my_net.reports.engine import (
    ReportError,
    compile_filter,
    parse_time,
    run_report,
    run_sql_report,
    sort_rows,
)
from snowth_my_net.reports.render import render

NOW = 1_790_000_000
DAY = 86400

ROWS = [
    {"name": "sw-10", "vendor": "Cisco", "ports": 48, "seen": NOW - 3 * DAY, "up": True},
    {"name": "sw-9", "vendor": "cisco", "ports": 24, "seen": NOW - 20 * DAY, "up": False},
    {"name": "fw", "vendor": "Sophos", "ports": None, "seen": NOW, "up": True},
    {"name": "ap|1", "vendor": "", "ports": 2, "seen": None, "up": False},
]
DATASET = Dataset("things", "test rows", [
    Field("name"), Field("vendor"), Field("ports", "integer"), Field("seen", "time"),
    Field("up", "bool", default=False)], lambda ctx: [dict(r) for r in ROWS])


@pytest.fixture
def ctx(monkeypatch):
    from snowth_my_net.config import reports as cfg_module

    monkeypatch.setitem(ds_module.STATIC, "things", DATASET)
    monkeypatch.setattr(cfg_module, "STATIC_DATASETS", (*cfg_module.STATIC_DATASETS, "things"))
    return ReportContext(None, None, NOW)


def test_dataset_names_are_declared_for_validation():
    from snowth_my_net.config.reports import STATIC_DATASETS

    assert tuple(ds_module.STATIC) == STATIC_DATASETS


def report(**kwargs) -> ReportCfg:
    return build(ReportCfg, {"name": "t", "dataset": "things", **kwargs})


def names(table) -> list[str]:
    return [row[0] for row in table.rows]


# --------------------------------------------------------------------------- definitions


def test_definition_checks(ctx):
    assert report().check() == []
    with pytest.raises(ConfigError) as caught:
        build(ReportCfg, {"name": "Bad Name", "dataset": "nope", "sql": "select 1"})
    errors = "\n".join(caught.value.errors)
    assert "lowercase" in errors and "exactly one of dataset or sql" in errors
    assert "unknown dataset 'nope'" in errors
    assert build(ReportCfg, {"name": "c", "dataset": "custom:poe"}).check() == []
    with pytest.raises(ConfigError, match="SELECT"):
        build(ReportCfg, {"name": "s", "sql": "delete from devices"})
    with pytest.raises(ConfigError, match="relative path"):
        build(ReportCfg, {"name": "s", "dataset": "devices", "output": "../etc/x.csv"})
    with pytest.raises(ConfigError, match="schedule"):
        build(ReportCfg, {"name": "s", "dataset": "devices", "schedule": "every day"})
    with pytest.raises(ConfigError, match="needs a value"):
        build(ReportCfg, {"name": "s", "dataset": "devices", "filters": [{"field": "ip"}]})
    with pytest.raises(ConfigError, match="takes no value"):
        build(ReportCfg, {"name": "s", "dataset": "devices",
                          "filters": [{"field": "ip", "op": "empty", "value": "x"}]})


def test_extension_files_load_reports_and_refuse_duplicates(tmp_path):
    (tmp_path / "a.yml").write_text(
        "reports:\n  - {name: r1, dataset: devices, format: html}\n"
        "collectors:\n  - {name: c1, get: {v: 1.3.6.1.2.1.1.5.0}}\n")
    collectors, reports = load_extensions(tmp_path)
    assert [c.cfg.name for c in collectors] == ["c1"]
    assert [(r.cfg.name, r.cfg.format, r.origin) for r in reports] == [
        ("r1", "html", str(tmp_path / "a.yml"))]
    (tmp_path / "b.yml").write_text("reports:\n  - {name: r1, sql: select 1}\n")
    with pytest.raises(ConfigError, match="report name 'r1' is defined more than once"):
        load_extensions(tmp_path)


def test_default_output_path(ctx, tmp_path):
    assert report(format="markdown").output_path(tmp_path) == tmp_path / "reports" / "t.md"
    assert report(output="x/y.csv").output_path(tmp_path) == tmp_path / "x" / "y.csv"


# --------------------------------------------------------------------------- filters, sort


@pytest.mark.parametrize(("flt", "expected"), [
    ({"field": "vendor", "op": "eq", "value": "CISCO"}, ["sw-10", "sw-9"]),
    ({"field": "vendor", "op": "ne", "value": "cisco"}, ["fw", "ap|1"]),
    ({"field": "vendor", "op": "empty"}, ["ap|1"]),
    ({"field": "ports", "op": "not_empty"}, ["sw-10", "sw-9", "ap|1"]),
    ({"field": "name", "op": "contains", "value": "SW"}, ["sw-10", "sw-9"]),
    ({"field": "name", "op": "startswith", "value": "f"}, ["fw"]),
    ({"field": "name", "op": "regex", "value": r"^sw-\d$"}, ["sw-9"]),
    ({"field": "ports", "op": "gt", "value": "24"}, ["sw-10"]),
    ({"field": "ports", "op": "le", "value": 24}, ["sw-9", "ap|1"]),
    ({"field": "vendor", "op": "in", "value": ["sophos", "Cisco"]}, ["sw-10", "sw-9", "fw"]),
    ({"field": "vendor", "op": "not_in", "value": ["cisco"]}, ["fw", "ap|1"]),
    ({"field": "seen", "op": "older_than", "value": "7d"}, ["sw-9"]),
    ({"field": "seen", "op": "newer_than", "value": "7d"}, ["sw-10", "fw"]),
    ({"field": "seen", "op": "lt", "value": "2026-09-05"}, ["sw-9"]),
    ({"field": "up", "op": "eq", "value": "yes"}, ["sw-10", "fw"]),
])
def test_filters(ctx, flt, expected):
    assert names(run_report(report(filters=[flt], columns=["name"]), ctx)) == expected


def test_filter_errors_name_the_problem(ctx):
    with pytest.raises(ReportError, match=r"unknown field 'nope'.*fields: name, vendor"):
        run_report(report(filters=[{"field": "nope", "op": "empty"}]), ctx)
    with pytest.raises(ReportError, match="only applies to time fields"):
        compile_filter(FilterCfg("name", "older_than", "1d"), DATASET, NOW)
    with pytest.raises(ReportError, match="expected a number"):
        compile_filter(FilterCfg("ports", "gt", "many"), DATASET, NOW)
    with pytest.raises(ReportError, match="true/false"):
        compile_filter(FilterCfg("up", "gt", "yes"), DATASET, NOW)
    with pytest.raises(ReportError, match="expected a date"):
        parse_time("last tuesday")


def test_sort_is_natural_stable_and_keeps_empty_values_last(ctx):
    assert names(run_report(report(sort=["name"]), ctx)) == ["ap|1", "fw", "sw-9", "sw-10"]
    assert names(run_report(report(sort=["-ports"]), ctx)) == ["sw-10", "sw-9", "ap|1", "fw"]
    assert names(run_report(report(sort=["ports"]), ctx)) == ["ap|1", "sw-9", "sw-10", "fw"]
    rows = sort_rows([dict(r) for r in ROWS], ["-up", "name"], DATASET)
    assert [r["name"] for r in rows] == ["fw", "sw-10", "ap|1", "sw-9"]
    with pytest.raises(ReportError, match="sort: unknown field"):
        run_report(report(sort=["-x"]), ctx)


def test_columns_labels_default_columns_and_limit(ctx):
    table = run_report(report(columns=["vendor", {"field": "name", "label": "Device Name"}],
                              sort=["name"], limit=2), ctx)
    assert table.labels == ["vendor", "Device Name"]
    assert table.rows == [["", "ap|1"], ["Sophos", "fw"]] and table.total == 4
    assert run_report(report(), ctx).labels == ["name", "vendor", "ports", "seen"]
    with pytest.raises(ReportError, match="columns: unknown field"):
        run_report(report(columns=["nope"]), ctx)


# --------------------------------------------------------------------------- renderers


def test_renderers(ctx):
    cfg = report(title="Things | all", columns=["name", "ports", "seen", "up"], sort=["name"])
    table = run_report(cfg, ctx)
    csv_text = render(table, cfg, NOW, "csv").decode()
    assert csv_text.startswith("name,ports,seen,up\r\nap|1,2,,no\r\nfw,,")
    assert render(table, cfg, NOW, "csv", "lf").decode().count("\r") == 0
    document = json.loads(render(table, cfg, NOW, "json"))
    assert document["row_count"] == 4 and document["columns"] == ["name", "ports", "seen", "up"]
    assert document["rows"][1] == {"name": "fw", "ports": None, "seen": "2026-09-21T14:13:20Z",
                                   "up": True}
    markdown = render(table, cfg, NOW, "markdown").decode()
    assert "# Things \\| all" in markdown and "| ap\\|1 | 2 |  | no |" in markdown
    assert "|---|---:|---|---|" in markdown
    page = render(table, cfg, NOW, "html").decode()
    assert "<title>Things | all</title>" in page and "ap|1" in page
    assert '<td class="integer" data-sort="48">48</td>' in page
    assert "http" not in page.split("<script>")[1]          # self-contained, no external call


def test_html_escapes_values(ctx, monkeypatch):
    evil = Dataset("things", "", [Field("name")], lambda c: [{"name": "<script>x</script>"}])
    monkeypatch.setitem(ds_module.STATIC, "things", evil)
    cfg = report()
    page = render(run_report(cfg, ReportContext(None, None, NOW)), cfg, NOW, "html").decode()
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page


# --------------------------------------------------------------------------- SQL


def sql(query: str) -> ReportCfg:
    return build(ReportCfg, {"name": "q", "sql": query})


def test_sql_reads_the_named_datasets(ctx):
    table = run_report(sql("SELECT lower(vendor) AS v, count(*) AS n, sum(ports) AS p "
                           "FROM things WHERE vendor <> '' GROUP BY 1 ORDER BY n DESC"), ctx)
    assert table.labels == ["v", "n", "p"] and table.rows == [["cisco", 2, 72], ["sophos", 1, None]]
    assert [t for _l, t in table.columns] == ["text", "integer", "integer"]
    table = run_report(sql("select name, iso(seen), age_days(seen) from things "
                           "where up order by name"), ctx)
    assert table.rows == [["fw", "2026-09-21T14:13:20Z", 0], ["sw-10", "2026-09-18T14:13:20Z", 3]]
    with_cte = sql("WITH x AS (SELECT name FROM things) SELECT count(*) FROM x")
    assert run_report(with_cte, ctx).rows == [[4]]


@pytest.mark.parametrize(("query", "message"), [
    ("select * from things; delete from things", "only one SELECT"),
    ("select * from things, pragma_table_info('things')", "not authorized"),
    ("select load_extension('x') from things", "not authorized"),
    ("select * from nothing_here", "uses no dataset table"),
    ("select * from things join nothing_here", "no such table"),
])
def test_sql_refuses_anything_but_reading(ctx, query, message):
    with pytest.raises(ReportError, match=message):
        run_report(sql(query), ctx)


def test_sql_is_stopped_after_the_time_limit(ctx):
    runaway = sql("WITH RECURSIVE c(x) AS (SELECT 1 FROM things UNION ALL SELECT x + 1 FROM c) "
                  "SELECT count(*) FROM c")
    with pytest.raises(ReportError, match="stopped after"):
        run_sql_report(runaway, ctx, timeout_s=0.2)
