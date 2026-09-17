"""Generic HTTP push: multipart upload of exported files, optional job polling.

* One request per file, in the order of the target's ``files``; a failure never stops the next
  file.
* No redirect is followed: a 301/302 would turn the POST into a GET and could send the
  ``Authorization`` header elsewhere. A 3xx is reported as a failure naming the new location.
* Retries only when the request was not processed: network errors, 429 (``Retry-After``
  honoured), 502, 503, 504. Never on 413 or any other 4xx: an import is not idempotent.
* Secrets (tokens, passwords, header values) come from files or environment variables and are
  registered with the log redactor; they never appear in logs or summaries.
"""

from __future__ import annotations

import base64
import email.utils
import json
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from snowth_my_net import __version__
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.schema import PushTargetCfg
from snowth_my_net.config.secrets import resolve_secret
from snowth_my_net.logs import get_logger

log = get_logger("push")

FILE_NAMES = {"devices": "devices.csv", "nodes": "nodes.csv", "links": "links.csv",
              "snapshot": "snapshot.json"}
CONTENT_TYPES = {".csv": "text/csv", ".json": "application/json"}
RETRY_STATUSES = frozenset({429, 502, 503, 504})
BODY_LOG_LIMIT = 4096


class PushError(Exception):
    pass


@dataclass
class PushOutcome:
    target: str
    file: str
    ok: bool
    status: int | None = None
    duration_ms: int = 0
    detail: str = ""
    attempts: int = 0
    job_id: str | None = None
    job_status: str | None = None

    def as_dict(self) -> dict:
        return {"target": self.target, "file": self.file, "ok": self.ok, "status": self.status,
                "duration_ms": self.duration_ms, "detail": self.detail,
                "attempts": self.attempts, "job_id": self.job_id, "job_status": self.job_status}


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def text(self, limit: int = BODY_LOG_LIMIT) -> str:
        text = self.body[:limit].decode("utf-8", errors="replace")
        text = "".join(ch if ch.isprintable() or ch in "\n\t" else "�" for ch in text)
        return text + ("…" if len(self.body) > limit else "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Client:
    target: PushTargetCfg
    headers: dict[str, str]
    opener: urllib.request.OpenerDirector
    sleep: object = field(default=time.sleep)

    def request(self, method: str, url: str, body: bytes | None = None,
                extra_headers: dict[str, str] | None = None) -> Response:
        headers = {"User-Agent": f"snowth_my_net/{__version__}", **self.headers,
                   **(extra_headers or {})}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
        try:
            with self.opener.open(req, timeout=self.target.timeout) as response:
                return Response(response.status, dict(response.headers.items()), response.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, dict(exc.headers.items()) if exc.headers else {},
                            exc.read() if exc.fp else b"")


def build_client(loaded: LoadedConfig, target: PushTargetCfg) -> tuple[Client, list[str]]:
    """Resolve secrets and TLS settings of a target. Raises SecretError / PushError."""
    base = loaded.paths.secrets_dir
    warnings: list[str] = []
    headers: dict[str, str] = {}
    auth = target.auth
    if auth.bearer_token_file or auth.bearer_token_env:
        token, w = resolve_secret(auth.bearer_token_file, auth.bearer_token_env, base,
                                  f"push target '{target.name}' bearer token")
        warnings += w
        headers["Authorization"] = f"Bearer {token.reveal()}"
    elif auth.basic is not None:
        password, w = resolve_secret(auth.basic.password_file, auth.basic.password_env, base,
                                     f"push target '{target.name}' password")
        warnings += w
        raw = f"{auth.basic.username}:{password.reveal()}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    for name, ref in target.headers.items():
        value, w = resolve_secret(ref.file, ref.env, base,
                                  f"push target '{target.name}' header {name}")
        warnings += w
        headers[name] = value.reveal()

    if target.url.startswith("https://"):
        try:
            context = ssl.create_default_context(cafile=target.ca_bundle or None)
        except (OSError, ssl.SSLError) as exc:
            raise PushError(f"target '{target.name}': cannot load ca_bundle: {exc}") from None
        if not target.tls_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            warnings.append(f"target '{target.name}': TLS certificate verification is DISABLED")
    else:
        context = None
    handlers = [urllib.request.ProxyHandler(), _NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return Client(target, headers, urllib.request.build_opener(*handlers)), warnings


def multipart_body(field_name: str, filename: str, content: bytes, content_type: str,
                   extra_fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "snowth-" + secrets.token_hex(16)
    parts = []
    for name, value in extra_fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                     f"{value}\r\n".encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; '
                 f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def retry_delay(response: Response | None, attempt: int, cap: float) -> float:
    if response is not None:
        header = next((v for k, v in response.headers.items() if k.lower() == "retry-after"),
                      None)
        if header:
            header = header.strip()
            if header.isdigit():
                return min(float(header), cap)
            try:
                moment = email.utils.parsedate_to_datetime(header)
                return max(0.0, min((moment - datetime.now(UTC)).total_seconds(), cap))
            except (TypeError, ValueError):
                pass
    return min(2.0 ** attempt, 30.0, cap)


def dotted(data: object, path: str) -> object:
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def has_data(path: Path) -> bool:
    if path.suffix == ".csv":
        with path.open("rb") as handle:
            handle.readline()
            return bool(handle.readline().strip())
    return path.stat().st_size > 2


def push_file(client: Client, name: str, path: Path, wait: bool) -> PushOutcome:
    target = client.target
    outcome = PushOutcome(target.name, name, ok=False)
    start = time.monotonic()
    try:
        content = path.read_bytes()
    except OSError as exc:
        outcome.detail = f"cannot read {path}: {exc.strerror}"
        return outcome
    body, content_type = multipart_body(target.multipart_field, path.name, content,
                                        CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
                                        target.extra_fields)
    response: Response | None = None
    for attempt in range(target.retries + 1):
        outcome.attempts = attempt + 1
        try:
            response = client.request("POST", target.url, body, {"Content-Type": content_type})
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError,
                OSError) as exc:
            reason = getattr(exc, "reason", exc)
            outcome.detail = f"network error: {reason}"
            response = None
            if attempt < target.retries:
                client.sleep(retry_delay(None, attempt, target.timeout))
                continue
            break
        outcome.status = response.status
        if response.status in RETRY_STATUSES and attempt < target.retries:
            delay = retry_delay(response, attempt, target.timeout)
            log.warning("%s %s: HTTP %d, retrying in %.0fs", target.name, name, response.status,
                        delay)
            client.sleep(delay)
            continue
        break

    if response is not None:
        text = response.text()
        if 200 <= response.status < 300:
            outcome.ok = True
            outcome.detail = text.strip()[:200]
            log.info("%s %s: HTTP %d %s", target.name, name, response.status, text)
            if response.status == 202 and wait:
                poll(client, response, outcome)
        elif 300 <= response.status < 400:
            location = next((v for k, v in response.headers.items() if k.lower() == "location"),
                            "?")
            outcome.detail = f"redirect to {location} (not followed: update the URL)"
        else:
            outcome.detail = f"HTTP {response.status}: {text.strip()[:300]}"
            log.error("%s %s: HTTP %d %s", target.name, name, response.status, text)
    outcome.duration_ms = int((time.monotonic() - start) * 1000)
    return outcome


def poll(client: Client, accepted: Response, outcome: PushOutcome) -> None:
    target = client.target
    cfg = target.poll
    if cfg is None:
        outcome.ok = False
        outcome.detail = "HTTP 202 but no poll: section to wait for the job"
        return
    try:
        job_id = dotted(json.loads(accepted.body or b"{}"), cfg.id_field)
    except ValueError:
        job_id = None
    if job_id in (None, ""):
        outcome.ok = False
        outcome.detail = f"HTTP 202 without {cfg.id_field!r} in the JSON body"
        return
    outcome.job_id = str(job_id)
    url = cfg.url.replace("{id}", urllib.parse.quote(str(job_id), safe=""))
    deadline = time.monotonic() + cfg.timeout
    status = None
    while time.monotonic() < deadline:
        try:
            response = client.request("GET", url)
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
            log.warning("%s: polling job %s failed (%s), retrying", target.name, job_id, exc)
            client.sleep(cfg.interval)
            continue
        if response.status != 200:
            outcome.ok = False
            outcome.detail = f"job {job_id}: poll HTTP {response.status}"
            return
        try:
            status = dotted(json.loads(response.body or b"{}"), cfg.status_field)
        except ValueError:
            status = None
        outcome.job_status = None if status is None else str(status)
        if status in cfg.success:
            outcome.ok = True
            outcome.detail = f"job {job_id}: {status}"
            log.info("%s: job %s finished: %s", target.name, job_id, response.text())
            return
        if status not in cfg.pending:
            outcome.ok = False
            outcome.detail = f"job {job_id}: {status} ({response.text(300)})"
            return
        client.sleep(cfg.interval)
    outcome.ok = False
    outcome.detail = f"job {job_id}: still {status} after {cfg.timeout}s"


def push_all(loaded: LoadedConfig, *, target_name: str | None = None,
             files: list[str] | None = None, wait: bool | None = None,
             available: dict[str, str] | None = None, dry_run: bool = False,
             sleep=time.sleep) -> tuple[list[PushOutcome], list[str]]:
    """Push every configured file. ``available`` maps a file name to a reason it must not be
    sent (an export that failed in this run); ``None`` means "use what is on disk"."""
    targets = [t for t in loaded.cfg.push.targets if target_name in (None, t.name)]
    if target_name and not targets:
        raise PushError(f"unknown push target {target_name!r}")
    outcomes: list[PushOutcome] = []
    warnings: list[str] = []
    for target in targets:
        try:
            client, target_warnings = build_client(loaded, target)
            client.sleep = sleep
        except Exception as exc:                      # secrets or TLS: this target only
            warnings.append(str(exc))
            outcomes += [PushOutcome(target.name, f, ok=False, detail=str(exc))
                         for f in target.files if files is None or f in files]
            continue
        warnings += target_warnings
        for name in target.files:
            if files is not None and name not in files:
                continue
            path = loaded.paths.output_dir / FILE_NAMES[name]
            if available is not None and name in available:
                outcomes.append(PushOutcome(target.name, name, False, detail=available[name]))
                continue
            if not path.exists():
                outcomes.append(PushOutcome(target.name, name, False,
                                            detail=f"{path} does not exist (run export)"))
                continue
            if not has_data(path):
                outcomes.append(PushOutcome(target.name, name, False,
                                            detail=f"{path} has no data row: not pushed"))
                continue
            if dry_run:
                outcomes.append(PushOutcome(target.name, name, True,
                                            detail=f"dry run: would POST {path} "
                                                   f"({path.stat().st_size} bytes)"))
                continue
            outcomes.append(push_file(client, name, path,
                                      target.wait if wait is None else wait))
    return outcomes, warnings
