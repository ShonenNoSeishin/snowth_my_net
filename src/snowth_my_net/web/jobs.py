"""Running a collect (or a discovery, an export, a push) from the interface.

The interface does not do the work itself: it starts the same command anyone would type, as a
separate process, and watches it. Nothing is duplicated — the state lock, the hooks, the exit
codes and the report are the command's own — a crash cannot take the server down with it, and
the scheduler running at the same time simply waits for the lock like any other writer.

One job at a time: a second request is refused rather than queued, because two collects at once
would only fight over that lock.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from snowth_my_net.logs import get_logger

log = get_logger("web")

ACTIONS = ("collect", "discover", "export", "push", "names")
GRACE = 30                                       # seconds added to the run timeout, to kill it


@dataclass
class Job:
    """What is running, or what ran last."""

    what: str
    by: str                                      # who asked, "" when there is no account
    started_at: float
    extra: tuple[str, ...] = ()                  # e.g. ("--device", "10.0.0.1"): one address
    finished_at: float | None = None
    exit_code: int | None = None
    summary: str = ""

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def status(self) -> str:
        if self.running:
            return "running"
        return {0: "ok", 1: "partial"}.get(self.exit_code or 0, "failed")

    def seconds(self, now: float) -> int:
        return int((self.finished_at or now) - self.started_at)


@dataclass
class Runner:
    """Starts one job at a time and remembers the last one for the next page."""

    config_file: str
    timeout: float
    current: Job | None = None
    last: Job | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, what: str, by: str = "", clock=time.time,
              extra: tuple[str, ...] = ()) -> Job | None:
        """The job that was started, or ``None`` when one is already running."""
        if what not in ACTIONS:
            return None
        with self._lock:
            if self.current is not None:
                return None
            job = Job(what, by, clock(), tuple(extra))
            self.current = job
        log.info("%s%s started from the web interface by %s", what,
                 " " + " ".join(job.extra) if job.extra else "", by or "an anonymous reader")
        threading.Thread(target=self._run, args=(job, clock), daemon=True).start()
        return job

    def argv(self, what: str, extra: tuple[str, ...] = ()) -> list[str]:
        """The command line a reader would have typed, run without a shell."""
        words = ["names", "ask"] if what == "names" else [what]     # the command has an action
        return [sys.executable, "-m", "snowth_my_net", "--config", self.config_file,
                "--json", *words, *extra]

    def _run(self, job: Job, clock) -> None:
        argv = self.argv(job.what, job.extra)
        try:
            done = subprocess.run(argv, capture_output=True, text=True,        # noqa: S603
                                  timeout=self.timeout + GRACE, check=False)
            job.exit_code, job.summary = done.returncode, summarize(job.what, done)
        except subprocess.TimeoutExpired:
            job.exit_code, job.summary = 124, f"stopped after {int(self.timeout + GRACE)} s"
        except OSError as exc:                   # the command could not even be started
            job.exit_code, job.summary = 127, str(exc)
        finally:
            job.finished_at = clock()
            with self._lock:
                self.current, self.last = None, job
            log.info("%s from the web interface: %s (%s)", job.what, job.status, job.summary)


def summarize(what: str, done: subprocess.CompletedProcess) -> str:
    """One line for a reader: what the command reports, never a dump of its output."""
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        return (done.stderr or done.stdout or "").strip().splitlines()[-1][:200] if (
            done.stderr or done.stdout).strip() else ""
    if what in ("collect", "discover"):
        stats = payload.get("stats") or {}
        return (f"{stats.get('reachable', '?')}/{stats.get('devices', '?')} devices, "
                f"{len(payload.get('errors') or [])} error(s)")
    if what == "names":
        return (f"{payload.get('answered', '?')}/{payload.get('nodes', '?')} node(s) named by "
                "the host")
    if what == "export":
        written = payload.get("written") or []
        return f"{len(written)} file(s) written"
    if what == "push":
        results = payload.get("results") or []
        ok = sum(1 for result in results if result.get("ok"))
        return f"{ok}/{len(results)} file(s) accepted"
    return ""
