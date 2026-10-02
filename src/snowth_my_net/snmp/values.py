"""Pure helpers to decode SNMP values: OIDs, MAC addresses, display strings."""

from __future__ import annotations

import re

Oid = tuple[int, ...]

_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_SEPARATED = re.compile(r"^[0-9a-f]{1,2}([:\- ])[0-9a-f]{1,2}(\1[0-9a-f]{1,2}){4}$")
_CISCO = re.compile(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$")


def parse_oid(text: str) -> Oid:
    return tuple(int(part) for part in text.strip().strip(".").split("."))


def oid_str(oid: Oid) -> str:
    return ".".join(str(part) for part in oid)


def has_prefix(oid: Oid, prefix: Oid) -> bool:
    return oid[: len(prefix)] == prefix


def normalize_mac(value: bytes | bytearray | str | None) -> str | None:
    """Return ``aa:bb:cc:dd:ee:ff`` or None for anything that is not a usable unicast-or-not MAC.

    Accepts 6 raw octets (always taken as binary) and the usual textual forms:
    ``001122334455``, ``00:11:22:33:44:55``, ``00-11-…``, ``00 11 …``, ``0011.2233.4455`` and
    unpadded ``0:11:2:…``. The all-zero address is rejected (it means "unknown" everywhere).
    """
    if value is None:
        return None
    if isinstance(value, bytes | bytearray):
        raw = bytes(value)
        if len(raw) == 6:
            octets = raw
        else:
            try:
                return normalize_mac(raw.decode("ascii"))
            except UnicodeDecodeError:
                return None
    else:
        text = value.strip().lower()
        if _HEX12.match(text):
            octets = bytes.fromhex(text)
        elif _CISCO.match(text):
            octets = bytes.fromhex(text.replace(".", ""))
        elif _SEPARATED.match(text):
            octets = bytes(int(part, 16) for part in re.split(r"[:\- ]", text))
        else:
            return None
    if octets == b"\x00" * 6:
        return None
    return ":".join(f"{b:02x}" for b in octets)


def normalize_mac_prefix(text: str) -> str | None:
    """Normalize a MAC prefix such as ``00:00:5e:00:01`` or ``00:00:0c:9f:f`` (nibble precision).

    Returned as a plain lowercase hex string without separators, e.g. ``00005e0001``.
    """
    compact = re.sub(r"[:\-. ]", "", text.strip().lower())
    if not compact or len(compact) > 12 or not re.fullmatch(r"[0-9a-f]+", compact):
        return None
    return compact


def mac_matches_prefix(mac: str, compact_prefix: str) -> bool:
    return mac.replace(":", "").startswith(compact_prefix)


def is_multicast(mac: str) -> bool:
    """I/G bit set: multicast, including broadcast ff:ff:ff:ff:ff:ff."""
    return bool(int(mac[:2], 16) & 0x01)


def is_locally_administered(mac: str) -> bool:
    """U/L bit set: locally administered (randomized, virtual…). No meaningful OUI."""
    return bool(int(mac[:2], 16) & 0x02)


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
HIGH_SHARE = 0.25          # above this, Latin-1 "letters" are bytes, not a word


def decode_text(value: bytes | str | None) -> str:
    """Display string from an OctetString: UTF-8 if valid, else Latin-1; NULs removed.

    An OctetString is not always text. A chassis identifier or a device name can hold raw bytes
    — a MAC address, a binary serial — and Latin-1 never fails, so those used to come out as
    mojibake ("ýtÇp") and were shown as a neighbour's name. Three things tell them apart from a
    legitimate accented label, in order of certainty: a control character is never in a name;
    six bytes that are not UTF-8 are a MAC address, which is what a device puts in a field meant
    for its name; and beyond a quarter of high bytes, "letters" are bytes (``Café switch`` is one
    in eleven, ``ýtÇp`` is two in four). What is not a display string is shown in hex, which is
    readable, searchable, and recognised as a MAC when it is one.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raw = bytes(value)
    stripped = raw.replace(b"\x00", b"")
    try:
        text = stripped.decode("utf-8")
    except UnicodeDecodeError:
        if len(raw) == 6:
            return normalize_mac(raw) or raw.hex(":")
        text = stripped.decode("latin-1")
        high = sum(1 for char in text if ord(char) > 0x7E)
        if text and high / len(text) > HIGH_SHARE:
            return raw.hex(":")
    if _CONTROL.search(text):
        return raw.hex(":")
    return text.strip()


def one_line(text: str) -> str:
    """Collapse CR/LF/tabs and runs of whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()
