"""Read the block-framed QuickLZ files used by the Carvera firmware cache."""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

import quicklz

BLOCK_HEADER_SIZE = 4
CHECKSUM_SIZE = 2
QUICKLZ_LONG_HEADER_SIZE = 9
QUICKLZ_SHORT_HEADER_SIZE = 3


class QuickLZContainerError(ValueError):
    """The payload looks like a Carvera QuickLZ container but is invalid."""


class DownloadIntegrityError(ValueError):
    """The decoded payload does not match the MD5 advertised by the machine."""


@dataclass(frozen=True)
class QuickLZContainerInfo:
    block_count: int
    compressed_size: int
    uncompressed_size: int
    checksum: int


@dataclass(frozen=True)
class DownloadPayloadInfo:
    was_compressed: bool
    wire_size: int
    file_size: int
    md5: str | None


def _quicklz_header_sizes(header: bytes) -> tuple[int, int, int] | None:
    """Return header, compressed and uncompressed sizes from a QuickLZ header."""
    if not header or header[0] & 0xC0 != 0x40:
        return None

    size_width = 4 if header[0] & 0x02 else 1
    header_size = QUICKLZ_LONG_HEADER_SIZE if size_width == 4 else QUICKLZ_SHORT_HEADER_SIZE
    if len(header) < header_size:
        return None

    compressed_size = int.from_bytes(header[1 : 1 + size_width], "little")
    uncompressed_size = int.from_bytes(header[1 + size_width : 1 + 2 * size_width], "little")
    if compressed_size < header_size or uncompressed_size <= 0:
        return None
    return header_size, compressed_size, uncompressed_size


def inspect_quicklz_container(filename: str | os.PathLike[str]) -> QuickLZContainerInfo | None:
    """Identify a structurally valid Carvera QuickLZ container without decoding it.

    The firmware format is a sequence of ``uint32_be length + QuickLZ block``
    records followed by a ``uint16_be`` additive checksum of the original file.
    Merely checking for the historical ``00 00`` prefix is not sufficient because
    that prefix is only the high half of the first block length.
    """
    file_size = os.path.getsize(filename)
    data_end = file_size - CHECKSUM_SIZE
    if data_end < BLOCK_HEADER_SIZE + QUICKLZ_SHORT_HEADER_SIZE:
        return None

    block_count = 0
    uncompressed_size = 0
    position = 0
    with open(filename, "rb") as source:
        while position < data_end:
            if data_end - position < BLOCK_HEADER_SIZE:
                return None
            length_data = source.read(BLOCK_HEADER_SIZE)
            if len(length_data) != BLOCK_HEADER_SIZE:
                return None
            block_size = struct.unpack(">I", length_data)[0]
            position += BLOCK_HEADER_SIZE
            if block_size < QUICKLZ_SHORT_HEADER_SIZE or block_size > data_end - position:
                return None

            header = source.read(min(block_size, QUICKLZ_LONG_HEADER_SIZE))
            sizes = _quicklz_header_sizes(header)
            if sizes is None:
                return None
            _header_size, quicklz_size, decoded_size = sizes
            if quicklz_size != block_size:
                return None

            source.seek(block_size - len(header), os.SEEK_CUR)
            position += block_size
            block_count += 1
            uncompressed_size += decoded_size

        if position != data_end:
            return None
        checksum_data = source.read(CHECKSUM_SIZE)
        if len(checksum_data) != CHECKSUM_SIZE or source.read(1):
            return None

    return QuickLZContainerInfo(
        block_count=block_count,
        compressed_size=file_size,
        uncompressed_size=uncompressed_size,
        checksum=struct.unpack(">H", checksum_data)[0],
    )


def decompress_quicklz_container(
    input_filename: str | os.PathLike[str], output_filename: str | os.PathLike[str]
) -> QuickLZContainerInfo:
    """Decode and checksum a Carvera QuickLZ container into ``output_filename``."""
    info = inspect_quicklz_container(input_filename)
    if info is None:
        raise QuickLZContainerError("not a valid Carvera QuickLZ container")

    checksum = 0
    written = 0
    try:
        with open(input_filename, "rb") as source, open(output_filename, "wb") as destination:
            for _ in range(info.block_count):
                block_size_data = source.read(BLOCK_HEADER_SIZE)
                block_size = struct.unpack(">I", block_size_data)[0]
                block = source.read(block_size)
                try:
                    decoded = quicklz.decompress(block)
                except Exception as exc:
                    raise QuickLZContainerError("QuickLZ block decompression failed") from exc
                header_sizes = _quicklz_header_sizes(block[:QUICKLZ_LONG_HEADER_SIZE])
                if header_sizes is None or len(decoded) != header_sizes[2]:
                    raise QuickLZContainerError("QuickLZ block decoded to an unexpected size")
                destination.write(decoded)
                written += len(decoded)
                checksum = (checksum + sum(decoded)) & 0xFFFF

        if written != info.uncompressed_size:
            raise QuickLZContainerError(f"decoded size mismatch: expected {info.uncompressed_size}, got {written}")
        if checksum != info.checksum:
            raise QuickLZContainerError(f"checksum mismatch: expected {info.checksum:04x}, got {checksum:04x}")
    except Exception:
        try:
            os.remove(output_filename)
        except OSError:
            pass
        raise

    return info


def finalize_download_payload(
    filename: str | os.PathLike[str], expected_md5: str | None = None, *, decode_quicklz: bool = True
) -> DownloadPayloadInfo:
    """Decode firmware-cache transport data atomically and verify the original MD5.

    ``expected_md5`` is the digest advertised by the firmware. For cached QuickLZ
    transfers it describes the uncompressed file, not the bytes sent on the wire.
    Set ``decode_quicklz`` to false when the user explicitly requested an ``.lz``
    file and the compressed container is therefore the file itself.
    """
    path = Path(filename)
    wire_size = path.stat().st_size
    container = inspect_quicklz_container(path) if decode_quicklz else None
    decoded_path: str | None = None

    try:
        if container is not None:
            descriptor, decoded_path = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".decoded", dir=str(path.parent)
            )
            os.close(descriptor)
            decompress_quicklz_container(path, decoded_path)
            digest = _md5(decoded_path)
            file_size = os.path.getsize(decoded_path)
        else:
            digest = _md5(path) if expected_md5 else None
            file_size = wire_size

        if expected_md5 and digest != expected_md5.strip().lower():
            raise DownloadIntegrityError(f"expected MD5 {expected_md5}, got {digest}")

        if decoded_path is not None:
            os.replace(decoded_path, path)
            decoded_path = None

        return DownloadPayloadInfo(
            was_compressed=container is not None,
            wire_size=wire_size,
            file_size=file_size,
            md5=digest,
        )
    finally:
        if decoded_path is not None:
            try:
                os.remove(decoded_path)
            except OSError:
                pass


def _md5(filename: str | os.PathLike[str]) -> str:
    digest = hashlib.md5()
    with open(filename, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
