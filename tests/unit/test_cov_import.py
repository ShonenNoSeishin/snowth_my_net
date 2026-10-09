"""Giving names to many MACs from one uploaded CSV, and the log that comes back."""

from __future__ import annotations

import csv
import io
import threading
import urllib.parse
import urllib.request

import pytest

from snowth_my_net import names as mod
from snowth_my_net.i18n import Translator
from snowth_my_net.web.server import Site, WebServer
from tests.unit.test_cov_names import named
from tests.unit.test_cov_views import D
from tests.unit.test_cov_web import FixedClock

A, B = "00:11:22:33:44:01", "00:11:22:33:44:02"


def store(tmp_path):
    return mod.Names(tmp_path / mod.STORE_NAME)


def run(tmp_path, text, known=()):
    lines = mod.import_names(store(tmp_path), text, set(known))
    return {(x.mac or x.name): x for x in lines}, lines


def test_a_new_mac_is_added_and_an_existing_one_updated(tmp_path):
    store(tmp_path).set(A, "old")
    store(tmp_path).set(B, "same")
    _by, lines = run(tmp_path, "mac,name\n" + f"{A},new\n{B},same\n00:11:22:33:44:03,fresh\n",
                     known={A})
    assert [x.result for x in lines] == ["updated", "unchanged", "added"]
    assert lines[0].before == "old"
    assert lines[2].detail == "not seen on the network yet"
    assert store(tmp_path).read()["00:11:22:33:44:03"] == {"name": "fresh"}
    assert store(tmp_path).get(A) == "new"


def test_a_known_mac_added_has_no_remark(tmp_path):
    _by, lines = run(tmp_path, f"{A};box\n", known={A})
    assert lines[0].result == "added" and lines[0].detail == ""    # also: ; and no header


def test_the_separator_the_spreadsheet_used_is_followed(tmp_path):
    _by, lines = run(tmp_path, f"﻿MAC;Nom\r\n{A};a, b\r\n{B}\r\n")
    assert [(x.line, x.result) for x in lines] == [(2, "added"), (3, "error")]
    assert store(tmp_path).get(A) == "a, b"          # the comma stayed in the name
    assert lines[1].detail == "no second column: the name"


def test_bad_lines_are_reported_and_the_rest_goes_on(tmp_path):
    text = (f"# comment\n\n{A},one\nnot-a-mac,x\n{A},again\n{B},\n"
            f"00:11:22:33:44:05,{'x' * 80}\n")
    _by, lines = run(tmp_path, text)
    assert [x.result for x in lines] == ["added", "error", "error", "skipped", "error"]
    assert [x.line for x in lines] == [3, 4, 5, 6, 7]
    assert "not a MAC address" in lines[1].detail
    assert "already on line 3" in lines[2].detail
    assert "nothing is changed" in lines[3].detail
    assert "at most 60" in lines[4].detail
    assert store(tmp_path).read() == {A: {"name": "one"}}


def test_a_first_line_that_is_no_header_is_an_error_not_dropped(tmp_path):
    _by, lines = run(tmp_path, f"00:11:22:33:44:0g,typo\n{A},ok\n")
    assert [x.result for x in lines] == ["error", "added"]


def test_too_many_lines_are_refused_whole(tmp_path):
    text = "".join(f"00:00:00:00:{i >> 8:02x}:{i & 255:02x},n\n" for i in range(1, 5002))
    with pytest.raises(mod.NameError_, match="at most 5000"):
        mod.import_names(store(tmp_path), text, set())
    assert store(tmp_path).read() == {}


def test_the_log_has_a_row_per_line_a_total_and_no_formula(tmp_path):
    _by, lines = run(tmp_path, f"{A},=1+1\nnope,x\n{B},\n")
    rows = list(csv.reader(io.StringIO(mod.import_log(lines))))
    assert rows[0] == ["line", "mac", "name", "before", "result", "detail"]
    assert rows[1][2] == "'=1+1" and rows[1][4] == "added"
    assert rows[2][4] == "error" and rows[3][4] == "skipped"
    assert rows[-1][4:] == ["total", "1 error, 0 updated, 1 added, 1 skipped, 0 unchanged"]
    assert store(tmp_path).get(A) == "=1+1"            # the log is neutralised, not the data


def test_planning_writes_nothing(tmp_path):
    lines, todo = mod.plan_import({}, f"{A},x\n", set())
    assert [x.result for x in lines] == ["added"] and todo == {A: "x"}
    assert store(tmp_path).read() == {}


def test_the_template_lists_the_nodes_with_their_names_and_reads_back_as_nothing(tmp_path):
    text = mod.template([(B, "", "10.0.0.2", "Acme"), (A, "hall", "10.0.0.1", "Zed, Inc")])
    assert text.splitlines()[:3] == ["mac,name,ip,vendor", f"{A},hall,10.0.0.1,\"Zed, Inc\"",
                                     f"{B},,10.0.0.2,Acme"]
    _by, lines = run(tmp_path, text)                    # the extra columns are not read
    assert [x.result for x in lines] == ["added", "skipped"]
    assert store(tmp_path).read() == {A: {"name": "hall"}}
    assert mod.template([]).startswith("mac,name,ip,vendor\r\n#")
    assert mod.plan_import({}, mod.template([]), set())[0] == []


# ------------------------------------------------------------------------- the web side


def multipart(content: bytes, filename="names.csv", field="file"):
    boundary = "xBOUNDARYx"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n').encode() + content + (
            f"\r\n--{boundary}--\r\n").encode()
    return f"multipart/form-data; boundary={boundary}", body


EN = Translator("en")


def test_the_upload_text_is_read_or_refused():
    from snowth_my_net.web.nodeimport import upload_text
    ctype, body = multipart(b"\xef\xbb\xbfmac,name\n")
    assert upload_text(ctype, body) == "mac,name\n"
    assert upload_text(*multipart(b"  \n")) is None
    assert upload_text(*multipart(b"x", field="other")) is None
    assert upload_text("application/x-www-form-urlencoded", b"a=b") is None


def test_the_three_screens_check_first_then_apply_then_log(tmp_path):
    site = Site(named(tmp_path, ""), FixedClock())
    labels = mod.store_for(site.loaded.paths)
    csv_text = f"mac,name\n{D},hall\nzzz,x\n"
    status, _t, page = site.import_check(*multipart(csv_text.encode()), EN)
    html = page.decode()
    assert status == 200 and labels.read() == {}                    # the check wrote nothing
    assert "Apply 1 change(s)" in html and "not a MAC address" in html
    assert '<textarea name="csv" hidden>' in html and "1 error" in html
    status, _t, page = site.import_apply({"csv": [csv_text]}, EN)
    html = page.decode()
    assert status == 200 and labels.get(D) == "hall"
    assert "Done." in html and "Download the log" in html and "1 added" in html
    status, _t, page = site.import_check(*multipart(f"{D},hall\n".encode()), EN)
    assert b"Nothing to change" in page.decode().encode()           # a second pass changes nothing
    status, _t, page = site.import_check("text/plain", b"", EN)
    assert status == 400 and b"No file received" in page
    assert site.import_apply({"csv": [""]}, EN)[0] == 400
    big = "".join(f"00:00:00:00:{i >> 8:02x}:{i & 255:02x},n\n" for i in range(1, 5002))
    assert b"at most 5000" in site.import_check(*multipart(big.encode()), EN)[2]
    assert b"at most 5000" in site.import_apply({"csv": [big]}, EN)[2]


def test_the_pages_and_the_real_routes(tmp_path):
    site = Site(named(tmp_path, "imprimante"), FixedClock())
    assert "/import" in site.respond("/nodes", {})[2].decode()
    status, _t, page = site.respond("/import", {})
    assert status == 200 and 'enctype="multipart/form-data"' in page.decode()
    template = site.respond("/import/template.csv", {})[2].decode()
    assert template.startswith("mac,name,ip,vendor") and f"{D},imprimante" in template

    server = WebServer(("127.0.0.1", 0), site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        ctype, body = multipart(f"{D},from the route\n".encode())
        with urllib.request.urlopen(urllib.request.Request(
                base + "/import", data=body, headers={"Content-Type": ctype})) as answer:
            assert b"Appliquer 1" in answer.read()                  # a check, not a write
        assert mod.store_for(site.loaded.paths).get(D) == "imprimante"
        form = urllib.parse.urlencode({"csv": f"{D},from the route\n", "apply": "1"}).encode()
        with urllib.request.urlopen(urllib.request.Request(base + "/import", data=form)) as answer:
            assert b"1 mis" in answer.read()
        assert mod.store_for(site.loaded.paths).get(D) == "from the route"
        log = urllib.parse.urlencode({"log": "line,mac\r\n"}).encode()
        with urllib.request.urlopen(urllib.request.Request(base + "/import/log", data=log)) as a:
            assert "attachment; filename=" in a.headers["Content-Disposition"]
            assert a.read() == b"line,mac\r\n"
        with urllib.request.urlopen(base + "/import/template.csv") as answer:
            assert "names-template.csv" in answer.headers["Content-Disposition"]
        big = urllib.request.Request(base + "/import", data=b"x" * (4 * mod.MAX_IMPORT_BYTES),
                                     headers={"Content-Type": ctype})
        with pytest.raises(OSError):
            urllib.request.urlopen(big)             # 413, or a socket closed on the oversize body
    finally:
        server.shutdown()
        server.server_close()


def test_the_reasons_shown_follow_the_language_the_log_keeps_in_english(tmp_path):
    from snowth_my_net.web.nodeimport import _detail
    fr = Translator("fr")
    assert _detail(fr, "not a MAC address") == "pas une adresse MAC"
    assert "ligne 3" in _detail(fr, "MAC already on line 3, this line is ignored")
    assert "au plus 60" in _detail(fr, "a name is at most 60 characters")
    assert _detail(fr, "something else") == "something else"
    assert _detail(Translator("en"), "already named so") == "already named so"


def test_the_page_title_is_the_page_not_the_last_cell(tmp_path):
    site = Site(named(tmp_path, ""), FixedClock())
    for path in ("/nodes", "/", "/links", "/runs"):
        page = site.respond(path, {}, None, "en")[2].decode()
        h1 = page.split("<h1>")[1].split("</h1>")[0]
        assert h1 and not h1[:4].isdigit(), (path, h1)
