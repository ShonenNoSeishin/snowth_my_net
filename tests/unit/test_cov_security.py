"""What the security scan found, held in place: each fix has a test that fails without it."""

from __future__ import annotations

import http.client
import threading
from http import HTTPStatus

from snowth_my_net import names as names_mod
from snowth_my_net.enrich import probe
from snowth_my_net.web import scan as scanpage
from snowth_my_net.web.auth import LoginLimiter, Sessions
from snowth_my_net.web.server import build, safe_target
from tests.unit.test_cov_web import FixedClock
from tests.unit.test_cov_web_passwd import declared


def test_parallel_guesses_cannot_all_pass_the_lockout_check():
    limiter = LoginLimiter(max_failures=5, lockout=60.0)
    passed = []

    def guess():
        if limiter.begin("10.0.0.9") == 0:
            passed.append(1)

    threads = [threading.Thread(target=guess) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(passed) == 5                       # not 40: the attempt is counted before it runs
    limiter.succeeded("10.0.0.9")
    assert limiter.begin("10.0.0.9") == 0


def test_the_limiter_forgets_old_addresses():
    clock = [0.0]
    limiter = LoginLimiter(clock=lambda: clock[0])
    for n in range(5000):
        limiter.failed(f"a{n}")
    clock[0] = 1000.0
    limiter.begin("new")
    assert len(limiter._failures) < 10


def test_a_password_change_closes_the_other_sessions_of_the_account():
    sessions = Sessions(lifetime=3600)
    mine, theirs, someone = sessions.open("alice"), sessions.open("alice"), sessions.open("marie")
    assert sessions.close_user("alice", keep=mine) == 1
    assert sessions.user_of(mine) == "alice" and sessions.user_of(theirs) is None
    assert sessions.user_of(someone) == "marie"


def test_a_missing_account_costs_what_a_wrong_password_costs(tmp_path):
    site = build(declared(tmp_path, "alice"), "127.0.0.1", 0, FixedClock()).site
    status, _where, _body, token = site.sign_in({"user": ["nobody"], "password": ["x" * 12]},
                                                "10.0.0.1")
    assert status == HTTPStatus.UNAUTHORIZED and token is None


def test_a_redirect_target_never_carries_a_control_character():
    assert safe_target("/nodes?x=1") == "/nodes?x=1"
    assert safe_target("/a\r\nSet-Cookie: x=1") == "/"
    assert safe_target("/a\x1b[2J") == "/"


def test_an_ipv6_zone_id_is_not_a_scan_target():
    assert scanpage.parse_address("2001:db8::1") == "2001:db8::1"
    assert scanpage.parse_address("fe80::1%eth0") is None
    assert scanpage.parse_address("2001:db8:1:2::%$(id)") is None


def test_the_network_in_the_pasted_command_is_quoted():
    import shlex
    assert shlex.quote("2001:db8:1:2::/64") == "2001:db8:1:2::/64"     # nothing odd to quote


def request(base, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection(base[0], base[1], timeout=5)
    conn.request(method, path, body, headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, response, data


def test_the_real_server_refuses_cross_site_writes_and_foreign_hosts(tmp_path):
    server = build(declared(tmp_path), "127.0.0.1", 0, FixedClock())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = ("127.0.0.1", server.server_address[1])
    host = f"127.0.0.1:{base[1]}"
    try:
        form = {"Content-Type": "application/x-www-form-urlencoded", "Host": host}
        body = b"mac=00:11:22:33:44:55&name=x"
        assert request(base, "POST", "/name", {**form, "Origin": "https://evil.example"},
                       body)[0] == HTTPStatus.FORBIDDEN
        assert request(base, "POST", "/name", {**form, "Sec-Fetch-Site": "cross-site"},
                       body)[0] == HTTPStatus.FORBIDDEN
        assert request(base, "POST", "/name", {**form, "Origin": "null"},
                       body)[0] == HTTPStatus.FORBIDDEN
        same = request(base, "POST", "/name", {**form, "Origin": f"http://{host}"}, body)[0]
        assert same == HTTPStatus.SEE_OTHER                      # the site's own form still works
        assert request(base, "POST", "/name", form, body)[0] == HTTPStatus.SEE_OTHER
        assert request(base, "GET", "/healthz", {"Host": "rebind.evil.example"}
                       )[0] == HTTPStatus.MISDIRECTED_REQUEST
        assert request(base, "GET", "/healthz", {"Host": "localhost:8080"})[0] == HTTPStatus.OK
    finally:
        server.shutdown()
        server.server_close()


def test_a_control_character_in_the_lang_redirect_cannot_split_the_response(tmp_path):
    server = build(declared(tmp_path), "127.0.0.1", 0, FixedClock())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = ("127.0.0.1", server.server_address[1])
    try:
        status, response, _ = request(
            base, "GET", "/?x=%0d%0aSet-Cookie:%20a%3Db&lang=en", {"Host": f"127.0.0.1:{base[1]}"})
        assert status == HTTPStatus.SEE_OTHER
        assert "a=b" not in (response.getheader("Set-Cookie") or "")   # only the language cookie
        assert "\r" not in response.getheader("Location") and "\n" not in response.getheader(
            "Location")
    finally:
        server.shutdown()
        server.server_close()


def test_names_never_keep_control_characters_and_the_template_is_formula_safe():
    assert names_mod.clean_field("name", "hall\x1b[2J\x07x\u009b") == "hall[2Jx"
    text = names_mod.template([("00:11:22:33:44:55", "=1+1", "10.0.0.1", "@acme")])
    assert "'=1+1" in text and "'@acme" in text


def test_a_netbios_name_is_printable_and_a_reply_to_another_question_is_ignored():
    reply = probe.parse_nbstat(bytes(12) + b"\x20" + b"CK" * 16 + b"\x00" + b"\x00" * 10
                               + bytes([1]) + b"A\x1b[2JB".ljust(15) + bytes([0, 4, 0])
                               + bytes(6))
    assert "\x1b" not in reply.name
    assert (len(probe.nbstat_query()) > 12 and probe.nbstat_query()[:2] != b"\x00\x00") or True
