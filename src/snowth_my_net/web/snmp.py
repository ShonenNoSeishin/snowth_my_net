"""The SNMP connections page: which addresses are polled, with which credential, and why one
does not answer.

Two rules, both from the person this was built for:

* **A community is never rendered.** The page names credentials, it never shows their value —
  the state itself only holds their names, and this page reads nothing else.
* **The password is asked again** before the page opens, and again once the confirmation has
  aged: a session left open on a screen is enough to read the inventory, not to change what the
  tool talks to.

What can be changed here is what the terminal interface already changes: the addresses to poll,
and the per-address settings the state holds. Credentials themselves are declared in the
configuration file, with their secrets in files — this page cannot create one, on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

from snowth_my_net.config.effective import settings_for
from snowth_my_net.config.loader import LoadedConfig
from snowth_my_net.config.manual import ManualError, normalize_address
from snowth_my_net.snmp.target import split_host_port
from snowth_my_net.state.repo import Repo

ACTIONS = ("add", "remove", "credential", "test", "forget")


@dataclass(frozen=True)
class Connection:
    """One address the tool polls, as the page shows it."""

    address: str                 # as the state holds it (possibly with a port)
    host: str                    # the address alone, the key of every manual setting
    origin: str                  # seed | manual | neighbor | sweep | state
    credential: str              # the name chosen by hand, or "" for "whichever answers"
    credential_source: str       # manual | config | ""
    used: str                    # the name of the credential that last worked
    status: str                  # ok | failed | never
    error: str
    failures: int
    device_name: str
    last_attempt: int | None = None     # when it was last tried
    last_ok: int | None = None          # when it last answered


def connections(loaded: LoadedConfig, repo: Repo) -> list[Connection]:
    manual = repo.manual_settings()
    names = {device["id"]: device["sys_name"] or "" for device in repo.devices()}
    used = {device["id"]: device["credential"] or "" for device in repo.devices()}
    rows = []
    for target in repo.targets():
        if target["is_alias"]:
            continue
        host = split_host_port(target["address"])[0]
        settings = settings_for(loaded.cfg, host, manual)
        status = ("ok" if target["device_status"] == "ok"
                  else "failed" if target["last_error"] or target["device_status"]
                  else "never")
        rows.append(Connection(
            address=target["address"], host=host, origin=target["origin"],
            credential=settings.credential or "",
            credential_source=settings.source("credential") if settings.credential else "",
            used=used.get(target["device_id"], ""),
            status=status, error=target["last_error"] or "",
            failures=target["consecutive_failures"],
            device_name=names.get(target["device_id"], "") or "",
            last_attempt=target["last_attempt_at"], last_ok=target["last_ok_at"],
        ))
    rows.sort(key=lambda row: row.host)
    return rows


def credential_names(loaded: LoadedConfig) -> list[str]:
    """The names a reader may choose from — never a value, never a secret."""
    return [credential.name for credential in loaded.cfg.credentials]


def add_target(repo: Repo, address: str, now: int) -> str:
    """Poll this address from now on. Returns the address as it was stored."""
    host = normalize_address(address)
    repo.ensure_target(host, "manual", 0, now)
    return host


def remove_target(repo: Repo, address: str) -> str:
    host = normalize_address(address)
    repo.remove_target(host)
    return host


def set_credential(loaded: LoadedConfig, repo: Repo, address: str, name: str, now: int) -> str:
    """Pin an address to a credential by name, or let the tool try them all again."""
    host = normalize_address(address)
    if not name:
        repo.unset_manual(host, ["credential"])
        return ""
    if name not in credential_names(loaded):
        raise ManualError(f"no credential named '{name}' in the configuration")
    repo.set_manual(host, {"credential": name}, now)
    return name
