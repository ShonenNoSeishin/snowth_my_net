import importlib.util
from pathlib import Path

import pytest

from snowth_my_net.export.csvout import (
    DEVICES_HEADER,
    LINKS_HEADER,
    NODES_HEADER,
    EmptyExport,
    devices_csv,
    render_csv,
)

TESTS = Path(__file__).resolve().parents[1]


def test_headers_are_byte_exact():
    assert DEVICES_HEADER.encode() == (
        b'"Device Name","Device Details","IP Address",Location,Model,Serial,Vendor,'
        b'"Operating System","OS Version","MAC Address"')
    assert NODES_HEADER.encode() == (
        b'"MAC Address",Vendor,"IP Address","DNS Name",Switch,Port,VLAN,"Last Seen"')
    assert LINKS_HEADER.encode() == (
        b"Local Device,Local Port,Remote Device,Remote Port,Protocol,Last Seen")


def test_rfc4180_quoting_crlf_and_no_bom():
    data = render_csv("h1,h2", [["plain", 'say "hi", twice'], ["é", "line1\nline2"]])
    assert data == b'h1,h2\r\nplain,"say ""hi"", twice"\r\n\xc3\xa9,"line1\nline2"\r\n'
    assert render_csv("h", [["a"]], "lf") == b"h\na\n"
    assert not data.startswith(b"\xef\xbb\xbf")


def _device(i, **kw):
    row = {"id": i, "mgmt_address": f"192.0.2.{i}", "sys_descr": "Line 1\r\nLine 2",
           "sys_location": "Hall, desk 3", "model": "M", "serial": "S", "vendor": "V",
           "os_name": "OS", "os_version": "1.0", "base_mac": "00:00:5e:00:53:01",
           "device_type": ""}
    row.update(kw)
    return row


def test_devices_csv_rows_are_one_line_and_naturally_sorted():
    devices = [_device(1), _device(2, mgmt_address="192.0.2.2:1161")]
    names = {1: "sw10", 2: "sw9"}
    lines = devices_csv(devices, names, include_type=True, line_terminator="crlf").split(b"\r\n")
    assert lines[0].endswith(b',"Device Type"')
    assert lines[1].startswith(b"sw9,Line 1 Line 2,192.0.2.2,")      # no port in IP Address
    assert lines[2].startswith(b"sw10,")
    assert b'"Hall, desk 3"' in lines[1]
    without_type = devices_csv(devices, names, include_type=False, line_terminator="lf")
    assert without_type.split(b"\n")[0] == DEVICES_HEADER.encode()


def test_empty_devices_csv_is_refused_unless_allowed():
    with pytest.raises(EmptyExport):
        devices_csv([], {}, include_type=True, line_terminator="crlf")
    assert devices_csv([], {}, True, "crlf", allow_empty=True).count(b"\r\n") == 1


def test_committed_fixtures_match_their_builder(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "build_snmprec", TESTS / "fixtures" / "build_snmprec.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    built = builder.build(tmp_path)
    for path in built.values():
        committed = TESTS / "fixtures" / "snmprec" / path.relative_to(tmp_path)
        assert committed.read_text() == path.read_text(), (
            f"{committed} is stale: run python tests/fixtures/build_snmprec.py")
