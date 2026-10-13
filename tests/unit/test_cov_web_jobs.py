"""Starting a collect from the interface: one job at a time, the command does the work."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.i18n import Translator
from snowth_my_net.web import jobs
from tests.unit.signed import SignedSite, cookie_of
from tests.unit.test_cov_views import build_state, make_loaded
from tests.unit.test_cov_web import FixedClock


class FakeRunner(jobs.Runner):
    """The same runner, running a harmless command instead of a collect."""

    def __init__(self, stdout: str = "{}", code: int = 0, seconds: float = 0.0) -> None:
        super().__init__("/nowhere/config.yml", timeout=10)
        self.stdout, self.code, self.seconds = stdout, code, seconds

    def argv(self, what: str, extra: tuple = ()) -> list[str]:
        script = (f"import sys,time; time.sleep({self.seconds}); "
                  f"sys.stdout.write({self.stdout!r}); sys.exit({self.code})")
        return [sys.executable, "-c", script]


def wait_for(condition, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("the job never finished")


# --------------------------------------------------------------------------- the runner


def test_a_job_runs_and_says_what_it_did():
    runner = FakeRunner('{"stats": {"devices": 4, "reachable": 3}, "errors": ["x"]}')
    job = runner.start("collect", "alice")
    assert job is not None and job.running and job.what == "collect" and job.by == "alice"
    wait_for(lambda: runner.last is not None)
    assert runner.current is None
    assert runner.last.status == "ok"
    assert runner.last.summary == "3/4 devices, 1 error(s)"
    assert runner.last.seconds(time.time()) >= 0


def test_only_one_job_at_a_time():
    runner = FakeRunner(seconds=0.4)
    assert runner.start("collect") is not None
    assert runner.start("export") is None            # refused, not queued
    wait_for(lambda: runner.current is None)
    assert runner.start("export") is not None
    wait_for(lambda: runner.current is None)


def test_an_unknown_action_is_never_started():
    runner = FakeRunner()
    assert runner.start("rm -rf") is None and runner.current is None


def test_a_command_that_fails_is_reported_as_such():
    runner = FakeRunner(stdout="boom", code=2)
    runner.start("export")
    wait_for(lambda: runner.last is not None)
    assert runner.last.status == "failed" and runner.last.exit_code == 2
    assert runner.last.summary == "boom"


def test_a_partial_collect_is_not_a_failure():
    runner = FakeRunner(stdout='{"stats": {}}', code=1)
    runner.start("collect")
    wait_for(lambda: runner.last is not None)
    assert runner.last.status == "partial"


def test_a_job_that_never_ends_is_stopped(monkeypatch):
    runner = FakeRunner()
    runner.timeout = 0

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", timeout)
    runner.start("collect")
    wait_for(lambda: runner.last is not None)
    assert runner.last.exit_code == 124 and "stopped after" in runner.last.summary


def test_a_command_that_cannot_be_started_is_reported(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    runner.start("collect")
    wait_for(lambda: runner.last is not None)
    assert runner.last.exit_code == 127 and "no" in runner.last.summary


@pytest.mark.parametrize(("what", "payload", "expected"), [
    ("export", '{"written": ["a", "b"]}', "2 file(s) written"),
    ("push", '{"results": [{"ok": true}, {"ok": false}]}', "1/2 file(s) accepted"),
    ("discover", '{"stats": {"devices": 1, "reachable": 1}}', "1/1 devices, 0 error(s)"),
    ("collect", "not json", "not json"),          # no JSON: show the last thing it said
    ("collect", "   ", ""),
])
def test_the_summary_of_each_command(what, payload, expected):
    done = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
    assert jobs.summarize(what, done) == expected


def test_the_real_command_line_is_the_one_a_reader_would_type():
    runner = jobs.Runner("/etc/snowth_my_net/config.yml", timeout=60)
    assert runner.argv("collect") == [sys.executable, "-m", "snowth_my_net", "--config",
                                      "/etc/snowth_my_net/config.yml", "--json", "collect"]
    assert runner.argv("collect", ("--device", "10.0.0.1"))[-2:] == ["--device", "10.0.0.1"]


# --------------------------------------------------------------------------- in the interface


def site_with(tmp_path, runner=None, actions: bool = True):
    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.web.actions = actions
    site = SignedSite(loaded)
    site.jobs = runner or FakeRunner()
    return site


def test_the_buttons_are_on_the_runs_page(tmp_path):
    site = site_with(tmp_path)
    page = site.respond("/runs", {}, lang="en")[2].decode()
    assert 'action="/action"' in page
    for what in ("collect", "discover", "export"):
        assert f'value="{what}"' in page
    assert 'value="push"' not in page            # no push target configured


def test_no_button_at_all_when_they_are_turned_off(tmp_path):
    site = site_with(tmp_path, actions=False)
    assert 'action="/action"' not in site.respond("/runs", {})[2].decode()
    assert site.start_job("collect", "alice")[0] == HTTPStatus.NOT_FOUND
    assert site.jobs.current is None


def test_starting_a_job_from_the_page_and_being_told_it_runs(tmp_path):
    site = site_with(tmp_path, FakeRunner(seconds=0.5))
    status, where, _body = site.start_job("collect", "alice", Translator("en"))
    assert (status, where) == (HTTPStatus.SEE_OTHER, "/runs")
    page = site.respond("/runs", {}, lang="en")[2].decode()
    assert "running for" in page and "disabled" in page
    assert 'http-equiv="refresh"' in page         # it comes back on its own
    wait_for(lambda: site.jobs.current is None)
    after = site.respond("/runs", {}, lang="en")[2].decode()
    assert "Last:" in after and 'http-equiv="refresh"' not in after


def test_a_second_job_is_refused_with_a_word_not_a_queue(tmp_path):
    site = site_with(tmp_path, FakeRunner(seconds=0.5))
    site.start_job("collect", "alice")
    status, _type, body = site.start_job("export", "alice", Translator("en"))
    assert status == HTTPStatus.CONFLICT and "already running" in body.decode()
    wait_for(lambda: site.jobs.current is None)


def test_an_action_nobody_offers_is_not_started(tmp_path):
    site = site_with(tmp_path)
    assert site.start_job("rm", "alice")[0] == HTTPStatus.NOT_FOUND
    assert site.jobs.current is None


# --------------------------------------------------------------------------- over HTTP


def serve(loaded, runner):
    import threading

    from snowth_my_net.web.server import build

    loaded.cfg.web.auth.users = loaded.cfg.web.auth.users or [WebUserCfg("alice")]
    server = build(loaded, "127.0.0.1", 0, FixedClock())
    server.site.jobs = runner
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_reader_presses_the_button(tmp_path):
    repo = build_state(tmp_path)
    repo.conn.close()
    runner = FakeRunner()
    server = serve(make_loaded(tmp_path), runner)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        form = urllib.parse.urlencode({"what": "collect"}).encode()
        request = urllib.request.Request(base + "/action", form,
                                         headers={"Cookie": cookie_of(server)})
        with urllib.request.urlopen(request) as response:
            assert response.url.endswith("/runs")
        wait_for(lambda: runner.last is not None)
        assert runner.last.what == "collect"
    finally:
        server.shutdown()
        server.server_close()


def test_pressing_it_needs_a_session_when_there_are_accounts(tmp_path):
    from snowth_my_net.config.schema import WebUserCfg

    repo = build_state(tmp_path)
    repo.conn.close()
    loaded = make_loaded(tmp_path)
    loaded.cfg.web.auth.users = [WebUserCfg("alice")]
    runner = FakeRunner()
    server = serve(loaded, runner)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        form = urllib.parse.urlencode({"what": "collect"}).encode()
        with urllib.request.urlopen(base + "/action", form) as response:
            assert response.url.endswith("/login")
        assert runner.current is None and runner.last is None
    finally:
        server.shutdown()
        server.server_close()


def test_a_running_job_says_so_before_it_is_done():
    runner = FakeRunner(seconds=0.4)
    job = runner.start("collect")
    assert job.status == "running" and job.exit_code is None
    wait_for(lambda: runner.current is None)
    assert runner.last.status == "ok"


def test_a_command_with_nothing_to_summarize_says_nothing():
    done = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    assert jobs.summarize("something-else", done) == ""
