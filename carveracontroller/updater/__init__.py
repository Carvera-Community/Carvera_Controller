"""GitHub Releases-based updater used by the Update Center."""

from .actions import (
    ControllerActions,
    FirmwareActions,
    controller_actions,
    firmware_actions,
    firmware_one_click_supported,
)
from .backup import matching_backup_paths
from .download import DownloadCancelled, DownloadError, download_file
from .github import FetchResult, GitHubReleasesClient, filter_releases, parse_release, pick_latest
from .install import fetch_firmware_bin
from .models import Release, ReleaseAsset
from .notes import NoteRow, format_release_notes
from .platform import detect_platform, firmware_one_click_ready, select_controller_asset, select_firmware_asset
from .service import (
    ChannelStatus,
    UpdateSnapshot,
    apply_current_versions,
    check_updates,
    evaluate_channel,
    snapshot_from_fetches,
    snapshot_with_prereleases,
)
from .version import Version, parse_version

__all__ = [
    "ChannelStatus",
    "ControllerActions",
    "DownloadCancelled",
    "DownloadError",
    "FetchResult",
    "FirmwareActions",
    "GitHubReleasesClient",
    "NoteRow",
    "Release",
    "ReleaseAsset",
    "UpdateSnapshot",
    "Version",
    "apply_current_versions",
    "check_updates",
    "controller_actions",
    "detect_platform",
    "download_file",
    "evaluate_channel",
    "fetch_firmware_bin",
    "filter_releases",
    "firmware_actions",
    "firmware_one_click_ready",
    "firmware_one_click_supported",
    "format_release_notes",
    "matching_backup_paths",
    "parse_release",
    "parse_version",
    "pick_latest",
    "select_controller_asset",
    "select_firmware_asset",
    "snapshot_from_fetches",
    "snapshot_with_prereleases",
]
