"""Link-loss detection and reconnect attempt accounting."""

import socket
import sys

import pytest
import serial

from carveracontroller.Controller import Controller
from carveracontroller.USBStream import USBStream
from carveracontroller.WIFIStream import _LINK_LOSS_SEC, _TCP_RXT_CONNDROPTIME_DARWIN, WIFIStream


class _PeekSocket:
    def __init__(self, payload):
        self.payload = payload
        self.flags = None

    def recv(self, _n, flags=0):
        self.flags = flags
        return self.payload


class _Serial:
    def __init__(self, is_open=True, waiting=0, error=None):
        self.is_open = is_open
        self._waiting = waiting
        self._error = error

    @property
    def in_waiting(self):
        if self._error is not None:
            raise self._error
        return self._waiting


def _wifi(payload=b""):
    stream = WIFIStream.__new__(WIFIStream)
    stream.socket = _PeekSocket(payload)
    return stream


def _select(readable, errored):
    def _fake(_r, _w, _e, _timeout):
        return (readable, [], errored)

    return _fake


def test_wifi_idle_socket_is_up(monkeypatch):
    stream = _wifi()
    monkeypatch.setattr("carveracontroller.WIFIStream.select.select", _select([], []))
    assert stream.is_link_up() is True
    assert stream.socket.flags is None


def test_wifi_fin_is_down_and_peek_does_not_consume(monkeypatch):
    stream = _wifi(b"")
    monkeypatch.setattr("carveracontroller.WIFIStream.select.select", _select([stream.socket], []))
    assert stream.is_link_up() is False
    assert stream.socket.flags & socket.MSG_PEEK
    assert stream.socket.payload == b""


def test_wifi_pending_byte_stays_up(monkeypatch):
    stream = _wifi(b"?")
    monkeypatch.setattr("carveracontroller.WIFIStream.select.select", _select([stream.socket], []))
    assert stream.is_link_up() is True


def test_wifi_error_fd_and_oserror_are_down(monkeypatch):
    stream = _wifi()
    monkeypatch.setattr("carveracontroller.WIFIStream.select.select", _select([], [stream.socket]))
    assert stream.is_link_up() is False

    def _boom(*_args):
        raise OSError("reset")

    monkeypatch.setattr("carveracontroller.WIFIStream.select.select", _boom)
    assert stream.is_link_up() is False


def test_wifi_missing_socket_is_down():
    stream = WIFIStream.__new__(WIFIStream)
    stream.socket = None
    assert stream.is_link_up() is False


def test_arm_link_loss_detection_sets_keepalive_and_retransmit_limit():
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        stream = WIFIStream.__new__(WIFIStream)
        stream.socket = sock
        stream._arm_link_loss_detection()
        # macOS getsockopt(SO_KEEPALIVE) returns the idle time, not the 1 we stored.
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        if hasattr(socket, "TCP_KEEPALIVE"):
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE) == _LINK_LOSS_SEC
        if hasattr(socket, "TCP_USER_TIMEOUT"):
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == _LINK_LOSS_SEC * 1000
        if sys.platform == "darwin":
            assert sock.getsockopt(socket.IPPROTO_TCP, _TCP_RXT_CONNDROPTIME_DARWIN) == _LINK_LOSS_SEC
    finally:
        sock.close()


def test_usb_open_port_is_up_and_unplug_is_down():
    stream = USBStream.__new__(USBStream)
    stream.serial = None
    assert stream.is_link_up() is False

    stream.serial = _Serial(is_open=False)
    assert stream.is_link_up() is False

    stream.serial = _Serial(waiting=0)
    assert stream.is_link_up() is True

    stream.serial = _Serial(error=OSError(6, "Device not configured"))
    assert stream.is_link_up() is False

    stream.serial = _Serial(error=serial.SerialException("device gone"))
    assert stream.is_link_up() is False


def test_usb_probe_does_not_swallow_programming_errors():
    stream = USBStream.__new__(USBStream)

    class _Broken:
        is_open = True

        @property
        def in_waiting(self):
            raise AttributeError("no ioctl")

    stream.serial = _Broken()
    with pytest.raises(AttributeError):
        stream.is_link_up()


def test_link_lost_closes_only_when_the_probe_fails():
    ctl = Controller.__new__(Controller)
    closed = []
    ctl.close = lambda: closed.append(True)

    ctl.stream = None
    assert ctl._link_lost() is False
    assert closed == []

    class _Up:
        def is_link_up(self):
            return True

    ctl.stream = _Up()
    assert ctl._link_lost() is False
    assert closed == []

    class _Down:
        def is_link_up(self):
            return False

    ctl.stream = _Down()
    assert ctl._link_lost() is True
    assert closed == [True]

    class _Raises:
        def is_link_up(self):
            raise RuntimeError("probe bug")

    ctl.stream = _Raises()
    assert ctl._link_lost() is True
    assert len(closed) == 2
