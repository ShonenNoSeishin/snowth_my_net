"""Where the passwords of the web interface live: one small file the tool writes itself.

A password must never travel through a clipboard. A 131-character hash pasted into an editor
over SSH is one line break away from being unreadable, and an unreadable hash looks exactly like
a wrong password. So the tool owns the file: ``web passwd`` writes it, the interface writes it
when it invents the first password, and nobody ever types a hash by hand.

The file sits beside the state (``web_accounts.json``, mode 0600) rather than in the secrets
directory, because Docker mounts secrets read-only: a password nobody can change is not a
password. It holds verifiers, never a password — losing it costs a new one, not a secret.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

STORE_NAME = "web_accounts.json"
FORMAT = 1
MIN_LENGTH = 8                                   # a password the interface will accept
ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"    # no l/1, no o/0: it is read from a log
GROUPS, GROUP_SIZE = 3, 4


@dataclass(frozen=True)
class Account:
    """One account as the interface sees it, whatever the password came from."""

    name: str
    hash: str
    must_change: bool = False
    from_file: bool = False                      # password_file/password_env: read-only here


def initial_password() -> str:
    """A password that survives being read from a log and typed back: ``k7m3-qp9x-4tvr``."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(GROUP_SIZE))
                    for _ in range(GROUPS))


class Store:
    """The password file. Every write replaces it atomically; reads never raise."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Account]:
        """What the file holds right now — it is re-read on every sign-in, so ``web passwd``
        reaches a running interface without a restart."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            users = data["users"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        found = {}
        for name, entry in users.items() if isinstance(users, dict) else ():
            if isinstance(entry, dict) and isinstance(entry.get("hash"), str):
                found[name] = Account(name, entry["hash"], bool(entry.get("must_change")))
        return found

    def set(self, name: str, password_hash: str, must_change: bool = False) -> None:
        users = {n: {"hash": a.hash, "must_change": a.must_change}
                 for n, a in self.read().items()}
        users[name] = {"hash": password_hash, "must_change": must_change}
        self._write(users)

    def forget(self, name: str) -> None:
        users = {n: {"hash": a.hash, "must_change": a.must_change}
                 for n, a in self.read().items() if n != name}
        self._write(users)

    def _write(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".new")
        text = json.dumps({"version": FORMAT, "users": users}, indent=2, sort_keys=True) + "\n"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self.path)          # never a half-written password file
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
