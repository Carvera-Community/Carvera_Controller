"""High-level update checks for Controller and Firmware GitHub releases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config
from .github import FetchResult, GitHubReleasesClient, filter_releases, pick_latest
from .models import Release, ReleaseAsset
from .platform import detect_platform, firmware_one_click_ready, select_controller_asset, select_firmware_asset
from .version import parse_version


@dataclass(frozen=True)
class ChannelStatus:
    product: str
    current: str
    latest: Release | None
    update_available: bool
    ahead_of_channel: bool
    from_cache: bool
    error: str | None
    last_checked: datetime | None
    matching_asset: ReleaseAsset | None
    can_one_click: bool = False

    @property
    def latest_label(self) -> str:
        if self.latest is None:
            return ""
        return self.latest.display_name

    @property
    def channel_label(self) -> str:
        if self.latest is None:
            return ""
        return (
            "RC" if self.latest.prerelease or (self.latest.version and self.latest.version.is_prerelease) else "Stable"
        )


@dataclass(frozen=True)
class UpdateSnapshot:
    controller: ChannelStatus
    firmware: ChannelStatus
    include_prereleases: bool
    platform_key: str
    controller_releases: tuple[Release, ...] = ()
    firmware_releases: tuple[Release, ...] = ()


def evaluate_channel(
    releases: tuple[Release, ...] | list[Release],
    current: str,
    *,
    include_prereleases: bool,
    product: str,
    from_cache: bool = False,
    error: str | None = None,
    last_checked: datetime | None = None,
    platform_key: str = "",
    require_current: bool = False,
) -> ChannelStatus:
    filtered = filter_releases(releases, include_prereleases=include_prereleases)
    latest = pick_latest(filtered)
    current_version = parse_version(current)
    latest_version = latest.version if latest is not None else None

    update_available = False
    ahead = False
    if require_current and not (current or "").strip():
        update_available = False
    elif latest_version is not None:
        if current_version is None or latest_version > current_version:
            update_available = True
        elif current_version > latest_version:
            ahead = True

    matching: ReleaseAsset | None = None
    can_one_click = False
    if product == "controller":
        matching = select_controller_asset(latest, platform_key)
    elif product == "firmware":
        matching = select_firmware_asset(latest)
        can_one_click = firmware_one_click_ready(latest)

    return ChannelStatus(
        product=product,
        current=(current or "").strip(),
        latest=latest,
        update_available=update_available,
        ahead_of_channel=ahead,
        from_cache=from_cache,
        error=error,
        last_checked=last_checked,
        matching_asset=matching,
        can_one_click=can_one_click,
    )


def check_updates(
    *,
    current_controller: str,
    current_firmware: str,
    include_prereleases: bool,
    cache_dir: str | Path | None,
    platform_key: str | None = None,
    client: GitHubReleasesClient | None = None,
    force: bool = False,
) -> UpdateSnapshot:
    resolved_platform = platform_key or detect_platform()
    github = client or GitHubReleasesClient(cache_dir=cache_dir)
    max_age_s = None if force else config.CACHE_MAX_AGE_S
    controller_fetch = github.fetch_releases(
        config.CONTROLLER_RELEASES_URL, config.CONTROLLER_CACHE_NAME, max_age_s=max_age_s
    )
    firmware_fetch = github.fetch_releases(
        config.FIRMWARE_RELEASES_URL, config.FIRMWARE_CACHE_NAME, max_age_s=max_age_s
    )
    return snapshot_from_fetches(
        controller_fetch,
        firmware_fetch,
        current_controller=current_controller,
        current_firmware=current_firmware,
        include_prereleases=include_prereleases,
        platform_key=resolved_platform,
    )


def snapshot_from_fetches(
    controller_fetch: FetchResult,
    firmware_fetch: FetchResult,
    *,
    current_controller: str,
    current_firmware: str,
    include_prereleases: bool,
    platform_key: str,
) -> UpdateSnapshot:
    return UpdateSnapshot(
        controller=evaluate_channel(
            controller_fetch.releases,
            current_controller,
            include_prereleases=include_prereleases,
            product="controller",
            from_cache=controller_fetch.from_cache,
            error=controller_fetch.error,
            last_checked=controller_fetch.fetched_at,
            platform_key=platform_key,
        ),
        firmware=evaluate_channel(
            firmware_fetch.releases,
            current_firmware,
            include_prereleases=include_prereleases,
            product="firmware",
            from_cache=firmware_fetch.from_cache,
            error=firmware_fetch.error,
            last_checked=firmware_fetch.fetched_at,
            platform_key=platform_key,
            require_current=True,
        ),
        include_prereleases=include_prereleases,
        platform_key=platform_key,
        controller_releases=controller_fetch.releases,
        firmware_releases=firmware_fetch.releases,
    )


def apply_current_versions(
    snapshot: UpdateSnapshot,
    *,
    current_controller: str,
    current_firmware: str,
) -> UpdateSnapshot:
    """Refresh update-available flags after a local version is discovered."""
    return UpdateSnapshot(
        controller=_status_with_current(snapshot.controller, current_controller, require_current=False),
        firmware=_status_with_current(snapshot.firmware, current_firmware, require_current=True),
        include_prereleases=snapshot.include_prereleases,
        platform_key=snapshot.platform_key,
        controller_releases=snapshot.controller_releases,
        firmware_releases=snapshot.firmware_releases,
    )


def snapshot_with_prereleases(
    snapshot: UpdateSnapshot,
    include_prereleases: bool,
    *,
    current_controller: str,
    current_firmware: str,
) -> UpdateSnapshot:
    """Re-evaluate Stable vs RC from already-fetched releases. Does not call GitHub."""
    controller_releases = snapshot.controller_releases or _fallback_releases(snapshot.controller)
    firmware_releases = snapshot.firmware_releases or _fallback_releases(snapshot.firmware)
    return snapshot_from_fetches(
        FetchResult(
            releases=controller_releases,
            from_cache=snapshot.controller.from_cache,
            etag_hit=False,
            error=snapshot.controller.error,
            fetched_at=snapshot.controller.last_checked,
        ),
        FetchResult(
            releases=firmware_releases,
            from_cache=snapshot.firmware.from_cache,
            etag_hit=False,
            error=snapshot.firmware.error,
            fetched_at=snapshot.firmware.last_checked,
        ),
        current_controller=current_controller,
        current_firmware=current_firmware,
        include_prereleases=include_prereleases,
        platform_key=snapshot.platform_key,
    )


def _fallback_releases(status: ChannelStatus) -> tuple[Release, ...]:
    return (status.latest,) if status.latest is not None else ()


def _status_with_current(status: ChannelStatus, current: str, *, require_current: bool) -> ChannelStatus:
    current_text = (current or "").strip()
    current_version = parse_version(current_text)
    latest_version = status.latest.version if status.latest is not None else None
    update_available = False
    ahead = False
    if require_current and not current_text:
        update_available = False
    elif latest_version is not None:
        if current_version is None or latest_version > current_version:
            update_available = True
        elif current_version > latest_version:
            ahead = True
    return ChannelStatus(
        product=status.product,
        current=current_text,
        latest=status.latest,
        update_available=update_available,
        ahead_of_channel=ahead,
        from_cache=status.from_cache,
        error=status.error,
        last_checked=status.last_checked,
        matching_asset=status.matching_asset,
        can_one_click=status.can_one_click,
    )
