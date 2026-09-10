"""Smoke the Update Center tabs at normal and compact window sizes."""

from kivy.core.window import Window

from carveracontroller.updater.github import FetchResult, parse_release
from carveracontroller.updater.service import snapshot_from_fetches
from tests.integration.conftest import pump_frames


def _snapshot():
    controller = parse_release(
        {
            "tag_name": "v2.2.0",
            "name": "v2.2.0",
            "html_url": "https://github.com/Carvera-Community/Carvera_Controller/releases/tag/v2.2.0",
            "body": "## Added\n- Update Center",
            "published_at": "2024-05-01T00:00:00Z",
            "prerelease": False,
            "draft": False,
            "assets": [
                {
                    "name": "CarveraController-2.2.0-x86_64.AppImage",
                    "size": 10,
                    "browser_download_url": "https://example.test/controller.AppImage",
                    "digest": "",
                    "content_type": "application/octet-stream",
                }
            ],
        }
    )
    firmware = parse_release(
        {
            "tag_name": "2.1.0c",
            "name": "2.1.0c",
            "html_url": "https://github.com/Carvera-Community/Carvera_Community_Firmware/releases/tag/2.1.0c",
            "body": "## Fixed\n- Homing",
            "published_at": "2024-05-02T00:00:00Z",
            "prerelease": False,
            "draft": False,
            "assets": [
                {
                    "name": "firmware-2.1.0c.bin",
                    "size": 10,
                    "browser_download_url": "https://example.test/firmware.bin",
                    "digest": "sha256:" + "ab" * 32,
                    "content_type": "application/octet-stream",
                }
            ],
        }
    )
    fetch_c = FetchResult(releases=(controller,), from_cache=False, etag_hit=False, error=None, fetched_at=None)
    fetch_f = FetchResult(releases=(firmware,), from_cache=False, etag_hit=False, error=None, fetched_at=None)
    return snapshot_from_fetches(
        fetch_c,
        fetch_f,
        current_controller="2.1.0",
        current_firmware="2.0.0c",
        include_prereleases=False,
        platform_key="linux-x64",
    )


def test_update_center_tabs_normal_and_compact(kivy_app, connected_idle_state):
    root = kivy_app.root
    popup = root.upgrade_popup
    snapshot = _snapshot()
    root._update_snapshot = snapshot
    popup.apply_snapshot(snapshot)

    def _open_without_network():
        popup.open()

    root.open_update_popup = _open_without_network
    try:
        popup.open()
        pump_frames(10)
        # The session window stays ~1920px; the shell layout will not shrink to
        # 480px. Drive compact from an explicit width and ignore size events.
        Window.unbind(size=popup._on_window_size)
        popup.set_compact_from_window(width=1920)
        popup.set_tab("controller")
        pump_frames(5)
        assert popup._is_open
        assert popup.active_tab == "controller"
        assert popup.ids.footer_actions.children
        assert not popup.compact
        assert "Current version" in popup.controller_tab_path
        assert popup.notes_link_text == "View release on GitHub"
        assert all(
            "Check for updates" not in getattr(child, "btn_text", "") for child in popup.ids.footer_actions.children
        )
        assert all(
            "View release on GitHub" not in getattr(child, "btn_text", "")
            for child in popup.ids.footer_actions.children
        )

        popup.set_tab("firmware")
        pump_frames(5)
        assert popup.active_tab == "firmware"
        assert popup.firmware_notify or popup.controller_notify

        popup.set_compact_from_window(width=480)
        popup._sync_chrome()
        pump_frames(5)
        assert popup.compact
        assert popup.size_hint[0] >= 0.9
        popup.set_tab("controller")
        pump_frames(5)
        assert popup.active_tab == "controller"
    finally:
        popup.dismiss()
        pump_frames(5)
