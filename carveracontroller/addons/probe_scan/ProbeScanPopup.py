from __future__ import annotations

import logging
import os
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

from kivy.factory import Factory

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.serial_listeners import (
    register_serial_listener,
    unregister_serial_listener,
)
from carveracontroller.translation import tr

from .construction_geom import (
    circle_circle_intersections_2d,
    circle_line_intersections_2d,
    circumcircle_2d,
    line_intersection_2d,
    midpoint_2d,
    tangent_circle_to_circle_external_2d,
    tangent_point_to_circle_2d,
)
from .coordinate_transform import mcs_xyz_to_wcs_xyz
from .export_format import export_csv, export_dxf, export_json
from .gcode_builders import (
    build_m461,
    build_m462,
    build_m463,
    build_m464,
    build_m465,
    build_m466,
    split_execute_lines,
)
from .feature_resolve import (
    features_referencing_id,
    index_by_id,
    resolve_circle,
    resolve_xy,
    segment_endpoints,
)
from .gcode_m118 import extract_probe_start_meta
from .m118_capture import M118ProbeCapture, map_values_to_dict
from .scan_preview_sketch import ProbeScanPreviewSketch
from .session import CoordSys, FeatureKind, ProbeScanFeature, ProbeScanSession

if "ProbeScanPreviewSketch" not in Factory.classes:
    Factory.register("ProbeScanPreviewSketch", cls=ProbeScanPreviewSketch)


class ProbeScanIconToggle(ToggleButton):

    image = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)


if "ProbeScanIconToggle" not in Factory.classes:
    Factory.register("ProbeScanIconToggle", cls=ProbeScanIconToggle)


class JogProbeScanPopup(ModalView):

    _jog_height_tracking_inited = False

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        Clock.schedule_once(self._ensure_jog_height_tracking, 0)

    def on_open(self):
        super().on_open()
        Clock.schedule_once(self._snap_modal_height_to_inner, -1)
        Clock.schedule_once(self._snap_modal_height_to_inner, 0.05)

    def _snap_modal_height_to_inner(self, _dt=None):
        try:
            inner = self.ids.jog_modal_inner
        except KeyError:
            return
        mh = inner.minimum_height
        if mh > 0:
            self.height = max(mh, 1)

    def _ensure_jog_height_tracking(self, _dt=None):
        try:
            inner = self.ids.jog_modal_inner
        except KeyError:
            return
        if self._jog_height_tracking_inited:
            return
        self._jog_height_tracking_inited = True

        def on_geom(*_args):
            self._snap_modal_height_to_inner()

        def on_width(*_args):
            Clock.schedule_once(self._snap_modal_height_to_inner, 0)

        inner.bind(minimum_height=on_geom, width=on_width)
        self._snap_modal_height_to_inner()

if "JogProbeScanPopup" not in Factory.classes:
    Factory.register("JogProbeScanPopup", cls=JogProbeScanPopup)

logger = logging.getLogger(__name__)


def _parse_float_field(w: TextInput, default: float = 0.0) -> float:
    t = w.text.strip().replace(",", ".")
    if not t:
        return default
    return float(t)


def _parse_optional_float_text(w: TextInput) -> str | None:
    t = w.text.strip().replace(",", ".")
    if not t:
        return None
    float(t)
    return t


def _fmt_wcs_manual_field(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_gcode(v: float) -> str:
    if v == int(v):
        return str(int(v))
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _distance_for_command(text: str, *, negate: bool) -> str:
    v = abs(float(text.strip().replace(",", ".")))
    if negate:
        v = -v
    return _fmt_gcode(v)


def _signed_distance_for_command(text: str) -> str:
    return _fmt_gcode(float(text.strip().replace(",", ".")))


def _corner_deltas_from_quadrant(quadrant: str, mx: float, my: float) -> tuple[float, float]:
    ax, ay = abs(mx), abs(my)
    signs: dict[str, tuple[int, int]] = {
        "BottomLeft": (1, 1),
        "BottomRight": (-1, 1),
        "TopLeft": (1, -1),
        "TopRight": (-1, -1),
    }
    sx, sy = signs.get(quadrant, (1, 1))
    return sx * ax, sy * ay


_PROBE_ANIM_FRAMES = ("◐", "◓", "◑", "◒")
_PROBE_TIMEOUT_S = 60.0


class ProbeScanPopup(ModalView):
    controller: Controller
    _listener_handle: int | None = None
    _capture: M118ProbeCapture | None = None

    is_probing = BooleanProperty(False)
    probing_status_text = StringProperty("")

    # Construction button enable states — recomputed after every selection change.
    can_make_segment = BooleanProperty(False)
    can_make_polyline_open = BooleanProperty(False)
    can_make_polyline_closed = BooleanProperty(False)
    can_make_circumcircle = BooleanProperty(False)
    can_make_intersection = BooleanProperty(False)
    can_make_midpoint = BooleanProperty(False)
    can_make_tangent = BooleanProperty(False)
    has_construct_selection = BooleanProperty(False)

    def __init__(self, controller: Controller, **kwargs):
        self.controller = controller
        self.session = ProbeScanSession()
        self._selection_order: list[str] = []
        self._preview_focus_id: str | None = None
        self._angle_variant: str | None = None
        self._m466_side: str | None = None
        self._m461_preset: str | None = None
        self._m462_preset: str | None = None
        self._m463_quadrant: str | None = None
        self._m464_quadrant: str | None = None
        self._jog_popup = None
        self._probe_anim_event = None
        self._probe_timeout_event = None
        self._probe_anim_frame: int = 0
        super().__init__(**kwargs)

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        try:
            self.ids.sketch.on_feature_tap = self._on_sketch_feature_tap
        except Exception:
            logger.debug("sketch tap hook", exc_info=True)

    def _on_sketch_feature_tap(self, feat_id: str) -> None:
        """Called by ProbeScanPreviewSketch when the user taps a feature."""
        if self._preview_focus_id == feat_id:
            self._preview_focus_id = None
        else:
            self._preview_focus_id = feat_id
        self._refresh_feature_ui()
        Clock.schedule_once(lambda _dt: self._scroll_to_feature(feat_id), 0.05)

    def _scroll_to_feature(self, feat_id: str) -> None:
        """Scroll the feature list so the row for feat_id is visible."""
        try:
            sv = self.ids.feature_rows_scroll
            grid = self.ids.feature_rows
            # Find which row index corresponds to feat_id.
            idx = next(
                (i for i, f in enumerate(self.session.features) if f.id == feat_id),
                None,
            )
            if idx is None:
                return
            n = len(self.session.features)
            if n <= 1:
                return
            grid_h = grid.height
            sv_h = sv.height
            if grid_h <= sv_h:
                return
            # Approximate row top from grid bottom (rows are stacked bottom-to-top in Kivy).
            # Each row is either dp(50) or dp(40); use the child widgets if available.
            children = list(reversed(grid.children))  # grid children are in reverse order
            if idx >= len(children):
                return
            child = children[idx]
            # child.y is relative to grid bottom (Kivy stacks bottom-to-top).
            child_bot = child.y
            # scroll_y=1 → top of content; scroll_y=0 → bottom.
            # Convert child position to scroll_y.
            scroll_range = grid_h - sv_h
            # We want the child to be centred in the viewport.
            target_bottom = child_bot - (sv_h - child.height) / 2.0
            target_sy = max(0.0, min(1.0, target_bottom / scroll_range))
            sv.scroll_y = target_sy
        except Exception:
            logger.debug("scroll to feature", exc_info=True)

    def open_jog_popup(self, *_args):
        jog = getattr(self, "_jog_popup", None)
        if jog is None:
            jog = Factory.JogProbeScanPopup()
            self._jog_popup = jog
        jog.open()

    def _dismiss_jog_popup(self):
        jog = getattr(self, "_jog_popup", None)
        if jog is not None:
            jog.dismiss()

    def on_open(self):
        self._capture = M118ProbeCapture(self._on_probe_values)
        self._listener_handle = register_serial_listener(self._capture.feed_line)
        Clock.schedule_interval(self._tick_wcs_live, 0.35)
        Clock.schedule_once(lambda _dt: self._tick_wcs_live(), 0.05)
        Clock.schedule_once(lambda _dt: self._sync_manual_wcs_fields_from_machine(), 0.08)
        Clock.schedule_once(lambda _dt: self._refresh_feature_ui(), 0)

    def on_dismiss(self):
        self._dismiss_jog_popup()
        self._stop_probing()
        Clock.unschedule(self._tick_wcs_live)
        if self._listener_handle is not None:
            unregister_serial_listener(self._listener_handle)
            self._listener_handle = None
        self._capture = None
        App.get_running_app().root.restore_keyboard_jog_control()

    def _start_probing(self) -> None:
        self._probe_anim_frame = 0
        self.is_probing = True
        self._update_probing_text()
        if self._probe_anim_event is not None:
            self._probe_anim_event.cancel()
        self._probe_anim_event = Clock.schedule_interval(self._tick_probe_anim, 0.18)
        if self._probe_timeout_event is not None:
            self._probe_timeout_event.cancel()
        self._probe_timeout_event = Clock.schedule_once(
            lambda _dt: self._stop_probing(), _PROBE_TIMEOUT_S
        )

    def _stop_probing(self) -> None:
        self.is_probing = False
        self.probing_status_text = ""
        if self._probe_anim_event is not None:
            self._probe_anim_event.cancel()
            self._probe_anim_event = None
        if self._probe_timeout_event is not None:
            self._probe_timeout_event.cancel()
            self._probe_timeout_event = None

    def _tick_probe_anim(self, _dt=None) -> None:
        self._probe_anim_frame = (self._probe_anim_frame + 1) % len(_PROBE_ANIM_FRAMES)
        self._update_probing_text()

    def _update_probing_text(self) -> None:
        frame = _PROBE_ANIM_FRAMES[self._probe_anim_frame % len(_PROBE_ANIM_FRAMES)]
        self.probing_status_text = f"{frame}  {tr._('Probing in progress…')}"

    def _tick_wcs_live(self, *_args):
        try:
            lbl = self.ids.lbl_wcs_live
            wx = float(CNC.vars.get("wx", 0.0))
            wy = float(CNC.vars.get("wy", 0.0))
            wz = float(CNC.vars.get("wz", 0.0))
            lbl.text = (
                f"[b]{tr._('Current position')}[/b]\n"
                f"X  {wx:+.4f}   Y  {wy:+.4f}   Z  {wz:+.4f}"
            )
        except Exception:
            logger.debug("wcs tick", exc_info=True)

    def _sync_manual_wcs_fields_from_machine(self, *_args):
        try:
            wx = float(CNC.vars.get("wx", 0.0))
            wy = float(CNC.vars.get("wy", 0.0))
            wz = float(CNC.vars.get("wz", 0.0))
            self.ids.t_manual_wx.text = _fmt_wcs_manual_field(wx)
            self.ids.t_manual_wy.text = _fmt_wcs_manual_field(wy)
            self.ids.t_manual_wz.text = _fmt_wcs_manual_field(wz)
        except Exception:
            logger.debug("manual wcs sync", exc_info=True)

    def on_manual_sync_from_machine(self, *_args):
        self._sync_manual_wcs_fields_from_machine()

    def _parse_manual_wcs_xyz_from_fields(self) -> tuple[float, float, float] | None:
        vals: list[float] = []
        for w in (self.ids.t_manual_wx, self.ids.t_manual_wy, self.ids.t_manual_wz):
            t = w.text.strip().replace(",", ".")
            if not t:
                self._toast(tr._("Enter X, Y, and Z."))
                return None
            try:
                vals.append(float(t))
            except ValueError:
                self._toast(tr._("Invalid coordinate."))
                return None
        return vals[0], vals[1], vals[2]

    def _toast(self, msg: str):
        root = App.get_running_app().root
        if hasattr(root, "show_message_popup"):
            root.show_message_popup(msg, False)

    def _toast_need_probing_option(self) -> None:
        self._toast(tr._("Select a probing option before running."))

    def _idle_ok(self) -> bool:
        app = App.get_running_app()
        return app.state == "Idle"

    def _run_gcode_program(self, program: str):
        if not self._idle_ok():
            self._toast(tr._("Machine must be Idle to probe."))
            return
        lines = split_execute_lines(program)
        if not lines:
            self._toast(tr._("No G-code to run."))
            return
        if self._capture is not None:
            for ln in lines:
                meta = extract_probe_start_meta(ln)
                if meta:
                    op, keys = meta
                    self._capture.prime_upstream(op, keys)
                    break
        self._start_probing()
        for ln in lines:
            self.controller.executeCommand(ln + "\n")

    def _on_probe_values(self, op: str, values: list[float], var_keys: list[str]):
        def _ui(_dt):
            self._stop_probing()
            vd = map_values_to_dict(op, values, var_keys)
            self._append_probe_result(op, vd)

        Clock.schedule_once(_ui, 0)

    def _append_probe_result(self, op: str, vd: dict[str, float]):
        if op == "M466":
            mx = float(CNC.vars.get("mx", 0.0))
            my = float(CNC.vars.get("my", 0.0))
            mz = float(CNC.vars.get("mz", 0.0))
            x_m = vd["154"] if "154" in vd else mx
            y_m = vd["155"] if "155" in vd else my
            z_m = vd["156"] if "156" in vd else mz
            wx, wy, wz = mcs_xyz_to_wcs_xyz(x_m, y_m, z_m)
            f = ProbeScanFeature.new_point(
                tr._("Touch probe (M466)"),
                wx,
                wy,
                wz,
                source="M466",
                coord_sys=CoordSys.WCS,
            )
            self.session.features.append(f)
        elif op in ("M461", "M462"):
            cx_m = float(vd.get("154", 0.0))
            cy_m = float(vd.get("155", 0.0))
            wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
            f = ProbeScanFeature.new_circle(
                tr._("Bore center (M461)")
                if op == "M461"
                else tr._("Boss center (M462)"),
                wx,
                wy,
                float(vd.get("151", 0.0)),
                float(vd.get("152", 0.0)),
                coord_sys=CoordSys.WCS,
            )
            self.session.features.append(f)
        elif op in ("M463", "M464"):
            xm = float(vd.get("154", 0.0))
            ym = float(vd.get("155", 0.0))
            wx, wy, _ = mcs_xyz_to_wcs_xyz(xm, ym, 0.0)
            f = ProbeScanFeature.new_corner(
                tr._("Inside corner (M463)")
                if op == "M463"
                else tr._("Outside corner (M464)"),
                wx,
                wy,
                coord_sys=CoordSys.WCS,
            )
            self.session.features.append(f)
        elif op == "M465":
            f = ProbeScanFeature.new_angle(
                tr._("Angle (M465)"),
                float(vd.get("153", 0.0)),
                probe_variant=str(self._angle_variant or ""),
            )
            self.session.features.append(f)
        self._refresh_feature_ui()

    def _kind_has_vertex_xy(self, f: ProbeScanFeature) -> bool:
        return f.kind in (
            FeatureKind.POINT,
            FeatureKind.CORNER,
            FeatureKind.CIRCLE,
            FeatureKind.DERIVED_POINT,
        )

    def _payload_wcs_xyz_for_display(
        self, feat: ProbeScanFeature
    ) -> tuple[float, float, float] | None:
        p = feat.payload
        k = feat.kind
        try:
            if k in (FeatureKind.POINT, FeatureKind.CORNER, FeatureKind.DERIVED_POINT):
                return float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
            if k in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
                return float(p["cx"]), float(p["cy"]), 0.0
        except (KeyError, TypeError, ValueError):
            return None
        return None

    def _fmt_wcs_xy_detail(
        self,
        x: float,
        y: float,
        *,
        feat: ProbeScanFeature | None,
        z_fallback: float = 0.0,
    ) -> str:
        """Table detail text: Z only if the feature actually stores elevation."""
        if feat is not None and "z" in feat.payload:
            try:
                zv = float(feat.payload["z"])
            except (TypeError, ValueError):
                zv = z_fallback
            return tr._("X=%(x).3f  Y=%(y).3f  Z=%(z).3f") % {
                "x": x,
                "y": y,
                "z": zv,
            }
        return tr._("X=%(x).3f  Y=%(y).3f") % {"x": x, "y": y}

    def _feature_secondary_line(
        self,
        feat: ProbeScanFeature,
        by_id: dict[str, ProbeScanFeature],
    ) -> str:
        p = feat.payload
        k = feat.kind
        if k == FeatureKind.ANGLE:
            deg = float(p.get("degrees", 0.0))
            line = tr._("Measured %(deg).5f °") % {"deg": deg}
            pv = str(p.get("probe_variant") or "").strip()
            return f"{line} · {pv}" if pv else line

        xyz = self._payload_wcs_xyz_for_display(feat)
        if xyz is not None:
            x_, y_, z_ = xyz
            line = self._fmt_wcs_xy_detail(x_, y_, feat=feat, z_fallback=z_)
            if k == FeatureKind.CIRCLE:
                try:
                    dx = float(p.get("diameter_x", 0.0))
                    dy = float(p.get("diameter_y", 0.0))
                except (TypeError, ValueError):
                    dx = dy = 0.0
                dim = tr._("Ø %(dx).3f × %(dy).3f") % {"dx": dx, "dy": dy}
                return f"{line} · {dim}"
            if k == FeatureKind.DERIVED_CIRCLE:
                try:
                    r = float(p.get("r", 0.0))
                except (TypeError, ValueError):
                    r = 0.0
                rad = tr._("R %(r).3f") % {"r": r}
                return f"{line} · {rad}"
            return line

        if k == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, feat)
            if not ends:
                return ""
            pa, pb = ends
            wa = by_id.get(str(p.get("a_id", "")))
            wb = by_id.get(str(p.get("b_id", "")))
            za = zb = 0.0
            if wa:
                ta = self._payload_wcs_xyz_for_display(wa)
                if ta:
                    za = ta[2]
            if wb:
                tb = self._payload_wcs_xyz_for_display(wb)
                if tb:
                    zb = tb[2]
            x1, y1 = pa
            x2, y2 = pb
            sa = self._fmt_wcs_xy_detail(x1, y1, feat=wa, z_fallback=za)
            sb = self._fmt_wcs_xy_detail(x2, y2, feat=wb, z_fallback=zb)
            return tr._("A %(sa)s  →  B %(sb)s") % {"sa": sa, "sb": sb}

        if k == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list) or len(verts) < 2:
                return ""
            vert_rows: list[tuple[ProbeScanFeature | None, float, float, float]] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                if wf is None:
                    return ""
                xyzv = self._payload_wcs_xyz_for_display(wf)
                if xyzv is not None:
                    vert_rows.append((wf, xyzv[0], xyzv[1], xyzv[2]))
                    continue
                xy = resolve_xy(wf)
                if xy is None:
                    return ""
                vert_rows.append((wf, float(xy[0]), float(xy[1]), 0.0))
            n = len(vert_rows)
            if n <= 4:
                parts = [
                    tr._("%(vi)d: %(det)s")
                    % {
                        "vi": i + 1,
                        "det": self._fmt_wcs_xy_detail(
                            vx, vy, feat=wf, z_fallback=vz
                        ),
                    }
                    for i, (wf, vx, vy, vz) in enumerate(vert_rows)
                ]
                return "; ".join(parts)
            wf0, x0, y0, z0 = vert_rows[0]
            wfk, xk, yk, zk = vert_rows[-1]
            s0 = self._fmt_wcs_xy_detail(x0, y0, feat=wf0, z_fallback=z0)
            sk = self._fmt_wcs_xy_detail(xk, yk, feat=wfk, z_fallback=zk)
            return tr._("%(num)d verts: %(s0)s  …  %(sk)s") % {
                "num": n,
                "s0": s0,
                "sk": sk,
            }

        return ""

    def _sanitize_feature_ui_state(self):
        avail = {f.id for f in self.session.features}
        if self._preview_focus_id is not None and self._preview_focus_id not in avail:
            self._preview_focus_id = None
        self._selection_order[:] = [x for x in self._selection_order if x in avail]

    def _recompute_construct_buttons(self) -> None:
        """Update can_* properties based on current selection and feature types."""
        by_id = index_by_id(self.session.features)
        ids = list(self._selection_order)
        n = len(ids)
        self.has_construct_selection = n > 0

        # Helpers
        def is_point_like(fid: str) -> bool:
            f = by_id.get(fid)
            return f is not None and self._kind_has_vertex_xy(f) and resolve_xy(f) is not None

        def is_segment(fid: str) -> bool:
            f = by_id.get(fid)
            return f is not None and f.kind == FeatureKind.SEGMENT

        def is_circle_like(fid: str) -> bool:
            f = by_id.get(fid)
            return f is not None and f.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE)

        # Segment: exactly 2 point-like features
        self.can_make_segment = (
            n == 2 and all(is_point_like(fid) for fid in ids)
        )
        # Open polyline: 2+ point-like
        self.can_make_polyline_open = (
            n >= 2 and all(is_point_like(fid) for fid in ids)
        )
        # Closed polyline: 3+ point-like
        self.can_make_polyline_closed = (
            n >= 3 and all(is_point_like(fid) for fid in ids)
        )
        # Circumcircle: exactly 3 point-like features
        self.can_make_circumcircle = (
            n == 3 and all(is_point_like(fid) for fid in ids)
        )
        # Intersection: 2 segments OR 2 lines (segments) OR circle+segment OR 2 circles
        self.can_make_intersection = (
            n == 2 and (
                all(is_segment(fid) for fid in ids)
                or all(is_circle_like(fid) for fid in ids)
                or (is_circle_like(ids[0]) and is_segment(ids[1]))
                or (is_segment(ids[0]) and is_circle_like(ids[1]))
            )
        )
        # Midpoint: exactly 2 point-like features
        self.can_make_midpoint = (
            n == 2 and all(is_point_like(fid) for fid in ids)
        )
        # Tangent: 1 point + 1 circle, or 2 circles
        self.can_make_tangent = n == 2 and (
            (is_point_like(ids[0]) and is_circle_like(ids[1]))
            or (is_circle_like(ids[0]) and is_point_like(ids[1]))
            or all(is_circle_like(fid) for fid in ids)
        )

    def _on_feature_row_label_touch(self, feat_id: str, instance: Label, touch):
        if not instance.collide_point(*touch.pos):
            return False
        if self._preview_focus_id == feat_id:
            self._preview_focus_id = None
        else:
            self._preview_focus_id = feat_id
        self._refresh_feature_ui()
        return True

    def _refresh_feature_ui(self):
        try:
            self._sanitize_feature_ui_state()
            self._recompute_construct_buttons()
            fl = self.ids.feature_rows
            fl.clear_widgets()
            by_id = index_by_id(self.session.features)
            title_font = sp(13)
            detail_font = sp(11)
            for i, feat in enumerate(self.session.features):
                line1 = f"{i + 1}. {feat.label}"
                line2 = self._feature_secondary_line(feat, by_id)
                row_h = dp(50) if line2 else dp(40)
                row = BoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=row_h,
                    spacing=dp(4),
                    padding=[0, 0, dp(4), 0],
                )
                if feat.id == self._preview_focus_id:
                    with row.canvas.before:
                        Color(0.18, 0.38, 0.58, 0.22)
                        rect = Rectangle(pos=row.pos, size=row.size)

                    def _upd_focus_bg(*_a, r=rect, rw=row):
                        r.pos = rw.pos
                        r.size = rw.size

                    row.bind(pos=_upd_focus_bg, size=_upd_focus_bg)
                cb_col = BoxLayout(
                    orientation="horizontal",
                    size_hint_x=None,
                    width=dp(36),
                    size_hint_y=1,
                    padding=[0, 0, 0, 0],
                    spacing=0,
                )
                cb = CheckBox(size_hint=(1, 1))
                cb.active = feat.id in self._selection_order
                cb.bind(active=partial(self._on_row_checkbox, feat.id))
                cb_col.add_widget(cb)

                lbl = Label(
                    text=(
                        line1
                        if not line2
                        else (
                            f"{line1}\n"
                            f"[color=78797f][size={int(round(detail_font))}]{line2}[/size]"
                            f"[/color]"
                        )
                    ),
                    markup=bool(line2),
                    font_size=title_font,
                    size_hint_x=1,
                    size_hint_min_x=dp(120),
                    halign="left",
                    valign="middle",
                )

                def _sync_feat_label_textsize(instance, *_):
                    w = instance.width
                    instance.text_size = (max(w, 1), None)

                lbl.bind(width=_sync_feat_label_textsize)
                lbl.bind(on_touch_down=partial(self._on_feature_row_label_touch, feat.id))

                row.add_widget(cb_col)
                row.add_widget(lbl)
                row.add_widget(
                    Button(
                        text=tr._("Rename"),
                        size_hint_x=None,
                        width=dp(78),
                        on_release=partial(self._on_rename_feature, feat.id),
                    )
                )
                row.add_widget(
                    Button(
                        text=tr._("Delete"),
                        size_hint_x=None,
                        width=dp(78),
                        on_release=partial(self._on_delete_feature, feat.id),
                    )
                )
                Clock.schedule_once(lambda dt, lw=lbl: _sync_feat_label_textsize(lw), 0)
                fl.add_widget(row)
            self.ids.sketch.set_features(
                self.session.features,
                focus_id=self._preview_focus_id,
                selection_ids=list(self._selection_order),
            )
            empty = len(self.session.features) == 0
            ph = self.ids.lbl_sketch_placeholder
            ph.opacity = 1.0 if empty else 0.0
            ph.height = ph.texture_size[1] if empty else 0 # Collapse height if empty to avoid touch interferences
        except Exception as e:
            logger.debug("refresh feature ui: %s", e)

    def _on_row_checkbox(self, fid: str, _widget, active: bool):
        if active:
            if fid not in self._selection_order:
                self._selection_order.append(fid)
        else:
            self._selection_order[:] = [
                x for x in self._selection_order if x != fid
            ]
        self._recompute_construct_buttons()
        try:
            self.ids.sketch.set_features(
                self.session.features,
                focus_id=self._preview_focus_id,
                selection_ids=list(self._selection_order),
            )
        except Exception:
            logger.debug("sketch sync after checkbox", exc_info=True)

    def on_clear_construct_selection(self):
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_segment(self):
        ids = list(self._selection_order)
        if len(ids) != 2:
            self._toast(tr._("Select exactly two point features."))
            return
        by_id = index_by_id(self.session.features)
        a = by_id.get(ids[0])
        b = by_id.get(ids[1])
        if not a or not b:
            self._toast(tr._("Missing features for segment."))
            return
        if not self._kind_has_vertex_xy(a) or not self._kind_has_vertex_xy(b):
            self._toast(tr._("Segments need point-like features (corner, circle center, probe point…)."))
            return
        if resolve_xy(a) is None or resolve_xy(b) is None:
            self._toast(tr._("Could not resolve XY for selected features."))
            return
        self.session.features.append(
            ProbeScanFeature.new_segment(tr._("Segment"), ids[0], ids[1])
        )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_polyline(self, closed: bool):
        ids = list(self._selection_order)
        min_n = 3 if closed else 2
        if len(ids) < min_n:
            self._toast(
                tr._("Select at least %(n)d vertices in checkbox order.") % {"n": min_n},
            )
            return
        by_id = index_by_id(self.session.features)
        for fid in ids:
            f = by_id.get(fid)
            if (
                not f
                or not self._kind_has_vertex_xy(f)
                or resolve_xy(f) is None
            ):
                self._toast(
                    tr._("Polyline needs point-like features only (wrong selection)."),
                )
                return
        self.session.features.append(
            ProbeScanFeature.new_polyline(
                tr._("Closed polyline") if closed else tr._("Open polyline"),
                ids,
                closed=closed,
            )
        )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_polyline_open(self):
        self.on_construct_polyline(False)

    def on_construct_polyline_closed(self):
        self.on_construct_polyline(True)

    def on_construct_derived_circle(self):
        ids = list(self._selection_order)
        if len(ids) != 3:
            self._toast(tr._("Select exactly three point features."))
            return
        by_id = index_by_id(self.session.features)
        pts_xy: list[tuple[float, float]] = []
        for fid in ids:
            f = by_id.get(fid)
            xy = resolve_xy(f)
            if xy is None:
                self._toast(tr._("Circumcircle needs three resolvable XY points."))
                return
            pts_xy.append(xy)
        try:
            (ax, ay), (bx, by), (cx, cy) = pts_xy
            ucx, ucy, r = circumcircle_2d(ax, ay, bx, by, cx, cy)
        except ValueError as e:
            if str(e) == "colinear_points":
                self._toast(tr._("Points are colinear, cannot form a circle."))
            else:
                self._toast(str(e))
            return
        self.session.features.append(
            ProbeScanFeature.new_derived_circle(
                tr._("Circumcircle"),
                (ids[0], ids[1], ids[2]),
                ucx,
                ucy,
                r,
            )
        )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_intersection(self):
        ids = list(self._selection_order)
        if len(ids) != 2:
            self._toast(tr._("Select exactly two features."))
            return
        by_id = index_by_id(self.session.features)
        f1, f2 = by_id.get(ids[0]), by_id.get(ids[1])
        if not f1 or not f2:
            self._toast(tr._("Missing features for intersection."))
            return

        def _is_seg(f):
            return f.kind == FeatureKind.SEGMENT

        def _is_circ(f):
            return f.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE)

        new_pts: list[tuple[float, float]] = []

        if _is_seg(f1) and _is_seg(f2):
            # Line × Line → 0 or 1 point
            e1 = segment_endpoints(by_id, f1)
            e2 = segment_endpoints(by_id, f2)
            if not e1 or not e2:
                self._toast(tr._("Segment endpoints could not be resolved."))
                return
            (x1, y1), (x2, y2) = e1
            (x3, y3), (x4, y4) = e2
            hit = line_intersection_2d(x1, y1, x2, y2, x3, y3, x4, y4)
            if hit is None:
                self._toast(tr._("Lines are parallel, no intersection point."))
                return
            new_pts = [hit]

        elif (_is_circ(f1) and _is_seg(f2)) or (_is_seg(f1) and _is_circ(f2)):
            # Circle × Line → 0, 1, or 2 points
            fc, fl = (f1, f2) if _is_circ(f1) else (f2, f1)
            circ = resolve_circle(fc)
            ends = segment_endpoints(by_id, fl)
            if circ is None or ends is None:
                self._toast(tr._("Could not resolve circle/segment geometry."))
                return
            cx_, cy_, r = circ
            (ax, ay), (bx, by_) = ends
            new_pts = circle_line_intersections_2d(cx_, cy_, r, ax, ay, bx, by_)
            if not new_pts:
                self._toast(tr._("Circle and line do not intersect."))
                return

        elif _is_circ(f1) and _is_circ(f2):
            # Circle × Circle → 0, 1, or 2 points
            c1 = resolve_circle(f1)
            c2 = resolve_circle(f2)
            if c1 is None or c2 is None:
                self._toast(tr._("Could not resolve circle geometry."))
                return
            new_pts = circle_circle_intersections_2d(*c1, *c2)
            if not new_pts:
                self._toast(tr._("Circles do not intersect."))
                return
        else:
            self._toast(tr._("Select two segments, two circles, or a circle and a segment."))
            return

        label_base = tr._("Intersection")
        for i, (ix, iy) in enumerate(new_pts):
            label = f"{label_base} {i + 1}" if len(new_pts) > 1 else label_base
            self.session.features.append(
                ProbeScanFeature.new_derived_point(label, f1.id, f2.id, ix, iy)
            )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_midpoint(self):
        ids = list(self._selection_order)
        if len(ids) != 2:
            self._toast(tr._("Select exactly two point features."))
            return
        by_id = index_by_id(self.session.features)
        fa, fb = by_id.get(ids[0]), by_id.get(ids[1])
        if not fa or not fb:
            self._toast(tr._("Missing features for midpoint."))
            return
        pa, pb = resolve_xy(fa), resolve_xy(fb)
        if pa is None or pb is None:
            self._toast(tr._("Could not resolve XY for selected features."))
            return
        mx, my = midpoint_2d(pa[0], pa[1], pb[0], pb[1])
        self.session.features.append(
            ProbeScanFeature.new_derived_point(tr._("Midpoint"), fa.id, fb.id, mx, my)
        )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def on_construct_tangent(self):
        ids = list(self._selection_order)
        if len(ids) != 2:
            self._toast(tr._("Select a point + circle, or two circles."))
            return
        by_id = index_by_id(self.session.features)
        f1, f2 = by_id.get(ids[0]), by_id.get(ids[1])
        if not f1 or not f2:
            self._toast(tr._("Missing features for tangent."))
            return

        def _is_circ(f):
            return f.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE)

        def _is_pt(f):
            return self._kind_has_vertex_xy(f) and resolve_xy(f) is not None

        if _is_pt(f1) and _is_circ(f2):
            pt_feat, circ_feat = f1, f2
        elif _is_circ(f1) and _is_pt(f2):
            pt_feat, circ_feat = f2, f1
        elif _is_circ(f1) and _is_circ(f2):
            pt_feat, circ_feat = None, None
        else:
            self._toast(tr._("Select a point + circle, or two circles."))
            return

        if pt_feat is not None:
            # Point → Circle tangents: produce 2 touch-point derived-points.
            pxy = resolve_xy(pt_feat)
            circ = resolve_circle(circ_feat)
            if pxy is None or circ is None:
                self._toast(tr._("Could not resolve geometry."))
                return
            touch_pts = tangent_point_to_circle_2d(pxy[0], pxy[1], circ[0], circ[1], circ[2])
            if not touch_pts:
                self._toast(tr._("Point is inside the circle — no tangent exists."))
                return
            for i, (tx, ty) in enumerate(touch_pts):
                label = tr._("Tangent point %(n)d") % {"n": i + 1}
                self.session.features.append(
                    ProbeScanFeature.new_derived_point(
                        label, pt_feat.id, circ_feat.id, tx, ty
                    )
                )
        else:
            # Circle → Circle external tangents: produce pairs of touch-points + segments.
            c1 = resolve_circle(f1)
            c2 = resolve_circle(f2)
            if c1 is None or c2 is None:
                self._toast(tr._("Could not resolve circle geometry."))
                return
            tangent_lines = tangent_circle_to_circle_external_2d(*c1, *c2)
            if not tangent_lines:
                self._toast(tr._("Circles are concentric — no external tangent exists."))
                return
            for i, (tp1, tp2) in enumerate(tangent_lines):
                lbl1 = tr._("Tangent %(n)d·A") % {"n": i + 1}
                lbl2 = tr._("Tangent %(n)d·B") % {"n": i + 1}
                dp1 = ProbeScanFeature.new_derived_point(lbl1, f1.id, f2.id, tp1[0], tp1[1])
                dp2 = ProbeScanFeature.new_derived_point(lbl2, f1.id, f2.id, tp2[0], tp2[1])
                self.session.features.append(dp1)
                self.session.features.append(dp2)
                self.session.features.append(
                    ProbeScanFeature.new_segment(
                        tr._("Tangent %(n)d") % {"n": i + 1}, dp1.id, dp2.id
                    )
                )
        self._selection_order.clear()
        self._refresh_feature_ui()

    def _on_delete_feature(self, fid: str, *args):
        blockers = features_referencing_id(self.session.features, fid)
        if blockers:
            preview = ", ".join(blockers[:5])
            suffix = "…" if len(blockers) > 5 else ""
            self._toast(
                tr._("Cannot delete: referenced by constructed features.")
                + "\n"
                + preview
                + suffix
            )
            return
        self.session.features[:] = [f for f in self.session.features if f.id != fid]
        self._selection_order[:] = [x for x in self._selection_order if x != fid]
        self._refresh_feature_ui()

    def _on_rename_feature(self, fid: str, *_args):
        feat = next((f for f in self.session.features if f.id == fid), None)
        if feat is None:
            return
        root_v = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        ti = TextInput(
            text=feat.label,
            multiline=False,
            size_hint_y=None,
            height=dp(40),
        )
        btns = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        popup = Popup(
            title=tr._("Rename feature"),
            content=root_v,
            size_hint=(0.88, None),
            height=dp(196),
            auto_dismiss=False,
        )

        def on_ok(*_):
            name = ti.text.strip()
            if not name:
                self._toast(tr._("Enter a name."))
                return
            feat.label = name
            popup.dismiss()
            self._refresh_feature_ui()

        def on_cancel(*_):
            popup.dismiss()

        ok_btn = Button(text=tr._("OK"))
        ok_btn.bind(on_release=on_ok)
        cancel_btn = Button(text=tr._("Cancel"))
        cancel_btn.bind(on_release=on_cancel)
        ti.bind(on_text_validate=lambda *_a: on_ok())

        btns.add_widget(cancel_btn)
        btns.add_widget(ok_btn)
        root_v.add_widget(ti)
        root_v.add_widget(btns)
        popup.open()
        Clock.schedule_once(lambda _dt: ti.select_all(), 0.1)

    def on_add_current_position(self):
        parsed = self._parse_manual_wcs_xyz_from_fields()
        if parsed is None:
            return
        wx, wy, wz = parsed
        f = ProbeScanFeature.new_point(
            tr._("Stored position"),
            wx,
            wy,
            wz,
            source="Manual",
            coord_sys=CoordSys.WCS,
        )
        self.session.features.append(f)
        self._refresh_feature_ui()

    def on_add_manual_circle(self):
        parsed = self._parse_manual_wcs_xyz_from_fields()
        if parsed is None:
            return
        wx, wy, _wz = parsed
        rt = self.ids.t_manual_radius.text.strip().replace(",", ".")
        if not rt:
            self._toast(tr._("Enter radius."))
            return
        try:
            r = float(rt)
        except ValueError:
            self._toast(tr._("Invalid radius."))
            return
        if r <= 0:
            self._toast(tr._("Radius must be greater than zero."))
            return
        d = 2.0 * r
        f = ProbeScanFeature.new_circle(
            tr._("Manual circle"),
            wx,
            wy,
            d,
            d,
            coord_sys=CoordSys.WCS,
        )
        self.session.features.append(f)
        self._refresh_feature_ui()

    def on_probe_side_hint(self, side: str):
        self._m466_side = side

    def on_bore_preset(self, key: str):
        self._m461_preset = key

    def on_boss_preset(self, key: str):
        self._m462_preset = key

    def on_inside_corner_quick(self, quadrant: str):
        self._m463_quadrant = quadrant

    def on_outside_corner_quick(self, quadrant: str):
        self._m464_quadrant = quadrant

    def on_angle_axis_hint(self, which: str):
        self._angle_variant = which

    def _read_common_probe_opts(self, prefix: str) -> dict:
        return dict(
            h=_parse_optional_float_text(self.ids[f"t{prefix}_h"]) or "",
            c=_parse_optional_float_text(self.ids[f"t{prefix}_c"]) or "",
            f_probe=_parse_float_field(self.ids[f"t{prefix}_f"], 300.0),
            k_rapid=_parse_float_field(self.ids[f"t{prefix}_k"], 800.0),
            l_repeat=_parse_optional_float_text(self.ids[f"t{prefix}_l"]) or "",
            r_retract=_parse_optional_float_text(self.ids[f"t{prefix}_r"]) or "",
        )

    def on_probe_axis466(self):
        try:
            if not self._m466_side:
                self._toast_need_probing_option()
                return
            xs = self.ids.t466_x.text.strip()
            ys = self.ids.t466_y.text.strip()
            zs = self.ids.t466_z.text.strip()
            side = self._m466_side
            x_cmd, y_cmd = xs, ys
            if side in ("Left", "Right"):
                y_cmd = ""
                if not xs and not zs:
                    self._toast(tr._("Enter X (and/or Z) for this probe direction."))
                    return
                if xs:
                    x_cmd = _distance_for_command(xs, negate=(side == "Right"))
            elif side in ("Bottom", "Top"):
                x_cmd = ""
                if not ys and not zs:
                    self._toast(tr._("Enter Y (and/or Z) for this probe direction."))
                    return
                if ys:
                    y_cmd = _distance_for_command(ys, negate=(side == "Top"))
            else:
                self._toast_need_probing_option()
                return
            opts = self._read_common_probe_opts("466")
            e_o = _parse_optional_float_text(self.ids.t466_e)
            self._run_gcode_program(
                build_m466(x=x_cmd, y=y_cmd, z=zs, e=e_o or "", **opts)
            )
        except Exception as e:
            self._toast(str(e))

    def on_bore461(self):
        try:
            if not self._m461_preset:
                self._toast_need_probing_option()
                return
            xs = self.ids.t461_x.text.strip().replace(",", ".")
            ys = self.ids.t461_y.text.strip().replace(",", ".")
            preset = self._m461_preset
            x_cmd, y_cmd = xs, ys
            if preset == "CenterX":
                y_cmd = ""
                if not xs:
                    self._toast(tr._("Enter X travel for M461 (Center X)."))
                    return
            elif preset == "CenterY":
                x_cmd = ""
                if not ys:
                    self._toast(tr._("Enter Y travel for M461 (Center Y)."))
                    return
            elif preset in ("CenterBore", "CenterPocket"):
                if not xs or not ys:
                    self._toast(tr._("Enter both X and Y travel for this bore pattern."))
                    return
            else:
                self._toast_need_probing_option()
                return
            if x_cmd:
                float(x_cmd)
            if y_cmd:
                float(y_cmd)
            opts = self._read_common_probe_opts("461")
            e_o = _parse_optional_float_text(self.ids.t461_e)
            self._run_gcode_program(
                build_m461(x=x_cmd, y=y_cmd, e=e_o or "", **opts)
            )
        except Exception as e:
            self._toast(str(e))

    def on_boss462(self):
        try:
            if not self._m462_preset:
                self._toast_need_probing_option()
                return
            xs = self.ids.t462_x.text.strip().replace(",", ".")
            ys = self.ids.t462_y.text.strip().replace(",", ".")
            preset = self._m462_preset
            x_cmd, y_cmd = xs, ys
            if preset == "CenterX":
                y_cmd = ""
                if not xs:
                    self._toast(tr._("Enter X travel for M462 (Center X)."))
                    return
            elif preset == "CenterY":
                x_cmd = ""
                if not ys:
                    self._toast(tr._("Enter Y travel for M462 (Center Y)."))
                    return
            elif preset in ("CenterBoss", "CenterBlock"):
                if not xs or not ys:
                    self._toast(tr._("Enter both X and Y travel for this boss pattern."))
                    return
            else:
                self._toast_need_probing_option()
                return
            if x_cmd:
                float(x_cmd)
            if y_cmd:
                float(y_cmd)
            opts = self._read_common_probe_opts("462")
            e_o = _parse_optional_float_text(self.ids.t462_e)
            j_o = _parse_optional_float_text(self.ids.t462_j)
            self._run_gcode_program(
                build_m462(
                    x=x_cmd, y=y_cmd,
                    e_depth=e_o or "", j_clearance=j_o or "",
                    **opts,
                )
            )
        except Exception as e:
            self._toast(str(e))

    def on_in463(self):
        try:
            if not self._m463_quadrant:
                self._toast_need_probing_option()
                return
            mx = _parse_float_field(self.ids.t463_x, 10.0)
            my = _parse_float_field(self.ids.t463_y, 10.0)
            x, y = _corner_deltas_from_quadrant(self._m463_quadrant, mx, my)
            opts = self._read_common_probe_opts("463")
            e_o = _parse_optional_float_text(self.ids.t463_e)
            self._run_gcode_program(
                build_m463(x, y, e=e_o or "", **opts)
            )
        except Exception as e:
            self._toast(str(e))

    def on_out464(self):
        try:
            if not self._m464_quadrant:
                self._toast_need_probing_option()
                return
            mx = _parse_float_field(self.ids.t464_x, 10.0)
            my = _parse_float_field(self.ids.t464_y, 10.0)
            x, y = _corner_deltas_from_quadrant(self._m464_quadrant, mx, my)
            opts = self._read_common_probe_opts("464")
            e_o = _parse_optional_float_text(self.ids.t464_e)
            self._run_gcode_program(
                build_m464(x, y, e=e_o or "", **opts)
            )
        except Exception as e:
            self._toast(str(e))

    def on_angle465(self):
        try:
            if not self._angle_variant:
                self._toast_need_probing_option()
                return
            xs = self.ids.t465_x.text.strip()
            ys = self.ids.t465_y.text.strip()
            v = self._angle_variant
            if v in ("above", "below"):
                if not xs:
                    self._toast(tr._("Enter X distance for M465."))
                    return
                xs_cmd = _signed_distance_for_command(xs)
                ys_cmd = ""
            elif v in ("left", "right"):
                if not ys:
                    self._toast(tr._("Enter Y distance for M465."))
                    return
                xs_cmd = ""
                ys_cmd = _signed_distance_for_command(ys)
            else:
                self._toast_need_probing_option()
                return
            e_o = _parse_optional_float_text(self.ids.t465_e)
            e_cmd = _signed_distance_for_command(e_o) if e_o is not None else ""
            opts = self._read_common_probe_opts("465")
            self._run_gcode_program(
                build_m465(x=xs_cmd, y=ys_cmd, e=e_cmd, **opts)
            )
        except Exception as e:
            self._toast(str(e))

    def on_export_json(self):
        try:
            from kivy.core.clipboard import Clipboard

            Clipboard.copy(export_json(self.session))
            self._toast(tr._("JSON copied to clipboard."))
        except Exception as e:
            self._toast(str(e))

    def on_export_csv(self):
        try:
            from kivy.core.clipboard import Clipboard

            Clipboard.copy(export_csv(self.session))
            self._toast(tr._("CSV copied to clipboard."))
        except Exception as e:
            self._toast(str(e))

    def on_export_dxf(self):
        try:
            from kivy.core.clipboard import Clipboard

            Clipboard.copy(export_dxf(self.session))
            self._toast(tr._("DXF copied to clipboard."))
        except Exception as e:
            self._toast(str(e))

    def open_save_format_dropdown(self, anchor_widget):
        self._open_export_format_dropdown(anchor_widget, self._prompt_save_export_file)

    def open_copy_format_dropdown(self, anchor_widget):
        def _dispatch(fmt: str):
            if fmt == "JSON":
                self.on_export_json()
            elif fmt == "CSV":
                self.on_export_csv()
            else:
                self.on_export_dxf()

        self._open_export_format_dropdown(anchor_widget, _dispatch)

    def _open_export_format_dropdown(self, anchor_widget, on_pick):
        dd = DropDown()
        dd.auto_width = False
        dd.width = max(int(anchor_widget.width), int(dp(160)))
        dd.max_height = dp(240)

        for kind in ("JSON", "CSV", "DXF"):

            def _choose(*_a, k=kind):
                dd.dismiss()
                Clock.schedule_once(lambda dt, kk=k: on_pick(kk), 0)

            btn = Button(
                text=tr._(kind),
                size_hint_y=None,
                height=dp(44),
                font_size=dp(14),
            )
            btn.bind(on_release=_choose)
            dd.add_widget(btn)

        dd.open(anchor_widget)

    def on_reset_session(self):
        root = App.get_running_app().root
        cp = root.confirm_popup
        cp.lb_title.text = tr._("Reset probe scan?")
        cp.lb_content.text = tr._(
            "Clear all features from the current session?\nYou will lose unsaved work."
        )

        def on_confirm():
            self.session.features.clear()
            self._selection_order.clear()
            self._preview_focus_id = None
            self._refresh_feature_ui()
            self._toast(tr._("Probe scan cleared."))

        cp.confirm = on_confirm
        cp.cancel = None
        cp.open(root)

    def on_load_session(self):
        self._prompt_load_session_file()

    def _home_dir_fc(self) -> str:
        try:
            h = os.path.expanduser("~")
            return h if os.path.isdir(h) else os.getcwd()
        except Exception:
            return "/"

    def _overwrite_then(self, dest: str, write_fn):
        root = App.get_running_app().root
        if os.path.isfile(dest):
            cp = root.confirm_popup
            cp.lb_title.text = tr._("Overwrite file?")
            cp.lb_content.text = tr._("Replace existing file?\n%s") % dest
            cp.confirm = lambda: write_fn(dest)
            cp.cancel = None
            cp.open(root)
        else:
            write_fn(dest)

    def _open_file_dialog(self, *, title, default_name, size_hint, on_confirm, btn_text=None):
        root = App.get_running_app().root
        try:
            content = Factory.ProbeScanFileSheet()
        except KeyError:
            self._toast(tr._("Dialog unavailable (UI not loaded)."))
            return
        fc = content.ids.fc
        ti = content.ids.ti_filename
        fc.path = self._home_dir_fc()
        ti.text = default_name

        def sync_filename_from_selection(_inst, sel):
            if not sel:
                return
            path = sel[0]
            try:
                if os.path.isfile(path):
                    ti.text = os.path.basename(path)
            except OSError:
                pass

        fc.bind(selection=sync_filename_from_selection)
        popup = Popup(title=title, content=content, size_hint=size_hint, auto_dismiss=False)
        if btn_text:
            content.ids.btn_save.text = btn_text

        def attempt(*_):
            raw_name = ti.text.strip()
            if not raw_name:
                root.show_message_popup(tr._("Enter a file name."), False)
                return
            fn = os.path.basename(raw_name)
            dd = fc.path
            if not dd or not os.path.isdir(dd):
                root.show_message_popup(tr._("Choose an existing folder."), False)
                return
            on_confirm(popup, os.path.join(dd, fn))

        content.ids.btn_cancel.bind(on_release=lambda *_: popup.dismiss())
        content.ids.btn_save.bind(on_release=attempt)
        popup.open()

    def _prompt_load_session_file(self):
        root = App.get_running_app().root

        def on_confirm(popup, dest):
            try:
                with open(dest, encoding="utf-8") as fp:
                    self.session = ProbeScanSession.loads(fp.read())
                self._selection_order.clear()
                self._preview_focus_id = None
                self._refresh_feature_ui()
                popup.dismiss()
                self._toast(tr._("Loaded:\n%s") % dest)
            except OSError as e:
                root.show_message_popup(tr._("Could not read:\n%s") % e, False)
            except Exception as e:
                root.show_message_popup(tr._("Invalid session file:\n%s") % e, False)

        self._open_file_dialog(
            title=tr._("Load session"),
            default_name="probe_scan_export.json",
            size_hint=(0.82, 0.82),
            on_confirm=on_confirm,
            btn_text=tr._("Load"),
        )

    def _prompt_save_export_file(self, export_kind: str = "JSON"):
        root = App.get_running_app().root
        kind = export_kind.strip().upper() if isinstance(export_kind, str) else "JSON"
        if kind not in ("JSON", "CSV", "DXF"):
            kind = "JSON"
        stems = {
            "JSON": "probe_scan_export.json",
            "CSV": "probe_scan_export.csv",
            "DXF": "probe_scan_export.dxf",
        }

        def on_confirm(popup, dest):
            def write(path: str):
                try:
                    if kind == "JSON":
                        blob = export_json(self.session)
                    elif kind == "CSV":
                        blob = export_csv(self.session)
                    else:
                        blob = export_dxf(self.session)
                    with open(path, "w", encoding="utf-8") as fp:
                        fp.write(blob)
                    popup.dismiss()
                    self._toast(tr._("Saved:\n%s") % path)
                except OSError as e:
                    root.show_message_popup(tr._("Could not save:\n%s") % e, False)

            self._overwrite_then(dest, write)

        self._open_file_dialog(
            title=tr._("Save export (%s)") % kind,
            default_name=stems[kind],
            size_hint=(0.82, 0.85),
            on_confirm=on_confirm,
        )
