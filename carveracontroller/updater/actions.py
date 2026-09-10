"""Action availability for Controller and Firmware update tabs."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Release, ReleaseAsset
from .platform import firmware_one_click_ready, select_controller_asset

REASON_IOS = "ios"
REASON_NO_PACKAGE = "no_package"
REASON_NOT_CONNECTED = "not_connected"
REASON_TRANSFERRING = "transferring"
REASON_NOT_IDLE = "not_idle"
REASON_NO_CHECKSUM = "no_checksum"
REASON_UNSUPPORTED_MODEL = "unsupported_model"

ONE_CLICK_FIRMWARE_MODELS = frozenset({"C1", "CA1"})


@dataclass(frozen=True)
class ControllerActions:
    download_url: str
    release_url: str
    can_download: bool
    reason: str


@dataclass(frozen=True)
class FirmwareActions:
    can_one_click: bool
    one_click_supported: bool
    can_install_from_file: bool
    can_backup: bool
    release_url: str
    reason: str


def controller_actions(release: Release | None, *, platform_key: str) -> ControllerActions:
    if release is None:
        return ControllerActions("", "", False, "")
    asset = select_controller_asset(release, platform_key)
    release_url = release.html_url
    if asset is not None:
        return ControllerActions(asset.browser_download_url, release_url, True, "")
    reason = REASON_IOS if platform_key == "ios" else REASON_NO_PACKAGE
    return ControllerActions("", release_url, False, reason)


def firmware_one_click_supported(machine_model: str | None) -> bool:
    return (machine_model or "").strip() in ONE_CLICK_FIRMWARE_MODELS


def firmware_actions(
    release: Release | None,
    *,
    connected: bool,
    idle: bool,
    transferring: bool,
    backup_supported: bool,
    machine_model: str = "",
) -> FirmwareActions:
    release_url = release.html_url if release is not None else ""
    one_click = firmware_one_click_ready(release)
    model_supported = firmware_one_click_supported(machine_model)
    machine_reason = _machine_block_reason(connected=connected, idle=idle, transferring=transferring)
    reason = machine_reason
    if not reason and not model_supported:
        reason = REASON_UNSUPPORTED_MODEL
    if not reason and release is not None and not one_click:
        reason = REASON_NO_CHECKSUM
    return FirmwareActions(
        can_one_click=bool(one_click and not machine_reason and model_supported),
        one_click_supported=model_supported,
        can_install_from_file=not machine_reason,
        can_backup=bool(backup_supported and not machine_reason),
        release_url=release_url,
        reason=reason,
    )


def _machine_block_reason(*, connected: bool, idle: bool, transferring: bool) -> str:
    if not connected:
        return REASON_NOT_CONNECTED
    if transferring:
        return REASON_TRANSFERRING
    if not idle:
        return REASON_NOT_IDLE
    return ""


def controller_asset_for(release: Release | None, platform_key: str) -> ReleaseAsset | None:
    return select_controller_asset(release, platform_key)
