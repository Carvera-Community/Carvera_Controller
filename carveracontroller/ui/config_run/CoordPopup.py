"""Config and Run dialog: bed preview plus job setup."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

from carveracontroller.CNC import CNC
from carveracontroller.translation import tr
from carveracontroller.ui.common.compact import COMPACT_WIDTH_DP, is_compact_width
from carveracontroller.ui.popups.set_position import (
    ChangeToolPopup,
    MoveAPopup,
    SetAPopup,
    SetToolPopup,
    SetXPopup,
    SetYPopup,
    SetZPopup,
)
from carveracontroller.Utils import digitize_v

logger = logging.getLogger(__name__)

_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_BUILTIN_BACKGROUND_DIR = os.path.join(_PACKAGE_ROOT, "data", "play_file_image_backgrounds")


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


def feature_switch_card_height(padding, *row_heights):
    """Card height for the machine toggles, or 0 when every row is hidden."""
    total = sum(row_heights)
    if total <= 0:
        return 0
    return padding[1] + padding[3] + total


def _set_feature_row(row, visible):
    """Show or hide a toggle row.

    Firmware flags are written off the UI thread, so the card can stay
    disabled after its height has changed. Release the card before the row:
    clearing only the row leaves the switch with one leftover count.
    Assigning ``disabled = False`` is not enough once that value is already
    false while the count is still above zero.
    """

    def clear_disabled(widget):
        if widget._disabled_value:
            widget.disabled = False
        extra = widget._disabled_count
        if extra > 0:
            widget.dec_disabled(extra)

    row.height = dp(36) if visible else 0
    row.opacity = 1 if visible else 0
    if not visible:
        row.disabled = True
        return
    card = row.parent
    if card is not None and card.disabled:
        clear_disabled(card)
    clear_disabled(row)


class HoverBox(BoxLayout):
    """A box that knows whether the mouse is over it."""

    hovered = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, _window, pos):
        self.hovered = self.get_root_window() is not None and self.collide_point(*self.to_widget(*pos))


class CoordSetupCard(BoxLayout):
    """One setup row in the Config and Run dialog."""

    title_text = StringProperty("")
    dot_rgba = ListProperty([1, 1, 1, 1])
    show_dot = BooleanProperty(True)
    icon = StringProperty("")
    show_checkbox = BooleanProperty(True)
    show_summary = BooleanProperty(True)
    show_config = BooleanProperty(True)
    show_line_field = BooleanProperty(False)
    section_disabled = BooleanProperty(False)
    summary_blocked = BooleanProperty(False)
    config_blocked = BooleanProperty(False)
    checkbox_locked = BooleanProperty(False)
    collapsed = BooleanProperty(False)

    checkbox = ObjectProperty(None, allownone=True)
    summary_label = ObjectProperty(None, allownone=True)
    config_button = ObjectProperty(None, allownone=True)
    line_input = ObjectProperty(None, allownone=True)

    def toggle_checkbox(self):
        if not self.show_checkbox or self.checkbox is None:
            return
        if self.disabled or self.checkbox.disabled or self.checkbox_locked:
            return
        self.checkbox._do_press()

    def on_touch_down(self, touch):
        if self.collapsed:
            return False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collapsed:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.collapsed:
            return False
        return super().on_touch_up(touch)


class CoordPopup(ModalView):
    config = {}
    mode = StringProperty()
    compact = BooleanProperty(False)
    # set when a 4th axis job starts in a rotated WCS, empty otherwise
    rotation_warning = StringProperty("")
    # the program uses more than one WCS, the preview can hide all but the start WCS then
    multiple_wcs = BooleanProperty(False)
    hide_other_wcs = BooleanProperty(False)
    vacuummode = ObjectProperty()
    extoutmode = ObjectProperty()
    autoblowmode = ObjectProperty()
    autobedcleanmode = ObjectProperty()
    ionizermode = ObjectProperty()
    timelapsemode = ObjectProperty()
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
        # Imported here so main.py can import this module while those classes are still being defined.
        from carveracontroller.main import AutoLevelPopup, OriginPopup, ZProbePopup

        self.config = config
        self._cards_bound = False
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
        self._suppress_background_image_config_write = False
        self.user_play_file_image_dir = Config.get("carvera", "custom_bkg_img_dir")
        self.custom_background_image_files = []
        self.builtin_background_image_files = []
        super().__init__(**kwargs)

        if os.path.exists(self.user_play_file_image_dir):
            self.custom_background_image_files = [
                f.replace(".png", "") for f in os.listdir(self.user_play_file_image_dir) if f.endswith(".png")
            ]

        if os.path.isdir(_BUILTIN_BACKGROUND_DIR):
            for filename in os.listdir(_BUILTIN_BACKGROUND_DIR):
                if filename.endswith(".png"):
                    self.builtin_background_image_files.append(filename.replace(".png", ""))

        Clock.schedule_once(self.populate_spinner, 0)
        app = App.get_running_app()
        if app is not None:
            app.bind(model=self._on_machine_model_changed)
        self.set_compact_from_window()

    def on_kv_post(self, base_widget):
        if not getattr(self, "cbx_margin", None):
            return
        self._bind_setup_cards()
        if self.lb_origin and not self.lb_origin.text:
            self.lb_origin.text = tr._(" (0, 0) from Anchor1")
        if self.lb_zprobe and not self.lb_zprobe.text:
            self.lb_zprobe.text = tr._(" (10, 10) from Path Origin")
        if self.lb_leveling and not self.lb_leveling.text:
            self.lb_leveling.text = tr._(" X Points: 10, Y Points: 10, Height: 5")

    def _bind_setup_cards(self):
        if self._cards_bound:
            return
        self._cards_bound = True
        self.cbx_margin.bind(active=self._on_margin_checkbox)
        self.cbx_zprobe.bind(active=self._on_zprobe_checkbox)
        self.cbx_leveling.bind(active=self._on_leveling_checkbox)
        self.btn_origin.bind(on_release=self._open_origin)
        self.btn_zprobe.bind(on_release=self._open_zprobe)
        self.btn_leveling.bind(on_release=self._open_leveling)

    def _on_margin_checkbox(self, _checkbox, active):
        self.set_config("margin", "active", active)
        self.toggle_config()

    def _on_zprobe_checkbox(self, _checkbox, active):
        self.on_zprobe_checkbox(active)

    def _on_leveling_checkbox(self, _checkbox, active):
        self.on_leveling_checkbox(active)

    def _open_origin(self, *_args):
        self.origin_popup.open()

    def _open_zprobe(self, *_args):
        self.zprobe_popup.open()

    def _open_leveling(self, *_args):
        self.auto_level_popup.init_and_open(False)

    def on_pre_open(self):
        super().on_pre_open()
        self.apply_feature_switch_visibility()
        # every popup starts with all WCS shown
        self.hide_other_wcs = False
        app = App.get_running_app()
        self.multiple_wcs = not app.has_4axis and len(app.root.controller.programWCS()) > 1

    def on_hide_other_wcs(self, _instance, hide):
        self.cnc_workspace.hide_other_wcs = hide
        self.cnc_workspace.draw()

    def on_open(self):
        super().on_open()
        Window.bind(size=self._on_window_size)
        self.set_compact_from_window()

    def apply_feature_switch_visibility(self):
        """Show the machine toggles that match the connected model and firmware."""
        if "vacuum_switch_row" not in self.ids:
            return
        app = App.get_running_app()
        if app is None:
            return
        community_extout = bool(app.is_community_firmware and app.fw_version_digitized >= digitize_v("2.2.0"))
        z1 = app.model == "Z1"
        show_vacuum = app.model == "C1"
        _set_feature_row(self.ids.vacuum_switch_row, show_vacuum)
        _set_feature_row(self.ids.extout_switch_row, community_extout)
        _set_feature_row(self.ids.autoblow_switch_row, z1)
        _set_feature_row(self.ids.autobedclean_switch_row, z1)
        _set_feature_row(self.ids.ionizer_switch_row, z1)
        _set_feature_row(self.ids.timelapse_switch_row, z1)

    def on_dismiss(self):
        Window.unbind(size=self._on_window_size)
        return super().on_dismiss()

    def _on_window_size(self, *_args):
        self.set_compact_from_window()

    def set_compact_from_window(self, width=None):
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
            self.size_hint = (0.8, 0.8)
        self.pos_hint = {"center_x": 0.5, "center_y": 0.5}

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
            old_source = os.path.join(_BUILTIN_BACKGROUND_DIR, filename)
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

        folder_path = _BUILTIN_BACKGROUND_DIR

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

        if CNC.vars["tl_requested"] == 1:
            self.timelapsemode = True
        else:
            self.timelapsemode = False

        # Apply leveling before Z probe so turning both off does not warn.
        self.cbx_margin.active = self.config["margin"]["active"]
        self.cbx_leveling.active = self.config["leveling"]["active"]
        self.cbx_zprobe.active = self.config["zprobe"]["active"]
        # init zprobe popup
        self.zprobe_popup.cbx_origin1.active = self.config["zprobe"]["origin"] == 1
        self.zprobe_popup.cbx_origin2.active = self.config["zprobe"]["origin"] == 2
        self.zprobe_popup.txt_x_offset.text = str(self.config["zprobe"]["x_offset"])
        self.zprobe_popup.txt_y_offset.text = str(self.config["zprobe"]["y_offset"])

        self.load_zprobe_label()

        self.auto_level_popup.sp_x_points.text = str(self.config["leveling"]["x_points"])
        self.auto_level_popup.sp_y_points.text = str(self.config["leveling"]["y_points"])
        self.auto_level_popup.sp_height.text = str(self.config["leveling"]["height"])

        self.load_leveling_label()

    def load_origin_label(self):
        app = App.get_running_app()
        name, wcox, wcoy, rotation = app.root.controller.startWCSOrigin()
        if app.has_4axis:
            self.lb_origin.text = "(%g, %g) " % (
                round(wcox - CNC.vars["anchor1_x"] - CNC.vars["rotation_offset_x"], 4),
                round(wcoy - CNC.vars["anchor1_y"] - CNC.vars["rotation_offset_y"], 4),
            ) + tr._("from Headstock")
        else:
            laser_x = CNC.vars["laser_module_offset_x"] if CNC.vars["lasermode"] else 0.0
            laser_y = CNC.vars["laser_module_offset_y"] if CNC.vars["lasermode"] else 0.0
            if self.config["origin"]["anchor"] == 2 and app.has_anchor2:
                self.lb_origin.text = "(%g, %g) " % (
                    round(wcox + laser_x - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"], 4),
                    round(wcoy + laser_y - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"], 4),
                ) + tr._("from Anchor2")
            else:
                self.lb_origin.text = "(%g, %g) " % (
                    round(wcox + laser_x - CNC.vars["anchor1_x"], 4),
                    round(wcoy + laser_y - CNC.vars["anchor1_y"], 4),
                ) + tr._("from Anchor1")
        self.lb_origin.text = name + ": " + self.lb_origin.text
        if app.has_4axis and abs(rotation) >= 0.001:
            self.rotation_warning = tr._(
                "%s is rotated by %g°. Rotary jobs normally run unrotated; keep it only if the rotation was measured for the rotary axis."
            ) % (name, round(rotation, 3))
        else:
            self.rotation_warning = ""

    def clear_start_wcs_rotation(self):
        """Set the rotation of the WCS the job starts in to 0."""
        controller = App.get_running_app().root.controller
        controller.wcsClearRotation(CNC.wcs_names.index(controller.startWCSOrigin()[0]) + 1)
        controller.viewWCS()  # the shown rotation of another WCS comes from "get wcs"
        Clock.schedule_once(lambda *_: self.load_origin_label(), 1)

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

    def _zprobe_controls_allowed(self):
        app = App.get_running_app()
        lasering = bool(app and getattr(app, "lasering", False))
        return self.mode in ("Run", "ZProbe", "Leveling") and not lasering

    def on_zprobe_checkbox(self, active):
        app = App.get_running_app()
        has_4axis = bool(app and getattr(app, "has_4axis", False))
        allowed = self._zprobe_controls_allowed()
        self.lb_zprobe.disabled = not active or not allowed
        self.btn_zprobe.disabled = not active or has_4axis or not allowed
        self.set_config("zprobe", "active", active)
        if not active and self.cbx_leveling.active:
            self._warn_zprobe_disabled_during_leveling()
        self.toggle_config()

    def on_leveling_checkbox(self, active):
        app = App.get_running_app()
        has_4axis = bool(app and getattr(app, "has_4axis", False))
        leveling_allowed = self.mode in ("Run", "Leveling") and not has_4axis
        self.lb_leveling.disabled = not active or not leveling_allowed
        self.btn_leveling.disabled = not active or not leveling_allowed
        self.set_config("leveling", "active", active)
        if active:
            self.cbx_zprobe.active = True
            self.set_config("zprobe", "active", True)
        self.toggle_config()

    def _warn_zprobe_disabled_during_leveling(self):
        app = App.get_running_app()
        if app is None or getattr(app, "root", None) is None:
            return
        message = tr._(
            "Auto Leveling without Auto Z Probe will use the current Z zero. "
            "Probe Z first or leave Auto Z Probe enabled, or job height may be wrong."
        )
        Clock.schedule_once(partial(app.root.show_message_popup, message, False), 0)

    def toggle_config(self):
        # upldate main status
        app = App.get_running_app()
        app.root.update_coord_config()
