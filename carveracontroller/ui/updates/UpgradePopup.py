"""Update Center popup: Controller and Firmware GitHub releases."""

from __future__ import annotations

from datetime import datetime, timezone

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.utils import platform as kivy_platform

from carveracontroller.translation import tr
from carveracontroller.ui.file_browser.FileBrowserPopup import FileBrowserActionButton
from carveracontroller.ui.file_browser.sources import COMPACT_WIDTH_DP, is_compact_width
from carveracontroller.updater import (
    ChannelStatus,
    UpdateSnapshot,
    controller_actions,
    firmware_actions,
    format_release_notes,
)
from carveracontroller.updater.actions import (
    REASON_IOS,
    REASON_NO_CHECKSUM,
    REASON_NO_PACKAGE,
    REASON_NOT_CONNECTED,
    REASON_NOT_IDLE,
    REASON_TRANSFERRING,
    REASON_UNSUPPORTED_MODEL,
)
from carveracontroller.updater.config import CONFIG_INCLUDE_PRERELEASES, CONFIG_SHOW_UPDATE

TAB_CONTROLLER = "controller"
TAB_FIRMWARE = "firmware"

_BADGE_COLORS = {
    "enhancement": [32 / 255, 114 / 255, 148 / 255, 1],
    "fixed": [46 / 255, 125 / 255, 50 / 255, 1],
    "change": [150 / 255, 110 / 255, 40 / 255, 1],
    "breaking": [160 / 255, 55 / 255, 55 / 255, 1],
}


class UpdateNotesRow(RecycleDataViewBehavior, BoxLayout):
    kind = StringProperty("paragraph")
    text = StringProperty("")
    badge = StringProperty("")
    badge_color = ListProperty([0.0, 0.0, 0.0, 0.0])
    show_bullet = BooleanProperty(False)
    body_font_size = NumericProperty(13)
    body_bold = BooleanProperty(False)
    body_color = ListProperty([220 / 255, 220 / 255, 220 / 255, 1])

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)


class UpgradePopup(ModalView):
    active_tab = StringProperty(TAB_CONTROLLER)
    compact = BooleanProperty(False)
    check_at_startup = BooleanProperty(True)
    include_prereleases = BooleanProperty(False)
    checking = BooleanProperty(False)

    controller_notify = BooleanProperty(False)
    firmware_notify = BooleanProperty(False)
    controller_tab_path = StringProperty("")
    firmware_tab_path = StringProperty("")

    status_title = StringProperty("")
    status_detail = StringProperty("")
    channel_badge = StringProperty("")
    last_check_text = StringProperty("")
    helper_text = StringProperty("")
    notes_empty_text = StringProperty("")
    show_notes = BooleanProperty(False)
    release_url = StringProperty("")
    notes_link_text = StringProperty("")

    _snapshot: UpdateSnapshot | None = None
    _check_failed = False
    _notes_key = None
    _footer_key = None

    def __init__(self, **kwargs):
        self._ready = False
        super().__init__(**kwargs)
        self.check_at_startup = _config_flag(CONFIG_SHOW_UPDATE, True)
        self.include_prereleases = _config_flag(CONFIG_INCLUDE_PRERELEASES, False)
        self.controller_tab_path = tr._("This app")
        self.firmware_tab_path = tr._("Not connected")
        self._ready = True

    def on_open(self):
        super().on_open()
        Window.bind(size=self._on_window_size)
        app = App.get_running_app()
        if app is not None:
            app.bind(state=self._on_app_state, model=self._on_app_state)
        self.set_compact_from_window()
        self._sync_chrome()

    def on_dismiss(self):
        Window.unbind(size=self._on_window_size)
        app = App.get_running_app()
        if app is not None:
            app.unbind(state=self._on_app_state, model=self._on_app_state)
        return super().on_dismiss()

    def set_tab(self, tab: str):
        if tab not in (TAB_CONTROLLER, TAB_FIRMWARE):
            return
        if self.active_tab == tab:
            return
        self.active_tab = tab
        self._notes_key = None
        self._footer_key = None
        self._sync_chrome()

    def set_compact_from_window(self, width: float | None = None):
        try:
            threshold = dp(COMPACT_WIDTH_DP)
        except Exception:
            threshold = float(COMPACT_WIDTH_DP)
        measured = Window.width if width is None else width
        compact = is_compact_width(measured, threshold=threshold)
        self.compact = compact
        if compact:
            self.size_hint = (0.96, 0.94)
        else:
            self.size_hint = (0.82, 0.85)
        self.pos_hint = {"center_x": 0.5, "center_y": 0.5}

    def apply_snapshot(self, snapshot: UpdateSnapshot | None, *, checking: bool = False, error: bool = False):
        if snapshot is not None:
            self._snapshot = snapshot
            self._check_failed = False
        else:
            self._check_failed = bool(error) and self._snapshot is None
        self.checking = checking
        self._notes_key = None
        self._footer_key = None
        self._sync_chrome()

    def set_checking(self, checking: bool):
        self.checking = checking
        self._footer_key = None
        self._sync_chrome()

    def on_check_at_startup(self, _instance, value: bool):
        if not getattr(self, "_ready", False):
            return
        _set_config_flag(CONFIG_SHOW_UPDATE, value)
        makera = _makera()
        if makera is not None:
            makera.show_update = bool(value)

    def on_include_prereleases(self, _instance, value: bool):
        if not getattr(self, "_ready", False):
            return
        _set_config_flag(CONFIG_INCLUDE_PRERELEASES, value)
        makera = _makera()
        if makera is not None and self._is_open:
            makera.apply_include_prereleases()

    def on_refresh(self):
        makera = _makera()
        if makera is not None:
            makera.check_for_updates(force=True)

    def on_close(self):
        makera = _makera()
        if makera is not None:
            makera.close_update_popup()
        else:
            self.dismiss()

    def on_download_controller(self):
        makera = _makera()
        if makera is None:
            return
        actions = self._controller_actions()
        if actions.can_download and actions.download_url:
            makera.open_url(actions.download_url)

    def on_view_release(self):
        makera = _makera()
        if makera is None or not self.release_url:
            return
        makera.open_url(self.release_url)

    def on_install_firmware(self):
        makera = _makera()
        snapshot = self._snapshot
        if makera is None or snapshot is None or snapshot.firmware.latest is None:
            return
        if not self._firmware_actions().can_one_click:
            return
        makera.install_firmware_release(snapshot.firmware.latest)

    def on_install_from_file(self):
        makera = _makera()
        if makera is not None:
            makera.open_fw_upload()

    def on_backup(self):
        makera = _makera()
        if makera is not None:
            makera.start_back_up_config()

    def _on_window_size(self, *_args):
        was_compact = self.compact
        self.set_compact_from_window()
        if was_compact != self.compact:
            self._footer_key = None
            self._rebuild_footer()
        Clock.unschedule(self._relayout_notes)
        Clock.schedule_once(self._relayout_notes, 0.2)

    def _relayout_notes(self, *_args):
        rv = self.ids.get("notes_list")
        if rv is not None and self._notes_key and len(self._notes_key) == 3:
            if abs(self._notes_key[2] - int(rv.width or 0)) < 8:
                return
        self._notes_key = None
        self._apply_notes(self._active_status())

    def _on_app_state(self, *_args):
        self._footer_key = None
        self._rebuild_footer()
        self._apply_status(self._active_status())

    def _sync_chrome(self):
        snapshot = self._snapshot
        if snapshot is not None:
            self.controller_notify = snapshot.controller.update_available
            self.firmware_notify = snapshot.firmware.update_available
            self.controller_tab_path = _current_version_text(snapshot.controller.current, missing=tr._("This app"))
            self.firmware_tab_path = _current_version_text(snapshot.firmware.current, missing=tr._("Not connected"))
        status = self._active_status()
        self._apply_status(status)
        self._apply_notes(status)
        self._rebuild_footer()

    def _active_status(self) -> ChannelStatus | None:
        if self._snapshot is None:
            return None
        if self.active_tab == TAB_FIRMWARE:
            return self._snapshot.firmware
        return self._snapshot.controller

    def _apply_status(self, status: ChannelStatus | None):
        if self.checking and status is None:
            self.status_title = tr._("Checking for updates…")
            self.status_detail = ""
            self.channel_badge = ""
            self.last_check_text = ""
            self.helper_text = ""
            self.release_url = ""
            self.notes_link_text = ""
            return

        if status is None:
            self.status_title = (
                tr._("Couldn't check for updates")
                if getattr(self, "_check_failed", False)
                else tr._("Check GitHub for Controller and Firmware releases.")
            )
            self.status_detail = ""
            self.channel_badge = ""
            self.last_check_text = ""
            self.helper_text = ""
            self.release_url = ""
            self.notes_link_text = ""
            return

        published = _format_iso(status.latest.published_at if status.latest else "")
        self.channel_badge = status.channel_label
        self.last_check_text = _last_check_label(status.last_checked, stale=bool(status.from_cache and status.error))
        self.release_url = status.latest.html_url if status.latest is not None else ""
        self.notes_link_text = tr._("View release on GitHub") if self.release_url else ""

        if self.checking:
            self.status_title = tr._("Checking for updates…")
            self.status_detail = ""
        elif status.error and status.from_cache:
            self.status_title = tr._("Showing last known releases")
            self.status_detail = status.error
        elif status.error and status.latest is None:
            self.status_title = tr._("Couldn't check for updates")
            self.status_detail = status.error
        elif status.latest is None:
            self.status_title = tr._("No releases found")
            self.status_detail = ""
        elif status.update_available:
            self.status_title = tr._("New version available")
            self.status_detail = _join_detail(tr._("%s is ready to install.") % status.latest_label, published)
        elif status.ahead_of_channel:
            self.status_title = tr._("You're newer than this channel")
            self.status_detail = _join_detail(tr._("Latest published release is %s.") % status.latest_label, published)
        else:
            self.status_title = tr._("You're up to date")
            self.status_detail = _join_detail(tr._("Latest published release is %s.") % status.latest_label, published)

        if self.active_tab == TAB_CONTROLLER:
            self.helper_text = _controller_reason_text(self._controller_actions().reason)
        else:
            self.helper_text = _firmware_reason_text(self._firmware_actions().reason)

    def _apply_notes(self, status: ChannelStatus | None):
        rv = self.ids.get("notes_list")
        if rv is None:
            return
        key = None
        body = ""
        if status is not None and status.latest is not None:
            body = status.latest.body or ""
            key = (status.latest.tag_name, body, int(rv.width or 0))
        if key == self._notes_key:
            return
        self._notes_key = key
        if not body.strip():
            rv.data = []
            self.show_notes = False
            self.notes_empty_text = tr._("Release notes will appear here after a successful check.")
            return
        wrap_width = rv.width if rv.width > 80 else Window.width * 0.7
        rows = format_release_notes(body)
        rv.data = [_note_view_data(row, _measure_note_height(row, wrap_width)) for row in rows]
        self.show_notes = bool(rv.data)
        self.notes_empty_text = tr._("No release notes were published for this version.")
        rv.scroll_y = 1

    def _controller_actions(self):
        snapshot = self._snapshot
        release = snapshot.controller.latest if snapshot is not None else None
        platform_key = snapshot.platform_key if snapshot is not None else ""
        return controller_actions(release, platform_key=platform_key)

    def _firmware_actions(self):
        snapshot = self._snapshot
        release = snapshot.firmware.latest if snapshot is not None else None
        app = App.get_running_app()
        makera = _makera()
        connected = app is not None and app.state != "N/A"
        idle = app is not None and app.state == "Idle"
        transferring = bool(
            makera is not None and (getattr(makera, "uploading", False) or getattr(makera, "downloading", False))
        )
        backup_supported = kivy_platform not in ("android", "ios")
        machine_model = getattr(app, "model", "") if app is not None else ""
        return firmware_actions(
            release,
            connected=connected,
            idle=idle,
            transferring=transferring,
            backup_supported=backup_supported,
            machine_model=machine_model,
        )

    def _rebuild_footer(self):
        bar = self.ids.get("footer_actions")
        if bar is None:
            return
        snapshot = self._snapshot
        version = ""
        if snapshot is not None:
            status = snapshot.firmware if self.active_tab == TAB_FIRMWARE else snapshot.controller
            version = status.latest_label
        if self.active_tab == TAB_CONTROLLER:
            actions = self._controller_actions()
            key = ("controller", version, actions.can_download, self.compact)
        else:
            actions = self._firmware_actions()
            key = (
                "firmware",
                version,
                actions.can_one_click,
                actions.one_click_supported,
                actions.can_install_from_file,
                actions.can_backup,
                self.compact,
            )
        if key == self._footer_key:
            return
        self._footer_key = key
        bar.clear_widgets()
        if self.active_tab == TAB_CONTROLLER:
            if actions.can_download and version:
                bar.add_widget(
                    self._footer_btn(
                        tr._("Download Controller %s") % version,
                        self.on_download_controller,
                        icon="data/download.png",
                        primary=True,
                    )
                )
        else:
            if version and actions.one_click_supported:
                bar.add_widget(
                    self._footer_btn(
                        tr._("Install Firmware %s") % version,
                        self.on_install_firmware,
                        icon="data/upload.png",
                        primary=actions.can_one_click,
                        disabled=not actions.can_one_click,
                    )
                )
            bar.add_widget(
                self._footer_btn(
                    tr._("Install from file…"),
                    self.on_install_from_file,
                    icon="data/memory.png",
                    disabled=not actions.can_install_from_file,
                )
            )
            if kivy_platform not in ("android", "ios"):
                bar.add_widget(
                    self._footer_btn(
                        tr._("Back up machine configuration…"),
                        self.on_backup,
                        icon="data/download.png",
                        disabled=not actions.can_backup,
                    )
                )

    def _footer_btn(self, text, callback, *, icon="", primary=False, disabled=False):
        extra = dp(50) if icon else dp(20)
        btn = FileBrowserActionButton(
            btn_text=text,
            icon=icon,
            primary=primary,
            flat=True,
        )
        btn.disabled = disabled
        btn.size_hint_y = None
        btn.height = dp(40)
        btn.size_hint_x = None
        btn.width = max(dp(96), _text_width(text) + extra)
        btn.bind(on_release=lambda *_: callback())
        return btn


def _makera():
    app = App.get_running_app()
    return None if app is None else app.root


def _config_flag(key: str, default: bool) -> bool:
    if not Config.has_section("carvera") or not Config.has_option("carvera", key):
        return default
    return Config.get("carvera", key) in ("1", "true", "True")


def _set_config_flag(key: str, value: bool) -> None:
    if not Config.has_section("carvera"):
        Config.add_section("carvera")
    Config.set("carvera", key, "1" if value else "0")
    Config.write()


def _current_version_text(current: str, *, missing: str) -> str:
    version = (current or "").strip()
    if not version:
        return missing
    return tr._("Current version: %s") % version


def _join_detail(detail: str, published: str) -> str:
    if detail and published:
        return "%s (%s)" % (detail.rstrip("."), tr._("published %s") % published)
    if published:
        return tr._("Published %s") % published
    return detail


def _last_check_label(value: datetime | None, *, stale: bool) -> str:
    if value is None:
        return ""
    formatted = value.astimezone().strftime("%Y-%m-%d %H:%M")
    if stale:
        return tr._("Last successful check: %s") % formatted
    return tr._("Last checked: %s") % formatted


def _format_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d")


def _controller_reason_text(reason: str) -> str:
    if reason == REASON_IOS:
        return tr._("iOS builds are not distributed as a GitHub download. Use TestFlight or a development build.")
    if reason == REASON_NO_PACKAGE:
        return tr._("No Controller package is available for this device. Open the GitHub release to pick one.")
    return ""


def _firmware_reason_text(reason: str) -> str:
    if reason == REASON_NOT_CONNECTED:
        return tr._("Connect to a machine to install firmware.")
    if reason == REASON_TRANSFERRING:
        return tr._("Wait for the current file transfer to finish.")
    if reason == REASON_NOT_IDLE:
        return tr._("The machine must be idle to install firmware.")
    if reason == REASON_NO_CHECKSUM:
        return tr._(
            "This release cannot be installed in one click because it is missing a unique firmware file or checksum."
        )
    if reason == REASON_UNSUPPORTED_MODEL:
        return tr._(
            "One-click firmware install is only supported on C1 and CA1. Use Install from file for other machines."
        )
    return ""


def _note_view_data(row, height: float) -> dict:
    heading = row.kind == "heading"
    return {
        "kind": row.kind,
        "text": row.text,
        "badge": row.badge,
        "badge_color": _BADGE_COLORS.get(row.kind, [0.0, 0.0, 0.0, 0.0]),
        "show_bullet": row.kind == "bullet",
        "body_font_size": dp(16) if heading else (dp(14) if row.kind == "paragraph" else dp(13)),
        "body_bold": heading,
        "body_color": [50 / 255, 164 / 255, 206 / 255, 1] if heading else [220 / 255, 220 / 255, 220 / 255, 1],
        "height": height,
    }


def _measure_note_height(row, wrap_width: float) -> float:
    font_size = 16 if row.kind == "heading" else (14 if row.kind == "paragraph" else 13)
    reserved = dp(24)
    if row.badge:
        reserved += dp(108)
    if row.kind == "bullet":
        reserved += dp(18)
    inner = max(wrap_width - reserved, dp(80))
    text_h = _text_height(row.text or " ", font_size, inner)
    pad = dp(28) if row.kind == "heading" else (dp(16) if row.kind == "paragraph" else dp(12))
    return max(text_h + pad, dp(36) if row.kind == "heading" else dp(28))


def _core_label(text: str, font_size: float, **kwargs) -> CoreLabel:
    try:
        label = CoreLabel(text=text, font_size=font_size, font_name="ARIALUNI", **kwargs)
        label.refresh()
        return label
    except Exception:
        label = CoreLabel(text=text, font_size=font_size, **kwargs)
        label.refresh()
        return label


def _text_width(text: str) -> float:
    return float(_core_label(text, 15).content_size[0])


def _text_height(text: str, font_size: float, wrap_width: float) -> float:
    label = _core_label(text, font_size, text_size=(wrap_width, None), valign="top", halign="left")
    return float(label.content_size[1])


if "UpdateNotesRow" not in Factory.classes:
    Factory.register("UpdateNotesRow", cls=UpdateNotesRow)

if "UpgradePopup" not in Factory.classes:
    Factory.register("UpgradePopup", cls=UpgradePopup)
