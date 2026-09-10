"""Verified streaming download of a GitHub release asset."""

from __future__ import annotations

import hashlib
import logging
import ssl
import threading
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import config

logger = logging.getLogger(__name__)

try:
    import certifi

    def _ssl_context() -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())

except ImportError:

    def _ssl_context() -> ssl.SSLContext:
        return ssl.create_default_context()


class DownloadError(Exception):
    """Raised when a firmware asset cannot be downloaded or verified."""


class DownloadCancelled(DownloadError):
    """Raised when the user cancels a firmware download."""


OpenUrlFn = Callable[[str, dict[str, str], float], BinaryIO]
ProgressFn = Callable[[int, int], None]


def download_file(
    url: str,
    dest: str | Path,
    *,
    expected_size: int,
    expected_sha256: str,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
    timeout: float = config.DOWNLOAD_TIMEOUT_S,
    chunk_size: int = 64 * 1024,
    open_url: OpenUrlFn | None = None,
    user_agent: str = config.USER_AGENT,
) -> Path:
    """Download *url* to *dest*, verifying size and SHA-256 before returning."""
    if not url.lower().startswith("https://"):
        raise DownloadError("Firmware downloads must use HTTPS.")
    hex_digest = (expected_sha256 or "").strip().lower()
    if len(hex_digest) != 64 or any(c not in "0123456789abcdef" for c in hex_digest):
        raise DownloadError("This release does not include a SHA-256 digest.")
    if expected_size <= 0:
        raise DownloadError("This release does not advertise a firmware file size.")

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_name(dest_path.name + ".part")
    _remove_quietly(part_path)
    _remove_quietly(dest_path)

    headers = {"User-Agent": user_agent, "Accept": "application/octet-stream"}
    opener = open_url or _open_url
    digest = hashlib.sha256()
    received = 0

    try:
        with opener(url, headers, timeout) as response, part_path.open("wb") as handle:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Firmware download cancelled.")
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if expected_size and received > expected_size:
                    raise DownloadError("Downloaded firmware is larger than GitHub advertised.")
                if progress is not None:
                    progress(received, expected_size)
    except DownloadError:
        _remove_quietly(part_path)
        raise
    except (URLError, TimeoutError, OSError) as exc:
        _remove_quietly(part_path)
        raise DownloadError("Couldn't download the firmware file.") from exc

    if received != expected_size:
        _remove_quietly(part_path)
        raise DownloadError("Downloaded firmware size does not match GitHub.")
    if digest.hexdigest() != hex_digest:
        _remove_quietly(part_path)
        raise DownloadError("Firmware checksum does not match GitHub.")

    part_path.replace(dest_path)
    if progress is not None:
        progress(received, expected_size)
    return dest_path


def _open_url(url: str, headers: dict[str, str], timeout: float) -> BinaryIO:
    request = Request(url, headers=headers, method="GET")
    return urlopen(request, timeout=timeout, context=_ssl_context())


def _remove_quietly(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Could not remove incomplete download %s", path, exc_info=True)
