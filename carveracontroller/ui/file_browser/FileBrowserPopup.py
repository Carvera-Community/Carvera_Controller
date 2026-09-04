"""Job / firmware file browser: This device vs Machine in one popup."""

from __future__ import annotations

import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView

from carveracontroller import Utils
from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
from carveracontroller.translation import tr

from . import sources
from .sources import (
    CONFIG_LAST_LOCATION,
    DEFAULT_SORT_REVERSE,
    KIND_FILE,
    LOCATION_DEVICE,
    LOCATION_MACHINE,
    MACHINE_BASE_DIR,
    MACHINE_BASE_DIR_WIN,
    SORT_DATE,
    SORT_NAME,
    SORT_SIZE,
    ActionState,
    compute_action_state,
    current_file_banner,
    default_device_dir,
    device_tab_path_display,
    download_dest_tooltip,
    group_and_sort_entries,
    is_compact_width,
    is_ios_platform,
    is_local_preview,
    is_under_machine_root,
    list_device_directory,
    local_dir_has_file,
    machine_listing_has,
    machine_parent_dir,
    machine_tab_path_display,
    trim_breadcrumb_pairs,
    upload_dest_tooltip,
)
from .thumbnail import (
    is_gcode_path,
    local_cache_key,
    machine_cache_key,
    thumbnail_cache_for_app,
)


class FileBrowserLocationTab(ButtonBehavior, BoxLayout):
    selected = BooleanProperty(False)
    tab_text = StringProperty("")
    icon = StringProperty("")
    path_text = StringProperty("")


class FileBrowserIconButton(ButtonBehavior, BoxLayout):
    icon = StringProperty("")


class FileBrowserActionButton(ToolTipButton):
    """Standard app Button with an optional leading icon and tinted variants."""

    icon = StringProperty("")
    btn_text = StringProperty("")
    primary = BooleanProperty(False)
    destructive = BooleanProperty(False)
    flat = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # ToolTipButton KV draws a rounded overlay; keep the atlas/tint look.
        self.canvas.before.clear()
        self.bind(
            state=self._sync_colors,
            primary=self._sync_colors,
            destructive=self._sync_colors,
            disabled=self._sync_colors,
            flat=self._sync_colors,
            pos=self._redraw_flat,
            size=self._redraw_flat,
            texture=self._redraw_flat,
            texture_size=self._redraw_flat,
            color=self._redraw_flat,
            background_color=self._redraw_flat,
            icon=self._redraw_flat,
        )
        self._sync_colors()

    def _sync_colors(self, *_args):
        down = self.state == "down"
        if self.disabled:
            self.color = [160 / 255, 160 / 255, 160 / 255, 1]
            if self.flat:
                self.background_normal = ""
                self.background_down = ""
                self.background_color = [50 / 255, 50 / 255, 50 / 255, 1]
            else:
                self.background_normal = "atlas://data/images/defaulttheme/button_disabled"
                self.background_down = "atlas://data/images/defaulttheme/button_disabled"
                self.background_color = [1, 1, 1, 1]
            self._redraw_flat()
            return
        self.color = [1, 1, 1, 1]
        if self.flat:
            # Solid fill so primary/destructive colors stay true; used on the footer.
            self.background_normal = ""
            self.background_down = ""
            if self.destructive:
                self.background_color = (
                    [150 / 255, 55 / 255, 55 / 255, 1] if down else [186 / 255, 72 / 255, 72 / 255, 1]
                )
            elif self.primary:
                self.background_color = (
                    [32 / 255, 114 / 255, 148 / 255, 1] if down else [50 / 255, 164 / 255, 206 / 255, 1]
                )
            else:
                self.background_color = [64 / 255, 64 / 255, 64 / 255, 1] if down else [88 / 255, 88 / 255, 88 / 255, 1]
            self._redraw_flat()
            return
        self.background_normal = "atlas://data/images/defaulttheme/button"
        self.background_down = "atlas://data/images/defaulttheme/button_pressed"
        self.background_color = [1, 1, 1, 1]

    def _redraw_flat(self, *_args):
        """Left-align label on flat buttons so gaps match the 10dp icon inset."""
        if not self.flat:
            return
        inset = dp(10)
        icon_size = dp(20) if self.icon else 0
        text_x = self.x + inset + (icon_size + inset if self.icon else 0)
        text_h = self.texture_size[1] if self.texture_size else 0
        self.canvas.clear()
        with self.canvas:
            Color(rgba=self.background_color)
            Rectangle(pos=self.pos, size=self.size)
            if self.texture:
                Color(rgba=self.color)
                Rectangle(
                    texture=self.texture,
                    size=self.texture_size,
                    pos=(text_x, self.center_y - text_h / 2.0),
                )

    def on_parent(self, _instance, parent):
        if parent is None:
            self.close_tooltip()
            Window.unbind(mouse_pos=self.on_mouse_pos)


class FileBrowserBadge(Label):
    pass


class FileBrowserPathChip(ButtonBehavior, Label):
    pass


class FileBrowserEmptyOverlay(BoxLayout):
    """Empty-state layer that must not steal scroll when hidden."""

    active = BooleanProperty(False)

    def collide_point(self, x, y):
        if not self.active:
            return False
        return super().collide_point(x, y)

    def on_touch_down(self, touch):
        if not self.active:
            return False
        if super().on_touch_down(touch):
            return True
        return self.collide_point(*touch.pos)


class FileBrowserPopup(ModalView):
    firmware_mode = BooleanProperty(False)
    location = StringProperty(LOCATION_MACHINE)
    compact = BooleanProperty(False)
    search_expanded = BooleanProperty(False)
    multi_select_mode = BooleanProperty(False)
    ios_device_mode = BooleanProperty(False)

    title_text = StringProperty("")
    job_filename = StringProperty("")
    job_badge_text = StringProperty("")
    can_clear_job = BooleanProperty(False)
    listing_banner_text = StringProperty("")
    empty_state_text = StringProperty("")
    show_empty_state = BooleanProperty(False)
    show_list = BooleanProperty(True)
    curr_dir_name = StringProperty("")
    sort_button_text = StringProperty("")
    search_text = StringProperty("")
    show_multi_button = BooleanProperty(False)
    show_new_folder_button = BooleanProperty(False)

    machine_dir = StringProperty(MACHINE_BASE_DIR)
    device_dir = StringProperty("")
    device_tab_path = StringProperty("")
    machine_tab_path = StringProperty("")
    selected_device_file = StringProperty("")
    selected_machine_file = StringProperty("")
    selected_machine_filesize = NumericProperty(0)
    selected_device_paths = ListProperty([])
    selected_machine_paths = ListProperty([])

    _device_entries: list = []
    _machine_entries: list = []
    _breadcrumb_paths: list = []
    _sort_key = SORT_DATE
    _sort_reverse = True
    _highlight_path = ""
    _last_range_index = -1
    _bound_app = False
    _list_events_bound = False
    _thumb_gen = 0

    def __init__(self, **kwargs):
        self._device_entries = []
        self._machine_entries = []
        self._breadcrumb_paths = []
        self._thumb_gen = 0
        self.device_dir = default_device_dir()
        super().__init__(**kwargs)
        self._sort_dropdown = DropDown(auto_width=False, width="160dp")
        self._rebuild_sort_dropdown()
        self.title_text = tr._("File Browser")
        self.job_filename = tr._("None")
        self.sort_button_text = self._sort_label()
        Clock.schedule_once(lambda *_: self._bind_list_events(), 0)

    def _bind_list_events(self):
        if self._list_events_bound:
            return
        rv = self.ids.get("file_list")
        if rv is None:
            return
        rv.bind(
            on_open_folder=lambda _rv, path: self._on_open_folder(path),
            on_select_row=lambda _rv, path, kind, size: self._on_select_row(path, kind, size),
            on_activate_file=lambda _rv, path, size: self._on_activate_file(path, size),
            on_toggle_checked=lambda _rv, path: self._on_toggle_checked(path),
            on_long_press=lambda _rv, path, index: self._on_long_press(path, index),
            on_modifier_select=lambda _rv, path, index, mod: self._on_modifier_select(path, index, mod),
        )
        self._list_events_bound = True

    def on_open(self):
        super().on_open()
        self._bind_list_events()
        app = App.get_running_app()
        if app is not None and not self._bound_app:
            app.bind(
                selected_remote_filename=self._on_job_changed,
                selected_local_filename=self._on_job_changed,
                state=self._on_app_state,
            )
            self._bound_app = True
        Window.bind(size=self._on_window_size)
        self.set_compact_from_window()
        self._sync_chrome()

    def on_dismiss(self):
        Window.unbind(size=self._on_window_size)
        self._remember_device_dir()
        self._remember_machine_dir()
        return super().on_dismiss()

    def open_for_jobs(self):
        self.firmware_mode = False
        self.multi_select_mode = False
        self.search_text = ""
        self.ios_device_mode = False
        self.title_text = tr._("File Browser")
        last = ""
        if Config.has_section("carvera") and Config.has_option("carvera", CONFIG_LAST_LOCATION):
            last = Config.get("carvera", CONFIG_LAST_LOCATION) or ""
        app = App.get_running_app()
        if last in (LOCATION_DEVICE, LOCATION_MACHINE):
            self.location = last
        else:
            self.location = LOCATION_MACHINE if app is not None and app.state != "N/A" else LOCATION_DEVICE
        self._restore_device_dir()
        self._restore_machine_dir()
        self.open()
        self._apply_location(refresh=True)

    def open_for_firmware(self):
        self.firmware_mode = True
        self.multi_select_mode = False
        self.search_text = ""
        self.location = LOCATION_DEVICE
        self.title_text = tr._("Firmware")
        if is_ios_platform():
            self._pick_ios_file()
            return
        self._restore_device_dir()
        self.open()
        self._apply_location(refresh=True)

    def set_location(self, location: str):
        if location not in (LOCATION_DEVICE, LOCATION_MACHINE):
            return
        if self.firmware_mode and location != LOCATION_DEVICE:
            return
        if self.location == location:
            return
        self.location = location
        self.multi_select_mode = False
        self.search_text = ""
        self._clear_list_selection()
        if not self.firmware_mode:
            self._persist_location()
        self._apply_location(refresh=True)

    def set_compact_from_window(self):
        try:
            threshold = dp(sources.COMPACT_WIDTH_DP)
        except Exception:
            threshold = float(sources.COMPACT_WIDTH_DP)
        compact = is_compact_width(Window.width, threshold=threshold)
        self.compact = compact
        if compact:
            self.size_hint = (0.96, 0.94)
            self.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        else:
            self.size_hint = (0.82, 0.85)
            self.pos_hint = {"center_x": 0.5, "center_y": 0.5}

    def machine_listing_has(self, filename: str) -> bool:
        return machine_listing_has(self._machine_entries, filename)

    def device_has_file(self, filename: str) -> bool:
        return local_dir_has_file(self.device_dir, filename)

    def refresh_machine(self, *args):
        self._request_machine_listing(self.machine_dir)

    def list_machine_dir(self, path: str):
        target = os.path.normpath(path or MACHINE_BASE_DIR)
        self.machine_dir = target
        self._remember_machine_dir()
        self._clear_list_selection()
        self._request_machine_listing(target)

    def restore_machine_root(self):
        self.machine_dir = MACHINE_BASE_DIR

    def list_device_dir(self, path: str):
        target = path or self.device_dir or default_device_dir()
        if not os.path.isdir(target):
            target = default_device_dir()
        self.device_dir = os.path.normpath(target)
        self._remember_device_dir()
        self._clear_list_selection()
        self._device_entries = list_device_directory(self.device_dir)
        self._rebuild_list(reset_scroll=True)
        self._sync_chrome()
        self._schedule_local_thumbnail_extract()

    def apply_machine_listing(self, file_list, *args):
        self._machine_entries = list(file_list or [])
        self.machine_dir = os.path.normpath(self.machine_dir or MACHINE_BASE_DIR)
        makera = _makera()
        if makera is not None:
            makera.flush_pending_machine_thumbnail()
        if self.location == LOCATION_MACHINE:
            self._rebuild_list(reset_scroll=True)
        self._sync_chrome()

    def go_up(self):
        if self.location == LOCATION_DEVICE:
            parent = os.path.dirname(self.device_dir)
            if parent and parent != self.device_dir:
                self.list_device_dir(parent)
            return
        parent = machine_parent_dir(self.machine_dir)
        if parent:
            self.list_machine_dir(parent)

    def goto_path(self, index: int):
        if index < 0 or index >= len(self._breadcrumb_paths):
            return
        self.search_text = ""
        path = self._breadcrumb_paths[index]
        if self.location == LOCATION_DEVICE:
            self.list_device_dir(path)
        else:
            self.list_machine_dir(path)

    def open_places_dropdown(self, button):
        makera = _makera()
        if makera is None:
            return
        if self.location == LOCATION_DEVICE:
            makera.open_local_dir_drop_down(button)
        else:
            makera.open_remote_dir_drop_down(button)

    def open_sort_dropdown(self, button):
        self._rebuild_sort_dropdown()
        self._sort_dropdown.open(button)

    def on_search_text(self, _instance, _value):
        self._rebuild_list(reset_scroll=True)
        if self.ids:
            self._sync_chrome()

    def toggle_search_expanded(self):
        self.search_expanded = not self.search_expanded

    def clear_search(self):
        self.search_text = ""
        if "ti_search" in self.ids:
            self.ids.ti_search.text = ""
        self._rebuild_list(reset_scroll=True)

    def toggle_multi_select(self):
        if not self._multi_select_allowed():
            return
        self.multi_select_mode = not self.multi_select_mode
        if not self.multi_select_mode:
            self._restore_single_selection()
        self._rebuild_list()
        self._sync_chrome()

    def cancel_multi_select(self):
        self.multi_select_mode = False
        self._restore_single_selection()
        self._rebuild_list()
        self._sync_chrome()

    def pick_ios_file(self):
        self._pick_ios_file()

    def on_preview(self):
        makera = _makera()
        if makera is not None:
            makera.view_local_file()

    def on_upload(self):
        makera = _makera()
        if makera is not None:
            makera.check_and_upload()

    def on_upload_and_use(self):
        makera = _makera()
        if makera is None:
            return
        makera.check_upload_and_select()
        self.dismiss()

    def on_use_as_job(self):
        makera = _makera()
        if makera is None:
            return
        makera.check_and_download()
        self.dismiss()

    def on_download(self):
        makera = _makera()
        if makera is not None:
            makera.check_and_save_to_device()

    def on_rename(self):
        makera = _makera()
        if makera is not None:
            makera.open_rename_input_popup()

    def on_delete(self):
        makera = _makera()
        if makera is not None:
            makera.open_del_confirm_popup()

    def on_new_folder(self):
        makera = _makera()
        if makera is not None:
            makera.open_newfolder_input_popup()

    def on_clear_job(self):
        app = App.get_running_app()
        makera = _makera()
        if app is None or makera is None:
            return
        app.selected_local_filename = ""
        app.selected_remote_filename = ""
        makera.clear_selection()
        self._rebuild_list()
        self._sync_chrome()

    def _apply_location(self, *, refresh: bool):
        if self.location == LOCATION_DEVICE:
            if is_ios_platform() and not self.firmware_mode:
                self.ios_device_mode = True
                self._rebuild_list(reset_scroll=True)
                self._sync_chrome()
                return
            self.ios_device_mode = False
            if refresh:
                self.list_device_dir(self.device_dir)
            else:
                self._rebuild_list(reset_scroll=True)
                self._sync_chrome()
            return
        self.ios_device_mode = False
        if refresh:
            self.refresh_machine()
        else:
            self._rebuild_list(reset_scroll=True)
            self._sync_chrome()

    def _request_machine_listing(self, path: str):
        app = App.get_running_app()
        makera = _makera()
        if app is None or makera is None:
            return
        if app.state == "N/A":
            self._rebuild_list(reset_scroll=True)
            self._sync_chrome()
            return
        if app.state != "Idle":
            self._rebuild_list(reset_scroll=True)
            self._sync_chrome()
            return
        threading.Thread(target=makera.loadRemoteDir, args=(path,), daemon=True).start()

    def _restore_device_dir(self):
        makera = _makera()
        if makera is None:
            if not (self.device_dir and os.path.isdir(self.device_dir)):
                self.device_dir = default_device_dir()
            return
        makera.fetch_recent_local_dir_list()
        for folder in makera.recent_local_dir_list:
            if folder and os.path.isdir(folder):
                self.device_dir = folder
                return
        self.device_dir = default_device_dir()

    def _restore_machine_dir(self):
        makera = _makera()
        if makera is None:
            if not is_under_machine_root(self.machine_dir):
                self.machine_dir = MACHINE_BASE_DIR
            return
        if not makera.recent_remote_dir_list:
            makera.fetch_recent_remote_dir_list()
        for folder in makera.recent_remote_dir_list:
            folder = (folder or "").strip()
            if folder and is_under_machine_root(folder):
                self.machine_dir = os.path.normpath(folder)
                return
        if not is_under_machine_root(self.machine_dir):
            self.machine_dir = MACHINE_BASE_DIR

    def _remember_device_dir(self):
        if self.firmware_mode:
            return
        makera = _makera()
        if makera is None or not self.device_dir or not os.path.isdir(self.device_dir):
            return
        makera.update_recent_local_dir_list(self.device_dir)

    def _remember_machine_dir(self):
        if self.firmware_mode:
            return
        makera = _makera()
        if makera is None or not is_under_machine_root(self.machine_dir):
            return
        makera.update_recent_remote_dir_list(os.path.normpath(self.machine_dir).replace("\\", "/"))

    def _persist_location(self):
        if not Config.has_section("carvera"):
            return
        Config.set("carvera", CONFIG_LAST_LOCATION, self.location)
        Config.write()

    def _on_window_size(self, *_args):
        self.set_compact_from_window()
        self._sync_chrome()

    def _on_job_changed(self, *_args):
        self._rebuild_list()
        self._sync_chrome()

    def _on_app_state(self, *_args):
        self._sync_chrome()

    def _current_entries(self) -> list:
        if self.location == LOCATION_DEVICE:
            return self._device_entries
        return self._machine_entries

    def _current_job_path(self) -> str:
        app = App.get_running_app()
        if app is None:
            return ""
        if self.location == LOCATION_MACHINE:
            return app.selected_remote_filename or ""
        return app.selected_local_filename or ""

    def _current_is_preview(self) -> bool:
        app = App.get_running_app()
        if app is None:
            return False
        return is_local_preview(app.selected_remote_filename or "", app.selected_local_filename or "")

    def _thumbnail_cache(self):
        app = App.get_running_app()
        if app is None:
            return None
        return thumbnail_cache_for_app(app.user_data_dir)

    def _fill_entry_thumbnails(self, entries: list) -> None:
        for entry in entries:
            entry["thumbnail"] = ""
        if self.firmware_mode:
            return
        cache = self._thumbnail_cache()
        if cache is None:
            return
        conn = ""
        if self.location == LOCATION_MACHINE:
            makera = _makera()
            if makera is None:
                return
            conn = makera._get_current_machine_connection_key() or ""
            if not conn:
                return
        for entry in entries:
            if entry.get("is_dir"):
                continue
            name = entry.get("name") or ""
            path = entry.get("path") or ""
            if not is_gcode_path(name) and not is_gcode_path(path):
                continue
            if self.location == LOCATION_DEVICE:
                key = local_cache_key(path)
                mtime = entry.get("date")
            else:
                key = machine_cache_key(conn, path)
                mtime = entry.get("date_raw") or ""
            result = cache.lookup(key, int(entry.get("size") or 0), mtime)
            entry["thumbnail"] = result.image_path or ""

    def _schedule_local_thumbnail_extract(self) -> None:
        if self.firmware_mode or self.location != LOCATION_DEVICE:
            return
        cache = self._thumbnail_cache()
        if cache is None:
            return
        self._thumb_gen += 1
        gen = self._thumb_gen
        directory = self.device_dir
        entries = list(self._device_entries)
        threading.Thread(
            target=self._extract_local_thumbnails,
            args=(gen, directory, entries, cache),
            daemon=True,
        ).start()

    def _extract_local_thumbnails(self, gen: int, directory: str, entries: list, cache) -> None:
        changed = False
        for entry in entries:
            if gen != self._thumb_gen:
                return
            if entry.get("is_dir"):
                continue
            path = entry.get("path") or ""
            if not is_gcode_path(path):
                continue
            size = int(entry.get("size") or 0)
            mtime = entry.get("date")
            key = local_cache_key(path)
            if cache.lookup(key, size, mtime).hit:
                continue
            cache.ingest_file(path, key, size, mtime)
            changed = True
        if changed:
            Clock.schedule_once(lambda *_: self._on_local_thumbnails_ready(gen, directory), 0)

    def _on_local_thumbnails_ready(self, gen: int, directory: str) -> None:
        if gen != self._thumb_gen:
            return
        if self.location != LOCATION_DEVICE or self.device_dir != directory:
            return
        self._rebuild_list()

    def _rebuild_list(self, *, reset_scroll: bool = False):
        rv = self.ids.get("file_list")
        if rv is None:
            return
        if self.ios_device_mode:
            rv.data = []
            if reset_scroll:
                rv.scroll_y = 1
            return
        selected_paths = self._selected_paths()
        entries = self._current_entries()
        self._fill_entry_thumbnails(entries)
        rv.data = group_and_sort_entries(
            entries,
            sort_key=self._sort_key,
            reverse=self._sort_reverse,
            keyword=self.search_text,
            firmware_mode=self.firmware_mode,
            current_job_path=self._current_job_path(),
            current_is_preview=self._current_is_preview(),
            multi_select=self.multi_select_mode and self._multi_select_allowed(),
            selected_paths=selected_paths,
            highlight_path=self._highlight_path,
        )
        if reset_scroll:
            rv.scroll_y = 1
        Clock.schedule_once(lambda *_: self._refresh_list_view(reset_scroll=reset_scroll), 0)

    def _refresh_list_view(self, *_args, reset_scroll: bool = False):
        rv = self.ids.get("file_list")
        if rv is None:
            return
        if rv.data:
            rv.refresh_from_data()
        layout = rv.children[0] if rv.children else None
        if reset_scroll or layout is None or layout.height <= rv.height + 1:
            rv.scroll_y = 1

    def _clear_list_selection(self):
        self._highlight_path = ""
        self.selected_device_file = ""
        self.selected_machine_file = ""
        self.selected_machine_filesize = 0
        self.selected_device_paths = []
        self.selected_machine_paths = []
        self._last_range_index = -1

    def _on_open_folder(self, path: str):
        if self.location == LOCATION_DEVICE:
            self.list_device_dir(path)
        else:
            self.list_machine_dir(path)

    def _select_file(self, path: str, intsize: int):
        self._highlight_path = path
        self._apply_selected_paths([path])
        if self.location == LOCATION_MACHINE:
            self.selected_machine_filesize = intsize
        self._rebuild_list()
        self._sync_chrome()

    def _on_select_row(self, path: str, kind: str, intsize: int):
        if kind != KIND_FILE:
            return
        if self._highlight_path == path:
            self._clear_list_selection()
            self._rebuild_list()
            self._sync_chrome()
            return
        self._select_file(path, intsize)

    def _on_activate_file(self, path: str, intsize: int):
        """Double-click: Upload & select on This device, Select file on Your machine."""
        if self.multi_select_mode:
            return
        self._select_file(path, intsize)
        state = self._action_state()
        if state.primary == "upload_and_use":
            self.on_upload_and_use()
        elif state.primary == "use_as_job":
            self.on_use_as_job()
        elif state.primary == "upload":
            self.on_upload()

    def _on_toggle_checked(self, path: str):
        paths = self._selected_paths()
        if path in paths:
            paths.remove(path)
        else:
            paths.append(path)
        self._apply_selected_paths(paths)
        self._rebuild_list()
        self._sync_chrome()

    def _on_long_press(self, path: str, index: int):
        if not self._multi_select_allowed():
            return
        if self._path_is_dir(path) and not self.multi_select_mode:
            self._highlight_path = path
            self._apply_selected_paths([path])
            self._rebuild_list()
            self._sync_chrome()
            return
        if not self.multi_select_mode:
            self.multi_select_mode = True
            self._apply_selected_paths([])
        self._on_toggle_checked(path)
        self._last_range_index = index

    def _on_modifier_select(self, path: str, index: int, modifier: str):
        if not self._multi_select_allowed():
            return
        if not self.multi_select_mode:
            self.multi_select_mode = True
            self._apply_selected_paths([])
        if modifier == "shift" and self._last_range_index >= 0:
            rv = self.ids.get("file_list")
            if rv is None:
                return
            start = min(self._last_range_index, index)
            end = max(self._last_range_index, index)
            paths = self._selected_paths()
            for i in range(start, end + 1):
                if i < 0 or i >= len(rv.data):
                    continue
                row = rv.data[i]
                if not row.get("selectable"):
                    continue
                p = row.get("path")
                if p and p not in paths:
                    paths.append(p)
            self._apply_selected_paths(paths)
            self._rebuild_list()
            self._sync_chrome()
            return
        self._last_range_index = index
        self._on_toggle_checked(path)

    def _multi_select_allowed(self) -> bool:
        if self.firmware_mode:
            return False
        if self.location == LOCATION_MACHINE:
            return True
        if self.location == LOCATION_DEVICE:
            return not is_ios_platform()
        return False

    def _selected_paths(self) -> list:
        if self.location == LOCATION_DEVICE:
            return list(self.selected_device_paths)
        return list(self.selected_machine_paths)

    def _apply_selected_paths(self, paths: list) -> None:
        paths = list(paths)
        if self.location == LOCATION_DEVICE:
            self.selected_device_paths = paths
            self.selected_device_file = paths[-1] if paths else ""
            return
        self.selected_machine_paths = paths
        if paths:
            last = paths[-1]
            self.selected_machine_file = last
            self.selected_machine_filesize = 0 if self._path_is_dir(last) else self._size_for_path(last)
        else:
            self.selected_machine_file = ""
            self.selected_machine_filesize = 0

    def _restore_single_selection(self) -> None:
        """Keep the last checked item as the single-select highlight when leaving multi-select."""
        paths = self._selected_paths()
        keep = paths[-1] if paths else ""
        if keep:
            self._highlight_path = keep
            self._apply_selected_paths([keep])
            return
        self._highlight_path = ""
        self._apply_selected_paths([])

    def _path_is_dir(self, path: str) -> bool:
        if not path:
            return False
        norm = os.path.normpath(path)
        for entry in self._current_entries():
            if os.path.normpath(entry.get("path") or "") == norm:
                return bool(entry.get("is_dir"))
        return self.location == LOCATION_DEVICE and os.path.isdir(path)

    def _size_for_path(self, path: str) -> int:
        for entry in self._current_entries():
            if os.path.normpath(entry.get("path") or "") == os.path.normpath(path):
                return int(entry.get("size") or 0)
        return 0

    def _action_state(self) -> ActionState:
        app = App.get_running_app()
        connected = app is not None and app.state != "N/A"
        idle = app is not None and app.state == "Idle"
        paths = self._selected_paths()
        highlight = self.selected_device_file if self.location == LOCATION_DEVICE else self.selected_machine_file
        if self.multi_select_mode:
            selected_is_file = False
            selected_count = len(paths)
        else:
            selected_is_file = bool(highlight) and not self._path_is_dir(highlight)
            selected_count = len(paths) or (1 if highlight else 0)
        return compute_action_state(
            location=self.location,
            firmware_mode=self.firmware_mode,
            ios=is_ios_platform(),
            machine_connected=connected,
            machine_idle=idle,
            selected_is_file=selected_is_file,
            selected_count=selected_count,
            multi_select_mode=self.multi_select_mode,
        )

    def _sync_chrome(self):
        app = App.get_running_app()
        state = self._action_state()
        self._update_job_banner(app)
        self._update_breadcrumbs()
        self._update_empty_state(app, state)
        self._update_listing_banner(app)
        self.sort_button_text = self._sort_label()
        self.curr_dir_name = os.path.basename(self.device_dir if self.location == LOCATION_DEVICE else self.machine_dir)
        self.device_tab_path = device_tab_path_display(self.device_dir)
        connected = app is not None and app.state != "N/A"
        self.machine_tab_path = machine_tab_path_display(self.machine_dir, connected=connected, translate=tr._)
        self._rebuild_footer(state)
        self._sync_tool_buttons(state)

    def _update_job_banner(self, app):
        if self.firmware_mode or app is None:
            self.job_filename = ""
            self.job_badge_text = ""
            self.can_clear_job = False
            return
        remote = app.selected_remote_filename if app else ""
        local = app.selected_local_filename if app else ""
        filename, badge, can_clear = current_file_banner(remote, local, translate=tr._)
        self.job_filename = filename
        self.job_badge_text = badge
        self.can_clear_job = can_clear

    def _update_listing_banner(self, app):
        if self.location != LOCATION_MACHINE or self.firmware_mode:
            self.listing_banner_text = ""
            return
        if app is None or app.state == "N/A":
            self.listing_banner_text = ""
            return
        if app.state != "Idle":
            self.listing_banner_text = tr._("Listing is paused while the machine is busy")
            return
        self.listing_banner_text = ""

    def _update_empty_state(self, app, state: ActionState):
        if self.ios_device_mode or state.show_ios_browse:
            self.show_empty_state = True
            self.show_list = False
            self.empty_state_text = tr._("Use Browse to pick a file on this device.")
            return
        if self.location == LOCATION_MACHINE and (app is None or app.state == "N/A"):
            self.show_empty_state = True
            self.show_list = False
            self.empty_state_text = tr._("Connect to browse files on the machine")
            return
        rv = self.ids.get("file_list")
        has_rows = bool(rv and rv.data)
        if not has_rows:
            self.show_empty_state = True
            self.show_list = False
            if self.search_text.strip():
                self.empty_state_text = tr._("No files match this search")
            else:
                self.empty_state_text = tr._("This folder is empty")
            return
        self.show_empty_state = False
        self.show_list = True
        self.empty_state_text = ""

    def _update_breadcrumbs(self):
        directory = self.device_dir if self.location == LOCATION_DEVICE else self.machine_dir
        markers = (MACHINE_BASE_DIR, MACHINE_BASE_DIR_WIN, "gcodes") if self.location == LOCATION_MACHINE else ("",)
        root_label = "gcodes" if self.location == LOCATION_MACHINE else "root"
        full_paths, labels = Utils.directory_breadcrumb_paths(
            directory,
            root_label_markers=markers,
            root_label=root_label,
            max_ancestors=32,
        )
        full_paths, labels = trim_breadcrumb_pairs(full_paths, labels, machine=self.location == LOCATION_MACHINE)
        self._breadcrumb_paths = full_paths
        box = self.ids.get("breadcrumb_box")
        if box is None:
            return
        box.clear_widgets()
        sv = self.ids.get("breadcrumb_scroll")
        if sv is not None:
            sv.scroll_x = 0
        for i, label in enumerate(labels):
            if i > 0:
                sep = Label(
                    text=" > ",
                    size_hint_x=None,
                    width=dp(16),
                    color=(150 / 255, 150 / 255, 150 / 255, 1),
                )
                box.add_widget(sep)
            chip = FileBrowserPathChip(
                text=label,
                bold=True,
                size_hint_x=None,
                color=(225 / 255, 225 / 255, 225 / 255, 1),
            )
            chip.bind(texture_size=lambda inst, value: setattr(inst, "width", value[0] + dp(8)))
            chip.bind(on_release=lambda _btn, idx=i: self.goto_path(idx))
            box.add_widget(chip)
        Clock.schedule_once(lambda *_: self._align_breadcrumb_scroll(), 0)

    def _align_breadcrumb_scroll(self):
        sv = self.ids.get("breadcrumb_scroll")
        box = self.ids.get("breadcrumb_box")
        if sv is None or box is None:
            return
        sv.scroll_x = 1 if box.width > sv.width + 1 else 0

    def _can_go_up(self) -> bool:
        if self.location == LOCATION_DEVICE:
            parent = os.path.dirname(self.device_dir)
            return bool(parent and parent != self.device_dir)
        return machine_parent_dir(self.machine_dir) is not None

    def _sync_tool_buttons(self, state: ActionState):
        ids = self.ids
        if "btn_up" in ids:
            ids.btn_up.disabled = not self._can_go_up()
        if "btn_places" in ids:
            ids.btn_places.disabled = not state.show_places
            ids.btn_places.opacity = 1 if state.show_places else 0
        if "btn_sort" in ids:
            ids.btn_sort.disabled = self.show_empty_state and not self.show_list
        self.show_multi_button = state.show_multi_toggle or state.show_cancel_multi
        if "btn_multi" in ids:
            ids.btn_multi.btn_text = tr._("Done") if self.multi_select_mode else tr._("Select")
            ids.btn_multi.icon = "data/check.png" if self.multi_select_mode else "data/checkbox-multiple-outline.png"
        self.show_new_folder_button = state.show_new_folder
        if "ti_search" in ids:
            ids.ti_search.disabled = not state.search_enabled
        if "btn_ios_browse" in ids:
            ids.btn_ios_browse.opacity = 1 if state.show_ios_browse else 0
            ids.btn_ios_browse.disabled = not state.show_ios_browse

    def _rebuild_footer(self, state: ActionState):
        bar = self.ids.get("footer_actions")
        if bar is None:
            return
        bar.clear_widgets()
        if state.show_upload_and_use:
            bar.add_widget(
                self._footer_btn(
                    tr._("Upload & select"),
                    self.on_upload_and_use,
                    icon="data/play.png",
                    primary=state.primary == "upload_and_use",
                    tooltip=self._upload_dest_tooltip(),
                )
            )
        if state.show_upload:
            bar.add_widget(
                self._footer_btn(
                    tr._("Upload"),
                    self.on_upload,
                    icon="data/upload.png",
                    primary=state.primary == "upload",
                    tooltip=self._upload_dest_tooltip() if not self.firmware_mode else "",
                )
            )
        if state.show_preview:
            bar.add_widget(
                self._footer_btn(
                    tr._("Preview"),
                    self.on_preview,
                    icon="data/eye.png",
                    primary=state.primary == "preview",
                )
            )
        if state.show_use_as_job:
            bar.add_widget(
                self._footer_btn(
                    tr._("Select file"),
                    self.on_use_as_job,
                    icon="data/play.png",
                    primary=state.primary == "use_as_job",
                )
            )
        if state.show_download:
            bar.add_widget(
                self._footer_btn(
                    tr._("Download"),
                    self.on_download,
                    icon="data/download.png",
                    tooltip=self._download_dest_tooltip(),
                )
            )
        if state.show_rename:
            bar.add_widget(self._footer_btn(tr._("Rename"), self.on_rename, icon="data/pencil.png"))
        if state.show_delete:
            bar.add_widget(
                self._footer_btn(
                    tr._("Delete"),
                    self.on_delete,
                    icon="data/delete.png",
                    primary=state.primary == "delete",
                    destructive=True,
                )
            )

    def _footer_btn(self, text, callback, *, icon="", primary=False, destructive=False, tooltip=""):
        btn = FileBrowserActionButton(
            btn_text=text,
            icon=icon,
            primary=primary,
            destructive=destructive,
            flat=True,
            tooltip_txt=tooltip,
        )
        if self.compact and primary:
            btn.size_hint_x = 1
            btn.width = 0
        else:
            btn.size_hint_x = None
        btn.bind(on_release=lambda *_: callback())
        return btn

    def _upload_dest_tooltip(self) -> str:
        return upload_dest_tooltip(self.machine_dir, translate=tr._)

    def _download_dest_tooltip(self) -> str:
        return download_dest_tooltip(self.device_dir, translate=tr._)

    def _sort_label(self) -> str:
        names = {SORT_NAME: tr._("Name"), SORT_DATE: tr._("Date"), SORT_SIZE: tr._("Size")}
        arrow = "↓" if self._sort_reverse else "↑"
        return f"{names.get(self._sort_key, tr._('Date'))} {arrow}"

    def _rebuild_sort_dropdown(self):
        self._sort_dropdown.clear_widgets()
        for key, label in ((SORT_NAME, tr._("Name")), (SORT_DATE, tr._("Date")), (SORT_SIZE, tr._("Size"))):
            btn = Button(text=label, size_hint_y=None, height=dp(36))
            btn.bind(on_release=lambda _btn, k=key: self._choose_sort(k))
            self._sort_dropdown.add_widget(btn)

    def _choose_sort(self, key: str):
        self._sort_dropdown.dismiss()
        if key == self._sort_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = key
            self._sort_reverse = DEFAULT_SORT_REVERSE[key]
        self.sort_button_text = self._sort_label()
        self._rebuild_list()

    def _pick_ios_file(self):
        try:
            from carveracontroller import ios_helpers

            ios_helpers.pick_file()
        except Exception:
            pass

    def on_search_from_input(self, text: str):
        self.search_text = text


def _makera():
    app = App.get_running_app()
    return None if app is None else app.root


if "FileBrowserLocationTab" not in Factory.classes:
    Factory.register("FileBrowserLocationTab", cls=FileBrowserLocationTab)

if "FileBrowserIconButton" not in Factory.classes:
    Factory.register("FileBrowserIconButton", cls=FileBrowserIconButton)

if "FileBrowserActionButton" not in Factory.classes:
    Factory.register("FileBrowserActionButton", cls=FileBrowserActionButton)

if "FileBrowserEmptyOverlay" not in Factory.classes:
    Factory.register("FileBrowserEmptyOverlay", cls=FileBrowserEmptyOverlay)

if "FileBrowserBadge" not in Factory.classes:
    Factory.register("FileBrowserBadge", cls=FileBrowserBadge)

if "FileBrowserPathChip" not in Factory.classes:
    Factory.register("FileBrowserPathChip", cls=FileBrowserPathChip)

if "FileBrowserPopup" not in Factory.classes:
    Factory.register("FileBrowserPopup", cls=FileBrowserPopup)
