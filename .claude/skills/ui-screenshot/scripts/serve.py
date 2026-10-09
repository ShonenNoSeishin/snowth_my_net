"""Serve the web UI on 127.0.0.1:8765 with the test fixtures' sample data (no real network)."""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tests.unit.test_cov_views import build_state, make_loaded  # noqa: E402
from tests.unit.test_cov_web import FixedClock  # noqa: E402

from snowth_my_net.web.server import Site, WebServer  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp())
build_state(tmp).conn.close()
server = WebServer(("127.0.0.1", 8765), Site(make_loaded(tmp), FixedClock()))
print("ready", flush=True)
server.serve_forever()
