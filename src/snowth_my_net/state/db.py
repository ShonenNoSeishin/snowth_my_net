"""SQLite state: connection helpers and numbered migrations (``PRAGMA user_version``)."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 5


class StateError(Exception):
    pass


def open_db(path: Path, readonly: bool = False) -> sqlite3.Connection:
    """Open the state database. Read-only mode never creates, migrates or waits for writers."""
    if readonly:
        if not path.exists():
            raise StateError(f"no state yet at {path} (run 'collect' first)")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if readonly:
            if version < SCHEMA_VERSION:
                raise StateError(f"state schema v{version} at {path} is older than this version "
                                 f"(v{SCHEMA_VERSION}); run any writing command (e.g. collect) "
                                 "to upgrade it")
            if version > SCHEMA_VERSION:
                raise StateError(f"state schema v{version} at {path} is newer than this version "
                                 f"of snowth_my_net (v{SCHEMA_VERSION}); upgrade the tool")
        else:
            migrate(conn, version)
    except BaseException:
        conn.close()              # never leave a connection (and its file handle) behind
        raise
    return conn


def migrate(conn: sqlite3.Connection, current: int) -> None:
    if current > SCHEMA_VERSION:
        raise StateError(
            f"state schema v{current} is newer than this version of snowth_my_net "
            f"(v{SCHEMA_VERSION}); upgrade the tool"
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        script = resources.files("snowth_my_net.state").joinpath(f"schema_v{version}.sql")
        with conn:
            conn.executescript(script.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {version}")
