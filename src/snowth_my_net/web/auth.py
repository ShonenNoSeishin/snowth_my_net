"""Login for the web interface: scrypt password hashes, sessions in memory.

The configuration never holds a password, not even hashed by accident: it points at a file (or
an environment variable) containing a hash produced by ``snowth_my_net web --hash-password``.
Sessions are renewed by use up to an absolute cap and survive a restart: the state directory
keeps a hash of each token (mode 0600), never the token.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fcntl
except ImportError:          # not a POSIX system: one process only
    fcntl = None

log = logging.getLogger(__name__)

SCHEME = "scrypt"
COST, BLOCK, PARALLEL = 2 ** 14, 8, 1      # ~100 ms and 16 MB per attempt on a small server
SALT_BYTES, TOKEN_BYTES = 16, 32
COOKIE = "snowth_session"
SESSIONS_NAME = "web_sessions.json"
MAX_FAILURES, LOCKOUT_SECONDS = 5, 60.0
RENEW_SAVE_SECONDS = 300            # a renewal reaches the file at most this often
CONFIRM_SECONDS = 15 * 60          # how long a re-typed password unlocks the SNMP page


def hash_password(password: str) -> str:
    """``scrypt$cost$block$parallel$salt$hash``, one line, safe to keep in a file."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=COST, r=BLOCK, p=PARALLEL)
    return "$".join([SCHEME, str(COST), str(BLOCK), str(PARALLEL),
                     base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    """``(cost, block, parallel, salt, digest)``, or ``None`` when the line is not a hash.

    A file mangled on its way in -- a line broken by a copy from a terminal, the prompts of the
    command pasted along with it -- parses to ``None``. The interface refuses such a file at
    startup rather than answering "wrong password" to a password that is in fact right.
    """
    try:
        scheme, cost, block, parallel, salt, digest = stored.strip().split("$")
        if scheme != SCHEME:
            return None
        return (int(cost), int(block), int(parallel),
                base64.b64decode(salt, validate=True), base64.b64decode(digest, validate=True))
    except (ValueError, TypeError):
        return None


def verify_password(password: str, stored: str) -> bool:
    """Compare in constant time; an unreadable hash is a failed attempt, never a pass."""
    parsed = parse_hash(stored)
    if parsed is None:
        return False
    cost, block, parallel, salt, expected = parsed
    try:
        computed = hashlib.scrypt(password.encode(), salt=salt, n=cost, r=block, p=parallel,
                                  dklen=len(expected))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(computed, expected)


def _locked(method):
    """The sessions are shared by every request thread: one at a time touches them. What another
    process wrote since is read first (one ``stat`` when nothing changed)."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            self._refresh()
            return method(self, *args, **kwargs)
    return wrapper


def _writes(method):
    """A change to the sessions: made on what the other processes left, one process at a time."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._writing():
            return method(self, *args, **kwargs)
    return wrapper


@dataclass
class Sessions:
    """Opaque session tokens, kept in memory and, when ``path`` is given, in a file.

    A session ends when it has been idle for ``lifetime`` seconds (every request renews that) or
    when ``max_lifetime`` seconds have passed since the login, whatever the activity. The file
    holds a hash of each token, never the token itself, so reading it signs nobody in; it lets a
    restart or a redeploy keep the people who were working. The clock is the wall clock for that
    reason: a monotonic clock means nothing after a restart.

    Several processes may share the file (two workers behind one proxy): the file is the truth.
    Every change is made while holding a lock on a sibling file, after reading what the others
    wrote, and the file is replaced atomically, so a login, a logout or a password change made by
    one process is seen by the others at their next request. What stays per process: the log's
    reason for a refusal and the login limiter (see ``LoginLimiter``).
    """

    lifetime: float                                    # idle seconds
    clock: object = time.time
    max_lifetime: float | None = None                  # absolute cap, None: no cap
    path: Path | None = None                           # None: nothing is persisted
    _open: dict[str, list] = field(default_factory=dict)    # hash -> [user, created, last seen]
    _confirmed: dict[str, float] = field(default_factory=dict)          # hash -> when
    _gone: dict[str, str] = field(default_factory=dict)     # hash -> why it ended (bounded)
    binding_of: object = None          # user -> the binding of their credential now, or None
    _saved_at: float = 0.0                             # when the file last recorded a renewal
    _stamp: tuple | None = None                        # (inode, mtime, size) of the file we read
    _depth: int = 0                                    # > 0 while the file lock is held
    _lock: threading.RLock = field(default_factory=threading.RLock)     # one thread per request

    def __post_init__(self) -> None:
        if self.max_lifetime is not None:
            self.max_lifetime = max(self.max_lifetime, self.lifetime)
        with self._writing():
            self.purge()

    @property
    def cookie_age(self) -> int:
        """``Max-Age`` of the cookie: the cap, so a closed browser keeps the session it may keep."""
        return int(self.max_lifetime if self.max_lifetime is not None else self.lifetime)

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _why(self, key: str, found: list) -> str | None:
        """``idle`` / ``cap`` when a session is over, ``None`` while it holds."""
        _user, created, last, _binding = found
        now = self.clock()
        if self.max_lifetime is not None and now >= created + self.max_lifetime:
            return "cap"
        return "idle" if now >= last + self.lifetime else None

    def _forget(self, key: str, why: str) -> None:
        self._open.pop(key, None)
        self._confirmed.pop(key, None)
        self._gone[key] = why
        while len(self._gone) > 256:
            del self._gone[next(iter(self._gone))]

    @_writes
    def open(self, user: str, binding: str | None = None) -> str:
        """The session is tied to the credential it was opened with: ``binding``, else the
        account's current one (``binding_of``), so that nobody can forget to."""
        if binding is None:
            binding = (self.binding_of(user) if self.binding_of is not None else "") or ""
        self.purge()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = self.clock()
        self._open[self._key(token)] = [user, now, now, binding]
        self._save()
        return token

    @_writes
    def confirm(self, token: str) -> None:
        """The password was typed again: what it unlocks stays open for a while, not forever."""
        key = self._key(token)
        if key in self._open:
            self._confirmed[key] = self.clock()
            self._save()

    @_locked
    def confirmed(self, token: str | None, within: float = CONFIRM_SECONDS) -> bool:
        when = self._confirmed.get(self._key(token or ""))
        return when is not None and self.clock() - when < within

    @_locked
    def user_of(self, token: str | None) -> str | None:
        if not token:
            return None
        key = self._key(token)
        found = self._open.get(key)
        if found is None:
            return None
        why = self._why(key, found)
        if why is None and self.binding_of is not None and (
                self.binding_of(found[0]) != found[3]):
            why = "closed"          # the account is gone or its password changed, by anyone
        if why:
            with self._writing():
                if key in self._open:
                    self._forget(key, why)
                    self._save()
            return None
        now = self.clock()
        found[2] = now
        if now - self._saved_at >= RENEW_SAVE_SECONDS:      # not one write per request
            with self._writing():
                again = self._open.get(key)
                if again is None:
                    return None             # closed by another process in the meantime
                again[2] = max(again[2], now)
                self._save()
        return found[0]

    @_locked
    def refusal(self, token: str | None) -> str:
        """Why a token is not a session: ``none`` (no cookie), ``unknown`` (never issued, or
        issued before a restart that kept no file), ``idle``, ``cap`` or ``closed``."""
        if not token:
            return "none"
        key = self._key(token)
        found = self._open.get(key)
        if found is not None:
            return self._why(key, found) or "valid"
        return self._gone.get(key, "unknown")

    @_writes
    def close(self, token: str | None) -> None:
        if token:
            key = self._key(token)
            if key in self._open:
                self._forget(key, "closed")
                self._save()

    @_writes
    def close_user(self, user: str, keep: str | None = None) -> int:
        """Close every session of an account but one (the one that just changed the password)."""
        spared = self._key(keep) if keep else None
        gone = [k for k, found in self._open.items() if found[0] == user and k != spared]
        for key in gone:
            self._forget(key, "closed")
        if gone:
            self._save()
        return len(gone)

    @contextlib.contextmanager
    def exclusive(self):
        """Hold every other request, in this process and in the others, off the sessions while a
        credential and its sessions are changed together: no request sees the new password with
        the old binding."""
        with self._writing():
            yield

    @staticmethod
    def bind(stored_hash: str) -> str:
        """What a session remembers of the password it was opened with."""
        return hashlib.sha256(stored_hash.encode()).hexdigest()[:16]

    @_writes
    def rebind(self, token: str, binding: str) -> None:
        """The session that changed the password follows its new credential."""
        found = self._open.get(self._key(token))
        if found is not None:
            found[3] = binding
            self._save()

    @_writes
    def purge(self) -> None:
        over = [(k, why) for k, found in self._open.items() if (why := self._why(k, found))]
        for key, why in over:
            self._forget(key, why)
        if over:
            self._save()

    @property
    def count(self) -> int:
        self.purge()
        return len(self._open)

    # ------------------------------------------------------------- persistence

    @contextlib.contextmanager
    def _writing(self):
        """The thread lock and, for a file shared with other processes, an exclusive lock on a
        sibling file; the file is read again under it, so that a change is made on what the others
        left and never over it. Re-entrant."""
        with self._lock:
            if self._depth:
                yield
                return
            handle = self._lock_file()
            self._depth += 1
            try:
                self._refresh(force=True)
                yield
            finally:
                self._depth -= 1
                if handle is not None:
                    with contextlib.suppress(OSError):
                        fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()

    def _lock_file(self):
        if self.path is None or fcntl is None:
            return None
        try:
            fd = os.open(self.path.with_name(self.path.name + ".lock"),
                         os.O_WRONLY | os.O_CREAT, 0o600)
            handle = os.fdopen(fd, "w")
            fcntl.flock(handle, fcntl.LOCK_EX)
            return handle
        except OSError as exc:
            log.debug("sessions lock unavailable (%s): this process works alone", exc)
            return None

    def _stat(self) -> tuple | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def _refresh(self, force: bool = False) -> None:
        """Adopt what another process wrote. A renewal not written yet is kept (the latest wins);
        a session the file no longer holds was closed elsewhere."""
        if self.path is None:
            return
        stamp = self._stat()
        if stamp == self._stamp and not (force and stamp is not None):
            return
        if stamp is None and self._stamp is None:
            return                          # no file, and none was ever read: memory is all
        sessions, confirmed = {}, {}
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            sessions = {k: [str(u), float(c), float(last), str(b)]
                        for k, (u, c, last, b) in payload["sessions"].items()}
            confirmed = {k: float(v) for k, v in payload.get("confirmed", {}).items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            sessions, confirmed = {}, {}    # missing or damaged: everybody signs in again
        for key, row in sessions.items():
            mine = self._open.get(key)
            if mine is not None and mine[2] > row[2]:
                row[2] = mine[2]
        for key in self._open.keys() - sessions.keys():
            self._gone.setdefault(key, "closed")
        self._open = sessions
        self._confirmed = {k: v for k, v in confirmed.items() if k in sessions}
        self._stamp = stamp

    def _save(self) -> None:
        self._saved_at = self.clock()
        if self.path is None:
            return
        payload = json.dumps({"sessions": self._open, "confirmed": self._confirmed})
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
            self._stamp = self._stat()
        except OSError as exc:
            # A file that no longer matches memory could bring a closed session back after a
            # restart: better no file at all, everybody signs in again.
            log.warning("sessions not persisted (%s); the stale file is removed", exc)
            for leftover in (tmp, self.path):
                with contextlib.suppress(OSError):
                    leftover.unlink()
            self._stamp = None


@dataclass
class LoginLimiter:
    """After a few failures, an address waits before it may try again."""

    max_failures: int = MAX_FAILURES
    lockout: float = LOCKOUT_SECONDS
    clock: object = time.monotonic
    _failures: dict[str, tuple[int, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def begin(self, address: str) -> float:
        """Reserve an attempt, atomically: seconds to wait, or 0 and the attempt is counted.

        The count is taken before the (slow) verification, so that a burst of parallel guesses
        cannot all pass a check made before any of them was recorded. A success clears it.
        """
        with self._lock:
            if len(self._failures) > 4096:               # bounded, whatever the sources
                now = self.clock()
                self._failures = {a: v for a, v in self._failures.items() if v[1] > now}
            waiting = self.locked_for(address)
            if waiting > 0:
                return waiting
            self.failed(address)
            return 0.0

    def locked_for(self, address: str) -> float:
        count, until = self._failures.get(address, (0, 0.0))
        remaining = until - self.clock()
        return remaining if count >= self.max_failures and remaining > 0 else 0.0

    def failed(self, address: str) -> None:
        count, until = self._failures.get(address, (0, 0.0))
        if self.clock() >= until:
            count = 0                                   # the previous window has expired
        self._failures[address] = (count + 1, self.clock() + self.lockout)

    def succeeded(self, address: str) -> None:
        self._failures.pop(address, None)


# Verified when an account does not exist, so that a missing account costs what a wrong password
# costs and the time says nothing about which user names exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def parse_cookie(header: str | None, name: str = COOKIE) -> str | None:
    """The value of one cookie, without importing the whole cookie machinery."""
    for part in (header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None
