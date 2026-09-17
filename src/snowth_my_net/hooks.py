"""Hooks: external programs run after collect, export, push or a report.

This is the ONLY module allowed to start processes (the read-only test names it). It does
nothing unless ``hooks:`` is configured, and every hook is run:

* without a shell: ``command`` is an argument list, placeholders are replaced inside each
  argument, so a value can never become a new argument or a shell construct;
* with a timeout, after which the whole process group is terminated (then killed);
* with a cleaned environment: a fixed PATH, ``LANG``, the ``SNOWTH_*`` variables describing the
  run, the literal ``env:`` values and only the variables listed in ``pass_env:``. Secrets read
  by snowth_my_net are never passed;
* after the state lock is released, so a hook may itself call snowth_my_net.

A failing hook is reported (exit code 1) and never stops the other hooks.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess  # the one sanctioned use, see the module docstring
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.schema import HOOK_EVENT_FIELDS, HookCfg, hook_placeholders
from snowth_my_net.logs import REDACTOR, get_logger

log = get_logger("hooks")
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
OUTPUT_LIMIT = 64 * 1024
KILL_GRACE_S = 5.0


@dataclass
class HookResult:
    event: str
    name: str
    ok: bool
    returncode: int | None = None
    duration_ms: int = 0
    detail: str = ""
    skipped: bool = False

    def as_dict(self) -> dict:
        return {"event": self.event, "name": self.name, "ok": self.ok,
                "returncode": self.returncode, "duration_ms": self.duration_ms,
                "detail": self.detail, "skipped": self.skipped}


def placeholder_values(loaded: LoadedConfig, event: str, status: str, run_id: int | None,
                       summary: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    out = loaded.paths.output_dir
    values = {"event": event, "status": status, "run_id": "" if run_id is None else str(run_id),
              "output_dir": str(out), "state_dir": str(loaded.paths.state_dir),
              "summary": str(summary)}
    if HOOK_EVENT_FIELDS[event][:1] == ("devices",):
        values |= {"devices": str(out / "devices.csv"), "nodes": str(out / "nodes.csv"),
                   "links": str(out / "links.csv"), "snapshot": str(out / "snapshot.json")}
    return values | (extra or {})


def expand(argument: str, values: dict[str, str]) -> str:
    result = argument.replace("{{", "\x00").replace("}}", "\x01")
    for name in hook_placeholders(argument):
        result = result.replace("{" + name + "}", values.get(name, ""))
    return result.replace("\x00", "{").replace("\x01", "}")


def hook_environment(loaded: LoadedConfig, hook: HookCfg, event: str, status: str,
                     run_id: int | None, summary: Path) -> dict[str, str]:
    env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "HOME": str(loaded.paths.state_dir)}
    for name in ("TZ",):
        if name in os.environ:
            env[name] = os.environ[name]
    for name in hook.pass_env:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update(hook.env)
    env.update({"SNOWTH_EVENT": event, "SNOWTH_STATUS": status,
                "SNOWTH_RUN_ID": "" if run_id is None else str(run_id),
                "SNOWTH_OUTPUT_DIR": str(loaded.paths.output_dir),
                "SNOWTH_SUMMARY": str(summary)})
    return env


def _tail(data: bytes, limit: int = 2000) -> str:
    text = data.decode("utf-8", errors="replace").strip()
    if len(text) > limit:
        text = "…" + text[-limit:]
    return REDACTOR.redact(text)


def _terminate(process: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, None)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, sig)
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run_hook(loaded: LoadedConfig, event: str, hook: HookCfg, status: str,
             run_id: int | None, summary: Path, extra: dict[str, str] | None = None,
             dry_run: bool = False) -> HookResult:
    values = placeholder_values(loaded, event, status, run_id, summary, extra)
    argv = [expand(a, values) for a in hook.command]
    result = HookResult(event, hook.name, ok=False)
    if dry_run:
        result.ok, result.detail = True, "dry run: " + " ".join(argv)
        return result
    env = hook_environment(loaded, hook, event, status, run_id, summary)
    cwd = loaded.paths.output_dir if loaded.paths.output_dir.is_dir() else None
    start = time.monotonic()
    try:
        process = subprocess.Popen(  # noqa: S603 — argv list, no shell
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=cwd, start_new_session=True, close_fds=True)
    except OSError as exc:
        result.detail = f"cannot start {argv[0]}: {exc.strerror or exc}"
        return result
    try:
        stdout, stderr = process.communicate(timeout=hook.timeout)
    except subprocess.TimeoutExpired:
        _terminate(process)
        with contextlib.suppress(Exception):
            process.communicate(timeout=1)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        result.detail = f"timed out after {hook.timeout}s (process group terminated)"
        return result
    result.duration_ms = int((time.monotonic() - start) * 1000)
    result.returncode = process.returncode
    result.ok = process.returncode == 0
    for line in _tail(stdout[:OUTPUT_LIMIT]).splitlines():
        log.debug("hook %s: %s", hook.name, line)
    if not result.ok:
        result.detail = (f"exit code {process.returncode}" if process.returncode >= 0
                         else f"killed by signal {-process.returncode}")
        tail = _tail(stderr[-OUTPUT_LIMIT:], 500)
        if tail:
            result.detail += f": {tail}"
    return result


def run_hooks(loaded: LoadedConfig, event: str, status: str, payload: dict,
              run_id: int | None = None, extra: dict[str, str] | None = None,
              only: str | None = None, dry_run: bool = False) -> list[HookResult]:
    """Run the hooks of an event in order. ``status`` is ok, partial or failed."""
    hooks = [h for h in loaded.cfg.hooks.events()[event] if only in (None, h.name)]
    if not hooks:
        return []
    results: list[HookResult] = []
    loaded.paths.state_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".hook-{event}-", suffix=".json",
                                dir=loaded.paths.state_dir)
    summary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"event": event, "status": status, "run_id": run_id, **payload}, handle,
                      indent=2, default=str)
        os.chmod(summary, 0o644)            # hooks may run as another user (sudo -u …)
        for hook in hooks:
            if (hook.when == "ok" and status != "ok") or (hook.when == "failed"
                                                           and status == "ok"):
                results.append(HookResult(event, hook.name, ok=True, skipped=True,
                                          detail=f"skipped (when: {hook.when})"))
                continue
            result = run_hook(loaded, event, hook, status, run_id, summary, extra, dry_run)
            results.append(result)
            if result.ok:
                log.info("hook %s (%s): ok in %d ms", hook.name, event, result.duration_ms)
            else:
                log.warning("hook %s (%s) failed: %s", hook.name, event, result.detail)
    finally:
        with contextlib.suppress(FileNotFoundError):
            summary.unlink()
    return results


def failed(results: list[HookResult]) -> bool:
    return any(not r.ok for r in results)
