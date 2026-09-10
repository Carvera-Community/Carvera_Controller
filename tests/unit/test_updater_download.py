"""Verified firmware download and check-to-upload handoff tests."""

from __future__ import annotations

import hashlib
import io
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from carveracontroller.updater.download import DownloadCancelled, DownloadError, download_file
from carveracontroller.updater.github import FetchResult, parse_release
from carveracontroller.updater.install import fetch_firmware_bin
from carveracontroller.updater.service import check_updates


class _FakeBody:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_download_file_verifies_size_and_digest(tmp_path: Path):
    payload = b"firmware-bytes-1234"
    dest = tmp_path / "firmware.bin"
    path = download_file(
        "https://github.com/downloads/firmware.bin",
        dest,
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        open_url=lambda url, headers, timeout: _FakeBody(payload),
    )
    assert path == dest
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()


def test_download_rejects_http_and_bad_digest(tmp_path: Path):
    dest = tmp_path / "firmware.bin"
    with pytest.raises(DownloadError, match="HTTPS"):
        download_file("http://example.test/fw.bin", dest, expected_size=4, expected_sha256="ab" * 32)
    payload = b"abcd"
    with pytest.raises(DownloadError, match="checksum"):
        download_file(
            "https://github.com/downloads/firmware.bin",
            dest,
            expected_size=len(payload),
            expected_sha256="cd" * 32,
            open_url=lambda url, headers, timeout: _FakeBody(payload),
        )
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_download_size_mismatch_and_cancel_cleanup(tmp_path: Path):
    dest = tmp_path / "firmware.bin"
    payload = b"too-short"
    with pytest.raises(DownloadError, match="size"):
        download_file(
            "https://github.com/downloads/firmware.bin",
            dest,
            expected_size=64,
            expected_sha256=_sha(payload),
            open_url=lambda url, headers, timeout: _FakeBody(payload),
        )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        download_file(
            "https://github.com/downloads/firmware.bin",
            dest,
            expected_size=4,
            expected_sha256=_sha(b"abcd"),
            cancel_event=cancel,
            open_url=lambda url, headers, timeout: _FakeBody(b"abcd"),
        )
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_check_then_verified_firmware_handoff(tmp_path: Path):
    payload = b"unique-firmware-bin"
    digest = "sha256:" + _sha(payload)
    firmware_payload = {
        "tag_name": "2.1.0c",
        "name": "2.1.0c",
        "html_url": "https://github.com/Carvera-Community/Carvera_Community_Firmware/releases/tag/2.1.0c",
        "body": "## Added\n- Faster homing",
        "published_at": "2024-05-01T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "assets": [
            {
                "name": "firmware-2.1.0c.bin",
                "size": len(payload),
                "browser_download_url": "https://github.com/downloads/firmware-2.1.0c.bin",
                "digest": digest,
                "content_type": "application/octet-stream",
            }
        ],
    }
    controller_payload = {
        "tag_name": "v2.2.0",
        "name": "v2.2.0",
        "html_url": "https://github.com/Carvera-Community/Carvera_Controller/releases/tag/v2.2.0",
        "body": "Controller notes",
        "published_at": "2024-05-02T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "assets": [
            {
                "name": "CarveraController-2.2.0-x86_64.AppImage",
                "size": 20,
                "browser_download_url": "https://github.com/downloads/controller.AppImage",
                "digest": "",
                "content_type": "application/octet-stream",
            }
        ],
    }

    class _Client:
        def fetch_releases(self, url: str, cache_name: str, **_kwargs) -> FetchResult:
            body = firmware_payload if "Firmware" in url else controller_payload
            release = parse_release(body)
            assert release is not None
            return FetchResult(
                releases=(release,),
                from_cache=False,
                etag_hit=False,
                error=None,
                fetched_at=datetime.now(timezone.utc),
            )

    snapshot = check_updates(
        current_controller="2.1.0",
        current_firmware="2.0.0c",
        include_prereleases=False,
        cache_dir=tmp_path,
        platform_key="linux-x64",
        client=_Client(),
    )
    assert snapshot.controller.update_available
    assert snapshot.firmware.update_available
    assert snapshot.firmware.can_one_click
    assert snapshot.controller.matching_asset is not None

    dest_dir = tmp_path / "fw"
    path = fetch_firmware_bin(
        snapshot.firmware.latest,
        dest_dir,
        download_fn=lambda url, dest, **kwargs: download_file(
            url,
            dest,
            expected_size=kwargs["expected_size"],
            expected_sha256=kwargs["expected_sha256"],
            open_url=lambda _url, _headers, _timeout: _FakeBody(payload),
        ),
    )
    assert path.name == "firmware-2.1.0c.bin"
    assert path.read_bytes() == payload
    # Upload handoff: the controller copies this verified file to /sd/firmware.bin.
    assert snapshot.firmware.latest is not None
    assert path.exists()
