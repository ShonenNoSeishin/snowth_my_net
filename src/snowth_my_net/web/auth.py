"""Login for the web interface: scrypt password hashes, sessions in memory.

The configuration never holds a password, not even hashed by accident: it points at a file (or
an environment variable) containing a hash produced by ``snowth_my_net web --hash-password``.
Sessions live in the process, so restarting the interface logs everybody out — there is no
session store to secure and nothing to clean up.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

SCHEME = "scrypt"
COST, BLOCK, PARALLEL = 2 ** 14, 8, 1      # ~100 ms and 16 MB per attempt on a small server
SALT_BYTES, TOKEN_BYTES = 16, 32
COOKIE = "snowth_session"
MAX_FAILURES, LOCKOUT_SECONDS = 5, 60.0
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
    """The sessions are shared by every request thread: one at a time touches them."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass
class Sessions:
    """Opaque session tokens with an expiry, kept in memory."""

    lifetime: float                                    # seconds
    clock: object = time.monotonic
    _open: dict[str, tuple[str, float]] = field(default_factory=dict)   # token -> (user, until)
    _confirmed: dict[str, float] = field(default_factory=dict)          # token -> when
    _lock: threading.RLock = field(default_factory=threading.RLock)     # one thread per request

    @_locked
    def open(self, user: str) -> str:
        self.purge()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._open[token] = (user, self.clock() + self.lifetime)
        return token

    @_locked
    def confirm(self, token: str) -> None:
        """The password was typed again: what it unlocks stays open for a while, not forever."""
        self._confirmed[token] = self.clock()

    @_locked
    def confirmed(self, token: str | None, within: float = CONFIRM_SECONDS) -> bool:
        when = self._confirmed.get(token or "")
        return when is not None and self.clock() - when < within

    @_locked
    def user_of(self, token: str | None) -> str | None:
        if not token:
            return None
        found = self._open.get(token)
        if found is None:
            return None
        user, until = found
        if self.clock() >= until:
            del self._open[token]
            return None
        return user

    @_locked
    def close(self, token: str | None) -> None:
        if token:
            self._open.pop(token, None)
            self._confirmed.pop(token, None)

    @_locked
    def close_user(self, user: str, keep: str | None = None) -> int:
        """Close every session of an account but one (the one that just changed the password)."""
        gone = [t for t, (who, _until) in self._open.items() if who == user and t != keep]
        for token in gone:
            del self._open[token]
            self._confirmed.pop(token, None)
        return len(gone)

    @_locked
    def purge(self) -> None:
        now = self.clock()
        for token in [t for t, (_user, until) in self._open.items() if now >= until]:
            del self._open[token]
            self._confirmed.pop(token, None)

    @property
    def count(self) -> int:
        self.purge()
        return len(self._open)


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
