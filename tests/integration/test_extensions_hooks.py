"""E3 against snmpsim: Python extensions (collector, dataset, exporter) and hooks."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from snowth_my_net.cli import main
from tests.support.lab import write_config

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "extensions" / "host_storage.py"
TOOL = str(Path(sys.executable).parent / "snowth_my_net")

RECORDER = """
import json, os, sys
out = sys.argv[1]
summary = json.load(open(os.environ["SNOWTH_SUMMARY"]))
with open(out, "a") as handle:
    handle.write(json.dumps({"argv": sys.argv[2:], "env": dict(os.environ),
                             "summary": summary, "cwd": os.getcwd()}) + "\\n")
"""


def run_json(capsys, *argv):
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def with_python(lab, tmp_path, extra_yaml=""):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("linux")], files="[devices, snapshot]")
    (tmp_path / "extensions").mkdir()
    shutil.copy(EXAMPLE, tmp_path / "extensions" / "host_storage.py")
    text = cfg.read_text().replace("general:\n", "general:\n  python_extensions: [host_storage]\n",
                                   1)
    cfg.write_text(text + extra_yaml)
    return cfg


def test_python_extension_end_to_end(lab, tmp_path, capsys):
    cfg = with_python(lab, tmp_path)
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    code, shown = run_json(capsys, "--config", str(cfg), "custom", "show", lab.agent("linux"))
    storage = shown["collectors"]["host-storage"]
    assert storage["status"] == "ok"
    assert ["31", "used_pct", "90"] in storage["table"]
    assert ["51", "kind", "virtual"] in storage["table"]
    code, listed = run_json(capsys, "--config", str(cfg), "custom", "list")
    assert {"name": "host-storage", "kind": "python", "origin": "python:host_storage"} in [
        {k: c[k] for k in ("name", "kind", "origin")} for c in listed]

    assert main(["--config", str(cfg), "report", "run", "--dataset", "py:disk-usage",
                 "--filter", "used_pct ge 85", "--columns", "device,description,used_pct"]) == 0
    assert capsys.readouterr().out.splitlines() == ["device,description,used_pct",
                                                     "backup01,/,90"]
    assert main(["--config", str(cfg), "report", "preview", "--sql",
                 "select count(*) from py_disk_usage"]) == 0
    capsys.readouterr()

    code, result = run_json(capsys, "--config", str(cfg), "export")
    assert code == 0, result
    prom = (tmp_path / "out" / "metrics" / "snowth_my_net.prom").read_text()
    assert "snowth_devices 1" in prom and 'snowth_device_ok{device="backup01"} 1' in prom
    snapshot = json.loads((tmp_path / "out" / "snapshot.json").read_text())
    assert snapshot["devices"][0]["custom"]["host-storage"]["status"] == "ok"


def test_python_extension_errors_are_configuration_errors(lab, tmp_path, capsys):
    cfg = with_python(lab, tmp_path)
    (tmp_path / "extensions" / "host_storage.py").write_text("import nothing_here\n")
    assert main(["--config", str(cfg), "custom", "list"]) == 2
    assert "import failed: ModuleNotFoundError" in capsys.readouterr().err


def hooks_yaml(recorder: Path, log: Path, extra: str = "") -> str:
    return f"""
hooks:
  after_collect:
    - name: record
      command: [{sys.executable}, {recorder}, {log}, "{{event}}", "{{status}}", "{{{{literal}}}}"]
      pass_env: [KEEP_ME]
      env: {{MODE: test}}
    - name: export-inside
      command: [{TOOL}, --config, "{{summary}}-unused", version]
    - name: only-on-failure
      when: failed
      command: [/bin/false]
  after_export:
    - name: record
      command: [{sys.executable}, {recorder}, {log}, "{{snapshot}}", "{{devices}}"]
{extra}"""


def test_hooks_run_after_the_lock_with_a_clean_environment(lab, tmp_path, capsys, monkeypatch):
    recorder, log = tmp_path / "recorder.py", tmp_path / "hooks.log"
    recorder.write_text(RECORDER)
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("linux")], files="[devices, snapshot]")
    extra = f"""    - name: nested-export
      command: [{TOOL}, --config, {cfg}, -q, export, --no-hooks]
      timeout: 60
"""
    cfg.write_text(cfg.read_text() + hooks_yaml(recorder, log, extra))
    monkeypatch.setenv("KEEP_ME", "kept")
    monkeypatch.setenv("LEAK_ME", "must-not-leak")

    code, result = run_json(capsys, "--config", str(cfg), "run", "--no-push")
    assert code == 0, result
    hooks = {(h["event"], h["name"]): h for h in result["hooks"]}
    assert hooks[("after_collect", "record")]["ok"]
    assert hooks[("after_collect", "only-on-failure")]["skipped"]
    assert hooks[("after_export", "nested-export")]["ok"], hooks   # the lock was released

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    collect, export = entries
    assert collect["argv"] == ["after_collect", "ok", "{literal}"]
    env = collect["env"]
    assert env["KEEP_ME"] == "kept" and env["MODE"] == "test" and "LEAK_ME" not in env
    assert env["SNOWTH_EVENT"] == "after_collect" and env["PATH"].startswith("/usr/local/sbin")
    assert collect["summary"]["collect"]["status"] == "ok"
    assert collect["cwd"] == str(tmp_path / "out")
    assert export["argv"] == [str(tmp_path / "out" / "snapshot.json"),
                              str(tmp_path / "out" / "devices.csv")]
    assert str(tmp_path / "out" / "devices.csv") in export["summary"]["export"]["written"]
    assert not list((tmp_path / "state").glob(".hook-*"))          # summaries are removed


def test_failing_and_slow_hooks(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("linux")])
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    cfg.write_text(cfg.read_text() + f"""
hooks:
  after_export:
    - name: fails
      command: [{sys.executable}, -c,
                "import sys; print('bad things', file=sys.stderr); sys.exit(3)"]
    - name: slow
      command: [{sys.executable}, -c, "import time; time.sleep(30)"]
      timeout: 1
    - name: fine
      command: [/bin/true]
""")
    capsys.readouterr()
    started = time.monotonic()
    code, result = run_json(capsys, "--config", str(cfg), "export")
    assert time.monotonic() - started < 15
    assert code == 1 and (tmp_path / "out" / "devices.csv").exists()
    details = {h["name"]: (h["ok"], h["detail"]) for h in result["hooks"]}
    assert details["fails"] == (False, "exit code 3: bad things")
    assert details["slow"][0] is False and "timed out after 1s" in details["slow"][1]
    assert details["fine"] == (True, "")
    assert main(["--config", str(cfg), "-q", "export", "--no-hooks"]) == 0

    assert main(["--config", str(cfg), "hooks", "test", "after_export", "fine"]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["--config", str(cfg), "hooks", "test", "after_export", "--dry-run"]) == 0
    assert "dry run: /bin/true" in capsys.readouterr().out
    assert main(["--config", str(cfg), "hooks", "list"]) == 0
    assert "after_export" in capsys.readouterr().out


def test_hook_configuration_is_validated(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("linux")])
    base = cfg.read_text()
    cfg.write_text(base + """
hooks:
  after_collect:
    - name: shell-line
      command: ["notify-send done"]
    - name: typo
      command: [/bin/echo, "{snapshot}"]
""")
    assert main(["--config", str(cfg), "hooks", "list"]) == 2
    err = capsys.readouterr().err
    assert "not a shell line" in err and "unknown placeholder {snapshot}" in err
    cfg.write_text(base + """
hooks:
  after_report:
    - name: relative
      command: [surely-not-installed-tool, "{report_file}"]
""")
    main(["--config", str(cfg), "check", "--quick", lab.agent("linux")])
    assert "surely-not-installed-tool is not found" in capsys.readouterr().out


@pytest.fixture
def python_collected(lab, tmp_path, capsys):
    cfg = with_python(lab, tmp_path)
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    return cfg


async def test_tui_shows_python_collectors(python_collected):
    from textual.widgets import DataTable, Static, TabbedContent

    from snowth_my_net.config.loader import load_config
    from snowth_my_net.tui.app import CollectorModal, SnowthApp, TuiContext

    cfg = python_collected
    ctx = TuiContext(load_config(cfg))
    app = SnowthApp(ctx)
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause()
        app.screen.query_one("#main-tabs", TabbedContent).active = "tab-extensions"
        for _ in range(3):
            await pilot.pause()
        table = app.screen.query_one("#extensions", DataTable)
        assert [str(c) for c in table.get_row_at(0)[:2]] == ["host-storage", "python"]
        table.focus()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()
        assert isinstance(app.screen, CollectorModal)
        text = str(app.screen.query_one("#collector-yaml", Static).render())
        assert "python_extension: host_storage" in text and "used_pct" in text
    ctx.close()
