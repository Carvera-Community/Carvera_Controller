"""Map the running OS/arch to a GitHub release asset."""

from __future__ import annotations

import platform
import sys

from .models import Release, ReleaseAsset

PLATFORM_WINDOWS = "windows"
PLATFORM_MACOS_INTEL = "macos-intel"
PLATFORM_MACOS_APPLE = "macos-apple"
PLATFORM_LINUX_X64 = "linux-x64"
PLATFORM_LINUX_ARM = "linux-arm"
PLATFORM_ANDROID = "android"
PLATFORM_IOS = "ios"
PLATFORM_UNKNOWN = "unknown"

_CONTROLLER_SUFFIXES = {
    PLATFORM_WINDOWS: ("-windows-x64.exe",),
    PLATFORM_MACOS_INTEL: ("-intel.dmg",),
    PLATFORM_MACOS_APPLE: ("-applesilicon.dmg",),
    PLATFORM_LINUX_X64: ("-x86_64.appimage",),
    PLATFORM_LINUX_ARM: ("-aarch64.appimage",),
    PLATFORM_ANDROID: (".apk",),
}


def detect_platform(
    *,
    sys_platform: str | None = None,
    machine: str | None = None,
    kivy_platform: str | None = None,
) -> str:
    """Return a stable platform key used to pick a Controller asset."""
    kivy = (kivy_platform or "").lower()
    if kivy == "android":
        return PLATFORM_ANDROID
    if kivy == "ios" or (sys_platform or sys.platform) == "ios":
        return PLATFORM_IOS

    plat = (sys_platform or sys.platform).lower()
    cpu = (machine or platform.machine() or "").lower()

    if plat.startswith("win"):
        return PLATFORM_WINDOWS
    if plat == "darwin":
        if cpu in {"arm64", "aarch64"}:
            return PLATFORM_MACOS_APPLE
        return PLATFORM_MACOS_INTEL
    if plat.startswith("linux"):
        if cpu in {"aarch64", "arm64"}:
            return PLATFORM_LINUX_ARM
        if cpu in {"x86_64", "amd64"}:
            return PLATFORM_LINUX_X64
        return PLATFORM_UNKNOWN
    return PLATFORM_UNKNOWN


def select_controller_asset(release: Release | None, platform_key: str) -> ReleaseAsset | None:
    if release is None:
        return None
    suffixes = _CONTROLLER_SUFFIXES.get(platform_key)
    if not suffixes:
        return None
    matches = [asset for asset in release.assets if _name_matches(asset.name, suffixes)]
    if len(matches) == 1:
        return matches[0]
    return None


def select_firmware_asset(release: Release | None) -> ReleaseAsset | None:
    """Return the unique firmware .bin, ignoring debug-symbol archives and Z1 firmware."""
    if release is None:
        return None
    bins = [
        asset
        for asset in release.assets
        if asset.name.lower().endswith(".bin") and "debug" not in asset.name.lower() and "z1" not in asset.name.lower()
    ]
    if len(bins) == 1:
        return bins[0]
    firmware_named = [asset for asset in bins if asset.name.lower().startswith("firmware-")]
    if len(firmware_named) == 1:
        return firmware_named[0]
    return None


def firmware_one_click_ready(release: Release | None) -> bool:
    asset = select_firmware_asset(release)
    return bool(asset and asset.sha256 and asset.size > 0 and asset.browser_download_url)


def _name_matches(name: str, suffixes: tuple[str, ...]) -> bool:
    lowered = name.lower()
    if lowered.endswith(".apk.idsig"):
        return False
    return any(lowered.endswith(suffix) for suffix in suffixes)
