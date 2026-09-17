"""Compose test profile: collect from simulator containers, push over HTTPS to a fake server.

Runs only inside ``docker compose --profile test run --rm tests`` (SNOWTH_COMPOSE_TEST=1).
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from pathlib import Path

import pytest

from snowth_my_net.cli import main
from tests.support.lab import COMMUNITY, V3_AUTH, V3_PRIV, V3_USER

pytestmark = pytest.mark.skipif(os.environ.get("SNOWTH_COMPOSE_TEST") != "1",
                                reason="only in the compose test profile")
CERT = Path("/certs/cert.pem")
PUSH = "https://172.31.250.30:8443"
TOKEN = "compose-test-token"


def wait_for_certificate(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not CERT.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert CERT.exists(), "the fake push server did not create its certificate"


def received() -> list[dict]:
    context = ssl.create_default_context(cafile=str(CERT))
    with urllib.request.urlopen(PUSH + "/_received", context=context, timeout=10) as response:
        return json.loads(response.read())["received"]


def test_collect_export_push_through_the_stack(tmp_path, capsys):
    wait_for_certificate()
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name, value in (("v3_auth", V3_AUTH), ("v3_priv", V3_PRIV), ("community", COMMUNITY),
                        ("token", TOKEN)):
        (secrets / name).write_text(value)
        (secrets / name).chmod(0o600)
    cfg = tmp_path / "config.yml"
    cfg.write_text(f"""
general:
  state_dir: {tmp_path / 'state'}
  output_dir: {tmp_path / 'out'}
  secrets_dir: {secrets}
  snmp: {{port: 1161, timeout: 2, retries: 2, probe_timeout: 2}}
credentials:
  - {{name: v3, version: 3, username: {V3_USER}, auth_protocol: sha256, auth_key_file: v3_auth,
      priv_protocol: aes128, priv_key_file: v3_priv}}
  - {{name: v2c, version: 2c, community_file: community}}
discovery:
  seeds: [172.31.250.11, 172.31.250.21]
  allowed: [172.31.250.0/24]
dns: {{enabled: false}}
export: {{files: [devices, nodes, links]}}
push:
  targets:
    - name: fake
      url: {PUSH}/ok
      files: [devices, nodes, links]
      auth: {{bearer_token_file: token}}
      ca_bundle: {CERT}
""")
    for _ in range(30):                          # simulators may still be indexing
        if main(["--config", str(cfg), "-q", "check", "--quick"]) == 0:
            break
        time.sleep(2)
    capsys.readouterr()
    code = main(["--json", "--config", str(cfg), "run"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert [p["ok"] for p in result["push"]] == [True, True, True]
    links = (tmp_path / "out" / "links.csv").read_text()
    assert "sw-access-01,1/1/12,sw-cisco-03,Gi1/0/4,LLDP+CDP" in links
    files = [f for r in received() if r["path"] == "/ok" for f in r["files"]]
    assert files[-3:] == ["devices.csv", "nodes.csv", "links.csv"]
