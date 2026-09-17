"""Secrets: read from files or environment variables, never from the YAML itself.

A :class:`Secret` never shows its value in ``repr``/``str`` and registers the value with the
log redactor as soon as it is loaded.
"""

from __future__ import annotations

import os
from pathlib import Path

from snowth_my_net.logs import REDACTOR

BOM = "﻿"


class SecretError(Exception):
    """A secret reference cannot be resolved (missing file, unset variable, empty value)."""


class Secret:
    __slots__ = ("_value", "source")

    def __init__(self, value: str, source: str) -> None:
        if not value:
            raise SecretError(f"secret from {source} is empty")
        self._value = value
        self.source = source
        REDACTOR.add(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"<Secret from {self.source}>"

    __str__ = __repr__

    def __reduce__(self) -> tuple:
        raise TypeError("secrets cannot be pickled")


def _clean(text: str) -> str:
    # UTF-8 BOM (Windows editors) and surrounding whitespace / CR / LF are never part of a secret.
    return text.removeprefix(BOM).strip()


def read_secret_file(path: Path) -> tuple[str, list[str]]:
    """Return ``(value, warnings)``; warns when the file is readable by group or others."""
    try:
        raw = path.read_bytes()
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise SecretError(f"cannot read secret file {path}: {exc.strerror}") from None
    try:
        value = _clean(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise SecretError(f"secret file {path} is not valid UTF-8") from None
    if not value:
        raise SecretError(f"secret file {path} is empty")
    warnings = []
    if mode & 0o077:
        warnings.append(
            f"secret file {path} is readable by group/others (mode {mode:04o}); "
            "chmod 600 is recommended"
        )
    return value, warnings


def resolve_secret(
    file: str | None, env: str | None, base_dir: Path, what: str
) -> tuple[Secret, list[str]]:
    """Resolve a ``*_file`` / ``*_env`` pair. Relative files are read from ``base_dir``."""
    if file and env:
        raise SecretError(f"{what}: set either the _file or the _env form, not both")
    if file:
        path = Path(file).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        value, warnings = read_secret_file(path)
        return Secret(value, f"file {path}"), warnings
    if env:
        raw = os.environ.get(env)
        if raw is None:
            raise SecretError(f"{what}: environment variable {env} is not set")
        value = _clean(raw)
        if not value:
            raise SecretError(f"{what}: environment variable {env} is empty")
        return Secret(value, f"env {env}"), []
    raise SecretError(f"{what}: missing (use the _file or the _env form)")
