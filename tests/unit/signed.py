"""A signed-in reader: writing is only offered to an account, so tests that write need one."""

from __future__ import annotations

from snowth_my_net.config.schema import WebUserCfg
from snowth_my_net.web.auth import COOKIE
from snowth_my_net.web.server import Site
from tests.unit.test_cov_web import FixedClock

PASSWORD = "un-mot-de-passe-qui-va-bien"


class SignedSite:
    """A ``Site`` whose ``respond`` carries the session of its one account."""

    def __init__(self, loaded, clock=None):
        loaded.cfg.web.auth.users = [WebUserCfg("alice")]
        self.site = Site(loaded, clock or FixedClock())
        self.site.set_password("alice", PASSWORD)
        self.token = self.site.sessions.open("alice")

    def respond(self, path, query, token=None, *args, **kwargs):
        return self.site.respond(path, query, token or self.token, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.site, name)

    def __setattr__(self, name, value):
        if name in ("site", "token"):
            super().__setattr__(name, value)
        else:
            setattr(self.site, name, value)


def cookie_of(server) -> str:
    """The Cookie header of a session on a running server whose configuration has 'alice'."""
    server.site.set_password("alice", PASSWORD)
    return f"{COOKIE}={server.site.sessions.open('alice')}"
