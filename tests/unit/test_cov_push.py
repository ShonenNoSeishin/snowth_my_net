"""HTTP push: authentication, TLS, retries, polling and every failure, without a real server
where a scripted client is enough."""

from __future__ import annotations

import base64
import email.utils
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from snowth_my_net.config.loader import load_config
from snowth_my_net.config.secrets import SecretError
from snowth_my_net.push import http
from snowth_my_net.push.http import (
    Client,
    PushError,
    PushOutcome,
    Response,
    build_client,
    dotted,
    has_data,
    poll,
    push_all,
    push_file,
    retry_delay,
)
from tests.support.fake_push import FakeImportServer

CSV = b"a,b\r\n1,2\r\n"


def config(tmp_path: Path, targets: str, env_header: str = "") -> object:
    (tmp_path / "secrets").mkdir(exist_ok=True)
    for name, value in (("token", "tok-123456"), ("password", "pw-123456")):
        (tmp_path / "secrets" / name).write_text(value)
        (tmp_path / "secrets" / name).chmod(0o600)
    (tmp_path / "out").mkdir(exist_ok=True)
    path = tmp_path / "c.yml"
    path.write_text(f"""
general: {{state_dir: {tmp_path / 'state'}, output_dir: {tmp_path / 'out'},
          secrets_dir: {tmp_path / 'secrets'}}}
push:
  targets:
{targets}
""")
    return load_config(path)


class Scripted(Client):
    """A client whose responses (or exceptions) are scripted, recording every request."""

    def __init__(self, target, script):
        super().__init__(target, {}, opener=None, sleep=self._sleep)
        self.script, self.requests, self.sleeps = list(script), [], []

    def _sleep(self, seconds):
        self.sleeps.append(seconds)

    def request(self, method, url, body=None, extra_headers=None):
        self.requests.append((method, url))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(status=200, body=None, headers=None):
    return Response(status, headers or {}, json.dumps(body or {}).encode())


def target_of(tmp_path, extra=""):
    loaded = config(tmp_path, f"""    - name: t
      url: https://import.example/api
      files: [devices]
      retries: 2
{extra}""")
    return loaded, loaded.cfg.push.targets[0]


def csv_file(tmp_path, content=CSV, name="devices.csv"):
    path = tmp_path / "out" / name
    path.write_bytes(content)
    return path


# --------------------------------------------------------------------------- client building


def test_basic_auth_headers_and_tls_options(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSH_ORG", "acme")
    loaded = config(tmp_path, f"""    - name: basic
      url: https://import.example/api
      auth: {{basic: {{username: bob, password_file: password}}}}
      headers: {{X-Org: {{env: PUSH_ORG}}}}
      tls_verify: false
    - name: badca
      url: https://import.example/api
      ca_bundle: {tmp_path / 'missing.pem'}
    - name: plain
      url: http://import.example/api
""")
    basic, badca, plain = loaded.cfg.push.targets
    client, warnings = build_client(loaded, basic)
    assert client.headers["Authorization"] == "Basic " + base64.b64encode(
        b"bob:pw-123456").decode()
    assert client.headers["X-Org"] == "acme"
    assert warnings == ["target 'basic': TLS certificate verification is DISABLED"]
    with pytest.raises(PushError, match="cannot load ca_bundle"):
        build_client(loaded, badca)
    assert build_client(loaded, plain)[1] == []
    monkeypatch.delenv("PUSH_ORG")
    with pytest.raises(SecretError, match="PUSH_ORG is not set"):
        build_client(loaded, basic)


def test_client_request_handles_http_errors(tmp_path):
    with FakeImportServer() as server:
        loaded = config(tmp_path, f"""    - name: t
      url: {server.base_url}/missing
""")
        client, _ = build_client(loaded, loaded.cfg.push.targets[0])
        response = client.request("GET", server.base_url + "/missing")
    assert response.status == 404 and json.loads(response.body) == {}


# --------------------------------------------------------------------------- helpers


def test_retry_delay_forms():
    later = email.utils.format_datetime(datetime.now(UTC) + timedelta(seconds=40))
    past = email.utils.format_datetime(datetime.now(UTC) - timedelta(days=1))
    assert retry_delay(ok(headers={"Retry-After": " 7 "}), 0, 60) == 7
    assert retry_delay(ok(headers={"retry-after": "120"}), 0, 60) == 60
    assert 30 <= retry_delay(ok(headers={"Retry-After": later}), 0, 60) <= 40
    assert retry_delay(ok(headers={"Retry-After": past}), 0, 60) == 0
    assert retry_delay(ok(headers={"Retry-After": "soon"}), 3, 60) == 8
    assert retry_delay(None, 10, 60) == 30 and retry_delay(None, 1, 1) == 1


def test_dotted_has_data_and_response_text(tmp_path):
    assert dotted({"a": {"b": 1}}, "a.b") == 1
    assert dotted({"a": 1}, "a.b") is None and dotted({}, "x") is None
    (tmp_path / "out").mkdir()
    assert not has_data(csv_file(tmp_path, b"header\r\n"))
    assert has_data(csv_file(tmp_path, b"{}\n\n", "snapshot.json"))
    assert not has_data(csv_file(tmp_path, b"{}", "snapshot.json"))
    long = Response(200, {}, b"x\x01" * 3000)
    assert long.text(10) == "x�x�x�x�x�…"
    outcome = PushOutcome("t", "devices", True, 201, 5, "done", 1, "j", "ok")
    assert outcome.as_dict()["job_status"] == "ok"


# --------------------------------------------------------------------------- push_file


def test_unreadable_file(tmp_path):
    _loaded, target = target_of(tmp_path)
    outcome = push_file(Scripted(target, []), "devices", tmp_path / "out" / "nope.csv", False)
    assert not outcome.ok and outcome.detail.startswith("cannot read")


def test_network_errors_are_retried_then_reported(tmp_path):
    _loaded, target = target_of(tmp_path)
    client = Scripted(target, [urllib.error.URLError("refused"), TimeoutError("slow"),
                               ConnectionResetError("reset")])
    outcome = push_file(client, "devices", csv_file(tmp_path), False)
    assert not outcome.ok and outcome.attempts == 3 and outcome.detail == "network error: reset"
    assert client.sleeps == [1.0, 2.0]
    client = Scripted(target, [OSError("down"), ok(201, {"imported": 1})])
    outcome = push_file(client, "devices", csv_file(tmp_path), False)
    assert outcome.ok and outcome.attempts == 2 and outcome.status == 201


def test_413_and_other_client_errors_are_not_retried(tmp_path):
    _loaded, target = target_of(tmp_path)
    for status in (400, 401, 413):
        client = Scripted(target, [Response(status, {}, b"no")])
        outcome = push_file(client, "devices", csv_file(tmp_path), False)
        assert (outcome.ok, outcome.attempts, outcome.detail) == (False, 1, f"HTTP {status}: no")
    client = Scripted(target, [Response(502, {}, b""), Response(504, {}, b""),
                               Response(503, {}, b"still down")])
    outcome = push_file(client, "devices", csv_file(tmp_path), False)
    assert outcome.attempts == 3 and outcome.detail == "HTTP 503: still down"


# --------------------------------------------------------------------------- polling


POLL = """      wait: true
      poll: {{url: "https://import.example/jobs/{{id}}", id_field: job.id,
              status_field: status, interval: 3, timeout: {timeout}}}
"""


def accepted(job="j/1"):
    return ok(202, {"job": {"id": job}})


def test_202_without_poll_section_or_job_id(tmp_path):
    _loaded, target = target_of(tmp_path)
    outcome = push_file(Scripted(target, [accepted()]), "devices", csv_file(tmp_path), True)
    assert not outcome.ok and "no poll: section" in outcome.detail
    _loaded, target = target_of(tmp_path, POLL.format(timeout=30))
    for body in (b"not json", b"{}", json.dumps({"job": {"id": ""}}).encode()):
        outcome = push_file(Scripted(target, [Response(202, {}, body)]), "devices",
                            csv_file(tmp_path), True)
        assert not outcome.ok and outcome.detail == "HTTP 202 without 'job.id' in the JSON body"
    outcome = push_file(Scripted(target, [accepted()]), "devices", csv_file(tmp_path), False)
    assert outcome.ok and outcome.job_id is None          # not waiting: accepted is success


def test_polling_outcomes(tmp_path, monkeypatch):
    _loaded, target = target_of(tmp_path, POLL.format(timeout=30))
    client = Scripted(target, [urllib.error.URLError("blip"), ok(200, {"status": "running"}),
                               ok(200, {"status": "done"})])
    outcome = PushOutcome("t", "devices", True)
    poll(client, accepted(), outcome)
    assert client.requests[0] == ("GET", "https://import.example/jobs/j%2F1")
    assert (outcome.ok, outcome.job_id, outcome.job_status) == (True, "j/1", "done")
    assert client.sleeps == [3, 3]
    assert outcome.detail == "job j/1: done"

    outcome = PushOutcome("t", "devices", True)
    poll(Scripted(target, [ok(500)]), accepted(), outcome)
    assert (outcome.ok, outcome.detail) == (False, "job j/1: poll HTTP 500")

    outcome = PushOutcome("t", "devices", True)
    poll(Scripted(target, [ok(200, {"status": "failed"})]), accepted(), outcome)
    assert not outcome.ok and outcome.detail.startswith("job j/1: failed (")

    for unreadable in (ok(200, {}), Response(200, {}, b"garbage")):
        outcome = PushOutcome("t", "devices", True)
        poll(Scripted(target, [unreadable]), accepted(), outcome)
        assert not outcome.ok and outcome.job_status is None

    clock = iter([0, 10, 20, 40, 80])
    monkeypatch.setattr(http.time, "monotonic", lambda: next(clock))
    outcome = PushOutcome("t", "devices", True)
    poll(Scripted(target, [ok(200, {"status": "queued"}), ok(200, {"status": "queued"})]),
         accepted(), outcome)
    assert not outcome.ok and outcome.detail == "job j/1: still queued after 30s"


# --------------------------------------------------------------------------- push_all


def test_push_all_selection_and_per_target_failures(tmp_path):
    loaded = config(tmp_path, """    - name: good
      url: http://127.0.0.1:9/import
      files: [devices, nodes, links]
    - name: broken
      url: https://import.example/api
      files: [devices, nodes]
      auth: {bearer_token_env: SNOWTH_NO_SUCH_TOKEN}
""")
    csv_file(tmp_path)
    csv_file(tmp_path, name="nodes.csv")
    with pytest.raises(PushError, match="unknown push target 'nope'"):
        push_all(loaded, target_name="nope")
    outcomes, warnings = push_all(loaded, files=["devices", "nodes"], dry_run=True,
                                  available={"nodes": "export failed in this run: x"})
    by = {(o.target, o.file): o for o in outcomes}
    assert set(by) == {("good", "devices"), ("good", "nodes"), ("broken", "devices"),
                       ("broken", "nodes")}
    assert by[("good", "devices")].ok and by[("good", "devices")].detail.startswith("dry run")
    assert by[("good", "nodes")].detail == "export failed in this run: x"
    assert not by[("broken", "devices")].ok and "SNOWTH_NO_SUCH_TOKEN" in warnings[0]
    outcomes, _ = push_all(loaded, target_name="good", dry_run=True)
    assert [o.file for o in outcomes] == ["devices", "nodes", "links"]
    assert "does not exist" in outcomes[2].detail
