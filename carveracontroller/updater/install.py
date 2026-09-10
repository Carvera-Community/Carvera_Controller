"""Download a verified firmware binary from a GitHub release."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .download import DownloadError, download_file
from .models import Release
from .platform import select_firmware_asset

ProgressFn = Callable[[int, int], None]


def fetch_firmware_bin(
    release: Release,
    dest_dir: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
    download_fn=download_file,
) -> Path:
    """Download and verify the firmware .bin for *release* into *dest_dir*."""
    asset = select_firmware_asset(release)
    if asset is None:
        raise DownloadError("This release does not contain a unique firmware file.")
    if not asset.sha256:
        raise DownloadError("This firmware file cannot be verified because GitHub did not publish a checksum.")
    dest = Path(dest_dir) / asset.name
    return download_fn(
        asset.browser_download_url,
        dest,
        expected_size=asset.size,
        expected_sha256=asset.sha256,
        cancel_event=cancel_event,
        progress=progress,
    )
