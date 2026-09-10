"""GitHub Releases client, filtering, cache, and channel evaluation tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from carveracontroller.updater import config
from carveracontroller.updater.github import (
    FetchResult,
    GitHubError,
    GitHubReleasesClient,
    HttpResponse,
    filter_releases,
    parse_release,
    pick_latest,
)
from carveracontroller.updater.service import (
    apply_current_versions,
    evaluate_channel,
    snapshot_from_fetches,
    snapshot_with_prereleases,
)


def _payload(tag, *, prerelease=False, draft=False, body="notes", published="2024-01-01T00:00:00Z", assets=None):
    return {
        "tag_name": tag,
        "name": tag,
        "html_url": f"https://github.com/org/repo/releases/tag/{tag}",
        "body": body,
        "published_at": published,
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets or [],
    }


def _asset_payload(name, *, size=10, digest="", url="https://github.com/downloads/a.bin"):
    return {
        "name": name,
        "size": size,
        "browser_download_url": url,
        "digest": digest,
        "content_type": "application/octet-stream",
    }


def test_parse_release_reads_digest_and_skips_nameless_assets():
    release = parse_release(
        _payload(
            "v2.2.0",
            assets=[
                _asset_payload("app.exe", size=12, digest="sha256:" + "ab" * 32),
                {"size": 1, "browser_download_url": "https://x"},
            ],
        )
    )
    assert release is not None
    assert len(release.assets) == 1
    assert release.assets[0].sha256 == "ab" * 32


def test_filter_releases_skips_drafts_dev_and_optional_rcs():
    releases = (
        parse_release(_payload("v2.1.0")),
        parse_release(_payload("v2.2.0-RC1", prerelease=True)),
        parse_release(_payload("dev")),
        parse_release(_payload("v2.0.0", draft=True)),
        parse_release(_payload("not-a-version")),
    )
    releases = tuple(item for item in releases if item is not None)
    stable = filter_releases(releases, include_prereleases=False)
    assert [item.tag_name for item in stable] == ["v2.1.0"]
    with_rc = filter_releases(releases, include_prereleases=True)
    assert [item.tag_name for item in with_rc] == ["v2.1.0", "v2.2.0-RC1"]


def test_pick_latest_orders_rc_below_matching_stable():
    releases = tuple(
        parse_release(_payload(tag, prerelease="RC" in tag)) for tag in ("v2.2.0-RC1", "v2.2.0-RC2", "v2.2.0", "v2.1.0")
    )
    latest = pick_latest(releases)
    assert latest is not None
    assert latest.tag_name == "v2.2.0"
    rc_only = pick_latest(filter_releases(releases, include_prereleases=True)[:2])
    assert rc_only is not None
    assert rc_only.tag_name == "v2.2.0-RC2"


def test_firmware_c_channel_evaluation():
    firmware = parse_release(
        _payload(
            "2.1.0c",
            assets=[_asset_payload("firmware-2.1.0c.bin", size=32, digest="sha256:" + "cd" * 32)],
        )
    )
    rc = parse_release(_payload("2.2.0c-RC1", prerelease=True, published="2024-02-01T00:00:00Z"))
    status = evaluate_channel(
        (firmware, rc),
        "2.0.0c",
        include_prereleases=False,
        product="firmware",
        require_current=True,
    )
    assert status.update_available
    assert status.latest_label == "2.1.0c"
    assert status.can_one_click
    disconnected = evaluate_channel(
        (firmware,),
        "",
        include_prereleases=False,
        product="firmware",
        require_current=True,
    )
    assert not disconnected.update_available
    with_rc = evaluate_channel(
        (firmware, rc),
        "2.1.0c",
        include_prereleases=True,
        product="firmware",
        require_current=True,
    )
    assert with_rc.update_available
    assert with_rc.latest_label == "2.2.0c-RC1"


def test_github_client_etag_cache_and_stale_fallback(tmp_path: Path):
    url = config.CONTROLLER_RELEASES_URL
    payload = [_payload("v2.2.0")]
    calls: list[tuple[int, dict[str, str]]] = []
    state = {"status": 200}

    def request(req_url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append((state["status"], dict(headers)))
        if state["status"] == 304:
            return HttpResponse(304, {"etag": '"abc"'}, b"")
        if state["status"] >= 400:
            raise GitHubError("GitHub rate limit reached. Try again later.")
        return HttpResponse(200, {"etag": '"abc"'}, json.dumps(payload).encode("utf-8"))

    client = GitHubReleasesClient(cache_dir=tmp_path, request=request)
    first = client.fetch_releases(url, config.CONTROLLER_CACHE_NAME)
    assert not first.from_cache and not first.etag_hit
    cache_file = tmp_path / config.CONTROLLER_CACHE_NAME
    assert cache_file.is_file()
    assert not cache_file.with_suffix(cache_file.suffix + ".tmp").exists()

    state["status"] = 304
    second = client.fetch_releases(url, config.CONTROLLER_CACHE_NAME)
    assert second.etag_hit
    assert second.error is None
    assert calls[1][1].get("If-None-Match") == '"abc"'

    state["status"] = 403
    third = client.fetch_releases(url, config.CONTROLLER_CACHE_NAME)
    assert third.from_cache
    assert third.error is not None
    assert "rate limit" in third.error.lower()
    assert third.releases[0].tag_name == "v2.2.0"


def test_github_client_skips_http_when_cache_is_fresh(tmp_path: Path):
    cache = {
        "etag": '"fresh"',
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "releases": [_payload("v2.2.0")],
    }
    (tmp_path / config.CONTROLLER_CACHE_NAME).write_text(json.dumps(cache), encoding="utf-8")
    calls: list[str] = []

    def request(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append(url)
        raise AssertionError("fresh cache must not call GitHub")

    client = GitHubReleasesClient(cache_dir=tmp_path, request=request)
    result = client.fetch_releases(config.CONTROLLER_RELEASES_URL, config.CONTROLLER_CACHE_NAME, max_age_s=3600)
    assert result.from_cache
    assert result.error is None
    assert result.releases[0].tag_name == "v2.2.0"
    assert calls == []


def test_github_client_ignores_ttl_when_max_age_is_unset(tmp_path: Path):
    cache = {
        "etag": '"fresh"',
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "releases": [_payload("v2.2.0")],
    }
    (tmp_path / config.CONTROLLER_CACHE_NAME).write_text(json.dumps(cache), encoding="utf-8")
    calls: list[str] = []

    def request(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append(url)
        return HttpResponse(200, {"etag": '"new"'}, json.dumps([_payload("v2.3.0")]).encode("utf-8"))

    client = GitHubReleasesClient(cache_dir=tmp_path, request=request)
    result = client.fetch_releases(config.CONTROLLER_RELEASES_URL, config.CONTROLLER_CACHE_NAME)
    assert not result.from_cache
    assert result.releases[0].tag_name == "v2.3.0"
    assert calls


def test_github_client_reports_error_without_cache(tmp_path: Path):
    def request(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        raise GitHubError("Couldn't reach GitHub. Check your internet connection.")

    client = GitHubReleasesClient(cache_dir=tmp_path, request=request)
    result = client.fetch_releases(config.FIRMWARE_RELEASES_URL, config.FIRMWARE_CACHE_NAME)
    assert result.releases == ()
    assert result.error is not None
    assert not result.from_cache


def test_snapshot_apply_current_versions_refreshes_firmware_flag():
    firmware = parse_release(_payload("2.1.0c"))
    assert firmware is not None
    fetch = FetchResult(
        releases=(firmware,),
        from_cache=False,
        etag_hit=False,
        error=None,
        fetched_at=datetime.now(timezone.utc),
    )
    empty_fetch = FetchResult(releases=(), from_cache=False, etag_hit=False, error=None, fetched_at=None)
    snapshot = snapshot_from_fetches(
        empty_fetch,
        fetch,
        current_controller="2.2.0",
        current_firmware="",
        include_prereleases=False,
        platform_key="linux-x64",
    )
    assert not snapshot.firmware.update_available
    updated = apply_current_versions(snapshot, current_controller="2.2.0", current_firmware="2.0.0c")
    assert updated.firmware.update_available
    same = apply_current_versions(snapshot, current_controller="2.2.0", current_firmware="2.1.0c")
    assert not same.firmware.update_available


def test_snapshot_with_prereleases_refilters_without_refetch():
    stable = parse_release(_payload("v2.1.0"))
    rc = parse_release(_payload("v2.2.0-RC1", prerelease=True))
    assert stable is not None and rc is not None
    fetch = FetchResult(
        releases=(stable, rc),
        from_cache=True,
        etag_hit=False,
        error=None,
        fetched_at=datetime.now(timezone.utc),
    )
    empty = FetchResult(releases=(), from_cache=True, etag_hit=False, error=None, fetched_at=None)
    stable_only = snapshot_from_fetches(
        fetch,
        empty,
        current_controller="2.1.0",
        current_firmware="",
        include_prereleases=False,
        platform_key="linux-x64",
    )
    assert stable_only.controller.latest_label == "2.1.0"
    assert not stable_only.controller.update_available
    with_rc = snapshot_with_prereleases(
        stable_only,
        True,
        current_controller="2.1.0",
        current_firmware="",
    )
    assert with_rc.include_prereleases
    assert with_rc.controller.latest_label == "2.2.0-RC1"
    assert with_rc.controller.update_available
    assert with_rc.controller_releases == (stable, rc)


def test_invalid_json_falls_back_to_stale_cache(tmp_path: Path):
    cache = {
        "etag": '"old"',
        "fetched_at": "2024-01-01T00:00:00+00:00",
        "releases": [_payload("v2.1.0")],
    }
    (tmp_path / config.CONTROLLER_CACHE_NAME).write_text(json.dumps(cache), encoding="utf-8")

    def request(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return HttpResponse(200, {}, b"not-json")

    client = GitHubReleasesClient(cache_dir=tmp_path, request=request)
    result = client.fetch_releases(config.CONTROLLER_RELEASES_URL, config.CONTROLLER_CACHE_NAME)
    assert result.from_cache
    assert result.releases[0].tag_name == "v2.1.0"


def test_parse_release_rejects_empty_payload():
    assert parse_release({}) is None
    assert parse_release({"name": "x"}) is None
    assert pick_latest(()) is None


def test_filter_github_prerelease_flag_without_rc_suffix():
    marked = parse_release(_payload("v2.3.0", prerelease=True))
    assert marked is not None
    assert filter_releases((marked,), include_prereleases=False) == ()
    assert filter_releases((marked,), include_prereleases=True)[0].tag_name == "v2.3.0"
