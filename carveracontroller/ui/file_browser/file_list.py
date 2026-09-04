"""RecycleView rows and list widget for the file browser."""

from __future__ import annotations

import sys
import time

from kivy.clock import Clock
from kivy.compat import string_types
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.widget import Widget

from carveracontroller.addons.tooltips.Tooltips import Tooltip, _compute_tooltip_box_size

from .sources import KIND_FILE, KIND_FOLDER

THUMB_TOOLTIP_SIDE = 280


class FileBrowserThumb(Widget):
    """In-row G-code preview used in place of the type icon. Hover shows a larger tooltip; clicks pass through."""

    source = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._tooltip = None
        self._hover_pos = None
        self._mouse_bound = False
        super().__init__(**kwargs)
        if sys.platform == "ios":
            return
        self._bind_mouse()

    def on_touch_down(self, _touch):
        return False

    def on_touch_move(self, _touch):
        return False

    def on_touch_up(self, _touch):
        return False

    def on_parent(self, _instance, parent):
        if parent is None:
            self.close_tooltip()
            self._unbind_mouse()
        elif sys.platform != "ios":
            self._bind_mouse()

    def _bind_mouse(self):
        if self._mouse_bound or sys.platform == "ios":
            return
        Window.bind(mouse_pos=self.on_mouse_pos)
        self._mouse_bound = True

    def _unbind_mouse(self):
        if not self._mouse_bound:
            return
        Window.unbind(mouse_pos=self.on_mouse_pos)
        self._mouse_bound = False

    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                current = self.parent
                depth = 0
                while current and depth < 20:
                    if current == child:
                        return False
                    current = current.parent
                    depth += 1
                return True
        return False

    def _build_tooltip(self, *_args):
        if self._tooltip is not None:
            return
        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()
        # Keep tooltip_label in the tree: Tooltips.kv binds to it. Collapse it
        # instead of remove_widget so those WeakProxy rules stay valid.
        self._tooltip.spacing = 0
        label = self._tooltip.ids.tooltip_label
        label.text = ""
        label.opacity = 0
        label.size = (0, 0)
        self._tooltip.ids.tooltip_image.bind(texture_size=self._update_image_size)

    def _sync_tooltip_image(self):
        self._build_tooltip()
        image_widget = self._tooltip.ids.tooltip_image
        if self.source:
            if image_widget.source != self.source:
                image_widget.source = self.source
            image_widget.visible = True
        else:
            image_widget.source = ""
            image_widget.texture = None
            image_widget.size = (0, 0)
            image_widget.visible = False
        self._update_image_size()

    def _tooltip_display_size(self):
        image_widget = self._tooltip.ids.tooltip_image
        width, height = image_widget.texture_size
        if width <= 0 or height <= 0:
            return (THUMB_TOOLTIP_SIDE, THUMB_TOOLTIP_SIDE)
        long_side = max(width, height)
        if long_side <= THUMB_TOOLTIP_SIDE:
            return (width, height)
        scale = THUMB_TOOLTIP_SIDE / float(long_side)
        return (max(1, round(width * scale)), max(1, round(height * scale)))

    def _update_image_size(self, *_args):
        if self._tooltip is None:
            return
        image_widget = self._tooltip.ids.tooltip_image
        if self.source:
            image_widget.size = self._tooltip_display_size()
        else:
            image_widget.size = (0, 0)
        self._update_tooltip_size()

    def _update_tooltip_size(self):
        if self._tooltip is None:
            return
        tooltip_image = self._tooltip.ids.tooltip_image
        width, height = _compute_tooltip_box_size(
            0,
            0,
            tooltip_image.size[0],
            tooltip_image.size[1],
            has_text=False,
            has_image=bool(self.source),
            horizontal=False,
            spacing=0,
        )
        self._tooltip.size = (width, height)
        self._tooltip.canvas.ask_update()

    def on_mouse_pos(self, *_args):
        if not self.show_tooltips or not self.source or not self.get_root_window():
            self.close_tooltip()
            return
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
        pos = _args[1]
        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            self._hover_pos = pos
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def _layout_tooltip_at(self, pos):
        if not self.source:
            return
        self._sync_tooltip_image()
        window_width, window_height = Window.size
        self._update_tooltip_size()
        tooltip_width, tooltip_height = self._tooltip.size
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

    def close_tooltip(self, *_args):
        Clock.unschedule(self.display_tooltip)
        if self._tooltip is not None:
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *_args):
        if not self.source:
            return
        if self._hover_pos is not None:
            self._layout_tooltip_at(self._hover_pos)
        if self._tooltip is not None:
            Window.add_widget(self._tooltip)


class FileBrowserRow(RecycleDataViewBehavior, BoxLayout):
    """One RecycleView row: folder or file."""

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
    thumbnail = StringProperty("")

    _touch_start_time = 0.0
    _touch_start_pos = None

    def refresh_view_attrs(self, rv, index, data):
        thumb = self.ids.get("thumb") if self.ids else None
        if thumb is not None:
            thumb.close_tooltip()
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
        if not self.selectable:
            return False

        self._touch_start_time = time.time()
        self._touch_start_pos = touch.pos
        rv = self.parent.recycleview
        modifiers = _touch_modifiers(touch)

        if touch.is_double_tap and not self.show_checkbox:
            if self.kind == KIND_FOLDER:
                rv.dispatch("on_open_folder", self.path)
                return True
            if self.kind == KIND_FILE:
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

        rv.dispatch("on_select_row", self.path, self.kind, int(self.intsize))
        return True

    def on_touch_up(self, touch):
        if (
            self.collide_point(*touch.pos)
            and self.selectable
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


if "FileBrowserThumb" not in Factory.classes:
    Factory.register("FileBrowserThumb", cls=FileBrowserThumb)

if "FileBrowserRow" not in Factory.classes:
    Factory.register("FileBrowserRow", cls=FileBrowserRow)

if "FileBrowserList" not in Factory.classes:
    Factory.register("FileBrowserList", cls=FileBrowserList)
