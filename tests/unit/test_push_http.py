import json

import pytest

from snowth_my_net.config.loader import LoadedConfig, Paths, parse_config_text
from snowth_my_net.logs import setup_logging
from snowth_my_net.push.http import Response, multipart_body, push_all, retry_delay
from tests.support.fake_push import FakeImportServer

TOKEN = "tok-3f9a1c77e2"


def loaded(tmp_path, url, extra="", files="[devices, nodes]"):
    (tmp_path / "secrets").mkdir(exist_ok=True)
    token = tmp_path / "secrets" / "token"
    token.write_bytes(b"\xef\xbb\xbf" + TOKEN.encode() + b"\r\n")
    token.chmod(0o600)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "devices.csv").write_text('"Device Name"\r\nsw1\r\n')
    (out / "nodes.csv").write_text('"MAC Address"\r\n00:00:5e:00:53:01\r\n')
    cfg = parse_config_text(f"""
push:
  targets:
    - name: cmdb
      url: {url}
      files: {files}
      auth: {{bearer_token_file: token}}
      extra_fields: {{org: acme}}
      timeout: 5
{extra}
""")
    return LoadedConfig(cfg, Paths(tmp_path / "c.yml", tmp_path, out, tmp_path / "secrets"))


def by_file(outcomes):
    return {o.file: o for o in outcomes}


def test_files_are_posted_in_order_as_multipart(tmp_path):
    with FakeImportServer(token=TOKEN) as server:
        outcomes, warnings = push_all(loaded(tmp_path, server.base_url + "/ok?org=acme"))
    assert [(o.file, o.ok, o.status) for o in outcomes] == [("devices", True, 201),
                                                            ("nodes", True, 201)]
    assert warnings == []
    first, second = server.posts("/ok")
    assert first.parts[1]["filename"] == "devices.csv"
    assert second.parts[1]["filename"] == "nodes.csv"
    assert first.parts[0] == {"name": "org", "filename": None, "content_type": "text/plain",
                              "content": b"acme"}
    assert first.parts[1]["name"] == "file" and first.parts[1]["content_type"] == "text/csv"
    assert first.parts[1]["content"] == b'"Device Name"\r\nsw1\r\n'


def test_202_is_polled_until_done_and_failures_are_reported(tmp_path):
    poll = """      wait: true
      poll:
        url: {base}/jobs/{{id}}
        id_field: data.job.id
        status_field: state.status
        interval: 0
        timeout: 5"""
    with FakeImportServer(token=TOKEN) as server:
        ok = loaded(tmp_path, server.base_url + "/async", poll.format(base=server.base_url),
                    files="[devices]")
        [outcome], _ = push_all(ok, sleep=lambda s: None)
        assert (outcome.ok, outcome.job_id, outcome.job_status) == (True, "job-1", "done")
        failing = loaded(tmp_path, server.base_url + "/async-fail",
                         poll.format(base=server.base_url), files="[devices]")
        [outcome], _ = push_all(failing, sleep=lambda s: None)
        assert not outcome.ok and "failed" in outcome.detail
        [no_wait], _ = push_all(ok, wait=False)
        assert no_wait.ok and no_wait.job_id is None


@pytest.mark.parametrize("path, status, retried", [
    ("/unauthorized-token", 401, False), ("/error", 500, False), ("/toolarge", 413, False)])
def test_errors_do_not_stop_the_next_file(tmp_path, path, status, retried):
    with FakeImportServer(token=TOKEN) as server:
        cfg = loaded(tmp_path, server.base_url + path, "      retries: 2")
        if path == "/unauthorized-token":
            (tmp_path / "secrets" / "token").write_text("wrong")
            path = "/ok"
            cfg.cfg.push.targets[0].url = server.base_url + path
        outcomes, _ = push_all(cfg, sleep=lambda s: None)
    assert [(o.ok, o.status, o.attempts) for o in outcomes] == [(False, status, 1)] * 2
    assert len(server.posts(path)) == 2


def test_retry_on_429_and_503_only(tmp_path):
    with FakeImportServer(token=TOKEN) as server:
        for path in ("/ratelimit", "/flaky"):
            cfg = loaded(tmp_path, server.base_url + path, "      retries: 1", files="[devices]")
            [outcome], _ = push_all(cfg, sleep=lambda s: None)
            assert (outcome.ok, outcome.status, outcome.attempts) == (True, 201, 2), path


def test_redirects_are_not_followed(tmp_path):
    with FakeImportServer(token=TOKEN) as server:
        [outcome], _ = push_all(loaded(tmp_path, server.base_url + "/redirect", files="[devices]"))
    assert not outcome.ok and "elsewhere.example" in outcome.detail
    assert len(server.received) == 1


def test_self_signed_certificate(tmp_path):
    with FakeImportServer(token=TOKEN, tls_dir=tmp_path) as server:
        url = server.base_url + "/ok"
        [refused], _ = push_all(loaded(tmp_path, url, files="[devices]"))
        assert not refused.ok and "CERTIFICATE_VERIFY_FAILED" in refused.detail
        [trusted], _ = push_all(loaded(tmp_path, url, f"      ca_bundle: {server.cert}",
                                       files="[devices]"))
        assert trusted.ok
        [insecure], warnings = push_all(loaded(tmp_path, url, "      tls_verify: false",
                                               files="[devices]"))
        assert insecure.ok and any("DISABLED" in w for w in warnings)


def test_empty_or_missing_files_are_never_sent(tmp_path):
    with FakeImportServer(token=TOKEN) as server:
        cfg = loaded(tmp_path, server.base_url + "/ok")
        (tmp_path / "out" / "devices.csv").write_text('"Device Name"\r\n')
        (tmp_path / "out" / "nodes.csv").unlink()
        outcomes = by_file(push_all(cfg)[0])
    assert "no data row" in outcomes["devices"].detail
    assert "does not exist" in outcomes["nodes"].detail
    assert server.received == []


def test_token_never_logged_and_group_readable_file_warns(tmp_path, capsys):
    setup_logging("debug")
    with FakeImportServer(token=TOKEN) as server:
        cfg = loaded(tmp_path, server.base_url + "/error", files="[devices]")
        (tmp_path / "secrets" / "token").chmod(0o644)
        _outcomes, warnings = push_all(cfg)
    assert any("readable by group/others" in w for w in warnings)
    assert TOKEN not in capsys.readouterr().err


def test_helpers():
    body, content_type = multipart_body("file", "a.csv", b"x", "text/csv", {})
    boundary = content_type.split("boundary=")[1]
    assert body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(
        f"--{boundary}--\r\n".encode())
    assert retry_delay(Response(429, {"Retry-After": "7"}, b""), 0, 60) == 7
    assert retry_delay(Response(429, {"Retry-After": "999"}, b""), 0, 60) == 60
    assert retry_delay(None, 3, 60) == 8
    assert json.loads(json.dumps({"ok": True}))
