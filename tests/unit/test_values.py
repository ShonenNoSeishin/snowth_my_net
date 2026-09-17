import pytest

from snowth_my_net.snmp.index import decode_inet_address, decode_ipv4_index, decode_mac_index
from snowth_my_net.snmp.values import (
    decode_text,
    is_locally_administered,
    is_multicast,
    mac_matches_prefix,
    normalize_mac,
    normalize_mac_prefix,
    oid_str,
    one_line,
    parse_oid,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (b"\x00\x11\x22\x33\x44\x55", "00:11:22:33:44:55"),
        (b"abcdef", "61:62:63:64:65:66"),  # 6 octets are always binary
        ("001122334455", "00:11:22:33:44:55"),
        ("00:11:22:33:44:55", "00:11:22:33:44:55"),
        ("00-11-22-33-44-55", "00:11:22:33:44:55"),
        ("00 11 22 33 44 55", "00:11:22:33:44:55"),
        ("0011.2233.4455", "00:11:22:33:44:55"),
        ("0:11:22:3:44:55", "00:11:22:03:44:55"),
        ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
        (b"00:11:22:33:44:55", "00:11:22:33:44:55"),  # textual MAC sent as an OctetString
        ("  00:11:22:33:44:55\n", "00:11:22:33:44:55"),
        ("ff:ff:ff:ff:ff:ff", "ff:ff:ff:ff:ff:ff"),
    ],
)
def test_normalize_mac_accepts_common_forms(value, expected):
    assert normalize_mac(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", b"", b"\x00" * 6, "00:00:00:00:00:00", b"\x00\x11", "00:11:22:33:44",
     "zz:11:22:33:44:55", "00:11:22:33:44:55:66", b"\xff" * 8, "00:11-22:33:44:55",
     "0011.2233.44"],
)
def test_normalize_mac_rejects_garbage(value):
    assert normalize_mac(value) is None


def test_mac_bits():
    assert is_multicast("01:00:5e:00:00:01")
    assert is_multicast("ff:ff:ff:ff:ff:ff")
    assert not is_multicast("00:11:22:33:44:55")
    assert is_locally_administered("02:00:00:00:00:01")
    assert is_locally_administered("da:a1:19:00:00:01")
    assert not is_locally_administered("00:11:22:33:44:55")


def test_mac_prefixes_have_nibble_precision():
    prefix = normalize_mac_prefix("00:00:0c:9f:f")
    assert prefix == "00000c9ff"
    assert mac_matches_prefix("00:00:0c:9f:f0:01", prefix)
    assert not mac_matches_prefix("00:00:0c:9f:e0:01", prefix)
    assert normalize_mac_prefix("zz") is None
    assert normalize_mac_prefix("00:11:22:33:44:55:66") is None


def test_text_decoding():
    assert decode_text(b"abc\x00") == "abc"
    assert decode_text(b"caf\xe9") == "café"  # Latin-1 fallback
    assert decode_text("é".encode()) == "é"
    assert decode_text(None) == ""
    assert one_line("line1\r\nline2\t  end ") == "line1 line2 end"


def test_oid_helpers():
    assert parse_oid(".1.3.6.1") == (1, 3, 6, 1)
    assert oid_str((1, 3, 6, 1)) == "1.3.6.1"


def test_inet_address_index():
    ip, used = decode_inet_address((4, 10, 0, 0, 1), 1)
    assert (str(ip), used) == ("10.0.0.1", 5)
    ip, used = decode_inet_address((10, 0, 0, 1), 1)  # length prefix omitted (agent bug)
    assert (str(ip), used) == ("10.0.0.1", 4)
    v6 = (16, 0x20, 0x01, 0x0D, 0xB8) + (0,) * 11 + (1,)
    ip, used = decode_inet_address(v6, 2)
    assert (str(ip), used) == ("2001:db8::1", 17)
    ip, _ = decode_inet_address((8, 169, 254, 0, 1, 0, 0, 0, 3), 3)  # ipv4z, zone dropped
    assert str(ip) == "169.254.0.1"
    assert decode_inet_address((4, 1, 2), 1)[0] is None     # too short either way
    assert decode_inet_address((1, 2, 3), 0)[0] is None
    assert decode_inet_address((4, 300, 0, 0, 1), 1)[0] is None


def test_fixed_indexes():
    assert str(decode_ipv4_index((192, 0, 2, 1))) == "192.0.2.1"
    assert decode_ipv4_index((1, 2, 3)) is None
    assert decode_mac_index((0, 17, 34, 51, 68, 85)) == "00:11:22:33:44:55"
    assert decode_mac_index((0, 17, 34)) is None
