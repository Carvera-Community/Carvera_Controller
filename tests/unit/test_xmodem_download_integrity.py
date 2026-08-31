"""Tests for download MD5 integrity in legacy and Makera framed transfers."""

import hashlib
import logging
import struct
from io import BytesIO

import quicklz

from carveracontroller.protocols.framing import (
    PTYPE_FILE_CAN,
    PTYPE_FILE_DATA,
    PTYPE_FILE_END,
    PTYPE_FILE_MD5,
    PTYPE_FILE_VIEW,
    build_frame,
)
from carveracontroller.quicklz_container import finalize_download_payload
from carveracontroller.XMODEM import ACK, CAN, CRC, EOT, XMODEM

# What stock Z1 firmware sends instead of a digest: 32 characters, but not hex.
Z1_PLACEHOLDER_MD5 = b"default_md5_hash_value_32_bytes_"


def _packet(modem, sequence, payload):
    packet_size = 8192
    header = modem._make_send_header(packet_size, sequence)
    data = bytes([len(payload) >> 8, len(payload) & 0xFF]) + payload.ljust(packet_size, modem.pad)
    checksum = modem._make_send_checksum(1, data)
    return bytes(header + data + checksum)


def _receive_legacy(advertised_payload, received_payload, local_md5="", advertised_md5=None):
    transport = BytesIO()
    writes = []

    def getc(size, timeout=0.5):
        return transport.read(size) or None

    def putc(data, timeout=0.5):
        writes.append(data)
        return len(data)

    modem = XMODEM(getc, putc, "xmodem8k")
    if advertised_md5 is None:
        advertised_md5 = hashlib.md5(advertised_payload).hexdigest().encode()
    transport.write(_packet(modem, 0, advertised_md5))
    if received_payload:
        transport.write(_packet(modem, 1, received_payload))
    transport.write(EOT)
    transport.seek(0)

    output = BytesIO()
    result = modem.recv_legacy(output, md5=local_md5)
    return result, output.getvalue(), writes, modem


def _receive_framed(advertised_payload, received_payload, local_md5="", advertised_md5=None):
    transport = BytesIO()
    writes = []

    def getc(size, timeout=0.5):
        return transport.read(size) or None

    def putc(data, timeout=0.5):
        writes.append(data)
        return len(data)

    modem = XMODEM(getc, putc, "xmodem8k")
    if advertised_md5 is None:
        advertised_md5 = hashlib.md5(advertised_payload).hexdigest().encode()
    transport.write(build_frame(PTYPE_FILE_MD5, advertised_md5))
    transport.write(build_frame(PTYPE_FILE_VIEW, (1).to_bytes(4, "big") + (8192).to_bytes(2, "big")))
    transport.write(build_frame(PTYPE_FILE_DATA, (1).to_bytes(4, "big") + received_payload))
    transport.seek(0)

    output = BytesIO()
    result = modem.recv(output, md5=local_md5, retry=5)
    return result, output.getvalue(), writes, modem


def test_legacy_accepts_matching_md5():
    payload = b"G0 X1 Y2\nM2\n"

    result, output, writes, modem = _receive_legacy(payload, payload)

    assert result is not None and result > 0
    assert output == payload
    assert writes == [CRC, ACK, ACK, ACK]
    assert modem.deferred_download_md5 is None


def test_legacy_short_circuits_when_uppercase_local_md5_matches():
    payload = b"G0 X1 Y2\nM2\n"
    local_md5 = hashlib.md5(payload).hexdigest().upper()

    result, output, writes, modem = _receive_legacy(payload, payload, local_md5=local_md5)

    assert result == 0
    assert output == b""
    assert writes == [CRC, CAN, CAN, CAN]


def test_legacy_rejects_plain_md5_mismatch():
    expected = b"G0 X1 Y2\nG1 X3 Y4\nM2\n"
    truncated = b"G0 X1 Y2\n"

    result, output, writes, modem = _receive_legacy(expected, truncated)

    assert result is None
    assert output == truncated
    assert writes == [CRC, ACK, ACK, ACK]
    assert modem.deferred_download_md5 is None


def test_legacy_skips_check_when_advertised_md5_empty(caplog):
    payload = b"G0 X1 Y2\nM2\n"

    with caplog.at_level(logging.INFO, logger="xmodem.XMODEM"):
        result, output, writes, modem = _receive_legacy(payload, payload, advertised_md5=b"")

    assert result is not None and result > 0
    assert output == payload
    assert modem.deferred_download_md5 is None
    assert any("skipped" in record.getMessage() for record in caplog.records)


def test_legacy_skips_check_when_advertised_md5_is_not_hex(caplog):
    """Stock Z1 firmware answers md5sum with a 32-character placeholder, not a digest."""
    payload = b"G0 X1 Y2\nM2\n"

    with caplog.at_level(logging.INFO, logger="xmodem.XMODEM"):
        result, output, writes, modem = _receive_legacy(payload, payload, advertised_md5=Z1_PLACEHOLDER_MD5)

    assert result is not None and result > 0
    assert output == payload
    assert modem.download_md5_failed is False
    assert any("skipped" in record.getMessage() for record in caplog.records)


def test_legacy_defers_md5_check_for_lz_payload():
    advertised_for = b"original uncompressed content"
    lz_payload = b"\x00\x00" + b"compressed-bytes"
    advertised = hashlib.md5(advertised_for).hexdigest()

    result, output, writes, modem = _receive_legacy(advertised_for, lz_payload)

    assert result is not None and result > 0
    assert output == lz_payload
    assert modem.deferred_download_md5 == advertised


def test_framed_accepts_matching_md5():
    payload = b"G0 X1 Y2\nM2\n"

    result, output, writes, modem = _receive_framed(payload, payload)

    assert result == len(payload)
    assert output == payload
    assert any(frame[4] == PTYPE_FILE_END for frame in writes)
    assert modem.deferred_download_md5 is None


def test_framed_rejects_plain_md5_mismatch():
    expected = b"G0 X1 Y2\nG1 X3 Y4\nM2\n"
    truncated = b"G0 X1 Y2\n"

    result, output, writes, modem = _receive_framed(expected, truncated)

    assert result is None
    assert output == truncated
    assert modem.deferred_download_md5 is None


def test_framed_skips_check_when_advertised_md5_empty(caplog):
    payload = b"G0 X1 Y2\nM2\n"

    with caplog.at_level(logging.INFO, logger="xmodem.XMODEM"):
        result, output, writes, modem = _receive_framed(payload, payload, advertised_md5=b"")

    assert result == len(payload)
    assert output == payload
    assert modem.deferred_download_md5 is None
    assert any("skipped" in record.getMessage() for record in caplog.records)


def test_framed_skips_check_when_advertised_md5_is_not_hex(caplog):
    payload = b"G0 X1 Y2\nM2\n"

    with caplog.at_level(logging.INFO, logger="xmodem.XMODEM"):
        result, output, writes, modem = _receive_framed(payload, payload, advertised_md5=Z1_PLACEHOLDER_MD5)

    assert result == len(payload)
    assert output == payload
    assert modem.download_md5_failed is False
    assert any("skipped" in record.getMessage() for record in caplog.records)


def test_framed_defers_md5_check_for_lz_payload():
    advertised_for = b"original uncompressed content"
    lz_payload = b"\x00\x00" + b"compressed-bytes"
    advertised = hashlib.md5(advertised_for).hexdigest()

    result, output, writes, modem = _receive_framed(advertised_for, lz_payload)

    assert result == len(lz_payload)
    assert output == lz_payload
    assert modem.deferred_download_md5 == advertised


def test_framed_quicklz_payload_decodes_to_exact_advertised_file(tmp_path):
    original = b"alpha_steps_per_mm 400\nbeta_steps_per_mm 400\n" * 100
    compressed = quicklz.compress(original)
    wire_payload = struct.pack(">I", len(compressed)) + compressed + struct.pack(">H", sum(original) & 0xFFFF)

    result, output, _writes, modem = _receive_framed(original, wire_payload)

    assert result == len(wire_payload)
    assert output == wire_payload
    downloaded = tmp_path / "config.txt.tmp"
    downloaded.write_bytes(output)
    info = finalize_download_payload(downloaded, modem.deferred_download_md5)
    assert info.was_compressed is True
    assert downloaded.read_bytes() == original
    assert hashlib.md5(downloaded.read_bytes()).hexdigest() == hashlib.md5(original).hexdigest()


def test_framed_short_circuits_when_uppercase_local_md5_matches():
    payload = b"G0 X1 Y2\nM2\n"
    local_md5 = hashlib.md5(payload).hexdigest().upper()

    result, output, writes, modem = _receive_framed(payload, payload, local_md5=local_md5)

    assert result == 0
    assert output == b""
    assert len(writes) == 1
    assert writes[0][4] == PTYPE_FILE_CAN


def test_finalize_download_integrity_policies():
    modem = XMODEM(lambda *_: None, lambda *_: 1, "xmodem8k")
    received = hashlib.md5()
    received.update(b"abc")

    assert modem._finalize_download_integrity(b"", received, 3, b"abc") is True
    assert modem.deferred_download_md5 is None

    lz_received = hashlib.md5()
    lz_received.update(b"\x00\x00data")
    advertised = hashlib.md5(b"plain").hexdigest().encode()
    assert modem._finalize_download_integrity(advertised, lz_received, 6, b"\x00\x00data") is True
    assert modem.deferred_download_md5 == advertised.decode()

    plain = hashlib.md5()
    plain.update(b"plain")
    assert modem._finalize_download_integrity(advertised, plain, 5, b"plain") is True
    assert modem.deferred_download_md5 is None

    wrong = hashlib.md5()
    wrong.update(b"other")
    assert modem._finalize_download_integrity(advertised, wrong, 5, b"other") is False
    assert modem.deferred_download_md5 is None
