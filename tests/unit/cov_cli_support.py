"""Shared helpers for the CLI coverage tests: a configuration and a state without SNMP."""

from __future__ import annotations

import json
from pathlib import Path

from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo

NOW = 1_790_000_000


def write_config(tmp: Path, extra: str = "", files: str = "[devices]") -> Path:
    secrets = tmp / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "token").write_text("tok-cli-cov\n")
    (secrets / "token").chmod(0o600)
    cfg = tmp / "snowth_my_net.yml"
    cfg.write_text(f"""
general:
  state_dir: {tmp / 'state'}
  output_dir: {tmp / 'out'}
  secrets_dir: {secrets}
  lock_wait: {{collect: 0, default: 0}}
credentials:
  - name: v2c
    version: 2c
    community_env: SNOWTH_COV_COMMUNITY
discovery:
  seeds: ['192.0.2.1']
  allowed: [192.0.2.0/24]
  exclude: [192.0.2.128/25]
dns:
  enabled: false
export:
  files: {files}
{extra}""")
    return cfg


def state(tmp: Path) -> Repo:
    return Repo(open_db(tmp / "state" / "state.sqlite"))


def add_device(repo: Repo, address: str = "192.0.2.1", name: str = "sw-cov", now: int = NOW,
               **fields) -> int:
    values = {"mgmt_address": address, "sys_name": name, "first_seen": now, "last_seen": now,
              "vendor": "Acme", "model": "X1", "device_type": "switch", "type_rule": "catalog",
              "last_collect_status": "ok", **fields}
    with repo.conn:
        cur = repo.conn.execute(
            f"INSERT INTO devices({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            list(values.values()))
    return int(cur.lastrowid)


def add_run(repo: Repo, finished: int, status: str = "ok", command: str = "collect") -> int:
    run_id = repo.start_run(command, finished - 10)
    repo.finish_run(run_id, status, finished, {"devices": 1, "reachable": 1})
    return run_id


def add_custom(repo: Repo, device_id: int, now: int = NOW) -> None:
    with repo.conn:
        repo.conn.execute(
            "INSERT INTO custom_runs(device_id, collector, run_at, status, rows, detail) "
            "VALUES (?, 'fw-info', ?, 'ok', 3, 'slow agent')", (device_id, now))
        repo.conn.executemany(
            "INSERT INTO custom_values(device_id, collector, idx, column, value, raw, first_seen, "
            "last_seen) VALUES (?, 'fw-info', ?, ?, ?, NULL, ?, ?)",
            [(device_id, "", "version", "7.2", now, now),
             (device_id, "1", "status", "up", now, now)])


def read_json(capsys) -> object:
    return json.loads(capsys.readouterr().out)
