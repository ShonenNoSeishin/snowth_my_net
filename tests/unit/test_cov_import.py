"""Giving names to many MACs from one uploaded CSV, and the log that comes back."""

from __future__ import annotations

import csv
import io
import threading
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
    assert lines[0].detail == "was 'old'"
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
    assert [x.result for x in lines] == ["added", "error", "error", "error", "error"]
    assert [x.line for x in lines] == [3, 4, 5, 6, 7]
    assert "not a MAC address" in lines[1].detail
    assert "already on line 3" in lines[2].detail
    assert "nothing is erased" in lines[3].detail
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
    _by, lines = run(tmp_path, f"{A},=1+1\nnope,x\n")
    rows = list(csv.reader(io.StringIO(mod.import_log(lines))))
    assert rows[0] == ["line", "mac", "name", "result", "detail"]
    assert rows[1][2] == "'=1+1" and rows[1][3] == "added"
    assert rows[2][3] == "error"
    assert rows[-1][3:] == ["total", "1 added, 0 updated, 0 unchanged, 1 error"]
    assert store(tmp_path).get(A) == "=1+1"            # the log is neutralised, not the data


def test_the_template_is_a_valid_empty_import(tmp_path):
    _by, lines = run(tmp_path, mod.TEMPLATE)
    assert lines == [] and store(tmp_path).read() == {}


# ------------------------------------------------------------------------- the web side


def multipart(content: bytes, filename="names.csv", field="file"):
    boundary = "xBOUNDARYx"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n').encode() + content + (
            f"\r\n--{boundary}--\r\n").encode()
    return f"multipart/form-data; boundary={boundary}", body


def test_the_upload_text_is_read_or_refused():
    from snowth_my_net.web.nodeimport import upload_text
    ctype, body = multipart(b"\xef\xbb\xbfmac,name\n")
    assert upload_text(ctype, body) == "mac,name\n"
    assert upload_text(*multipart(b"  \n")) is None
    assert upload_text(*multipart(b"x", field="other")) is None
    assert upload_text("application/x-www-form-urlencoded", b"a=b") is None


def test_the_site_answers_with_the_log_and_keeps_the_names(tmp_path):
    site = Site(named(tmp_path, ""), FixedClock())
    status, ctype, body = site.import_names(*multipart(f"{D},hall\nzzz,x\n".encode()))
    assert status == 200 and ctype.startswith("text/csv")
    assert b",added," in body and b",error," in body and b"1 added" in body
    assert mod.store_for(site.loaded.paths).get(D) == "hall"
    status, _t, page = site.import_names("text/plain", b"", Translator("en"))
    assert status == 400 and b"No file received" in page
    status, _t, page = site.import_names(*multipart(
        ("".join(f"00:00:00:00:{i >> 8:02x}:{i & 255:02x},n\n" for i in range(1, 5002))).encode()),
        Translator("en"))
    assert status == 400 and b"at most 5000" in page


def test_the_pages_and_the_real_route(tmp_path):
    site = Site(named(tmp_path, ""), FixedClock())
    assert "/import" in site.respond("/nodes", {})[2].decode()
    page = site.respond("/import", {})[2].decode()
    assert 'enctype="multipart/form-data"' in page and "/import/template.csv" in page
    assert site.respond("/import/template.csv", {})[2].decode().startswith("mac,name")

    server = WebServer(("127.0.0.1", 0), site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        ctype, body = multipart(f"{D},from the route\n".encode())
        with urllib.request.urlopen(urllib.request.Request(
                base + "/import", data=body, headers={"Content-Type": ctype})) as answer:
            assert "attachment; filename=" in answer.headers["Content-Disposition"]
            assert b"1 added" in answer.read()
        with urllib.request.urlopen(base + "/import/template.csv") as answer:
            assert "names-template.csv" in answer.headers["Content-Disposition"]
        big = urllib.request.Request(base + "/import", data=b"x" * (mod.MAX_IMPORT_BYTES + 9000),
                                     headers={"Content-Type": ctype})
        with pytest.raises(OSError):
            urllib.request.urlopen(big)             # 413, or a socket closed on the oversize body
    finally:
        server.shutdown()
        server.server_close()
    assert mod.store_for(site.loaded.paths).get(D) == "from the route"
