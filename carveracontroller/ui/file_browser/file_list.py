"""RecycleView rows and list widget for the file browser."""

from __future__ import annotations

import time

from kivy.core.window import Window
from kivy.factory import Factory
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior

from .sources import KIND_FILE, KIND_FOLDER, KIND_HEADER


class FileBrowserRow(RecycleDataViewBehavior, BoxLayout):
    """One RecycleView row: section header, folder, or file."""

    index = None
    row_index = NumericProperty(0)
    kind = StringProperty(KIND_FILE)
    filename = StringProperty("")
    path = StringProperty("")
    subtitle = StringProperty("")
    file_type = StringProperty("")
    icon = StringProperty("data/file-outline.png")
    filesize = StringProperty("")
    filedate = StringProperty("")
    is_dir = BooleanProperty(False)
    selected = BooleanProperty(False)
    is_current_job = BooleanProperty(False)
    current_badge = StringProperty("")
    show_checkbox = BooleanProperty(False)
    checked = BooleanProperty(False)
    selectable = BooleanProperty(True)
    intsize = NumericProperty(0)

    _touch_start_time = 0.0
    _touch_start_pos = None

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        self.row_index = index
        return super().refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if not self.collide_point(*touch.pos):
            return False
        if "button" in touch.profile and str(touch.button).startswith("scroll"):
            return False
        if self.kind == KIND_HEADER or not self.selectable:
            return False

        self._touch_start_time = time.time()
        self._touch_start_pos = touch.pos
        rv = self.parent.recycleview
        modifiers = _touch_modifiers(touch)

        if touch.is_double_tap and self.kind == KIND_FILE:
            rv.dispatch("on_activate_file", self.path, int(self.intsize))
            return True

        if {"ctrl", "control", "meta"} & modifiers:
            rv.dispatch("on_modifier_select", self.path, self.index, "ctrl")
            return True
        if "shift" in modifiers:
            rv.dispatch("on_modifier_select", self.path, self.index, "shift")
            return True

        if self.show_checkbox:
            rv.dispatch("on_toggle_checked", self.path)
            return True

        if self.kind == KIND_FOLDER:
            rv.dispatch("on_open_folder", self.path)
            return True

        rv.dispatch("on_select_row", self.path, self.kind, int(self.intsize))
        return True

    def on_touch_up(self, touch):
        if (
            self.collide_point(*touch.pos)
            and self.selectable
            and self.kind != KIND_HEADER
            and self._touch_start_pos is not None
            and time.time() - self._touch_start_time >= 0.5
            and _same_position(touch.pos, self._touch_start_pos)
        ):
            rv = self.parent.recycleview
            rv.dispatch("on_long_press", self.path, self.index)
            self._touch_start_pos = None
            return True
        self._touch_start_pos = None
        return super().on_touch_up(touch)


class FileBrowserList(RecycleView):
    """File list RecycleView. Events are handled by FileBrowserPopup."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_open_folder")
        self.register_event_type("on_select_row")
        self.register_event_type("on_activate_file")
        self.register_event_type("on_toggle_checked")
        self.register_event_type("on_long_press")
        self.register_event_type("on_modifier_select")

    def on_open_folder(self, path):
        pass

    def on_select_row(self, path, kind, intsize):
        pass

    def on_activate_file(self, path, intsize):
        pass

    def on_toggle_checked(self, path):
        pass

    def on_long_press(self, path, index):
        pass

    def on_modifier_select(self, path, index, modifier):
        pass


def _touch_modifiers(touch) -> set[str]:
    modifiers: set[str] = set()
    for source in (
        getattr(touch, "modifiers", None),
        getattr(Window, "modifiers", None),
        getattr(Window, "_modifiers", None),
    ):
        if callable(source):
            source = source()
        if source:
            modifiers.update(source)
    return modifiers


def _same_position(pos1, pos2, tolerance=12):
    return abs(pos1[0] - pos2[0]) <= tolerance and abs(pos1[1] - pos2[1]) <= tolerance


if "FileBrowserRow" not in Factory.classes:
    Factory.register("FileBrowserRow", cls=FileBrowserRow)

if "FileBrowserList" not in Factory.classes:
    Factory.register("FileBrowserList", cls=FileBrowserList)
