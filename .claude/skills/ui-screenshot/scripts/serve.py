"""Serve the web UI on 127.0.0.1:8765 with the test fixtures' sample data (no real network)."""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tests.unit.test_cov_views import build_state, make_loaded  # noqa: E402
from tests.unit.test_cov_web import FixedClock  # noqa: E402

from snowth_my_net.config.schema import WebUserCfg  # noqa: E402
from snowth_my_net.web.auth import COOKIE  # noqa: E402
from snowth_my_net.web.server import Site, WebServer  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp())
build_state(tmp).conn.close()
loaded = make_loaded(tmp)
loaded.cfg.web.auth.users = [WebUserCfg("alice")]   # writing needs an account
loaded.cfg.web.nmap = True
site = Site(loaded, FixedClock())
site.set_password("alice", "un-mot-de-passe-qui-va-bien")
server = WebServer(("127.0.0.1", 8765), site)
# the session of 'alice': pass it to shot.py as COOKIE (a signed-out page is /login)
pathlib.Path(tempfile.gettempdir(), "snowth-shot-cookie").write_text(f"{COOKIE}={site.sessions.open('alice')}")
print("ready", flush=True)
server.serve_forever()
