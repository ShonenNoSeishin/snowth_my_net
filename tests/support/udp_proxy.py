"""UDP proxy that records the PDU type of every SNMPv1/v2c request it forwards.

Used to prove, on the wire, that snowth_my_net only ever sends GetRequest (0xA0),
GetNextRequest (0xA1) and GetBulkRequest (0xA5). SNMPv3 PDUs are encrypted, so the proxy is
used with a v2c credential.
"""

from __future__ import annotations

import select
import socket
import threading

GET, GET_NEXT, RESPONSE, SET, GET_BULK = 0xA0, 0xA1, 0xA2, 0xA3, 0xA5


def _length(buf: bytes, i: int) -> tuple[int, int]:
    first = buf[i]
    if first < 0x80:
        return first, i + 1
    n = first & 0x7F
    return int.from_bytes(buf[i + 1:i + 1 + n], "big"), i + 1 + n


def pdu_tag(message: bytes) -> int | None:
    """Tag of the PDU inside an SNMPv1/v2c message, None when it cannot be read."""
    try:
        if message[0] != 0x30:
            return None
        _, i = _length(message, 1)
        if message[i] != 0x02:          # version
            return None
        size, i = _length(message, i + 1)
        i += size
        if message[i] != 0x04:          # community (absent in SNMPv3)
            return None
        size, i = _length(message, i + 1)
        return message[i + size]
    except IndexError:
        return None


class RecordingProxy(threading.Thread):
    def __init__(self, listen: tuple[str, int], upstream: tuple[str, int]) -> None:
        super().__init__(daemon=True)
        self.upstream = upstream
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(listen)
        self.address = self.sock.getsockname()
        self.tags: list[int | None] = []
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            ready, _, _ = select.select([self.sock], [], [], 0.1)
            if not ready:
                continue
            data, client = self.sock.recvfrom(65535)
            self.tags.append(pdu_tag(data))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as up:
                up.settimeout(3)
                up.sendto(data, self.upstream)
                try:
                    reply, _ = up.recvfrom(65535)
                except TimeoutError:
                    continue
            self.sock.sendto(reply, client)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2)
        self.sock.close()
