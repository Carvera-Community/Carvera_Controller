"""
Facing wizard — Community firmware and millimeters only.
"""

import logging
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.modalview import ModalView

from carveracontroller.CNC import CNC, escape_gcode_markup, highlight_gcode_line
from carveracontroller.translation import tr

from .facing_gcode import (
    MILLING_BOTH,
    MILLING_CLIMB,
    MILLING_CONVENTIONAL,
    FacingParams,
    compute_facing_envelope,
    facing_raster_xy_polyline,
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

# Loads facing_preview_sketch so Factory registers widget name "FacingSketch" for KV before Builder applies rules.
from . import facing_preview_sketch as _facing_preview_sketch

logger = logging.getLogger(__name__)


def _parse_float_widget(widget, label: str) -> float:
    t = widget.text.strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    return float(t)


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

            self._prefill_facing_tool_t()
            self._preview_trigger()
        except Exception as e:
            logger.debug("facing wizard init widgets: %s", e)

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

        if "raster_x_btn" not in ids or "raster_y_btn" not in ids:
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
        ):
            try:
                getattr(ids, wid_name).bind(text=self._preview_trigger)
            except Exception:
                pass
        for wid_name in ("chk_probe", "chk_finish"):
            try:
                getattr(ids, wid_name).bind(active=self._preview_trigger)
            except Exception:
                pass
        try:
            ids.raster_x_btn.bind(state=self._preview_trigger)
            ids.raster_y_btn.bind(state=self._preview_trigger)
        except Exception:
            pass
        try:
            ids.spn_stock_corner.bind(text=self._preview_trigger)
        except Exception:
            pass
        try:
            ids.spn_milling_dir.bind(text=self._preview_trigger)
        except Exception:
            pass

        ids.facing_preview_sketch.bind(size=self._preview_trigger)

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

    def _build_facing_params_from_ui(self) -> FacingParams:
        self._ensure_wizard_lists()
        fp = FacingParams(
            stock_width_mm=_parse_float_widget(self.ids.txt_w, tr._("Stock width (mm)")),
            stock_length_mm=_parse_float_widget(self.ids.txt_l, tr._("Stock length (mm)")),
            stock_origin_corner=self._stock_origin_corner_from_ui(),
            margin_x_mm=_parse_float_widget(self.ids.txt_mx, tr._("Margin X (mm)")),
            margin_y_mm=_parse_float_widget(self.ids.txt_my, tr._("Margin Y (mm)")),
            margin_z_mm=_parse_float_widget(self.ids.txt_mz, tr._("Extra depth (mm)")),
            tool_diameter_mm=_parse_float_widget(self.ids.txt_tool_d, tr._("Tool diameter (mm)")),
            clearance_z_mm=_parse_float_widget(self.ids.txt_clear, tr._("Clearance Z (mm)")),
            spindle_rpm=_parse_float_widget(self.ids.txt_spindle, tr._("Spindle RPM")),
            raster_along_x=self.ids.raster_x_btn.state == "down",
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
            raster_pts = facing_raster_xy_polyline(facing_env)
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
            raster=raster_pts,
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
            self._refresh_gcode_preview()
        except ValueError as e:
            App.get_running_app().root.show_message_popup(str(e), False)

    def load_in_viewer(self, *args):
        text = self._gcode_plain.strip()
        if not text:
            App.get_running_app().root.show_message_popup(tr._("Generate or paste G-code first."), False)
            return
        path = self._write_temp_nc(text)
        root = App.get_running_app().root
        root.progress_popup.progress_value = 0
        root.progress_popup.btn_cancel.disabled = True
        root.progress_popup.progress_text = tr._("Loading file") + "\n%s" % path
        root.progress_popup.open()
        threading.Thread(target=root.load_gcode_file, args=(path,), daemon=True).start()

    def upload_to_machine(self, *args):
        text = self._gcode_plain.strip()
        if not text:
            App.get_running_app().root.show_message_popup(tr._("Generate or paste G-code first."), False)
            return
        path = self._write_temp_nc(text)
        App.get_running_app().root.uploadLocalFile(path, App.get_running_app().root.select_file)
