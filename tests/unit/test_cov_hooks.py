"""Hooks runner: placeholders, environment, failures, signals and timeouts."""

from __future__ import annotations

import json
import sys
import time

from snowth_my_net import hooks
from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.config.schema import HookCfg
from snowth_my_net.logs import REDACTOR

PY = sys.executable


def loaded_with(tmp_path, hooks_yaml: str = "") -> LoadedConfig:
    cfg = parse_config_text(hooks_yaml)
    out = tmp_path / "out"
    return LoadedConfig(cfg, Paths(tmp_path / "c.yml", tmp_path / "state", out, tmp_path))


def test_placeholders_and_literal_braces(tmp_path):
    loaded = loaded_with(tmp_path)
    summary = tmp_path / "s.json"
    values = hooks.placeholder_values(loaded, "after_collect", "ok", None, summary)
    assert values["run_id"] == "" and "devices" not in values
    values = hooks.placeholder_values(loaded, "after_push", "partial", 7, summary,
                                      {"extra": "x"})
    assert values["devices"].endswith("out/devices.csv") and values["run_id"] == "7"
    assert hooks.expand("{status}-{{status}}-{unknown}{extra}", values) == \
        "partial-{status}-x"


def test_environment_is_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Brussels")
    monkeypatch.setenv("WANTED", "yes")
    monkeypatch.setenv("SECRETISH", "no")
    hook = HookCfg("h", ["/bin/true"], env={"MODE": "x"}, pass_env=["WANTED", "ABSENT_VAR"])
    env = hooks.hook_environment(loaded_with(tmp_path), hook, "after_export", "ok", 3,
                                 tmp_path / "s.json")
    assert env["TZ"] == "Europe/Brussels" and env["WANTED"] == "yes" and env["MODE"] == "x"
    assert "SECRETISH" not in env and "ABSENT_VAR" not in env
    assert env["SNOWTH_RUN_ID"] == "3" and env["PATH"] == hooks.SAFE_PATH
    monkeypatch.delenv("TZ")
    assert "TZ" not in hooks.hook_environment(loaded_with(tmp_path), hook, "after_export", "ok",
                                              None, tmp_path / "s.json")


def test_tail_truncates_and_redacts():
    REDACTOR.add("hunter2-secret")
    text = hooks._tail(("x" * 3000 + " hunter2-secret").encode(), limit=100)
    assert text.startswith("…") and "hunter2-secret" not in text and len(text) < 120


def run(tmp_path, command, timeout=10, dry_run=False, **kwargs):
    hook = HookCfg("h", command, timeout=timeout, **kwargs)
    return hooks.run_hook(loaded_with(tmp_path), "after_export", hook, "ok", None,
                          tmp_path / "s.json", dry_run=dry_run)


def test_run_hook_results(tmp_path):
    missing = run(tmp_path, [str(tmp_path / "no-such-program")])
    assert not missing.ok and missing.detail.startswith("cannot start")
    assert missing.returncode is None
    dry = run(tmp_path, ["/bin/echo", "{devices}"], dry_run=True)
    assert dry.ok and dry.detail == f"dry run: /bin/echo {tmp_path / 'out' / 'devices.csv'}"
    killed = run(tmp_path, [PY, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
    assert (killed.ok, killed.detail) == (False, "killed by signal 9")
    quiet_fail = run(tmp_path, [PY, "-c", "raise SystemExit(4)"])
    assert quiet_fail.detail == "exit code 4" and quiet_fail.returncode == 4
    loud = run(tmp_path, [PY, "-c", "import sys; sys.exit('went wrong')"])
    assert loud.detail == "exit code 1: went wrong"
    fine = run(tmp_path, [PY, "-c", "print('hello')"])
    assert fine.ok and fine.detail == "" and fine.duration_ms >= 0
    assert fine.as_dict() == {"event": "after_export", "name": "h", "ok": True,
                              "returncode": 0, "duration_ms": fine.duration_ms, "detail": "",
                              "skipped": False}


def test_timeout_escalates_to_sigkill(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "KILL_GRACE_S", 0.3)
    script = ("import signal, time, sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
              "print('ready', flush=True); time.sleep(30)")
    started = time.monotonic()
    result = run(tmp_path, [PY, "-c", script], timeout=1)
    assert not result.ok and "timed out after 1s" in result.detail
    assert time.monotonic() - started < 10


def test_terminate_tolerates_a_process_already_gone():
    class Gone:
        pid = 2 ** 22 + 12345

        def wait(self, timeout):
            return 0

    hooks._terminate(Gone())


def test_run_hooks_order_when_and_summary(tmp_path):
    record = tmp_path / "record.txt"
    script = tmp_path / "record.py"
    script.write_text("import json, os, sys\n"
                      "summary = json.load(open(os.environ['SNOWTH_SUMMARY']))\n"
                      "open(sys.argv[1], 'a').write(json.dumps(summary) + '\\n')\n")
    loaded = loaded_with(tmp_path, f"""
hooks:
  after_export:
    - name: first
      command: [{PY}, "{script}", "{record}"]
    - name: only-ok
      when: ok
      command: [/bin/false]
    - name: only-failed
      when: failed
      command: [/bin/false]
""")
    assert hooks.run_hooks(loaded, "after_export", "ok", {"x": 1}, only="nothing") == []
    assert hooks.run_hooks(loaded, "after_collect", "ok", {}) == []
    results = hooks.run_hooks(loaded, "after_export", "partial", {"export": {"written": []}},
                              run_id=4)
    assert [(r.name, r.ok, r.skipped) for r in results] == [
        ("first", True, False), ("only-ok", True, True), ("only-failed", False, False)]
    assert hooks.failed(results) and not hooks.failed(results[:2])
    summary = json.loads(record.read_text())
    assert summary == {"event": "after_export", "status": "partial", "run_id": 4,
                       "export": {"written": []}}
    assert not list((tmp_path / "state").glob(".hook-*"))
    ok_results = hooks.run_hooks(loaded, "after_export", "ok", {}, only="only-ok")
    assert [(r.ok, r.skipped) for r in ok_results] == [(False, False)]
