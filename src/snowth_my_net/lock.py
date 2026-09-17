"""Exclusive lock on the state, held for the whole duration of a writing command.

``flock`` is released by the kernel when the process dies, so a crash never leaves a stale
lock behind. It works between the host and containers sharing the same local directory; it is
not reliable on NFS/CIFS, which is why the state must live on a local disk.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from pathlib import Path

from snowth_my_net.clock import iso_z


class LockBusy(Exception):
    """Another run held the lock for longer than the allowed wait."""

    def __init__(self, path: Path, holder: dict, waited: float) -> None:
        self.path = path
        self.holder = holder
        self.waited = waited
        who = "another process"
        if holder:
            since = iso_z(holder.get("started_at"))
            who = f"pid {holder.get('pid')} ({holder.get('command')}) since {since}"
        super().__init__(f"state is locked by {who}; gave up after {waited:.0f}s ({path})")


class StateLock:
    def __init__(self, path: Path, command: str) -> None:
        self.path = path
        self.command = command
        self._fd: int | None = None

    def acquire(self, wait: float) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                waited = time.monotonic() - start
                if waited >= wait:
                    holder = _read_holder(fd)
                    os.close(fd)
                    raise LockBusy(self.path, holder, waited) from None
                time.sleep(min(1.0, max(0.05, wait - waited)))
        info = {"pid": os.getpid(), "command": self.command, "started_at": int(time.time())}
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps(info).encode(), 0)
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        with contextlib.suppress(OSError):
            os.ftruncate(self._fd, 0)
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> StateLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _read_holder(fd: int) -> dict:
    try:
        data = os.pread(fd, 4096, 0)
        return json.loads(data) if data else {}
    except (OSError, ValueError):
        return {}
