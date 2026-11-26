"""Tests for WIFIStream socket write semantics."""

import socket
import struct
import threading

from carveracontroller.protocols.framing import PTYPE_FILE_DATA, build_frame
from carveracontroller.WIFIStream import WIFIStream
from carveracontroller.XMODEM import XMODEM


class DeterministicShortWriteSocket:
    """Socket double that accepts only a prefix from each ``send`` call."""

    def __init__(self, short_write_size):
        self.short_write_size = short_write_size
        self.send_calls = 0
        self.sendall_calls = 0
        self.wire = bytearray()

    def send(self, data):
        self.send_calls += 1
        accepted = min(self.short_write_size, len(data))
        self.wire.extend(data[:accepted])
        return accepted

    def sendall(self, data):
        self.sendall_calls += 1
        self.wire.extend(data)


def _xmodem8k_frame():
    modem = XMODEM(lambda _size, _timeout=0.5: None, lambda data, _timeout=0.5: len(data))
    payload = b"x" * 8192
    framed_payload = bytes([len(payload) >> 8, len(payload) & 0xFF]) + payload
    return bytes(modem._make_send_header(8192, 1) + framed_payload + modem._make_send_checksum(1, framed_payload))


def _makera_file_data_frame():
    """Full Makera FILE_DATA frame as emitted by XMODEM.send() via putc."""
    seq = struct.pack(">I", 1)
    file_data = b"x" * 8192
    return build_frame(PTYPE_FILE_DATA, seq + file_data)


def _assert_putc_writes_complete_frame(frame):
    stream = WIFIStream.__new__(WIFIStream)
    stream.socket = DeterministicShortWriteSocket(short_write_size=2048)

    result = stream.putc(frame)

    assert len(stream.socket.wire) == len(frame)
    assert bytes(stream.socket.wire) == frame
    assert stream.socket.send_calls == 0
    assert stream.socket.sendall_calls == 1
    assert result == len(frame)


def test_putc_sends_the_complete_xmodem_frame_and_returns_its_length():
    frame = _xmodem8k_frame()
    assert len(frame) == 8199, "fixture must model a complete xmodem8k frame"
    _assert_putc_writes_complete_frame(frame)


def test_putc_sends_the_complete_makera_file_data_frame_and_returns_its_length():
    frame = _makera_file_data_frame()
    assert len(frame) == 8205, "fixture must model a complete Makera FILE_DATA frame"
    _assert_putc_writes_complete_frame(frame)


def test_open_sets_tcp_nodelay():
    """open() should disable Nagle's algorithm via TCP_NODELAY."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept():
        conn, _ = srv.accept()
        conn.close()

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()

    stream = WIFIStream()
    stream.open(f"127.0.0.1:{port}")
    try:
        assert stream.socket.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
    finally:
        stream.close()
        thread.join(timeout=2.0)
        srv.close()
