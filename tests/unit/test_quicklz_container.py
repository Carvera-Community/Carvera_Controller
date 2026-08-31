"""Tests for the QuickLZ transport representation used by firmware downloads."""

import hashlib
import struct

import pytest
import quicklz

from carveracontroller.quicklz_container import (
    DownloadIntegrityError,
    QuickLZContainerError,
    finalize_download_payload,
    inspect_quicklz_container,
)


def _quicklz_container(*blocks: bytes) -> bytes:
    output = bytearray()
    checksum = 0
    for block in blocks:
        if not block:
            continue
        compressed = quicklz.compress(block)
        output.extend(struct.pack(">I", len(compressed)))
        output.extend(compressed)
        checksum = (checksum + sum(block)) & 0xFFFF
    output.extend(struct.pack(">H", checksum))
    return bytes(output)


def test_quicklz_download_is_replaced_with_exact_original_bytes(tmp_path):
    original = (
        b"alpha_steps_per_mm 400\n"
        b"beta_steps_per_mm 400\n"
        b"acceleration 500\n"
        b"network.note UTF-8: \xc3\xa4\xc3\xb6\xc3\xbc\n"
    ) * 80
    wire_payload = _quicklz_container(original[:4096], original[4096:])
    downloaded = tmp_path / "config.txt.tmp"
    downloaded.write_bytes(wire_payload)

    # This is transport data, not text; decoding it directly must not be the fix.
    with pytest.raises(UnicodeDecodeError):
        wire_payload.decode("utf-8")

    expected_md5 = hashlib.md5(original).hexdigest()
    info = finalize_download_payload(downloaded, expected_md5)

    assert info.was_compressed is True
    assert info.wire_size == len(wire_payload)
    assert info.file_size == len(original)
    assert info.md5 == expected_md5
    assert downloaded.read_bytes() == original


def test_plain_binary_download_is_not_mistaken_for_quicklz(tmp_path):
    original = b"\x00\x00not-a-quicklz-container\x81\xff"
    downloaded = tmp_path / "binary.dat"
    downloaded.write_bytes(original)

    info = finalize_download_payload(downloaded, hashlib.md5(original).hexdigest())

    assert info.was_compressed is False
    assert downloaded.read_bytes() == original


def test_explicit_lz_download_keeps_the_container_bytes(tmp_path):
    original = b"epsilon_steps_per_mm 400\n" * 50
    wire_payload = _quicklz_container(original)
    downloaded = tmp_path / "program.nc.lz"
    downloaded.write_bytes(wire_payload)

    expected_md5 = hashlib.md5(wire_payload).hexdigest()
    info = finalize_download_payload(downloaded, expected_md5, decode_quicklz=False)

    assert info.was_compressed is False
    assert info.md5 == expected_md5
    assert downloaded.read_bytes() == wire_payload


def test_quicklz_checksum_failure_does_not_replace_wire_payload(tmp_path):
    original = b"gamma_steps_per_mm 400\n" * 50
    wire_payload = bytearray(_quicklz_container(original))
    wire_payload[-1] ^= 0x01
    downloaded = tmp_path / "config.txt.tmp"
    downloaded.write_bytes(wire_payload)

    assert inspect_quicklz_container(downloaded) is not None
    with pytest.raises(QuickLZContainerError, match="checksum mismatch"):
        finalize_download_payload(downloaded, hashlib.md5(original).hexdigest())

    assert downloaded.read_bytes() == wire_payload


def test_decoded_md5_mismatch_does_not_replace_wire_payload(tmp_path):
    original = b"delta_steps_per_mm 400\n" * 50
    wire_payload = _quicklz_container(original)
    downloaded = tmp_path / "config.txt.tmp"
    downloaded.write_bytes(wire_payload)

    with pytest.raises(DownloadIntegrityError, match="expected MD5"):
        finalize_download_payload(downloaded, hashlib.md5(b"different").hexdigest())

    assert downloaded.read_bytes() == wire_payload
