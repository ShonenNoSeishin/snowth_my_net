"""Package entry points, clock, logging, lock and the error handling of ``cli.main``."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import os
import runpy
import sys

import pytest

import snowth_my_net
from snowth_my_net import cli
from snowth_my_net.clock import Clock, FrozenClock, iso_z
from snowth_my_net.lock import LockBusy, StateLock, _read_holder
from snowth_my_net.logs import LOGGER_NAME, MASK, REDACTOR, Redactor, get_logger, setup_logging
from tests.unit.cov_cli_support import write_config

# --------------------------------------------------------------------------- package


def test_version_without_installed_metadata(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        reloaded = importlib.reload(snowth_my_net)
        assert reloaded.__version__ == "0.0.0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(snowth_my_net)
    assert snowth_my_net.__version__ != "0.0.0+unknown"


def test_python_dash_m_runs_the_cli(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["snowth_my_net", "version"])
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    sys.modules.pop("snowth_my_net.__main__", None)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("snowth_my_net", run_name="__main__")
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"snowth_my_net {snowth_my_net.__version__}\n"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"


# --------------------------------------------------------------------------- clock


def test_clocks(monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.9)
    monkeypatch.setattr("time.monotonic", lambda: 42.5)
    assert Clock().now() == 1_700_000_000 and Clock().monotonic() == 42.5
    frozen = FrozenClock(1_000)
    assert (frozen.now(), frozen.monotonic()) == (1_000, 0.0)
    frozen.advance(30)
    assert (frozen.now(), frozen.monotonic()) == (1_030, 30.0)
    assert iso_z(None) == "" and iso_z(0) == "1970-01-01T00:00:00Z"


# --------------------------------------------------------------------------- logs


def test_redactor_ignores_empty_values_and_can_be_empty():
    redactor = Redactor()
    assert redactor.redact("nothing registered") == "nothing registered"
    redactor.add("")
    assert redactor.redact("still nothing") == "still nothing"
    redactor.add("s3cret")
    redactor.add("s3cret-longer")
    assert redactor.redact("a s3cret-longer and s3cret") == f"a {MASK} and {MASK}"
    redactor.clear()
    assert redactor.redact("s3cret") == "s3cret"


def test_setup_logging_file_quiet_and_no_stderr(tmp_path, capsys):
    log_file = tmp_path / "snowth.log"
    REDACTOR.add("hunter2-cov")
    try:
        setup_logging("debug", str(log_file), quiet=True)
        root = logging.getLogger(LOGGER_NAME)
        assert [type(h).__name__ for h in root.handlers] == ["StreamHandler",
                                                              "_PrivateRotatingFileHandler"]
        get_logger("test").info("password hunter2-cov")
        get_logger("test").warning("visible")
        err = capsys.readouterr().err
        assert "visible" in err and "password" not in err            # quiet: warnings only
        text = log_file.read_text()
        assert f"password {MASK}" in text and "hunter2-cov" not in text
        assert logging.getLogger("pysnmp").level == logging.WARNING

        setup_logging("info", None, stderr_output=False)               # the TUI
        assert [type(h) for h in logging.getLogger(LOGGER_NAME).handlers] == [logging.NullHandler]
        get_logger("test").info("silent")
        assert capsys.readouterr().err == ""
    finally:
        REDACTOR.clear()
        setup_logging("info")


# --------------------------------------------------------------------------- lock


def test_lock_busy_message_without_holder_and_release_twice(tmp_path):
    busy = LockBusy(tmp_path / "state.lock", {}, 2.4)
    assert str(busy) == ("state is locked by another process; gave up after 2s "
                         f"({tmp_path}/state.lock)")
    with StateLock(tmp_path / "state.lock", "export") as lock:
        lock.acquire(0)
        lock.release()
        lock.release()                                  # no-op
        lock.acquire(0)
    assert lock._fd is None                             # released by __exit__


def test_read_holder_tolerates_garbage(tmp_path):
    path = tmp_path / "state.lock"
    path.write_text("{not json")
    fd = os.open(path, os.O_RDONLY)
    try:
        assert _read_holder(fd) == {}
    finally:
        os.close(fd)
    assert _read_holder(-1) == {}                       # OSError


# --------------------------------------------------------------------------- main()


def test_no_command_on_a_terminal_opens_the_tui(monkeypatch, tmp_path):
    cfg = write_config(tmp_path)
    monkeypatch.setenv("SNOWTH_CONFIG", str(cfg))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    opened = []
    monkeypatch.setattr("snowth_my_net.tui.app.run_tui", lambda loaded: opened.append(loaded) or 0)
    assert cli.main([]) == 0
    assert opened[0].paths.config_file == cfg


def test_tui_command_logs_away_from_the_terminal(monkeypatch, tmp_path, capsys):
    cfg = write_config(tmp_path)
    monkeypatch.setattr("snowth_my_net.tui.app.run_tui", lambda loaded: 5)
    assert cli.main(["--config", str(cfg), "tui"]) == 5
    assert [type(h) for h in logging.getLogger(LOGGER_NAME).handlers] == [logging.NullHandler]
    setup_logging("info")


def test_state_errors_exit_1(tmp_path, capsys):
    cfg = write_config(tmp_path)
    assert cli.main(["--config", str(cfg), "show", "runs"]) == 1
    assert "state: no state yet" in capsys.readouterr().err


def test_interrupt_exits_130(monkeypatch, tmp_path, capsys):
    cfg = write_config(tmp_path)

    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_version", interrupted)
    assert cli.main(["--config", str(cfg), "version"]) == 130
    assert "interrupted" in capsys.readouterr().err


def test_version_command(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.startswith("snowth_my_net ")


def test_helpers_table_json_and_redaction(capsys):
    REDACTOR.add("tok-cov-123")
    try:
        cli.out_json({"token": "tok-cov-123", "when": iso_z(0)})
        assert json.loads(capsys.readouterr().out) == {"token": MASK,
                                                        "when": "1970-01-01T00:00:00Z"}
    finally:
        REDACTOR.clear()
    assert cli.table(["A", "LONG"], [["xyz", 1]]) == "A    LONG\nxyz  1"
    assert cli.status_of(0, False) == "ok"
    assert cli.status_of(1, True) == "partial" and cli.status_of(1, False) == "failed"


def test_no_stderr_output_means_no_warning_over_the_tui(capsys):
    setup_logging("info", None, stderr_output=False)
    try:
        get_logger("tui").warning("this must not reach the terminal")
        get_logger("tui").error("nor this")
        assert capsys.readouterr().err == ""
    finally:
        setup_logging("info")
