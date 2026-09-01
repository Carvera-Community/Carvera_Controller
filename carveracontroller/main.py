import os
import struct

import quicklz

# import os
# os.environ["KIVY_METRICS_DENSITY"] = '1'

CONFIG_FILES_TO_BACK_UP = [
    "/sd/cartesian_nm.grid",
    "/sd/config.default",
    "/sd/config.txt",
    "/sd/custom_tool_slots.txt",
    "/sd/flex_compensation.dat",
]

MACHINE_CONFIG_FILES = {
    "C1": "config_c1.json",
    "CA1": "config_ca1.json",
    "Z1": "config_z1.json",
}

MAX_CONFIG_DOWNLOAD_ATTEMPTS = 3


def is_android():
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ or "ANDROID_APP_PATH" in os.environ


def is_ios():
    return os.environ.get("KIVY_BUILD") == "ios"


if is_android():
    try:
        from jnius import autoclass

        DisplayMetrics = autoclass("android.util.DisplayMetrics")
        WindowManager = autoclass("android.view.WindowManager")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity = PythonActivity.mActivity
        metrics = DisplayMetrics()
        activity.getWindowManager().getDefaultDisplay().getMetrics(metrics)
        screen_width_density = int(metrics.widthPixels * 10 / 1000) / 10
        screen_height_density = int(metrics.heightPixels * 10 / 550) / 10

        os.environ["KIVY_METRICS_DENSITY"] = str(min(screen_width_density, screen_height_density))

    except ImportError:
        print("Pyjnius Import Fail.")

if is_ios() and os.environ.get("CARVERA_UI_IDIOM") == "phone":
    # Screen dimensions are exported by main.m (UIScreen access from pyobjus
    # is unreliable). iPad keeps default density; only iPhone is rescaled.
    try:
        w_px = int(os.environ["CARVERA_SCREEN_PX_W"])
        h_px = int(os.environ["CARVERA_SCREEN_PX_H"])
        screen_width_density = int(w_px * 10 / 1000) / 10
        screen_height_density = int(h_px * 10 / 550) / 10

        os.environ["KIVY_METRICS_DENSITY"] = str(min(screen_width_density, screen_height_density))
    except (KeyError, ValueError) as e:
        print(f"iOS density setup skipped: {e}")

import datetime
import logging
import sys
import threading
import time

# os.environ['KIVY_GL_DEBUG'] = '1'
from kivy.core.clipboard import Clipboard
from kivy.utils import platform as kivy_platform

from . import translation
from .translation import tr

logger = logging.getLogger(__name__)

import json
import os
import platform
import re
import subprocess
import tempfile

import kivy.lang.builder as _kivy_builder
import kivy.uix.widget as _kivy_widget
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.config import Config
from kivy.factory import Factory
from kivy.graphics import Color, Ellipse, InstructionGroup, Line, PopMatrix, PushMatrix, Rectangle, Rotate, Translate
from kivy.metrics import Metrics, dp
from kivy.properties import (
    BooleanProperty,
    DictProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior, FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.settings import SettingItem, SettingsPanel, SettingsWithSidebar
from kivy.uix.slider import Slider
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


def _safe_widget_destructor(uid, _ref):
    # Kivy 2.3.1 does `del _widget_destructors[uid]` in a weakref callback.
    # Python 3.12+ GC can invoke that after the uid is already gone, which
    # prints KeyError on quit. USB/libusb teardown makes that extra collection
    # more likely than serial or WiFi.
    # https://github.com/kivy/kivy/issues/5005
    _kivy_widget._widget_destructors.pop(uid, None)
    _kivy_builder.Builder.unbind_widget(uid)


_kivy_widget._widget_destructor = _safe_widget_destructor

from carveracontroller.addons.beds.catalog import is_known_machine
from carveracontroller.addons.beds.store import (
    get_bed,
    load_store,
    resolve_mesh_path,
    selected_id,
)
from carveracontroller.addons.beds.ui.BedSettingsPopup import BedSettingsPopup
from carveracontroller.addons.cam import CamMetadata, extract_cam_metadata
from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup
from carveracontroller.addons.pendant import (
    SUPPORTED_PENDANTS,
    OverrideController,
    SettingGamepadBindings,
    SettingPendantSelector,
)
from carveracontroller.addons.probing.ProbingPopup import ProbingPopup
from carveracontroller.addons.stock.stock_defaults import (
    bounds_from_settings,
    carver_mode_from_settings,
    checkpoint_level_from_settings,
    default_settings,
    material_from_settings,
    mesh_while_playing_from_settings,
    shape_from_settings,
    voxel_resolution_from_settings,
)
from carveracontroller.addons.stock.stock_estimate import auto_stock_for_loaded_file, header_stock_usable
from carveracontroller.addons.stock.ui.StockSettingsPopup import StockSettingsPopup
from carveracontroller.serial_listeners import dispatch_serial_line


# Custom Property to monitor CNC.vars["sw_light"] changes
class LightProperty(BooleanProperty):
    """Custom property that monitors CNC.vars['sw_light'] and converts it to a boolean"""

    def __init__(self, defaultvalue=False, **kwargs):
        super().__init__(defaultvalue=defaultvalue, **kwargs)
        self._light_value = 0
        # Don't call update_from_state in __init__ since we don't have an obj yet

    def update_from_state(self, obj):
        """Update the property value from CNC.vars['sw_light']"""
        try:
            current_value = CNC.vars.get("sw_light", 0)
            if current_value != self._light_value:
                self._light_value = current_value
                # Convert to boolean: 1 = True (down), 0 = False (normal)
                new_bool_value = current_value == 1
                BooleanProperty.set(self, obj, new_bool_value)

        except Exception as e:
            # If CNC.vars is not available yet, default to False
            BooleanProperty.set(self, obj, False)


import webbrowser
from functools import partial

from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.network.urlrequest import UrlRequest
from kivy.resources import resource_add_path

from .WIFIStream import MachineDetector

if sys.platform == "ios":
    from pyobjus import autoclass
    from pyobjus.dylib_manager import load_framework

    try:
        load_framework("/System/Library/Frameworks/UIKit.framework")

        NSURL = autoclass("NSURL")
        UIApplication = autoclass("UIApplication")

        def ios_webbrowser_open(url, new=None):
            nsurl = NSURL.URLWithString_(url)
            app = UIApplication.sharedApplication()

            options = {}
            app.openURL_options_completionHandler_(nsurl, options, None)

        webbrowser.open = ios_webbrowser_open
    except:
        # Doesn't work for iOS simulator
        pass

# import os
import shutil
import string
from pathlib import Path

from kivy.config import ConfigParser
from kivy.lang import Builder

from . import Utils, custom_widgets
from .__version__ import __version__
from .addons.camera.CameraView import ADJUST_DEFAULT
from .addons.camera.Z1Camera import (
    DEFAULT_RESOLUTION,
    RESOLUTION_BY_SIZE,
    RESOLUTION_VALUES,
    Z1Camera,
    has_camera,
    set_resolution,
)
from .addons.intellisense.engine import highlight_mdi_line
from .addons.intellisense.ui import (
    IntellisenseExplainRowMixin,
    handle_mdi_intellisense_key,
    hide_gcode_explain,
    hide_mdi_intellisense,
    update_mdi_intellisense,
)
from .addons.probing.ProbingControls import ProbeButton
from .addons.tool_visualization import (
    format_tool_tooltip,
)
from .addons.tooltips.Tooltips import Tooltip, ToolTipButton, ToolTipDropDown
from .CNC import (
    CNC,
    GCODE_DEFAULT_COLORS,
    LASER_TOOL_NUMBER,
    OCODE_PATTERN,
    PROBE_3D_TOOL_NUMBER,
    ZPROBE_TOOL_NUMBER,
    detect_document_unit,
    escape_gcode_markup,
    highlight_gcode_line,
    is_probe_tools_range,
    unit_scale_to_mm,
)
from .Controller import (
    CONN_USB,
    CONN_WIFI,
    CONNECTED,
    LOAD_CONN_WIFI,
    LOAD_DIR,
    LOAD_MKDIR,
    LOAD_MV,
    LOAD_RM,
    LOAD_WIFI,
    NOT_CONNECTED,
    SEND_FILE,
    STATECOLOR,
    STATECOLORDEF,
    Controller,
)
from .GcodeViewer import (
    COLOR_SCHEME_BY_SPEED,
    COLOR_SCHEME_BY_TOOL,
    COLOR_SCHEME_BY_TYPE,
    COLOR_SCHEME_BY_Z,
    VISIBILITY_ALL_BUCKET_BITS,
    VISIBILITY_MAX_TOOLS,
    GCodeViewer,
)
from .ui import widget_helpers
from .ui.PlayProgressBar import (
    next_tool_change_after_line,
    play_percent_from_line,
    seconds_from_start,
    seconds_until_target,
    tool_change_markers_to_percents,
)
from .ui.popups.adv_calibrate import AdvCalibratePopup
from .ui.popups.set_position import (
    ChangeToolPopup,
    MoveAPopup,
    SetAPopup,
    SetToolPopup,
    SetXPopup,
    SetYPopup,
    SetZPopup,
)

HALT_REASON_ESTOP = 13


def load_halt_translations(tr: translation.Lang):
    """Loads the appropriate language translation"""
    HALT_REASON = {
        # Just need to unlock the mahchine
        1: tr._("Halt Manually"),
        2: tr._("Home Fail"),
        3: tr._("Probe Fail"),
        4: tr._("Calibrate Fail"),
        5: tr._("ATC Home Fail"),
        6: tr._("ATC Invalid Tool Number"),
        7: tr._("ATC Drop Tool Fail"),
        8: tr._("ATC Position Occupied"),
        9: tr._("Spindle Temp Error"),
        10: tr._("Soft Limit Triggered"),
        11: tr._("Cover opened when playing"),
        12: tr._("Wireless probe dead or not set"),
        13: tr._("Emergency stop button pressed"),
        14: tr._("Electronics Temp Error"),
        16: tr._("3D probe crash detected"),
        # Need to reset the machine
        21: tr._("Hard Limit Triggered, reset needed"),
        22: tr._("X Axis Motor Error, reset needed"),
        23: tr._("Y Axis Motor Error, reset needed"),
        24: tr._("Z Axis Motor Error, reset needed"),
        25: tr._("Spindle Stall, reset needed"),
        26: tr._("SD card read fail, reset needed"),
        # Need to power off/on the machine
        41: tr._("Spindle Alarm, power off/on needed"),
    }
    return HALT_REASON


def app_base_path():
    """
    The base path should be used for reference for any bundled assets.
    This should be done via __file__ since this will work in situations
    where the application is both frozen in pyinstaller, and when run normally
    """
    return os.path.abspath(os.path.dirname(__file__))


def register_fonts(base_path):
    """
    To support both frozen and normal execution of the application font locations
    should be registered
    """
    arialuni_location = os.path.abspath(os.path.join(os.path.dirname(__file__), "ARIALUNI.ttf"))
    LabelBase.register(name="ARIALUNI", fn_regular=arialuni_location)


def register_images(base_path):
    """
    To support both frozen and normal execution of the application image locations
    should be registered
    """
    icons_path = os.path.join(base_path)
    resource_add_path(icons_path)


class MDITextInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.past_mdi_commands = []
        self.active_past_mdi_index = 0
        self.bind(focus=self.on_focus)
        self.bind(text=self._on_mdi_text)

    def on_focus(self, instance, have_focus):
        if have_focus:
            Clock.schedule_once(lambda _dt: update_mdi_intellisense(self), 0)
        else:
            hide_mdi_intellisense()

    def _on_mdi_text(self, _instance, _value):
        if self.focus:
            update_mdi_intellisense(self)

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        key = keycode[0] if isinstance(keycode, (tuple, list)) else keycode
        if handle_mdi_intellisense_key(self, key, modifiers):
            return True
        if self._handle_navigation_key(key, modifiers):
            return True
        return super().keyboard_on_key_down(window, keycode, text, modifiers)

    def _handle_navigation_key(self, key, modifiers):
        ENTER_KEY = 13
        UP_ARROW_KEY = 273
        DOWN_ARROW_KEY = 274
        if self.focus and "ctrl" in modifiers and key == ENTER_KEY:
            self.send_mdi_command()
            return True
        if self.focus and key == UP_ARROW_KEY:
            cursor_is_at_top_left = self.cursor_index() == 0
            can_move_backward_in_history = len(self.past_mdi_commands) > 0 and self.active_past_mdi_index > 0
            if cursor_is_at_top_left and can_move_backward_in_history:
                self.active_past_mdi_index = max(0, self.active_past_mdi_index - 1)
                self.text = self.past_mdi_commands[self.active_past_mdi_index]
                self.cursor = (0, 0)
                return True
            col, row = self.cursor
            if row == 0:
                self.cursor = (0, 0)
                return True
            # Let the TextInput handle moving up a line
            return False

        if self.focus and key == DOWN_ARROW_KEY:
            cursor_is_at_bottom_right = self.cursor_index() == len(self.text)
            can_move_forward_in_history = (
                len(self.past_mdi_commands) > 0 and self.active_past_mdi_index < len(self.past_mdi_commands) - 1
            )
            if cursor_is_at_bottom_right and can_move_forward_in_history:
                self.active_past_mdi_index = min(len(self.past_mdi_commands) - 1, self.active_past_mdi_index + 1)
                self.text = self.past_mdi_commands[self.active_past_mdi_index]
                return True
            col, row = self.cursor
            lines_in_command = self.text.count("\n")
            if row == lines_in_command:
                self.cursor = (len(self.text), row)
                return True
            # Let the TextInput handle moving down a line
            return False

        return False

    def send_mdi_command(self):
        cmd_to_send = self.text.strip()
        if not cmd_to_send:
            return
        hide_mdi_intellisense()
        self.past_mdi_commands.append(cmd_to_send)
        self.active_past_mdi_index = len(self.past_mdi_commands)
        app = App.get_running_app()
        app.root.send_cmd()


class GcodePlaySlider(Slider):
    """Preview timeline scrubber with a thin green cut-simulation progress strip
    and blue checkpoint markers."""

    sim_progress = NumericProperty(0.0)  # 0–100, path-distance percent carved by the voxel sim
    sim_checkpoints = ListProperty([])  # path-distance percents (0–100) of stored checkpoints
    _SIM_BAR_COLOR = (0.25, 0.82, 0.35, 0.95)
    _SIM_MARKER_COLOR = (0.3, 0.55, 0.95, 1.0)
    _SIM_BAR_HEIGHT = dp(3)
    _SIM_MARKER_WIDTH = dp(2)
    _SIM_MARKER_HEIGHT = dp(7)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_line_update = None  # Track pending scheduled line update
        with self.canvas.after:
            self._sim_color = Color(*self._SIM_BAR_COLOR)
            self._sim_rect = Rectangle(pos=(0, 0), size=(0, 0))
            self._sim_marker_group = InstructionGroup()
        self.bind(
            pos=self._update_sim_bar,
            size=self._update_sim_bar,
            padding=self._update_sim_bar,
            min=self._update_sim_bar,
            max=self._update_sim_bar,
            sim_progress=self._update_sim_bar,
            sim_checkpoints=self._update_sim_bar,
        )

    def _update_sim_bar(self, *_args):
        if not hasattr(self, "_sim_rect"):
            return
        progress = float(self.sim_progress or 0.0)
        pad = float(self.padding)
        track_w = max(0.0, self.width - 2.0 * pad) if self.width > 0 else 0.0
        bar_h = float(self._SIM_BAR_HEIGHT)
        bar_y = self.y + dp(1)

        if progress <= 0 or track_w <= 0 or self.height <= 0:
            self._sim_rect.size = (0, 0)
        else:
            fill_w = track_w * min(100.0, progress) / 100.0
            self._sim_rect.pos = (self.x + pad, bar_y)
            self._sim_rect.size = (fill_w, bar_h)

        # Checkpoint ticks on the sim strip (full track so future restore points stay visible).
        group = getattr(self, "_sim_marker_group", None)
        if group is None:
            return
        group.clear()
        if track_w <= 0 or self.height <= 0:
            return
        marker_w = float(self._SIM_MARKER_WIDTH)
        marker_h = float(self._SIM_MARKER_HEIGHT)
        marker_y = bar_y + (bar_h - marker_h) / 2.0
        for pct in self.sim_checkpoints or []:
            try:
                p = float(pct)
            except (TypeError, ValueError):
                continue
            if p < 0.0 or p > 100.0:
                continue
            x = self.x + pad + track_w * (p / 100.0) - marker_w / 2.0
            group.add(Color(*self._SIM_MARKER_COLOR))
            group.add(Rectangle(pos=(x, marker_y), size=(marker_w, marker_h)))

    def on_touch_down(self, touch):
        if self.disabled:
            return None
        released = super().on_touch_down(touch)
        if released and self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance / 1000)

            self._update_line_highlighting()  # Add line highlighting when slider is moved
            return True
        return released

    def on_touch_move(self, touch):
        if self.disabled:
            return None
        released = super().on_touch_move(touch)
        if self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance / 1000)

            self._update_line_highlighting()  # Add line highlighting when slider is moved
            return True
        return released

    def _update_line_highlighting(self):
        """Update line highlighting in the file viewer based on current slider position"""
        # Cancel any pending update
        if self._pending_line_update is not None:
            Clock.unschedule(self._pending_line_update)
            self._pending_line_update = None

        # Schedule update for next frame
        self._pending_line_update = Clock.schedule_once(self._do_update_line_highlighting, 0)

    def _do_update_line_highlighting(self, dt):
        """Actually perform the line highlighting update on the next frame"""
        self._pending_line_update = None
        app = App.get_running_app()
        if hasattr(app.root, "gcode_viewer") and app.root.gcode_viewer:
            # Get current position and line number from gcode viewer
            current_pos = app.root.gcode_viewer.get_cur_pos_index()
            if current_pos and len(current_pos) > 1:
                line_number = current_pos[1]
                if line_number > 0 and hasattr(app.root, "gcode_rv"):
                    app.root.gcode_rv.set_selected_line(line_number)

    def on_value(self, instance, value):
        """Called when the slider value changes (both programmatically and manually)"""
        # Disable this callback to prevent conflicts with programmatic updates
        # Line highlighting will only be updated through touch methods
        pass


class FloatBox(FloatLayout):
    touch_interval = 0
    color_scheme_panel = ObjectProperty(None)
    camera_controls = ObjectProperty(None)
    camera_view = ObjectProperty(None)
    tool_bar = ObjectProperty(None)

    def _viewer_chrome_hit(self, touch):
        if self.gcode_ctl_bar.collide_point(*touch.pos):
            return True
        if self.tool_bar is not None and self.tool_bar.collide_point(*touch.pos):
            return True
        if self.camera_view is not None and self.camera_view.collide_point(*touch.pos):
            return True
        return any(
            panel is not None and panel.collide_point(*touch.pos)
            for panel in (self.color_scheme_panel, self.camera_controls)
        )

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True

        if self.collide_point(*touch.pos) and not self._viewer_chrome_hit(touch):
            if ("button" in touch.profile and touch.button == "left") or not "button" in touch.profile:
                self.touch_interval = time.time()

    def on_touch_up(self, touch):
        if super().on_touch_up(touch):
            return True

        app = App.get_running_app()
        if self.collide_point(*touch.pos) and not self._viewer_chrome_hit(touch):
            if ("button" in touch.profile and touch.button == "left") or not "button" in touch.profile:
                if time.time() - self.touch_interval < MAX_TOUCH_INTERVAL:
                    app.show_gcode_ctl_bar = not app.show_gcode_ctl_bar


class BoxStencil(BoxLayout, StencilView):
    pass


class ConfirmPopup(ModalView):
    showing = False
    content_scroll = ObjectProperty(None)
    lb_title = ObjectProperty(None)
    lb_content = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Capture KV (or constructor) defaults so expanded workflows can restore them.
        self._default_size_hint = tuple(self.size_hint)
        self._default_pos_hint = dict(self.pos_hint)
        self._default_title_size_hint_y = self.lb_title.size_hint_y
        self._default_content_halign = self.lb_content.halign

    def dismiss(self, *largs, **kwargs):
        # Instant dismiss so layout defaults restore before the next open.
        kwargs.setdefault("animation", False)
        return super().dismiss(*largs, **kwargs)

    def reset_layout_defaults(self):
        self.size_hint = self._default_size_hint
        self.pos_hint = dict(self._default_pos_hint)
        self.lb_title.size_hint_y = self._default_title_size_hint_y
        self.lb_content.halign = self._default_content_halign
        if self.content_scroll is not None:
            self.content_scroll.scroll_y = 1

    def on_open(self):
        self.showing = True
        if self.content_scroll is not None:
            self.content_scroll.scroll_y = 1

    def on_dismiss(self):
        self.showing = False
        self.reset_layout_defaults()


class UnlockPopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False


class SelectAndCalibrateProbePopup(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class MessagePopup(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ReconnectionPopup(ModalView):
    auto_reconnect_mode = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.countdown = 0
        self.max_attempts = 0
        self.current_attempt = 0
        self.wait_time = 10
        self.cancel_callback = None
        self.reconnect_callback = None

    def start_countdown(self, max_attempts, wait_time, reconnect_callback, cancel_callback):
        """Start auto-reconnect countdown mode"""
        self.auto_reconnect_mode = True
        self.max_attempts = max_attempts
        self.current_attempt = 0
        self.wait_time = wait_time
        self.reconnect_callback = reconnect_callback
        self.cancel_callback = cancel_callback
        self.countdown = wait_time
        self.update_display()

    def show_manual_reconnect(self, reconnect_callback):
        """Show manual reconnect mode (no countdown)"""
        self.auto_reconnect_mode = False
        self.reconnect_callback = reconnect_callback
        self.update_display()

    def update_display(self):
        if hasattr(self, "lb_content"):
            if self.auto_reconnect_mode:
                remaining_attempts = self.max_attempts - self.current_attempt
                self.lb_content.text = tr._(
                    f"Connection lost. Attempting to reconnect...\n\nAttempt {self.current_attempt + 1} of {self.max_attempts}\nReconnecting in {self.countdown} seconds"
                )
            else:
                self.lb_content.text = tr._("Connection to machine lost.")

    def countdown_tick(self, dt=None):
        if not self.auto_reconnect_mode:
            return

        if self.countdown > 0:
            self.countdown -= 1
            self.update_display()
        else:
            self.countdown = self.wait_time
            self.current_attempt += 1
            if self.current_attempt <= self.max_attempts:
                if self.reconnect_callback:
                    self.reconnect_callback()
                # Only call cancel_callback after the last attempt has been made
                if self.current_attempt >= self.max_attempts:
                    self.dismiss()
                    if self.cancel_callback:
                        self.cancel_callback()

    def cancel_reconnect(self):
        self.dismiss()
        if self.cancel_callback:
            self.cancel_callback()

    def reconnect(self):
        """Handle reconnect button press"""
        if self.reconnect_callback:
            self.reconnect_callback()
        self.dismiss()

    def on_dismiss(self):
        """Called when popup is dismissed"""
        super().on_dismiss()
        # Stop the countdown timer
        Clock.unschedule(self.countdown_tick)


class InputPopup(ModalView):
    cache_var1 = StringProperty("")
    cache_var2 = StringProperty("")
    cache_var3 = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ManualWifiPopup(ModalView):
    cache_var1 = StringProperty("")
    cache_var2 = StringProperty("")
    cache_var3 = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ProgressPopup(ModalView):
    progress_text = StringProperty("")
    progress_value = NumericProperty("0")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class GCodeLineContextMenu(FloatLayout):
    """Context menu for GCode file viewer lines"""

    line_number = NumericProperty(0)

    def __init__(self, line_number, **kwargs):
        super().__init__(**kwargs)
        self.line_number = line_number

    def on_touch_down(self, touch):
        """Handle touch events - dismiss menu if touch is outside"""
        if not self.collide_point(*touch.pos):
            # Touch outside the menu - dismiss it
            self.dismiss()
            return False

        # Prevent right-click from opening another context menu
        if hasattr(touch, "button") and touch.button == "right":
            return True

        return super().on_touch_down(touch)

    def resume_at_line(self):
        """Enable resume at line checkbox and set the line number"""
        app = App.get_running_app()

        app.root.coord_popup.cbx_startline.active = True
        app.root.coord_popup.txt_startline.text = str(self.line_number)
        self.parent.remove_widget(self)

    def clear_resume_at_line(self):
        """Clear the resume at line setting"""
        app = App.get_running_app()

        app.root.coord_popup.cbx_startline.active = False
        app.root.coord_popup.txt_startline.text = ""
        self.parent.remove_widget(self)

    def dismiss(self):
        """Close the context menu"""
        if self.parent:
            self.parent.remove_widget(self)


class OriginPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super().__init__(**kwargs)

    def on_open(self):
        super().on_open()
        # Use the same logic as CoordPopup.load_origin_label to set offsets
        app = App.get_running_app()
        if app.has_4axis:
            x = round(CNC.vars["wcox"] - CNC.vars["anchor1_x"] - CNC.vars["rotation_offset_x"], 4)
            y = round(CNC.vars["wcoy"] - CNC.vars["anchor1_y"] - CNC.vars["rotation_offset_y"], 4)
        else:
            laser_x = CNC.vars["laser_module_offset_x"] if CNC.vars["lasermode"] else 0.0
            laser_y = CNC.vars["laser_module_offset_y"] if CNC.vars["lasermode"] else 0.0
            if self.coord_popup.config["origin"]["anchor"] == 2 and app.has_anchor2:
                x = round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"], 4)
                y = round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"], 4)
            elif self.coord_popup.config["origin"]["anchor"] == 1:
                x = round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"], 4)
                y = round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"], 4)
            else:
                x = 0
                y = 0
        self.txt_x_offset.text = str(x)
        widget_helpers.bind_auto_select_to_text_input(self.txt_x_offset)
        self.txt_y_offset.text = str(y)
        widget_helpers.bind_auto_select_to_text_input(self.txt_y_offset)

    def selected_anchor(self):
        app = App.get_running_app()
        if self.cbx_anchor2.active and app.has_anchor2:
            return 2
        if self.cbx_4axis_origin.active:
            return 3
        if self.cbx_current_position.active:
            return 4
        return 1

    def update_offsets(self):
        # Use the same logic as CoordPopup.load_origin_label to set offsets
        app = App.get_running_app()
        x = 0
        y = 0
        if app.has_4axis:
            x = round(CNC.vars["wcox"] - CNC.vars["anchor1_x"] - CNC.vars["rotation_offset_x"], 4)
            y = round(CNC.vars["wcoy"] - CNC.vars["anchor1_y"] - CNC.vars["rotation_offset_y"], 4)
        else:
            laser_x = CNC.vars["laser_module_offset_x"] if CNC.vars["lasermode"] else 0.0
            laser_y = CNC.vars["laser_module_offset_y"] if CNC.vars["lasermode"] else 0.0
            if self.cbx_anchor1.active:
                x = round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"], 4)
                y = round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"], 4)
            elif self.cbx_anchor2.active and app.has_anchor2:
                x = round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"], 4)
                y = round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"], 4)
            elif self.cbx_current_position.active:
                x = 0
                y = 0
        self.txt_x_offset.text = str(x)
        self.txt_y_offset.text = str(y)

    def validate_inputs(self):
        """Validate inputs based on the active tab."""
        # Check which tab is active using the ID
        tabbed_panel = self.ids.tabbed_panel

        if tabbed_panel and tabbed_panel.current_tab:
            current_tab = tabbed_panel.current_tab
            if hasattr(current_tab, "text") and "XYZ Probe" in current_tab.text:
                # Validate XYZ Probe tab inputs
                probe_height_text = self.ids.txt_probe_height.text.strip()
                tool_diameter_text = self.ids.txt_tool_diameter.text.strip()

                if not probe_height_text or not tool_diameter_text:
                    return False, tr._("Please enter values for both block thickness and tool diameter.")

                try:
                    float(probe_height_text)
                    float(tool_diameter_text)
                    return True, ""
                except ValueError:
                    return False, tr._("Please enter valid numbers for block thickness and tool diameter.")

        # Default to validating X/Y offsets (Auto-Set By Offset tab)
        x_offset_text = self.ids.txt_x_offset.text.strip()
        y_offset_text = self.ids.txt_y_offset.text.strip()

        if not x_offset_text or not y_offset_text:
            return False, tr._("Please enter values for both X and Y offsets.")

        try:
            float(x_offset_text)
            float(y_offset_text)
            return True, ""
        except ValueError:
            return False, tr._("Please enter valid numbers for X and Y offsets.")

    def on_ok_pressed(self):
        """Handle OK button press with validation."""
        app = App.get_running_app()
        is_valid, error_message = self.validate_inputs()
        if is_valid:
            # Check which tab is active using the ID
            tabbed_panel = self.ids.tabbed_panel

            if tabbed_panel and tabbed_panel.current_tab:
                current_tab = tabbed_panel.current_tab

                if hasattr(current_tab, "text") and "XYZ Probe" in current_tab.text:
                    # Handle XYZ Probe tab
                    app.root.controller.xyzProbe(
                        float(self.ids.txt_probe_height.text), float(self.ids.txt_tool_diameter.text)
                    )
                    self.dismiss()
                    return

            # Handle Auto-Set By Offset tab (default)
            self.coord_popup.set_config("origin", "anchor", self.selected_anchor())
            self.coord_popup.set_config("origin", "x_offset", float(self.ids.txt_x_offset.text))
            self.coord_popup.set_config("origin", "y_offset", float(self.ids.txt_y_offset.text))
            app.root.set_work_origin()
            self.dismiss()
        else:
            Clock.schedule_once(partial(app.root.show_message_popup, error_message, False), 0)


class ZProbePopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super().__init__(**kwargs)

    def validate_inputs(self):
        """Validate that X and Y offset inputs are not empty and are valid numbers."""
        x_offset_text = self.ids.txt_x_offset.text.strip()
        y_offset_text = self.ids.txt_y_offset.text.strip()

        if not x_offset_text or not y_offset_text:
            return False, tr._("Please enter values for both X and Y offsets.")

        try:
            float(x_offset_text)
            float(y_offset_text)
            return True, ""
        except ValueError:
            return False, tr._("Please enter valid numbers for X and Y offsets.")

    def on_ok_pressed(self):
        """Handle OK button press with validation."""
        is_valid, error_message = self.validate_inputs()
        if is_valid:
            self.coord_popup.set_config("zprobe", "origin", 1 if self.ids.cbx_origin1.active else 2)
            self.coord_popup.set_config("zprobe", "x_offset", float(self.ids.txt_x_offset.text))
            self.coord_popup.set_config("zprobe", "y_offset", float(self.ids.txt_y_offset.text))
            self.coord_popup.load_zprobe_label()
            self.dismiss()
        else:
            app = App.get_running_app()
            Clock.schedule_once(partial(app.root.show_message_popup, error_message, False), 0)


class XYZProbePopup(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def validate_inputs(self):
        """Validate that probe height and tool diameter inputs are not empty and are valid numbers."""
        probe_height_text = self.ids.txt_probe_height.text.strip()
        tool_diameter_text = self.ids.txt_tool_diameter.text.strip()

        if not probe_height_text or not tool_diameter_text:
            return False, tr._("Please enter values for both probe height and tool diameter.")

        try:
            float(probe_height_text)
            float(tool_diameter_text)
            return True, ""
        except ValueError:
            return False, tr._("Please enter valid numbers for probe height and tool diameter.")

    def on_ok_pressed(self):
        """Handle OK button press with validation."""
        is_valid, error_message = self.validate_inputs()
        if is_valid:
            app = App.get_running_app()
            logger.debug(
                f"XYZProbePopup.on_ok_pressed: probe height={self.ids.txt_probe_height.text}, tool diameter={self.ids.txt_tool_diameter.text}"
            )
            app.root.controller.xyzProbe(float(self.ids.txt_probe_height.text), float(self.ids.txt_tool_diameter.text))
            self.dismiss()
        else:
            app = App.get_running_app()
            Clock.schedule_once(partial(app.root.show_message_popup, error_message, False), 0)


class LanguagePopup(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class PairingPopup(ModalView):
    pairing = BooleanProperty(0)
    countdown = NumericProperty(0)
    pairing_note = StringProperty("")
    pairing_success = False

    def __init__(self, **kwargs):
        self.pairing_string = {
            "start": tr._("Press the Wireless Probe until the green LED blinks quickly."),
            "success": tr._("Pairing Success!"),
            "timeout": tr._("Pairing Timeout!"),
        }
        super().__init__(**kwargs)

    def start_pairing(self):
        self.pairing = True
        self.pairing_success = False
        self.countdown = 30
        self.pairing_note = self.pairing_string["start"]
        self.countdown_event = Clock.schedule_interval(self.pairing_countdown, 1)

    def pairing_countdown(self, *args):
        self.countdown = self.countdown - 1
        if self.pairing_success:
            self.pairing = False
            self.pairing_note = self.pairing_string["success"]
            self.countdown_event.cancel()
        elif self.countdown < 1:
            self.pairing = False
            self.pairing_note = self.pairing_string["timeout"]
            self.countdown_event.cancel()


class PickFilePopup(FloatLayout):
    on_select = ObjectProperty(None)
    on_cancel = ObjectProperty(None)

    def __init__(self, on_select, on_cancel=None, **kwargs):
        super().__init__(**kwargs)
        self.on_select = on_select
        self.on_cancel = on_cancel

    def on_select_pressed(self, directory, filename):
        if self.on_select:
            self.on_select(directory, filename)

    def on_cancel_pressed(self):
        if self.on_cancel:
            self.on_cancel()


class UpgradePopup(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class AutoLevelPopup(ModalView):
    execute = False

    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super().__init__(**kwargs)

    def init(self):
        x_steps = int(self.sp_x_points.text)
        y_steps = int(self.sp_y_points.text)
        self.lb_min_x.text = "{:.2f}".format(CNC.vars["xmin"])
        self.lb_max_x.text = "{:.2f}".format(CNC.vars["xmax"])
        self.lb_step_x.text = "{:.2f}".format((CNC.vars["xmax"] - CNC.vars["xmin"]) * 1.0 / x_steps)
        self.lb_min_y.text = "{:.2f}".format(CNC.vars["ymin"])
        self.lb_max_y.text = "{:.2f}".format(CNC.vars["ymax"])
        self.lb_step_y.text = "{:.2f}".format((CNC.vars["ymax"] - CNC.vars["ymin"]) * 1.0 / y_steps)

    def init_and_open(self, execute=False):
        self.execute = execute
        self.init()
        self.open()

    def validate_inputs(self):
        """Validate that height, x_points, and y_points inputs are not empty and are valid numbers."""
        height_text = self.ids.sp_height.text.strip()
        x_points_text = self.ids.sp_x_points.text.strip()
        y_points_text = self.ids.sp_y_points.text.strip()

        if not height_text or not x_points_text or not y_points_text:
            return False, tr._("Please enter values for height, X points, and Y points.")

        try:
            int(height_text)
            int(x_points_text)
            int(y_points_text)
            return True, ""
        except ValueError:
            return False, tr._("Please enter valid numbers for height, X points, and Y points.")

    def on_ok_pressed(self):
        """Handle OK button press with validation."""
        is_valid, error_message = self.validate_inputs()
        if is_valid:
            self.coord_popup.set_config("leveling", "height", int(self.ids.sp_height.text))
            self.coord_popup.set_config("leveling", "x_points", int(self.ids.sp_x_points.text))
            self.coord_popup.set_config("leveling", "y_points", int(self.ids.sp_y_points.text))
            self.coord_popup.set_config(
                "leveling",
                "xn_offset",
                float(self.ids.txt_auto_xn_offset.text)
                if self.ids.cbx_autolevelOffsets.active
                and self.ids.txt_auto_xn_offset.text.strip()
                and self.ids.txt_auto_xn_offset.text != "."
                else 0.0,
            )
            self.coord_popup.set_config(
                "leveling",
                "xp_offset",
                float(self.ids.txt_auto_xp_offset.text)
                if self.ids.cbx_autolevelOffsets.active
                and self.ids.txt_auto_xp_offset.text.strip()
                and self.ids.txt_auto_xp_offset.text != "."
                else 0.0,
            )
            self.coord_popup.set_config(
                "leveling",
                "yn_offset",
                float(self.ids.txt_auto_yn_offset.text)
                if self.ids.cbx_autolevelOffsets.active
                and self.ids.txt_auto_yn_offset.text.strip()
                and self.ids.txt_auto_yn_offset.text != "."
                else 0.0,
            )
            self.coord_popup.set_config(
                "leveling",
                "yp_offset",
                float(self.ids.txt_auto_yp_offset.text)
                if self.ids.cbx_autolevelOffsets.active
                and self.ids.txt_auto_yp_offset.text.strip()
                and self.ids.txt_auto_yp_offset.text != "."
                else 0.0,
            )
            if self.ids.cbx_autolevelOffsets.active:
                self.coord_popup.set_config(
                    "zprobe",
                    "x_offset",
                    float(self.ids.txt_auto_xn_offset.text)
                    if self.ids.txt_auto_xn_offset.text.strip() and self.ids.txt_auto_xn_offset.text != "."
                    else 0.0,
                )
            if self.ids.cbx_autolevelOffsets.active:
                self.coord_popup.set_config(
                    "zprobe",
                    "y_offset",
                    float(self.ids.txt_auto_yn_offset.text)
                    if self.ids.txt_auto_yn_offset.text.strip() and self.ids.txt_auto_yn_offset.text != "."
                    else 0.0,
                )

            self.coord_popup.load_leveling_label()
            if self.execute:
                app = App.get_running_app()
                app.root.execute_autolevel(int(self.ids.sp_x_points.text), int(self.ids.sp_y_points.text), False)
            self.dismiss()
        else:
            app = App.get_running_app()
            Clock.schedule_once(partial(app.root.show_message_popup, error_message, False), 0)


class FilePopup(ModalView):
    firmware_mode = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def load_remote_page(self):
        self.popup_manager.transition.direction = "right"
        self.popup_manager.transition.duration = 0.3
        self.popup_manager.current = "remote_page"
        app = App.get_running_app()
        if app.state == "Idle":
            self.remote_rv.current_dir()

    # -----------------------------------------------------------------------
    def load_remote_root(self):
        self.remote_rv.child_dir("")

    # -----------------------------------------------------------------------
    def update_local_buttons(self):
        has_select = False
        app = App.get_running_app()
        for key in self.local_rv.view_adapter.views:
            if (
                self.local_rv.view_adapter.views[key].selected
                and not self.local_rv.view_adapter.views[key].selected_dir
            ):
                has_select = True
                break
        self.btn_view.disabled = not has_select or self.firmware_mode
        self.btn_upload.disabled = not has_select or app.state != "Idle"

    # -----------------------------------------------------------------------
    def update_remote_buttons(self):
        selected_files = self.remote_rv.get_selected_files()
        selected_infos = self.remote_rv.get_selected_file_infos()
        has_select = len(selected_files) > 0
        single_select = len(selected_files) == 1
        select_dir = single_select and selected_infos[0].get("is_dir", False)
        self.btn_delete.disabled = not has_select
        self.btn_rename.disabled = not single_select
        self.btn_select.disabled = (not single_select) or select_dir


def background_image_model(name):
    """Return the machine model a built-in background belongs to, or None if unknown."""
    if name.startswith("CA1") or name.startswith("Air "):
        return "CA1"
    if name.startswith("C1"):
        return "C1"
    if name.startswith("Z1"):
        return "Z1"
    return None


def filter_background_images(builtin_names, custom_names, model):
    """Built-ins matching `model`, then unprefixed custom images (always shown)."""
    matching = [name for name in builtin_names if background_image_model(name) == model]
    matching.sort(key=str.casefold)
    custom = sorted(custom_names, key=str.casefold)
    return matching + custom


def select_background_image(saved, matching):
    """Pick a spinner value. persist is False when falling back so a mismatched saved setting is kept."""
    values = ["None"] + list(matching)
    if saved in values:
        return saved, True
    if matching:
        return matching[0], False
    return "None", False


class CoordPopup(ModalView):
    config = {}
    mode = StringProperty()
    vacuummode = ObjectProperty()
    extoutmode = ObjectProperty()
    autoblowmode = ObjectProperty()
    autobedcleanmode = ObjectProperty()
    ionizermode = ObjectProperty()
    origin_popup = ObjectProperty()
    zprobe_popup = ObjectProperty()
    auto_level_popup = ObjectProperty()
    setx_popup = ObjectProperty()
    sety_popup = ObjectProperty()
    setz_popup = ObjectProperty()
    seta_popup = ObjectProperty()
    settool_popup = ObjectProperty()
    change_tool_popup = ObjectProperty()
    MoveA_popup = ObjectProperty()

    def __init__(self, config, **kwargs):
        self.config = config
        self.origin_popup = OriginPopup(self)
        self.zprobe_popup = ZProbePopup(self)
        self.auto_level_popup = AutoLevelPopup(self)
        self.setx_popup = SetXPopup(self)
        self.sety_popup = SetYPopup(self)
        self.setz_popup = SetZPopup(self)
        self.seta_popup = SetAPopup(self)
        self.settool_popup = SetToolPopup(self)
        self.change_tool_popup = ChangeToolPopup(self)
        self.MoveA_popup = MoveAPopup(self)
        self.mode = "Run"  # 'Margin' / 'ZProbe' / 'Leveling'
        super().__init__(**kwargs)
        self.user_play_file_image_dir = Config.get("carvera", "custom_bkg_img_dir")
        self.custom_background_image_files = []
        self.builtin_background_image_files = []
        self._suppress_background_image_config_write = False

        default_bkg_images = os.path.join(os.path.dirname(__file__), "data/play_file_image_backgrounds")

        if os.path.exists(self.user_play_file_image_dir):
            self.custom_background_image_files = [
                f.replace(".png", "") for f in os.listdir(self.user_play_file_image_dir) if f.endswith(".png")
            ]

        for f in os.listdir(default_bkg_images):
            if f.endswith(".png"):
                self.builtin_background_image_files.append(f.replace(".png", ""))

        Clock.schedule_once(self.populate_spinner, 0)
        app = App.get_running_app()
        if app is not None:
            app.bind(model=self._on_machine_model_changed)

    def _on_machine_model_changed(self, _instance, _value):
        self.populate_spinner()

    def populate_spinner(self, dt=None):
        if "background_image_spinner" not in self.ids:
            return
        app = App.get_running_app()
        model = app.model if app is not None else ""
        matching = filter_background_images(
            self.builtin_background_image_files, self.custom_background_image_files, model
        )
        saved_image = Config.get("carvera", "background_image")
        selected, persist = select_background_image(saved_image, matching)
        spinner = self.ids.background_image_spinner
        self._suppress_background_image_config_write = not persist
        try:
            spinner.values = ["None"] + matching
            if spinner.text != selected:
                spinner.text = selected
            else:
                self.update_background_image(selected)
        finally:
            self._suppress_background_image_config_write = False

    def update_background_image(self, filename):
        if not self._suppress_background_image_config_write:
            Config.set("carvera", "background_image", filename)
            Config.write()

        if filename != "None":
            old_source = os.path.join(os.path.dirname(__file__), "data/play_file_image_backgrounds", filename)
            new_source = os.path.join(self.user_play_file_image_dir, filename)
            cnc_workspace = self.ids.cnc_workspace
            if os.path.isfile(new_source + ".png"):
                cnc_workspace.update_background_image(new_source + ".png")
            elif os.path.isfile(old_source + ".png"):
                cnc_workspace.update_background_image(old_source + ".png")
            else:
                cnc_workspace.update_background_image("None")
        else:
            cnc_workspace = self.ids.cnc_workspace
            cnc_workspace.update_background_image("None")

    def open_bkg_img_dir(self):
        app = App.get_running_app()
        folder_path = app.ids.coord_popup.user_play_file_image_dir

        # Ensure the folder exists
        if not os.path.exists(folder_path):
            logger.warning(f"Folder '{folder_path}' does not exist!")
            return

        # Open based on OS
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", folder_path])
        else:  # Linux
            subprocess.Popen(["xdg-open", folder_path])

        folder_path = os.path.join(os.path.dirname(__file__), "data/play_file_image_backgrounds")

        # Ensure the folder exists
        if not os.path.exists(folder_path):
            logger.warning(f"Folder '{folder_path}' does not exist!")
            return

        # Open based on OS
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", folder_path])
        else:  # Linux
            subprocess.Popen(["xdg-open", folder_path])

    def set_config(self, key1, key2, value):
        self.config[key1][key2] = value
        self.cnc_workspace.draw()

    def load_config(self):
        self.cnc_workspace.load_config(self.config)
        Clock.schedule_once(self.cnc_workspace.draw, 0)

        # init origin popup
        origin_anchor = self.config["origin"]["anchor"]
        if origin_anchor == 2 and not App.get_running_app().has_anchor2:
            origin_anchor = 1
            self.config["origin"]["anchor"] = 1
        self.origin_popup.cbx_anchor1.active = origin_anchor == 1
        self.origin_popup.cbx_anchor2.active = origin_anchor == 2
        self.origin_popup.cbx_4axis_origin.active = origin_anchor == 3
        self.origin_popup.cbx_current_position.active = origin_anchor == 4
        self.origin_popup.txt_x_offset.text = str(self.config["origin"]["x_offset"])
        self.origin_popup.txt_y_offset.text = str(self.config["origin"]["y_offset"])

        self.load_origin_label()

        if CNC.vars["vacuummode"] == 1:
            self.vacuummode = True
        else:
            self.vacuummode = False

        if CNC.vars["extoutmode"] == 1:
            self.extoutmode = True
        else:
            self.extoutmode = False

        if CNC.vars["autoblowmode"] == 1:
            self.autoblowmode = True
        else:
            self.autoblowmode = False

        if CNC.vars["autobedcleanmode"] == 1:
            self.autobedcleanmode = True
        else:
            self.autobedcleanmode = False

        if CNC.vars["ionizermode"] == 1:
            self.ionizermode = True
        else:
            self.ionizermode = False

        # init margin widgets
        self.cbx_margin.active = self.config["margin"]["active"]

        # init zprobe widgets
        self.cbx_zprobe.active = self.config["zprobe"]["active"]
        # init zprobe popup
        self.zprobe_popup.cbx_origin1.active = self.config["zprobe"]["origin"] == 1
        self.zprobe_popup.cbx_origin2.active = self.config["zprobe"]["origin"] == 2
        self.zprobe_popup.txt_x_offset.text = str(self.config["zprobe"]["x_offset"])
        self.zprobe_popup.txt_y_offset.text = str(self.config["zprobe"]["y_offset"])

        self.load_zprobe_label()

        # init leveling widgets
        self.cbx_leveling.active = self.config["leveling"]["active"]
        self.auto_level_popup.sp_x_points.text = str(self.config["leveling"]["x_points"])
        self.auto_level_popup.sp_y_points.text = str(self.config["leveling"]["y_points"])
        self.auto_level_popup.sp_height.text = str(self.config["leveling"]["height"])

        self.load_leveling_label()

    def load_origin_label(self):
        app = App.get_running_app()
        if app.has_4axis:
            self.lb_origin.text = "(%g, %g) " % (
                round(CNC.vars["wcox"] - CNC.vars["anchor1_x"] - CNC.vars["rotation_offset_x"], 4),
                round(CNC.vars["wcoy"] - CNC.vars["anchor1_y"] - CNC.vars["rotation_offset_y"], 4),
            ) + tr._("from Headstock")
        else:
            laser_x = CNC.vars["laser_module_offset_x"] if CNC.vars["lasermode"] else 0.0
            laser_y = CNC.vars["laser_module_offset_y"] if CNC.vars["lasermode"] else 0.0
            if self.config["origin"]["anchor"] == 2 and app.has_anchor2:
                self.lb_origin.text = "(%g, %g) " % (
                    round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"], 4),
                    round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"], 4),
                ) + tr._("from Anchor2")
            else:
                self.lb_origin.text = "(%g, %g) " % (
                    round(CNC.vars["wcox"] + laser_x - CNC.vars["anchor1_x"], 4),
                    round(CNC.vars["wcoy"] + laser_y - CNC.vars["anchor1_y"], 4),
                ) + tr._("from Anchor1")
        self.lb_origin.text = CNC.wcs_names[CNC.vars["active_coord_system"]] + ": " + self.lb_origin.text

    def load_zprobe_label(self):
        app = App.get_running_app()
        if app.has_4axis:
            self.lb_zprobe.text = "(%g, %g) " % (
                round(CNC.vars["anchor1_x"] + CNC.vars["rotation_offset_x"] - 3, 4),
                round(CNC.vars["anchor1_y"] + CNC.vars["rotation_offset_y"], 4),
            ) + tr._("Fixed Pos")
        else:
            self.lb_zprobe.text = (
                "(%g, %g) " % (round(self.config["zprobe"]["x_offset"], 4), round(self.config["zprobe"]["y_offset"], 4))
                + tr._("from")
                + " %s" % (tr._("Work Origin") if self.config["zprobe"]["origin"] == 1 else tr._("Path Origin"))
            )

    def load_leveling_label(self):
        self.lb_leveling.text = (
            tr._("X Points: ")
            + "%d " % (self.config["leveling"]["x_points"])
            + tr._("Y Points: ")
            + "%d " % (self.config["leveling"]["y_points"])
            + tr._("Height: ")
            + "%d" % (self.config["leveling"]["height"])
        )

        any_offsets_set = False
        for offset_type in ["xn_offset", "xp_offset", "yn_offset", "yp_offset"]:
            if self.config["leveling"][offset_type] != 0:
                any_offsets_set = True

        if any_offsets_set:
            self.lb_leveling.text += (
                tr._(" Offsets: ")
                + tr._(" -X: ")
                + "%g " % (round(self.config["leveling"]["xn_offset"], 4))
                + tr._(" +X: ")
                + "%g " % (round(self.config["leveling"]["xp_offset"], 4))
                + tr._(" -Y: ")
                + "%g " % (round(self.config["leveling"]["yn_offset"], 4))
                + tr._(" +Y: ")
                + "%g " % (round(self.config["leveling"]["yp_offset"], 4))
            )

    def toggle_config(self):
        # upldate main status
        app = App.get_running_app()
        app.root.update_coord_config()


class DiagnosePopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False


# Kivy's SettingsPanel writes every change to Config and disk immediately
# with no undo. This subclass overrides set_value to skip the Config write
# while still notifying on_config_change, so changes only persist when the
# user clicks Apply.
#
# ConfigPopup._apply_changes detects pending changes by comparing each
# SettingItem's `value` ObjectProperty against a snapshot taken on open. That
# only works if `widget.value` reflects user input. Standard Kivy widgets
# assign `self.value` directly on input, but custom widgets that call
# `panel.set_value(...)` without first updating `self.value` (e.g.
# SettingPendantSelector) would otherwise be invisible to the Apply loop and
# silently lose data. We sync `widget.value` here so the contract holds for
# any caller of set_value.
class DeferredSettingsPanel(SettingsPanel):
    _skip_sections = ("Backup", "Restore")
    _setting_widget_value = False

    def set_value(self, section, key, value):
        if section in self._skip_sections:
            # Action triggers — write through immediately
            current = self.get_value(section, key)
            if current == value:
                return
            config = self.config
            if config:
                config.set(section, key, value)
                config.write()
            if self.settings:
                self.settings.dispatch("on_config_change", config, section, key, value)
            return
        # Re-entry guard: assigning child.value below fires SettingItem.on_value,
        # which calls back into panel.set_value. Skip the inner call.
        if self._setting_widget_value:
            return
        current = self.get_value(section, key)
        if str(current) == str(value):
            return
        for child in self.walk():
            if isinstance(child, SettingItem) and child.section == section and child.key == key:
                if str(child.value) != str(value):
                    self._setting_widget_value = True
                    try:
                        child.value = value
                    finally:
                        self._setting_widget_value = False
                break
        if self.settings:
            self.settings.dispatch("on_config_change", self.config, section, key, value)


class ConfigPopup(ModalView):
    def __init__(self, **kwargs):
        self._widget_snapshot = {}
        super().__init__(**kwargs)

    def _all_setting_items(self):
        panels = self.settings_panel.interface.content.panels
        for panel in panels.values():
            for widget in panel.walk():
                if isinstance(widget, SettingItem):
                    yield widget

    def on_open(self):
        self._widget_snapshot = {}
        for widget in self._all_setting_items():
            self._widget_snapshot[(widget.section, widget.key)] = widget.value

    def get_original(self, section, key):
        return self._widget_snapshot.get((section, key))

    def on_dismiss(self):
        app = App.get_running_app()
        makera = app.root
        has_pending = bool(makera.controller_setting_change_list or makera.setting_change_list)
        if has_pending:
            makera.confirm_popup.lb_title.text = tr._("Unapplied Changes")
            makera.confirm_popup.lb_content.text = tr._("You have unapplied changes. Do you wish to apply them?")
            makera.confirm_popup.confirm = self._apply_and_close
            makera.confirm_popup.cancel = self._discard_and_close
            makera.confirm_popup.open()
            return True  # cancel the dismiss

    def _apply_changes(self):
        app = App.get_running_app()
        # Write pending widget values to their Config instances
        for widget in self._all_setting_items():
            original = self._widget_snapshot.get((widget.section, widget.key))
            if original is not None and str(widget.value) != str(original):
                config = widget.panel.config
                config.set(widget.section, widget.key, widget.value)
        Config.write()
        app.root.apply_setting_changes()
        self._widget_snapshot = {}
        for widget in self._all_setting_items():
            self._widget_snapshot[(widget.section, widget.key)] = widget.value

    def _apply_and_close(self):
        self._apply_changes()
        self.dismiss(force=True)

    def _discard_and_close(self):
        app = App.get_running_app()
        makera = app.root
        makera.config_loading = True
        for widget in self._all_setting_items():
            original = self._widget_snapshot.get((widget.section, widget.key))
            if original is not None and str(widget.value) != str(original):
                widget.value = original
        makera.config_loading = False
        makera.controller_setting_change_list.clear()
        makera.setting_change_list.clear()
        self.btn_apply.disabled = True
        self.dismiss(force=True)


class WCSSettingsPopup(ModalView):
    def __init__(self, controller, wcs_names, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller
        self.original_values = {}  # Store original values for comparison
        self.wcs_names = wcs_names
        self.current_active_wcs = None  # Track current active WCS
        self.has_changes = False  # Track if any values have changed

    def load_wcs_descriptions(self):
        """Update the WCS descriptions when popup opens"""
        self.ids.g54_description.text = Config.get("carvera", "g54_description")
        self.ids.g55_description.text = Config.get("carvera", "g55_description")
        self.ids.g56_description.text = Config.get("carvera", "g56_description")
        self.ids.g57_description.text = Config.get("carvera", "g57_description")
        self.ids.g58_description.text = Config.get("carvera", "g58_description")
        self.ids.g59_description.text = Config.get("carvera", "g59_description")

    def change_wcs_description(self, wcs):
        """Change the WCS description when the WCS is changed"""
        if wcs == "G54":
            Config.set("carvera", "g54_description", self.ids.g54_description.text)
        elif wcs == "G55":
            Config.set("carvera", "g55_description", self.ids.g55_description.text)
        elif wcs == "G56":
            Config.set("carvera", "g56_description", self.ids.g56_description.text)
        elif wcs == "G57":
            Config.set("carvera", "g57_description", self.ids.g57_description.text)
        elif wcs == "G58":
            Config.set("carvera", "g58_description", self.ids.g58_description.text)
        elif wcs == "G59":
            Config.set("carvera", "g59_description", self.ids.g59_description.text)
        Config.write()

    def on_open(self):
        """Parse WCS values from machine and populate fields when popup opens"""
        if self.controller:
            # Register callback for WCS data
            self.controller.wcs_popup_callback = self.populate_wcs_values
            # Request parameters from machine
            self.controller.viewWCS()
            # Update WCS descriptions
            self.load_wcs_descriptions()
            # Update UI based on firmware type
            Clock.schedule_once(lambda dt: self.update_ui_for_firmware_type(), 0.2)

    def on_dismiss(self):
        """Clean up callback when popup is dismissed"""
        if self.controller and hasattr(self.controller, "wcs_popup_callback"):
            self.controller.wcs_popup_callback = None

    def populate_wcs_values(self, wcs_data):
        """Populate the WCS fields with parsed data from machine"""

        def update_ui(dt):
            # wcs_data format: {'G54': [x, y, z, a, rotation], 'G55': [...], ...}

            for wcs, values in wcs_data.items():
                if len(values) >= 5:  # Ensure we have X, Y, Z, A, rotation
                    x, y, z, a, b, rotation = values

                    # Store original values for comparison
                    self.original_values[wcs] = {"X": x, "Y": y, "Z": z, "A": a, "B": b, "R": rotation}
                    wcs = wcs.replace(".", "_")
                    # Update the corresponding text input fields
                    if hasattr(self.ids, f"{wcs.lower()}_x"):
                        self.ids[f"{wcs.lower()}_x"].text = f"{x:.3f}"
                    if hasattr(self.ids, f"{wcs.lower()}_y"):
                        self.ids[f"{wcs.lower()}_y"].text = f"{y:.3f}"
                    if hasattr(self.ids, f"{wcs.lower()}_z"):
                        self.ids[f"{wcs.lower()}_z"].text = f"{z:.3f}"
                    if hasattr(self.ids, f"{wcs.lower()}_a"):
                        self.ids[f"{wcs.lower()}_a"].text = f"{a:.3f}"
                    if hasattr(self.ids, f"{wcs.lower()}_r"):
                        self.ids[f"{wcs.lower()}_r"].text = f"{rotation:.3f}"

        Clock.schedule_once(update_ui, 0)

        # Update active WCS button after populating values
        active_coord_system = self.controller.cnc.vars.get("active_coord_system", 0)
        if active_coord_system < len(self.wcs_names):
            active_wcs = self.wcs_names[active_coord_system]
            self.update_active_wcs_button(active_wcs)

    def apply_changes(self):
        """Apply all changed values when OK is pressed"""
        if not self.controller:
            return

        # Get coordinate system index mapping
        for wcs in self.wcs_names:
            if wcs not in self.original_values:
                continue

            original = self.original_values[wcs]
            changed_values = {}

            wcs_txt = wcs.replace(".", "_")
            # Check each axis for changes
            for axis in ["X", "Y", "Z", "A"]:
                try:
                    current_value = float(getattr(self.ids, f"{wcs_txt.lower()}_{axis.lower()}").text)
                    if abs(current_value - original[axis]) > 0.001:  # Allow small floating point differences
                        changed_values[axis] = current_value
                except (ValueError, AttributeError):
                    continue

            # Check rotation for changes
            try:
                current_rotation = float(getattr(self.ids, f"{wcs_txt.lower()}_r").text)
                if abs(current_rotation - original["R"]) > 0.001:
                    changed_values["R"] = current_rotation
            except (ValueError, AttributeError):
                pass

            # Send commands for changed values
            if changed_values:
                coord_index = self.wcs_names.index(wcs) + 1  # G54=1, G55=2, etc.
                cmd = f"G10L2P{coord_index}"
                # Build offset command if any offsets changed
                offset_changes = {k: v for k, v in changed_values.items() if k in ["X", "Y", "Z", "A"]}
                if offset_changes:
                    for axis, value in offset_changes.items():
                        cmd += f"{axis}{value:.3f}"
                # Send rotation command if rotation changed
                if "R" in changed_values:
                    cmd += f"R{changed_values['R']:.3f}"
                self.controller.executeCommand(cmd)

    def clear_wcs_offsets(self, wcs):
        """Clear all offsets (X, Y, Z, A) for the specified WCS"""
        # Set all offset fields to 0.000
        wcs = wcs.replace(".", "_")
        if hasattr(self.ids, f"{wcs.lower()}_x"):
            self.ids[f"{wcs.lower()}_x"].text = "0.000"
        if hasattr(self.ids, f"{wcs.lower()}_y"):
            self.ids[f"{wcs.lower()}_y"].text = "0.000"
        if hasattr(self.ids, f"{wcs.lower()}_z"):
            self.ids[f"{wcs.lower()}_z"].text = "0.000"
        if hasattr(self.ids, f"{wcs.lower()}_a"):
            self.ids[f"{wcs.lower()}_a"].text = "0.000"
        self.clear_wcs_rotation(wcs)
        self.check_for_changes()

    def clear_wcs_rotation(self, wcs):
        """Clear rotation for the specified WCS"""
        # Set rotation field to 0.000
        wcs = wcs.replace(".", "_")
        if hasattr(self.ids, f"{wcs.lower()}_r"):
            self.ids[f"{wcs.lower()}_r"].text = "0.000"
        self.check_for_changes()

    def clear_all_wcs(self):
        """Clear all offsets and rotations for all WCS systems"""
        for wcs in self.wcs_names:
            self.clear_wcs_offsets(wcs)
            self.clear_wcs_rotation(wcs)
        self.check_for_changes()

    def update_active_wcs_button(self, active_wcs):
        """Update the active WCS button to show 'ACTIVE' and blue color"""
        self.current_active_wcs = active_wcs

        # Update all activate buttons
        for wcs in self.wcs_names:
            wcs_txt = wcs.replace(".", "_")
            button_id = wcs_txt
            if hasattr(self.ids, button_id):
                button = getattr(self.ids, button_id)
                if wcs == active_wcs:
                    button.color = (0 / 255, 255 / 255, 255 / 255, 1)  # Blue color
                else:
                    button.color = (1, 1, 1, 1)  # Default color

    def activate_wcs(self, wcs):
        """Activate the specified WCS and update the active coordinate system index"""
        try:
            if not self.controller:
                return

            # Execute the G-code command to activate the WCS
            self.controller.executeCommand(wcs)

            # done if community firmware
            if self.controller.is_community_firmware and CNC.can_rotate_wcs:
                return

            # Update the active coordinate system index
            if wcs in self.wcs_names:
                coord_index = self.wcs_names.index(wcs)
                self.controller.cnc.vars["active_coord_system"] = coord_index

            # Update the button display
            self.update_active_wcs_button(wcs)
        except Exception as e:
            logger.error(f"Error activating WCS {wcs}: {e}")

    def update_ui_for_firmware_type(self):
        """Update UI elements based on firmware type"""
        try:
            app = App.get_running_app()
            is_community = app.is_community_firmware

            # Update all text inputs
            for wcs in self.wcs_names:
                wcs_txt = wcs.replace(".", "_")
                for axis in ["x", "y", "z", "a", "r"]:
                    input_id = f"{wcs_txt.lower()}_{axis}"
                    if hasattr(self.ids, input_id):
                        text_input = getattr(self.ids, input_id)
                        if axis == "r":
                            text_input.disabled = not is_community or not CNC.can_rotate_wcs
                        else:
                            text_input.disabled = not is_community

            # Update clear all button
            if hasattr(self.ids, "btn_clear_all"):
                self.ids.btn_clear_all.disabled = not is_community
            self.check_for_changes()
        except Exception as e:
            logger.error(f"Error updating UI for firmware type: {e}")

    def check_for_changes(self):
        """Check if any values have changed and update the OK button text"""
        if not self.original_values:
            return

        has_changes = False
        for wcs in self.wcs_names:
            if wcs not in self.original_values:
                continue

            original = self.original_values[wcs]
            wcs_txt = wcs.replace(".", "_")

            # Check each axis for changes
            for axis in ["X", "Y", "Z", "A"]:
                try:
                    current_value = float(getattr(self.ids, f"{wcs_txt.lower()}_{axis.lower()}").text)
                    if abs(current_value - original[axis]) > 0.001:
                        has_changes = True
                        break
                except (ValueError, AttributeError):
                    continue

            if has_changes:
                break

            # Check rotation for changes
            try:
                current_rotation = float(getattr(self.ids, f"{wcs_txt.lower()}_r").text)
                if abs(current_rotation - original["R"]) > 0.001:
                    has_changes = True
            except (ValueError, AttributeError):
                pass

        self.has_changes = has_changes
        if hasattr(self.ids, "btn_ok"):
            self.ids.btn_ok.text = tr._("Save Changes") if has_changes else tr._("Ok")
        if hasattr(self.ids, "btn_close"):
            self.ids.btn_close.text = tr._("Close without saving") if has_changes else tr._("Close")


class SetRotationPopup(ModalView):
    def __init__(self, controller, cnc, **kwargs):
        self.controller = controller
        self.cnc = cnc
        super().__init__(**kwargs)

    def validate_inputs(self):
        """Validate that rotation input is not empty and is a valid number."""
        rotation_text = self.ids.txt_rotation.text.strip()

        if not rotation_text:
            return False, tr._("Please enter a value for rotation angle.")

        try:
            float(rotation_text)
            return True, ""
        except ValueError:
            return False, tr._("Please enter a valid number for rotation angle.")

    def on_ok_pressed(self):
        """Handle OK button press with validation."""
        is_valid, error_message = self.validate_inputs()
        if is_valid:
            app = App.get_running_app()
            app.root.controller.setRotation(float(self.ids.txt_rotation.text))
            self.dismiss()
        else:
            app = App.get_running_app()
            Clock.schedule_once(partial(app.root.show_message_popup, error_message, False), 0)

    def on_open(self):
        """Set the default rotation value when popup opens"""
        rotation_angle = self.cnc.vars.get("rotation_angle", 0.0)
        self.ids.txt_rotation.text = f"{rotation_angle:.3f}"


class MakeraConfigPanel(SettingsWithSidebar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register_type("pendant", SettingPendantSelector)
        self.register_type("gcodesnippet", custom_widgets.SettingGCodeSnippet)
        self.register_type("colorpicker", custom_widgets.SettingColorPicker)
        self.register_type("gamepad_bindings", SettingGamepadBindings)

    def create_json_panel(self, title, config, filename=None, data=None):
        panel = super().create_json_panel(title, config, filename, data)
        panel.__class__ = DeferredSettingsPanel
        return panel

    def on_config_change(self, config, section, key, value):
        app = App.get_running_app()
        if not app.root.config_loading:
            config_popup = app.root.config_popup
            original = config_popup.get_original(section, key)
            if section in ["carvera", "graphics", "kivy"]:
                if str(value) == str(original):
                    app.root.controller_setting_change_list.pop(key, None)
                else:
                    app.root.controller_setting_change_list[key] = value
                has_changes = bool(app.root.controller_setting_change_list or app.root.setting_change_list)
                config_popup.btn_apply.disabled = not has_changes
            elif section == "Backup":
                app.root.start_back_up_config()
                app.root.config_popup.btn_apply.disabled = True
            elif section != "Restore":
                if str(value) == str(original):
                    app.root.setting_change_list.pop(key, None)
                else:
                    new_value = Utils.to_config(app.root.setting_type_list[key], value).strip()
                    app.root.setting_change_list[key] = new_value
                has_changes = bool(app.root.controller_setting_change_list or app.root.setting_change_list)
                config_popup.btn_apply.disabled = not has_changes
            elif key == "restore" and value == "RESTORE":
                app.root.open_setting_restore_confirm_popup()
            elif key == "default" and value == "DEFAULT":
                app.root.open_setting_default_confirm_popup()


class JogSpeedDropDown(ToolTipDropDown):
    def __init__(self, controller, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller

    pass


class XDropDown(ToolTipDropDown):
    pass


class YDropDown(ToolTipDropDown):
    pass


class ZDropDown(ToolTipDropDown):
    pass


class ADropDown(ToolTipDropDown):
    pass


class FeedDropDown(ToolTipDropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class SpindleDropDown(ToolTipDropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class ToolDropDown(ToolTipDropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class LaserDropDown(ToolTipDropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class CoordinateSystemDropDown(ToolTipDropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False

    def update_ui(self):
        if not CNC.can_rotate_wcs:
            self.ids.set_rotation_popup_button.disabled = True


class FuncDropDown(ToolTipDropDown):
    pass


class StatusDropDown(ToolTipDropDown):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ComPortsDropDown(ToolTipDropDown):
    def __init__(self, **kwargs):
        super(DropDown, self).__init__(**kwargs)


class OperationDropDown(ToolTipDropDown):
    pass


class GcodeViewerDisplayMenuButton(ButtonBehavior, BoxLayout):
    icon = StringProperty("")
    active = BooleanProperty(False)
    text = StringProperty("")


class GcodeViewerDisplayDropDown(ToolTipDropDown):
    show_grid = BooleanProperty(True)
    ortho_projection = BooleanProperty(False)
    show_stock = BooleanProperty(False)
    show_bed = BooleanProperty(False)

    def open(self, widget):
        self._anchor = widget
        if hasattr(widget, "active"):
            widget.active = True
        super().open(widget)

    def on_dismiss(self):
        anchor = getattr(self, "_anchor", None)
        if anchor is not None and hasattr(anchor, "active"):
            anchor.active = False
        self._anchor = None


class MachineButton(ToolTipButton):
    ip = StringProperty("")
    port = NumericProperty(2222)
    busy = BooleanProperty(False)


class IconButton(BoxLayout, ToolTipButton):
    icon = StringProperty("fresk.png")


class TransparentButton(BoxLayout, ToolTipButton):
    icon = StringProperty("fresk.png")
    active = BooleanProperty(False)


class TransparentGrayButton(BoxLayout, ToolTipButton):
    icon = StringProperty("fresk.png")
    active = BooleanProperty(True)


class WiFiButton(BoxLayout, ToolTipButton):
    ssid = StringProperty("")
    encrypted = BooleanProperty(False)
    strength = NumericProperty(1000)
    connected = BooleanProperty(False)


class CNCWorkspace(Widget):
    config = {}
    bg_rect = ObjectProperty(None)
    bg_image = ""
    # Height/width of the preview. C1 is ~0.7 (240/340); Z1 is square (200/200).
    workspace_aspect = NumericProperty(0.7)

    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        self.bind(size=self.on_resize, pos=self.on_resize)
        super().__init__(**kwargs)
        self.bg_rect = None

    def on_resize(self, *args):
        self.draw()

    def _sync_workspace_aspect(self):
        wx = float(CNC.vars.get("worksize_x") or 0)
        wy = float(CNC.vars.get("worksize_y") or 0)
        aspect = (wy / wx) if wx > 0 else 0.7
        if abs(self.workspace_aspect - aspect) > 1e-4:
            self.workspace_aspect = aspect

    def load_config(self, config):
        self.config = config
        self._sync_workspace_aspect()

    def update_background_image(self, new_source):
        if new_source != "None":
            self.bg_image = new_source
            if self.bg_rect:
                self.bg_rect.source = new_source
        else:
            self.bg_image = ""
        self.draw()

    def draw(self, *args):
        old_aspect = self.workspace_aspect
        self._sync_workspace_aspect()
        if abs(old_aspect - self.workspace_aspect) > 1e-4:
            return
        if self.x <= 100:
            return
        self.canvas.clear()
        zoom = self.width / CNC.vars["worksize_x"]
        with self.canvas:
            # background
            Color(50 / 255, 50 / 255, 50 / 255, 1)
            if self.bg_image == "" or self.bg_image == "None":
                Color(50 / 255, 50 / 255, 50 / 255, 1)
            else:
                Color(1, 1, 1, 1)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size, source=self.bg_image)

            app = App.get_running_app()
            if self.bg_image == "" or self.bg_image == "None":
                Color(50 / 255, 50 / 255, 50 / 255, 1)
                if not app.has_4axis:
                    # anchor1
                    if self.config["origin"]["anchor"] == 1:
                        Color(75 / 255, 75 / 255, 75 / 255, 1)
                    else:
                        Color(55 / 255, 55 / 255, 55 / 255, 1)
                    Rectangle(
                        pos=(self.x, self.y), size=(CNC.vars["anchor_length"] * zoom, CNC.vars["anchor_width"] * zoom)
                    )
                    Rectangle(
                        pos=(self.x, self.y), size=(CNC.vars["anchor_width"] * zoom, CNC.vars["anchor_length"] * zoom)
                    )

                    if app.has_anchor2:
                        if self.config["origin"]["anchor"] == 2:
                            Color(75 / 255, 75 / 255, 75 / 255, 1)
                        else:
                            Color(55 / 255, 55 / 255, 55 / 255, 1)
                        Rectangle(
                            pos=(
                                self.x + CNC.vars["anchor2_offset_x"] * zoom,
                                self.y + CNC.vars["anchor2_offset_y"] * zoom,
                            ),
                            size=(CNC.vars["anchor_length"] * zoom, CNC.vars["anchor_width"] * zoom),
                        )
                        Rectangle(
                            pos=(
                                self.x + CNC.vars["anchor2_offset_x"] * zoom,
                                self.y + CNC.vars["anchor2_offset_y"] * zoom,
                            ),
                            size=(CNC.vars["anchor_width"] * zoom, CNC.vars["anchor_length"] * zoom),
                        )

                else:
                    rotation_base_y_center = (CNC.vars["anchor_width"] + CNC.vars["rotation_offset_y"]) * zoom
                    # draw rotation base
                    Color(60 / 255, 60 / 255, 60 / 255, 1)
                    Rectangle(
                        pos=(self.x, self.y + rotation_base_y_center - CNC.vars["rotation_base_height"] * zoom / 2),
                        size=(CNC.vars["rotation_base_width"] * zoom, CNC.vars["rotation_base_height"] * zoom),
                    )
                    # draw rotation head
                    Color(75 / 255, 75 / 255, 75 / 255, 1)
                    Rectangle(
                        pos=(self.x, self.y + rotation_base_y_center - CNC.vars["rotation_head_height"] * zoom / 2),
                        size=(CNC.vars["rotation_head_width"] * zoom, CNC.vars["rotation_head_height"] * zoom),
                    )

                    # draw rotation chuck
                    Color(75 / 255, 75 / 255, 75 / 255, 1)
                    Rectangle(
                        pos=(
                            self.x + (CNC.vars["rotation_head_width"] + CNC.vars["rotation_chuck_interval"]) * zoom,
                            self.y + rotation_base_y_center - CNC.vars["rotation_chuck_dia"] * zoom / 2,
                        ),
                        size=(CNC.vars["rotation_chuck_width"] * zoom, CNC.vars["rotation_chuck_dia"] * zoom),
                    )

                    # draw rotation tail
                    Color(75 / 255, 75 / 255, 75 / 255, 1)
                    Rectangle(
                        pos=(
                            self.x + (CNC.vars["rotation_base_width"] - CNC.vars["rotation_tail_width"]) * zoom,
                            self.y + rotation_base_y_center - CNC.vars["rotation_tail_height"] * zoom / 2,
                        ),
                        size=(CNC.vars["rotation_tail_width"] * zoom, CNC.vars["rotation_tail_height"] * zoom),
                    )

                    # draw rotation probe position
                    # Color(200 / 255, 200 / 255, 200 / 255, 1)
                    # Line(points=[self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width'] - 5) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width']) * zoom,
                    #              self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width'] + 5) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width']) * zoom], width=1)
                    # Line(points=[self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width']) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width'] - 5) * zoom,
                    #              self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width']) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width'] + 5) * zoom], width=1)

            laser_x = CNC.vars["laser_module_offset_x"] if CNC.vars["lasermode"] else 0.0
            laser_y = CNC.vars["laser_module_offset_y"] if CNC.vars["lasermode"] else 0.0

            # origin
            Color(52 / 255, 152 / 255, 219 / 255, 1)
            origin_x = CNC.vars["wcox"] - CNC.vars["anchor1_x"] + CNC.vars["anchor_width"] + laser_x
            origin_y = CNC.vars["wcoy"] - CNC.vars["anchor1_y"] + CNC.vars["anchor_width"] + laser_y
            Ellipse(pos=(self.x + origin_x * zoom - 10, self.y + origin_y * zoom - 10), size=(20, 20))

            # work area
            Color(0, 0.8, 0, 1)
            PushMatrix()
            Translate(self.x + origin_x * zoom, self.y + origin_y * zoom)
            if not app.has_4axis:
                Rotate(angle=CNC.vars["rotation_angle"])  # Use degrees directly
            Line(
                width=(2 if self.config["margin"]["active"] else 1),
                rectangle=(
                    CNC.vars["xmin"] * zoom,
                    CNC.vars["ymin"] * zoom,
                    (CNC.vars["xmax"] - CNC.vars["xmin"]) * zoom,
                    (CNC.vars["ymax"] - CNC.vars["ymin"]) * zoom,
                ),
            )
            PopMatrix()

            # z probe
            if self.config["zprobe"]["active"]:
                Color(231 / 255, 76 / 255, 60 / 255, 1)
                PushMatrix()
                if app.has_4axis:
                    Translate(self.x, self.y)
                    # a axis home enabled
                    if CNC.vars["FuncSetting"] & 1:
                        zprobe_x = CNC.vars["rotation_offset_x"] + CNC.vars["anchor_width"] - 7.0
                        zprobe_y = CNC.vars["rotation_offset_y"] + CNC.vars["anchor_width"]
                    else:
                        zprobe_x = CNC.vars["rotation_offset_x"] + CNC.vars["anchor_width"] - 3.0
                        zprobe_y = CNC.vars["rotation_offset_y"] + CNC.vars["anchor_width"]
                else:
                    Translate(self.x + origin_x * zoom, self.y + origin_y * zoom)
                    Rotate(angle=CNC.vars["rotation_angle"])
                    zprobe_x = self.config["zprobe"]["x_offset"] + (
                        0 if self.config["zprobe"]["origin"] == 1 else CNC.vars["xmin"]
                    )
                    zprobe_y = self.config["zprobe"]["y_offset"] + (
                        0 if self.config["zprobe"]["origin"] == 1 else CNC.vars["ymin"]
                    )
                Ellipse(pos=(zprobe_x * zoom - 7.5, zprobe_y * zoom - 7.5), size=(15, 15))
                PopMatrix()

            # auto leveling
            if self.config["leveling"]["active"]:
                Color(244 / 255, 208 / 255, 63 / 255, 1)
                PushMatrix()
                Translate(self.x + origin_x * zoom, self.y + origin_y * zoom)
                if not app.has_4axis:
                    Rotate(angle=CNC.vars["rotation_angle"])
                for x in Utils.xfrange(
                    self.config["leveling"]["xn_offset"],
                    CNC.vars["xmax"] - CNC.vars["xmin"] - self.config["leveling"]["xp_offset"],
                    self.config["leveling"]["x_points"],
                ):
                    for y in Utils.xfrange(
                        self.config["leveling"]["yn_offset"],
                        CNC.vars["ymax"] - CNC.vars["ymin"] - self.config["leveling"]["yp_offset"],
                        self.config["leveling"]["y_points"],
                    ):
                        Ellipse(
                            pos=((CNC.vars["xmin"] + x) * zoom - 5, (CNC.vars["ymin"] + y) * zoom - 5), size=(10, 10)
                        )
                PopMatrix()

    def on_draw(self, obj, value):
        self.draw()


class SelectableRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior, RecycleBoxLayout):
    """Adds selection and focus behaviour to the view."""


class TopDataView(BoxLayout, ToolTipButton):
    pass


class DropDownHint(Label):
    pass


class SelectableLabel(RecycleDataViewBehavior, Label):
    """Add selection support to the Label"""

    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)
    touch_start_time = 0
    touch_start_pos = None

    def on_keyboard_down(self, instance, keyboard, keycode, text, modifiers):
        mod = "ctrl" if sys.platform == "win32" else "meta"
        if text == "c" and self.selected and mod in modifiers:
            line = getattr(self, "plain_text", None) or getattr(self, "text", "")
            if line:
                Clipboard.copy(line.strip())
            return True
        return False

    def refresh_view_attrs(self, rv, index, data):
        """Catch and handle the view changes"""
        self.index = index
        return super().refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        """Add selection on touch down"""
        if super().on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            # Store touch start time and position for long press detection
            self.touch_start_time = time.time()
            self.touch_start_pos = touch.pos

            # Check for right click (button == 'right') or long press
            if hasattr(touch, "button") and touch.button == "right":
                self._show_context_menu(touch.pos)
                return True
            if touch.is_double_tap:
                app = App.get_running_app()
                line = getattr(self, "plain_text", None) or self.text
                app.root.manual_cmd.text = line.strip()
                Clock.schedule_once(app.root.refocus_cmd)
            return self.parent.select_with_touch(self.index, touch)

    def on_touch_up(self, touch):
        """Handle touch up for long press detection"""
        if self.collide_point(*touch.pos) and self.selectable:
            # Check if this was a long press
            if (
                self.touch_start_pos
                and time.time() - self.touch_start_time >= 0.5  # 0.5 seconds for long press
                and self._is_same_position(touch.pos, self.touch_start_pos)
            ):
                self._show_context_menu(touch.pos)
                return True
        return super().on_touch_up(touch)

    def _is_same_position(self, pos1, pos2, tolerance=10):
        """Check if two positions are within tolerance of each other"""
        return abs(pos1[0] - pos2[0]) <= tolerance and abs(pos1[1] - pos2[1]) <= tolerance

    def _show_context_menu(self, pos):
        """Show the context menu for this line"""
        app = App.get_running_app()

        # Check if a context menu is already open and dismiss it
        for child in app.root.children:
            if isinstance(child, GCodeLineContextMenu):
                child.dismiss()

        current_page = app.curr_page
        actual_line_number = (current_page - 1) * MAX_LOAD_LINES + self.index + 1

        # Create and show the context menu
        context_menu = GCodeLineContextMenu(actual_line_number)

        # Add to the main window first so it gets properly sized
        app.root.add_widget(context_menu)

        self._position_context_menu(context_menu, pos)

    def _position_context_menu(self, context_menu, pos):
        """Position the context menu after layout is complete"""
        app = App.get_running_app()

        window_width = Window.width
        window_height = Window.height

        # Get the actual size of the context menu after layout
        menu_width = context_menu.width
        menu_height = context_menu.height

        # For right-click (desktop): position at mouse pointer
        # Convert touch position to window coordinates
        window_pos = self.to_window(pos[0], pos[1])

        # Position the menu slightly offset from the mouse pointer (typical context menu behavior)
        # Try to position below and to the right of the cursor, but keep it on screen
        x = min(max(window_pos[0] + 5, 10), window_width - menu_width - 10)
        y = min(max(window_pos[1] - menu_height - 5, 10), window_height - menu_height - 10)

        context_menu.pos = (x, y)

    def apply_selection(self, rv, index, is_selected):
        """Respond to the selection of items in the view."""
        self.selected = is_selected
        if not is_selected:
            Window.unbind(on_key_down=self.on_keyboard_down)
        else:
            Window.bind(on_key_down=self.on_keyboard_down)
            # Commit selection immediately so it isn't overwritten by layout/other updates.
            # Use same iteration as GCodeRV.set_selected_line (views is a dict keyed by index).
            for key in rv.view_adapter.views:
                view = rv.view_adapter.views[key]
                if view and hasattr(view, "selected") and view.selected is not None:
                    view.selected = key == index


class Row(IntellisenseExplainRowMixin, SelectableLabel):
    """MDI history row with command-explanation hover and selection popups."""

    highlighted_text = StringProperty("")
    plain_text = StringProperty("")
    highlight = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind_intellisense_hover()

    def refresh_view_attrs(self, rv, index, data):
        self.intellisense_on_recycle()
        result = super().refresh_view_attrs(rv, index, data)
        self.plain_text = data.get("text", "") or ""
        self.highlighted_text = data.get("highlighted_text") or ""
        self.highlight = bool(data.get("highlight", False))
        return result

    def apply_selection(self, rv, index, is_selected):
        super().apply_selection(rv, index, is_selected)
        self.intellisense_on_selection(is_selected)

    def _show_context_menu(self, pos):
        hide_gcode_explain()
        super()._show_context_menu(pos)


Factory.register("Row", cls=Row)


class GCodeRow(IntellisenseExplainRowMixin, RecycleDataViewBehavior, BoxLayout):
    """Single row in GCodeRV: line number, optional resume-flag icon, gcode text."""

    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)
    line_no = NumericProperty(0)
    text = StringProperty("")
    highlighted_text = StringProperty("")
    color = ListProperty([1, 1, 1, 1])
    is_resume_line = BooleanProperty(False)
    touch_start_time = 0
    touch_start_pos = None
    _resume_bind_uids = None  # [txt_uid, cbx_uid] for unbind on recycle

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind_intellisense_hover()

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        self.intellisense_on_recycle()
        # Unbind previous resume-line updates when recycled
        if self._resume_bind_uids:
            app = App.get_running_app()
            if hasattr(app.root, "coord_popup") and app.root.coord_popup:
                cp = app.root.coord_popup
                if hasattr(cp, "txt_startline") and cp.txt_startline and self._resume_bind_uids[0] is not None:
                    cp.txt_startline.funbind("text", self._resume_bind_uids[0])
                if hasattr(cp, "cbx_startline") and cp.cbx_startline and self._resume_bind_uids[1] is not None:
                    cp.cbx_startline.funbind("active", self._resume_bind_uids[1])
            self._resume_bind_uids = None
        super().refresh_view_attrs(rv, index, data)
        self._update_is_resume_line()
        # Bind so flag updates when user changes resume line in popup
        app = App.get_running_app()
        txt_uid = cbx_uid = None
        if hasattr(app.root, "coord_popup") and app.root.coord_popup:
            cp = app.root.coord_popup
            if hasattr(cp, "txt_startline") and cp.txt_startline:
                txt_uid = cp.txt_startline.fbind("text", self._update_is_resume_line)
            if hasattr(cp, "cbx_startline") and cp.cbx_startline:
                cbx_uid = cp.cbx_startline.fbind("active", self._update_is_resume_line)
        self._resume_bind_uids = [txt_uid, cbx_uid]

    def _update_is_resume_line(self, *args):
        app = App.get_running_app()
        if not hasattr(app.root, "coord_popup") or not app.root.coord_popup:
            self.is_resume_line = False
            return
        cp = app.root.coord_popup
        if (
            not hasattr(cp, "cbx_startline")
            or not cp.cbx_startline
            or not hasattr(cp, "txt_startline")
            or not cp.txt_startline
        ):
            self.is_resume_line = False
            return
        try:
            self.is_resume_line = bool(
                cp.cbx_startline.active and str(int(self.line_no)) == cp.txt_startline.text.strip()
            )
        except (ValueError, TypeError):
            self.is_resume_line = False

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            self.touch_start_time = time.time()
            self.touch_start_pos = touch.pos
            if hasattr(touch, "button") and touch.button == "right":
                self._show_context_menu(touch.pos)
                return True
            if touch.is_double_tap:
                app = App.get_running_app()
                app.root.manual_cmd.text = self.text.strip()
                Clock.schedule_once(app.root.refocus_cmd)
            return self.parent.select_with_touch(self.index, touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and self.selectable:
            if (
                self.touch_start_pos
                and time.time() - self.touch_start_time >= 0.5
                and abs(touch.pos[0] - self.touch_start_pos[0]) <= 10
                and abs(touch.pos[1] - self.touch_start_pos[1]) <= 10
            ):
                self._show_context_menu(touch.pos)
                return True
        return super().on_touch_up(touch)

    def _show_context_menu(self, pos):
        hide_gcode_explain()
        app = App.get_running_app()
        for child in app.root.children:
            if isinstance(child, GCodeLineContextMenu):
                child.dismiss()
        current_page = app.curr_page
        actual_line_number = (current_page - 1) * MAX_LOAD_LINES + self.index + 1
        context_menu = GCodeLineContextMenu(actual_line_number)
        app.root.add_widget(context_menu)
        self._position_context_menu(context_menu, pos)

    def _position_context_menu(self, context_menu, pos):
        app = App.get_running_app()
        window_pos = self.to_window(pos[0], pos[1])
        x = min(max(window_pos[0] + 5, 10), Window.width - context_menu.width - 10)
        y = min(max(window_pos[1] - context_menu.height - 5, 10), Window.height - context_menu.height - 10)
        context_menu.pos = (x, y)

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected
        if not is_selected:
            Window.unbind(on_key_down=self.on_keyboard_down)
            self.intellisense_on_selection(False)
        else:
            Window.bind(on_key_down=self.on_keyboard_down)
            for key in rv.view_adapter.views:
                view = rv.view_adapter.views[key]
                if view and hasattr(view, "selected") and view.selected is not None:
                    view.selected = key == index
            self.intellisense_on_selection(True)
            Clock.schedule_once(lambda dt: self._update_3d_viewer_and_slider(selected_index=index), 0)

    def _update_3d_viewer_and_slider(self, selected_index=None):
        app = App.get_running_app()
        if hasattr(app.root, "gcode_viewer") and app.root.gcode_viewer:
            gcode_viewer = app.root.gcode_viewer
            if not hasattr(gcode_viewer, "raw_linenumbers") or not gcode_viewer.raw_linenumbers:
                return
            if not hasattr(gcode_viewer, "lengths") or not gcode_viewer.lengths:
                return
            index = selected_index if selected_index is not None else self.index
            current_page = app.curr_page
            actual_line_number = (current_page - 1) * MAX_LOAD_LINES + index + 1
            app.root._skip_next_set_selected_line_from_callback = True
            try:
                app.root.gcode_viewer.set_distance_by_lineidx(actual_line_number, 0.5)
            except (IndexError, AttributeError):
                pass
            if hasattr(app.root, "gcode_play_slider") and app.root.gcode_play_slider:
                distance = app.root.gcode_viewer.get_distance_by_lineidx(actual_line_number, 0.5)
                total = app.root.gcode_viewer_distance
                slider_value = (distance * 1000.0 / total) if total else 0.0
                Clock.schedule_once(lambda dt: setattr(app.root.gcode_play_slider, "value", slider_value), 0)

    def on_keyboard_down(self, instance, keyboard, keycode, text, modifiers):
        mod = "ctrl" if sys.platform == "win32" else "meta"
        if text == "c" and self.selected and mod in modifiers:
            Clipboard.copy(self.text.strip())
            return True
        return False


Factory.register("GCodeRow", cls=GCodeRow)


class SelectableBoxLayout(RecycleDataViewBehavior, BoxLayout):
    """Add selection support to the Label"""

    index = None
    selected = BooleanProperty(False)
    selected_dir = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        """Catch and handle the view changes"""
        self.index = index
        return super().refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        """Add selection on touch down"""
        if super().on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            rv = self.parent.recycleview
            if getattr(rv, "multi_select_enabled", False) and self.touch_has_desktop_modifier(touch):
                self.select_with_desktop_modifiers(rv, touch)
                return True
            if touch.is_double_tap:
                if rv.data[self.index]["is_dir"]:
                    rv.child_dir(rv.data[self.index]["filename"])
                else:
                    rv.dispatch("on_double_tap")
                return True
            if getattr(rv, "multi_select_enabled", False):
                self.select_with_desktop_modifiers(rv, touch)
                return True
            return self.parent.select_with_touch(self.index, touch)

    def touch_desktop_modifiers(self, touch):
        modifiers = set()
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

    def touch_has_desktop_modifier(self, touch):
        modifiers = self.touch_desktop_modifiers(touch)
        return bool({"ctrl", "control", "meta", "shift"} & modifiers)

    def select_with_desktop_modifiers(self, rv, touch):
        layout = self.parent
        modifiers = self.touch_desktop_modifiers(touch)
        ctrl_down = bool({"ctrl", "control", "meta"} & modifiers)
        shift_down = "shift" in modifiers

        if shift_down and rv.last_selected_index >= 0:
            if not ctrl_down:
                layout.clear_selection()
            start = min(rv.last_selected_index, self.index)
            end = max(rv.last_selected_index, self.index)
            for index in range(start, end + 1):
                layout.select_node(index)
        elif ctrl_down:
            if self.index in layout.selected_nodes:
                layout.deselect_node(self.index)
            else:
                layout.select_node(self.index)
            rv.last_selected_index = self.index
        else:
            layout.clear_selection()
            layout.select_node(self.index)
            rv.last_selected_index = self.index

        rv.update_selected_files_from_layout(current_index=self.index)
        rv.dispatch("on_select")

    def apply_selection(self, rv, index, is_selected):
        """Respond to the selection of items in the view."""
        self.selected = is_selected
        if self.selected:
            if rv.data[self.index]["is_dir"]:
                self.selected_dir = True
            else:
                self.selected_dir = False
            rv.set_curr_selected_file(rv.data[self.index]["filename"], rv.data[self.index]["intsize"])
        if not getattr(rv, "multi_select_enabled", False):
            rv.update_selected_files_from_layout(current_index=self.index if self.selected else None)
            rv.dispatch("on_select")


# -----------------------------------------------------------------------
# Data Recycle View
# -----------------------------------------------------------------------
class DataRV(RecycleView):
    curr_dir = ""
    curr_dir_name = StringProperty("")

    base_dir = ""
    base_dir_win = ""

    curr_sort_key = StringProperty("date")
    curr_sort_reverse = BooleanProperty(True)
    curr_sort_str = ListProperty(["", " ↓", ""])

    curr_path_list = ListProperty([])
    curr_full_path_list = []
    curr_file_list_buff = []

    default_sort_reverse = {"name": False, "date": True, "size": False}
    search_event = None

    curr_selected_file = StringProperty("")
    curr_selected_filesize = NumericProperty(0)
    curr_selected_is_dir = BooleanProperty(False)
    curr_selected_files = ListProperty([])
    curr_selected_file_infos = ListProperty([])
    multi_select_enabled = BooleanProperty(False)
    last_selected_index = NumericProperty(-1)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_select")
        self.register_event_type("on_double_tap")

    # -----------------------------------------------------------------------
    def on_select(self):
        pass

    def on_double_tap(self):
        pass

    # -----------------------------------------------------------------------
    def set_curr_selected_file(self, filename, filesize):
        self.curr_selected_file = os.path.join(self.curr_dir, filename)
        self.curr_selected_filesize = filesize
        self.curr_selected_is_dir = os.path.isdir(self.curr_selected_file)

    def get_selected_files(self):
        return list(self.curr_selected_files)

    def get_selected_file_infos(self):
        return list(self.curr_selected_file_infos)

    def file_info_for_index(self, index):
        if index < 0 or index >= len(self.data):
            return None
        item = self.data[index]
        path = os.path.join(self.curr_dir, item["filename"])
        return {
            "path": path,
            "filename": item["filename"],
            "filesize": item["intsize"],
            "is_dir": item["is_dir"],
            "index": index,
        }

    def update_selected_files_from_layout(self, current_index=None):
        layout = getattr(self, "layout_manager", None)
        selected_nodes = getattr(layout, "selected_nodes", [])
        selected_indices = sorted(index for index in selected_nodes if 0 <= index < len(self.data))
        infos = [info for info in (self.file_info_for_index(index) for index in selected_indices) if info is not None]
        self.curr_selected_file_infos = infos
        self.curr_selected_files = [info["path"] for info in infos]

        current_info = None
        if current_index is not None and current_index in selected_indices:
            current_info = self.file_info_for_index(current_index)
        elif infos:
            current_info = infos[-1]

        if current_info:
            self.curr_selected_file = current_info["path"]
            self.curr_selected_filesize = current_info["filesize"]
            self.curr_selected_is_dir = current_info["is_dir"]
        else:
            self.curr_selected_file = ""
            self.curr_selected_filesize = 0
            self.curr_selected_is_dir = False

    # -----------------------------------------------------------------------
    def clear_selection(self):
        layout = getattr(self, "layout_manager", None)
        if layout is not None:
            layout.clear_selection()
        for key in self.view_adapter.views:
            if self.view_adapter.views[key].selected != None:
                self.view_adapter.views[key].selected = False
        self.curr_selected_files = []
        self.curr_selected_file_infos = []
        self.curr_selected_file = ""
        self.curr_selected_filesize = 0
        self.curr_selected_is_dir = False
        self.last_selected_index = -1

    # -----------------------------------------------------------------------
    def child_dir(self, child_dir):
        new_path = os.path.join(self.curr_dir, child_dir)
        self.list_dir(new_dir=new_path)

    def fill_dir(self, sort_key=None, switch_reverse=True, keyword=None):
        if sort_key == None:
            sort_key = self.curr_sort_key
        sort_reverse = self.curr_sort_reverse
        if sort_key != self.curr_sort_key:
            sort_reverse = self.default_sort_reverse[sort_key]
            self.curr_sort_reverse = sort_reverse
            self.curr_sort_key = sort_key
        else:
            if switch_reverse:
                self.curr_sort_reverse = not self.curr_sort_reverse
                sort_reverse = self.curr_sort_reverse
        if sort_key == "name":
            self.curr_sort_str = ["↓" if sort_reverse else "↑", "", ""]
        elif sort_key == "date":
            self.curr_sort_str = ["", "↓" if sort_reverse else "↑", ""]
        elif sort_key == "size":
            self.curr_sort_str = ["", "", "↓" if sort_reverse else "↑"]
        self.curr_file_list_buff = sorted(self.curr_file_list_buff, key=lambda x: x[sort_key], reverse=sort_reverse)

        filtered_list = []
        app = App.get_running_app()
        if app.root.file_popup.firmware_mode:
            filtered_list = filter(lambda x: x["is_dir"] or Path(x["name"]).suffix == ".bin", self.curr_file_list_buff)
        else:
            if keyword == None or keyword.strip() == "":
                filtered_list = self.curr_file_list_buff
            else:
                filtered_list = filter(lambda x: keyword.lower() in x["name"].lower(), self.curr_file_list_buff)

        # fill out the list
        self.clear_selection()
        self.last_selected_index = -1
        self.data = []
        for rv_key, file in enumerate(filtered_list):
            try:
                self.data.append(
                    {
                        "rv_key": rv_key,
                        "filename": file["name"],
                        "intsize": file["size"],
                        "filesize": "--" if file["is_dir"] else Utils.humansize(file["size"]),
                        "filedate": Utils.humandate(file["date"]),
                        "is_dir": file["is_dir"],
                    }
                )
            except IndexError:
                logger.error("Tried to write to recycle view data at same time as reading, ignore (indexError)")
        # trigger
        self.dispatch("on_select")

    def goto_path(self, index):
        if index < len(self.curr_full_path_list):
            app = App.get_running_app()
            app.root.file_popup.ti_local_search.text = ""
            self.list_dir(new_dir=self.curr_full_path_list[index])

    def delay_search(self, keyword):
        # if keyword == None or keyword.strip() == '':
        #    return
        if self.search_event is not None:
            self.search_event.cancel()
        self.search_event = Clock.schedule_once(partial(self.execute_search, keyword), 1)

    def execute_search(self, keyword, *args):
        self.fill_dir(keyword=keyword, switch_reverse=False)
        self.search_event = None


# -----------------------------------------------------------------------
# Remote Recycle View
# -----------------------------------------------------------------------
class RemoteRV(DataRV):
    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_select")
        self.register_event_type("on_double_tap")

        self.base_dir = "/sd/gcodes"
        self.base_dir_win = "\\sd\\gcodes"

        self.curr_dir = self.base_dir
        self.curr_dir_name = "gcodes"

    # -----------------------------------------------------------------------
    def parent_dir(self):
        normpath = os.path.normpath(self.curr_dir)
        if normpath == self.base_dir or normpath == self.base_dir_win:
            self.list_dir(new_dir=normpath)
        else:
            self.list_dir(new_dir=os.path.dirname(normpath))

    # -----------------------------------------------------------------------
    def current_dir(self, *args):
        self.list_dir(new_dir=os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir=None):
        if new_dir == None:
            new_dir = self.curr_dir

        self.clear_selection()
        self.curr_file_list_buff = []

        app = App.get_running_app()
        threading.Thread(target=app.root.loadRemoteDir, args=(new_dir,), daemon=True).start()
        self.curr_dir = str(new_dir)
        # self.curr_dir_name = os.path.normpath(self.curr_dir)

    def on_double_tap(self):
        app = App.get_running_app()
        app.root.check_and_download()


# -----------------------------------------------------------------------
# Local Recycle View
# -----------------------------------------------------------------------
class LocalRV(DataRV):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_select")
        self.register_event_type("on_double_tap")
        if kivy_platform == "android":
            self.curr_dir = os.path.abspath(".carveracontroller/gcodes")
            if not os.path.exists(self.curr_dir):
                self.curr_dir = os.path.join(os.path.dirname(__file__), "carveracontroller/gcodes")
        else:
            self.curr_dir = os.path.abspath("./gcodes")
            if not os.path.exists(self.curr_dir):
                self.curr_dir = os.path.join(os.path.dirname(__file__), "gcodes")
        self.curr_dir_name = os.path.basename(os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def parent_dir(self):
        self.list_dir(new_dir=os.path.abspath(os.path.join(self.curr_dir, os.pardir)))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir=None):
        if new_dir == None:
            new_dir = self.curr_dir

        if not new_dir.endswith(os.path.sep):
            new_dir += os.path.sep

        self.curr_file_list_buff = []
        for dirpath, dirnames, filenames in os.walk(new_dir):
            for dirname in dirnames:
                if not dirname.startswith("."):
                    file_time = 0
                    file_path = os.path.join(new_dir, dirname)
                    try:
                        file_time = os.stat(file_path).st_mtime
                    except:
                        continue
                    self.curr_file_list_buff.append(
                        {"name": dirname, "path": file_path, "is_dir": True, "size": 0, "date": file_time}
                    )
            for filename in filenames:
                if not filename.startswith("."):
                    file_size = 0
                    file_time = 0
                    file_path = os.path.join(new_dir, filename)
                    try:
                        file_size = os.stat(file_path).st_size
                        file_time = os.stat(file_path).st_mtime
                    except:
                        continue
                    self.curr_file_list_buff.append(
                        {"name": filename, "path": file_path, "is_dir": False, "size": file_size, "date": file_time}
                    )
            break

        self.fill_dir(switch_reverse=False)

        self.curr_dir = os.path.normpath(new_dir)
        self.curr_full_path_list, path_labels = Utils.directory_breadcrumb_paths(
            self.curr_dir,
            root_label_markers=(self.base_dir,),
        )
        self.curr_path_list = path_labels
        self.curr_dir_name = path_labels[-1] if path_labels else ""

    def on_double_tap(self):
        app = App.get_running_app()
        if app.root.file_popup.firmware_mode:
            app.root.check_and_upload()
        else:
            app.root.check_upload_and_select()


# -----------------------------------------------------------------------
# GCode Recycle View
# -----------------------------------------------------------------------
class GCodeRV(RecycleView):
    data_length = 0
    scroll_time = 0
    old_selected_line = 0
    new_selected_line = 0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(scroll_y=self._on_intel_scroll)

    def _on_intel_scroll(self, *_args):
        hide_gcode_explain()

    def on_scroll_stop(self, touch):
        super().on_scroll_stop(touch)
        self.scroll_time = time.time()

    def set_selected_line(self, line):
        app = App.get_running_app()
        aiming_page = int(line / MAX_LOAD_LINES) + (0 if line % MAX_LOAD_LINES == 0 else 1)
        if aiming_page != app.curr_page:
            app.root.load_page(aiming_page)
        line = line % MAX_LOAD_LINES
        if self.data_length > 0 and line < self.data_length:
            page_lines = len(self.view_adapter.views)
            self.new_selected_line = line - 1

            # Schedule all UI attribute updates for the next frame to avoid re-entry loops
            def update_selection_ui(dt):
                for key in self.view_adapter.views:
                    view = self.view_adapter.views[key]
                    if view and hasattr(view, "selected") and view.selected is not None:
                        view.selected = False
                new_line = self.view_adapter.get_visible_view(self.new_selected_line)
                if new_line:
                    new_line.selected = True
                    self.old_selected_line = self.new_selected_line
                if time.time() - self.scroll_time > 3:
                    scroll_value = Utils.translate(
                        line + 1, page_lines / 2 - 1, self.data_length - page_lines / 2 + 1, 1.0, 0.0
                    )
                    if scroll_value < 0:
                        scroll_value = 0
                    if scroll_value > 1:
                        scroll_value = 1
                    self.scroll_y = scroll_value

            Clock.schedule_once(update_selection_ui, 0)


# -----------------------------------------------------------------------
# Manual Recycle View
# -----------------------------------------------------------------------
class ManualRV(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(scroll_y=self._on_intel_scroll)

    def _on_intel_scroll(self, *_args):
        hide_gcode_explain()


class TopBar(BoxLayout):
    pass


class BottomBar(BoxLayout):
    pass


# -----------------------------------------------------------------------
class Content(ScreenManager):
    pass


# Declare both screens
class FilePage(Screen):
    pass


class ControlPage(Screen):
    pass


class SettingPage(Screen):
    pass


# -----------------------------------------------------------------------
class CMDManager(ScreenManager):
    pass


class GCodeCMDPage(Screen):
    pass


class ManualCMDPage(Screen):
    pass


# -----------------------------------------------------------------------
class PopupManager(ScreenManager):
    pass


class RemotePage(Screen):
    pass


class LocalPage(Screen):
    pass


class Makera(RelativeLayout):
    holding = 0
    pausing = 0
    waiting = 0
    tooling = 0
    loading_dir = ""

    stop = threading.Event()
    load_event = threading.Event()
    machine_detector = MachineDetector()
    file_popup = ObjectProperty()
    coord_popup = ObjectProperty()
    diagnose_popup = ObjectProperty()
    config_popup = ObjectProperty()
    x_drop_down = ObjectProperty()
    y_drop_down = ObjectProperty()
    z_drop_down = ObjectProperty()
    a_drop_down = ObjectProperty()
    coordinate_system_drop_down = ObjectProperty()

    feed_drop_down = ObjectProperty()
    spindle_drop_down = ObjectProperty()
    tool_drop_down = ObjectProperty()
    laser_drop_down = ObjectProperty()
    func_drop_down = ObjectProperty()
    status_drop_down = ObjectProperty()

    operation_drop_down = ObjectProperty()
    gcode_viewer_display_drop_down = ObjectProperty()

    confirm_popup = ObjectProperty()
    unlock_popup = ObjectProperty()
    message_popup = ObjectProperty()
    reconnection_popup = ObjectProperty()
    progress_popup = ObjectProperty()
    input_popup = ObjectProperty()
    manual_wifi_popup = ObjectProperty()
    show_advanced_jog_controls = BooleanProperty(False)
    keyboard_jog_control = BooleanProperty(False)
    pendant_jog_control = BooleanProperty(False)
    _held_jog_keys = set()

    gcode_viewer = ObjectProperty()
    gcode_playing = BooleanProperty(False)
    gcode_cannot_visualise = BooleanProperty(False)

    probing_popup = ObjectProperty()
    coord_config = {}

    progress_info = StringProperty()
    selected_file_line_count = NumericProperty(0)

    test_line = NumericProperty(1)

    config_loaded = False
    config_loading = False

    uploading = False
    uploading_size = 0
    uploading_file = ""

    downloading = False
    downloading_size = 0
    downloading_file = ""
    downloading_config = False

    setting_list = {}
    setting_type_list = {}
    setting_default_list = {}
    setting_change_list = {}

    gcode_viewer_distance = 0

    alarm_triggered = False
    tool_triggered = False

    used_tools = ListProperty()
    upcoming_tool = 0
    file_has_ocodes = False
    tool_change_markers = []
    tool_table = {}
    cam_metadata = None
    document_unit = "mm"

    # Path visibility filters for the G-code viewer color-scheme panel.
    path_show_rapid = True
    path_show_feed = True
    path_speed_bits = VISIBILITY_ALL_BUCKET_BITS
    path_z_bits = VISIBILITY_ALL_BUCKET_BITS

    # Custom property to monitor CNC light state
    light_state = LightProperty(False)

    played_lines = 0
    _remaining_anchor_sec = 0.0
    _remaining_anchor_time = 0.0
    _progress_smooth_clock = None

    show_update = True
    instantFSoverride = True
    fw_upd_text = ""
    fw_version_new = ""
    fw_version = ""
    fw_version_checking = False
    fw_version_checked = False

    filetype_support = "nc"
    filetype = ""

    fileCompressionBlocks = 0  # 文件压缩后的块数
    decompercent = 0  # carvera解压压缩文件的块数
    decompercentlast = 0  # carvera解压压缩文件的块数
    decompstatus = False
    decomptime = 0

    ctl_upd_text = ""
    ctl_version_new = ""
    ctl_version = ""

    common_local_dir_list = []
    recent_local_dir_list = []
    recent_remote_dir_list = []

    lines = []

    load_canceled = False

    control_list = {
        # 'control_name: [update_time, value]'
        "feedrate_scale": [0.0, 100],
        "spindle_scale": [0.0, 100],
        "vacuum_mode": [0.0, 0],
        "extout_mode": [0.0, 0],
        "autoblow_mode": [0.0, 0],
        "autobedclean_mode": [0.0, 0],
        "ionizer_mode": [0.0, 0],
        "laser_mode": [0.0, 0],
        "laser_scale": [0.0, 100],
        "laser_test": [0.0, 0],
        "spindle_switch": [0.0, 0],
        "spindle_slider": [0.0, 0],
        "spindlefan_slider": [0.0, 0],
        "vacuum_slider": [0.0, 0],
        "laser_switch": [0.0, 0],
        "laser_slider": [0.0, 0],
        "light_switch": [0.0, 0],
        "ext_control": [0.0, 0],
        "tool_sensor_switch": [0.0, 0],
        "air_switch": [0.0, 0],
        "wp_charge_switch": [0.0, 0],
    }

    status_index = 0
    past_machine_addr = None
    allow_mdi_while_machine_running = "0"
    allow_jogging_while_machine_running = "1"
    allow_jogging_while_spindle_on = "0"
    _selected_file_machine_key = None
    _last_loaded_file_key = None  # used to track if a different file is selected

    def __init__(self, ctl_version):
        super().__init__()

        Window.bind(on_request_close=self.on_request_close)
        Window.bind(on_key_down=self._global_keyboard_keydown)

        self.temp_dir = tempfile.mkdtemp()
        self.ctl_version = ctl_version
        self.file_popup = FilePopup()

        self.cnc = CNC()
        self.wcs_names = self.cnc.getWCSNames()
        self.controller = Controller(
            self.cnc, self.execCallback, Config.getboolean("carvera", "log_sent_receive", fallback=False)
        )
        # Set up reconnection callbacks
        self.controller.set_reconnection_callbacks(
            self.attempt_reconnect, self.on_reconnect_failed, self.on_reconnect_success
        )
        # Fill basic global variables
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[NOT_CONNECTED]

        self.coord_config = {
            "origin": {"anchor": 1, "x_offset": 0.0, "y_offset": 0.0},
            "margin": {"active": False},
            "zprobe": {"active": False, "origin": 2, "x_offset": 5.0, "y_offset": 5.0},
            "leveling": {
                "active": False,
                "x_points": 5,
                "y_points": 5,
                "height": 5,
                "xn_offset": 0.0,
                "xp_offset": 0.0,
                "yn_offset": 0.0,
                "yp_offset": 0.0,
            },
        }
        self.update_coord_config()
        self.coord_popup = CoordPopup(self.coord_config)
        self.bind(gcode_cannot_visualise=self._update_startline_checkbox_disabled)
        self._update_startline_checkbox_disabled()
        self.xyz_probe_popup = XYZProbePopup()
        self.pairing_popup = PairingPopup()
        self.upgrade_popup = UpgradePopup()
        self.pick_file_popup = None
        self.language_popup = LanguagePopup()
        self.language_popup.sp_language.values = translation.LANGS.values()
        self.language_popup.sp_language.text = "English"
        for lang_key in translation.LANGS:
            if lang_key == translation.tr.lang:
                self.language_popup.sp_language.text = translation.LANGS[lang_key]
                break

        self.diagnose_popup = DiagnosePopup()

        self.x_drop_down = XDropDown()
        self.y_drop_down = YDropDown()
        self.z_drop_down = ZDropDown()
        self.a_drop_down = ADropDown()
        self.coordinate_system_drop_down = CoordinateSystemDropDown()
        self.feed_drop_down = FeedDropDown()
        self.spindle_drop_down = SpindleDropDown()
        self.tool_drop_down = ToolDropDown()
        self.laser_drop_down = LaserDropDown()
        self.func_drop_down = FuncDropDown()
        self.status_drop_down = StatusDropDown()
        self.operation_drop_down = OperationDropDown()
        self.gcode_viewer_display_drop_down = GcodeViewerDisplayDropDown()
        self.jog_speed_drop_down = JogSpeedDropDown(self.controller)

        self.confirm_popup = ConfirmPopup()
        self.unlock_popup = UnlockPopup()
        self.message_popup = MessagePopup()
        self.select_probe_popup = SelectAndCalibrateProbePopup()
        self.reconnection_popup = ReconnectionPopup()
        self.progress_popup = ProgressPopup()
        self.input_popup = InputPopup()
        self.manual_wifi_popup = ManualWifiPopup()

        self.probing_popup = ProbingPopup(self.controller)
        self.cmm_workbench_popup = None
        self.facing_popup = FacingWizardPopup()
        self.stock_settings_popup = StockSettingsPopup()
        self.bed_settings_popup = BedSettingsPopup()
        self.adv_calibrate_popup = AdvCalibratePopup()
        self.wcs_settings_popup = WCSSettingsPopup(self.controller, self.wcs_names)
        self.set_rotation_popup = SetRotationPopup(self.controller, self.cnc)
        self.comports_drop_down = DropDown(auto_width=False, width="250dp")
        self.wifi_conn_drop_down = DropDown(auto_width=False, width="250dp")

        self.wifi_ap_drop_down = DropDown(auto_width=False, width="300dp")
        self.wifi_ap_drop_down.bind(on_select=lambda instance, x: self.connWIFI(x))
        self.wifi_ap_status_bar = None

        self.local_dir_drop_down = DropDown(auto_width=False, width="190dp")
        self.local_dir_drop_down.bind(on_select=lambda instance, x: self.file_popup.local_rv.list_dir(x))

        self.remote_dir_drop_down = DropDown(auto_width=False, width="190dp")
        self.remote_dir_drop_down.bind(on_select=lambda instance, x: self.file_popup.remote_rv.list_dir(x))

        # init gcode viewer
        self.gcode_viewer = GCodeViewer()
        self.gcode_viewer.high_precision_time_estimate = Config.getboolean(
            "carvera", "high_precision_reamining_time_estimate", fallback=True
        )
        self.gcode_viewer_container.add_widget(self.gcode_viewer)
        self.gcode_viewer.set_frame_callback(self.gcode_play_call_back)
        self.gcode_viewer.set_play_over_callback(self.gcode_play_over_call_back)
        self.gcode_viewer.set_error_popup_callback(self._on_gcode_cannot_visualise)
        self.gcode_viewer.time_estimate_progress_callback = self._on_time_estimate_progress
        self.gcode_viewer.bind(sim_progress=self._on_viewer_sim_progress)
        self.gcode_viewer.bind(sim_checkpoints=self._on_viewer_sim_checkpoints)
        self.gcode_viewer.bind(sim_hud_text=self._on_viewer_sim_hud_text)
        self._on_viewer_sim_hud_text(self.gcode_viewer, self.gcode_viewer.sim_hud_text)
        self.gcode_viewer_display_drop_down.show_grid = self.gcode_viewer.is_grid_visible()
        self.gcode_viewer.bind(stock_visible=self._on_viewer_stock_visible)
        self._on_viewer_stock_visible(self.gcode_viewer, self.gcode_viewer.stock_visible)
        self.gcode_viewer.bind(bed_visible=self._on_viewer_bed_visible)
        self._on_viewer_bed_visible(self.gcode_viewer, self.gcode_viewer.bed_visible)
        self.path_hidden_tools = set()

        # init camera live view
        self.camera_checked = False
        self.camera_probe = 0
        self.camera_stream = Z1Camera(
            on_frame=self._show_camera_frame,
            on_streaming=self._set_camera_streaming,
            on_error=partial(self.show_message_popup, btn_disabled=False),
        )
        self.ids.camera_splitter.bind(collapsed=self._on_camera_splitter_collapsed)
        self.ids.camera_splitter.collapse()

        # init settings
        self.config = ConfigParser()
        self.config_popup = ConfigPopup()
        self.config_loaded = False
        self.config_loading = False
        self._config_apply_failed = False
        self._config_download_failures = 0
        self.setting_list = {}
        self.setting_type_list = {}
        self.setting_default_list = {}
        self.machine_config_data = None
        self.machine_config_data_model = None
        self.machine_settings_model = None
        self.controller_setting_change_list = {}
        self.load_controller_config()
        self.load_gcode_viewer_config()
        self.load_pendant_config()

        self.usb_event = lambda instance, device_path: self.openUSB(device_path)
        self.wifi_event = lambda instance, x: self.openWIFI(x)

        self.heartbeat_time = 0
        self.machine_metadata_query_time = 0
        self.file_just_loaded = False
        self.last_connection_method = Config.get("carvera", "last_connection_method", fallback="") or ""

        self.fill_remote_dir_callback = None

        self.instantFSoverride = Config.get("carvera", "instantFSoverride") == "1"

        self.show_update = Config.get("carvera", "show_update") == "1"
        self.upgrade_popup.cbx_check_at_startup.active = self.show_update
        if self.show_update:
            self.check_for_updates()

        if Config.has_option("carvera", "address"):
            self.past_machine_addr = Config.get("carvera", "address")

        if Config.has_option("carvera", "allow_mdi_while_machine_running"):
            self.allow_mdi_while_machine_running = Config.get("carvera", "allow_mdi_while_machine_running")

        if Config.has_option("carvera", "allow_jogging_while_machine_running"):
            self.allow_jogging_while_machine_running = Config.get("carvera", "allow_jogging_while_machine_running")

        if Config.has_option("carvera", "allow_jogging_while_spindle_on"):
            self.allow_jogging_while_spindle_on = Config.get("carvera", "allow_jogging_while_spindle_on")

        self._bind_jog_control_deps()

        # Setup pendant
        self.refresh_pendant_settings()
        self.setup_pendant()

        if Config.has_option("carvera", "tooltip_delay"):
            delay_value = Config.getfloat("carvera", "tooltip_delay")
            App.get_running_app().tooltip_delay = delay_value if delay_value >= 0 else 0.5

        if Config.has_option("carvera", "show_tooltips"):
            default_show_tooltips = Config.get("carvera", "show_tooltips") != "0"
            App.get_running_app().show_tooltips = default_show_tooltips

        if Config.has_option("carvera", "invert_y_axis_jogging"):
            App.get_running_app().invert_y_axis_jogging = Config.get("carvera", "invert_y_axis_jogging") == "1"

        if Config.has_option("carvera", "active_color"):
            App.get_running_app().active_color = self._parse_active_color(Config.get("carvera", "active_color"))

        self._load_gcode_highlight_settings()
        self._load_playbar_tool_change_marker_settings()
        if self.wpb_play:
            self.wpb_play.marker_tooltip_provider = self._playbar_tool_change_tooltip

        # blink timer
        Clock.schedule_interval(self.blink_state, 0.5)
        # status switch timer
        Clock.schedule_interval(self.switch_status, 8)
        # model metadata check timer
        Clock.schedule_interval(self.check_model_metadata, 10)

        self.has_onscreen_keyboard = False
        if sys.platform == "ios":
            self.has_onscreen_keyboard = True

        #
        threading.Thread(target=self.monitorSerial).start()

        # Auto-connect on startup only when auto-reconnect is enabled.
        if Config.getboolean("carvera", "auto_reconnect_enabled", fallback=True):
            Clock.schedule_once(lambda dt: self.reconnect_last_connection(quiet=True, for_app_launch=True))

    def _parse_active_color(self, value):
        """Parse a color string like '0,255,255,255' into an RGBA list (0-1 range)."""
        try:
            if not value:
                return [0, 1, 1, 1]  # Default cyan
            parts = [float(x.strip()) for x in value.split(",")]
            if len(parts) == 3:
                parts.append(255.0)  # Add alpha if missing
            # Assume 0-255 range, convert to 0-1
            return [parts[0] / 255, parts[1] / 255, parts[2] / 255, parts[3] / 255 if parts[3] > 1 else parts[3]]
        except Exception:
            return [0, 1, 1, 1]  # Default cyan

    def _load_playbar_tool_change_marker_settings(self):
        """Read playback bar tool-change marker visibility from config."""
        raw_enabled = (
            Config.get("carvera", "show_playbar_tool_change_markers")
            if Config.has_option("carvera", "show_playbar_tool_change_markers")
            else "1"
        )
        self.show_playbar_tool_change_markers = raw_enabled not in ("0", "false", "False")

    def _load_gcode_highlight_settings(self):
        """Read gcode highlighting config into cached attributes."""
        raw_enabled = (
            Config.get("carvera", "gcode_highlight_enabled")
            if Config.has_option("carvera", "gcode_highlight_enabled")
            else "1"
        )
        self.gcode_highlight_enabled = raw_enabled not in ("0", "false", "False")
        self.gcode_highlight_colors = {}
        for cat in GCODE_DEFAULT_COLORS:
            config_key = f"gcode_color_{cat}"
            raw = Config.get("carvera", config_key) if Config.has_option("carvera", config_key) else None
            if raw:
                self.gcode_highlight_colors[cat] = self._config_color_to_hex(raw)

    @staticmethod
    def _config_color_to_hex(value):
        """Convert a 'R,G,B,A' config string (0-255) to a Kivy markup hex color.

        Returns '#RRGGBBAA' when alpha < 255, otherwise '#RRGGBB'.
        """
        try:
            parts = [int(float(x.strip())) for x in value.split(",")]
            r, g, b = parts[0], parts[1], parts[2]
            a = parts[3] if len(parts) >= 4 else 255
            if a < 255:
                return f"#{r:02X}{g:02X}{b:02X}{a:02X}"
            return f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            return "#C8C8C8"

    def on_request_close(self, *args):
        # Cleanup the temporary directory when the app is closed
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.error(f"Error cleaning up temporary directory: {e}")

        try:
            self.pendant.close()
        except Exception as e:
            logger.error(f"Error closing pendant: {e}")

        try:
            if getattr(self, "controller", None) is not None:
                self.controller.close_manual()
        except Exception as e:
            logger.error(f"Error closing machine connection: {e}")

        # Save the last window size.
        # Seems that kivvy uses the window size before dpi scaling in the config,
        # but after dp scaling in Window.size
        Config.set("graphics", "width", int(Window.size[0] / Metrics.dp))
        Config.set("graphics", "height", int(Window.size[1] / Metrics.dp))
        Config.write()
        return False  # Allow the window to close

    def load_controller_config(self):
        config_def_file = os.path.join(os.path.dirname(__file__), "controller_config.json")
        with open(config_def_file) as file:
            controller_config_definition = json.load(file)
        controller_config = []

        # Set default controller config values
        for setting in controller_config_definition:
            if "default" in setting:
                Config.setdefault(setting["section"], setting["key"], setting["default"])
                setting.pop("default", None)
            controller_config.append(setting)

        self.config_popup.settings_panel.add_json_panel(tr._("Controller"), Config, data=json.dumps(controller_config))

        self._update_macro_button_text()

    def load_gcode_viewer_config(self):
        config_def_file = os.path.join(os.path.dirname(__file__), "gcode_viewer_config.json")
        try:
            with open(config_def_file) as file:
                gcode_viewer_config_definition = json.load(file)
        except Exception as e:
            logger.error(f"Failed to load gcode_viewer_config.json: {e}")
            return
        gcode_viewer_config = []

        for setting in gcode_viewer_config_definition:
            if "default" in setting:
                Config.setdefault(setting["section"], setting["key"], setting["default"])
                setting.pop("default", None)
            gcode_viewer_config.append(setting)

        self.config_popup.settings_panel.add_json_panel(
            tr._("G-Code Viewer"), Config, data=json.dumps(gcode_viewer_config)
        )

    def load_pendant_config(self):
        config_def_file = os.path.join(os.path.dirname(__file__), "pendant_config.json")
        with open(config_def_file) as file:
            pendant_config_definition = json.load(file)
        pendant_config = []
        pendant_types_map = {}

        for setting in pendant_config_definition:
            if "default" in setting:
                Config.setdefault(setting["section"], setting["key"], setting["default"])
                setting.pop("default", None)
            if "pendant_types" in setting:
                pendant_types_map[setting["key"]] = setting.pop("pendant_types")
            pendant_config.append(setting)

        SettingPendantSelector.pendant_types_map = pendant_types_map
        self.config_popup.settings_panel.add_json_panel(tr._("Pendant"), Config, data=json.dumps(pendant_config))

    def _update_macro_button_text(self):
        for macro_config_key in ["touch_macro_1", "touch_macro_2", "touch_macro_3"]:
            macro_value = Config.get("carvera", macro_config_key)
            if macro_value:
                logger.debug(f"{macro_config_key} set to: {macro_value=}")
                macro_name = json.loads(macro_value).get("name", False)
                if macro_name:
                    self.ids[
                        macro_config_key + "_btn"
                    ].text = macro_name  # the button ids for the macro UI buttons are suffixed with _btn

    def run_macro(self, macro_id: int) -> None:
        macro_key = f"touch_macro_{macro_id}"
        macro_value = Config.get("carvera", macro_key)

        if not macro_value:
            logger.warning(f"No macro defined for ID {macro_id}")
            return

        macro_value = json.loads(macro_value)

        if not macro_value.get("gcode"):
            Clock.schedule_once(
                partial(self.loadError, tr._("No Macro defined. Configure one in Settings-> Controller")), 0
            )

        try:
            lines = macro_value.get("gcode", "").splitlines()
            for l in lines:
                l = l.strip()
                if l == "":
                    continue
                self.controller.sendGCode(l)
        except Exception as e:
            logger.error(f"Failed to run macro {macro_id}: {e}")

    def open_download(self):
        webbrowser.open(DOWNLOAD_ADDRESS, new=2)

    def open_fw_download(self):
        webbrowser.open(FW_DOWNLOAD_ADDRESS, new=2)

    def open_fw_upload(self):
        self.file_popup.firmware_mode = True
        if sys.platform == "ios":
            from . import ios_helpers

            ios_helpers.pick_file()
        else:
            self.file_popup.popup_manager.transition.duration = 0
            self.file_popup.popup_manager.current = "local_page"
            self.file_popup.open()
            self.file_popup.local_rv.child_dir("")

    def open_online_docs(self):
        webbrowser.open("https://carvera-community.gitbook.io/docs/controller/")

    def send_bug_report(self):
        webbrowser.open("https://github.com/Carvera-Community/Carvera_Controller/issues/new")
        webbrowser.open("https://github.com/Carvera-Community/Carvera_Community_Firmware/issues/new")
        log_dir = Path.home() / ".kivy" / "logs"

        # Open the log directory with whatever native file browser is available
        if sys.platform == "win32":
            os.startfile(log_dir)
        else:
            # Linux and MacOS
            if sys.platform != "ios":
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, log_dir])

    def open_probing_popup(self):
        if CNC.vars["tool"] == ZPROBE_TOOL_NUMBER or is_probe_tools_range(CNC.vars["tool"]):
            # Disable keyboard control to prevent accidents when opening the popup
            # But save the state to restore after probing is closed
            self._pre_modal_keyboard_jog = self.keyboard_jog_control
            self.toggle_keyboard_jog_control(True)
            self.probing_popup.open()
        else:
            self.select_probe_popup = SelectAndCalibrateProbePopup()
            self.select_probe_popup.open()

    def _ensure_cmm_workbench_popup(self):
        if self.cmm_workbench_popup is None:
            from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import (
                CMMWorkbenchPopup,
            )

            self.cmm_workbench_popup = CMMWorkbenchPopup(self.controller)
        return self.cmm_workbench_popup

    def open_cmm_workbench_popup(self):
        app = App.get_running_app()
        if not app.is_community_firmware:
            self.show_message_popup(
                tr._("CMM Workbench requires the Community firmware."),
                False,
            )
            return
        if CNC.vars["tool"] == 0 or CNC.vars["tool"] >= 999990:
            self._pre_modal_keyboard_jog = self.keyboard_jog_control
            self.toggle_keyboard_jog_control(True)
            self._ensure_cmm_workbench_popup().open()
        else:
            self.select_probe_popup = SelectAndCalibrateProbePopup()
            self.select_probe_popup.open()

    def open_facing_popup(self):
        app = App.get_running_app()
        if not app.is_community_firmware:
            self.show_message_popup(tr._("Facing wizard requires the Community firmware."), False)
            return
        self._pre_modal_keyboard_jog = self.keyboard_jog_control
        self.toggle_keyboard_jog_control(True)
        self.facing_popup.open()

    def open_stock_settings_popup(self):
        self._pre_modal_keyboard_jog = self.keyboard_jog_control
        self.toggle_keyboard_jog_control(True)
        popup = self.stock_settings_popup
        popup.rotary_mode = bool(App.get_running_app().has_4axis)
        popup.has_off_axis_y = bool(App.get_running_app().has_off_axis_y)
        popup.open()

    def open_bed_settings_popup(self):
        self._pre_modal_keyboard_jog = self.keyboard_jog_control
        self.toggle_keyboard_jog_control(True)
        self.bed_settings_popup.open()

    def apply_bed_settings(self) -> bool:
        """Push the saved bed for the current machine into the 3D viewer."""
        if self.gcode_viewer is None:
            return False
        app = App.get_running_app()
        model = (getattr(app, "model", "") or "").strip() if app is not None else ""
        file_loaded = bool(app is not None and (app.selected_remote_filename or app.selected_local_filename))
        connected = app is not None and app.state != NOT_CONNECTED and is_known_machine(model)

        # Only show the bed if there is a file loaded for the current machine
        file_for_this_machine = (
            self._selected_file_machine_key is None
            or self._selected_file_machine_key == self._get_current_machine_connection_key()
        )
        if not file_loaded or not connected or not file_for_this_machine:
            return bool(self.gcode_viewer.set_bed(None, visible=False))

        store = load_store()
        bed = get_bed(store, model, selected_id(store, model))
        if bed is None:
            return bool(self.gcode_viewer.set_bed(None, visible=False))
        path = resolve_mesh_path(bed)
        if path is None:
            self.show_message_popup(tr._("Bed mesh is missing."), False)
            self.gcode_viewer.set_bed(None, visible=False)
            return False
        ok = bool(
            self.gcode_viewer.set_bed(
                path,
                mcs_xyz=(bed["mcs_x"], bed["mcs_y"], bed["mcs_z"]),
                material=bed["material"],
                visible=True,
            )
        )
        if not ok:
            self.show_message_popup(tr._("Could not load the bed mesh."), False)
        return ok

    def apply_stock_settings(self, settings: dict) -> bool:
        """Push stock settings from the popup into the 3D viewer.

        Must be called on the main thread (popup Apply is). Not ``@mainthread``:
        Kivy's decorator always schedules and returns ``None``, so the popup
        could not observe success/failure.
        """
        return self._apply_stock_settings_impl(settings)

    def _apply_stock_settings_impl(self, settings: dict) -> bool:
        """Apply stock settings on the calling thread (must already be main thread)."""
        if self.gcode_viewer is None:
            return False
        try:
            bounds = bounds_from_settings(settings)
            simulate = bool(settings.get("simulate_cut", False)) and self.gcode_viewer.simulation_available()
            self.gcode_viewer.set_stock(
                bounds,
                visible=bool(settings.get("show_stock", False)),
                simulate_cut=simulate,
                voxel_resolution=voxel_resolution_from_settings(settings),
                checkpoint_level=checkpoint_level_from_settings(settings),
                mesh_while_playing=mesh_while_playing_from_settings(settings),
                carver_mode=carver_mode_from_settings(settings),
                shape=shape_from_settings(settings),
                material=material_from_settings(settings),
            )
        except Exception:
            logger.exception("failed to apply stock settings")
            return False
        return True

    def _reset_stock_settings(self, shape=None, origin=None, show_stock=False):
        """Push a stock reset into the popup and viewer. Must already be main thread."""
        popup = getattr(self, "stock_settings_popup", None)
        if popup is not None:
            settings = popup.reset_for_loaded_file(shape=shape, origin=origin, show_stock=show_stock)
        else:
            settings = default_settings()
            if shape is not None:
                settings["shape"] = shape.to_dict()
            if origin is not None:
                settings["origin"] = origin.to_dict()
            settings["show_stock"] = bool(show_stock)
            settings["simulate_cut"] = False
        return self._apply_stock_settings_impl(settings)

    def _should_auto_show_header_stock(self, cam_stock) -> bool:
        """True when header stock exists and the viewer setting allows auto-display."""
        if not header_stock_usable(cam_stock):
            return False
        raw = (
            Config.get("carvera", "gcode_auto_show_stock")
            if Config.has_option("carvera", "gcode_auto_show_stock")
            else "1"
        )
        return raw not in ("0", "false", "False")

    def _auto_stock_shape_origin(self):
        """CAM-header stock if present, otherwise toolpath AABB estimate."""
        metadata = getattr(self, "cam_metadata", None) or CamMetadata.empty()
        viewer = getattr(self, "gcode_viewer", None)
        app = App.get_running_app()
        rotary = bool(app is not None and getattr(app, "has_4axis", False))
        feed_z_max_mm = None
        if viewer is not None:
            if rotary:
                feed_z_max_mm = viewer.raw_feed_z_max_mm()
            elif getattr(viewer, "raw_feed_rates", None):
                feed_z_max_mm = float(getattr(viewer, "z_max_mm", 0.0))
        return auto_stock_for_loaded_file(
            metadata.stock,
            CNC.vars["xmin"],
            CNC.vars["ymin"],
            CNC.vars["zmin"],
            CNC.vars["xmax"],
            CNC.vars["ymax"],
            CNC.vars["zmax"],
            tool_table=self.tool_table,
            unit_scale=unit_scale_to_mm(self.document_unit),
            feed_z_max_mm=feed_z_max_mm,
            rotary=rotary,
        )

    @mainthread
    def reset_stock_for_loaded_file(self):
        """Hide stock for a new file load (shape/origin filled later in load_end).

        Must run on the main thread — touches popup widgets and rebuilds GL meshes.
        Uses the last *applied* snapshot (not live UI) so an open popup's dirty
        or invalid edits are discarded rather than committed.
        """
        self._reset_stock_settings()

    def open_adv_calibrate_popup(self):
        app = App.get_running_app()
        if not app.is_community_firmware:
            self.show_message_popup(tr._("Adv Calibrate requires the Community firmware."), False)
            return
        self.adv_calibrate_popup.open()

    def open_update_popup(self):
        self.upgrade_popup.check_button.disabled = False
        self.upgrade_popup.open(self)

    def close_update_popup(self):
        if self.upgrade_popup.cbx_check_at_startup.active != self.show_update:
            self.show_update = self.upgrade_popup.cbx_check_at_startup.active
            Config.set("carvera", "show_update", "1" if self.show_update else "0")
            Config.write()
        self.upgrade_popup.dismiss(self)

    def check_for_updates(self):
        self.fw_upd_text = ""
        self.fw_version_checked = False
        self.ctl_upd_text = ""
        UrlRequest(FW_UPD_ADDRESS, on_success=self.fw_upd_loaded)
        UrlRequest(CTL_UPD_ADDRESS, on_success=self.ctl_upd_loaded)

    def fw_upd_loaded(self, req, result):
        # parse result
        self.fw_upd_text = result

    def check_fw_version(self):
        self.upgrade_popup.fw_upd_text.text = self.fw_upd_text
        self.upgrade_popup.fw_upd_text.cursor = (0, 0)  # Position the cursor at the top of the text
        versions = re.search(r"\[[0-9]+\.[0-9]+\.[0-9]+\]", self.fw_upd_text)
        if versions != None:
            self.fw_version_new = versions[0][1 : len(versions[0]) - 1]
            if self.fw_version != "":
                app = App.get_running_app()
                if Utils.digitize_v(self.fw_version_new) > Utils.digitize_v(self.fw_version):
                    app.fw_has_update = True
                    self.upgrade_popup.fw_version_txt.text = (
                        tr._(" New version detected: v") + self.fw_version_new + tr._(" Current: v") + self.fw_version
                    )
                else:
                    app.fw_has_update = False
                    self.upgrade_popup.fw_version_txt.text = tr._(" Current version: v") + self.fw_version
        self.fw_version_checked = True

    def ctl_upd_loaded(self, req, result):
        self.ctl_upd_text = result
        Clock.schedule_once(self.check_ctl_version, 0)

    def change_language(self, lang_desc):
        for lang_key in translation.LANGS:
            if translation.LANGS[lang_key] == lang_desc:
                if tr.lang != lang_key:
                    tr.switch_lang(lang_key)
                    Config.set("carvera", "language", lang_key)
                    Config.write()
        self.language_popup.dismiss()
        self.config_popup.btn_apply.disabled = True
        self.message_popup.lb_content.text = tr._("Language setting applied, restart Controller app to take effect !")
        self.message_popup.open()

    def check_ctl_version(self, *args):
        self.upgrade_popup.ctl_upd_text.text = self.ctl_upd_text
        self.upgrade_popup.ctl_upd_text.cursor = (0, 0)  # Position the cursor at the top of the text
        versions = re.search(r"\[[0-9]+\.[0-9]+\.[0-9]+\]", self.ctl_upd_text)
        if versions != None:
            self.ctl_version_new = versions[0][1 : len(versions[0]) - 1]
            app = App.get_running_app()
            if Utils.digitize_v(self.ctl_version_new) > Utils.digitize_v(self.ctl_version):
                app.ctl_has_update = True
                self.upgrade_popup.ctl_version_txt.text = (
                    tr._(" New version detected: v") + self.ctl_version_new + tr._(" Current: v") + self.ctl_version
                )
            else:
                app.ctl_has_update = False
                self.upgrade_popup.ctl_version_txt.text = tr._(" Current version: v") + self.ctl_version
        self.ctl_version_checked = True

    # -----------------------------------------------------------------------
    def play(self, file_name, start_line):
        # stop review play first
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False
        # apply and play
        self.apply(True)
        # play file
        CNC.vars["playedseconds"] = 0
        if start_line:
            # Show confirmation dialog for beta resume playback feature
            self.open_resume_playback_confirm_popup(file_name, start_line)
        else:
            self.controller.playCommand(file_name, has_ocodes=self.file_has_ocodes)

    # -----------------------------------------------------------------------
    def apply(self, buffer=False):
        app = App.get_running_app()

        if app.has_4axis:
            self.controller.wcsClearRotation()

        goto_origin = False
        apply_margin = self.coord_config["margin"]["active"]
        apply_zprobe = self.coord_config["zprobe"]["active"]
        apply_leveling = self.coord_config["leveling"]["active"]
        # set goto path origin flag if no ATC and not in path area
        if app.has_4axis:
            goto_origin = True
        elif not apply_margin and not apply_zprobe and not apply_leveling:
            if (
                CNC.vars["wx"] < CNC.vars["xmin"]
                or CNC.vars["wx"] > CNC.vars["xmax"]
                or CNC.vars["wy"] < CNC.vars["ymin"]
                or CNC.vars["wy"] > CNC.vars["ymax"]
            ):
                goto_origin = True

        zprobe_abs = False
        # calculate zprobe offset
        zprobe_offset_x = self.coord_config["zprobe"]["x_offset"] - self.coord_config["leveling"]["xn_offset"]
        zprobe_offset_y = self.coord_config["zprobe"]["y_offset"] - self.coord_config["leveling"]["yn_offset"]
        if self.coord_config["zprobe"]["origin"] == 1:
            zprobe_offset_x = zprobe_offset_x - CNC.vars["xmin"]
            zprobe_offset_y = zprobe_offset_y - CNC.vars["ymin"]
        if app.has_4axis:
            zprobe_abs = True

        self.controller.autoCommand(
            apply_margin,
            apply_zprobe,
            zprobe_abs,
            apply_leveling,
            goto_origin,
            zprobe_offset_x,
            zprobe_offset_y,
            self.coord_config["leveling"]["x_points"],
            self.coord_config["leveling"]["y_points"],
            self.coord_config["leveling"]["height"],
            buffer,
            [
                self.coord_config["leveling"]["xn_offset"],
                self.coord_config["leveling"]["xp_offset"],
                self.coord_config["leveling"]["yn_offset"],
                self.coord_config["leveling"]["yp_offset"],
            ],
            self.upcoming_tool,
        )

        # change back to last tool if needed
        if buffer and self.upcoming_tool == 0 and (apply_margin or apply_zprobe or apply_leveling):
            self.controller.bufferChangeToolCommand(CNC.vars["tool"])

    # -----------------------------------------------------------------------
    def set_work_origin(self):
        origin_x = self.coord_config["origin"]["x_offset"]
        origin_y = self.coord_config["origin"]["y_offset"]
        app = App.get_running_app()
        if not app.has_4axis:
            if self.coord_config["origin"]["anchor"] == 2 and app.has_anchor2:
                origin_x += CNC.vars["anchor1_x"] + CNC.vars["anchor2_offset_x"]
                origin_y += CNC.vars["anchor1_y"] + CNC.vars["anchor2_offset_y"]
            elif self.coord_config["origin"]["anchor"] == 4:
                origin_x += CNC.vars["mx"]
                origin_y += CNC.vars["my"]
            else:
                origin_x += CNC.vars["anchor1_x"]
                origin_y += CNC.vars["anchor1_y"]
        else:
            origin_x += CNC.vars["anchor1_x"] + CNC.vars["rotation_offset_x"]
            origin_y += CNC.vars["anchor1_y"] + CNC.vars["rotation_offset_y"]

        self.controller.wcsSetM(origin_x, origin_y, None, None)

        # refresh after 1 seconds
        Clock.schedule_once(self.refresh_work_origin, 1)

    # -----------------------------------------------------------------------
    def refresh_work_origin(self, *args):
        self.coord_popup.load_config()

    # -----------------------------------------------------------------------
    def blink_state(self, *args):
        app = App.get_running_app()
        if self.uploading or self.downloading:
            return
        if self.holding == 1:
            self.status_data_view.color = STATECOLOR["Hold"]
            self.holding = 2
        elif self.holding == 2:
            self.status_data_view.color = STATECOLOR["Disable"]
            self.holding = 1

        if self.pausing == 1:
            self.status_data_view.color = STATECOLOR["Pause"]
            self.pausing = 2
        elif self.pausing == 2:
            self.status_data_view.color = STATECOLOR["Disable"]
            self.pausing = 1

        if self.waiting == 1:
            self.status_data_view.color = STATECOLOR["Wait"]
            self.waiting = 2
        elif self.waiting == 2:
            self.status_data_view.color = STATECOLOR["Disable"]
            self.waiting = 1

        if self.tooling == 1:
            self.status_data_view.color = STATECOLOR["Tool"]
            self.tooling = 2
        elif self.tooling == 2:
            self.status_data_view.color = STATECOLOR["Disable"]
            self.tooling = 1

        # check heartbeat
        if self.controller.sendNUM != 0 or self.controller.loadNUM != 0:
            self.heartbeat_time = time.time()
        if getattr(self.controller, "_refresh_heartbeat", False):
            self.heartbeat_time = time.time()
            self.controller._refresh_heartbeat = False
        if getattr(self.controller, "_baud_switch_in_progress", False):
            # Don't treat a temporary baud-switch pause as a dead connection.
            self.heartbeat_time = time.time()
            return
        if getattr(self.controller, "_connecting", False) or getattr(self, "_usb_connect_in_progress", False):
            # Open + protocol probe run off the UI thread; stream is unset until ready.
            self.heartbeat_time = time.time()
            return
        grace_until = getattr(self.controller, "_heartbeat_grace_until", 0) or 0
        if grace_until and time.time() < grace_until:
            # USB DTR reset leaves the machine booting; wait for first status.
            self.heartbeat_time = time.time()
            return

        if self.file_just_loaded:
            self.file_just_loaded = False
            return

        if time.time() - self.heartbeat_time > HEARTBEAT_TIMEOUT and self.controller.stream:
            logger.error("Connection to machine lost")
            # Check reconnection configuration (only if not a manual disconnect and not already reconnecting)
            if not self.controller._manual_disconnect and not self.reconnection_popup._is_open:
                auto_reconnect_enabled = Config.getboolean("carvera", "auto_reconnect_enabled", fallback=True)
                reconnect_wait_time = Config.getint("carvera", "reconnect_wait_time", fallback=10)
                reconnect_attempts = Config.getint("carvera", "reconnect_attempts", fallback=3)

                # Update controller reconnection settings
                self.controller.set_reconnection_config(auto_reconnect_enabled, reconnect_wait_time, reconnect_attempts)

                if auto_reconnect_enabled:
                    # Show reconnection popup with countdown (WiFi or USB)
                    self.reconnection_popup.start_countdown(
                        reconnect_attempts, reconnect_wait_time, self.attempt_reconnect, self.on_reconnect_failed
                    )
                    self.reconnection_popup.open()

                    # Start countdown timer
                    Clock.schedule_interval(self.reconnection_popup.countdown_tick, 1.0)
                else:
                    # Show reconnection popup in manual mode
                    self.reconnection_popup.show_manual_reconnect(self.attempt_reconnect)
                    self.reconnection_popup.open()

            self.controller.close()
            self.updateStatus()

    # -----------------------------------------------------------------------
    def switch_status(self, *args):
        self.status_index = self.status_index + 1
        if self.status_index >= 6:
            self.status_index = 0
        if self._progress_smooth_clock is not None:
            self._update_progress_smooth(0)

    # -----------------------------------------------------------------------
    def check_model_metadata(self, *args):
        app = App.get_running_app()

        # The App.get_running_app() can return None in certain situations, especially during initialization or shutdown.
        if app is None:
            return

        if self.controller.stream is None:
            return

        # Check if model has been set and if not, query for it
        if not app.model or app.model == "":
            self.controller.queryModel()

        # Check if version has been set and if not, query for it
        if not self.fw_version or self.fw_version == "":
            self.controller.queryVersion()

        self.machine_metadata_query_time = time.time()

    # -----------------------------------------------------------------------
    def open_comports_drop_down(self, button):
        """Show USB serial and vendor-class bulk devices; labels are the USB serial number."""
        self.comports_drop_down.clear_widgets()
        devices = Utils.list_identifiable_usb_devices()
        if not devices:
            btn = Button(
                text=tr._("No USB devices found"),
                size_hint_y=None,
                height="35dp",
                color=(180 / 255, 180 / 255, 180 / 255, 1),
            )
            self.comports_drop_down.add_widget(btn)
        else:
            for device in devices:
                btn = Button(text=device["label"], size_hint_y=None, height="35dp")
                btn.device_path = device["device_path"]
                btn.bind(on_release=lambda b: self.comports_drop_down.select(b.device_path))
                self.comports_drop_down.add_widget(btn)
        if Config.getboolean("carvera", "allow_manual_usb_device", fallback=False):
            btn = Button(
                text=tr._("Manually Enter"),
                size_hint_y=None,
                height="35dp",
                color=(225 / 255, 225 / 255, 225 / 255, 1),
            )
            btn.bind(on_release=lambda btn: self.manually_input_usb_device())
            self.comports_drop_down.add_widget(btn)
        self.comports_drop_down.unbind(on_select=self.usb_event)
        self.comports_drop_down.bind(on_select=self.usb_event)
        self.comports_drop_down.open(button)

    def manually_input_usb_device(self):
        self.input_popup.lb_title.text = tr._("Input USB device path:")
        saved = Config.get("carvera", "manual_usb_device", fallback="") or ""
        self.input_popup.txt_content.text = saved
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = self.manually_open_usb
        self.input_popup.open(self)
        self.comports_drop_down.dismiss()
        self.status_drop_down.dismiss()

    def manually_open_usb(self):
        device = self.input_popup.txt_content.text.strip()
        self.input_popup.dismiss()
        if not device:
            return False
        Config.set("carvera", "manual_usb_device", device)
        Config.write()
        self.openUSB(device)

    def open_spindle_or_laser_drop_down(self, button):
        if CNC.vars.get("lasermode", False):
            self.laser_drop_down.open(button)
            self.laser_drop_down.opened = True
        else:
            self.spindle_drop_down.open(button)
            self.spindle_drop_down.opened = True

    def fetch_common_local_dir_list(self):
        self.common_local_dir_list = Utils.common_local_directories()

    def fetch_recent_local_dir_list(self):
        self.recent_local_dir_list = Utils.load_recent_local_directories()

    def update_recent_local_dir_list(self, new_dir):
        self.recent_local_dir_list = Utils.update_recent_local_directory_list(
            self.recent_local_dir_list,
            new_dir,
        )
        Utils.persist_recent_local_directories(self.recent_local_dir_list)

    # -----------------------------------------------------------------------
    def open_local_dir_drop_down(self, button):
        if len(self.common_local_dir_list) == 0:
            self.fetch_common_local_dir_list()

        self.recent_local_dir_list = Utils.load_recent_local_directories(
            seed_if_empty=len(self.recent_local_dir_list) == 0,
        )

        Utils.fill_local_dir_dropdown(
            self.local_dir_drop_down,
            self.common_local_dir_list,
            self.recent_local_dir_list,
        )
        self.local_dir_drop_down.open(button)

    # -----------------------------------------------------------------------
    def fetch_recent_remote_dir_list(self):
        if Config.has_section("carvera"):
            for index in range(5):
                if Config.has_option("carvera", "remote_folder_" + str(index + 1)):
                    folder = Config.get("carvera", "remote_folder_" + str(index + 1))
                    if folder:
                        self.recent_remote_dir_list.append(folder)
            if len(self.recent_remote_dir_list) == 0:
                self.update_recent_remote_dir_list("/sd/gcodes")

    # -----------------------------------------------------------------------
    def update_recent_remote_dir_list(self, new_dir):
        if new_dir in self.recent_remote_dir_list:
            if self.recent_remote_dir_list[0] == new_dir:
                return
            self.recent_remote_dir_list.remove(new_dir)
        self.recent_remote_dir_list.insert(0, new_dir)
        del self.recent_remote_dir_list[5:]
        # save config
        for index in range(5):
            if index < len(self.recent_remote_dir_list):
                Config.set("carvera", "remote_folder_" + str(index + 1), self.recent_remote_dir_list[index])
            else:
                Config.set("carvera", "remote_folder_" + str(index + 1), "")
        Config.write()

    # -----------------------------------------------------------------------
    def open_remote_dir_drop_down(self, button):
        from carveracontroller.ui.DirectoryView import DirectoryView
        from carveracontroller.ui.DropDownSplitter import DropDownSplitter

        if len(self.recent_remote_dir_list) == 0:
            self.fetch_recent_remote_dir_list()

        self.remote_dir_drop_down.clear_widgets()

        splitter = DropDownSplitter(text="       " + tr._("Recent Places"))
        self.remote_dir_drop_down.add_widget(splitter)

        for recent_dir in self.recent_remote_dir_list:
            btn = DirectoryView(
                full_path=recent_dir,
                data_text=os.path.basename(recent_dir),
                data_icon="",
                size_hint_y=None,
                height="30dp",
            )
            btn.bind(on_release=lambda btn: self.remote_dir_drop_down.select(btn.full_path))
            self.remote_dir_drop_down.add_widget(btn)

        self.remote_dir_drop_down.open(button)

    # -----------------------------------------------------------------------
    def _remember_connection_method(self, method):
        """Persist the last successful connection method (wifi|usb)."""
        method = (method or "").lower()
        if method not in ("wifi", "usb"):
            return
        self.last_connection_method = method
        Config.set("carvera", "last_connection_method", method)
        Config.write()

    def _preferred_reconnect_method(self, for_app_launch=False):
        """
        App launch uses the configured preferred method.
        Otherwise prefer the last successful connection method.
        """
        if for_app_launch:
            return Config.get("carvera", "reconnect_method", fallback="wifi").lower()
        method = (
            self.last_connection_method or Config.get("carvera", "last_connection_method", fallback="") or ""
        ).lower()
        if method in ("wifi", "usb"):
            return method
        return Config.get("carvera", "reconnect_method", fallback="wifi").lower()

    def _store_usb_device_identity(self, device_id, serial=""):
        """Record VID:PID and preferred serial for reconnect."""
        if not device_id:
            return
        vid_pid, legacy_serial = Utils.parse_usb_device_id(device_id)
        if not vid_pid:
            return
        Config.set("carvera", "usb_device_id", vid_pid)
        Config.set("carvera", "usb_serial", (serial or legacy_serial or "").strip())
        Config.write()

    def _store_usb_device_id_for_path(self, device_path):
        for entry in Utils.list_identifiable_usb_devices():
            if Utils.same_usb_device_path(entry["device_path"], device_path):
                self._store_usb_device_identity(entry["device_id"], entry["serial"])
                return
        from carveracontroller.USBBulkStream import parse_usb_bulk_address

        parsed = parse_usb_bulk_address(device_path)
        if parsed:
            vid, pid, serial = parsed
            self._store_usb_device_identity(f"{vid:04X}:{pid:04X}", serial)

    def _resolve_usb_reconnect_path(self):
        """Resolve configured VID:PID (+ preferred serial) to a current OS path."""
        device_id = Config.get("carvera", "usb_device_id", fallback="") or ""
        serial = Config.get("carvera", "usb_serial", fallback="") or ""
        path = None
        if device_id or serial:
            path = Utils.find_usb_device_path_by_id(device_id or None, serial=serial)
        if path:
            return path
        # Fall back to last path only if that path still maps to an identifiable USB device.
        last_path = getattr(self.controller, "connection_address", None)
        if last_path:
            for entry in Utils.list_identifiable_usb_devices():
                if Utils.same_usb_device_path(entry["device_path"], last_path):
                    return entry["device_path"]
        return None

    def reconnect_last_connection(self, *args, quiet=False, for_app_launch=False):
        """Reconnect using preferred/last method (WiFi address or USB device id)."""
        method = self._preferred_reconnect_method(for_app_launch=for_app_launch)
        if method == "usb":
            path = self._resolve_usb_reconnect_path()
            if path:
                self.openUSB(path)
                return True
            if not quiet:
                Clock.schedule_once(
                    partial(
                        self.show_message_popup,
                        tr._("No matching USB device found. Connect once via USB... to record the serial number."),
                        False,
                    ),
                    0,
                )
            else:
                logger.info("Startup USB auto-connect skipped: no matching USB device for stored identity")
            return False

        # WiFi
        if self.past_machine_addr:
            if not self.machine_detector.is_machine_busy(self.past_machine_addr):
                self.openWIFI(self.past_machine_addr)
                return True
            if not quiet:
                Clock.schedule_once(
                    partial(self.show_message_popup, tr._("Cannot connect, machine is busy or not available."), False),
                    0,
                )
            return False
        if not quiet:
            Clock.schedule_once(
                partial(self.show_message_popup, tr._("No previous machine network address stored."), False), 0
            )
            self.manually_input_ip()
        return False

    # -----------------------------------------------------------------------
    def attempt_reconnect(self):
        """Attempt to reconnect to the last known connection"""
        if self.reconnection_popup._is_open:
            Clock.unschedule(self.reconnection_popup.countdown_tick)
            self.reconnection_popup.dismiss()
        self.reconnect_last_connection(quiet=False, for_app_launch=False)

    def on_reconnect_failed(self):
        """Called when all reconnection attempts have failed"""
        # Only show the message if we're actually disconnected and not in the process of connecting
        app = App.get_running_app()
        if app and app.state == NOT_CONNECTED and self.controller.stream is None:
            Clock.schedule_once(
                partial(self.show_message_popup, tr._("Auto-reconnection failed. Please connect manually."), False), 0
            )

    def on_reconnect_success(self):
        """Called when reconnection succeeds"""
        # Stop any ongoing reconnection attempts
        self.controller.cancel_reconnection()

    def open_wifi_conn_drop_down(self, button):
        self.wifi_conn_drop_down.clear_widgets()
        btn = MachineButton(
            text=tr._("Searching for nearby machines..."),
            size_hint_y=None,
            height="35dp",
            color=(180 / 255, 180 / 255, 180 / 255, 1),
        )
        self.wifi_conn_drop_down.add_widget(btn)
        self.wifi_conn_drop_down.open(button)
        self.machine_detector.query_for_machines()
        Clock.schedule_interval(self.load_machine_list, 0.1)

    def load_machine_list(self, *args):
        machines = self.machine_detector.check_for_responses()
        if machines is None:
            # the MachineDetector is still waiting for responses from machines
            return
        Clock.unschedule(self.load_machine_list)
        self.wifi_conn_drop_down.clear_widgets()
        if len(machines) == 0:
            btn = MachineButton(
                text=tr._("None found, enter address manually..."),
                size_hint_y=None,
                height="35dp",
                color=(225 / 255, 225 / 255, 225 / 255, 1),
            )
            btn.bind(on_release=lambda btn: self.manually_input_ip())
            self.wifi_conn_drop_down.add_widget(btn)
        else:
            for machine in machines:
                btn = MachineButton(
                    text=machine["machine"] + ("(Busy)" if machine["busy"] else ""),
                    ip=machine["ip"],
                    port=machine["port"],
                    size_hint_y=None,
                    height="35dp",
                )
                btn.bind(on_release=lambda btn: self.wifi_conn_drop_down.select(btn.ip + ":" + str(btn.port)))
                self.wifi_conn_drop_down.add_widget(btn)
                self.wifi_conn_drop_down.unbind(on_select=self.wifi_event)
                self.wifi_conn_drop_down.bind(on_select=self.wifi_event)

    # -----------------------------------------------------------------------
    def manually_input_ip(self):
        self.input_popup.lb_title.text = tr._("Input machine network address:")
        # Prefer the in-memory value; fall back to the saved config address.
        saved = self.past_machine_addr
        if not saved and Config.has_option("carvera", "address"):
            saved = Config.get("carvera", "address")
            self.past_machine_addr = saved
        self.input_popup.txt_content.text = saved or ""
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = self.manually_open_wifi
        self.input_popup.open(self)
        self.wifi_conn_drop_down.dismiss()
        self.status_drop_down.dismiss()

    def manually_open_wifi(self):
        ip = self.input_popup.txt_content.text.strip()
        self.input_popup.dismiss()
        if not ip:
            return False
        self.store_machine_address(ip)
        self.openWIFI(ip)

    def store_machine_address(self, address):
        Config.set("carvera", "address", address)
        Config.write()
        self.past_machine_addr = address

    def manually_input_ssid(self):
        self.manual_wifi_popup.lb_title1.text = tr._("Input Wi-Fi network name (SSID):")
        self.manual_wifi_popup.lb_title2.text = tr._("Input Wi-Fi password (leave blank if open network):")
        self.manual_wifi_popup.txt_content1.password = False
        self.manual_wifi_popup.txt_content2.password = True
        self.manual_wifi_popup.confirm = self.manually_open_ssid
        self.manual_wifi_popup.open(self)
        self.wifi_ap_drop_down.dismiss()
        self.status_drop_down.dismiss()

    def manually_open_ssid(self):
        ssid = self.manual_wifi_popup.txt_content1.text.strip()
        password = self.manual_wifi_popup.txt_content2.text.strip()
        self.manual_wifi_popup.dismiss()
        if not ssid:
            return False
        self.input_popup.cache_var1 = ssid
        self.input_popup.txt_content.text = password
        self.connectToWiFi()

    # -----------------------------------------------------------------------
    def update_coord_config(self):
        self.wpb_margin.width = 50 if self.coord_config["margin"]["active"] else 0
        self.wpb_zprobe.width = 50 if self.coord_config["zprobe"]["active"] else 0
        self.wpb_leveling.width = 50 if self.coord_config["leveling"]["active"] else 0

    # -----------------------------------------------------------------------
    # Inner loop to catch any generic exception
    # -----------------------------------------------------------------------
    def monitorSerial(self):
        while not self.stop.is_set():
            t = time.time()

            while self.controller.log.qsize() > 0:
                try:
                    msg, line = self.controller.log.get_nowait()
                    line = line.rstrip("\n")
                    line = line.rstrip("\r")
                    dispatch_serial_line(msg, line)

                    remote_time = re.search("time = [0-9]+", line)
                    if remote_time != None:
                        if abs(Utils.local_unix_time() - int(remote_time[0].split("=")[1])) > 10:
                            self.controller.syncTime()

                    remote_version = re.search(r"version = [0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9\-_]*", line)
                    app = App.get_running_app()
                    if remote_version != None:
                        self.fw_version = remote_version[0].split("=")[1].strip()
                        app.is_community_firmware = bool(self.fw_version) and "c" in self.fw_version.lower()
                        self.controller.is_community_firmware = app.is_community_firmware
                        if not app.is_community_firmware or not CNC.can_rotate_wcs:
                            self.controller.viewWCS()
                        app.fw_version_digitized = Utils.digitize_v(self.fw_version)
                        logger.debug(f"Firmware Version detected as {self.fw_version}")
                        Clock.schedule_once(partial(self.onFirmwareDetected, self.fw_version), 0)
                        if self.fw_version_new != "":
                            self.check_fw_version()
                        # Baud upgrade is deferred until after config download / sync
                        # (see attempt_usb_baud_upgrade_if_eligible). Running it on the
                        # version line races framed config transfer and breaks the link.

                    remote_model = re.search(r"model = (\w+), (\d+), (\d+), (\d+)", line)
                    if remote_model != None:
                        detected_model = remote_model.group(1)
                        CNC.vars["MachineModel"] = int(remote_model.group(2))
                        CNC.vars["FuncSetting"] = int(remote_model.group(3))
                        logger.info(
                            f"Machine information: "
                            f"Model: {detected_model}, "
                            f"Model ID: {CNC.vars['MachineModel']}, "
                            f"FuncSetting: {CNC.vars['FuncSetting']}, "
                            f"Extra: {remote_model.group(4)}"
                        )
                        Clock.schedule_once(partial(self.setUIForModel, detected_model), 0)

                    remote_filetype = re.search("ftype = [a-zA-Z0-9]+", line)
                    if remote_filetype != None:
                        self.filetype = remote_filetype[0].split("=")[1]

                    remote_decompercent = re.search("decompart = [0-9.]+", line)
                    if remote_decompercent != None:
                        self.decompercent = int(remote_decompercent[0].split("=")[1])

                    # handle specific messages
                    if "WP PAIR SUCCESS" in line:
                        self.pairing_popup.pairing_success = True

                    # Framed MD5-match short-circuit uses FILE_CAN; firmware labels that as
                    # "canceled by Controller" even though the transfer succeeded via cache.
                    if "canceled by Controller" in line:
                        logger.debug("MDI Received (transfer short-circuit): %s", line)
                        continue

                    if msg == Controller.MSG_NORMAL:
                        logger.info(f"MDI Received: {line}")
                        entry = {
                            "text": line,
                            "color": (103 / 255, 150 / 255, 186 / 255, 1),
                            "entry_type": "output",
                        }
                        self._append_to_mdi([entry], log_to_mdi_data=line not in [" ", "ok", "Done ATC"])
                    elif msg == Controller.MSG_ERROR:
                        logger.error(f"MDI Received: {line}")
                        entry = {
                            "text": line,
                            "color": (250 / 255, 105 / 255, 102 / 255, 1),
                            "entry_type": "output",
                        }
                        self._append_to_mdi([entry], log_to_mdi_data=line not in [" ", "ok", "Done ATC"])
                except:
                    logger.error(sys.exc_info()[1])
                    break
            # Update Decompress status bar
            if self.decompstatus == True:
                if self.decompercent != self.decompercentlast:
                    self.updateCompressProgress(self.decompercent)
                    self.decompercentlast = self.decompercent
                    self.decomptime = time.time()
                else:
                    t = time.time()
                    if t - self.decomptime > 8:
                        self.updateCompressProgress(self.fileCompressionBlocks)

            # Update position if needed
            if self.controller.posUpdate:
                Clock.schedule_once(self.updateStatus, 0)
                self.controller.posUpdate = False

            # change diagnose status
            self.controller.diagnosing = self.diagnose_popup.showing
            # update diagnose if needed
            if self.controller.diagnoseUpdate:
                Clock.schedule_once(self.updateDiagnose, 0)
                Clock.schedule_once(self._apply_estop_note_to_halt_popup, 0)
                self.controller.diagnoseUpdate = False

            if self.controller.loadNUM == LOAD_DIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(
                            partial(self.loadError, tr._("Error loading dir") + " '%s'!" % (self.loading_dir)), 0
                        )
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(
                            partial(self.loadError, tr._("Timeout loading dir") + " '%s'!" % (self.loading_dir)), 0
                        )
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    self.process_loaded_dir(self.fill_remote_dir)
            if self.controller.loadNUM == LOAD_RM:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    deleting_file = getattr(self, "deleting_remote_file", self.file_popup.remote_rv.curr_selected_file)
                    delete_failed = self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT
                    if self.controller.loadERR:
                        Clock.schedule_once(
                            partial(self.loadError, tr._("Error deleting") + " '%s'!" % (deleting_file)), 0
                        )
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(
                            partial(self.loadError, tr._("Timeout deleting") + "'%s'!" % (deleting_file)), 0
                        )
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    if not delete_failed and getattr(self, "pending_remote_delete_files", []):
                        Clock.schedule_once(self.removeNextRemoteFile, 0)
                    else:
                        self.pending_remote_delete_files = []
                        self.deleting_remote_file = ""
                        Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MV:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(
                            partial(
                                self.loadError,
                                tr._("Error renaming") + " '%s'!" % (self.file_popup.remote_rv.curr_selected_file),
                            ),
                            0,
                        )
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(
                            partial(
                                self.loadError,
                                tr._("Timeout renaming") + " '%s'!" % (self.file_popup.remote_rv.curr_selected_file),
                            ),
                            0,
                        )
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MKDIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(
                            partial(
                                self.loadError,
                                tr._("Error making dir:") + " '%s'!" % (self.input_popup.txt_content.text.strip()),
                            ),
                            0,
                        )
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(
                            partial(
                                self.loadError,
                                tr._("Timeout making dir:") + " '%s'!" % (self.input_popup.txt_content.text.strip()),
                            ),
                            0,
                        )
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadWiFiError, tr._("Error getting WiFi info!")), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadWiFiError, tr._("Timeout getting WiFi info!")), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadWiFi, 0)
            if self.controller.loadNUM == LOAD_CONN_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadConnWiFiError, ""), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadConnWiFiError, tr._("Timeout connecting WiFi!")), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadConnWiFi, 0)

            time.sleep(0.1)

    # -----------------------------------------------------------------------
    def open_del_confirm_popup(self):
        selected_files = self.file_popup.remote_rv.get_selected_files()
        if not selected_files:
            return
        self.confirm_popup.lb_title.text = tr._("Delete File or Dir")
        if len(selected_files) == 1:
            self.confirm_popup.lb_content.text = tr._("Confirm to delete file or dir") + "'%s'?" % (selected_files[0])
            self.confirm_popup.confirm = partial(self.removeRemoteFile, selected_files[0])
        else:
            preview = "\n".join(selected_files[:5])
            if len(selected_files) > 5:
                preview += "\n..."
            self.confirm_popup.lb_content.text = tr._("Confirm to delete %d selected files or dirs?") % len(
                selected_files
            )
            self.confirm_popup.lb_content.text += "\n\n%s" % preview
            self.confirm_popup.confirm = partial(self.removeRemoteFiles, selected_files)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_halt_confirm_popup(self):
        app = App.get_running_app()

        # If playback was interrupted by halt, update resume at line with last executed line
        # Use playedlines if available, otherwise use the last tracked played_lines
        last_line = CNC.vars["playedlines"] if CNC.vars["playedlines"] > 0 else self.played_lines
        if last_line > 0:
            self.update_resume_at_line_from_played_line(
                last_line, play_percent_from_line(last_line, self.selected_file_line_count)
            )

        alarm_msg = CNC.vars.get("alarm_message", "")

        # Use UnlockPopup for halt_reason < 20 (machine doesn't require reset, only unlock)
        if CNC.vars["halt_reason"] < 20:
            if self.unlock_popup.showing:
                return

            if CNC.vars["halt_reason"] in HALT_REASON:
                self.unlock_popup.lb_title.text = (
                    tr._("Machine Is Halted: ") + "%s" % (HALT_REASON[CNC.vars["halt_reason"]])
                )
            else:
                self.unlock_popup.lb_title.text = tr._("Machine Is Halted!")

            if alarm_msg:
                self.unlock_popup.lb_content.text = alarm_msg
            else:
                self.unlock_popup.lb_content.text = tr._("Choose unlock option:")

            self.unlock_popup.unlock_stay = partial(self.unlockMachine)
            self.unlock_popup.unlock_safe_z = partial(self.unlockMachineAndMoveToSafeZ)
            self.unlock_popup.open(self)
            self._request_halt_estop_note()
            return

        # Use ConfirmPopup for halt_reason >= 20 (machine requires reset)
        if self.confirm_popup.showing:
            return

        if CNC.vars["halt_reason"] in HALT_REASON:
            self.confirm_popup.lb_title.text = (
                tr._("Machine Is Halted: ") + "%s" % (HALT_REASON[CNC.vars["halt_reason"]])
            )
        else:
            self.confirm_popup.lb_title.text = tr._("Machine Is Halted!")

        self.confirm_popup.cancel = None
        if CNC.vars["halt_reason"] > 40:
            action_text = tr._("Please manually switch off/on the machine!")
            self.confirm_popup.confirm = partial(self.resetMachine)
        elif CNC.vars["halt_reason"] > 20:
            action_text = tr._("Confirm to reset machine?")
            self.confirm_popup.confirm = partial(self.resetMachine)
        else:
            action_text = tr._("Confirm to unlock machine?")
            self.confirm_popup.confirm = partial(self.unlockMachine)

        if alarm_msg:
            self.confirm_popup.lb_content.text = alarm_msg + "\n" + action_text
        else:
            self.confirm_popup.lb_content.text = action_text

        self.confirm_popup.open(self)
        self._request_halt_estop_note()

    # -----------------------------------------------------------------------
    def _request_halt_estop_note(self):
        # Wait for diagnoseUpdate to apply
        self.controller.viewDiagnoseReport(True)

    # -----------------------------------------------------------------------
    def _apply_estop_note_to_halt_popup(self, *args):
        app = App.get_running_app()
        if app is None or app.state != "Alarm":
            return

        # Check if one of the two popups is opened
        if getattr(self.unlock_popup, "_is_open", False) or getattr(self.unlock_popup, "showing", False):
            popup = self.unlock_popup
        elif getattr(self.confirm_popup, "_is_open", False) or getattr(self.confirm_popup, "showing", False):
            popup = self.confirm_popup
        else:
            return

        title = popup.lb_title.text
        if not title or not (
            title.startswith(tr._("Machine Is Halted: ")) or title.startswith(tr._("Machine Is Halted!"))
        ):
            return

        note = tr._(
            "The emergency stop is engaged and may be the cause of this alarm. "
            "Disengage it before clearing the alarm or resetting the machine."
        )
        body = popup.lb_content.text or ""
        if body == note:
            base = ""
        elif body.startswith(note + "\n\n"):
            base = body[len(note) + 2 :]
        else:
            base = body

        show_note = CNC.vars.get("st_e_stop", 0) and CNC.vars["halt_reason"] != HALT_REASON_ESTOP
        if show_note:
            popup.lb_content.text = note if not base else note + "\n\n" + base
        else:
            popup.lb_content.text = base

    # -----------------------------------------------------------------------
    def open_sleep_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        self.confirm_popup.lb_title.text = tr._("Machine Is Sleeping")
        self.confirm_popup.lb_content.text = tr._("Confirm to reset machine?")
        self.confirm_popup.cancel = None
        self.confirm_popup.confirm = partial(self.resetMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def _format_target_tool_text(self):
        """Return display text for the tool being requested in a tool-change popup."""
        tool_number = CNC.vars["target_tool"]
        if tool_number == ZPROBE_TOOL_NUMBER:
            return "Probe"
        if tool_number == LASER_TOOL_NUMBER:
            return "Laser"
        if tool_number == PROBE_3D_TOOL_NUMBER:
            return "3D Probe"
        if is_probe_tools_range(tool_number):
            return "Custom Probe"

        tool_def = self.tool_table.get(tool_number)
        tooltip = format_tool_tooltip(tool_def, markup=False, unit=self.document_unit) if tool_def else ""
        return tooltip if tooltip else str(tool_number)

    # -----------------------------------------------------------------------
    def open_tool_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        target_tool = self._format_target_tool_text()
        target_collet_type = CNC.vars["target_collet_type"]
        target_collet_type_text = ["Undefined", "3mm", '1/8"', "4mm", "6mm", '1/4"', "8mm"]

        app = App.get_running_app()
        if app.has_atc:
            # target is valid tool
            if CNC.vars["target_tool"] != -1:
                if CNC.vars["tool"] == -1:
                    if target_collet_type == 0:
                        self.confirm_popup.lb_title.text = tr._("Manual toolchange")
                        self.confirm_popup.lb_content.text = (
                            tr._("Insert tool: ")
                            + "%s\n\n" % (target_tool)
                            + tr._("Then press ' Confirm' or main button to clamp.\n")
                        )
                    else:
                        self.confirm_popup.lb_title.text = tr._("Manual toolchange")
                        self.confirm_popup.lb_content.text = (
                            tr._("Change to collet: ")
                            + "%s\n" % (target_collet_type_text[target_collet_type])
                            + tr._("Insert tool: ")
                            + "%s\n" % (target_tool)
                            + tr._("Then press ' Confirm' or main button to clamp.\n")
                        )
                else:
                    self.confirm_popup.lb_title.text = tr._("Manual toolchange")
                    self.confirm_popup.lb_content.text = tr._(
                        "When the tool is clamped press ' Confirm' or main button to proceed.\nKeep your hands off the spindle unless you are willing to lose a finger!"
                    )
            else:
                if CNC.vars["tool"] != -1:
                    self.confirm_popup.lb_title.text = tr._("Hold tool")
                    self.confirm_popup.lb_content.text = tr._(
                        "Please hold the current tool and press ' Confirm' or main button to proceed"
                    )
                else:
                    if target_collet_type == 0:
                        self.confirm_popup.lb_title.text = tr._("Confirm empty")
                        self.confirm_popup.lb_content.text = tr._(
                            "When the collet is empty press ' Confirm' or main button to proceed"
                        )
                    else:
                        self.confirm_popup.lb_title.text = tr._("Confirm empty")
                        self.confirm_popup.lb_content.text = (
                            tr._("Change to collet: ")
                            + "%s\n" % (target_collet_type_text[target_collet_type])
                            + tr._("When the collet is changed and empty press ' Confirm' or main button to proceed")
                        )
        else:
            self.confirm_popup.lb_title.text = tr._("Changing Tool")
            self.confirm_popup.lb_content.text = (
                tr._("Please change to tool: ")
                + "%s\n" % (target_tool)
                + tr._("Then press ' Confirm' or main button to proceed")
            )

        self.confirm_popup.cancel = partial(self.controller.abortCommand)
        self.confirm_popup.confirm = partial(self.changeTool)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def resetMachine(self):
        self.controller.reset()

    # -----------------------------------------------------------------------
    def changeTool(self):
        self.controller.change()

    # -----------------------------------------------------------------------
    def unlockMachine(self):
        self.controller.unlock()

    def unlockMachineAndMoveToSafeZ(self):
        self.controller.unlock()
        self.controller.gotoSafeZ()

    # -----------------------------------------------------------------------
    def set_local_folder_to_last_opened(self):
        self.fetch_recent_local_dir_list()

        # Find the most recent directory that is still present
        local_path = ""
        for dir in self.recent_local_dir_list:
            if os.path.isdir(dir):
                local_path = dir
                break

        self.file_popup.local_rv.child_dir(local_path)

    def open_rename_input_popup(self):
        self.input_popup.lb_title.text = tr._("Change name") + "'%s' to:" % (
            self.file_popup.remote_rv.curr_selected_file
        )
        self.input_popup.txt_content.text = ""
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = partial(self.renameRemoteFile, self.file_popup.remote_rv.curr_selected_file)
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_newfolder_input_popup(self):
        self.input_popup.lb_title.text = tr._("Input new folder name:")
        self.input_popup.txt_content.text = ""
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = self.createRemoteDir
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_upload_local_file_popup(self):
        # For iOS we use the native file picker
        if sys.platform == "ios":
            from . import ios_helpers

            ios_helpers.pick_file()
            return
        self.file_popup.firmware_mode = False
        self.file_popup.popup_manager.transition.direction = "left"
        self.file_popup.popup_manager.transition.duration = 0.3
        self.file_popup.popup_manager.current = "local_page"
        self.set_local_folder_to_last_opened()

    # -----------------------------------------------------------------------
    def open_wifi_password_input_popup(self):
        self.input_popup.lb_title.text = tr._("Input WiFi password of") + " %s:" % self.input_popup.cache_var1
        self.input_popup.txt_content.text = ""
        self.input_popup.txt_content.password = True
        self.input_popup.confirm = self.connectToWiFi
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def check_and_upload(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        filename = os.path.basename(os.path.normpath(filepath))
        if len(list(filter(lambda person: person["filename"] == filename, self.file_popup.remote_rv.data))) > 0:
            # show message popup
            self.confirm_popup.lb_title.text = tr._("File Already Exists")
            self.confirm_popup.lb_content.text = tr._("Confirm to overwrite file:") + " \n '%s'?" % (filename)
            self.confirm_popup.cancel = None
            self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath)
            self.confirm_popup.open(self)
        else:
            if self.file_popup.firmware_mode:
                # show message popup
                self.confirm_popup.lb_title.text = tr._("Updating Firmware")
                self.confirm_popup.lb_content.text = tr._(
                    "Are you sure you want to update the firmware? A machine reset will be required to apply the new firmware."
                )
                self.confirm_popup.cancel = None
                self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath)
                self.confirm_popup.open(self)
            else:
                self.uploadLocalFile(filepath)

    def select_file(self, remote_path, local_cached_file_path):
        """Select a file that is already present both locally and remotely"""
        app = App.get_running_app()
        app.selected_local_filename = local_cached_file_path
        app.selected_remote_filename = remote_path

        Clock.schedule_once(partial(self._select_file_ui_update, remote_path, local_cached_file_path), 0)

    def _select_file_ui_update(self, remote_path, local_cached_file_path, *args):
        """Update UI elements on main thread"""
        app = App.get_running_app()
        self.wpb_play.value = 0

        Clock.schedule_once(
            partial(self.progressUpdate, 0, tr._("Loading file") + " \n%s" % app.selected_local_filename, True), 0
        )

        # Run load_gcode_file in background thread to avoid blocking UI, especially during decompression
        # Add a small delay to ensure file is ready, especially when called during decompression
        def load_file_delayed(dt):
            if os.path.exists(local_cached_file_path) and os.access(local_cached_file_path, os.R_OK):
                threading.Thread(target=self.load_gcode_file, args=(local_cached_file_path,), daemon=True).start()
            else:
                # Retry after a short delay if file is not ready
                Clock.schedule_once(load_file_delayed, 0.2)

        Clock.schedule_once(load_file_delayed, 0.1)

    def check_upload_and_select(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        filename = os.path.basename(os.path.normpath(filepath))
        if len(list(filter(lambda person: person["filename"] == filename, self.file_popup.remote_rv.data))) > 0:
            # show message popup
            self.confirm_popup.lb_title.text = tr._("File Already Exists")
            self.confirm_popup.lb_content.text = tr._("Confirm to overwrite file:") + " \n '%s'?" % (filename)
            self.confirm_popup.cancel = None
            self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath, self.select_file)
            self.confirm_popup.open(self)
        else:
            self.uploadLocalFile(filepath, self.select_file)

    # -----------------------------------------------------------------------
    def view_local_file(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        app = App.get_running_app()
        app.selected_local_filename = filepath
        app.selected_remote_filename = ""

        self.file_popup.dismiss()

        self.progress_popup.progress_value = 0
        self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.progress_text = tr._("Opening local file") + "\n%s" % filepath
        self.progress_popup.open()

        threading.Thread(target=self.load_gcode_file, args=(filepath,), daemon=True).start()
        # Clock.schedule_once(partial(self.load_gcode_file, filepath), 0)

    # -----------------------------------------------------------------------
    def check_and_download(self):
        remote_path = self.file_popup.remote_rv.curr_selected_file
        remote_size = self.file_popup.remote_rv.curr_selected_filesize
        remote_post_path = remote_path.replace("/sd/", "").replace("\\sd\\", "")
        local_path = os.path.join(self.temp_dir, remote_post_path)
        app = App.get_running_app()
        app.selected_local_filename = local_path
        app.selected_remote_filename = remote_path
        self.wpb_play.value = 0

        self.downloading_file = remote_path
        self.downloading_size = remote_size
        self.downloading_config = False
        threading.Thread(target=self.doDownload, args=(remote_path, local_path)).start()

    # -----------------------------------------------------------------------
    def start_back_up_config(self):
        # Workaround for the fact that backup isn't a proper setting. If we don't clear it, the
        # settings panel will show a selected value like "Back up files now" and won't allow
        # another backup to run until the controller is restarted.
        for panel in self.config_popup.settings_panel.interface.content.panels.values():
            for item in panel.children:
                if (
                    hasattr(item, "section")
                    and item.section == "Backup"
                    and hasattr(item, "key")
                    and item.key == "backup"
                ):
                    item.value = ""

        self.downloading_config = True
        Clock.schedule_once(partial(self.progressStart, tr._("Downloading config files..."), None), 0)

        self.fill_remote_dir_callback = self.download_config_files
        self.file_popup.remote_rv.list_dir("/sd")

    # -----------------------------------------------------------------------
    def download_config_files(self, remote_paths):
        matching_paths = []
        for file_info in remote_paths:
            if file_info["path"] in CONFIG_FILES_TO_BACK_UP:
                logger.debug(f"Found matching config file: {file_info['path']}")
                matching_paths.append(file_info["path"])

        local_paths = []
        progress = 0.0
        for remote_path in matching_paths:
            local_path = os.path.join(self.temp_dir, os.path.basename(remote_path))
            local_paths.append(local_path)
            logger.debug(f"Downloading config file {remote_path} to {local_path}")
            Clock.schedule_once(
                partial(self.progressUpdate, progress, tr._("Downloading") + " \n%s" % remote_path, True), 0
            )
            self.doDownload(remote_path, local_path, False)
            progress += 100.0 / len(matching_paths)
            Clock.schedule_once(
                partial(self.progressUpdate, progress, tr._("Downloading") + " \n%s" % remote_path, True), 0
            )

            # Delay to avoid breaking communication with the machine
            time.sleep(1.5)

        Clock.schedule_once(partial(self.choose_back_up_config_destination, local_paths), 0)

    # -----------------------------------------------------------------------
    def choose_back_up_config_destination(self, local_paths, *args):
        self.progressFinish()
        content = PickFilePopup(partial(self.finish_backing_up_config, local_paths))
        self.pick_file_popup = Popup(
            title="Choose where to back up your machine configuration",
            content=content,
            size_hint=(0.75, 0.75),
            auto_dismiss=True,
        )
        content.on_cancel = self.pick_file_popup.dismiss
        self.pick_file_popup.open()

    # -----------------------------------------------------------------------
    def finish_backing_up_config(self, downloaded_file_paths, selected_dir, _selected_file):
        for source_file_path in downloaded_file_paths:
            dest_file_path = os.path.join(selected_dir, os.path.basename(source_file_path))
            try:
                shutil.copyfile(source_file_path, dest_file_path)
            except Exception as e:
                Clock.schedule_once(
                    partial(
                        self.show_message_popup,
                        tr._(f"Couldn't back up '{source_file_path}'. The error was:\n\n{e}"),
                        False,
                    ),
                    0,
                )
                print("Error backing up config file:", e)

        self.pick_file_popup.dismiss()
        self.pick_file_popup = None
        self.downloading_config = False

        # Workaround so that we don't expose the SD card root directory to the user
        # next time they open the gcode file browser
        self.file_popup.remote_rv.curr_dir = self.file_popup.remote_rv.base_dir

        Clock.schedule_once(
            partial(self.show_message_popup, tr._("Configuration files backed up successfully"), False), 0
        )

    # -----------------------------------------------------------------------
    def download_config_file(self):
        self.downloading_size = 1024 * 5
        self.downloading_config = True
        remote_path = "/sd/config.txt"
        self.downloading_file = remote_path
        local_path = self._machine_config_cache_path()
        threading.Thread(target=self.doDownload, args=(remote_path, local_path)).start()

    # -----------------------------------------------------------------------
    def finishLoadConfig(self, success, *args):
        self.downloading_config = False
        if success:
            try:
                self.setting_list.clear()
                self.load_machine_config_defaults()
                # caching config file
                config_path = self._machine_config_cache_path()
                if not os.path.exists(config_path):
                    raise FileNotFoundError(f"Cached config not found: {config_path}")
                with open(config_path) as f:
                    config_string = "[dummy_section]\n" + f.read()
                # remove notes
                config_string = re.sub(r"#.*", "", config_string)
                # replace spaces to =
                config_string = re.sub(r"([a-zA-Z])( |\t)+([a-zA-Z0-9-])", r"\1=\3", config_string)

                setting_config = ConfigParser(allow_no_value=True)
                setting_config.read_string(config_string)
                for section_name in setting_config.sections():
                    for key, value in setting_config.items(section_name):
                        try:
                            self.setting_list[key.strip()] = value.strip()
                        except AttributeError:
                            Clock.schedule_once(
                                partial(
                                    self.load_error,
                                    tr._(
                                        "Error loading machine config setting. Possibly malformed value.\nSkipping setting key: "
                                    )
                                    + str(key),
                                ),
                                0,
                            )

                self.load_coordinates()
                self.load_laser_offsets()
                self.setting_change_list = {}

                self.config_loaded = self.load_machine_config()
                self._config_download_failures = 0
                if not self.config_loaded:
                    # Applying settings failed; retrying the download cannot fix panel/schema mismatches.
                    self._config_apply_failed = True
                self.config_popup.btn_apply.disabled = len(self.setting_change_list) == 0
                if getattr(self.gcode_viewer, "high_precision_time_estimate", False) and (
                    self.gcode_viewer.raw_linenumbers and self.gcode_viewer.raw_feed_rates
                ):
                    self.gcode_viewer._compute_line_times_async(show_progress=False)
            except Exception as e:
                logger.exception("Failed to load machine config")
                self.config_loaded = False
                self._config_apply_failed = True
                self.controller.log.put((Controller.MSG_ERROR, tr._("Failed to load config file: {}").format(e)))
            finally:
                self.config_loading = False
        else:
            self.config_loading = False
            self._config_download_failures += 1
            self.controller.log.put((Controller.MSG_ERROR, tr._("Download config file error")))
            if self._config_download_failures >= MAX_CONFIG_DOWNLOAD_ATTEMPTS:
                logger.error(
                    "Giving up config download after %s failed attempts",
                    self._config_download_failures,
                )
            # self.controller.close()

        # Preserve selected file only when reconnecting to the same machine.
        # finishLoadConfig() can be called on reconnect; resume-at-line depends on
        # loaded self.lines matching selection (_last_loaded_file_key). If the user
        # connects to a different machine (different IP/COM port), clear machine selection.
        app = App.get_running_app()
        current_key = self._get_current_machine_connection_key()
        if self._selected_file_machine_key is None:
            self._selected_file_machine_key = current_key
        elif current_key != self._selected_file_machine_key:
            app.selected_local_filename = ""
            app.selected_remote_filename = ""
            self._last_loaded_file_key = None
            self._selected_file_machine_key = current_key
            self.apply_bed_settings()
        self.updateStatus()

    def _get_current_machine_connection_key(self):
        """Return a stable identifier for the current machine connection."""
        try:
            conn_type = self.controller.connection_type
        except Exception:
            return None

        addr = None
        try:
            addr = self.controller.connection_address
        except Exception:
            addr = None

        if conn_type == CONN_WIFI:
            return f"wifi:{addr}" if addr else "wifi"
        if conn_type == CONN_USB:
            return f"usb:{addr}" if addr else "usb"
        return str(conn_type)

    def _machine_config_cache_path(self):
        """Return a per-machine path for the cached /sd/config.txt copy."""
        key = self._get_current_machine_connection_key() or "unknown"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key))
        return os.path.join(self.temp_dir, f"config_{safe}.txt")

    # -----------------------------------------------------------------------
    def doDownload(self, remote_path, local_path, show_progress=True):
        app = App.get_running_app()
        was_config_download = self.downloading_config
        if not self.downloading_config and not os.path.exists(os.path.dirname(local_path)):
            # os.mkdir(os.path.dirname(local_path))
            os.makedirs(os.path.dirname(local_path))
        tmp_filename = local_path + ".tmp"
        # Only use a temp file for MD5 skip when it is a copy of the real local file.
        # Orphan .tmp leftovers must not suppress a real download.
        if os.path.exists(local_path):
            shutil.copyfile(local_path, tmp_filename)
        elif os.path.exists(tmp_filename):
            try:
                os.remove(tmp_filename)
            except OSError:
                pass

        if show_progress:
            Clock.schedule_once(
                partial(
                    self.progressStart,
                    tr._("Load config...") if self.downloading_config else (tr._("Checking") + " \n%s" % local_path),
                    None if self.downloading_config else self.cancelProcessingFile,
                ),
                0,
            )
        self.downloading = True
        # None = error/abort; never use False — `False >= 0` is True in Python.
        download_result = None
        try:
            md5 = Utils.md5(tmp_filename) if os.path.exists(tmp_filename) else ""
            # Makera framed transfer: pause RX before the download command so
            # streamIO cannot steal the MD5 / file frames from XMODEM.
            # Smoothie/XMODEM legacy: send first, then pause (OEM timing).
            if self.controller.comms.uses_framed_transfer:
                self.controller.pauseStream(0.0)
                self.controller.downloadCommand(remote_path)
                progress_cb = self.downloadCallback_framed if show_progress else None
            else:
                self.controller.downloadCommand(remote_path)
                self.controller.pauseStream(0.2)
                progress_cb = partial(self.downloadCallback, remote_path) if show_progress else None
            download_result = self.controller.stream.download(tmp_filename, md5, progress_cb)
        except Exception:
            logger.error(sys.exc_info()[1])
            download_result = None
            self.controller.resumeStream()
            self.downloading = False

        self.controller.resumeStream()
        self.downloading = False

        self.heartbeat_time = time.time()

        if download_result is None:
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)
            # show message popup
            md5_failed = bool(
                getattr(getattr(getattr(self.controller, "stream", None), "modem", None), "download_md5_failed", False)
            )
            if was_config_download:
                Clock.schedule_once(partial(self.finishLoadConfig, False), 0.1)
                error_msg = (
                    tr._(
                        "Download config file error! The file MD5 hash doesn't match what is expected. "
                        "Possibly corruption occured during transfer or on SD card."
                    )
                    if md5_failed
                    else tr._("Download config file error!")
                )
                Clock.schedule_once(partial(self.show_message_popup, error_msg, False), 0.2)
            else:
                error_msg = (
                    tr._(
                        "Download file error! MD5 hash doesn't match what is expected. "
                        "Possible corruption during transfer or on SD card."
                    )
                    if md5_failed
                    else tr._("Download file error!")
                )
                Clock.schedule_once(partial(self.show_message_popup, error_msg, False), 0)
        elif download_result >= 0:
            if download_result > 0:
                # download success
                if os.path.exists(local_path):
                    os.remove(local_path)
                os.rename(tmp_filename, local_path)
            else:
                # MD5 matched: firmware reports "Download canceled by Controller!" for this
                # intentional FILE_CAN; keep/promote the local cache instead of re-fetching.
                if not os.path.exists(local_path) and os.path.exists(tmp_filename):
                    os.rename(tmp_filename, local_path)
                elif os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
                if was_config_download:
                    logger.info("Config unchanged (MD5 match), using cached file")
                    self.controller.log.put(
                        (Controller.MSG_NORMAL, tr._("Config unchanged (MD5 match), using cached file"))
                    )
            if was_config_download:
                if show_progress:
                    Clock.schedule_once(partial(self.progressUpdate, 100, "", True), 0)
                Clock.schedule_once(partial(self.finishLoadConfig, True), 0.1)

                if show_progress:
                    Clock.schedule_once(
                        partial(self.progressUpdate, 100, tr._("Synchronize version and time..."), True), 0
                    )
                Clock.schedule_once(self.controller.queryTime, 0.1)
                if app is None or not app.model:
                    Clock.schedule_once(self.controller.queryModel, 0.2)
                if not self.fw_version:
                    Clock.schedule_once(self.controller.queryVersion, 0.3)
                self.filetype = ""
                Clock.schedule_once(self.controller.queryFtype, 0.4)
                # Schedule a one off diagnostic command to get the machine's extended state
                Clock.schedule_once(self.controller.viewDiagnoseReport, 0.5)
                # Baud upgrade after config + sync commands have had time to finish.
                Clock.schedule_once(self.attempt_usb_baud_upgrade_if_eligible, 2.0)
            else:
                if show_progress:
                    Clock.schedule_once(
                        partial(self.progressUpdate, 0, tr._("Open cached file") + " \n%s" % local_path, True), 0
                    )
                # Clock.schedule_once(partial(self.load_gcode_file, local_path), 0.1)
                self.load_gcode_file(local_path)

            if not was_config_download:
                self.update_recent_remote_dir_list(os.path.dirname(remote_path))

        elif download_result < 0:
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)
            self.controller.log.put((Controller.MSG_NORMAL, tr._("Downloading is canceled manually.")))
            if was_config_download:
                Clock.schedule_once(partial(self.finishLoadConfig, False), 0)

        if show_progress:
            Clock.schedule_once(self.progressFinish, 0.1)

    def onFirmwareDetected(self, version, *args):
        app = App.get_running_app()
        if Config.get("carvera", "show_firmware_check") != "1":
            return
        if not app.is_community_firmware:
            content = BoxLayout(orientation="vertical", padding=dp(15))
            lbl = Label(
                text=tr._(
                    "This machine is not running the Community Firmware.\nComplete functionality is available when using both Community Firmware and Community Controller."
                ),
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            content.add_widget(lbl)
            btns = BoxLayout(size_hint_y=0.4)
            popup = Popup(
                title=tr._("Stock Firmware Detected"), content=content, size_hint=(0.5, 0.4), auto_dismiss=False
            )
            btn_information = Button(text=tr._("More Information"))
            btn_information.bind(
                on_release=lambda *a: (
                    webbrowser.open("https://carvera-community.gitbook.io/docs/compatibility"),
                    popup.dismiss(),
                )
            )
            btn_dont_show = Button(text=tr._("Don't Show Again"))
            btn_dont_show.bind(
                on_release=lambda *a: (
                    Config.set("carvera", "show_firmware_check", "0"),
                    Config.write(),
                    popup.dismiss(),
                )
            )
            btn_continue = Button(text=tr._("Continue"))
            btn_continue.bind(on_release=lambda *a: popup.dismiss())
            btns.add_widget(btn_information)
            btns.add_widget(btn_dont_show)
            btns.add_widget(btn_continue)
            content.add_widget(btns)
            popup.open()

        # Warn when community firmware major.minor is ahead of the controller.
        # Skip for unversioned controllers (0.0.0) and date-based YYYY.dev builds.
        fw_v = Utils.digitize_v(version) if version else 0
        ctl_v = Utils.digitize_v(self.ctl_version) if self.ctl_version else 0
        fw_major, ctl_major = fw_v // 1_000_000, ctl_v // 1_000_000
        if (
            app.is_community_firmware
            and fw_v
            and ctl_v
            and not (fw_major >= 2026 and ctl_major >= 2026)
            and fw_v // 1000 > ctl_v // 1000
        ):
            content = BoxLayout(orientation="vertical", padding=dp(15))
            lbl = Label(
                text=tr._(
                    "This is an unsupported configuration.\n"
                    "The machine firmware is newer than this Controller.\n\n"
                    "Firmware: v%s\n"
                    "Controller: v%s\n\n"
                    "Please update the Controller to a matching version."
                )
                % (version, self.ctl_version),
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            content.add_widget(lbl)
            btns = BoxLayout(size_hint_y=0.4)
            popup = Popup(
                title=tr._("Unsupported Configuration"),
                content=content,
                size_hint=(0.5, 0.4),
                auto_dismiss=False,
            )
            btn_dont_show = Button(text=tr._("Don't Show Again"))
            btn_dont_show.bind(
                on_release=lambda *a: (
                    Config.set("carvera", "show_firmware_check", "0"),
                    Config.write(),
                    popup.dismiss(),
                )
            )
            btn_continue = Button(text=tr._("Continue"))
            btn_continue.bind(on_release=lambda *a: popup.dismiss())
            btns.add_widget(btn_dont_show)
            btns.add_widget(btn_continue)
            content.add_widget(btns)
            popup.open()

    # -----------------------------------------------------------------------
    def setUIForModel(self, model, *args):
        app = App.get_running_app()
        model_changed = False
        if model != app.model:
            app.model = model.strip()
            model_changed = True
        app.has_anchor2 = app.model != "Z1"
        if not app.has_anchor2 and getattr(self, "coord_popup", None):
            if self.coord_popup.config.get("origin", {}).get("anchor") == 2:
                self.coord_popup.set_config("origin", "anchor", 1)
                self.coord_popup.load_config()
        if app.model == "CA1":
            CNC.vars["rotation_base_width"] = 300
            CNC.vars["rotation_head_width"] = 56.5
        elif app.model == "Z1":
            CNC.vars["rotation_base_width"] = 263
            CNC.vars["rotation_head_width"] = 50
        elif app.model == "C1":
            if CNC.vars["FuncSetting"] & 1:
                CNC.vars["rotation_base_width"] = 330
                CNC.vars["rotation_head_width"] = 18.5
            else:
                CNC.vars["rotation_base_width"] = 330
                CNC.vars["rotation_head_width"] = 7
        if app.is_community_firmware:
            self.tool_drop_down.set_dropdown.values = [
                "Empty",
                "Probe",
                "3D Probe",
                "Tool: 1",
                "Tool: 2",
                "Tool: 3",
                "Tool: 4",
                "Tool: 5",
                "Tool: 6",
                "Laser",
                "Custom",
            ]
            self.tool_drop_down.change_dropdown.values = [
                "Probe",
                "3D Probe",
                "Tool: 1",
                "Tool: 2",
                "Tool: 3",
                "Tool: 4",
                "Tool: 5",
                "Tool: 6",
                "Laser",
                "Custom",
            ]
        app.has_atc = bool(CNC.vars["FuncSetting"] & 4)
        # The first machine config load must happen after /sd/config.txt is parsed.
        if model_changed and self.config_loaded:

            def _reload_machine_config(_dt):
                self.config_loading = True
                try:
                    self.load_machine_config()
                finally:
                    self.config_loading = False

            Clock.schedule_once(_reload_machine_config, 0.1)
        if model_changed:
            self.apply_bed_settings()

    # -----------------------------------------------------------------------
    def downloadCallback(self, remote_path, packet_size, success_count, error_count):
        """Progress callback for legacy XMODEM downloads."""
        packets = self.downloading_size / packet_size + (1 if self.downloading_size % packet_size > 0 else 0)
        Clock.schedule_once(
            partial(
                self.progressUpdate, success_count * 100.0 / packets, tr._("Downloading") + " \n%s" % remote_path, False
            ),
            0,
        )

    def downloadCallback_framed(self, seq_rev, totalpackets):
        """Progress callback for Makera framed downloads (seq, total)."""
        if not totalpackets:
            return
        remote_path = getattr(self, "downloading_file", "") or ""
        Clock.schedule_once(
            partial(
                self.progressUpdate,
                seq_rev * 100.0 / totalpackets,
                tr._("Downloading") + " \n%s" % remote_path,
                False,
            ),
            0,
        )

    # -----------------------------------------------------------------------
    def cancelSelectFile(self):
        self.progress_popup.dismiss()
        app = App.get_running_app()
        app.selected_local_filename = ""
        app.selected_remote_filename = ""
        self.apply_bed_settings()

    # -----------------------------------------------------------------------
    def startLoadWiFi(self, button):
        self.wifi_ap_drop_down.open(button)
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = tr._("WiFi: Searching for network...")
        else:
            self.wifi_ap_status_bar = WiFiButton(
                ssid=tr._("WiFi: Searching for network..."), color=(180 / 255, 180 / 255, 180 / 255, 1)
            )
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

        # load wifi AP
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()
        self.controller.loadWiFiCommand()

    # -----------------------------------------------------------------------
    def finishLoadWiFi(self, *args):
        ap_list = []
        has_connected = False
        while self.controller.load_buffer.qsize() > 0:
            ap_info = self.controller.load_buffer.get_nowait().split(",")
            if len(ap_info) > 3:
                if ap_info[3] == "1":
                    has_connected = True
                ap_list.append(
                    {
                        "ssid": ap_info[0].replace("\x01", " "),
                        "connected": ap_info[3] == "1",
                        "encrypted": ap_info[1] == "1",
                        "strength": (int)(ap_info[2]),
                    }
                )

        self.wifi_ap_drop_down.clear_widgets()
        self.wifi_ap_status_bar = None
        self.wifi_ap_status_bar = WiFiButton(
            ssid=tr._("WiFi: Connected") if has_connected else tr._("WiFi: Not Connected"),
            color=(180 / 255, 180 / 255, 180 / 255, 1),
        )
        self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)
        if has_connected:
            btn = WiFiButton(ssid=tr._("Close Connection"))
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(""))
            self.wifi_ap_drop_down.add_widget(btn)
        # interval
        btn = WiFiButton(height="10dp")
        self.wifi_ap_drop_down.add_widget(btn)
        for ap in ap_list:
            btn = WiFiButton(
                connected=ap["connected"], ssid=ap["ssid"], encrypted=ap["encrypted"], strength=ap["strength"]
            )
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(btn.ssid))
            self.wifi_ap_drop_down.add_widget(btn)
        btn = WiFiButton(ssid=tr._("Other..."))
        btn.bind(on_release=lambda btn: self.manually_input_ssid())
        self.wifi_ap_drop_down.add_widget(btn)

    # -----------------------------------------------------------------------
    def loadWiFiError(self, error_msg, *args):
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = "WiFi: " + error_msg
        else:
            self.wifi_ap_status_bar = WiFiButton(ssid="WiFi: " + error_msg, color=(200 / 255, 200 / 255, 200 / 255, 1))
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

    # -----------------------------------------------------------------------
    def loadConnWiFiError(self, error_msg, *args):
        # start loading
        if error_msg == "":
            while self.controller.load_buffer.qsize() > 0:
                self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        else:
            self.message_popup.lb_content.text = error_msg
        self.message_popup.btn_ok.disabled = False

    def finishLoadConnWiFi(self, *args):
        while self.controller.load_buffer.qsize() > 0:
            self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        self.message_popup.btn_ok.disabled = False

    def load_machine_config_defaults(self):
        self.setting_default_list.clear()
        data = self.load_machine_config_data()
        if data is None:
            return

        for setting in data:
            if "key" in setting and "default" in setting:
                key = setting["key"]
                value = setting["default"]
                self.setting_default_list[key] = value
                self.setting_list[key] = value

    def load_machine_config_data(self):
        app = App.get_running_app()
        if not app.model or app.model == "":
            return None

        if self.machine_config_data_model == app.model:
            return self.machine_config_data

        config_file = MACHINE_CONFIG_FILES.get(app.model)
        if config_file is None:
            return None

        config_path = os.path.join(os.path.dirname(__file__), config_file)
        if not os.path.exists(config_path):
            return None

        with open(config_path) as fd:
            self.machine_config_data = json.loads(fd.read())
        self.machine_config_data_model = app.model
        return self.machine_config_data

    def load_coordinates(self):
        for coord_name in CNC.coord_names:
            new_name = "coordinate." + coord_name
            if new_name in self.setting_list:
                CNC.vars[coord_name] = float(self.setting_list[new_name])
            else:
                self.controller.log.put((Controller.MSG_ERROR, tr._("Can not load coordinate value:") + f" {new_name}"))

    def load_laser_offsets(self):
        for offset_name in CNC.laser_names:
            if offset_name in self.setting_list:
                CNC.vars[offset_name] = float(self.setting_list[offset_name])
            else:
                self.controller.log.put(
                    (Controller.MSG_ERROR, tr._("Can not load laser offset value:") + f" {offset_name}")
                )

    # -----------------------------------------------------------------------
    def loadRemoteDir(self, ls_dir):
        self.loading_dir = ls_dir
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_DIR
        self.controller.loadEOF = False
        self.controller.loadERR = False
        self.short_load_time = time.time()
        self.controller.lsCommand(os.path.normpath(ls_dir))

    # -----------------------------------------------------------------------
    def removeRemoteFile(self, filename):
        self.pending_remote_delete_files = []
        self.startRemoteDelete(filename)

    # -----------------------------------------------------------------------
    def removeRemoteFiles(self, filenames):
        self.pending_remote_delete_files = list(filenames)
        self.removeNextRemoteFile()

    # -----------------------------------------------------------------------
    def removeNextRemoteFile(self, *args):
        if not getattr(self, "pending_remote_delete_files", []):
            self.deleting_remote_file = ""
            Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            return
        filename = self.pending_remote_delete_files.pop(0)
        self.startRemoteDelete(filename)

    # -----------------------------------------------------------------------
    def startRemoteDelete(self, filename):
        self.deleting_remote_file = filename
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_RM
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        self.controller.rmCommand(os.path.normpath(filename))

    # -----------------------------------------------------------------------
    def renameRemoteFile(self, filename):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MV
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        new_name = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        if filename == new_name:
            return False
        self.controller.mvCommand(os.path.normpath(filename), os.path.normpath(new_name))
        return True

    # -----------------------------------------------------------------------
    def createRemoteDir(self):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MKDIR
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        dirname = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        self.controller.mkdirCommand(os.path.normpath(dirname))
        return True

    # -----------------------------------------------------------------------
    def connectToWiFi(self):
        password = self.input_popup.txt_content.text.strip()
        if not password:
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_CONN_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()

        Clock.schedule_once(
            partial(self.show_message_popup, tr._("Connecting to") + " %s...\n" % self.input_popup.cache_var1, True), 0
        )

        self.controller.connectWiFiCommand(self.input_popup.cache_var1, password)
        return True

    # -----------------------------------------------------------------------
    def show_message_popup(self, message, btn_disabled, *args):
        self.message_popup.lb_content.text = message
        self.message_popup.btn_ok.disabled = btn_disabled
        self.message_popup.open()

    def show_usb_reset_blocked_popup(self, *args):
        content = BoxLayout(orientation="vertical", padding=dp(15))
        lbl = Label(
            text=tr._(
                "As you are connected over USB, please disconnect the USB cable, then use the power switch on the machine "
                "to perform a reset.\n\n"
                "The Makera control board design allows the machine to "
                "receive power over USB, which results in it being left in a "
                "zombie-like state if a reset command is sent using the Controller."
            ),
            halign="center",
            valign="middle",
        )
        lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        content.add_widget(lbl)
        btns = BoxLayout(size_hint_y=0.35)
        popup = Popup(
            title=tr._("Cannot Reset Over USB"),
            content=content,
            size_hint=(0.55, 0.45),
            auto_dismiss=False,
        )
        btn_ok = Button(text=tr._("Ok"))
        btn_ok.bind(on_release=lambda *a: popup.dismiss())
        btns.add_widget(btn_ok)
        content.add_widget(btns)
        popup.open()

    # -----------------------------------------------------------------------
    def compress_file(self, input_filename):
        try:
            # If the uploaded file is a firmware file, return the original filename without compression.
            if input_filename.find(".bin") != -1:
                return input_filename

            # Check if the filename.lz is writeable
            can_write_in_lz = os.access(input_filename + ".lz", os.W_OK)
            if not can_write_in_lz:
                logger.warning(f"Compression failed: Cannot write to '{input_filename}.lz', using temp dir")
                # First copy the file to the temp dir (skip if already there, e.g. facing wizard .nc).
                dest_path = os.path.join(self.temp_dir, os.path.basename(input_filename))
                try:
                    shutil.copy(input_filename, self.temp_dir)
                except shutil.SameFileError:
                    pass
                input_filename = dest_path
                # Then compress the file to the temp dir
                output_filename = os.path.join(self.temp_dir, os.path.basename(input_filename) + ".lz")
            else:
                output_filename = input_filename + ".lz"
            sum = 0
            self.fileCompressionBlocks = 0
            self.decompercent = 0
            self.decompercentlast = 0
            with open(input_filename, "rb") as f_in, open(output_filename, "wb") as f_out:
                while True:
                    # Read block data
                    block = f_in.read(BLOCK_SIZE)
                    if not block:
                        break
                    # Calculate the sum
                    for byte in block:
                        sum += byte
                    # Compress the block data
                    compressed_block = quicklz.compress(block)

                    # Calculate the size of the compressed data block
                    cmprs_size = len(compressed_block)
                    buffer_hdr = struct.pack(">I", cmprs_size)
                    # Write the length of the compressed data block to the output file
                    f_out.write(buffer_hdr)
                    # Write the compressed data block to the output file
                    f_out.write(compressed_block)
                    self.fileCompressionBlocks += 1
                # Write the checksum
                sumdata = struct.pack(">H", sum & 0xFFFF)
                f_out.write(sumdata)

            logger.info(f"Compression completed. Compressed file saved as '{output_filename}'.")
            return output_filename

        except Exception as e:
            logger.error(f"Compression failed: {e}")
            if os.path.exists(output_filename):
                os.remove(output_filename)
            return None

    # -----------------------------------------------------------------------
    def _verify_deferred_download_md5(self, filepath):
        """Verify a machine-advertised MD5 after .lz decompress. Returns False on mismatch."""
        modem = getattr(getattr(self.controller, "stream", None), "modem", None)
        expected = getattr(modem, "deferred_download_md5", None) if modem is not None else None
        if modem is not None:
            modem.deferred_download_md5 = None
        if not expected:
            return True

        actual = Utils.md5(filepath)
        if actual.lower() == expected.lower():
            logger.info("Download MD5 matched after decompress: %s", actual)
            return True

        logger.error(
            "Download error: MD5 mismatch after decompress (expected=%s, actual=%s)",
            expected,
            actual,
        )
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
        Clock.schedule_once(
            partial(
                self.show_message_popup,
                tr._(
                    "Download file error! MD5 hash doesn't match what is expected. "
                    "Possible corruption during transfer or on SD card."
                ),
                False,
            ),
            0,
        )
        return False

    # -----------------------------------------------------------------------
    def decompress_file(self, input_filename, output_filename):
        try:
            # 打开输入文件和输出文件
            sum = 0
            read_size = 0
            with open(input_filename, "rb") as f_in, open(output_filename, "wb") as f_out:
                # 获取文件大小（以字节为单位）
                file_size = os.path.getsize(input_filename)
                while True:
                    if read_size == (file_size - 2):
                        break
                    # 读取块数据长度
                    block = f_in.read(BLOCK_HEADER_SIZE)
                    if not block:
                        break
                    blocksize = struct.unpack(">I", block)[0]
                    read_size += BLOCK_HEADER_SIZE + blocksize
                    # 读取块数据
                    block = f_in.read(blocksize)
                    # 解压缩数据
                    decompressed_block = quicklz.decompress(block)
                    # 计算sum和
                    for byte in decompressed_block:
                        sum += byte
                    # 写入解压缩后的块数据的长度到输出文件
                    f_out.write(decompressed_block)
            # 判断校验和
            with open(input_filename, "rb") as f_in:
                f_in.seek(-2, 2)  # 从文件末尾向前移动2个字节
                sumfile = f_in.read(2)
            sumfile = struct.unpack(">H", sumfile)[0]
            sumdata = sum & 0xFFFF

            if sumfile != sumdata:
                logger.error("deCompress failed: sum checksum mismatch")
                return False

            logger.info(f"deCompress completed. deCompressed file saved as '{output_filename}'.")
            return True

        except Exception as e:
            logger.error(f"deCompress failed: {e}")
            if os.path.exists(output_filename):
                os.remove(output_filename)
            return False

    # -----------------------------------------------------------------------
    def uploadLocalFile(self, filepath, callback=None):
        self.controller.sendNUM = SEND_FILE
        self.uploading_file = filepath
        self.original_upload_filepath = filepath  # Store original path for recent directory tracking
        if "lz" in self.filetype:  # 如果固件支持的上传文件类型为.lz，则进行压缩
            qlzfilename = self.compress_file(filepath)
            if qlzfilename:
                self.uploading_file = qlzfilename
        threading.Thread(target=self.doUpload, args=(callback,)).start()

    # -----------------------------------------------------------------------
    def doUpload(self, callback):
        self.uploading_size = os.path.getsize(self.uploading_file)
        remotename = os.path.join(
            self.file_popup.remote_rv.curr_dir, os.path.basename(os.path.normpath(self.uploading_file))
        )
        if self.file_popup.firmware_mode:
            remotename = "/sd/firmware.bin"
        displayname = self.uploading_file
        if displayname.endswith(".lz"):
            # 删除 ".lz" 后缀
            displayname = displayname[:-3]
        Clock.schedule_once(
            partial(self.progressStart, tr._("Uploading") + "\n%s" % displayname, self.cancelProcessingFile), 0
        )
        self.uploading = True
        self.controller.pauseStream(1)
        upload_result = None
        try:
            # md5 = Utils.md5(self.uploading_file)
            md5 = Utils.md5(displayname)
            self.controller.uploadCommand(os.path.normpath(remotename))
            upload_result = self.controller.stream.upload(self.uploading_file, md5, self.uploadCallback)
        except:
            self.controller.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))
            self.controller.resumeStream()
            self.uploading = False

        self.controller.resumeStream()
        self.uploading = False

        Clock.schedule_once(self.progressFinish, 0)

        self.heartbeat_time = time.time()

        if upload_result is None:
            self.controller.log.put((Controller.MSG_NORMAL, tr._("Uploading is canceled manually.")))
            # 如果为压缩后的'.lz'文件则删除该文件
            if self.uploading_file.endswith(".lz"):
                os.remove(self.uploading_file)
        elif not upload_result:
            # 如果为压缩后的'.lz'文件则删除该文件
            if self.uploading_file.endswith(".lz"):
                os.remove(self.uploading_file)
            # show message popup
            Clock.schedule_once(partial(self.show_message_popup, tr._("Upload file error!"), False), 0)
        else:
            # copy file to application directory if needed
            remote_path = os.path.join(
                self.file_popup.remote_rv.curr_dir, os.path.basename(os.path.normpath(self.uploading_file))
            )
            remote_post_path = remote_path.replace("/sd/", "").replace("\\sd\\", "")
            local_path = os.path.join(self.temp_dir, remote_post_path)
            if self.uploading_file != local_path and not self.file_popup.firmware_mode:
                if self.uploading_file.endswith(".lz"):
                    # copy lz file to .lz dir
                    lzpath, filename = os.path.split(local_path)
                    lzpath = os.path.join(lzpath, ".lz")
                    lzpath = os.path.join(lzpath, filename)
                    if not os.path.exists(os.path.dirname(lzpath)):
                        # os.mkdir(os.path.dirname(lzpath))
                        os.makedirs(os.path.dirname(lzpath))
                    shutil.copyfile(self.uploading_file, lzpath)

                    # copy the origin file
                    origin_file = self.uploading_file[0:-3]
                    origin_path = local_path[0:-3]
                    if not os.path.exists(os.path.dirname(origin_path)):
                        # os.mkdir(os.path.dirname(origin_path))
                        os.makedirs(os.path.dirname(origin_path))
                    shutil.copyfile(origin_file, origin_path)
                else:
                    if not os.path.exists(os.path.dirname(local_path)):
                        # os.mkdir(os.path.dirname(local_path))
                        os.makedirs(os.path.dirname(local_path))
                    shutil.copyfile(self.uploading_file, local_path)
            if self.file_popup.firmware_mode:
                Clock.schedule_once(self.confirm_reset, 0)
            # update recent folder
            if not self.file_popup.firmware_mode:
                self.update_recent_local_dir_list(os.path.dirname(self.original_upload_filepath))

            # If it is a compressed ''.lz' file, wait for the decompression to complete.
            if self.uploading_file.endswith(".lz"):
                self.log = logging.getLogger("File.Decompress")
                self.decompstatus = True
                os.remove(self.uploading_file)
                self.decomptime = time.time()
                Clock.schedule_once(
                    partial(self.progressStart, tr._("Decompressing") + "\n%s" % displayname, False), 0.2
                )

        self.controller.sendNUM = 0
        if upload_result and callback:  # Only run callback if upload succeeded
            if self.uploading_file.endswith(".lz"):
                # Schedule callback to run after decompression completes
                # The callback will be triggered in updateCompressProgress when decompression finishes
                self.pending_decompress_callback = partial(callback, remotename[:-3], origin_path)
            else:
                callback(remotename, local_path)
        # For iOS we display the file list remotely only so we need to refresh it but on main thread
        if upload_result and not self.file_popup.firmware_mode and not self.uploading_file.endswith(".lz"):
            Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)

    # -----------------------------------------------------------------------
    def confirm_reset(self, *args):
        self.confirm_popup.lb_title.text = tr._("Update Finished")
        self.confirm_popup.lb_content.text = tr._("Confirm to reset the machine?")
        self.confirm_popup.confirm = partial(self.resetMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def uploadCallback(self, packet_size, total_packets, success_count, error_count):
        packets = self.uploading_size / packet_size + (1 if self.uploading_size % packet_size > 0 else 0)
        Clock.schedule_once(partial(self.progressUpdate, total_packets * 100.0 / packets, "", False), 0)

    # -----------------------------------------------------------------------
    def cancelProcessingFile(self):
        self.controller.stream.cancel_process()

    # -----------------------------------------------------------------------
    def process_loaded_dir(self, *args):
        is_dir = False
        file_list = []
        while self.controller.load_buffer.qsize() > 0:
            line = self.controller.load_buffer.get_nowait().strip("\r").strip("\n")
            if len(line) > 0 and line[0] != "<":
                file_infos = line.split()
                if (
                    len(file_infos) == 3
                    and not file_infos[0].startswith(".")
                    and file_infos[1].isdigit()
                    and file_infos[2].isdigit()
                ):
                    is_dir = False
                    file_infos[0] = file_infos[0].replace("\x01", " ")
                    if file_infos[0].endswith("/"):
                        is_dir = True
                        file_infos[0] = file_infos[0][:-1]
                    timestamp = 0
                    try:
                        timestamp = time.mktime(datetime.datetime.strptime(file_infos[2], "%Y%m%d%H%M%S").timetuple())
                    except:
                        pass
                    file_list.append(
                        {
                            "name": file_infos[0],
                            "path": f"{self.file_popup.remote_rv.curr_dir}/{file_infos[0]}",
                            "is_dir": is_dir,
                            "size": int(file_infos[1]),
                            "date": timestamp,
                        }
                    )

        Clock.schedule_once(partial(self.fill_remote_dir, file_list), 0)

    # -----------------------------------------------------------------------
    def fill_remote_dir(self, file_list, *args):
        self.file_popup.remote_rv.curr_file_list_buff = file_list
        self.file_popup.remote_rv.fill_dir(switch_reverse=False)

        self.file_popup.remote_rv.curr_dir = os.path.normpath(self.file_popup.remote_rv.curr_dir)
        self.file_popup.remote_rv.curr_dir_name = os.path.basename(os.path.normpath(self.file_popup.remote_rv.curr_dir))

        self.file_popup.remote_rv.curr_full_path_list = [self.file_popup.remote_rv.curr_dir]
        if (
            self.file_popup.remote_rv.curr_dir == self.file_popup.remote_rv.base_dir
            or self.file_popup.remote_rv.curr_dir == self.file_popup.remote_rv.base_dir_win
        ):
            self.file_popup.remote_rv.curr_path_list = ["root"]

            if self.fill_remote_dir_callback:
                threading.Thread(
                    target=self.fill_remote_dir_callback, args=(self.file_popup.remote_rv.curr_file_list_buff,)
                ).start()
                self.fill_remote_dir_callback = None
            return
        self.file_popup.remote_rv.curr_path_list = [self.file_popup.remote_rv.curr_dir_name]
        last_parent_dir = self.file_popup.remote_rv.curr_dir

        for loop in range(5):
            parent_dir = os.path.dirname(last_parent_dir)
            if last_parent_dir == parent_dir:
                break
            self.file_popup.remote_rv.curr_full_path_list.insert(0, parent_dir)
            if parent_dir == self.file_popup.remote_rv.base_dir or parent_dir == self.file_popup.remote_rv.base_dir_win:
                self.file_popup.remote_rv.curr_path_list.insert(0, "root")
                break
            self.file_popup.remote_rv.curr_path_list.insert(0, os.path.basename(parent_dir))
            last_parent_dir = parent_dir

        if self.fill_remote_dir_callback:
            threading.Thread(
                target=self.fill_remote_dir_callback, args=(self.file_popup.remote_rv.curr_file_list_buff,)
            ).start()
            self.fill_remote_dir_callback = None

    # -----------------------------------------------------------------------
    def loadError(self, error_msg, *args):
        # close progress popups
        self.progress_popup.dismiss()
        # show message popup
        self.message_popup.lb_content.text = error_msg
        self.message_popup.open()

        # clear load buffer other will over load
        while self.controller.load_buffer.qsize() > 0:
            self.controller.load_buffer.get_nowait()

    # --------------------------------------------------------------`---------
    def progressStart(self, text, cancel_func, *args):
        self.progress_popup.progress_text = text
        self.progress_popup.progress_value = 0
        if cancel_func:
            self.progress_popup.cancel = cancel_func
            self.progress_popup.btn_cancel.disabled = False
        else:
            self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.open()

    # --------------------------------------------------------------`---------
    def progressUpdate(self, value, progress_text, button_disabled, *args):
        if progress_text != "":
            self.progress_popup.progress_text = progress_text
        self.progress_popup.btn_cancel.disabled = button_disabled
        self.progress_popup.progress_value = value

    # --------------------------------------------------------------`---------
    def progressFinish(self, *args):
        self.progress_popup.dismiss()

    # --------------------------------------------------------------`---------
    def _on_time_estimate_progress(self, state, percent):
        """Callback for GcodeViewer time estimate computation.

        'start'/'progress'/'done' drive the progress popup. 'updated' means a
        silent refresh applied new times (no popup).
        """
        if state == "start":
            self.progressStart(tr._("Calculating run time estimate..."), None)
        elif state == "progress":
            self.progressUpdate(percent, "", True)
        elif state == "done":
            self.progressFinish()
            self.refresh_gcode_color_legend()
            self._refresh_idle_progress_info()
        elif state == "updated":
            self.refresh_gcode_color_legend()
            self._refresh_idle_progress_info()

    # --------------------------------------------------------------`---------
    _PROGRESS_TIMER_PAUSED_STATES = frozenset({"Hold", "Pause", "Wait", "Tool"})

    def _current_remaining_sec(self):
        return max(0.0, self._remaining_anchor_sec - (time.time() - self._remaining_anchor_time))

    def _seconds_until_line(self, line_no, live_remaining=None):
        """Seconds until a line: from start when idle, from the playhead when running."""
        if line_no is None or not self.selected_file_line_count:
            return None
        remaining_at = self.gcode_viewer.get_remaining_time_by_lineidx
        total_time = self.gcode_viewer.total_time or 0.0
        percent_target = play_percent_from_line(line_no, self.selected_file_line_count)
        if live_remaining is None:
            return seconds_from_start(
                gcode_remaining_target=remaining_at(line_no, 0.0),
                total_time=total_time,
                percent_target=percent_target,
            )
        current_line = self.played_lines or 1
        return seconds_until_target(
            gcode_remaining_now=remaining_at(current_line, 0.5),
            gcode_remaining_target=remaining_at(line_no, 0.0),
            live_remaining=live_remaining,
            percent_now=self.wpb_play.value,
            percent_target=percent_target,
        )

    def _tool_change_display_name(self, label):
        if label == "L":
            return tr._("Laser")
        if label == "P":
            return tr._("Probe")
        if label == "3DP":
            return tr._("3D Probe")
        return label

    def _playbar_tool_change_tooltip(self, label, line_no):
        app = App.get_running_app()
        playing = bool(app and app.playing)
        if playing and app.state in self._PROGRESS_TIMER_PAUSED_STATES:
            live_remaining = max(0.0, self._remaining_anchor_sec)
        elif playing:
            live_remaining = self._current_remaining_sec()
        else:
            live_remaining = None
        seconds = self._seconds_until_line(line_no, live_remaining)
        tool_name = self._tool_change_display_name(label)
        if seconds is None:
            return tr._("Tool change to {}").format(tool_name)
        if playing and seconds <= 0:
            return tr._("Tool change to {} passed").format(tool_name)
        return tr._("Tool change to {} in {}").format(tool_name, Utils.second2hour(int(seconds)))

    def _format_file_progress_info(self, *, playing, remaining_sec=None):
        """Progress-bar text while a file is selected, playing or idle."""
        app = App.get_running_app()
        path = (app.selected_remote_filename or app.selected_local_filename) if app else ""
        filename = os.path.basename(path) if path else ""
        if not playing:
            duration_sec = self.gcode_viewer.total_time or 0.0
            if duration_sec <= 0:
                return f" {filename}" if filename else ""
            return f" {filename} ({Utils.second2hour(int(duration_sec))} {tr._('estimated')})"
        remaining = remaining_sec if remaining_sec is not None else 0.0
        time_phrase = f"{Utils.second2hour(int(remaining))} to go"
        next_change = next_tool_change_after_line(self.tool_change_markers, self.played_lines)
        if next_change is not None and self.status_index % 2 == 1:
            next_line, next_label = next_change
            until_sec = self._seconds_until_line(next_line, remaining)
            if until_sec is not None:
                time_phrase = tr._("{} until {}").format(Utils.second2hour(int(until_sec)), next_label)
        return (
            f" {filename} ( {self.played_lines}/{self.selected_file_line_count} - {int(self.wpb_play.value)}%,"
            f" {Utils.second2hour(int(CNC.vars.get('playedseconds', 0) or 0))} {tr._('elapsed')}, {time_phrase} )"
        )

    def _refresh_idle_progress_info(self):
        app = App.get_running_app()
        if app is None or app.playing:
            return
        if app.selected_remote_filename or app.selected_local_filename:
            self.progress_info = self._format_file_progress_info(playing=False)

    def _update_progress_smooth(self, dt):
        """Refresh elapsed/remaining display every second while playing."""
        app = App.get_running_app()
        if (
            not app.playing
            or app.state == NOT_CONNECTED
            or (not app.selected_remote_filename and not app.selected_local_filename)
            or not self.selected_file_line_count
            or app.state in self._PROGRESS_TIMER_PAUSED_STATES
        ):
            # While held/paused/disconnected, leave the last progress_info unchanged so both timers freeze.
            return
        self.progress_info = self._format_file_progress_info(playing=True, remaining_sec=self._current_remaining_sec())

    # --------------------------------------------------------------`---------
    def updateCompressProgress(self, value):
        Clock.schedule_once(partial(self.progressUpdate, value * 100.0 / self.fileCompressionBlocks, "", True), 0)
        if value == self.fileCompressionBlocks:
            Clock.schedule_once(self.progressFinish, 0)
            # Refresh the remote dir since upload finished
            Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            self.decompstatus = False
            # Call pending callback after decompression completes (for .lz files)
            if hasattr(self, "pending_decompress_callback") and self.pending_decompress_callback:
                # Capture callback before clearing it
                callback = self.pending_decompress_callback
                self.pending_decompress_callback = None
                # Schedule callback with a short delay to ensure decompression is fully complete
                Clock.schedule_once(lambda dt: callback(), 0.1)

    # -----------------------------------------------------------------------
    def updateStatus(self, *args):
        try:
            now = time.time()
            self.heartbeat_time = now
            app = App.get_running_app()

            # The App.get_running_app() can return None in certain situations, especially during initialization or shutdown.
            if app is None:
                return

            # First real machine state ends the post-connect heartbeat grace window.
            if CNC.vars["state"] not in (NOT_CONNECTED, CONNECTED):
                self.controller._heartbeat_grace_until = 0

            if app.state != CNC.vars["state"]:
                prev_state = app.state
                app.state = CNC.vars["state"]
                CNC.vars["color"] = STATECOLOR[app.state]
                self.status_data_view.color = CNC.vars["color"]
                self.holding = 1 if app.state == "Hold" else 0
                self.pausing = 1 if app.state == "Pause" else 0
                self.waiting = 1 if app.state == "Wait" else 0
                self.tooling = 1 if app.state == "Tool" else 0
                if app.playing:
                    was_paused = prev_state in self._PROGRESS_TIMER_PAUSED_STATES
                    now_paused = app.state in self._PROGRESS_TIMER_PAUSED_STATES
                    if now_paused and not was_paused:
                        # Park remaining so pause duration is not subtracted on resume.
                        self._remaining_anchor_sec = self._current_remaining_sec()
                        self._remaining_anchor_time = now
                    elif was_paused and not now_paused:
                        self._remaining_anchor_time = now
                # update status
                self.status_data_view.main_text = app.state
                if app.state == NOT_CONNECTED:
                    self.status_data_view.minr_text = tr._("disconnect")
                    self.status_drop_down.btn_connect_usb.disabled = False
                    self.status_drop_down.btn_connect_wifi.disabled = False
                    self.status_drop_down.btn_connect_network.disabled = False
                    self.status_drop_down.btn_disconnect.disabled = True
                    self.config_loaded = False
                    self.config_loading = False
                    self._config_apply_failed = False
                    self._config_download_failures = 0
                    self.fw_version_checked = False
                    self.fw_version = ""
                    app.model = ""
                    app.has_anchor2 = True
                    app.fw_version_digitized = 0
                    app.is_community_firmware = False
                    app.supports_auto_ext_out = False
                    app.supports_camera = False
                    self.camera_checked = False
                    self.camera_probe += 1  # discard the result of a probe still in flight
                    self.camera_stream.stop()
                    if self.gcode_viewer is not None:
                        self.gcode_viewer.set_bed(None, visible=False)
                    self.controller.is_community_firmware = False
                    self.machine_metadata_query_time = 0

                    # Clean up light toggle binding when disconnected
                    if hasattr(self, "_light_toggle_bound"):
                        self.unbind(light_state=self._on_light_state_changed)
                        delattr(self, "_light_toggle_bound")

                    # Check if we should show reconnection popup (only if not a manual disconnect and not already reconnecting)
                    if not self.controller._manual_disconnect and not self.reconnection_popup._is_open:
                        auto_reconnect_enabled = Config.getboolean("carvera", "auto_reconnect_enabled", fallback=True)
                        reconnect_wait_time = Config.getint("carvera", "reconnect_wait_time", fallback=10)
                        reconnect_attempts = Config.getint("carvera", "reconnect_attempts", fallback=3)
                        self.controller.set_reconnection_config(
                            auto_reconnect_enabled, reconnect_wait_time, reconnect_attempts
                        )
                        if auto_reconnect_enabled:
                            self.reconnection_popup.start_countdown(
                                reconnect_attempts,
                                reconnect_wait_time,
                                self.attempt_reconnect,
                                self.on_reconnect_failed,
                            )
                            self.reconnection_popup.open()
                            Clock.schedule_interval(self.reconnection_popup.countdown_tick, 1.0)
                            self.controller.start_reconnection()
                        else:
                            self.reconnection_popup.show_manual_reconnect(self.attempt_reconnect)
                            self.reconnection_popup.open()
                else:
                    self.status_data_view.minr_text = "WiFi" if self.controller.connection_type == CONN_WIFI else "USB"
                    self.status_drop_down.btn_connect_usb.disabled = True
                    self.status_drop_down.btn_connect_wifi.disabled = True
                    self.status_drop_down.btn_connect_network.disabled = True
                    self.status_drop_down.btn_disconnect.disabled = False

                    # If we just reconnected, stop any reconnection popup and timer
                    if self.reconnection_popup._is_open:
                        Clock.unschedule(self.reconnection_popup.countdown_tick)
                        self.reconnection_popup.dismiss()

                    # Notify that reconnection succeeded
                    self.controller.notify_reconnection_success()

                    # Reset manual disconnect flag since we're now connected
                    self.controller._manual_disconnect = False

                    # Look for a camera, only one time per connection
                    if not self.camera_checked and self.controller.connection_type == CONN_WIFI:
                        self.camera_checked = True
                        self.camera_probe += 1
                        host = self.controller.connection_address.split(":")[0]
                        threading.Thread(
                            target=self._detect_camera, args=(host, self.camera_probe), daemon=True
                        ).start()

                self.status_drop_down.btn_unlock.disabled = app.state != "Alarm" and app.state != "Sleep"
                if (CNC.vars["halt_reason"] in HALT_REASON and CNC.vars["halt_reason"] > 20) or app.state == "Sleep":
                    self.status_drop_down.btn_unlock.text = "Reset"
                else:
                    self.status_drop_down.btn_unlock.text = "Unlock"

            # load config, only one time per connection
            if (
                not app.playing
                and not self.config_loaded
                and not self.config_loading
                and not self._config_apply_failed
                and self._config_download_failures < MAX_CONFIG_DOWNLOAD_ATTEMPTS
                and app.state == "Idle"
            ):
                if not app.model or not self.fw_version:
                    if now - self.machine_metadata_query_time > 1:
                        self.check_model_metadata()
                else:
                    self.config_loading = True
                    self.download_config_file()

                    # Bind light toggle button to LightProperty (only once per connection)
                    if not hasattr(self, "_light_toggle_bound"):
                        self.bind_light_toggle_to_property()
                        self._light_toggle_bound = True

            # show update
            if not app.playing and self.fw_upd_text != "" and not self.fw_version_checked and app.state == "Idle":
                self.check_fw_version()

            # check alarm and sleep status
            if app.state == "Alarm" or app.state == "Sleep":
                if not self.alarm_triggered:
                    self.alarm_triggered = True
                    if app.state == "Alarm":
                        self.open_halt_confirm_popup()
                    else:
                        self.open_sleep_confirm_popup()
            elif app.state == "Tool":
                if not self.tool_triggered:
                    self.tool_triggered = True
                    self.open_tool_confirm_popup()
            else:
                if (self.alarm_triggered or self.tool_triggered) and (
                    self.confirm_popup.showing or self.unlock_popup.showing
                ):
                    if self.confirm_popup.showing:
                        self.confirm_popup.dismiss()
                    if self.unlock_popup.showing:
                        self.unlock_popup.dismiss()
                self.tool_triggered = False
                self.alarm_triggered = False

            # update x data
            self.x_data_view.main_text = "{:.3f}".format(CNC.vars["wx"])
            self.x_data_view.minr_text = "{:.3f}".format(CNC.vars["mx"])
            self.x_data_view.scale = 80.0 if app.lasering else 100.0
            # update y data
            self.y_data_view.main_text = "{:.3f}".format(CNC.vars["wy"])
            self.y_data_view.minr_text = "{:.3f}".format(CNC.vars["my"])
            self.y_data_view.scale = 80.0 if app.lasering else 100.0
            # update z data
            self.z_data_view.main_text = "{:.3f}".format(CNC.vars["wz"])
            self.z_data_view.minr_text = "{:.3f}".format(CNC.vars["mz"])
            self.z_data_view.scale = 80.0 if app.lasering or CNC.vars["max_delta"] != 0.0 else 100.0
            self.z_drop_down.status_max.value = "{:.3f}".format(CNC.vars["max_delta"])

            # update a data
            digi_len = 7 - len(str(int(CNC.vars["ma"])))
            if digi_len < 0:
                digi_len = 0
            if digi_len > 3:
                digi_len = 3
            self.a_data_view.main_text = str("{:." + str(digi_len) + "f}").format(CNC.vars["wa"])
            self.a_data_view.minr_text = "{:.3f}".format(CNC.vars["ma"])

            # update feed data
            self.feed_data_view.main_text = "{:.0f}".format(CNC.vars["curfeed"])
            self.feed_data_view.scale = CNC.vars["OvFeed"]
            self.feed_data_view.active = CNC.vars["curfeed"] > 0.0
            if self.status_index % 2 == 0:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["OvFeed"]) + " %"
            else:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["tarfeed"])

            elapsed = now - self.control_list["feedrate_scale"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setFeedScale(self.control_list["feedrate_scale"][1])
                    self.control_list["feedrate_scale"][0] = now - 2
            elif elapsed > 3 and self.feed_drop_down.opened:
                self.feed_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvFeed"]) + "%"
                self.feed_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarfeed"])
                if self.feed_drop_down.scale_slider.value != CNC.vars["OvFeed"]:
                    self.feed_drop_down.scale_slider.set_flag = True
                    self.feed_drop_down.scale_slider.value = CNC.vars["OvFeed"]

            # update spindle/laser data (single button: icon and content depend on laser mode)
            v = self.spindle_laser_data_view
            if CNC.vars["lasermode"]:
                v.data_icon = "data/laser.png"
                v.tooltip_txt = tr._("Laser Settings")
                v.main_text = "{:.1f}".format(CNC.vars["laserpower"])
                v.minr_text = "{:.0f}".format(CNC.vars["laserscale"]) + " %"
                v.scale = CNC.vars["laserscale"]
                v.active = CNC.vars["lasermode"]
            else:
                v.data_icon = "data/spindle.png"
                v.tooltip_txt = tr._("Spindle and Vacuum Overrides")
                v.main_text = "{:.0f}".format(CNC.vars["curspindle"])
                v.scale = CNC.vars["OvSpindle"]
                v.active = CNC.vars["curspindle"] > 0.0
                if self.status_index % 4 == 0:
                    v.minr_text = "{:.0f}".format(CNC.vars["tarspindle"])
                elif self.status_index % 4 == 1:
                    v.minr_text = "{:.0f}".format(CNC.vars["OvSpindle"]) + " %"
                elif self.status_index % 4 == 2:
                    v.minr_text = "{:.1f}".format(CNC.vars["spindletemp"]) + " °C"
                else:
                    v.minr_text = "Vac: {}".format("On" if CNC.vars["vacuummode"] else "Off")

            app.spindle_or_laser_is_on = app.state not in (NOT_CONNECTED, CONNECTED) and (
                (not CNC.vars["lasermode"] and CNC.vars["curspindle"] > 0.0)
                or (CNC.vars["lasermode"] and CNC.vars["laserpower"] > 0.0)
            )

            elapsed = now - self.control_list["vacuum_mode"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumMode(self.control_list["vacuum_mode"][1])
                    self.control_list["vacuum_mode"][0] = now - 2
            elif elapsed > 3:
                if self.spindle_drop_down.vacuum_switch.active != CNC.vars["vacuummode"]:
                    self.spindle_drop_down.vacuum_switch.set_flag = True
                    self.spindle_drop_down.vacuum_switch.active = CNC.vars["vacuummode"]

            elapsed = now - self.control_list["extout_mode"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setExtOutMode(self.control_list["extout_mode"][1])
                    self.control_list["extout_mode"][0] = now - 2
            elif elapsed > 3:
                if self.spindle_drop_down.extout_switch.active != CNC.vars["extoutmode"]:
                    self.spindle_drop_down.extout_switch.set_flag = True
                    self.spindle_drop_down.extout_switch.active = CNC.vars["extoutmode"]
                if self.coord_popup._is_open:
                    extout_switch_play = self.coord_popup.ids.extout_switch_play
                    if extout_switch_play.active != CNC.vars["extoutmode"]:
                        extout_switch_play.set_flag = True
                        extout_switch_play.active = CNC.vars["extoutmode"]

            for control_name, setter, var_name, switch_id in (
                ("autoblow_mode", self.controller.setAutoBlowMode, "autoblowmode", "autoblow_switch_play"),
                (
                    "autobedclean_mode",
                    self.controller.setAutoBedCleanMode,
                    "autobedcleanmode",
                    "autobedclean_switch_play",
                ),
                ("ionizer_mode", self.controller.setIonizerMode, "ionizermode", "ionizer_switch_play"),
            ):
                elapsed = now - self.control_list[control_name][0]
                if elapsed < 2:
                    if elapsed > 0.5:
                        setter(self.control_list[control_name][1])
                        self.control_list[control_name][0] = now - 2
                elif elapsed > 3 and self.coord_popup._is_open:
                    switch = self.coord_popup.ids[switch_id]
                    if switch.active != CNC.vars[var_name]:
                        switch.set_flag = True
                        switch.active = CNC.vars[var_name]

            elapsed = now - self.control_list["spindle_scale"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleScale(self.control_list["spindle_scale"][1])
                    self.control_list["spindle_scale"][0] = now - 2
            elif elapsed > 3 and self.spindle_drop_down.opened:
                self.spindle_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvSpindle"]) + "%"
                self.spindle_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarspindle"])
                self.spindle_drop_down.status_temp.value = "{:.1f}".format(CNC.vars["spindletemp"]) + "°C"
                if self.spindle_drop_down.scale_slider.value != CNC.vars["OvSpindle"]:
                    self.spindle_drop_down.scale_slider.set_flag = True
                    self.spindle_drop_down.scale_slider.value = CNC.vars["OvSpindle"]

            app.tool = CNC.vars["tool"]

            # update tool data
            if CNC.vars["tool"] < 0:
                if app.lasering or CNC.vars["tool"] == LASER_TOOL_NUMBER:
                    self.tool_data_view.main_text = tr._("Laser")
                    if self.status_index % 2 == 0:
                        self.tool_data_view.minr_text = "TLO: {:.3f}".format(CNC.vars["tlo"])
                    else:
                        self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                    self.tool_drop_down.status_tlo.value = "{:.3f}".format(CNC.vars["tlo"])
                else:
                    self.tool_data_view.main_text = tr._("None")
                    self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                    self.tool_drop_down.status_tlo.value = "N/A"
            else:
                if self.status_index % 2 == 0:
                    self.tool_data_view.minr_text = "TLO: {:.3f}".format(CNC.vars["tlo"])
                else:
                    self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                self.tool_drop_down.status_tlo.value = "{:.3f}".format(CNC.vars["tlo"])
                if CNC.vars["tool"] == 0:
                    self.tool_data_view.main_text = tr._("Probe")
                elif CNC.vars["tool"] == LASER_TOOL_NUMBER:
                    self.tool_data_view.main_text = tr._("Laser")
                elif CNC.vars["tool"] == PROBE_3D_TOOL_NUMBER:
                    self.tool_data_view.main_text = tr._("3DProb")
                else:
                    self.tool_data_view.main_text = "{:.0f}".format(CNC.vars["tool"])
            self.tool_drop_down.status_wpvoltage.value = "{:.2f}v".format(CNC.vars["wpvoltage"])

            self.tool_data_view.active = CNC.vars["atc_state"] in [1, 2, 3]

            # update laser status
            if CNC.vars["lasermode"]:
                if not app.lasering:
                    self.coord_popup.set_config("margin", "active", False)
                    self.coord_popup.set_config("zprobe", "active", False)
                    self.coord_popup.set_config("leveling", "active", False)
                    self.coord_popup.load_config()
                    app.lasering = True
            else:
                app.lasering = False

            # laser drop down UI (spindle/laser top bar content updated above)
            self.laser_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["laserscale"]) + "%"

            # update coordinate system data
            coord_system_index = CNC.vars["active_coord_system"]
            coord_system_name = self.wcs_names[coord_system_index]
            rotation_angle = CNC.vars["rotation_angle"]
            desc_key = coord_system_name.lower().replace(".", "_") + "_description"
            try:
                wcs_description = Config.get("carvera", desc_key).strip()
            except Exception:
                wcs_description = ""
            if wcs_description:
                self.coord_system_data_view.main_text = wcs_description
            else:
                self.coord_system_data_view.main_text = coord_system_name
            self.coord_system_data_view.minr_text = coord_system_name
            self.coord_system_data_view.scale = 80.0 if abs(rotation_angle) > 0.01 else 100.0

            if self.gcode_viewer is not None and self.gcode_viewer.bed_visible:
                self.gcode_viewer.update_bed_wcs()

            # Update WCS Settings popup if it's open
            if hasattr(self, "wcs_settings_popup") and self.wcs_settings_popup.parent:
                self.wcs_settings_popup.update_active_wcs_button(coord_system_name)

            elapsed = now - self.control_list["laser_mode"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    if self.control_list["laser_mode"][1]:
                        self.enable_laser_mode_confirm_popup()
                    else:
                        self.controller.setLaserMode(False)
                    self.control_list["laser_mode"][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.switch.active != CNC.vars["lasermode"]:
                    self.laser_drop_down.switch.set_flag = True
                    self.laser_drop_down.switch.active = CNC.vars["lasermode"]

            elapsed = now - self.control_list["laser_test"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserTest(self.control_list["laser_test"][1])
                    self.control_list["laser_test"][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.test_switch.active != CNC.vars["lasertesting"]:
                    self.laser_drop_down.test_switch.set_flag = True
                    self.laser_drop_down.test_switch.active = CNC.vars["lasertesting"]

            elapsed = now - self.control_list["laser_scale"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserScale(self.control_list["laser_scale"][1])
                    self.control_list["laser_scale"][0] = now - 2
            elif elapsed > 3 and self.laser_drop_down.opened:
                if self.laser_drop_down.scale_slider.value != CNC.vars["laserscale"]:
                    self.laser_drop_down.scale_slider.set_flag = True
                    self.laser_drop_down.scale_slider.value = CNC.vars["laserscale"]

            use_cf_playing_flag = app.is_community_firmware and app.fw_version_digitized >= Utils.digitize_v(
                "2.1.0"
            )  # in community firmware > 2.1.0 the machine state has a is_playing attribute
            if CNC.vars["state"] == NOT_CONNECTED:
                machine_not_playing = True
            elif use_cf_playing_flag:
                machine_not_playing = CNC.vars["is_playing"] == 0
            else:
                machine_not_playing = CNC.vars["playedlines"] <= 0

            # update progress bar and set selected
            if machine_not_playing:
                # not playing - check if we were playing before (interrupted playback)
                if self.played_lines > 0:
                    # Playback was interrupted, update resume at line with last executed line
                    self.update_resume_at_line_from_played_line(
                        self.played_lines, play_percent_from_line(self.played_lines, self.selected_file_line_count)
                    )
                    self.played_lines = 0  # Reset after updating

                app.playing = False
                self.wpb_margin.value = 0
                self.wpb_zprobe.value = 0
                self.wpb_leveling.value = 0
                self.wpb_play.value = 0
                # Stop smooth progress updates
                if self._progress_smooth_clock is not None:
                    self._progress_smooth_clock.cancel()
                    self._progress_smooth_clock = None

                last_job_elapsed = ""
                if CNC.vars["playedseconds"] > 0:
                    last_job_elapsed = " ( {} elapsed )".format(Utils.second2hour(CNC.vars["playedseconds"]))
                if app.selected_remote_filename or app.selected_local_filename:
                    self.progress_info = self._format_file_progress_info(playing=False)
                else:
                    self.progress_info = tr._(" No Remote File Selected") + last_job_elapsed
            else:
                app.playing = True
                if self.played_lines != CNC.vars["playedlines"]:
                    self.played_lines = CNC.vars["playedlines"]
                    self.wpb_play.value = play_percent_from_line(self.played_lines, self.selected_file_line_count)
                    if (
                        app.selected_remote_filename != "" or app.selected_local_filename != ""
                    ) and self.selected_file_line_count > 0:
                        self.gcode_rv.set_selected_line(self.played_lines)
                        self.gcode_viewer.set_distance_by_lineidx(self.played_lines, 0.5)
                        remaining_sec = self.gcode_viewer.get_remaining_time_by_lineidx(self.played_lines, 0.5)
                        if remaining_sec is not None and remaining_sec >= 0:
                            ov_feed = CNC.vars.get("OvFeed", 100) or 100
                            self._remaining_anchor_sec = remaining_sec / (ov_feed / 100.0)
                        elif self.wpb_play.value > 0:
                            self._remaining_anchor_sec = (
                                (100 - self.wpb_play.value) * CNC.vars["playedseconds"] / self.wpb_play.value
                            )
                        elif self.gcode_viewer.total_time > 0:
                            ov_feed = CNC.vars.get("OvFeed", 100) or 100
                            self._remaining_anchor_sec = self.gcode_viewer.total_time / (ov_feed / 100.0)
                        else:
                            self._remaining_anchor_sec = 0.0
                        self._remaining_anchor_time = now
                if (
                    (app.selected_remote_filename != "" or app.selected_local_filename != "")
                    and self.selected_file_line_count > 0
                    and self._progress_smooth_clock is None
                ):
                    self._progress_smooth_clock = Clock.schedule_interval(self._update_progress_smooth, 1.0)
                # playing margin
                if CNC.vars["atc_state"] == 4:
                    self.wpb_margin.value += 14
                    if self.wpb_margin.value >= 84:
                        self.wpb_margin.value = 14
                elif self.wpb_margin.value > 0:
                    self.wpb_margin.value = 84
                # playing zprobe
                if CNC.vars["atc_state"] == 5:
                    self.wpb_zprobe.value += 14
                    if self.wpb_zprobe.value >= 84:
                        self.wpb_zprobe.value = 14
                elif self.wpb_zprobe.value > 0:
                    self.wpb_zprobe.value = 84
                # playing leveling
                if CNC.vars["atc_state"] == 6:
                    self.wpb_leveling.value += 14
                    if self.wpb_leveling.value >= 84:
                        self.wpb_leveling.value = 14
                elif self.wpb_leveling.value > 0:
                    self.wpb_leveling.value = 84

        except:
            logger.error(sys.exc_info()[1])

    # -----------------------------------------------------------------------
    def updateDiagnose(self, *args):
        try:
            now = time.time()

            app = App.get_running_app()
            # control spindle
            self.diagnose_popup.sw_spindle.disabled = CNC.vars["lasermode"]
            self.diagnose_popup.sl_spindle.disabled = CNC.vars["lasermode"]
            elapsed = now - self.control_list["spindle_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(
                        self.control_list["spindle_switch"][1], self.diagnose_popup.sl_spindle.slider.value
                    )
                    self.control_list["spindle_switch"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_spindle.switch.active != CNC.vars["sw_spindle"]:
                    self.diagnose_popup.sw_spindle.set_flag = True
                    self.diagnose_popup.sw_spindle.switch.active = CNC.vars["sw_spindle"]
            elapsed = now - self.control_list["spindle_slider"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(
                        self.diagnose_popup.sw_spindle.switch.active, self.control_list["spindle_slider"][1]
                    )
                    self.control_list["spindle_slider"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindle.slider.value != CNC.vars["sl_spindle"]:
                    self.diagnose_popup.sl_spindle.set_flag = True
                    self.diagnose_popup.sl_spindle.slider.value = CNC.vars["sl_spindle"]

            # control spindle fan
            self.diagnose_popup.sl_spindlefan.disabled = CNC.vars["lasermode"]
            elapsed = now - self.control_list["spindlefan_slider"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindlefanPower(self.control_list["spindlefan_slider"][1])
                    self.control_list["spindlefan_slider"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindlefan.slider.value != CNC.vars["sl_spindlefan"]:
                    self.diagnose_popup.sl_spindlefan.set_flag = True
                    self.diagnose_popup.sl_spindlefan.slider.value = CNC.vars["sl_spindlefan"]

            # control vacuum
            elapsed = now - self.control_list["vacuum_slider"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumPower(self.control_list["vacuum_slider"][1])
                    self.control_list["vacuum_slider"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_vacuum.slider.value != CNC.vars["sl_vacuum"]:
                    self.diagnose_popup.sl_vacuum.set_flag = True
                    self.diagnose_popup.sl_vacuum.slider.value = CNC.vars["sl_vacuum"]

            # control laser mode
            elapsed = now - self.control_list["laser_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    if self.diagnose_popup.sw_laser.switch.active:
                        self.enable_laser_mode_confirm_popup()
                    else:
                        self.controller.setLaserMode(False)
                    self.control_list["laser_switch"][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.switch.active != CNC.vars["lasermode"]:
                    self.laser_drop_down.switch.set_flag = True
                    self.laser_drop_down.switch.active = CNC.vars["lasermode"]

            # control laser slider
            self.diagnose_popup.sl_laser.disabled = not CNC.vars["lasermode"]
            elapsed = now - self.control_list["laser_slider"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserPower(self.control_list["laser_slider"][1])
                    self.control_list["laser_slider"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_laser.slider.value != CNC.vars["sl_laser"]:
                    self.diagnose_popup.sl_laser.set_flag = True
                    self.diagnose_popup.sl_laser.slider.value = CNC.vars["sl_laser"]

            # control light
            elapsed = now - self.control_list["light_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLightSwitch(self.control_list["light_switch"][1])
                    self.control_list["light_switch"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_light.switch.active != CNC.vars["sw_light"]:
                    self.diagnose_popup.sw_light.set_flag = True
                    self.diagnose_popup.sw_light.switch.active = CNC.vars["sw_light"]

            # Update the custom light property to trigger UI updates
            property_obj = self.__class__.__dict__["light_state"]
            property_obj.update_from_state(self)

            # control tool sensor power
            elapsed = now - self.control_list["tool_sensor_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setToolSensorSwitch(self.control_list["tool_sensor_switch"][1])
                    self.control_list["tool_sensor_switch"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_tool_sensor_pwr.switch.active != CNC.vars["sw_tool_sensor_pwr"]:
                    self.diagnose_popup.sw_tool_sensor_pwr.set_flag = True
                    self.diagnose_popup.sw_tool_sensor_pwr.switch.active = CNC.vars["sw_tool_sensor_pwr"]

            # control air
            elapsed = now - self.control_list["air_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setAirSwitch(self.control_list["air_switch"][1])
                    self.control_list["air_switch"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_air.switch.active != CNC.vars["sw_air"]:
                    self.diagnose_popup.sw_air.set_flag = True
                    self.diagnose_popup.sw_air.switch.active = CNC.vars["sw_air"]

            # control pw charge power
            elapsed = now - self.control_list["wp_charge_switch"][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setPWChargeSwitch(self.control_list["wp_charge_switch"][1])
                    self.control_list["wp_charge_switch"][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_wp_charge_pwr.switch.active != CNC.vars["sw_wp_charge_pwr"]:
                    self.diagnose_popup.sw_wp_charge_pwr.set_flag = True
                    self.diagnose_popup.sw_wp_charge_pwr.switch.active = CNC.vars["sw_wp_charge_pwr"]

            # update states
            self.diagnose_popup.st_x_min.state = CNC.vars["st_x_min"]
            self.diagnose_popup.st_x_max.state = CNC.vars["st_x_max"]
            self.diagnose_popup.st_y_min.state = CNC.vars["st_y_min"]
            self.diagnose_popup.st_y_max.state = CNC.vars["st_y_max"]
            self.diagnose_popup.st_z_max.state = CNC.vars["st_z_max"]
            self.diagnose_popup.st_cover.state = CNC.vars["st_cover"]
            self.diagnose_popup.st_probe.state = CNC.vars["st_probe"]
            self.diagnose_popup.st_calibrate.state = CNC.vars["st_calibrate"]
            self.diagnose_popup.st_atc_home.state = CNC.vars["st_atc_home"]
            self.diagnose_popup.st_tool_sensor.state = CNC.vars["st_tool_sensor"]
            self.diagnose_popup.st_e_stop.state = CNC.vars["st_e_stop"]
        except:
            logger.error(sys.exc_info()[1])

    def update_control(self, name, value):
        if name in self.control_list:
            self.control_list[name][0] = time.time()
            self.control_list[name][1] = value
        if name == "laser_mode" and not value:
            if self.laser_drop_down.opened:
                self.laser_drop_down.dismiss()
                self.laser_drop_down.opened = False
            # Keep ToolDropDown laser switch in sync so it shows off when disabled from LaserDropDown
            self.tool_drop_down.ids.switch.set_flag = True
            self.tool_drop_down.ids.switch.active = False

    def moveLineIndex(self, up=True):
        if up:
            self.test_line = self.test_line - 1
        else:
            self.test_line = self.test_line + 1
        if self.test_line == 0:
            self.test_line = 1
        self.gcode_rv.set_selected_line(self.test_line - 1)

    def execCallback(self, line):
        logger.info(f"MDI Sent: {line}")
        entries = [
            {
                "text": cmd,
                "color": (200 / 255, 200 / 255, 200 / 255, 1),
                "entry_type": "command",
            }
            for cmd in line.strip().split("\n")
        ]
        self._append_to_mdi(entries, scroll_to_bottom=True)

    def _format_mdi_entry(self, entry):
        """Syntax-highlight sent MDI commands; keep machine output in status colors."""
        text = str(entry.get("text") or "")
        original_color = tuple(entry.get("original_color") or entry.get("color") or (1, 1, 1, 1))
        plain = text.strip()
        color = original_color
        entry_type = entry.get("entry_type")
        if entry_type is not None:
            should_highlight = entry_type == "command"
        elif "highlight" in entry:
            should_highlight = bool(entry.get("highlight"))
        else:
            # Compatibility with MDI history entries saved before entry_type existed.
            should_highlight = tuple(original_color[:3]) == (200 / 255, 200 / 255, 200 / 255)
        entry_type = "command" if should_highlight else "output"
        hl_enabled = getattr(self, "gcode_highlight_enabled", False)
        hl_colors = getattr(self, "gcode_highlight_colors", None)
        if hl_enabled and should_highlight and plain:
            highlighted = highlight_mdi_line(plain, hl_colors)
            if "[color=" in highlighted:
                color = (1.0, 1.0, 1.0, 1.0)
        else:
            highlighted = escape_gcode_markup(plain)
        formatted = dict(entry)
        formatted["text"] = text
        formatted["highlighted_text"] = highlighted
        formatted["color"] = color
        formatted["original_color"] = original_color
        formatted["entry_type"] = entry_type
        formatted["highlight"] = should_highlight
        return formatted

    @mainthread
    def _append_to_mdi(self, entries, log_to_mdi_data=False, scroll_to_bottom=False):
        self.manual_rv.data.extend([self._format_mdi_entry(entry) for entry in entries])
        if log_to_mdi_data:
            App.get_running_app().mdi_data.extend(entries)
        if scroll_to_bottom:
            Clock.schedule_once(lambda dt: setattr(self.manual_rv, "scroll_y", 0), 0)

    # -----------------------------------------------------------------------
    def openUSB(self, device):
        # Serial open + DTR reset sleeps (~1s) + protocol probe must not run on the UI thread.
        if getattr(self, "_usb_connect_in_progress", False):
            return
        self._usb_connect_in_progress = True
        self.heartbeat_time = time.time()
        self.status_drop_down.select("")
        # Keep VID:PID + serial in sync even when reconnecting by resolved path.
        self._store_usb_device_id_for_path(device)
        label = device
        for entry in Utils.list_identifiable_usb_devices():
            if Utils.same_usb_device_path(entry["device_path"], device):
                label = entry["label"]
                break
        Clock.schedule_once(
            partial(self.progressStart, tr._("Connecting via USB...\n%s") % label, None),
            0,
        )
        threading.Thread(target=self._open_usb_worker, args=(device,), daemon=True).start()

    def _open_usb_worker(self, device):
        success = False
        error_message = None
        try:
            success = bool(self.controller.open(CONN_USB, device))
            self.controller.connection_type = CONN_USB
        except Exception as exc:
            logger.exception("USB connection failed for %s", device)
            error_message = str(exc)
            success = False
        Clock.schedule_once(lambda dt, ok=success, err=error_message: self._finish_usb_open(ok, err), 0)

    def _finish_usb_open(self, success, error_message=None):
        self._usb_connect_in_progress = False
        if self.progress_popup._is_open:
            self.progress_popup.dismiss()
        if success:
            self.heartbeat_time = time.time()
            self._remember_connection_method("usb")
            # Fallback: attempt baud upgrade after 10s if version is > 2.1.0c and conditions met
            Clock.schedule_once(self.attempt_usb_baud_upgrade_if_eligible, 10)
        else:
            logger.error("USB connection attempt finished without an active link")
            if error_message:
                self.show_message_popup(error_message, False)
        self.updateStatus()

    def attempt_usb_baud_upgrade_if_eligible(self, dt):
        """If on USB, firmware >= 2.1.0, and use_higher_baud is on, request higher baud."""
        app = App.get_running_app()
        if self.controller.connection_type != CONN_USB or self.controller.stream != self.controller.usb_stream:
            return
        if self.controller._baud_upgrade_attempted:
            return
        # Never interrupt framed file transfer / config download with a baud switch.
        if self.downloading or self.downloading_config or self.uploading:
            Clock.schedule_once(self.attempt_usb_baud_upgrade_if_eligible, 1.0)
            return
        if self.controller.paused or self.controller.sendNUM != 0 or self.controller.loadNUM != 0:
            Clock.schedule_once(self.attempt_usb_baud_upgrade_if_eligible, 1.0)
            return
        if not app.is_community_firmware or not self.fw_version or app.fw_version_digitized < Utils.digitize_v("2.1.0"):
            return
        use_higher_val = Config.get("carvera", "use_higher_baud", fallback="0")
        use_higher = str(use_higher_val).lower() in ("1", "true", "yes", "on")
        baud_str = Config.get("carvera", "usb_baud_rate", fallback="115200")
        if use_higher and baud_str and int(baud_str) != 115200:
            baud = int(baud_str)
            self.controller._baud_upgrade_attempted = True
            threading.Thread(
                target=self.controller.request_baud_upgrade,
                args=(baud,),
                daemon=True,
            ).start()

    # -----------------------------------------------------------------------
    def openWIFI(self, address):
        try:
            if self.controller.open(CONN_WIFI, address):
                self.controller.connection_type = CONN_WIFI
                self.store_machine_address(address.split(":")[0])
                self._remember_connection_method("wifi")
        except Exception:
            logger.error(sys.exc_info()[1])
        self.updateStatus()
        self.status_drop_down.select("")

    # -----------------------------------------------------------------------
    def connWIFI(self, ssid):
        if ssid == "":
            self.controller.disconnectWiFiCommand()
        else:
            # open wifi conection popup window
            self.input_popup.cache_var1 = ssid
            self.open_wifi_password_input_popup()

    # -----------------------------------------------------------------------
    def close(self):
        try:
            self.controller.close_manual()
        except:
            logger.error(sys.exc_info()[1])
        self.updateStatus()

    # -----------------------------------------------------------------------
    def _clear_machine_settings_panels(self):
        """Remove Machine-* settings tabs from a previous model so they can be rebuilt."""
        settings = self.config_popup.settings_panel
        interface = getattr(settings, "interface", None)
        content = getattr(interface, "content", None) if interface is not None else None
        if content is None:
            self.machine_settings_model = None
            return

        menu = getattr(interface, "menu", None)
        machine_uids = [uid for uid, panel in list(content.panels.items()) if panel.config is self.config]
        if not machine_uids:
            self.machine_settings_model = None
            return

        remaining = next(
            (uid for uid, panel in content.panels.items() if panel.config is not self.config),
            None,
        )
        if getattr(content, "current_uid", None) in machine_uids:
            if remaining is not None:
                content.current_uid = remaining
                if menu is not None:
                    menu.selected_uid = remaining
            else:
                if content.current_panel is not None:
                    try:
                        content.remove_widget(content.current_panel)
                    except Exception:
                        pass
                content.current_panel = None
                content.current_uid = 0

        for uid in machine_uids:
            content.panels.pop(uid, None)
            buttons_layout = getattr(menu, "buttons_layout", None) if menu is not None else None
            if buttons_layout is not None:
                for child in list(buttons_layout.children):
                    if getattr(child, "uid", None) == uid:
                        buttons_layout.remove_widget(child)

        for section in list(self.config.sections()):
            self.config.remove_section(section)
        self.machine_settings_model = None
        self.setting_type_list.clear()

    # -----------------------------------------------------------------------
    def load_machine_config(self):
        app = App.get_running_app()
        panels = self.config_popup.settings_panel.interface.content.panels

        # Filter panels that are bound to the machine config
        machine_panels = [panel for panel in panels.values() if panel.config is self.config]
        same_model = bool(machine_panels) and self.machine_settings_model == getattr(app, "model", None)

        if same_model:
            # already have panels, update data
            for panel in machine_panels:
                children = panel.children
                for child in children:
                    if isinstance(child, SettingItem):
                        if child.key in self.setting_list:
                            new_value = self.setting_list[child.key]
                            if child.key in self.setting_type_list:
                                if self.setting_type_list[child.key] == "bool":
                                    new_value = "1" if new_value == "true" else "0"
                                elif self.setting_type_list[child.key] == "numeric":
                                    new_value = new_value + ".0" if new_value.isdigit() else new_value
                            if new_value != child.value:
                                child.value = new_value
                        elif child.key in self.setting_default_list:
                            new_value = self.setting_default_list[child.key]
                            self.setting_change_list[child.key] = new_value
                            if new_value != child.value:
                                child.value = new_value
                            # This warning message doesn't make sense since settings values not in config.txt will just use the firmware default value.
                            #
                            # Until functionality is added to the firmware to output the complete settings values we should not display such messages
                            #
                            # self.controller.log.put(
                            #     (Controller.MSG_NORMAL, 'Can not load config, Key: {}'.format(child.key)))

                        # restore/default are used for default config management
                        # carvera/graphics options are managed via Controller settings (not here)
                        # backup is a one-shot operation and not a setting to be stored
                        elif child.section.lower() not in [
                            "restore",
                            "default",
                            "backup",
                            "carvera",
                            "graphics",
                            "kivy",
                        ]:
                            self.controller.log.put(
                                (Controller.MSG_ERROR, tr._("Load config error, Key:") + f" {child.key}")
                            )
                            logger.warning("Load config error, Key:" + f" {child.key}")
                            # self.controller.close()
                            self.updateStatus()
                            return False
        else:
            if machine_panels:
                self._clear_machine_settings_panels()

            data = self.load_machine_config_data()
            if data is None:
                return True

            basic_config = []
            advanced_config = []
            restore_config = []
            backup_config = []
            self.setting_type_list.clear()
            for setting in data:
                if "key" in setting and "default" in setting:
                    self.setting_default_list[setting["key"]] = setting["default"]
                if "type" in setting:
                    has_setting = False
                    if setting["type"] != "title":
                        if "key" in setting and "section" in setting and setting["key"] in self.setting_list:
                            has_setting = True
                            self.config.setdefaults(
                                setting["section"],
                                {setting["key"]: Utils.from_config(setting["type"], self.setting_list[setting["key"]])},
                            )
                            self.setting_type_list[setting["key"]] = setting["type"]
                        elif "default" in setting:
                            has_setting = True
                            self.config.setdefaults(
                                setting["section"],
                                {setting["key"]: Utils.from_config(setting["type"], setting["default"])},
                            )
                            self.setting_type_list[setting["key"]] = setting["type"]
                            self.setting_change_list[setting["key"]] = setting["default"]
                            # This warning message doesn't make sense since settings values not in config.txt will just use the firmware default value.
                            #
                            # Until functionality is added to the firmware to output the complete settings values we should not display such messages
                            #
                            # self.controller.log.put(
                            #     (Controller.MSG_NORMAL, 'Can not load config, Key: {}'.format(setting['key'])))
                        elif setting["key"].lower() not in ["restore", "default", "backup"]:
                            self.controller.log.put(
                                (Controller.MSG_ERROR, "Load config error, Key: {}".format(setting["key"]))
                            )
                            self.updateStatus()
                            logger.warning("Load config error, Key: {}".format(setting["key"]))
                            # self.controller.close()
                            return False
                    else:
                        has_setting = True
                    # construct json objects
                    if has_setting:
                        panel_setting = setting.copy()
                        if "section" in setting and setting["section"] == "Basic":
                            basic_config.append(panel_setting)
                        elif "section" in setting and setting["section"] == "Advanced":
                            advanced_config.append(panel_setting)
                    elif "section" in setting and setting["section"] == "Restore":
                        self.config.setdefaults(
                            setting["section"], {setting["key"]: Utils.from_config(setting["type"], "")}
                        )
                        restore_config.append(setting.copy())
                    elif "section" in setting and setting["section"] == "Backup":
                        self.config.setdefaults(
                            setting["section"], {setting["key"]: Utils.from_config(setting["type"], "")}
                        )
                        backup_config.append(setting.copy())
            # clear title section
            for basic in basic_config:
                if basic["type"] == "title" and "section" in basic:
                    basic.pop("section")
                elif "default" in basic:
                    basic.pop("default")
            for advanced in advanced_config:
                if advanced["type"] == "title" and "section" in advanced:
                    advanced.pop("section")
                elif "default" in advanced:
                    advanced.pop("default")
            self.config_popup.settings_panel.add_json_panel(
                "Machine - Basic", self.config, data=json.dumps(basic_config)
            )
            self.config_popup.settings_panel.add_json_panel(
                "Machine - Advanced", self.config, data=json.dumps(advanced_config)
            )
            self.config_popup.settings_panel.add_json_panel(
                "Machine - Restore", self.config, data=json.dumps(restore_config)
            )
            if backup_config and kivy_platform not in ["android", "ios"]:
                self.config_popup.settings_panel.add_json_panel(
                    "Machine - Backup", self.config, data=json.dumps(backup_config)
                )
            self.machine_settings_model = getattr(app, "model", None)
        return True

    # -----------------------------------------------------------------------
    def toggle_jog_mode(self):
        if self.controller.jog_mode == Controller.JOG_MODE_STEP:
            self.update_ui_for_jog_mode_cont()

        elif self.controller.jog_mode == Controller.JOG_MODE_CONTINUOUS:
            self.update_ui_for_jog_mode_step()

    def update_ui_for_jog_mode_step(self):
        self.controller.setJogMode(Controller.JOG_MODE_STEP)
        self.ids.jog_mode_btn.text = tr._("Jog Mode:Step")
        App.get_running_app().jog_mode_text = tr._("Jog Mode:Step")
        self.ids.step_xy.disabled = False
        self.ids.step_a.disabled = False
        self.ids.step_z.disabled = False
        self.probing_popup.ids.step_xy.disabled = False
        self.probing_popup.ids.step_a.disabled = False
        self.probing_popup.ids.step_z.disabled = False
        self.update_pendant_jog_text()

    def update_ui_for_jog_mode_cont(self):
        self.controller.setJogMode(Controller.JOG_MODE_CONTINUOUS)
        self.ids.jog_mode_btn.text = tr._("Jog Mode:Continuous")
        App.get_running_app().jog_mode_text = tr._("Jog Mode:Continuous")
        self.ids.step_xy.disabled = True
        self.ids.step_a.disabled = True
        self.ids.step_z.disabled = True
        self.probing_popup.ids.step_xy.disabled = True
        self.probing_popup.ids.step_a.disabled = True
        self.probing_popup.ids.step_z.disabled = True
        self.update_pendant_jog_text()

    def _popup_prevents_jogging(self):
        modals = [self.probing_popup]
        if self.cmm_workbench_popup is not None:
            modals.append(self.cmm_workbench_popup)
        return self._is_popup_open() and not any(m.allows_external_jog() for m in modals)

    def _bind_jog_control_deps(self):
        app = App.get_running_app()
        if app is not None:
            app.bind(
                state=self.update_jog_controls_enabled,
                playing=self.update_jog_controls_enabled,
                spindle_or_laser_is_on=self.update_jog_controls_enabled,
            )
        self.update_jog_controls_enabled()

    def update_jog_controls_enabled(self, *args):
        app = App.get_running_app()
        if app is None:
            return
        app.jog_controls_enabled = self._machine_allows_jogging()

    def _machine_allows_jogging(self):
        app = App.get_running_app()
        return (
            (not app.playing or app.state == "Pause")
            and (
                app.state in ["Idle", "Pause"]
                or (app.state == "Run" and self.allow_jogging_while_machine_running == "1")
            )
            and (not app.spindle_or_laser_is_on or self.allow_jogging_while_spindle_on == "1")
        )

    def is_jogging_enabled(self):
        # Keyboard/pendant jogging is normally blocked whenever a modal popup is open,
        # except for probing and the probe-scan jog overlay (see allows_external_jog).
        return self._machine_allows_jogging() and not self._popup_prevents_jogging()

    def is_pendant_jogging_enabled(self):
        # If the user disabled pendant, respect it.
        if not App.get_running_app().root.pendant_jog_control:
            return False
        # ...otherwise behave as any other jogging except when probing screen is
        # open. We want to use the pendant as a convenient way to get to the
        # initial probing location
        return self.is_jogging_enabled()

    def restore_keyboard_jog_control(self):
        prev = getattr(self, "_pre_modal_keyboard_jog", None)
        if prev is None:
            return
        if self.keyboard_jog_control != prev:
            self.toggle_keyboard_jog_control()
        self._pre_modal_keyboard_jog = None

    def toggle_keyboard_jog_control(self, disable=False):
        app = App.get_running_app()
        app.root.keyboard_jog_control = not app.root.keyboard_jog_control  # toggle the boolean
        if disable:
            app.root.keyboard_jog_control = False

        if app.root.keyboard_jog_control:
            Window.bind(on_key_down=self._keyboard_jog_keydown, on_key_up=self._keyboard_jog_keyup)
            app.jog_keyboard_enable = "down"
        else:
            Window.unbind(on_key_down=self._keyboard_jog_keydown, on_key_up=self._keyboard_jog_keyup)
            app.jog_keyboard_enable = "normal"

    def toggle_pendant_jog_control(self):
        app = App.get_running_app()
        app.root.pendant_jog_control = not app.root.pendant_jog_control

        if app.root.pendant_jog_control:
            app.jog_pendant_enable = "down"
        else:
            app.jog_pendant_enable = "normal"
        # self.ids.pendant_jogging_en_btn.state = app.jog_pendant_enable

    def setup_pendant(self):
        self.handle_pendant_disconnected()
        if self.controller.continuous_jog_active and self.controller.stream is not None:
            self.controller.executeRealtime(0x19)
        self.controller._clear_continuous_jog_state()

        type_name = Config.get("carvera", "pendant_type")
        pendant_type = SUPPORTED_PENDANTS.get(type_name, SUPPORTED_PENDANTS["None"])

        def get_feed():
            return self.feed_drop_down.scale_slider.value

        def set_feed(val):
            self.feed_drop_down.scale_slider.value = val

        feed_override = OverrideController(get_feed, set_feed, min_limit=10, max_limit=300, step=10)

        def get_spindle():
            return self.spindle_drop_down.scale_slider.value

        def set_spindle(val):
            self.spindle_drop_down.scale_slider.value = val

        spindle_override = OverrideController(get_spindle, set_spindle, min_limit=10, max_limit=300, step=10)

        self.pendant = pendant_type(
            self.controller,
            self.cnc,
            feed_override,
            spindle_override,
            self.is_pendant_jogging_enabled,
            self.handle_pendat_run_pause_resume,
            self.handle_pendant_probe_z,
            self.handle_pendant_open_probing_popup,
            self.handle_pendant_connected,
            self.handle_pendant_disconnected,
            self.handle_pendant_button_press,
        )

        if self.controller.jog_mode == Controller.JOG_MODE_CONTINUOUS:
            self.update_ui_for_jog_mode_cont()
        else:
            self.update_ui_for_jog_mode_step()

    def refresh_pendant_settings(self):
        self.pendant_jogging_default = Config.getboolean("carvera", "pendant_jogging_default", fallback=True)
        self.pendant_probe_z_alt_cmd = Config.getboolean("carvera", "pendant_probe_z_alt_cmd", fallback=False)

    def handle_pendant_connected(self):
        self.ids.pendant_jogging_en_btn.disabled = False
        app = App.get_running_app()
        app.jog_pendant_text = tr._("Pendant Jogging")
        self.update_pendant_jog_text()
        app.jog_pendant_enable = "down" if self.pendant_jogging_default else "normal"
        app.root.pendant_jog_control = self.pendant_jogging_default

    def handle_pendant_disconnected(self):
        app = App.get_running_app()
        app.jog_pendant_text = tr._("No Pendant")
        app.jog_pendant_enable = "normal"
        if app.root:
            app.root.pendant_jog_control = False

        self.ids.pendant_jogging_en_btn.disabled = True

    def handle_pendat_run_pause_resume(self):
        app = App.get_running_app()
        if app.state == "Pause":
            self.controller.resumeCommand()
        elif app.state == "Alarm":
            self.unlockMachine()
        else:
            self.controller.suspendCommand()

    def handle_pendant_open_probing_popup(self):
        self.open_probing_popup()
        # self.probing_popup.open()

    def handle_pendant_probe_z(self):
        if self.pendant_probe_z_alt_cmd:
            if self.controller.is_community_firmware:
                self.controller.executeCommand("M466 Z-200 S2")
            else:
                self.controller.executeCommand("G38.2 Z-200")
        else:
            # self.probing_popup.open()
            self.open_probing_popup()

    def update_pendant_jog_text(self):
        app = App.get_running_app()
        if not self.ids.pendant_jogging_en_btn.disabled:
            if hasattr(self, "pendant") and hasattr(self.pendant, "current_step_size"):
                if self.controller.jog_mode == self.controller.JOG_MODE_CONTINUOUS:
                    percent = int(self.pendant.STEP_SIZE_SPEED_FRACTION[self.pendant.current_step_size] * 100)
                    app.jog_pendant_text = tr._("Pendant Jogging") + f" ({percent}%)"
                else:
                    app.jog_pendant_text = tr._("Pendant Jogging") + f" ({self.pendant.current_step_size:g}mm)"
            else:
                app.jog_pendant_text = tr._("Pendant Jogging")

    def handle_pendant_button_press(self, button_action: str):
        """
        Handle UI updates when pendant buttons are pressed.
        This method can be customized to update specific UI elements
        based on the button action.
        """
        app = App.get_running_app()

        # Update jog mode button text if jog mode changed
        if button_action in ["mode_continuous", "mode_step"]:
            if button_action == "mode_continuous":
                self.update_ui_for_jog_mode_cont()
            elif button_action == "mode_step":
                self.update_ui_for_jog_mode_step()
        elif button_action == "step_size_changed":
            self.update_pendant_jog_text()

    def _is_popup_open(self):
        """Checks to see if any of the popups objects are open."""
        popups_to_check = [
            self.file_popup._is_open,
            self.coord_popup._is_open,
            self.xyz_probe_popup._is_open,
            self.pairing_popup._is_open,
            self.upgrade_popup._is_open,
            self.language_popup._is_open,
            self.diagnose_popup._is_open,
            self.confirm_popup._is_open,
            self.unlock_popup._is_open,
            self.message_popup._is_open,
            self.progress_popup._is_open,
            self.input_popup._is_open,
            self.config_popup._is_open,
            self.probing_popup._is_open,
            (self.cmm_workbench_popup._is_open if self.cmm_workbench_popup is not None else False),
            self.facing_popup._is_open,
        ]

        return any(popups_to_check)

    def bind_light_toggle_to_property(self):
        """Bind the light toggle button state to the LightProperty"""
        self.bind(light_state=self._on_light_state_changed)

        # Trigger an initial update by accessing the property object directly
        property_obj = self.__class__.__dict__["light_state"]
        property_obj.update_from_state(self)

    def _on_light_state_changed(self, instance, value):
        """Handle changes in the LightProperty and update the light toggle button"""
        new_state = "down" if value else "normal"
        self.ids.light_toggle.state = new_state

    def refresh_light_state(self):
        """Manually refresh the light state from CNC.vars"""
        if hasattr(self, "light_state"):
            property_obj = self.__class__.__dict__["light_state"]
            property_obj.update_from_state(self)
            logger.debug("Light state manually refreshed from CNC.vars")

    def _global_keyboard_keydown(self, window, key, scancode, codepoint, modifiers):
        COMMA_KEY = 44
        M_KEY = 109
        cmd_mod = "meta" if sys.platform == "darwin" else "ctrl"

        # Cmd+Comma (macOS) or Ctrl+Comma (Windows/Linux) to open settings
        if key == COMMA_KEY and cmd_mod in modifiers:
            if not self._is_popup_open() and not self.manual_cmd.focus:
                self.config_popup.open()
                return True

        # Ctrl+M to open manual command (MDI) page
        if key == M_KEY and "ctrl" in modifiers:
            self.content.transition.direction = "right"
            self.content.current = "File"
            self.cmd_manager.transition.direction = "left"
            self.cmd_manager.current = "manual_cmd_page"
            self.manual_cmd.focus = True

        return False

    def _keyboard_jog_keydown(self, *args):
        app = App.get_running_app()

        # Only allow keyboard jogging when machine in a suitable state and has no popups open
        if self.is_jogging_enabled() and not self.manual_cmd.focus:
            key = args[1]  # keycode

            if app.root.controller.jog_mode == Controller.JOG_MODE_STEP:
                if key in self._held_jog_keys:
                    # Ignore - only move once per keypress in step mode
                    return
                if key in (273, 274, 275, 276, 280, 281):
                    self._held_jog_keys.add(key)

            if key == 274:  # down button
                app.root.controller.jog(f"Y{'-' if app.invert_y_axis_jogging else ''}{app.root.step_xy.text}")
            elif key == 273:  # up button
                app.root.controller.jog(f"Y{'' if app.invert_y_axis_jogging else '-'}{app.root.step_xy.text}")
            elif key == 275:  # right button
                app.root.controller.jog(f"X{app.root.step_xy.text}")
            elif key == 276:  # left button
                app.root.controller.jog(f"X-{app.root.step_xy.text}")
            elif key == 280:  # page up
                app.root.controller.jog(f"Z{app.root.step_z.text}")
            elif key == 281:  # page down
                app.root.controller.jog(f"Z-{app.root.step_z.text}")

    def _keyboard_jog_keyup(self, *args):
        app = App.get_running_app()
        key = args[1]  # keycode
        if key in (273, 274, 275, 276, 280, 281):  # only if a jog button is released
            self._held_jog_keys.discard(key)
            app.root.controller.stopContinuousJog()

    def apply_setting_changes(self):
        if self.setting_change_list:
            self.apply_machine_setting_changes()
        if self.controller_setting_change_list:
            self.apply_controller_setting_changes()

    def apply_machine_setting_changes(self):
        for key in self.setting_change_list:
            self.controller.setConfigValue(key, self.setting_change_list[key])
            time.sleep(0.1)
        self.setting_change_list.clear()
        self.config_popup.btn_apply.disabled = True
        self.message_popup.lb_content.text = tr._("Settings applied, need machine reset to take effect !")
        self.message_popup.open()

    def apply_controller_setting_changes(self):
        if self.controller_setting_change_list.get("ui_density_override") or self.controller_setting_change_list.get(
            "ui_density"
        ):
            self.message_popup.lb_content.text = tr._("UI Density changed, restart application to apply.")
            self.message_popup.open()

        if (
            self.controller_setting_change_list.get("allow_mdi_while_machine_running")
            != self.allow_mdi_while_machine_running
        ):
            self.allow_mdi_while_machine_running = self.controller_setting_change_list.get(
                "allow_mdi_while_machine_running"
            )

        if "allow_jogging_while_machine_running" in self.controller_setting_change_list:
            self.allow_jogging_while_machine_running = self.controller_setting_change_list[
                "allow_jogging_while_machine_running"
            ]

        if "allow_jogging_while_spindle_on" in self.controller_setting_change_list:
            self.allow_jogging_while_spindle_on = self.controller_setting_change_list["allow_jogging_while_spindle_on"]

        if (
            "allow_jogging_while_machine_running" in self.controller_setting_change_list
            or "allow_jogging_while_spindle_on" in self.controller_setting_change_list
        ):
            self.update_jog_controls_enabled()

        if self.controller_setting_change_list.get("invert_y_axis_jogging"):
            App.get_running_app().invert_y_axis_jogging = (
                self.controller_setting_change_list.get("invert_y_axis_jogging") == "1"
            )

        if self.controller_setting_change_list.get("show_tooltips"):
            App.get_running_app().show_tooltips = self.controller_setting_change_list.get("show_tooltips") != "0"

        if self.controller_setting_change_list.get("tooltip_delay"):
            delay_value = float(self.controller_setting_change_list.get("tooltip_delay"))
            App.get_running_app().tooltip_delay = delay_value if delay_value > 0 else 0.5

        if self.controller_setting_change_list.get("active_color"):
            App.get_running_app().active_color = self._parse_active_color(
                self.controller_setting_change_list.get("active_color")
            )

        pendant_changed = any(
            k == "pendant_type" or k.startswith("gamepad_") for k in self.controller_setting_change_list
        )

        if any(
            k in self.controller_setting_change_list for k in ("pendant_jogging_default", "pendant_probe_z_alt_cmd")
        ):
            self.refresh_pendant_settings()

        if pendant_changed:
            self.pendant.close()
            self.setup_pendant()

        self._update_macro_button_text()

        self.config_popup.btn_apply.disabled = True

        # Configure logging level from config
        if "log_level" in self.controller_setting_change_list:
            log_level = Config.get("kivy", "log_level").upper()
            if log_level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
                logging.getLogger().setLevel(getattr(logging, log_level))
                logger.info(f"Log level set to {log_level}")

        if "log_sent_receive" in self.controller_setting_change_list:
            self.controller.log_sent_receive = self.controller_setting_change_list.get("log_sent_receive")

        if "high_precision_reamining_time_estimate" in self.controller_setting_change_list:
            raw_enabled = self.controller_setting_change_list.get("high_precision_reamining_time_estimate")
            if isinstance(raw_enabled, str):
                enabled = raw_enabled not in ("0", "false", "False", "")
            else:
                enabled = bool(raw_enabled)
            self.gcode_viewer.high_precision_time_estimate = enabled
            if enabled:
                if self.gcode_viewer.raw_linenumbers and self.gcode_viewer.raw_feed_rates:
                    self.gcode_viewer._compute_line_times_async()
                else:
                    self.refresh_gcode_color_legend()
            else:
                self.gcode_viewer.line_times = []
                self.gcode_viewer.total_time = 0.0
                self.gcode_viewer._invalidate_legend_durations()
                self.gcode_viewer._begin_line_times_job(show_progress=False)
                self.refresh_gcode_color_legend()
                self._refresh_idle_progress_info()

        gcode_hl_changed = False
        if "gcode_highlight_enabled" in self.controller_setting_change_list:
            self.gcode_highlight_enabled = self.controller_setting_change_list["gcode_highlight_enabled"] not in (
                "0",
                "false",
                "False",
            )
            gcode_hl_changed = True
        for cat in GCODE_DEFAULT_COLORS:
            config_key = f"gcode_color_{cat}"
            if config_key in self.controller_setting_change_list:
                self.gcode_highlight_colors[cat] = self._config_color_to_hex(
                    self.controller_setting_change_list[config_key]
                )
                gcode_hl_changed = True
        if gcode_hl_changed:
            app = App.get_running_app()
            if hasattr(self, "gcode_rv") and self.gcode_rv.data:
                self.load_page(app.curr_page)
            if hasattr(self, "manual_rv") and self.manual_rv.data:
                self.manual_rv.data = [self._format_mdi_entry(entry) for entry in self.manual_rv.data]

        if "show_playbar_tool_change_markers" in self.controller_setting_change_list:
            raw_enabled = self.controller_setting_change_list["show_playbar_tool_change_markers"]
            self.show_playbar_tool_change_markers = raw_enabled not in ("0", "false", "False")
            self._apply_tool_change_markers()

        self.controller_setting_change_list.clear()

    # -----------------------------------------------------------------------
    def open_setting_restore_confirm_popup(self):
        self.confirm_popup.lb_title.text = tr._("Restore Settings")
        self.confirm_popup.lb_content.text = tr._("Confirm to restore settings from default ?")
        self.confirm_popup.confirm = partial(self.restoreSettings)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def restoreSettings(self):
        self.controller.restoreConfigCommand()

    def enter_laser_mode(self):
        self.controller.setLaserMode(True)

    # -----------------------------------------------------------------------
    def open_setting_default_confirm_popup(self):
        self.confirm_popup.lb_title.text = tr._("Save As Default")
        self.confirm_popup.lb_content.text = tr._("Confirm to save current settings as default ?")
        self.confirm_popup.confirm = partial(self.defaultSettings)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    def enable_laser_mode_confirm_popup(self):
        self.confirm_popup.size_hint = (0.6, 0.7)
        self.confirm_popup.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        self.confirm_popup.lb_title.text = tr._("Entering Laser Mode")
        self.confirm_popup.lb_title.size_hint_y = None
        self.confirm_popup.lb_content.text = tr._(
            "You are about to enable laser mode. \n\nWhen enabled the current tool will be dropped, the spindle fan locked to 90%, \nand the empty spindle nose will be set as the tool and length probed.\n\n It's recommended to remove the laser dust cap, and put on safety glasses now.\n\nAre you ready to proceed ?"
        )
        self.confirm_popup.confirm = partial(self.enter_laser_mode)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def _resume_gcode_lines_available(self):
        app = App.get_running_app()
        key = app.selected_remote_filename or app.selected_local_filename
        return (
            bool(key)
            and bool(getattr(self, "lines", None))
            and key == self._last_loaded_file_key
            and not self.loading_file
            and self.selected_file_line_count > 0
        )

    def _show_resume_gcode_not_loaded_popup(self):
        self.show_message_popup(
            tr._(
                "The gcode for this job is not loaded in the controller, or a different file is loaded.\n"
                "Open the file again from the file browser (download or upload as needed), then retry resume-at-line."
            ),
            False,
        )

    def _resume_playback_warning_text(self, warning_keys):
        """Build translated warning text for missing resume recovery state."""
        messages = {
            "tool_change": tr._("- No tool change (M6)"),
            "feed": tr._("- No feed rate (F)"),
            "spindle_speed": tr._("- No spindle speed (M3 S...)"),
        }
        lines = [messages[key] for key in warning_keys if key in messages]
        if not lines:
            return ""
        return (
            tr._("WARNING: The resume recovery sequence was unable to find important state prior to the resume line:\n")
            + "\n".join(lines)
            + "\n"
        )

    def open_resume_playback_confirm_popup(self, file_name, start_line):
        if self.confirm_popup.showing:
            return

        if not self._resume_gcode_lines_available():
            self._show_resume_gcode_not_loaded_popup()
            return

        try:
            commands = self.controller.playStartLineCommand(
                file_name, start_line, preview=True, lines=self.lines, has_ocodes=self.file_has_ocodes
            )
        except Exception as e:
            self.show_message_popup(tr._(f"Resume-at-line cannot run:\n\n{e}"), False)
            return
        commands_preview = "\n".join(commands)
        warning_text = self._resume_playback_warning_text(self.controller.resume_playback_warnings(commands))

        self.confirm_popup.size_hint = (0.8, 0.8)
        self.confirm_popup.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        self.confirm_popup.lb_title.text = tr._("Resume Playback")
        self.confirm_popup.lb_title.size_hint_y = None
        self.confirm_popup.lb_content.halign = "left"
        self.confirm_popup.lb_content.text = (
            warning_text
            + tr._(
                "The Controller will run the below commands to restart this file. Please be prepared to e-stop your machine if it doesn't move as expected.\n\n"
            )
            + commands_preview
        )
        self.confirm_popup.confirm = partial(self.execute_play_with_start_line, file_name, start_line)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def execute_play_with_start_line(self, file_name, start_line):
        """Execute play command with start_line after user confirmation"""
        if not self._resume_gcode_lines_available():
            self._show_resume_gcode_not_loaded_popup()
            return
        try:
            self.controller.playStartLineCommand(
                file_name, start_line, lines=self.lines, has_ocodes=self.file_has_ocodes
            )
        except Exception as e:
            self.show_message_popup(tr._(f"Resume-at-line failed:\n\n{e}"), False)

    # -----------------------------------------------------------------------
    def update_resume_at_line_from_played_line(self, line_number, percent_complete):
        """Update the resume at line input with the last executed line number -1 for the incompletely executed line"""

        if percent_complete >= 98:  # if close enough to end of file consider it as complete and clear resume
            self.coord_popup.cbx_startline.active = False
            self.coord_popup.txt_startline.text = ""

        if line_number > 0:
            resume_line = max(1, line_number - 1)
            self.coord_popup.txt_startline.text = str(resume_line)

    # -----------------------------------------------------------------------
    def defaultSettings(self):
        self.controller.defaultConfigCommand()

    # -----------------------------------------------------------------------
    def _on_viewer_sim_progress(self, _instance, value):
        """Mirror voxel-sim catch-up onto the preview timeline scrubber."""
        slider = getattr(self, "gcode_play_slider", None)
        if slider is not None:
            slider.sim_progress = float(value or 0.0)

    def _on_viewer_sim_checkpoints(self, _instance, value):
        """Mirror sim checkpoint positions onto the preview timeline scrubber."""
        slider = getattr(self, "gcode_play_slider", None)
        if slider is not None:
            slider.sim_checkpoints = list(value or [])

    def _on_viewer_sim_hud_text(self, _instance, value):
        """Mirror cut-simulation stats onto the viewer overlay label."""
        label = getattr(self, "sim_stats_hud", None)
        if label is not None:
            label.text = value or ""

    def _on_viewer_stock_visible(self, _instance, visible):
        """Keep the Stock menu item highlight in sync with viewer visibility."""
        dropdown = getattr(self, "gcode_viewer_display_drop_down", None)
        if dropdown is not None:
            dropdown.show_stock = bool(visible)

    def _on_viewer_bed_visible(self, _instance, visible):
        """Keep the Bed menu item highlight in sync with viewer visibility."""
        dropdown = getattr(self, "gcode_viewer_display_drop_down", None)
        if dropdown is not None:
            dropdown.show_bed = bool(visible)

    # -----------------------------------------------------------------------
    def gcode_play_call_back(self, distance, line_number):
        if not self.loading_file:
            total = self.gcode_viewer_distance
            self.gcode_play_slider.value = (distance * 1000.0 / total) if total else 0.0
            # Update line highlighting in file viewer during playback.
            # Skip when callback was triggered by a user click (set_distance_by_lineidx from click
            # invokes this before GcodeViewer updates cur_line_index, so line_number would be stale).
            if getattr(self, "_skip_next_set_selected_line_from_callback", False):
                self._skip_next_set_selected_line_from_callback = False
            elif line_number > 0 and hasattr(self, "gcode_rv"):
                self.gcode_rv.set_selected_line(line_number)

    # -----------------------------------------------------------------------
    def gcode_play_over_call_back(self):
        self.gcode_playing = False

    # -----------------------------------------------------------------------
    def gcode_play_to_start(self):
        self.gcode_viewer.set_pos_by_distance(0)
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False

    # -----------------------------------------------------------------------
    def gcode_play_to_end(self):
        self.gcode_viewer.show_all()
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False

    # -----------------------------------------------------------------------
    def gcode_play_speed_up(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 2)

    # -----------------------------------------------------------------------
    def gcode_play_speed_down(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 0.5)

    # -----------------------------------------------------------------------
    def gcode_play_toggle(self):
        if self.gcode_playing:
            self.gcode_playing = False
            self.gcode_viewer.dynamic_display = False
        else:
            if self.gcode_viewer.display_count >= self.gcode_viewer.get_total_distance():
                self.gcode_play_to_start()
            self.gcode_playing = True
            self.gcode_viewer.dynamic_display = True

    # -----------------------------------------------------------------------
    def toggle_camera_stream(self):
        splitter = self.ids.get("camera_splitter")
        if splitter is not None:
            splitter.toggle_collapsed()
            return
        if self.camera_stream.is_streaming():
            self.camera_stream.stop()
        elif App.get_running_app().supports_camera:
            self.camera_stream.start(self.controller.connection_address.split(":")[0])

    # -----------------------------------------------------------------------
    def _on_camera_splitter_collapsed(self, _splitter, collapsed):
        if collapsed:
            if self.camera_stream.is_streaming():
                self.camera_stream.stop()
            controls = self.ids.get("camera_controls")
            if controls is not None:
                controls.adjust_open = False
        elif App.get_running_app().supports_camera and not self.camera_stream.is_streaming():
            self.camera_stream.start(self.controller.connection_address.split(":")[0])

    # -----------------------------------------------------------------------
    def _detect_camera(self, host, probe):
        found = has_camera(host)
        Clock.schedule_once(partial(self._on_camera_detected, probe, found), 0)

    # -----------------------------------------------------------------------
    def _on_camera_detected(self, probe, found, *args):
        """Ignore a probe that a disconnect or a newer probe has superseded."""
        if probe != self.camera_probe:
            return
        App.get_running_app().supports_camera = found
        splitter = self.ids.get("camera_splitter")
        if splitter is None:
            return
        if found and splitter.collapsed:
            splitter.height = splitter.strip_size
        elif not found:
            splitter.collapse()

    # -----------------------------------------------------------------------
    def set_camera_resolution(self, label):
        """Apply a resolution the user picked from the camera panel.

        Also absorbs the echo from _show_camera_frame updating the picker to
        match what the stream is already sending.
        """
        app = App.get_running_app()
        value = RESOLUTION_VALUES.get(label)
        if value is None or value == app.camera_resolution:
            return
        app.camera_resolution = value
        host = self.controller.connection_address.split(":")[0]
        threading.Thread(target=set_resolution, args=(host, value), daemon=True).start()

    # -----------------------------------------------------------------------
    def _show_camera_frame(self, jpeg):
        camera_view = self.ids.camera_view
        camera_view.show_frame(jpeg)
        # The machine cannot be asked what resolution it is on, so the frames
        # themselves are what keeps the picker honest.
        texture = camera_view.texture
        if texture is not None:
            value = RESOLUTION_BY_SIZE.get(tuple(texture.size))
            if value is not None:
                App.get_running_app().camera_resolution = value

    # -----------------------------------------------------------------------
    def _set_camera_streaming(self, streaming):
        App.get_running_app().camera_streaming = streaming
        splitter = self.ids.get("camera_splitter")
        if splitter is not None and not streaming and not splitter.collapsed:
            splitter.collapse()

    # -----------------------------------------------------------------------
    def clear_selection(self):
        self.gcode_rv.data = []
        self.gcode_rv.data_length = 0
        self.gcode_viewer.clearDisplay()
        self.wpb_play.value = 0
        self.used_tools = []
        self.upcoming_tool = 0
        self.tool_table = {}
        self.cam_metadata = CamMetadata.empty()
        self.document_unit = "mm"
        self.gcode_viewer.tool_table = {}
        self.gcode_viewer.tool_unit_scale = 1.0
        self.init_path_visibility()
        self._clear_tool_change_markers()
        app = App.get_running_app()
        app.curr_page = 1
        app.total_pages = 1
        # Sync stock session toggles with cleared viewer (cancel load / clear file).
        popup = getattr(self, "stock_settings_popup", None)
        if popup is not None:
            settings = popup.reset_for_loaded_file()
            self._apply_stock_settings_impl(settings)
        self.updateStatus()

    # ------------------------------------------------------------------------
    def _clear_play_bar_tool_markers(self, *args):
        if hasattr(self, "wpb_play") and self.wpb_play:
            self.wpb_play.tool_markers = []

    def _clear_tool_change_markers(self):
        self.tool_change_markers = []
        self._clear_play_bar_tool_markers()

    def _apply_tool_change_markers(self):
        if not hasattr(self, "wpb_play") or not self.wpb_play:
            return
        if not getattr(self, "show_playbar_tool_change_markers", True):
            self.wpb_play.tool_markers = []
            return
        self.wpb_play.tool_markers = tool_change_markers_to_percents(
            self.tool_change_markers, self.selected_file_line_count
        )

    # ------------------------------------------------------------------------
    def load_start(self, *args):
        self.loading_file = True
        self._clear_play_bar_tool_markers()
        self.cmd_manager.transition.direction = "right"
        self.cmd_manager.current = "gcode_cmd_page"
        self.gcode_rv.data = []
        self.init_path_visibility()
        self.gcode_viewer.clearDisplay(close_progress=False)
        self.gcode_viewer.begin_new_file_load()
        self.gcode_viewer.set_display_offset(self.content.x, self.content.y)
        self.gcode_viewer.set_move_speed(GCODE_VIEW_SPEED)
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False
        # Set up frame callback for line highlighting
        self.gcode_viewer.set_frame_callback(self.gcode_play_call_back)

    # ------------------------------------------------------------------------
    def load_page(self, page_no, *args):
        app = App.get_running_app()
        app.loading_page = True
        if page_no == -1:
            page_no = 1 if app.curr_page == 1 else app.curr_page - 1
        elif page_no == 0:
            page_no = app.curr_page + 1
        if page_no > app.total_pages:
            page_no = app.total_pages
        self.gcode_rv.data = []
        hl_enabled = getattr(self, "gcode_highlight_enabled", False)
        hl_colors = getattr(self, "gcode_highlight_colors", None)
        line_no = (page_no - 1) * MAX_LOAD_LINES + 1
        for line in self.lines[(page_no - 1) * MAX_LOAD_LINES : MAX_LOAD_LINES * page_no]:
            line_txt = line.rstrip("\r\n")
            plain = line_txt.strip()
            if hl_enabled:
                hl = highlight_gcode_line(plain, hl_colors)
            else:
                hl = escape_gcode_markup(plain)
            try:
                self.gcode_rv.data.append(
                    {
                        "line_no": line_no,
                        "text": plain,
                        "highlighted_text": hl,
                        "color": (200 / 255, 200 / 255, 200 / 255, 1),
                    }
                )
            except IndexError:
                logger.error("Tried to write to recycle view data at same time as reading, ignore (indexError)")
            line_no = line_no + 1
        self.gcode_rv.data_length = len(self.gcode_rv.data)
        app.curr_page = page_no
        app.loading_page = False

    # ------------------------------------------------------------------------
    def cancel_load_gcodes(self):
        self.load_canceled = True

    # ------------------------------------------------------------------------
    def load_gcodes(self, line_no, parsed_list, *args):
        is_end = line_no == self.selected_file_line_count
        if parsed_list or is_end:
            self.gcode_viewer.load_array(parsed_list, is_end)

        if is_end and getattr(self.gcode_viewer, "line_times_job_show_progress", False):
            # load_array started the estimate; keep this popup until that job sends 'done'.
            self.progress_popup.btn_cancel.disabled = True
            self.progress_popup.progress_text = tr._("Calculating run time estimate...")
            self.progress_popup.progress_value = 0
        else:
            self.progress_popup.cancel = self.cancel_load_gcodes
            self.progress_popup.btn_cancel.disabled = False
            self.progress_popup.progress_value = line_no * 100.0 / self.selected_file_line_count

        self.load_event.set()

    # ------------------------------------------------------------------------
    def _update_startline_checkbox_disabled(self, *args):
        """Keep Resume at line checkbox disabled when gcode cannot be visualised (KV can't bind: app.root is None during CoordPopup build)."""
        if self.coord_popup and hasattr(self.coord_popup, "cbx_startline") and self.coord_popup.cbx_startline:
            self.coord_popup.cbx_startline.disabled = self.gcode_cannot_visualise

    # ------------------------------------------------------------------------
    def _on_gcode_cannot_visualise(self, msg):
        """Called when GcodeViewer detects unvisualisable gcode (e.g. zero-length segments). Show popup on next frame."""
        self.gcode_cannot_visualise = True
        Clock.schedule_once(partial(self.load_error, msg), 0)

    # ------------------------------------------------------------------------
    def load_error(self, error_msg, *args):
        self._clear_tool_change_markers()
        self.progress_popup.dismiss()
        self.message_popup.lb_content.text = error_msg
        self.message_popup.open(self)

    # ------------------------------------------------------------------------
    def load_end(self, *args):
        if self.load_canceled:
            self.gcode_viewer.load_array([], True)
            self.gcode_cannot_visualise = False
            self.clear_selection()
            self.load_canceled = False
            self.file_popup.dismiss()
            self.progress_popup.dismiss()
            self.updateStatus()
            self.loading_file = False
            return

        if len(self.gcode_viewer.lengths) > 0:
            self.gcode_cannot_visualise = False
            self.gcode_viewer_distance = self.gcode_viewer.get_total_distance()
            self.gcode_viewer.show_all()

        self._push_path_visibility()
        self.refresh_gcode_color_legend()

        app = App.get_running_app()

        # Only clear resume-at-line when a different file is loaded.
        current_file_key = app.selected_remote_filename or app.selected_local_filename
        if current_file_key != self._last_loaded_file_key:
            if self.coord_popup:
                self.coord_popup.cbx_startline.active = False
                self.coord_popup.txt_startline.text = ""
            self._last_loaded_file_key = current_file_key

        app.has_4axis = self.cnc.has_4axis
        app.has_off_axis_y = bool(self.cnc.has_off_axis_y)
        if app.has_4axis:
            self.coord_popup.set_config("leveling", "active", False)
            self.coord_popup.set_config("origin", "anchor", 3)
        else:
            if (
                app.has_anchor2
                and (CNC.vars["wcox"] - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"]) >= 0
                and (CNC.vars["wcoy"] - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"]) >= 0
            ):
                self.coord_popup.set_config("origin", "anchor", 2)
            else:
                self.coord_popup.set_config("origin", "anchor", 1)
        shape, origin = self._auto_stock_shape_origin()
        popup = getattr(self, "stock_settings_popup", None)
        if popup is not None:
            popup.rotary_mode = bool(app.has_4axis)
            popup.has_off_axis_y = bool(app.has_off_axis_y)
        metadata = getattr(self, "cam_metadata", None) or CamMetadata.empty()
        self._reset_stock_settings(
            shape=shape,
            origin=origin,
            show_stock=self._should_auto_show_header_stock(metadata.stock),
        )
        self.apply_bed_settings()
        self.coord_popup.load_config()

        self.file_popup.dismiss()
        if not getattr(self.gcode_viewer, "line_times_job_show_progress", False):
            self.progress_popup.dismiss()

        self.heartbeat_time = time.time()
        self.file_just_loaded = True

        self.updateStatus()
        self.loading_file = False
        self._apply_tool_change_markers()

        # Scroll to top of program that we just loaded
        self.gcode_rv.scroll_y = 1

    # -----------------------------------------------------------------------
    def first_page(self):
        self.load_page(1)

    # -----------------------------------------------------------------------
    def last_page(self):
        self.load_page(9999)

    # -----------------------------------------------------------------------
    def previous_page(self):
        self.load_page(-1)

    # -----------------------------------------------------------------------
    def next_page(self):
        self.load_page(0)

    # -----------------------------------------------------------------------
    def load_gcode_file(self, filepath):
        self.load_event.set()
        self.upcoming_tool = 0
        self.file_has_ocodes = False
        self.used_tools = []
        self.tool_change_markers = []
        self.tool_table = {}
        self.cam_metadata = CamMetadata.empty()
        self.document_unit = "mm"
        self.gcode_viewer.tool_table = {}
        self.gcode_viewer.tool_unit_scale = 1.0
        Clock.schedule_once(self.load_start)
        f = None
        try:
            with open(filepath, "rb") as f:
                # 读取文件开头的两个字节
                first_two_bytes = f.read(2)
            if first_two_bytes == b"\x00\x00":  # we just confirm this is a file compressed by quicklz
                # copy lz file to .lz dir
                lzpath, filename = os.path.split(filepath)
                lzpath = os.path.join(lzpath, ".lz")
                lzpath = os.path.join(lzpath, filename)
                if not os.path.exists(os.path.dirname(lzpath)):
                    # os.mkdir(os.path.dirname(lzpath))
                    os.makedirs(os.path.dirname(lzpath))
                lzpath = lzpath + ".lz"
                shutil.copyfile(filepath, lzpath)
                if not self.decompress_file(lzpath, filepath):
                    return
                if not self._verify_deferred_download_md5(filepath):
                    return

            # Load all lines from the file
            self.cnc.init()
            f = open(filepath, encoding="utf-8")
            self.lines = f.readlines()
            self.selected_file_line_count = len(self.lines)
            f.close()

            # Detect tools/stock metadata and set document unit if available
            self.document_unit = detect_document_unit(self.lines)
            self.cam_metadata = extract_cam_metadata(self.lines, unit_scale=unit_scale_to_mm(self.document_unit))
            self.tool_table = self.cam_metadata.tool_table
            self.gcode_viewer.tool_table = self.tool_table
            self.gcode_viewer.tool_unit_scale = unit_scale_to_mm(self.document_unit)

            # Hide previous stock immediately; dimensions are filled in load_end.
            self.reset_stock_for_loaded_file()

            # Load the first "page" of the file
            app = App.get_running_app()
            app.total_pages = int(self.selected_file_line_count / MAX_LOAD_LINES) + (
                0 if self.selected_file_line_count % MAX_LOAD_LINES == 0 else 1
            )
            Clock.schedule_once(partial(self.load_page, 1), 0)
            f = None
            line_no = 1
            # now = time.time()
            # temp_list = []
            for line in self.lines:
                if self.load_canceled:
                    break
                if not self.file_has_ocodes and OCODE_PATTERN.search(line):
                    self.file_has_ocodes = True
                prev_tool = self.cnc.tool
                self.cnc.parseLine(line, line_no)
                if self.upcoming_tool == 0:
                    self.upcoming_tool = self.cnc.tool
                if (self.cnc.tool_cmd or self.cnc.tool != prev_tool) and self.cnc.tool not in self.used_tools:
                    self.used_tools.append(self.cnc.tool)
                tool_change_label = None
                if self.cnc.mval == 321 or self.cnc.tool == LASER_TOOL_NUMBER:
                    tool_change_label = "L"
                elif self.cnc.tool == ZPROBE_TOOL_NUMBER and (self.cnc.tool != prev_tool or self.cnc.tool_cmd):
                    tool_change_label = "P"
                elif self.cnc.tool == PROBE_3D_TOOL_NUMBER and (self.cnc.tool != prev_tool or self.cnc.tool_cmd):
                    tool_change_label = "3DP"
                elif self.cnc.tool >= 1 and self.cnc.tool != prev_tool:
                    tool_change_label = "T%d" % self.cnc.tool
                if tool_change_label is not None:
                    if not (self.tool_change_markers and self.tool_change_markers[-1][1] == tool_change_label):
                        self.tool_change_markers.append((line_no, tool_change_label))

                if line_no % LOAD_INTERVAL == 0 or line_no == self.selected_file_line_count:
                    parsed_list = self.cnc.coordinates
                    self.load_event.wait()
                    self.load_event.clear()
                    # temp_list.extend(self.cnc.coordinates)
                    Clock.schedule_once(partial(self.load_gcodes, line_no, parsed_list), 0)
                    self.cnc.coordinates = []
                line_no += 1
            # print('Load time: ' + str(time.time() - now))
            # with open("laser.txt", "w") as output:
            #     output.write(str(temp_list))
        except Exception:
            logger.error(sys.exc_info()[1])
            self.heartbeat_time = time.time()
            self.loading_file = False
            if f:
                f.close()
            self.gcode_cannot_visualise = True
            self.controller.log.put(
                (
                    Controller.MSG_ERROR,
                    "Gcode cannot be visualised (parser error or complexity). Playback is unaffected.",
                )
            )
            Clock.schedule_once(
                partial(
                    self.load_error, "Gcode cannot be visualised (parser error or complexity). Playback is unaffected."
                ),
                0,
            )
            return

        Clock.schedule_once(self.load_end, 0)

    # -----------------------------------------------------------------------
    def init_path_visibility(self):
        """Reset all path visibility filters to show everything."""
        self.path_show_rapid = True
        self.path_show_feed = True
        self.path_speed_bits = VISIBILITY_ALL_BUCKET_BITS
        self.path_z_bits = VISIBILITY_ALL_BUCKET_BITS
        self.path_hidden_tools = set()
        if getattr(self, "gcode_viewer", None) is not None:
            self._push_path_visibility()

    def _tool_filter_ids(self):
        return sorted({int(t) for t in (self.used_tools or []) if int(t) >= 0})[:VISIBILITY_MAX_TOOLS]

    def _hidden_tools(self):
        hidden = getattr(self, "path_hidden_tools", None)
        if hidden is None:
            hidden = set()
            self.path_hidden_tools = hidden
        return hidden

    def _push_path_visibility(self):
        if getattr(self, "gcode_viewer", None) is None:
            return
        tools = self._tool_filter_ids()
        hidden = self._hidden_tools()
        # Drop stale hidden ids when the file's tool list changes.
        if tools:
            allowed = set(tools)
            self.path_hidden_tools = {t for t in hidden if t in allowed}
            hidden = self.path_hidden_tools
        bits = 0
        for index, tool in enumerate(tools):
            if tool not in hidden:
                bits |= 1 << index
        self.gcode_viewer.set_visibility_filters(
            show_rapid=self.path_show_rapid,
            show_feed=self.path_show_feed,
            speed_bucket_bits=self.path_speed_bits,
            z_bucket_bits=self.path_z_bits,
            tool_ids=tools,
            tool_bits=bits,
        )

    def is_legend_entry_visible(self, kind, key):
        if kind == "rapid":
            return bool(self.path_show_rapid)
        if kind == "feed":
            return bool(self.path_show_feed)
        if kind == "tool":
            return int(key) not in self._hidden_tools()
        if kind == "speed_bucket":
            return bool(self.path_speed_bits & (1 << int(key)))
        if kind == "z_bucket":
            return bool(self.path_z_bits & (1 << int(key)))
        return True

    def _current_scheme_any_visible(self):
        viewer = getattr(self, "gcode_viewer", None)
        scheme = getattr(viewer, "color_scheme", COLOR_SCHEME_BY_TYPE) if viewer else COLOR_SCHEME_BY_TYPE
        if scheme == COLOR_SCHEME_BY_TYPE:
            return self.path_show_rapid or self.path_show_feed
        if scheme == COLOR_SCHEME_BY_TOOL:
            tools = self._tool_filter_ids()
            if not tools:
                return True
            hidden = self._hidden_tools()
            return any(t not in hidden for t in tools)
        if scheme == COLOR_SCHEME_BY_SPEED:
            return self.path_show_rapid or bool(self.path_speed_bits)
        if scheme == COLOR_SCHEME_BY_Z:
            return bool(self.path_z_bits)
        return True

    def toggle_gcode_visibility_entry(self, kind, key):
        if kind == "rapid":
            self.path_show_rapid = not self.path_show_rapid
        elif kind == "feed":
            self.path_show_feed = not self.path_show_feed
        elif kind == "tool":
            tool = int(key)
            hidden = self._hidden_tools()
            if tool in hidden:
                hidden.discard(tool)
            else:
                hidden.add(tool)
        elif kind == "speed_bucket":
            bit = 1 << int(key)
            self.path_speed_bits ^= bit
            self.path_speed_bits &= VISIBILITY_ALL_BUCKET_BITS
        elif kind == "z_bucket":
            bit = 1 << int(key)
            self.path_z_bits ^= bit
            self.path_z_bits &= VISIBILITY_ALL_BUCKET_BITS
        else:
            return
        self._push_path_visibility()
        self.refresh_gcode_visibility_legend()

    def toggle_gcode_visibility_all(self):
        viewer = getattr(self, "gcode_viewer", None)
        if viewer is None:
            return
        show = not self._current_scheme_any_visible()
        scheme = getattr(viewer, "color_scheme", COLOR_SCHEME_BY_TYPE)
        if scheme == COLOR_SCHEME_BY_TYPE:
            self.path_show_rapid = show
            self.path_show_feed = show
        elif scheme == COLOR_SCHEME_BY_TOOL:
            if show:
                self.path_hidden_tools = set()
            else:
                self.path_hidden_tools = set(self._tool_filter_ids())
        elif scheme == COLOR_SCHEME_BY_SPEED:
            self.path_speed_bits = VISIBILITY_ALL_BUCKET_BITS if show else 0
            self.path_show_rapid = show
        elif scheme == COLOR_SCHEME_BY_Z:
            self.path_z_bits = VISIBILITY_ALL_BUCKET_BITS if show else 0
        self._push_path_visibility()
        self.refresh_gcode_visibility_legend()

    def refresh_gcode_visibility_legend(self):
        """Update legend eye states without rebuilding rows (preserves scroll)."""
        panel = self.ids.get("color_scheme_panel")
        if panel is not None:
            panel.apply_visibility(self)

    def refresh_gcode_color_legend(self, *_args):
        panel = self.ids.get("color_scheme_panel")
        if panel is not None:
            panel.refresh(self)

    def _scheme_visibility_modified(self, scheme):
        """True when that scheme's visibility filters differ from all-visible defaults."""
        if scheme == COLOR_SCHEME_BY_TYPE:
            return not (self.path_show_rapid and self.path_show_feed)
        if scheme == COLOR_SCHEME_BY_TOOL:
            hidden = self._hidden_tools()
            if not hidden:
                return False
            return any(t in hidden for t in self._tool_filter_ids())
        if scheme == COLOR_SCHEME_BY_SPEED:
            # Rapid is shared with Move type but also listed under Speed.
            return (self.path_speed_bits != VISIBILITY_ALL_BUCKET_BITS) or (not self.path_show_rapid)
        if scheme == COLOR_SCHEME_BY_Z:
            return self.path_z_bits != VISIBILITY_ALL_BUCKET_BITS
        return False

    def gcode_scheme_spinner_label(self, scheme):
        if scheme == COLOR_SCHEME_BY_TOOL:
            base = tr._("Tool")
        elif scheme == COLOR_SCHEME_BY_SPEED:
            base = tr._("Speed")
        elif scheme == COLOR_SCHEME_BY_Z:
            base = tr._("Height")
        else:
            base = tr._("Move type")
        if self._scheme_visibility_modified(scheme):
            return f"{base} *"
        return base

    def gcode_scheme_spinner_labels(self):
        return [
            self.gcode_scheme_spinner_label(COLOR_SCHEME_BY_TOOL),
            self.gcode_scheme_spinner_label(COLOR_SCHEME_BY_TYPE),
            self.gcode_scheme_spinner_label(COLOR_SCHEME_BY_SPEED),
            self.gcode_scheme_spinner_label(COLOR_SCHEME_BY_Z),
        ]

    def _scheme_from_spinner_text(self, text):
        base = text[:-2].rstrip() if text.endswith(" *") else text
        if base == tr._("Tool"):
            return COLOR_SCHEME_BY_TOOL
        if base == tr._("Speed"):
            return COLOR_SCHEME_BY_SPEED
        if base == tr._("Height"):
            return COLOR_SCHEME_BY_Z
        return COLOR_SCHEME_BY_TYPE

    def on_gcode_color_scheme_changed(self, text):
        scheme = self._scheme_from_spinner_text(text)
        if getattr(self.gcode_viewer, "color_scheme", None) == scheme:
            return
        if scheme == COLOR_SCHEME_BY_TOOL:
            self.gcode_viewer.set_color_scheme("by_tool")
        elif scheme == COLOR_SCHEME_BY_SPEED:
            self.gcode_viewer.set_color_scheme("by_speed")
        elif scheme == COLOR_SCHEME_BY_Z:
            self.gcode_viewer.set_color_scheme("by_z")
        else:
            self.gcode_viewer.set_color_scheme("by_type")
        self.refresh_gcode_color_legend()

    # -----------------------------------------------------------------------
    def send_cmd(self):
        to_send = self.manual_cmd.text.strip()
        if to_send:
            self.manual_cmd.last_mdi_command = to_send
            self.manual_rv.scroll_y = 0
            if to_send.lower() == "clear":
                self.manual_rv.data = []
            else:
                sanitized_to_send = "\n".join([line for line in to_send.split("\n") if line.strip().lower() != "clear"])
                if sanitized_to_send != to_send:
                    self.manual_rv.data.append(
                        self._format_mdi_entry(
                            {
                                "text": "clear command can't be used together with other commands",
                                "color": (250 / 255, 105 / 255, 102 / 255, 1),
                            }
                        )
                    )
                self.controller.executeCommand(sanitized_to_send)
        self.manual_cmd.text = ""
        hide_mdi_intellisense()
        Clock.schedule_once(self.refocus_cmd)

    # -----------------------------------------------------------------------
    def refocus_cmd(self, dt):
        self.manual_cmd.focus = True

    def stop_run(self):
        self.stop.set()
        if hasattr(self, "controller") and self.controller:
            self.controller.stop.set()
            # Cancel any ongoing reconnection attempts
            self.controller.cancel_reconnection()
        # Dismiss reconnection popup if it's open
        if hasattr(self, "reconnection_popup") and self.reconnection_popup and self.reconnection_popup._is_open:
            self.reconnection_popup.dismiss()


class MakeraApp(App):
    state = StringProperty(NOT_CONNECTED)
    playing = BooleanProperty(False)
    spindle_or_laser_is_on = BooleanProperty(False)
    jog_controls_enabled = BooleanProperty(False)
    has_4axis = BooleanProperty(False)
    has_off_axis_y = BooleanProperty(False)
    has_atc = BooleanProperty(False)
    has_anchor2 = BooleanProperty(True)
    lasering = BooleanProperty(False)
    show_gcode_ctl_bar = BooleanProperty(False)
    fw_has_update = BooleanProperty(False)
    ctl_has_update = BooleanProperty(False)
    selected_local_filename = StringProperty("")
    selected_remote_filename = StringProperty("")
    tool = NumericProperty(-1)
    curr_page = NumericProperty(1)
    total_pages = NumericProperty(1)
    loading_page = BooleanProperty(False)
    model = StringProperty("")
    is_community_firmware = BooleanProperty(False)
    supports_camera = BooleanProperty(False)
    camera_streaming = BooleanProperty(False)
    camera_brightness = NumericProperty(ADJUST_DEFAULT)
    camera_contrast = NumericProperty(ADJUST_DEFAULT)
    camera_gamma = NumericProperty(ADJUST_DEFAULT)
    camera_resolution = NumericProperty(DEFAULT_RESOLUTION)
    supports_auto_ext_out = BooleanProperty(False)
    fw_version_digitized = NumericProperty(0)
    show_tooltips = BooleanProperty(True)
    tooltip_delay = NumericProperty(0.5)
    mdi_data = ListProperty([])
    invert_y_axis_jogging = BooleanProperty(False)
    jog_step_xy = StringProperty("10")
    jog_step_z = StringProperty("1")
    jog_step_a = StringProperty("90")
    active_color = ListProperty([0, 1, 1, 1])  # Default cyan (0, 255, 255) in 0-1 range
    jog_mode_text = StringProperty(tr._("Jog Mode:Step"))
    jog_speed_text = StringProperty(tr._("Jog Speed:Max"))
    jog_keyboard_enable = StringProperty("normal")
    jog_pendant_enable = StringProperty("normal")
    jog_pendant_text = StringProperty(tr._("No Pendant"))
    # [left, top, right, bottom] in pixels — populated on iOS from
    # UIWindow.safeAreaInsets (see _update_safe_area_padding).
    safe_area_padding = ListProperty([0, 0, 0, 0])

    def on_stop(self):
        # Cancel any ongoing reconnection attempts to prevent hanging
        if hasattr(self.root, "controller") and self.root.controller:
            self.root.controller.cancel_reconnection()
        # Stop all scheduled Clock events
        if hasattr(self.root, "blink_state"):
            Clock.unschedule(self.root.blink_state)
        if hasattr(self.root, "switch_status"):
            Clock.unschedule(self.root.switch_status)
        if hasattr(self.root, "check_model_metadata"):
            Clock.unschedule(self.root.check_model_metadata)
        # Stop the main run loop
        self.root.stop_run()

    def build(self):
        self.settings_cls = SettingsWithSidebar
        self.use_kivy_settings = True
        self.title = tr._("Carvera Controller Community") + " v" + __version__
        self.icon = os.path.join(os.path.dirname(__file__), "icon.png")

        return Makera(ctl_version=__version__)

    def on_start(self):
        # Workaround for Android blank screen issue
        # https://github.com/kivy/python-for-android/issues/2720
        viewport_update_count = 0

        def update_viewport_with_counter(dt):
            nonlocal viewport_update_count
            Window.update_viewport()
            viewport_update_count += 1
            if viewport_update_count >= 20:  # Stop after 5 seconds (5/0.25=20)
                return False  # This will unschedule the event

        Clock.schedule_interval(update_viewport_with_counter, 0.25)

        if kivy_platform == "ios":
            # UIKit may not have laid out the key window yet on the first tick,
            # so the early query returns zeros — re-query after a short delay
            # and on resize (rotation, split-view, etc.) to stay accurate.
            Clock.schedule_once(self._update_safe_area_padding, 0)
            Clock.schedule_once(self._update_safe_area_padding, 0.5)
            Window.bind(on_resize=lambda *a: self._update_safe_area_padding())

    def _update_safe_area_padding(self, *args):
        try:
            import ctypes

            lib = ctypes.CDLL(None)
            fn = lib.get_safe_area_insets_px
            fn.argtypes = [ctypes.POINTER(ctypes.c_double)] * 4
            fn.restype = None
            top, left, bottom, right = (ctypes.c_double(0) for _ in range(4))
            fn(ctypes.byref(top), ctypes.byref(left), ctypes.byref(bottom), ctypes.byref(right))
            self.safe_area_padding = [left.value, top.value, right.value, bottom.value]
        except (OSError, AttributeError) as e:
            print(f"safe area query skipped: {e}")

    def on_pause(self):
        return True


def load_app_configs():
    if Config.has_option("carvera", "ui_density_override") and Config.get("carvera", "ui_density_override") == "1":
        Metrics.set_density(float(Config.get("carvera", "ui_density")))

    # Configure logging level from config
    if Config.has_option("kivy", "log_level"):
        log_level = Config.get("kivy", "log_level").upper()
        if log_level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            logging.getLogger().setLevel(getattr(logging, log_level))
            logger.info(f"Log level set to {log_level}")


def set_config_defaults(default_lang):
    if not Config.has_section("carvera"):
        Config.add_section("carvera")

    if not Config.has_section("input"):
        Config.add_section("input")

    if not kivy_platform in ["android", "ios"]:
        Config.set(
            "input", "mouse", "mouse,multitouch_on_demand"
        )  # disable multitouch simulation on non-mobile platforms

    if kivy_platform == "linux":
        # Remove the default probesysfs entry that treats trackpads as touchscreens.
        # Kivy's default adds '%(name)s = probesysfs,provider=hidinput' which picks up
        # all HID devices including laptop trackpads.
        if Config.has_option("input", "%(name)s"):
            Config.remove_option("input", "%(name)s")
        # Re-add probesysfs using mtdev, filtered to devices whose name contains
        # "touchscreen" (case-insensitive). This preserves real touchscreen support
        # while excluding trackpads, which never have "touchscreen" in their device name.
        Config.set("input", "touchscreen_%(name)s", "probesysfs,provider=mtdev,match=(?i)touchscreen")

    # Only update config if running new version
    if not Config.has_option("carvera", "version") or Config.get("carvera", "version") != __version__:
        Config.set("carvera", "version", __version__)
        # Default params that are not configurable, set only once
        Config.set("kivy", "window_icon", "data/icon.png")
        Config.set("kivy", "exit_on_escape", "0")
        Config.set("kivy", "pause_on_minimize", "0")

    # Configurable config options. Don't change if they are already set
    if not Config.has_option("carvera", "show_update"):
        Config.set("carvera", "show_update", "1")
    if not Config.has_option("carvera", "show_firmware_check"):
        Config.set("carvera", "show_firmware_check", "1")
    if not Config.has_option("carvera", "show_tooltips"):
        Config.set("carvera", "show_tooltips", "1")
    if not Config.has_option("carvera", "tooltip_delay"):
        Config.set("carvera", "tooltip_delay", "1.5")
    if not Config.has_option("carvera", "active_color"):
        Config.set("carvera", "active_color", "0,255,255,255")
    if not Config.has_option("carvera", "language"):
        Config.set("carvera", "language", default_lang)
    if not Config.has_option("carvera", "local_folder_1"):
        Config.set("carvera", "local_folder_1", "")
    if not Config.has_option("carvera", "local_folder_2"):
        Config.set("carvera", "local_folder_2", "")
    if not Config.has_option("carvera", "local_folder_3"):
        Config.set("carvera", "local_folder_3", "")
    if not Config.has_option("carvera", "local_folder_4"):
        Config.set("carvera", "local_folder_4", "")
    if not Config.has_option("carvera", "local_folder_5"):
        Config.set("carvera", "local_folder_5", "")
    if not Config.has_option("carvera", "remote_folder_1"):
        Config.set("carvera", "remote_folder_1", "")
    if not Config.has_option("carvera", "remote_folder_2"):
        Config.set("carvera", "remote_folder_2", "")
    if not Config.has_option("carvera", "remote_folder_3"):
        Config.set("carvera", "remote_folder_3", "")
    if not Config.has_option("carvera", "remote_folder_4"):
        Config.set("carvera", "remote_folder_4", "")
    if not Config.has_option("carvera", "remote_folder_5"):
        Config.set("carvera", "remote_folder_5", "")
    if not Config.has_option("carvera", "custom_bkg_img_dir"):
        Config.set("carvera", "custom_bkg_img_dir", "")
    if not Config.has_option("carvera", "invert_y_axis_jogging"):
        Config.set("carvera", "invert_y_axis_jogging", "0")
    had_jogging_while_running = Config.has_option("carvera", "allow_jogging_while_machine_running")
    if not had_jogging_while_running:
        Config.set("carvera", "allow_jogging_while_machine_running", "1")
    if not Config.has_option("carvera", "allow_jogging_while_spindle_on"):
        migrate_spindle_on = had_jogging_while_running and Config.getboolean(
            "carvera", "allow_jogging_while_machine_running", fallback=False
        )
        Config.set("carvera", "allow_jogging_while_spindle_on", "1" if migrate_spindle_on else "0")
    if not Config.has_option("carvera", "allow_manual_usb_device"):
        Config.set("carvera", "allow_manual_usb_device", "0")
    if not Config.has_option("carvera", "manual_usb_device"):
        Config.set("carvera", "manual_usb_device", "")
    if not Config.has_option("carvera", "use_higher_baud"):
        Config.set("carvera", "use_higher_baud", "0")
    if not Config.has_option("carvera", "usb_baud_rate"):
        Config.set("carvera", "usb_baud_rate", "1500000")
    if not Config.has_option("carvera", "reconnect_method"):
        Config.set("carvera", "reconnect_method", "wifi")
    if not Config.has_option("carvera", "usb_device_id"):
        Config.set("carvera", "usb_device_id", "")
    if not Config.has_option("carvera", "usb_serial"):
        Config.set("carvera", "usb_serial", "")
    if not Config.has_option("carvera", "last_connection_method"):
        Config.set("carvera", "last_connection_method", "")
    # Migrate legacy VID:PID:SERIAL stored in usb_device_id.
    legacy_id = Config.get("carvera", "usb_device_id", fallback="") or ""
    vid_pid, legacy_serial = Utils.parse_usb_device_id(legacy_id)
    if vid_pid and legacy_serial and legacy_id.count(":") >= 2:
        Config.set("carvera", "usb_device_id", vid_pid)
        if not Config.get("carvera", "usb_serial", fallback=""):
            Config.set("carvera", "usb_serial", legacy_serial)
    if not Config.has_option("carvera", "high_precision_reamining_time_estimate"):
        Config.set("carvera", "high_precision_reamining_time_estimate", "1")
    if not Config.has_option("carvera", "background_image"):
        Config.set("carvera", "background_image", "None")
    if not Config.has_option("graphics", "allow_screensaver"):
        Config.set("graphics", "allow_screensaver", "0")
    if not Config.has_option("graphics", "height"):
        Config.set("graphics", "height", "1440")
    if not Config.has_option("graphics", "width"):
        Config.set("graphics", "width", "900")
    if not Config.has_option("carvera", "instantFSoverride"):
        Config.set("carvera", "instantFSoverride", "1")
    if not Config.has_option("carvera", "show_playbar_tool_change_markers"):
        Config.set("carvera", "show_playbar_tool_change_markers", "1")

    # G-code viewer defaults
    if not Config.has_option("carvera", "gcode_auto_show_stock"):
        Config.set("carvera", "gcode_auto_show_stock", "1")
    if not Config.has_option("carvera", "gcode_highlight_enabled"):
        Config.set("carvera", "gcode_highlight_enabled", "1")
    if not Config.has_option("carvera", "gcode_color_comment"):
        Config.set("carvera", "gcode_color_comment", "106,153,85,255")
    if not Config.has_option("carvera", "gcode_color_g_command"):
        Config.set("carvera", "gcode_color_g_command", "86,156,214,255")
    if not Config.has_option("carvera", "gcode_color_m_command"):
        Config.set("carvera", "gcode_color_m_command", "197,134,192,255")
    if not Config.has_option("carvera", "gcode_color_coordinate"):
        Config.set("carvera", "gcode_color_coordinate", "206,145,120,255")
    if not Config.has_option("carvera", "gcode_color_feedrate"):
        Config.set("carvera", "gcode_color_feedrate", "78,201,176,255")
    if not Config.has_option("carvera", "gcode_color_spindle"):
        Config.set("carvera", "gcode_color_spindle", "209,105,105,255")
    if not Config.has_option("carvera", "gcode_color_tool"):
        Config.set("carvera", "gcode_color_tool", "181,206,168,255")
    if not Config.has_option("carvera", "gcode_color_line_number"):
        Config.set("carvera", "gcode_color_line_number", "133,133,133,255")
    if not Config.has_option("carvera", "gcode_color_parameter"):
        Config.set("carvera", "gcode_color_parameter", "156,220,254,255")
    if not Config.has_option("carvera", "gcode_color_o_label"):
        Config.set("carvera", "gcode_color_o_label", "86,156,214,255")
    if not Config.has_option("carvera", "gcode_color_o_keyword"):
        Config.set("carvera", "gcode_color_o_keyword", "220,220,170,255")
    if not Config.has_option("carvera", "gcode_color_param_ref"):
        Config.set("carvera", "gcode_color_param_ref", "181,206,168,255")
    if not Config.has_option("carvera", "gcode_color_math_keyword"):
        Config.set("carvera", "gcode_color_math_keyword", "215,186,125,255")
    if not Config.has_option("carvera", "gcode_color_shell_command"):
        Config.set("carvera", "gcode_color_shell_command", "47,117,181,255")

    Config.write()


def load_constants():
    Window.softinput_mode = "below_target"

    _device = None
    _baud = None

    global SHORT_LOAD_TIMEOUT
    global WIFI_LOAD_TIMEOUT
    global HEARTBEAT_TIMEOUT
    global MAX_TOUCH_INTERVAL
    global GCODE_VIEW_SPEED
    global LOAD_INTERVAL
    global MAX_LOAD_LINES
    global BLOCK_SIZE
    global BLOCK_HEADER_SIZE

    global FW_UPD_ADDRESS
    global CTL_UPD_ADDRESS
    global DOWNLOAD_ADDRESS
    global FW_DOWNLOAD_ADDRESS

    FW_UPD_ADDRESS = "https://raw.githubusercontent.com/carvera-community/carvera_community_firmware/master/version.txt"
    CTL_UPD_ADDRESS = "https://raw.githubusercontent.com/carvera-community/carvera_controller/main/CHANGELOG.md"
    DOWNLOAD_ADDRESS = "https://github.com/carvera-community/carvera_controller/releases/latest"
    FW_DOWNLOAD_ADDRESS = "https://github.com/Carvera-Community/Carvera_Community_Firmware/releases/latest"

    SHORT_LOAD_TIMEOUT = 3  # s
    WIFI_LOAD_TIMEOUT = 30  # s
    HEARTBEAT_TIMEOUT = 5
    MAX_TOUCH_INTERVAL = 0.15
    GCODE_VIEW_SPEED = 1

    LOAD_INTERVAL = 10000  # must be divisible by MAX_LOAD_LINES
    MAX_LOAD_LINES = 10000

    # 定义块大小
    BLOCK_SIZE = 4096
    BLOCK_HEADER_SIZE = 4


def main():
    langname = None
    if Config.has_option("carvera", "language"):
        langname = Config.get("carvera", "language")
    translation.init(langname)

    # load the global constants
    load_constants()

    # Language translation needs to be globally accessible
    global HALT_REASON

    set_config_defaults(tr.lang)
    load_app_configs()

    HALT_REASON = load_halt_translations(tr)

    base_path = app_base_path()
    register_fonts(base_path)
    register_images(base_path)

    # Make it global to be able to access it from native APIs
    global global_app
    global_app = MakeraApp()
    global_app.run()


if __name__ == "__main__":
    main()
