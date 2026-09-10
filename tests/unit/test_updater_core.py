"""Unit tests for updater versioning, notes, platform, actions, and backup."""

from carveracontroller.updater.actions import (
    REASON_IOS,
    REASON_NO_CHECKSUM,
    REASON_NOT_CONNECTED,
    REASON_UNSUPPORTED_MODEL,
    controller_actions,
    firmware_actions,
    firmware_one_click_supported,
)
from carveracontroller.updater.backup import matching_backup_paths
from carveracontroller.updater.models import Release, ReleaseAsset
from carveracontroller.updater.notes import format_release_notes
from carveracontroller.updater.platform import (
    PLATFORM_ANDROID,
    PLATFORM_IOS,
    PLATFORM_LINUX_ARM,
    PLATFORM_LINUX_X64,
    PLATFORM_MACOS_APPLE,
    PLATFORM_MACOS_INTEL,
    PLATFORM_WINDOWS,
    detect_platform,
    firmware_one_click_ready,
    select_controller_asset,
    select_firmware_asset,
)
from carveracontroller.updater.version import parse_version


def _asset(name, *, size=10, digest="", url="https://example.test/a.bin"):
    return ReleaseAsset(name=name, size=size, browser_download_url=url, digest=digest)


def _release(tag, *, prerelease=False, assets=(), body="", html_url="https://github.com/org/repo/releases/tag/x"):
    return Release(
        tag_name=tag,
        name=tag,
        html_url=html_url,
        body=body,
        published_at="2024-06-01T00:00:00Z",
        prerelease=prerelease,
        assets=tuple(assets),
    )


def test_parse_controller_and_firmware_versions():
    stable = parse_version("v2.2.0")
    rc = parse_version("2.2.0-RC3")
    fw = parse_version("2.1.0c")
    fw_rc = parse_version("2.1.0c-RC2")
    assert stable is not None and not stable.is_prerelease
    assert rc is not None and rc.is_prerelease and rc.prerelease_n == 3
    assert fw is not None and fw.community and fw.display() == "2.1.0c"
    assert fw_rc is not None and fw_rc.community and fw_rc.is_prerelease
    assert fw_rc < fw
    assert parse_version("2.1.0c-RC1") < parse_version("2.1.0c-RC2")
    assert rc < stable
    assert parse_version("2.1.0c") < parse_version("2.2.0c")


def test_format_release_notes_strips_markup_and_keeps_structure():
    body = """
# Added
- **Bold** item with [a link](https://example.test)
- <script>alert(1)</script>plain

Paragraph one.

## Fixed
1. numbered fix
"""
    rows = format_release_notes(body)
    kinds = [row.kind for row in rows]
    texts = [row.text for row in rows]
    assert "heading" in kinds
    assert "bullet" in kinds
    assert "paragraph" in kinds
    assert any(row.text == "Added" for row in rows if row.kind == "heading")
    assert "Bold item with a link" in texts
    assert all("<script>" not in row.text for row in rows)
    assert all("http" not in row.text for row in rows)


def test_format_release_notes_categorizes_changelog_prefixes():
    rows = format_release_notes(
        """
## What's Changed
- **Enhancement:** Support connecting to hidden wifi
- **Fixed:** Restore keyboard jogging
- **Change:** Hide Auto Vacuum on C1
"""
    )
    kinds = [row.kind for row in rows]
    assert "heading" in kinds
    assert "enhancement" in kinds
    assert "fixed" in kinds
    assert "change" in kinds
    enhancement = next(row for row in rows if row.kind == "enhancement")
    assert enhancement.badge == "Enhancement"
    assert enhancement.text == "Support connecting to hidden wifi"


def test_format_release_notes_keeps_source_line_breaks():
    rows = format_release_notes("Hello,\nThis is the stable version\n\n## Changes\n- item")
    paragraphs = [row.text for row in rows if row.kind == "paragraph"]
    assert paragraphs
    assert "Hello,\nThis is the stable version" in paragraphs


def test_format_release_notes_does_not_truncate_long_changelogs():
    bullets = "\n".join(f"- Enhancement: item {i}" for i in range(90))
    rows = format_release_notes(f"## Changes\n{bullets}")
    assert len(rows) == 91
    assert rows[0].kind == "heading"
    assert rows[-1].text == "item 89"


def test_detect_platform_keys():
    assert detect_platform(sys_platform="win32", machine="AMD64") == PLATFORM_WINDOWS
    assert detect_platform(sys_platform="darwin", machine="arm64") == PLATFORM_MACOS_APPLE
    assert detect_platform(sys_platform="darwin", machine="x86_64") == PLATFORM_MACOS_INTEL
    assert detect_platform(sys_platform="linux", machine="x86_64") == PLATFORM_LINUX_X64
    assert detect_platform(sys_platform="linux", machine="aarch64") == PLATFORM_LINUX_ARM
    assert detect_platform(kivy_platform="android") == PLATFORM_ANDROID
    assert detect_platform(kivy_platform="ios") == PLATFORM_IOS


def test_select_controller_asset_is_unambiguous():
    release = _release(
        "v2.2.0",
        assets=[
            _asset("CarveraController-2.2.0-windows-x64.exe"),
            _asset("CarveraController-2.2.0-Intel.dmg"),
            _asset("CarveraController-2.2.0-AppleSilicon.dmg"),
            _asset("CarveraController-2.2.0-x86_64.AppImage"),
            _asset("CarveraController-2.2.0-aarch64.AppImage"),
            _asset("CarveraController-2.2.0.apk"),
            _asset("CarveraController-2.2.0.apk.idsig"),
        ],
    )
    assert select_controller_asset(release, PLATFORM_WINDOWS).name.endswith("-windows-x64.exe")
    assert select_controller_asset(release, PLATFORM_MACOS_INTEL).name.lower().endswith("-intel.dmg")
    assert select_controller_asset(release, PLATFORM_MACOS_APPLE).name.lower().endswith("-applesilicon.dmg")
    assert select_controller_asset(release, PLATFORM_LINUX_X64).name.lower().endswith("-x86_64.appimage")
    assert select_controller_asset(release, PLATFORM_LINUX_ARM).name.lower().endswith("-aarch64.appimage")
    assert select_controller_asset(release, PLATFORM_ANDROID).name.endswith(".apk")
    assert select_controller_asset(release, PLATFORM_IOS) is None


def test_firmware_asset_requires_unique_bin_and_digest():
    ready = _release(
        "2.1.0c",
        assets=[
            _asset("firmware-2.1.0c.bin", size=128, digest="sha256:" + "ab" * 32),
            _asset("firmware-debug-symbols-2.1.0c.zip", size=50),
        ],
    )
    skipped = _release(
        "2.1.0c",
        assets=[
            _asset("firmware-2.1.0c.bin", size=128),
            _asset("firmware-2.1.0c-alt.bin", size=64),
        ],
    )
    with_z1 = _release(
        "2.1.0c",
        assets=[
            _asset("firmware-2.1.0c.bin", size=128, digest="sha256:" + "ab" * 32),
            _asset("firmware-z1-1.0.0.bin", size=96, digest="sha256:" + "cd" * 32),
            _asset("Z1-firmware.bin", size=80),
        ],
    )
    assert select_firmware_asset(ready).name == "firmware-2.1.0c.bin"
    assert firmware_one_click_ready(ready)
    assert select_firmware_asset(with_z1).name == "firmware-2.1.0c.bin"
    assert firmware_one_click_ready(with_z1)
    assert select_firmware_asset(skipped) is None
    assert not firmware_one_click_ready(skipped)
    assert not firmware_one_click_ready(_release("2.1.0c", assets=[_asset("firmware-2.1.0c.bin", size=128)]))


def test_controller_and_firmware_action_rules():
    controller = _release(
        "v2.2.0",
        html_url="https://github.com/Carvera-Community/Carvera_Controller/releases/tag/v2.2.0",
        assets=[_asset("CarveraController-2.2.0-x86_64.AppImage", url="https://example.test/appimage")],
    )
    linux = controller_actions(controller, platform_key=PLATFORM_LINUX_X64)
    assert linux.can_download
    assert linux.download_url.endswith("/appimage")
    ios = controller_actions(controller, platform_key=PLATFORM_IOS)
    assert not ios.can_download
    assert ios.reason == REASON_IOS

    firmware = _release(
        "2.1.0c",
        assets=[_asset("firmware-2.1.0c.bin", size=128, digest="sha256:" + "ab" * 32)],
    )
    idle = firmware_actions(
        firmware, connected=True, idle=True, transferring=False, backup_supported=True, machine_model="C1"
    )
    assert idle.can_one_click
    assert idle.one_click_supported
    assert idle.can_install_from_file
    assert idle.can_backup
    disconnected = firmware_actions(
        firmware, connected=False, idle=False, transferring=False, backup_supported=True, machine_model=""
    )
    assert not disconnected.can_one_click
    assert not disconnected.one_click_supported
    assert not disconnected.can_install_from_file
    assert disconnected.reason == REASON_NOT_CONNECTED
    busy = firmware_actions(
        firmware, connected=True, idle=True, transferring=True, backup_supported=True, machine_model="C1"
    )
    assert not busy.can_one_click
    missing = firmware_actions(
        _release("2.1.0c", assets=[_asset("firmware-2.1.0c.bin", size=128)]),
        connected=True,
        idle=True,
        transferring=False,
        backup_supported=False,
        machine_model="CA1",
    )
    assert not missing.can_one_click
    assert missing.one_click_supported
    assert missing.can_install_from_file
    assert missing.reason == REASON_NO_CHECKSUM


def test_firmware_one_click_is_limited_to_c1_and_ca1():
    firmware = _release(
        "2.1.0c",
        assets=[_asset("firmware-2.1.0c.bin", size=128, digest="sha256:" + "ab" * 32)],
    )
    kwargs = {"connected": True, "idle": True, "transferring": False, "backup_supported": True}
    for model in ("C1", "CA1"):
        actions = firmware_actions(firmware, machine_model=model, **kwargs)
        assert actions.one_click_supported
        assert actions.can_one_click
        assert actions.can_install_from_file
    z1 = firmware_actions(firmware, machine_model="Z1", **kwargs)
    assert not z1.one_click_supported
    assert not z1.can_one_click
    assert z1.can_install_from_file
    assert z1.can_backup
    assert z1.reason == REASON_UNSUPPORTED_MODEL
    unknown = firmware_actions(firmware, machine_model="", **kwargs)
    assert not unknown.can_one_click
    assert unknown.reason == REASON_UNSUPPORTED_MODEL
    assert firmware_one_click_supported("C1")
    assert firmware_one_click_supported("CA1")
    assert not firmware_one_click_supported("Z1")
    assert not firmware_one_click_supported("")
    assert not firmware_one_click_supported(None)


def test_matching_backup_paths_allowlist_and_empty_listing():
    listing = [
        {"path": "/sd/config.txt", "is_dir": False},
        {"path": "/sd/gcodes", "is_dir": True},
        {"path": "/sd/other.txt", "is_dir": False},
        {"path": "/sd/config.txt", "is_dir": False},
    ]
    assert matching_backup_paths(listing) == ["/sd/config.txt"]
    assert matching_backup_paths([]) == []
    assert matching_backup_paths(None) == []
    assert matching_backup_paths([{"path": "/sd/readme.txt", "is_dir": False}]) == []
