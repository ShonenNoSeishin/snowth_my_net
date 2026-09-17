"""Report engine, renderers, service helpers and schedule planning: remaining paths."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.config.reports import FilterCfg, LoadedReport, ReportCfg
from snowth_my_net.config.validate import ConfigError, build
from snowth_my_net.reports import datasets as ds_module
from snowth_my_net.reports import engine
from snowth_my_net.reports.datasets import Dataset, DatasetError, Field, ReportContext, get_dataset
from snowth_my_net.reports.engine import (
    ReportError,
    ReportTable,
    compile_filter,
    parse_time,
    run_report,
    run_sql_report,
)
from snowth_my_net.reports.render import render
from snowth_my_net.reports.service import all_reports, parse_report, report_definition
from snowth_my_net.schedule import planning
from snowth_my_net.schedule.cron import CronError, parse_cron

NOW = 1_800_000_000
ROWS = [{"name": "a", "count": 3, "seen": NOW, "flag": True},
        {"name": "B", "count": None, "seen": None, "flag": False}]
DATASET = Dataset("things", "t", [Field("name"), Field("count", "integer"),
                                  Field("seen", "time"), Field("flag", "bool")],
                  lambda ctx: [dict(r) for r in ROWS])


@pytest.fixture
def ctx(monkeypatch):
    from snowth_my_net.config import reports as cfg_reports

    monkeypatch.setitem(ds_module.STATIC, "things", DATASET)
    monkeypatch.setattr(cfg_reports, "STATIC_DATASETS", (*cfg_reports.STATIC_DATASETS, "things"))
    return ReportContext(None, None, NOW)


def names(table):
    return [r[0] for r in table.rows]


def test_parse_time_forms():
    assert parse_time(5) == 5 and parse_time(" 42 ") == 42
    assert parse_time("2027-01-15T12:00:00+01:00") == int(
        datetime(2027, 1, 15, 11, tzinfo=UTC).timestamp())
    with pytest.raises(ReportError, match="expected a date"):
        parse_time(False)


def test_coercion_and_text_operators(ctx):
    def rows(field, op, value=None):
        return run_report(build(ReportCfg, {"name": "t", "dataset": "things", "columns": ["name"],
                                            "filters": [{"field": field, "op": op,
                                                         "value": value}]}), ctx)

    assert names(rows("flag", "eq", True)) == ["a"]
    assert names(rows("flag", "eq", "off")) == ["B"]
    assert names(rows("flag", "ne", "no")) == ["a"]
    assert names(rows("name", "not_contains", "A")) == ["B"]
    assert names(rows("name", "endswith", "b")) == ["B"]
    assert names(rows("count", "regex", "^3$")) == ["a"]
    with pytest.raises(ReportError, match="expected a number, got True"):
        compile_filter(FilterCfg("count", "gt", True), DATASET, NOW)
    with pytest.raises(ReportError, match="expected true or false, got 'maybe'"):
        compile_filter(FilterCfg("flag", "eq", "maybe"), DATASET, NOW)
    with pytest.raises(ReportError, match="only applies to text fields"):
        compile_filter(FilterCfg("count", "contains", "3"), DATASET, NOW)
    with pytest.raises(ReportError, match="needs a value"):
        compile_filter(FilterCfg("name", "eq"), DATASET, NOW)


def test_dataset_errors(ctx):
    with pytest.raises(DatasetError, match="unknown dataset 'nope'"):
        get_dataset("nope", [])
    cfg = ReportCfg("t", dataset="custom:missing")
    with pytest.raises(ReportError, match="unknown dataset 'custom:missing'"):
        run_report(cfg, ctx)
    with pytest.raises(ReportError, match="set exactly one of dataset or sql"):
        run_report(ReportCfg("t"), ctx)

    def broken(context):
        raise KeyError("column")

    ctx.extra = [Dataset("py:broken", "", [Field("a")], broken),
                 Dataset("py:strict", "", [Field("a")],
                         lambda c: (_ for _ in ()).throw(ReportError("already clear")))]
    with pytest.raises(ReportError, match="dataset py:broken failed: KeyError"):
        run_report(ReportCfg("t", dataset="py:broken"), ctx)
    with pytest.raises(ReportError, match="already clear"):
        run_report(ReportCfg("t", dataset="py:strict"), ctx)


def test_sql_limits_and_errors(ctx, monkeypatch):
    with pytest.raises(ReportError, match="sql must be a SELECT query"):
        run_sql_report(ReportCfg("t", sql="delete from things"), ctx)
    table = run_report(ReportCfg("t", sql="select name from things order by lower(name)",
                                 limit=1), ctx)
    assert table.rows == [["a"]] and table.total == 2
    monkeypatch.setattr(engine, "SQL_MAX_ROWS", 1)
    with pytest.raises(ReportError, match="more than 1 rows"):
        run_report(ReportCfg("t", sql="select name from things"), ctx)
    monkeypatch.setattr(engine, "SQL_MAX_ROWS", 100)

    real_connect = sqlite3.connect

    class Failing:
        def __init__(self, error):
            self.inner, self.error = real_connect(":memory:"), error

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, query, *args):
            if query.lstrip().lower().startswith("select"):
                raise self.error
            return self.inner.execute(query, *args)

    for error, message in ((sqlite3.ProgrammingError("bad binding"), "sql: bad binding"),
                           (sqlite3.Warning("two statements"), "only one SELECT statement")):
        monkeypatch.setattr(engine.sqlite3, "connect", lambda _p, e=error: Failing(e))
        with pytest.raises(ReportError, match=message):
            run_report(ReportCfg("t", sql="select name from things"), ctx)


def test_sort_key_puts_empty_values_last():
    assert engine._sort_key(None, "text") > engine._sort_key("z", "text")
    assert engine._sort_key("", "integer") > engine._sort_key(10**9, "integer")


def test_render_markdown_description_and_unknown_format():
    cfg = ReportCfg("r", dataset="devices", description="Line one\nline two")
    table = ReportTable([("a", "text")], [["x"]], 1)
    text = render(table, cfg, NOW, "markdown").decode()
    assert "Line one line two" in text
    empty = render(ReportTable([], [], 0), cfg, NOW, "markdown").decode()
    assert "|" not in empty
    with pytest.raises(ValueError, match="unknown format 'pdf'"):
        render(table, cfg, NOW, "pdf")


def test_report_definitions_round_trip():
    data = {"name": "full", "title": "T", "description": "D", "dataset": "nodes",
            "columns": ["mac", {"field": "ip", "label": "IP"}, {"field": "vlan"}],
            "filters": [{"field": "vlan", "op": "eq", "value": 10},
                        {"field": "ip", "op": "empty"}],
            "sort": ["-last_seen"], "limit": 5, "format": "json", "output": "x/y.json",
            "schedule": "@daily", "push": ["cmdb"], "allow_empty": True}
    definition = report_definition(parse_report(data))
    assert definition["columns"] == ["mac", {"field": "ip", "label": "IP"}, "vlan"]
    assert definition == {**data, "columns": definition["columns"]}
    assert report_definition(parse_report({"name": "min", "sql": "select 1"})) == {
        "name": "min", "sql": "select 1", "format": "csv"}
    with pytest.raises(ConfigError, match="unknown dataset"):
        parse_report({"name": "bad", "dataset": "nope"})


def test_all_reports_merges_files_and_state(tmp_path):
    loaded = LoadedConfig(parse_config_text("push: {targets: [{name: cmdb, url: 'https://x'}]}"),
                          Paths(tmp_path / "c.yml", tmp_path, tmp_path, tmp_path))
    loaded.reports = [LoadedReport(ReportCfg("from-file", dataset="devices", push=["cmdb"]),
                                   "reports.yml")]
    stored = {"from-file": {"name": "from-file", "dataset": "nodes"},
              "broken": {"name": "broken", "dataset": "nope"},
              "tui": {"name": "tui", "dataset": "links", "push": ["cmdb", "gone"]}}
    reports, warnings = all_reports(loaded, stored)
    assert [(r.cfg.name, r.origin) for r in reports] == [("from-file", "reports.yml"),
                                                         ("tui", "tui")]
    assert any("shadowed by an extension file" in w for w in warnings)
    assert any("'broken' from the state is invalid" in w for w in warnings)
    assert "report 'tui': unknown push target(s) gone" in warnings


# --------------------------------------------------------------------------- schedule


def test_cron_edge_cases():
    with pytest.raises(CronError, match="empty list item"):
        parse_cron("1,,2 * * * *")
    expr = parse_cron("0 0 * feb *")
    moments = list(expr.fire_times(datetime(2026, 11, 30, 23, 59, 30, tzinfo=UTC),
                                   datetime(2027, 2, 2, tzinfo=UTC)))
    assert moments[0] == datetime(2027, 2, 1, tzinfo=UTC)
    assert not expr.matches(datetime(2027, 3, 1, tzinfo=UTC))


def test_executable_detection(tmp_path, monkeypatch):
    assert planning.executable("/opt/x") == "/opt/x"
    binary = tmp_path / "snowth_my_net"
    binary.write_text("")
    monkeypatch.setattr(planning.sys, "argv", [str(binary)])
    assert planning.executable() == str(binary.resolve())
    monkeypatch.setattr(planning.sys, "argv", ["python"])
    monkeypatch.setattr(planning.shutil, "which", lambda name: None)
    assert planning.executable() == "snowth_my_net"
    monkeypatch.setattr(planning.shutil, "which", lambda name: str(binary))
    assert planning.executable() == str(binary.resolve())


def test_cron_lines_without_quiet_or_schedules(tmp_path):
    loaded = LoadedConfig(parse_config_text("schedule: {collect: null, export_push: null}"),
                          Paths(tmp_path / "c.yml", tmp_path, tmp_path, tmp_path))
    loaded.reports = [LoadedReport(ReportCfg("r", dataset="devices"), "f")]
    assert planning.cron_lines(loaded, "/bin/snowth", quiet=False) == []
    assert planning.max_collect_age(loaded) == (86400, "no schedule.collect: default 24h")
    loaded.cfg.schedule.collect = "0 0 29 2 *"          # fires once in 14 days at most
    assert planning.max_collect_age(loaded)[0] == 14 * 86400 * 2
    loaded.cfg.schedule.health_max_age = 600
    assert planning.max_collect_age(loaded) == (600, "schedule.health_max_age")
    loaded.cfg.schedule.export_push = "@daily"
    line = planning.cron_lines(loaded, "/bin/snowth", config_path="/etc/c.yml", quiet=False)[-1]
    assert line.command == ["/bin/snowth", "--config", "/etc/c.yml", "run", "--no-collect",
                            "--no-push"]
    assert Path(line.command[0]).name == "snowth"
    loaded.reports.append(LoadedReport(ReportCfg("weekly", dataset="devices", schedule="0 7 * * 1"),
                                       "tui"))
    last = planning.cron_lines(loaded, "/bin/snowth")[-1]
    assert (last.schedule, last.command[-3:], last.comment) == (
        "0 7 * * 1", ["report", "run", "weekly"], "report weekly (tui)")
