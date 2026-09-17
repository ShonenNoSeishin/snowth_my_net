"""Phase 4 end to end: run (collect + export + push), health, cron print."""

from __future__ import annotations

import json

from snowth_my_net.cli import main
from tests.support.fake_push import FakeImportServer
from tests.support.lab import write_config

TOKEN = "tok-run-5d1e8b2c"


def with_push(cfg, tmp_path, url, files="[devices, nodes, links]"):
    token = tmp_path / "secrets" / "cmdb_token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    cfg.write_text(cfg.read_text() + f"""
push:
  targets:
    - name: cmdb
      url: {url}
      files: {files}
      auth: {{bearer_token_file: cmdb_token}}
      timeout: 10
""")


def test_run_collects_exports_and_pushes(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=lab.all_seeds(), files="[devices, nodes, links]")
    with FakeImportServer(token=TOKEN) as server:
        with_push(cfg, tmp_path, server.base_url + "/ok")
        code = main(["--json", "--config", str(cfg), "run"])
        result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert [(p["file"], p["ok"], p["status"]) for p in result["push"]] == [
        ("devices", True, 201), ("nodes", True, 201), ("links", True, 201)]
    names = [r.parts[0]["filename"] for r in server.posts("/ok")]
    assert names == ["devices.csv", "nodes.csv", "links.csv"]


def test_failed_export_is_not_pushed_with_an_old_file(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("printer")], files="[devices, nodes]")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "nodes.csv").write_text('"MAC Address"\r\nold,row\r\n')
    with FakeImportServer(token=TOKEN) as server:
        with_push(cfg, tmp_path, server.base_url + "/ok", files="[devices, nodes]")
        code = main(["--json", "--config", str(cfg), "run"])
        result = json.loads(capsys.readouterr().out)
    assert code == 1
    pushed = {p["file"]: p for p in result["push"]}
    assert pushed["devices"]["ok"] and not pushed["nodes"]["ok"]
    assert "export failed in this run" in pushed["nodes"]["detail"]
    assert [r.parts[0]["filename"] for r in server.posts("/ok")] == ["devices.csv"]


def test_push_command_and_dry_run(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access")], files="[devices]")
    assert main(["--config", str(cfg), "-q", "run", "--no-push"]) == 0
    capsys.readouterr()
    with FakeImportServer(token=TOKEN) as server:
        with_push(cfg, tmp_path, server.base_url + "/error", files="[devices]")
        assert main(["--config", str(cfg), "push", "--dry-run"]) == 0
        assert server.received == []
        assert main(["--config", str(cfg), "push"]) == 1
        text = capsys.readouterr().out
    assert "FAILED" in text and "HTTP 500" in text and TOKEN not in text


def test_health_and_cron_print(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access")])
    assert main(["--config", str(cfg), "health"]) == 1
    assert "no successful collect yet" in capsys.readouterr().out
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    code = main(["--json", "--config", str(cfg), "health"])
    health = json.loads(capsys.readouterr().out)
    assert code == 0 and health["healthy"] and health["max_age_s"] == 1200
    assert main(["--config", str(cfg), "collect", "--device", lab.agent("sw-access")]) == 0
    capsys.readouterr()
    assert main(["--config", str(cfg), "cron", "print", "--binary", "/usr/bin/snowth_my_net"]) == 0
    lines = capsys.readouterr().out
    assert "*/10 * * * * /usr/bin/snowth_my_net --config" in lines
