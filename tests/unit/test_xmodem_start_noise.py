"""Legacy (text protocol) uploads: console text left on the wire before the receiver's start byte
must not abort the transfer, and must not change what is sent."""

from io import BytesIO

from carveracontroller.XMODEM import ACK, CRC, EOT, XMODEM


def _send(incoming: bytes, content: bytes):
    rx = BytesIO(incoming)
    writes = []

    def getc(size, timeout=0.5):
        return bytearray(rx.read(size)) or None

    def putc(data, timeout=0.5):
        writes.append(bytes(data))
        return len(data)

    modem = XMODEM(getc, putc, "xmodem8k")
    result = modem.send_legacy(BytesIO(content), md5="0" * 32, retry=10, quiet=True)
    return result, writes


def test_status_reply_before_the_start_byte_is_skipped():
    stale = b"<Idle|MPos:-2.0000,-2.0000,-2.0000,0.5000,0.0000|WPos:357.7000,233.6800>\nInfo: Upload canceled by remote!\r\n"
    # MD5 block ACK, one data block ACK, EOT ACK.
    result, writes = _send(stale + CRC + ACK + ACK + ACK, b"G21\n")
    assert result is True
    assert writes[-1] == EOT


def test_same_bytes_sent_with_or_without_noise():
    content = b"(test)\nG21\n" * 100
    clean = _send(CRC + ACK + ACK + ACK, content)
    noisy = _send(b"ok\r\n<Idle|MPos:0,0,0>\n" + CRC + ACK + ACK + ACK, content)
    assert clean == noisy


def test_unexpected_control_bytes_still_count_as_errors():
    # Non-text garbage (not CRC/NAK/CAN/EOT) still aborts after `retry` errors.
    result, _ = _send(bytes([0x01]) * 20, b"G21\n")
    assert result is False


def _blocks(writes):
    return [w for w in writes if len(w) > 100]  # data blocks (8 KB), not single control bytes


def test_cancel_mid_transfer_stops_without_resending():
    content = b"G1 Z-1 F100\n" * 2000  # 3 data blocks
    # MD5 ACK, block 1 ACK, then the receiver cancels.
    from carveracontroller.XMODEM import CAN

    result, writes = _send(CRC + ACK + ACK + CAN + CAN, content)
    assert result is False
    assert len(_blocks(writes)) == 3  # MD5 block, block 1, block 2 once: nothing after the CAN


def test_console_text_mid_transfer_stops_without_resending():
    content = b"G1 Z-1 F100\n" * 2000
    result, writes = _send(CRC + ACK + b"Info: Upload canceled by remote!\r\n", content)
    assert result is False
    assert len(_blocks(writes)) == 2  # MD5 block and block 1, each once


def test_nak_still_resends_and_late_start_bytes_are_ignored():
    from carveracontroller.XMODEM import NAK

    content = b"G21\n"
    # Extra 'C's after block 0 (ignored), then NAK for block 1 (resend), then ACKs.
    result, writes = _send(CRC + CRC + CRC + ACK + NAK + ACK + ACK, content)
    assert result is True
    blocks = _blocks(writes)
    assert len(blocks) == 3  # MD5 once, block 1 twice
    assert blocks[1] == blocks[2]
