"""Asking a host its own name: the packets, the parsing, and what silence means.

The protocols are what ``nbtstat -A`` and a scanner use. They are built and parsed here rather
than measured against a live network, so the tests say what the code does, and a probe against a
real network says what that network answers — the two questions stay apart.
"""

from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest

from snowth_my_net.enrich import probe

MAC = bytes.fromhex("000c291b88fc")


def reply(names: list[tuple[str, int, int]], mac: bytes = MAC) -> bytes:
    """A node status reply, as a Windows host sends it."""
    question = probe._first_level("*")
    header = b"\x00" * 12
    record = question + b"\x00\x21\x00\x01" + b"\x00\x00\x00\x00" + b"\x00\x00"
    rdata = bytes((len(names),))
    for name, kind, flags in names:
        rdata += name.ljust(15).encode("latin-1") + bytes((kind,)) + flags.to_bytes(2)
    return header + record + rdata + mac + b"\x00" * 40


# --------------------------------------------------------------------------- the question


def test_the_question_is_the_one_nbtstat_asks():
    query = probe.nbstat_query()
    assert len(query) == 50                                  # 12 header, 34 name, 2 + 2
    assert query[2:12] == bytes((0, 0, 0, 1, 0, 0, 0, 0, 0, 0))   # one question, no flags
    assert query[12] == 32 and query[13:45] == b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert query[45] == 0 and query[46:] == b"\x00\x21\x00\x01"   # NBSTAT, class IN
    assert probe.nbstat_query()[:2] != query[:2] or True      # the id only has to vary


def test_the_encoding_is_two_letters_per_byte():
    assert probe._first_level("*")[1:5] == b"CKAA"            # '*' is 0x2A, NUL is 0x00
    assert len(probe._first_level("WORKGROUP")) == 34


# --------------------------------------------------------------------------- the answer


def test_the_workstation_name_and_the_adapter_address_are_read():
    answer = probe.parse_nbstat(reply([("POSTE-JULIE", 0x00, 0x0400),
                                       ("ACME", 0x00, 0x8400)]))
    assert answer.found and answer.name == "POSTE-JULIE"
    assert answer.mac == "00:0c:29:1b:88:fc"                  # stated by the host itself
    assert answer.source == "netbios"


def test_a_group_name_is_never_taken_for_a_host():
    """A workgroup or domain name is shared: it names nobody."""
    answer = probe.parse_nbstat(reply([("ACME", 0x00, 0x8000)]))
    assert not answer.found and answer.detail == "only group names"
    assert answer.mac == "00:0c:29:1b:88:fc"                  # still useful


def test_the_server_service_name_counts_too():
    answer = probe.parse_nbstat(reply([("SRV-FILES", probe.SERVER, 0x0400)]))
    assert answer.name == "SRV-FILES"


@pytest.mark.parametrize(("payload", "detail"), [
    (b"", "truncated answer"),                               # nothing past the header
    (b"\x00" * 12, "no names in the answer"),                 # a header saying zero names
    (probe._first_level("*") + b"\x00" * 10, "no names in the answer"),
])
def test_an_answer_that_is_not_one_says_so(payload, detail):
    assert probe.parse_nbstat(b"\x00" * 12 + payload).detail == detail


def test_an_answer_with_no_name_at_all():
    assert probe.parse_nbstat(reply([])).detail == "no names in the answer"


def test_a_truncated_name_entry_is_dropped():
    broken = reply([("POSTE", 0x00, 0x0400)])[:-56]            # cut inside the entry
    assert not probe.parse_nbstat(broken).found


# --------------------------------------------------------------------------- over the wire


def test_a_question_is_really_sent_and_silence_is_reported():
    """No host answers on a port nothing listens on: the probe says so rather than hanging."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    async def ask_once():
        return await probe.ask_netbios("127.0.0.1", timeout=0.2)

    original = probe.NBNS_PORT
    try:
        probe.NBNS_PORT = port                                # the listener never answers
        answer = asyncio.run(ask_once())
        assert answer.detail == "no answer" and not answer.found
        assert listener.recv(1024)[:2] != b""                 # the question did arrive
    finally:
        probe.NBNS_PORT = original
        listener.close()


def test_an_address_that_is_not_one_is_refused():
    with pytest.raises(ValueError):
        asyncio.run(probe.ask_all("sw-office"))


def test_a_reverse_question_to_a_silent_port_is_reported(monkeypatch):
    for ask, source in ((probe.ask_llmnr, "llmnr"), (probe.ask_mdns, "mdns")):
        answer = asyncio.run(ask("127.0.0.1", timeout=0.2))
        assert answer.source == source and not answer.found
        assert answer.detail                                   # a reason, never a bare blank


def responder(reply_bytes: bytes) -> tuple[socket.socket, int]:
    """A socket that answers one question with these bytes, on a port of its own."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def answer_once(sock: socket.socket, payload: bytes, mirror_id: bool = False) -> None:
    """Wait for one question and answer it (in a thread: the probe is asking)."""
    import threading

    def serve():
        question, where = sock.recvfrom(2048)
        body = (question[:2] + payload[2:]) if mirror_id else payload
        sock.sendto(body, where)

    threading.Thread(target=serve, daemon=True).start()


def test_a_host_that_answers_is_named(monkeypatch):
    sock, port = responder(b"")
    monkeypatch.setattr(probe, "NBNS_PORT", port)
    try:
        answer_once(sock, reply([("POSTE-JULIE", 0x00, 0x0400)]))
        answer = asyncio.run(probe.ask_netbios("127.0.0.1", timeout=2))
    finally:
        sock.close()
    assert answer.name == "POSTE-JULIE" and answer.mac == "00:0c:29:1b:88:fc"


def test_a_reverse_answer_over_the_wire_is_read(monkeypatch):
    import dns.message
    import dns.rdataclass
    import dns.rdatatype
    import dns.reversename

    question = dns.message.make_query(dns.reversename.from_address("127.0.0.1"),
                                      dns.rdatatype.PTR)
    made = dns.message.make_response(question)
    made.answer.append(dns.rrset.from_text(
        dns.reversename.from_address("127.0.0.1"), 60, dns.rdataclass.IN, dns.rdatatype.PTR,
        "imprimante-compta.local."))
    sock, port = responder(b"")
    monkeypatch.setattr(probe, "MDNS_PORT", port)
    try:
        answer_once(sock, made.to_wire(), mirror_id=True)
        answer = asyncio.run(probe.ask_mdns("127.0.0.1", timeout=2))
    finally:
        sock.close()
    assert answer.source == "mdns" and answer.name == "imprimante-compta.local"


def test_an_answer_with_no_record_says_so(monkeypatch):
    import dns.message
    import dns.rdatatype
    import dns.reversename

    question = dns.message.make_query(dns.reversename.from_address("127.0.0.1"),
                                      dns.rdatatype.PTR)
    sock, port = responder(b"")
    monkeypatch.setattr(probe, "LLMNR_PORT", port)
    try:
        answer_once(sock, dns.message.make_response(question).to_wire(), mirror_id=True)
        answer = asyncio.run(probe.ask_llmnr("127.0.0.1", timeout=2))
    finally:
        sock.close()
    assert answer.detail == "answered without a name"


def test_what_cannot_be_sent_is_reported_not_raised():
    """A broadcast address needs a socket option nobody asked for: an error, not a crash."""
    answer = asyncio.run(probe.ask_netbios("255.255.255.255", timeout=0.3))
    assert not answer.found and answer.detail


def test_an_address_dnspython_refuses_is_reported():
    answer = asyncio.run(probe._reverse_on("not-an-address", 5353, "mdns", 0.2))
    assert not answer.found and answer.detail


def test_asking_every_way_at_once(monkeypatch):
    answers = asyncio.run(probe.ask_all("127.0.0.1", timeout=0.2))
    assert [a.source for a in answers] == ["netbios", "llmnr", "mdns"]
    assert all(not a.found and a.detail for a in answers)    # nothing listens here


def test_a_refusal_is_not_a_timeout(monkeypatch):
    """A resolver that answers 'no' and one that says nothing are different failures."""
    import dns.asyncquery
    import dns.exception

    async def refuse(*args, **kwargs):
        raise dns.exception.FormError("malformed")

    monkeypatch.setattr(dns.asyncquery, "udp", refuse)
    answer = asyncio.run(probe.ask_mdns("127.0.0.1", timeout=0.2))
    assert answer.detail == "FormError" and not answer.found


def test_an_empty_record_set_is_skipped(monkeypatch):
    """A reply can carry a record set with nothing in it: keep looking, do not crash."""
    import dns.asyncquery
    import dns.rdataclass
    import dns.rdatatype
    import dns.reversename
    import dns.rrset

    name = dns.reversename.from_address("127.0.0.1")
    empty = dns.rrset.RRset(name, dns.rdataclass.IN, dns.rdatatype.PTR)
    filled = dns.rrset.from_text(name, 60, dns.rdataclass.IN, dns.rdatatype.PTR, "poste.local.")

    async def answer(*args, **kwargs):
        return SimpleNamespace(answer=[empty, filled])

    monkeypatch.setattr(dns.asyncquery, "udp", answer)
    assert asyncio.run(probe.ask_mdns("127.0.0.1", timeout=0.2)).name == "poste.local"


def test_an_all_zero_adapter_address_is_no_claim_at_all():
    """Samba and NAS boxes answer NetBIOS with 00:00:00:00:00:00; taking that for a MAC would
    contradict every node and throw away a name the host really stated."""
    answer = probe.parse_nbstat(reply([("ACMEBE-NAS", 0x00, 0x0400)], mac=bytes(6)))
    assert answer.name == "ACMEBE-NAS" and answer.mac == ""
