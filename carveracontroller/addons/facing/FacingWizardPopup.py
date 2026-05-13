"""
Facing wizard — Community firmware and millimeters only.
"""

import logging
import os
import threading
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from carveracontroller.CNC import CNC, escape_gcode_markup, highlight_gcode_line
from carveracontroller.translation import tr

from .facing_gcode import (
    MILLING_BOTH,
    MILLING_CLIMB,
    MILLING_CONVENTIONAL,
    PATTERN_RASTER_X,
    PATTERN_RASTER_Y,
    PATTERN_SPIRAL,
    FacingParams,
    compute_facing_envelope,
    facing_toolpath_xy_polyline,
    generate_facing_gcode,
)
from .probe_grid_gcode import (
    ProbeGridParams,
    compute_probe_grid_xy,
    generate_probe_grid_gcode,
    probe_grid_z_datum_shift_after_probe_gcode,
)
from .stock_geometry import (
    CORNER_BL,
    CORNER_BR,
    CORNER_TL,
    CORNER_TR,
    rect_with_xy_margin,
    stock_rect_from_origin_corner,
)
from .facing_presets import (
    apply_preset_data,
    delete_preset_by_name,
    get_preset_by_name,
    load_store,
    preset_data_from_popup,
    save_store,
    sorted_preset_names,
    upsert_preset,
)

# Loads facing_preview_sketch so Factory registers widget name "FacingSketch" for KV before Builder applies rules.
from . import facing_preview_sketch as _facing_preview_sketch

logger = logging.getLogger(__name__)


def _parse_float_widget(widget, label: str) -> float:
    t = widget.text.strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    return float(t)


def _parse_non_negative_int_widget(widget, label: str) -> int:
    t = widget.text.strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    try:
        v = int(round(float(t)))
    except ValueError:
        raise ValueError(tr._("%s must be a number.") % label) from None
    if v < 0:
        raise ValueError(tr._("%s must be zero or positive.") % label)
    return v


def _optional_float(widget, default: float) -> float:
    t = widget.text.strip().replace(",", ".")
    if not t:
        return default
    return float(t)


def _m6_collet_pairs():
    return [
        ("", None),
        (tr._("3 mm"), 1),
        (tr._('1/8" (3.175 mm)'), 2),
        (tr._("4 mm"), 3),
        (tr._("6 mm"), 4),
        (tr._('1/4" (6.35 mm)'), 5),
        (tr._("8 mm"), 6),
    ]


def _probe_tool_pairs():
    return [
        (tr._("3D probe"), 999990),
        (tr._("Z probe"), 0),
    ]


def _milling_direction_pairs():
    return [
        (tr._("Climb"), MILLING_CLIMB),
        (tr._("Conventional"), MILLING_CONVENTIONAL),
        (tr._("Both (zigzag)"), MILLING_BOTH),
    ]


def _stock_corner_pairs():
    return [
        (tr._("Bottom-left (+X width, +Y length)"), CORNER_BL),
        (tr._("Bottom-right (-X width, +Y length)"), CORNER_BR),
        (tr._("Top-left (+X width, -Y length)"), CORNER_TL),
        (tr._("Top-right (-X width, -Y length)"), CORNER_TR),
    ]


class FacingSaveGcodeContent(BoxLayout):
    pass


class FacingSavePresetContent(BoxLayout):
    pass


class FacingWizardPopup(ModalView):
    """Facing toolpath parameters plus optional Z-grid probe; facing is always generated."""

    def __init__(self, **kwargs):
        self._m6_collet_pairs_list = None
        self._probe_tool_pairs_list = None
        self._stock_corner_pairs_list = None
        self._milling_direction_pairs_list = None
        super().__init__(**kwargs)
        self.bind(on_open=self._on_open_wizard, on_dismiss=self._on_dismiss_wizard)
        self._preview_trigger = Clock.create_trigger(self._update_preview_safe, timeout=0.2)
        self._preview_bindings_done = False
        self._preview_bind_attempts = 0
        self._gcode_plain = ""
        self._facing_gcode_stale = False
        self._facing_suspend_stale = False
        self._gcode_preview_width_bound = False
        Clock.schedule_once(lambda _dt: self._bind_preview_inputs(), 0)

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        Clock.schedule_once(lambda _dt: self._bind_preview_inputs(), 0)
        Clock.schedule_once(lambda _dt: self._bind_gcode_preview_resize(), 0)

    def _bind_gcode_preview_resize(self):
        if self._gcode_preview_width_bound:
            return
        try:
            rv = self.ids.rv_gcode_preview

            def _on_width(*_a):
                Clock.schedule_once(lambda _dt: self._refresh_gcode_preview(), 0)

            rv.fbind("width", _on_width)
            self._gcode_preview_width_bound = True
        except Exception:
            pass

    def _refresh_gcode_preview(self):
        try:
            rv = self.ids.rv_gcode_preview
        except Exception:
            return
        root = App.get_running_app().root
        hl_on = getattr(root, "gcode_highlight_enabled", True)
        hl_colors = getattr(root, "gcode_highlight_colors", None)
        raw = self._gcode_plain.replace("\r\n", "\n").replace("\r", "\n")
        if not raw.strip():
            rv.data = []
            return
        data = []
        for line in raw.split("\n"):
            if hl_on:
                text = highlight_gcode_line(line, hl_colors)
            else:
                text = escape_gcode_markup(line)
            data.append({"text": text})
        rv.data = data

    def _on_open_wizard(self, *args):
        self._preview_bind_attempts = 0
        Clock.schedule_once(lambda _dt: self._bind_preview_inputs(), 0)
        Clock.schedule_once(lambda _dt: self._update_preview_safe(), 0.02)
        Clock.schedule_once(self._init_wizard_widgets, 0.05)
        Clock.schedule_once(lambda _dt: self._preview_trigger(), 0.35)

    def open_presets_menu(self, anchor_widget, *args):
        dd = DropDown(auto_width=False, width=max(dp(240), anchor_widget.width))
        items = [
            (tr._("Load preset…"), "load"),
            (tr._("Save as…"), "save"),
            (tr._("Delete preset…"), "delete"),
        ]
        for label, action in items:
            btn = Button(text=label, size_hint_y=None, height=dp(44), font_size=dp(12))
            btn.bind(on_release=partial(self._on_presets_dropdown_choice, dd, action))
            dd.add_widget(btn)
        dd.open(anchor_widget)

    def _on_presets_dropdown_choice(self, dd, action, *_args):
        dd.dismiss()
        if action == "load":
            self._open_preset_list_for_load()
        elif action == "save":
            self.save_facing_preset_as()
        elif action == "delete":
            self._open_preset_list_for_delete()

    def open_gcode_menu(self, anchor_widget, *args):
        dd = DropDown(auto_width=False, width=max(dp(260), anchor_widget.width))
        entries = [
            (tr._("Save to file"), self.save_gcode_to_file),
            (tr._("Load in viewer"), self.load_in_viewer),
            (tr._("Upload & select"), self.upload_to_machine),
        ]
        for label, fn in entries:
            btn = Button(text=label, size_hint_y=None, height=dp(44), font_size=dp(12))
            btn.bind(on_release=partial(self._on_gcode_dropdown_choice, dd, fn))
            dd.add_widget(btn)
        dd.open(anchor_widget)

    def _on_gcode_dropdown_choice(self, dd, fn, *_args):
        dd.dismiss()
        fn()

    def _open_preset_list_for_load(self):
        names = sorted_preset_names(load_store())
        root = App.get_running_app().root
        if not names:
            root.show_message_popup(tr._("No saved presets yet."), False)
            return
        list_h = min(dp(280), max(dp(120), len(names) * dp(46)))
        outer = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        outer.add_widget(
            Label(
                text=tr._("Tap a preset to load."),
                size_hint_y=None,
                height=dp(32),
                font_size=dp(12),
                color=(0.75, 0.76, 0.8, 1),
                text_size=(root.width * 0.5, None),
                halign="left",
                valign="top",
            )
        )
        scroll = ScrollView(
            size_hint_y=None,
            height=list_h,
            bar_width=dp(10),
            scroll_type=["bars", "content"],
        )
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        inner.bind(minimum_height=inner.setter("height"))

        popup = Popup(
            title=tr._("Load preset"),
            content=outer,
            size_hint=(0.58, None),
            auto_dismiss=True,
            separator_height=dp(1),
        )

        for name in names:
            b = Button(text=name, size_hint_y=None, height=dp(44), font_size=dp(12))

            def make_pick(p, n):
                def _on_pick(*_a):
                    p.dismiss()
                    self._load_preset_by_name(n)

                return _on_pick

            b.bind(on_release=make_pick(popup, name))
            inner.add_widget(b)
        scroll.add_widget(inner)
        outer.add_widget(scroll)
        cancel_btn = Button(text=tr._("Cancel"), size_hint_y=None, height=dp(42), font_size=dp(12))
        cancel_btn.bind(on_release=lambda *_a: popup.dismiss())
        outer.add_widget(cancel_btn)

        def _fit_list_popup_height(*_a):
            popup.height = min(
                root.height * 0.72,
                outer.minimum_height + dp(56),
            )

        popup.open()
        Clock.schedule_once(_fit_list_popup_height, 0.05)

    def _open_preset_list_for_delete(self):
        names = sorted_preset_names(load_store())
        root = App.get_running_app().root
        if not names:
            root.show_message_popup(tr._("No saved presets yet."), False)
            return
        list_h = min(dp(280), max(dp(120), len(names) * dp(46)))
        outer = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        outer.add_widget(
            Label(
                text=tr._("Tap a preset to delete."),
                size_hint_y=None,
                height=dp(32),
                font_size=dp(12),
                color=(0.75, 0.76, 0.8, 1),
                text_size=(root.width * 0.5, None),
                halign="left",
                valign="top",
            )
        )
        scroll = ScrollView(
            size_hint_y=None,
            height=list_h,
            bar_width=dp(10),
            scroll_type=["bars", "content"],
        )
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        inner.bind(minimum_height=inner.setter("height"))

        popup = Popup(
            title=tr._("Delete preset"),
            content=outer,
            size_hint=(0.58, None),
            auto_dismiss=True,
            separator_height=dp(1),
        )

        for name in names:
            b = Button(text=name, size_hint_y=None, height=dp(44), font_size=dp(12))

            def make_pick(p, n):
                def _on_pick(*_a):
                    p.dismiss()
                    self._confirm_delete_preset_by_name(n)

                return _on_pick

            b.bind(on_release=make_pick(popup, name))
            inner.add_widget(b)
        scroll.add_widget(inner)
        outer.add_widget(scroll)
        cancel_btn = Button(text=tr._("Cancel"), size_hint_y=None, height=dp(42), font_size=dp(12))
        cancel_btn.bind(on_release=lambda *_a: popup.dismiss())
        outer.add_widget(cancel_btn)

        def _fit_list_popup_height(*_a):
            popup.height = min(
                root.height * 0.72,
                outer.minimum_height + dp(56),
            )

        popup.open()
        Clock.schedule_once(_fit_list_popup_height, 0.05)

    def _load_preset_by_name(self, name: str):
        root = App.get_running_app().root
        store = load_store()
        entry = get_preset_by_name(store, name.strip())
        if not entry:
            root.show_message_popup(tr._("Preset not found."), False)
            return
        self._facing_suspend_stale = True
        try:
            apply_preset_data(self, entry["data"])
        finally:
            self._facing_suspend_stale = False
        if self._gcode_plain.strip():
            self._facing_gcode_stale = True
        self._preview_trigger()

    def _confirm_delete_preset_by_name(self, name: str):
        root = App.get_running_app().root
        store = load_store()
        if not get_preset_by_name(store, name.strip()):
            root.show_message_popup(tr._("Preset not found."), False)
            return
        cp = root.confirm_popup
        cp.lb_title.text = tr._("Delete preset?")
        cp.lb_content.text = tr._("Remove this preset?\n%s") % name.strip()

        def on_confirm():
            st = load_store()
            if delete_preset_by_name(st, name.strip()):
                save_store(st)

        cp.confirm = on_confirm
        cp.cancel = None
        cp.open(root)

    def save_facing_preset_as(self, *args):
        content = FacingSavePresetContent()
        content.ids.ti_name.text = ""
        save_popup = Popup(
            title=tr._("Save preset"),
            content=content,
            size_hint=(0.58, None),
            auto_dismiss=False,
            separator_height=dp(1),
        )

        def _fit_popup_height(*_a):
            save_popup.height = min(
                App.get_running_app().root.height * 0.42,
                content.minimum_height + dp(56),
            )

        content.ids.btn_cancel.bind(on_release=lambda *_: save_popup.dismiss())
        content.ids.btn_save.bind(
            on_release=lambda *_: self._try_save_preset(save_popup, content)
        )
        save_popup.open()
        Clock.schedule_once(_fit_popup_height, 0.05)

    def _try_save_preset(self, save_popup: Popup, content: FacingSavePresetContent):
        root = App.get_running_app().root
        name = content.ids.ti_name.text.strip()
        if not name:
            root.show_message_popup(tr._("Enter a preset name."), False)
            return
        store = load_store()
        if get_preset_by_name(store, name):
            cp = root.confirm_popup
            cp.lb_title.text = tr._("Overwrite preset?")
            cp.lb_content.text = tr._("Replace existing preset?\n%s") % name

            def on_overwrite():
                self._commit_preset_save(save_popup, content, name)

            cp.confirm = on_overwrite
            cp.cancel = None
            cp.open(root)
            return
        self._commit_preset_save(save_popup, content, name)

    def _commit_preset_save(
        self,
        save_popup: Popup,
        content: FacingSavePresetContent,
        name: str,
    ):
        root = App.get_running_app().root
        name = name.strip()
        try:
            data = preset_data_from_popup(self)
        except ValueError as e:
            root.show_message_popup(str(e), False)
            return
        store = load_store()
        upsert_preset(store, name, data)
        save_store(store)
        save_popup.dismiss()
        root.show_message_popup(tr._("Preset saved.") + "\n" + name, False)

    def _ensure_wizard_lists(self):
        if self._m6_collet_pairs_list is None:
            self._m6_collet_pairs_list = _m6_collet_pairs()
        if self._probe_tool_pairs_list is None:
            self._probe_tool_pairs_list = _probe_tool_pairs()
        if self._stock_corner_pairs_list is None:
            self._stock_corner_pairs_list = _stock_corner_pairs()
        if self._milling_direction_pairs_list is None:
            self._milling_direction_pairs_list = _milling_direction_pairs()

    def _init_wizard_widgets(self, dt):
        self._facing_suspend_stale = True
        try:
            self._m6_collet_pairs_list = _m6_collet_pairs()
            spc = self.ids.spn_m6_collet
            spc.values = [p[0] for p in self._m6_collet_pairs_list]
            spc.text = self._m6_collet_pairs_list[0][0]

            self._probe_tool_pairs_list = _probe_tool_pairs()
            spp = self.ids.spn_probe_tool
            spp.values = [p[0] for p in self._probe_tool_pairs_list]
            spp.text = self._probe_tool_pairs_list[0][0]

            self._stock_corner_pairs_list = _stock_corner_pairs()
            spcorner = self.ids.spn_stock_corner
            spcorner.values = [p[0] for p in self._stock_corner_pairs_list]
            if spcorner.text not in spcorner.values:
                spcorner.text = self._stock_corner_pairs_list[0][0]

            self._milling_direction_pairs_list = _milling_direction_pairs()
            spmd = self.ids.spn_milling_dir
            spmd.values = [p[0] for p in self._milling_direction_pairs_list]
            if spmd.text not in spmd.values:
                spmd.text = self._milling_direction_pairs_list[0][0]

            self._sync_milling_spinner_for_pattern()

            self._prefill_facing_tool_t()
            self._preview_trigger()
        except Exception as e:
            logger.debug("facing wizard init widgets: %s", e)
        finally:
            self._facing_suspend_stale = False

    def _prefill_facing_tool_t(self):
        try:
            t = CNC.vars.get("tool", 0)
            try:
                t_int = int(float(t))
            except (TypeError, ValueError):
                t_int = 0
            if t_int == 0 or t_int >= 999990:
                self.ids.txt_m6_t.text = "1"
            else:
                self.ids.txt_m6_t.text = str(t_int)
        except Exception as e:
            logger.debug("facing prefill tool T: %s", e)

    def _probe_tool_t_from_ui(self) -> int:
        self._ensure_wizard_lists()
        text = self.ids.spn_probe_tool.text
        for label, val in self._probe_tool_pairs_list:
            if text == label:
                return int(val)
        return 999990

    def _stock_origin_corner_from_ui(self) -> str:
        self._ensure_wizard_lists()
        text = self.ids.spn_stock_corner.text
        for label, val in self._stock_corner_pairs_list:
            if text == label:
                return val
        return CORNER_BL

    def _milling_direction_from_ui(self) -> str:
        self._ensure_wizard_lists()
        text = self.ids.spn_milling_dir.text
        for label, val in self._milling_direction_pairs_list:
            if text == label:
                return val
        return MILLING_CLIMB

    def _pattern_from_ui(self) -> str:
        try:
            ids = self.ids
        except Exception:
            return PATTERN_RASTER_X
        if getattr(ids, "raster_spiral_btn", None) and ids.raster_spiral_btn.state == "down":
            return PATTERN_SPIRAL
        if ids.raster_x_btn.state == "down":
            return PATTERN_RASTER_X
        if ids.raster_y_btn.state == "down":
            return PATTERN_RASTER_Y
        return PATTERN_RASTER_X

    def _sync_milling_spinner_for_pattern(self) -> None:
        self._ensure_wizard_lists()
        try:
            spmd = self.ids.spn_milling_dir
        except Exception:
            return
        pat = self._pattern_from_ui()
        if pat == PATTERN_SPIRAL:
            filtered = [
                (lab, v)
                for lab, v in self._milling_direction_pairs_list
                if v != MILLING_BOTH
            ]
            new_values = [p[0] for p in filtered]
            if list(spmd.values) != new_values:
                spmd.values = new_values
            if spmd.text not in spmd.values:
                spmd.text = filtered[0][0]
        else:
            full = [p[0] for p in self._milling_direction_pairs_list]
            if list(spmd.values) != full:
                spmd.values = full
            if spmd.text not in spmd.values:
                spmd.text = self._milling_direction_pairs_list[0][0]

    def _on_dismiss_wizard(self, *args):
        try:
            App.get_running_app().root.restore_keyboard_jog_control()
        except Exception:
            pass

    def _write_temp_nc(self, text: str) -> str:
        root = App.get_running_app().root
        path = os.path.join(root.temp_dir, "facing_wizard.nc")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _attempt_save_gcode_file(self, save_popup: Popup, content: FacingSaveGcodeContent, text: str):
        root = App.get_running_app().root
        raw_name = content.ids.ti_filename.text.strip()
        if not raw_name:
            root.show_message_popup(tr._("Enter a file name."), False)
            return
        fn = os.path.basename(raw_name)
        if not fn:
            root.show_message_popup(tr._("Enter a file name."), False)
            return
        dest_dir = content.ids.fc.path
        if not dest_dir or not os.path.isdir(dest_dir):
            root.show_message_popup(tr._("Choose an existing folder."), False)
            return
        dest = os.path.join(dest_dir, fn)

        def write_file():
            try:
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(text)
                save_popup.dismiss()
                root.show_message_popup(tr._("Saved to:\n%s") % dest, False)
            except OSError as e:
                root.show_message_popup(tr._("Could not save:\n%s") % e, False)

        if os.path.isfile(dest):
            cp = root.confirm_popup
            cp.lb_title.text = tr._("Overwrite file?")
            cp.lb_content.text = tr._("Replace existing file?\n%s") % dest

            def on_overwrite():
                write_file()

            cp.confirm = on_overwrite
            cp.cancel = None
            cp.open(root)
        else:
            write_file()

    def save_gcode_to_file(self, *args):
        text = self._gcode_plain.strip()
        if not text:
            App.get_running_app().root.show_message_popup(tr._("Generate or paste G-code first."), False)
            return

        def _open_dialog():
            root = App.get_running_app().root
            content = FacingSaveGcodeContent()
            try:
                home = os.path.expanduser("~")
                content.ids.fc.path = home if os.path.isdir(home) else "/"
            except Exception:
                content.ids.fc.path = "."
            save_popup = Popup(
                title=tr._("Save G-code"),
                content=content,
                size_hint=(0.85, 0.85),
                auto_dismiss=False,
            )
            content.ids.btn_cancel.bind(on_release=lambda *_: save_popup.dismiss())
            content.ids.btn_save.bind(
                on_release=lambda *_: self._attempt_save_gcode_file(save_popup, content, text)
            )
            save_popup.open()

        if self._facing_gcode_stale:
            self._confirm_facing_stale_then(_open_dialog)
        else:
            _open_dialog()

    def _opt_float_field(self, widget):
        t = widget.text.strip().replace(",", ".")
        if not t:
            return None
        return float(t)

    def _build_probe_to_facing_transition(self) -> str:
        """
        Tool change after Z probe, before facing.
        Default: M6 … C1 with optional collet S and optional repeat count R.
        If any setter offset (X/Y/Z) is given: M6 followed by M491 
        """
        self._ensure_wizard_lists()
        t_text = self.ids.txt_m6_t.text.strip().replace(",", ".")
        if not t_text:
            raise ValueError(tr._("Facing tool T is required."))
        try:
            t_int = int(float(t_text))
        except ValueError:
            raise ValueError(tr._("Facing tool T must be a number (e.g. 1, 2, ...)."))

        s_val = None
        for label, code in self._m6_collet_pairs_list:
            if self.ids.spn_m6_collet.text == label:
                s_val = code
                break

        ox = self._opt_float_field(self.ids.txt_m491_x)
        oy = self._opt_float_field(self.ids.txt_m491_y)
        oz = self._opt_float_field(self.ids.txt_m491_z)
        has_setter_offsets = any(v is not None for v in (ox, oy, oz))

        r_txt = self.ids.txt_tlo_r.text.strip()
        r_val = None
        if r_txt:
            try:
                r_val = int(float(r_txt))
            except ValueError:
                raise ValueError(tr._("TLO repeats must be a whole number."))
            if r_val < 1:
                raise ValueError(tr._("TLO repeats must be at least 1."))

        parts = ["M6", "T%d" % t_int]
        if s_val is not None:
            parts.append("S%d" % s_val)

        if has_setter_offsets:
            parts.append("C0")
            line_m6 = " ".join(parts)
            m491 = ["M491"]
            if ox is not None:
                m491.append("X%g" % ox)
            if oy is not None:
                m491.append("Y%g" % oy)
            if oz is not None:
                m491.append("Z%g" % oz)
            if r_val is not None:
                m491.append("R%d" % r_val)
            return line_m6 + "\n" + " ".join(m491)

        parts.append("C1")
        if r_val is not None:
            parts.append("R%d" % r_val)
        return " ".join(parts)

    def _bind_preview_inputs(self):
        if self._preview_bindings_done:
            return

        self._preview_bind_attempts += 1
        if self._preview_bind_attempts > 40:
            logger.warning("Facing wizard preview: gave up binding inputs after retries")
            return

        try:
            ids = self.ids
            ids.facing_preview_sketch
        except Exception:
            logger.debug("facing preview bind: ids not ready, retrying")
            Clock.schedule_once(lambda _dt: self._bind_preview_inputs(), 0.12)
            return

        if (
            "raster_x_btn" not in ids
            or "raster_y_btn" not in ids
            or "raster_spiral_btn" not in ids
        ):
            logger.debug("facing preview bind: tab widgets missing, retrying")
            Clock.schedule_once(lambda _dt: self._bind_preview_inputs(), 0.12)
            return

        self._preview_bindings_done = True
        self._preview_bind_attempts = 0

        ids = self.ids
        for wid_name in (
            "txt_w",
            "txt_l",
            "txt_mx",
            "txt_my",
            "txt_mz",
            "txt_clear",
            "txt_tool_d",
            "txt_spindle",
            "txt_spindle_dwell",
            "txt_rough_f",
            "txt_rough_plunge",
            "txt_rough_step",
            "txt_rough_doc",
            "txt_rough_total",
            "txt_finish_f",
            "txt_finish_step",
            "txt_finish_depth",
            "txt_grid_nx",
            "txt_grid_ny",
            "txt_probe_approach",
            "txt_probe_travel",
            "txt_probe_f",
            "txt_probe_inset",
            "txt_m6_t",
            "txt_m491_x",
            "txt_m491_y",
            "txt_m491_z",
            "txt_tlo_r",
            "txt_ext_port_s",
        ):
            try:
                getattr(ids, wid_name).bind(text=self._on_facing_input_changed)
            except Exception:
                pass
        for wid_name in ("chk_probe", "chk_finish", "chk_ext_port"):
            try:
                getattr(ids, wid_name).bind(active=self._on_facing_input_changed)
            except Exception:
                pass
        try:
            ids.raster_x_btn.bind(state=self._on_facing_input_changed)
            ids.raster_y_btn.bind(state=self._on_facing_input_changed)
            ids.raster_spiral_btn.bind(state=self._on_facing_input_changed)
        except Exception:
            pass
        for wid_name in ("spn_stock_corner", "spn_milling_dir", "spn_m6_collet", "spn_probe_tool"):
            try:
                getattr(ids, wid_name).bind(text=self._on_facing_input_changed)
            except Exception:
                pass

        ids.facing_preview_sketch.bind(size=self._preview_trigger)

    def _on_facing_input_changed(self, *args):
        self._sync_milling_spinner_for_pattern()
        self._mark_facing_gcode_stale_from_ui()
        self._preview_trigger()

    def _mark_facing_gcode_stale_from_ui(self, *args):
        if self._facing_suspend_stale:
            return
        if self._gcode_plain.strip():
            self._facing_gcode_stale = True

    def _build_probe_params_from_ui(self) -> ProbeGridParams:
        self._ensure_wizard_lists()
        pg = ProbeGridParams(
            stock_width_mm=_parse_float_widget(self.ids.txt_w, tr._("Stock width (mm)")),
            stock_length_mm=_parse_float_widget(self.ids.txt_l, tr._("Stock length (mm)")),
            stock_origin_corner=self._stock_origin_corner_from_ui(),
            margin_x_mm=_parse_float_widget(self.ids.txt_mx, tr._("Margin X (mm)")),
            margin_y_mm=_parse_float_widget(self.ids.txt_my, tr._("Margin Y (mm)")),
            clearance_z_mm=_parse_float_widget(self.ids.txt_clear, tr._("Clearance Z (mm)")),
            approach_z_mm=_parse_float_widget(self.ids.txt_probe_approach, tr._("Probe approach Z (mm)")),
            probe_z_travel_mm=_parse_float_widget(self.ids.txt_probe_travel, tr._("Probe Z travel (mm)")),
            probe_feed_mm_min=_parse_float_widget(self.ids.txt_probe_f, tr._("Probe feed (mm/min)")),
            grid_nx=int(_parse_float_widget(self.ids.txt_grid_nx, tr._("Grid NX"))),
            grid_ny=int(_parse_float_widget(self.ids.txt_grid_ny, tr._("Grid NY"))),
            inset_mm=_optional_float(self.ids.txt_probe_inset, 0.0),
            probe_tool_t=self._probe_tool_t_from_ui(),
        )
        if pg.clearance_z_mm <= 0:
            raise ValueError(tr._("Clearance Z must be positive."))
        if pg.approach_z_mm <= 0:
            raise ValueError(tr._("Probe approach Z must be positive."))
        if pg.probe_z_travel_mm > -0.01:
            raise ValueError(tr._("Probe Z travel must be negative (e.g. -30)."))
        if pg.grid_nx < 1 or pg.grid_ny < 1:
            raise ValueError(tr._("Grid NX and NY must be at least 1."))
        return pg

    def _ext_port_options_from_ui(self) -> tuple[bool, int]:
        """(enabled, PWM 0–100 for M851 S in G-code)."""
        if not self.ids.chk_ext_port.active:
            return False, 100
        raw = self.ids.txt_ext_port_s.text.strip().replace(",", ".")
        if not raw:
            raise ValueError(tr._("Ext. port is enabled but PWM % is empty."))
        try:
            s_val = int(round(float(raw)))
        except ValueError:
            raise ValueError(tr._("Ext. port PWM % must be a number."))
        if s_val < 0 or s_val > 100:
            raise ValueError(tr._("Ext. port PWM % is out of range (0–100)."))
        return True, s_val

    def _build_facing_params_from_ui(self) -> FacingParams:
        self._ensure_wizard_lists()
        ext_on, ext_pwm = self._ext_port_options_from_ui()
        fp = FacingParams(
            stock_width_mm=_parse_float_widget(self.ids.txt_w, tr._("Stock width (mm)")),
            stock_length_mm=_parse_float_widget(self.ids.txt_l, tr._("Stock length (mm)")),
            stock_origin_corner=self._stock_origin_corner_from_ui(),
            margin_x_mm=_parse_float_widget(self.ids.txt_mx, tr._("Margin X (mm)")),
            margin_y_mm=_parse_float_widget(self.ids.txt_my, tr._("Margin Y (mm)")),
            margin_z_mm=_parse_float_widget(self.ids.txt_mz, tr._("Extra depth (mm)")),
            tool_diameter_mm=_parse_float_widget(self.ids.txt_tool_d, tr._("Facing tool diameter (mm)")),
            clearance_z_mm=_parse_float_widget(self.ids.txt_clear, tr._("Clearance Z (mm)")),
            spindle_rpm=_parse_float_widget(self.ids.txt_spindle, tr._("Spindle RPM")),
            spindle_spinup_dwell_s=_parse_non_negative_int_widget(self.ids.txt_spindle_dwell, tr._("Spindle dwell (s)")),
            pattern=self._pattern_from_ui(),
            milling_direction=self._milling_direction_from_ui(),
            rough_feed_mm_min=_parse_float_widget(self.ids.txt_rough_f, tr._("Rough feed (mm/min)")),
            rough_plunge_feed_mm_min=_parse_float_widget(self.ids.txt_rough_plunge, tr._("Rough plunge feed (mm/min)")),
            rough_stepover_mm=_parse_float_widget(self.ids.txt_rough_step, tr._("Rough stepover (mm)")),
            rough_depth_per_pass_mm=_parse_float_widget(self.ids.txt_rough_doc, tr._("Rough depth / pass (mm)")),
            rough_total_depth_mm=_parse_float_widget(self.ids.txt_rough_total, tr._("Rough total depth (mm)")),
            finish_enabled=self.ids.chk_finish.active,
            finish_feed_mm_min=_optional_float(self.ids.txt_finish_f, 600.0),
            finish_stepover_mm=_optional_float(self.ids.txt_finish_step, 0.5),
            finish_depth_mm=_optional_float(self.ids.txt_finish_depth, 0.2),
            ext_port_enabled=ext_on,
            ext_port_pwm=ext_pwm,
        )
        if fp.clearance_z_mm <= 0:
            raise ValueError(tr._("Clearance Z must be positive."))
        return fp

    def _update_preview_safe(self, *args):
        try:
            self._update_preview(*args)
        except Exception:
            logger.exception("Facing wizard preview update failed")

    def _update_preview(self, *args):
        try:
            lbl_err = self.ids.lbl_preview_error
            sketch = self.ids.facing_preview_sketch
        except Exception:
            return
        lbl_err.text = ""

        try:
            w = _parse_float_widget(self.ids.txt_w, tr._("Stock width (mm)"))
            sl = _parse_float_widget(self.ids.txt_l, tr._("Stock length (mm)"))
            mx = _parse_float_widget(self.ids.txt_mx, tr._("Margin X (mm)"))
            my = _parse_float_widget(self.ids.txt_my, tr._("Margin Y (mm)"))
        except ValueError:
            sketch.clear_geometry()
            return

        corner = self._stock_origin_corner_from_ui()
        stock_rect = stock_rect_from_origin_corner(w, sl, corner)
        machining_rect = rect_with_xy_margin(stock_rect, mx, my)
        try:
            fp = self._build_facing_params_from_ui()
            facing_env = compute_facing_envelope(fp)
            toolpath_pts = facing_toolpath_xy_polyline(facing_env)
        except ValueError as e:
            sketch.clear_geometry()
            lbl_err.text = str(e)
            return

        probe_geom = None
        if self.ids.chk_probe.active:
            try:
                probe_geom = compute_probe_grid_xy(self._build_probe_params_from_ui())
            except ValueError as e:
                sketch.clear_geometry()
                lbl_err.text = str(e)
                return

        sketch.set_geometry(
            stock_rect=stock_rect,
            machining_rect=machining_rect,
            facing=facing_env,
            probe_geom=probe_geom,
            toolpath=toolpath_pts,
        )

    def generate_program(self, *args):
        try:
            self._ensure_wizard_lists()
            fp = self._build_facing_params_from_ui()
            face_str = generate_facing_gcode(fp).rstrip()

            probe_str = ""
            if self.ids.chk_probe.active:
                pg = self._build_probe_params_from_ui()
                probe_str = generate_probe_grid_gcode(pg, end_program=False).rstrip()

            blocks: list[str] = []
            if probe_str:
                blocks.append(probe_str)
            blocks.append(self._build_probe_to_facing_transition())
            if probe_str:
                blocks.append(probe_grid_z_datum_shift_after_probe_gcode())
            blocks.append(face_str)
            combined = "\n".join(blocks) + "\n"
            self._gcode_plain = combined
            self._facing_gcode_stale = False
            self._refresh_gcode_preview()
        except ValueError as e:
            App.get_running_app().root.show_message_popup(str(e), False)

    def _confirm_facing_stale_then(self, proceed):
        root = App.get_running_app().root
        cp = root.confirm_popup
        cp.lb_title.text = tr._("G-code may be out of date")
        cp.lb_content.text = tr._(
            "Parameters changed since last Generate. The preview may not match what you run. Continue anyway?"
        )
        cp.confirm = proceed
        cp.cancel = None
        cp.open(root)

    def _switch_to_gcode_viewer_screen(self):
        """Show file/viewer layout (not Control) and hide viewer tool + playback chrome."""
        app = App.get_running_app()
        root = app.root
        if root.content.current != "File":
            root.content.transition.direction = "right"
            root.content.current = "File"
        app.show_gcode_ctl_bar = False
        try:
            root.cmd_manager.transition.direction = "right"
            root.cmd_manager.current = "gcode_cmd_page"
        except Exception:
            pass

    def load_in_viewer(self, *args):
        text = self._gcode_plain.strip()
        if not text:
            App.get_running_app().root.show_message_popup(tr._("Generate or paste G-code first."), False)
            return

        def _do_load():
            path = self._write_temp_nc(text)
            root = App.get_running_app().root
            self.dismiss()
            self._switch_to_gcode_viewer_screen()
            root.progress_popup.progress_value = 0
            root.progress_popup.btn_cancel.disabled = True
            root.progress_popup.progress_text = tr._("Loading file") + "\n%s" % path
            root.progress_popup.open()
            threading.Thread(target=root.load_gcode_file, args=(path,), daemon=True).start()

        if self._facing_gcode_stale:
            self._confirm_facing_stale_then(_do_load)
        else:
            _do_load()

    def upload_to_machine(self, *args):
        text = self._gcode_plain.strip()
        if not text:
            App.get_running_app().root.show_message_popup(tr._("Generate or paste G-code first."), False)
            return

        def _do_upload():
            path = self._write_temp_nc(text)
            root = App.get_running_app().root
            self.dismiss()
            self._switch_to_gcode_viewer_screen()
            root.uploadLocalFile(path, root.select_file)

        if self._facing_gcode_stale:
            self._confirm_facing_stale_then(_do_upload)
        else:
            _do_upload()
