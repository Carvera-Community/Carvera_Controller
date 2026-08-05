from __future__ import annotations

import logging
import os
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.factory import Factory
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

from carveracontroller.addons.probing.operations.ConfigUtils import get_machine_config_hint
from carveracontroller.CNC import CNC
from carveracontroller.Controller import NOT_CONNECTED, Controller
from carveracontroller.main import is_ios
from carveracontroller.serial_listeners import (
    register_serial_listener,
    unregister_serial_listener,
)
from carveracontroller.translation import tr
from carveracontroller.ui.LocalFilePicker import (
    confirm_overwrite_then,
    open_local_file_picker,
)

from ..core.features import (
    DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM,
    ConstructButtonStates,
    compute_construct_button_states,
    construct_circumcircle,
    construct_intersection,
    construct_midpoint,
    construct_polyline,
    construct_segment,
    construct_tangent,
    features_from_m461_m462,
    features_referencing_id,
    index_by_id,
    mcs_xyz_to_wcs_xyz,
)
from ..core.gcode import (
    PROBE_VAR_ANGLE,
    PROBE_VAR_CENTER_X,
    PROBE_VAR_CENTER_Y,
    PROBE_VAR_CENTER_Z,
    M118ProbeCapture,
    ProbeProgram,
    build_m461,
    build_m462,
    build_m463,
    build_m464,
    build_m465,
    build_m466,
    extract_probe_start_meta,
)
from ..core.io_export import export_csv, export_dxf, export_json
from ..core.session import CMMWorkbenchFeature, CMMWorkbenchSession, FeatureKind
from .display import feature_secondary_line, fmt_wcs_manual_field
from .probe_runner import ProbeRunner
from .sketch import CMMWorkbenchPreviewSketch

if "CMMWorkbenchPreviewSketch" not in Factory.classes:
    Factory.register("CMMWorkbenchPreviewSketch", cls=CMMWorkbenchPreviewSketch)

# Feature list row highlight (canvas.before Color on each row BoxLayout).
_FEATURE_ROW_FOCUS_RGBA_ON = (0.18, 0.38, 0.58, 0.22)
_FEATURE_ROW_FOCUS_RGBA_OFF = (0.18, 0.38, 0.58, 0.0)
_HIDDEN_FEATURE_LABEL_COLOR = "5a5a5f"

_SESSION_FILE_FILTERS = {
    "JSON": ["*.json"],
    "CSV": ["*.csv"],
    "DXF": ["*.dxf"],
}


class CMMWorkbenchIconToggle(ToggleButton):
    image = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)


class CMMWorkbenchSketchVisibilityToggle(CMMWorkbenchIconToggle):
    """Per-row sketch visibility toggle — not in a shared ToggleButton group."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.group = None


if "CMMWorkbenchIconToggle" not in Factory.classes:
    Factory.register("CMMWorkbenchIconToggle", cls=CMMWorkbenchIconToggle)

if "CMMWorkbenchSketchVisibilityToggle" not in Factory.classes:
    Factory.register("CMMWorkbenchSketchVisibilityToggle", cls=CMMWorkbenchSketchVisibilityToggle)


class JogCMMWorkbenchPopup(ModalView):
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


if "JogCMMWorkbenchPopup" not in Factory.classes:
    Factory.register("JogCMMWorkbenchPopup", cls=JogCMMWorkbenchPopup)

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


class CMMWorkbenchPopup(ModalView):
    controller: Controller
    _listener_handle: int | None = None
    _capture: M118ProbeCapture | None = None

    is_probing = BooleanProperty(False)
    probing_status_text = StringProperty("")
    can_use_local_file_picker = BooleanProperty(not is_ios())

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
        self.session = CMMWorkbenchSession()
        self._selection_order: list[str] = []
        self._preview_focus_id: str | None = None
        self._angle_variant: str | None = None
        self._m466_side: str | None = None
        self._m461_preset: str | None = None
        self._m462_preset: str | None = None
        self._m463_quadrant: str | None = None
        self._m464_quadrant: str | None = None
        self._jog_popup = None
        self._keyboard_jog_while_jog_modal_open = False
        super().__init__(**kwargs)
        self._runner = ProbeRunner(
            set_is_probing=lambda v: setattr(self, "is_probing", v),
            set_status_text=lambda v: setattr(self, "probing_status_text", v),
            on_is_probing_changed=self._on_probe_is_probing_changed,
            controller_abort=self.controller.abortCommand,
            get_state=self._machine_state,
            execute_line=self._execute_line,
            on_aborted=self._on_probe_aborted,
        )

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        try:
            self.ids.sketch.on_feature_tap = self._on_sketch_feature_tap
        except Exception:
            logger.debug("Could not bind sketch tap handler", exc_info=True)

    def _on_sketch_feature_tap(self, feat_id: str) -> None:
        """Called by CMMWorkbenchPreviewSketch when the user taps a feature."""
        feat = next((f for f in self.session.features if f.id == feat_id), None)
        if feat is None or not feat.sketch_visible:
            return
        if self._preview_focus_id == feat_id:
            self._preview_focus_id = None
        else:
            self._preview_focus_id = feat_id
        self._recompute_construct_buttons()
        self._sync_sketch_preview()
        self._apply_feature_row_focus_visual()
        Clock.schedule_once(lambda _dt: self._scroll_to_feature(feat_id), 0.05)

    def _scroll_to_feature(self, feat_id: str) -> None:
        """Scroll the feature list so the row for feat_id is visible."""
        try:
            sv = self.ids.feature_rows_scroll
            grid = self.ids.feature_rows
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
            children = list(reversed(grid.children))
            if idx >= len(children):
                return
            child = children[idx]
            child_bot = child.y
            scroll_range = grid_h - sv_h
            target_bottom = child_bot - (sv_h - child.height) / 2.0
            target_sy = max(0.0, min(1.0, target_bottom / scroll_range))
            sv.scroll_y = target_sy
        except Exception:
            logger.debug("Could not scroll feature list", exc_info=True)

    def _effective_construct_selection(self) -> list[str]:
        """Checkbox selection, or the highlighted feature when no box is checked."""
        visible = {f.id for f in self.session.features if f.sketch_visible}
        if self._selection_order:
            return [x for x in self._selection_order if x in visible]
        if self._preview_focus_id and self._preview_focus_id in visible:
            return [self._preview_focus_id]
        return []

    @staticmethod
    def _feature_row_label_text(line1: str, line2: str, *, visible: bool, detail_font: float) -> tuple[str, bool]:
        title = line1 if visible else f"[color={_HIDDEN_FEATURE_LABEL_COLOR}]{line1}[/color]"
        if not line2:
            return title, not visible
        detail_color = "78797f" if visible else _HIDDEN_FEATURE_LABEL_COLOR
        text = f"{title}\n[color={detail_color}][size={int(round(detail_font))}]{line2}[/size][/color]"
        return text, True

    def _sketch_hidden_ids(self) -> set[str]:
        return {f.id for f in self.session.features if not f.sketch_visible}

    def _sync_sketch_preview(self) -> None:
        """Push session/focus/selection into the XY preview sketch."""
        try:
            self.ids.sketch.set_features(
                self.session.features,
                focus_id=self._preview_focus_id,
                selection_ids=self._effective_construct_selection(),
                hidden_ids=self._sketch_hidden_ids(),
            )
        except Exception:
            logger.debug("Could not update sketch preview", exc_info=True)

    def _apply_feature_row_focus_visual(self) -> None:
        """Toggle row highlight without rebuilding the feature list."""
        fid_focus = self._preview_focus_id
        try:
            for row in self.ids.feature_rows.children:
                fc = getattr(row, "_probe_focus_color", None)
                fid = getattr(row, "_probe_feat_id", None)
                if fc is None or fid is None:
                    continue
                feat = next((f for f in self.session.features if f.id == fid), None)
                fc.rgba = (
                    _FEATURE_ROW_FOCUS_RGBA_ON
                    if feat is not None and feat.sketch_visible and fid == fid_focus
                    else _FEATURE_ROW_FOCUS_RGBA_OFF
                )
        except Exception:
            logger.debug("Could not toggle row focus", exc_info=True)

    def is_jog_overlay_open(self) -> bool:
        jog = self._jog_popup
        return jog is not None and jog._is_open

    def allows_external_jog(self) -> bool:
        """Allow keyboard/pendant jog via the probe-scan jog overlay."""
        return self._is_open and self.is_jog_overlay_open() and not self.is_probing

    def open_jog_popup(self, *_args):
        if not self._guard_session_mutation():
            return
        jog = self._jog_popup
        if jog is None:
            jog = Factory.JogCMMWorkbenchPopup()
            jog.bind(on_open=self._on_jog_modal_open)
            jog.bind(on_dismiss=self._on_jog_modal_dismiss)
            self._jog_popup = jog
        jog.open()

    def _on_jog_modal_open(self, *_args):
        Clock.schedule_once(self._restore_keyboard_jog_if_wanted_for_jog_modal, 0)

    def _restore_keyboard_jog_if_wanted_for_jog_modal(self, _dt=None):
        root = App.get_running_app().root
        if self._keyboard_jog_while_jog_modal_open and not root.keyboard_jog_control:
            root.toggle_keyboard_jog_control()

    def _on_jog_modal_dismiss(self, *_args):
        root = App.get_running_app().root
        self._keyboard_jog_while_jog_modal_open = bool(root.keyboard_jog_control)
        root.toggle_keyboard_jog_control(True)

    def _dismiss_jog_popup(self):
        if self._jog_popup is not None:
            self._jog_popup.dismiss()

    def on_open(self):
        self._capture = M118ProbeCapture(
            self._on_probe_values,
            on_abort=self._on_probe_abort,
        )
        self._listener_handle = register_serial_listener(self._on_serial_line)
        Clock.schedule_interval(self._tick_wcs_live, 0.35)
        Clock.schedule_once(lambda _dt: self._tick_wcs_live(), 0.05)
        Clock.schedule_once(lambda _dt: self._sync_manual_wcs_fields_from_machine(), 0.08)
        Clock.schedule_once(lambda _dt: self._refresh_feature_ui(), 0)
        Clock.schedule_once(lambda _dt: self._refresh_probe_tip_diameter_hints(), 0)

    def dismiss(self, *args, **kwargs):
        if self.is_probing:
            self._confirm_dismiss_while_probing()
            return
        super().dismiss(*args, **kwargs)

    def _confirm_dismiss_while_probing(self) -> None:
        root = App.get_running_app().root
        cp = root.confirm_popup
        cp.lb_title.text = tr._("Probing in progress")
        cp.lb_content.text = tr._("A probe operation is still running. Close anyway and discard any result?")

        def on_confirm(*_args):
            self._cancel_probe_run()
            super(CMMWorkbenchPopup, self).dismiss()

        cp.confirm = on_confirm
        cp.cancel = None
        cp.open(root)

    def on_dismiss(self):
        self._dismiss_jog_popup()
        if self._capture is not None:
            self._capture.reset()
        self._runner.shutdown()
        Clock.unschedule(self._tick_wcs_live)
        if self._listener_handle is not None:
            unregister_serial_listener(self._listener_handle)
            self._listener_handle = None
        self._capture = None
        App.get_running_app().root.restore_keyboard_jog_control()

    def _on_probe_is_probing_changed(self) -> None:
        """Called when ``is_probing`` toggles (not on status animation ticks)."""
        self._apply_probing_ui_lock()

    def _apply_probing_ui_lock(self) -> None:
        """Sync construct buttons and row disabled state without rebuilding the feature list."""
        self._recompute_construct_buttons()
        probing = self.is_probing
        try:
            for row in self.ids.feature_rows.children:
                for w in row.children:
                    if isinstance(w, BoxLayout):
                        for inner in w.children:
                            if isinstance(inner, CheckBox):
                                inner.disabled = probing
                    elif isinstance(w, Button):
                        w.disabled = probing
        except Exception:
            logger.debug("Could not apply probing lock to feature rows", exc_info=True)

    def _on_serial_line(self, msg_kind: int, line: str) -> None:
        # An error line means the machine gave up on the run; without this the UI
        # would stay locked until the timeout.
        if msg_kind == Controller.MSG_ERROR and self.is_probing:
            self._runner.abort(tr._("Probe stopped: machine reported an error."))
            return
        if self._capture is not None:
            self._capture.feed_line(msg_kind, line)

    def _on_probe_aborted(self, reason: str) -> None:
        if self._capture is not None:
            self._capture.reset()
        self._toast(reason)

    def _cancel_probe_run(self) -> None:
        if self._capture is not None:
            self._capture.reset()
        self._runner.cancel(abort_machine=True)

    def _tick_wcs_live(self, *_args):
        try:
            lbl = self.ids.lbl_wcs_live
            wx = float(CNC.vars.get("wx", 0.0))
            wy = float(CNC.vars.get("wy", 0.0))
            wz = float(CNC.vars.get("wz", 0.0))
            lbl.text = f"[b]{tr._('Current position')}[/b]\nX  {wx:+.4f}   Y  {wy:+.4f}   Z  {wz:+.4f}"
        except Exception:
            logger.debug("Could not refresh live position label", exc_info=True)

    def _sync_manual_wcs_fields_from_machine(self, *_args):
        try:
            wx = float(CNC.vars.get("wx", 0.0))
            wy = float(CNC.vars.get("wy", 0.0))
            wz = float(CNC.vars.get("wz", 0.0))
            self.ids.t_manual_wx.text = fmt_wcs_manual_field(wx)
            self.ids.t_manual_wy.text = fmt_wcs_manual_field(wy)
            self.ids.t_manual_wz.text = fmt_wcs_manual_field(wz)
        except Exception:
            logger.debug("Could not sync manual WCS fields", exc_info=True)

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

    def _guard_session_mutation(self) -> bool:
        if self.is_probing:
            self._toast(tr._("Wait for probing to finish."))
            return False
        return True

    def _toast_need_probing_option(self) -> None:
        self._toast(tr._("Select a probing option before running."))

    def _machine_state(self) -> str:
        app = App.get_running_app()
        if app is None:
            return NOT_CONNECTED
        return app.state or NOT_CONNECTED

    def _is_idle(self) -> bool:
        return self._machine_state() == "Idle"

    def _execute_line(self, line: str) -> None:
        self.controller.executeCommand(line + "\n")

    def _run_gcode_program(self, program: ProbeProgram):
        if self.is_probing:
            self._toast(tr._("Probe already in progress."))
            return
        if not self._is_idle():
            self._toast(tr._("Machine must be Idle to probe."))
            return
        if self._capture is not None:
            for ln in program.tail:
                meta = extract_probe_start_meta(ln)
                if meta:
                    op, keys = meta
                    self._capture.prime_upstream(op, keys)
                    break
        self._dismiss_jog_popup()
        self._runner.start(program)

    def _on_probe_values(self, op: str, values: dict[str, float], var_keys: list[str]):
        self._runner.pre_complete()
        saved_token = self._runner.get_active_token()

        def _ui(_dt):
            if not self._runner.is_token_valid(saved_token):
                return
            if self._append_probe_result(op, values, var_keys):
                self._runner.complete()
            else:
                self._runner.cancel()

        Clock.schedule_once(_ui, 0)

    def _on_probe_abort(self, op: str, values: dict[str, float], var_keys: list[str]) -> None:
        self._runner.pre_complete()
        saved_token = self._runner.get_active_token()

        def _ui(_dt):
            if not self._runner.is_token_valid(saved_token):
                return
            self._cancel_probe_run()
            if values:
                self._toast(
                    tr._("Probe ended with incomplete data ({got}/{exp}).").format(got=len(values), exp=len(var_keys))
                )
            else:
                self._toast(tr._("Probe failed or was cancelled."))

        Clock.schedule_once(_ui, 0)

    def _read_circle_classify_tolerance_mm(self, op: str) -> float | None:
        """Absolute mm tolerance for full bore/boss circle vs ellipse classification."""
        raw = ""
        try:
            field_id = "t462_circle_tol" if op == "M462" else "t461_circle_tol"
            raw = getattr(self.ids, field_id).text.strip().replace(",", ".")
        except Exception:
            logger.debug("Could not read circle classify tolerance", exc_info=True)
        if not raw:
            return DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM
        try:
            tol = float(raw)
        except ValueError:
            self._toast(tr._("Invalid circle tolerance."))
            return None
        if tol < 0:
            self._toast(tr._("Circle tolerance must be zero or positive."))
            return None
        return tol

    def _m461_m462_probe_labels(self, op: str, preset: str) -> dict[str, str] | None:
        """Labels for M461/M462 feature construction."""
        bore = op == "M461"
        labels = {
            "segment_label": "",
            "endpoint_a_label": "",
            "endpoint_b_label": "",
            "center_label": tr._("Center"),
            "h_segment_label": "",
            "h_endpoint_a_label": "",
            "h_endpoint_b_label": "",
            "v_segment_label": "",
            "v_endpoint_a_label": "",
            "v_endpoint_b_label": "",
            "curve_label": "",
        }

        if preset == "CenterX":
            seg = tr._("Bore X (M461)") if bore else tr._("Boss X (M462)")
        elif preset == "CenterY":
            seg = tr._("Bore Y (M461)") if bore else tr._("Boss Y (M462)")
        elif preset in ("CenterBore", "CenterBoss"):
            labels["curve_label"] = tr._("Bore center (M461)") if bore else tr._("Boss center (M462)")
            return labels
        elif preset == "CenterPocket":
            h_seg = tr._("Pocket X (M461)")
            v_seg = tr._("Pocket Y (M461)")
        elif preset == "CenterBlock":
            h_seg = tr._("Block X (M462)")
            v_seg = tr._("Block Y (M462)")
        else:
            return None

        if preset in ("CenterX", "CenterY"):
            labels["segment_label"] = seg
            labels["endpoint_a_label"] = f"{seg} · A"
            labels["endpoint_b_label"] = f"{seg} · B"
            return labels

        labels["h_segment_label"] = h_seg
        labels["h_endpoint_a_label"] = f"{h_seg} · A"
        labels["h_endpoint_b_label"] = f"{h_seg} · B"
        labels["v_segment_label"] = v_seg
        labels["v_endpoint_a_label"] = f"{v_seg} · A"
        labels["v_endpoint_b_label"] = f"{v_seg} · B"
        return labels

    def _append_probe_result(self, op: str, vd: dict[str, float], var_keys: list[str] | None = None) -> bool:
        """Apply probe values to the session. Returns True when a feature was added."""
        if op == "M466":
            mx = float(CNC.vars.get("mx", 0.0))
            my = float(CNC.vars.get("my", 0.0))
            mz = float(CNC.vars.get("mz", 0.0))
            x_m = vd.get(PROBE_VAR_CENTER_X, mx)
            y_m = vd.get(PROBE_VAR_CENTER_Y, my)
            z_m = vd.get(PROBE_VAR_CENTER_Z, mz)
            wx, wy, wz = mcs_xyz_to_wcs_xyz(x_m, y_m, z_m)
            f = CMMWorkbenchFeature.new_point(
                tr._("Touch probe (M466)"),
                wx,
                wy,
                wz,
                source="M466",
            )
            self.session.features.append(f)
            self._refresh_feature_ui()
            return True
        if op in ("M461", "M462"):
            preset = self._m461_preset if op == "M461" else self._m462_preset
            if not preset:
                self._toast_need_probing_option()
                return False
            labels = self._m461_m462_probe_labels(op, preset)
            if labels is None:
                self._toast_need_probing_option()
                return False
            mx = float(CNC.vars.get("mx", 0.0))
            my = float(CNC.vars.get("my", 0.0))
            feat_kwargs: dict[str, object] = {
                "preset": preset,
                "mx": mx,
                "my": my,
                "source": op,
                **labels,
            }
            if preset in ("CenterBore", "CenterBoss"):
                tol = self._read_circle_classify_tolerance_mm(op)
                if tol is None:
                    return False
                feat_kwargs["tolerance_mm"] = tol
            feats, err = features_from_m461_m462(
                vd,
                var_keys or [],
                **feat_kwargs,
            )
            if err is not None:
                self._toast(tr._(err))
                return False
            if not feats:
                return False
            self.session.features.extend(feats)
            self._refresh_feature_ui()
            return True
        if op in ("M463", "M464"):
            xm = float(vd.get(PROBE_VAR_CENTER_X, 0.0))
            ym = float(vd.get(PROBE_VAR_CENTER_Y, 0.0))
            wx, wy, _ = mcs_xyz_to_wcs_xyz(xm, ym, 0.0)
            f = CMMWorkbenchFeature.new_corner(
                tr._("Inside corner (M463)") if op == "M463" else tr._("Outside corner (M464)"),
                wx,
                wy,
            )
            self.session.features.append(f)
            self._refresh_feature_ui()
            return True
        if op == "M465":
            mx = float(CNC.vars.get("mx", 0.0))
            my = float(CNC.vars.get("my", 0.0))
            mz = float(CNC.vars.get("mz", 0.0))
            wx, wy, wz = mcs_xyz_to_wcs_xyz(mx, my, mz)
            f = CMMWorkbenchFeature.new_angle(
                tr._("Angle (M465)"),
                float(vd.get(PROBE_VAR_ANGLE, 0.0)),
                probe_variant=str(self._angle_variant or ""),
                x=wx,
                y=wy,
                z=wz,
            )
            self.session.features.append(f)
            self._refresh_feature_ui()
            return True
        return False

    def _sanitize_feature_ui_state(self):
        avail = {f.id for f in self.session.features}
        visible = {f.id for f in self.session.features if f.sketch_visible}
        if self._preview_focus_id is not None and self._preview_focus_id not in visible:
            self._preview_focus_id = None
        self._selection_order[:] = [x for x in self._selection_order if x in avail and x in visible]

    def _recompute_construct_buttons(self) -> None:
        states: ConstructButtonStates = compute_construct_button_states(
            self.session.features,
            self._effective_construct_selection(),
            self.is_probing,
        )
        self.has_construct_selection = states.has_selection
        self.can_make_segment = states.can_segment
        self.can_make_polyline_open = states.can_polyline_open
        self.can_make_polyline_closed = states.can_polyline_closed
        self.can_make_circumcircle = states.can_circumcircle
        self.can_make_intersection = states.can_intersection
        self.can_make_midpoint = states.can_midpoint
        self.can_make_tangent = states.can_tangent

    def _on_feature_row_label_touch(self, feat_id: str, instance: Label, touch):
        if not instance.collide_point(*touch.pos):
            return False
        feat = next((f for f in self.session.features if f.id == feat_id), None)
        if feat is None or not feat.sketch_visible:
            return False
        if self._preview_focus_id == feat_id:
            self._preview_focus_id = None
        else:
            self._preview_focus_id = feat_id
        self._recompute_construct_buttons()
        self._sync_sketch_preview()
        self._apply_feature_row_focus_visual()
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
                line2 = feature_secondary_line(feat, by_id)
                row_h = dp(50) if line2 else dp(40)
                row = BoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=row_h,
                    spacing=dp(4),
                    padding=[0, 0, dp(4), 0],
                )
                with row.canvas.before:
                    fc = Color(
                        *(
                            _FEATURE_ROW_FOCUS_RGBA_ON
                            if feat.sketch_visible and feat.id == self._preview_focus_id
                            else _FEATURE_ROW_FOCUS_RGBA_OFF
                        )
                    )
                    rect = Rectangle(pos=row.pos, size=row.size)

                def _upd_focus_bg(*_a, r=rect, rw=row):
                    r.pos = rw.pos
                    r.size = rw.size

                row.bind(pos=_upd_focus_bg, size=_upd_focus_bg)
                row._probe_feat_id = feat.id
                row._probe_focus_color = fc
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
                cb.disabled = self.is_probing or not feat.sketch_visible
                cb.bind(active=partial(self._on_row_checkbox, feat.id))
                cb_col.add_widget(cb)

                lbl_text, lbl_markup = self._feature_row_label_text(
                    line1, line2, visible=feat.sketch_visible, detail_font=detail_font
                )
                lbl = Label(
                    text=lbl_text,
                    markup=lbl_markup,
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
                vis_btn = CMMWorkbenchSketchVisibilityToggle(
                    image="data/eye.png",
                    size_hint_x=None,
                    width=dp(32),
                    state="down" if feat.sketch_visible else "normal",
                    disabled=self.is_probing,
                )
                vis_btn.opacity = 1.0 if feat.sketch_visible else 0.38
                vis_btn.bind(on_release=partial(self._on_sketch_visibility_toggle, feat.id))
                row.add_widget(vis_btn)
                rename_btn = Button(
                    text=tr._("Rename"),
                    size_hint_x=None,
                    width=dp(78),
                    disabled=self.is_probing,
                    on_release=partial(self._on_rename_feature, feat.id),
                )
                row.add_widget(rename_btn)
                delete_btn = Button(
                    text=tr._("Delete"),
                    size_hint_x=None,
                    width=dp(78),
                    disabled=self.is_probing,
                    on_release=partial(self._on_delete_feature, feat.id),
                )
                row.add_widget(delete_btn)
                Clock.schedule_once(lambda dt, lw=lbl: _sync_feat_label_textsize(lw), 0)
                fl.add_widget(row)
            self._sync_sketch_preview()
            empty = len(self.session.features) == 0
            ph = self.ids.lbl_sketch_placeholder
            ph.opacity = 1.0 if empty else 0.0
            ph.height = ph.texture_size[1] if empty else 0  # Collapse height if empty to avoid touch interferences
        except Exception:
            logger.debug("Could not refresh feature UI", exc_info=True)

    def _on_sketch_visibility_toggle(self, fid: str, widget, *_args) -> None:
        feat = next((f for f in self.session.features if f.id == fid), None)
        if feat is None:
            return
        visible = widget.state == "down"
        if feat.sketch_visible == visible:
            return
        feat.sketch_visible = visible
        widget.opacity = 1.0 if visible else 0.38
        if not visible:
            if fid in self._selection_order:
                self._selection_order[:] = [x for x in self._selection_order if x != fid]
            if self._preview_focus_id == fid:
                self._preview_focus_id = None
            self._recompute_construct_buttons()
        self._refresh_feature_ui()

    def _on_row_checkbox(self, fid: str, _widget, active: bool):
        if not self._guard_session_mutation():
            _widget.active = not active
            return
        feat = next((f for f in self.session.features if f.id == fid), None)
        if feat is None or not feat.sketch_visible:
            _widget.active = False
            return
        if active:
            if fid not in self._selection_order:
                self._selection_order.append(fid)
        else:
            self._selection_order[:] = [x for x in self._selection_order if x != fid]
        self._recompute_construct_buttons()
        self._sync_sketch_preview()

    def _clear_construct_selection(self) -> None:
        self._selection_order.clear()
        self._preview_focus_id = None

    def on_clear_construct_selection(self):
        if not self._guard_session_mutation():
            return
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_segment(self):
        if not self._guard_session_mutation():
            return
        new_feats, err = construct_segment(
            self.session.features,
            self._effective_construct_selection(),
            label=tr._("Segment"),
        )
        if err:
            self._toast(tr._(err))
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_polyline(self, closed: bool):
        if not self._guard_session_mutation():
            return
        min_n = 3 if closed else 2
        min_err = tr._("Select at least %(n)d vertices in checkbox order.") % {"n": min_n}
        new_feats, err = construct_polyline(
            self.session.features,
            self._effective_construct_selection(),
            label=tr._("Closed polyline") if closed else tr._("Open polyline"),
            closed=closed,
            min_verts_error=min_err,
        )
        if err:
            self._toast(err)
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_polyline_open(self):
        self.on_construct_polyline(False)

    def on_construct_polyline_closed(self):
        self.on_construct_polyline(True)

    def on_construct_derived_circle(self):
        if not self._guard_session_mutation():
            return
        new_feats, err = construct_circumcircle(
            self.session.features,
            self._effective_construct_selection(),
            label=tr._("Circumcircle"),
        )
        if err:
            self._toast(tr._(err))
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_intersection(self):
        if not self._guard_session_mutation():
            return
        new_feats, err = construct_intersection(
            self.session.features,
            self._effective_construct_selection(),
            intersection_base_label=tr._("Intersection"),
        )
        if err:
            self._toast(tr._(err))
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_midpoint(self):
        if not self._guard_session_mutation():
            return
        new_feats, err = construct_midpoint(
            self.session.features,
            self._effective_construct_selection(),
            label=tr._("Midpoint"),
        )
        if err:
            self._toast(tr._(err))
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def on_construct_tangent(self):
        if not self._guard_session_mutation():
            return
        new_feats, err = construct_tangent(
            self.session.features,
            self._effective_construct_selection(),
            tangent_point_label=lambda n: tr._("Tangent point %(n)d") % {"n": n},
            tangent_line_label=lambda n: tr._("Tangent %(n)d") % {"n": n},
            tangent_a_label=lambda n: tr._("Tangent %(n)d\u00b7A") % {"n": n},
            tangent_b_label=lambda n: tr._("Tangent %(n)d\u00b7B") % {"n": n},
        )
        if err:
            self._toast(tr._(err))
            return
        self.session.features.extend(new_feats)
        self._clear_construct_selection()
        self._refresh_feature_ui()

    def _on_delete_feature(self, fid: str, *args):
        if not self._guard_session_mutation():
            return
        blockers = features_referencing_id(self.session.features, fid)
        if blockers:
            preview = ", ".join(blockers[:5])
            suffix = "…" if len(blockers) > 5 else ""
            self._toast(tr._("Cannot delete: referenced by constructed features.") + "\n" + preview + suffix)
            return
        self.session.features[:] = [f for f in self.session.features if f.id != fid]
        self._selection_order[:] = [x for x in self._selection_order if x != fid]
        self._refresh_feature_ui()

    def _on_rename_feature(self, fid: str, *_args):
        if not self._guard_session_mutation():
            return
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
            if not self._guard_session_mutation():
                return
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
        f = CMMWorkbenchFeature.new_point(
            tr._("Stored position"),
            wx,
            wy,
            wz,
            source="Manual",
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
        f = CMMWorkbenchFeature.new_circle(
            tr._("Manual circle"),
            wx,
            wy,
            r,
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

    def _refresh_probe_tip_diameter_hints(self) -> None:
        hint = get_machine_config_hint("zprobe.probe_tip_diameter") or tr._("config")
        for prefix in ("466", "461", "462", "463", "464", "465"):
            try:
                self.ids[f"t{prefix}_d"].hint_text = hint
            except Exception:
                logger.debug("Could not update tip diameter hint for t%s_d", prefix)

    def _read_common_probe_opts(self, prefix: str) -> dict:
        return {
            "h": _parse_optional_float_text(self.ids[f"t{prefix}_h"]) or "",
            "c": _parse_optional_float_text(self.ids[f"t{prefix}_c"]) or "",
            "f_probe": _parse_float_field(self.ids[f"t{prefix}_f"], 300.0),
            "k_rapid": _parse_float_field(self.ids[f"t{prefix}_k"], 800.0),
            "l_repeat": _parse_optional_float_text(self.ids[f"t{prefix}_l"]) or "",
            "r_retract": _parse_optional_float_text(self.ids[f"t{prefix}_r"]) or "",
            "d_tip": _parse_optional_float_text(self.ids[f"t{prefix}_d"]) or "",
        }

    def on_probe_axis466(self):
        try:
            if not self._m466_side:
                self._toast_need_probing_option()
                return
            travel = self.ids.t466_xy.text.strip().replace(",", ".")
            side = self._m466_side
            x_cmd, y_cmd = "", ""
            if side in ("Left", "Right"):
                if not travel:
                    self._toast(tr._("Enter X travel for this probe direction."))
                    return
                x_cmd = _distance_for_command(travel, negate=(side == "Right"))
            elif side in ("Bottom", "Top"):
                if not travel:
                    self._toast(tr._("Enter Y travel for this probe direction."))
                    return
                y_cmd = _distance_for_command(travel, negate=(side == "Top"))
            else:
                self._toast_need_probing_option()
                return
            opts = self._read_common_probe_opts("466")
            e_o = _parse_optional_float_text(self.ids.t466_e)
            self._run_gcode_program(build_m466(x=x_cmd, y=y_cmd, e=e_o or "", **opts))
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
            self._run_gcode_program(build_m461(x=x_cmd, y=y_cmd, e=e_o or "", **opts))
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
                    x=x_cmd,
                    y=y_cmd,
                    e_depth=e_o or "",
                    j_clearance=j_o or "",
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
            self._run_gcode_program(build_m463(x, y, e=e_o or "", **opts))
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
            self._run_gcode_program(build_m464(x, y, e=e_o or "", **opts))
        except Exception as e:
            self._toast(str(e))

    def on_angle465(self):
        try:
            if not self._angle_variant:
                self._toast_need_probing_option()
                return
            travel = self.ids.t465_xy.text.strip().replace(",", ".")
            v = self._angle_variant
            if v in ("above", "below"):
                if not travel:
                    self._toast(tr._("Enter X distance for M465."))
                    return
                xs_cmd = _signed_distance_for_command(travel)
                ys_cmd = ""
            elif v in ("left", "right"):
                if not travel:
                    self._toast(tr._("Enter Y distance for M465."))
                    return
                xs_cmd = ""
                ys_cmd = _signed_distance_for_command(travel)
            else:
                self._toast_need_probing_option()
                return
            e_field = self.ids.t465_e
            e_val = _parse_optional_float_text(e_field) or e_field.hint_text.strip().replace(",", ".") or "2"
            e_cmd = _distance_for_command(e_val, negate=(v in ("above", "right")))
            opts = self._read_common_probe_opts("465")
            self._run_gcode_program(build_m465(x=xs_cmd, y=ys_cmd, e=e_cmd, **opts))
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

        _format_labels = {
            "JSON": tr._("JSON (full session)"),
            "CSV": tr._("CSV (feature table)"),
            "DXF": tr._("DXF (geometry + angle labels)"),
        }
        for kind in ("JSON", "CSV", "DXF"):

            def _choose(*_a, k=kind):
                dd.dismiss()
                Clock.schedule_once(lambda dt, kk=k: on_pick(kk), 0)

            btn = Button(
                text=_format_labels[kind],
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
        cp.lb_title.text = tr._("Reset CMM Workbench?")
        cp.lb_content.text = tr._("Clear all features from the current session?\nYou will lose unsaved work.")

        def on_confirm():
            if not self._guard_session_mutation():
                return
            self.session.features.clear()
            self._clear_construct_selection()
            self._refresh_feature_ui()
            self._toast(tr._("CMM Workbench cleared."))

        cp.confirm = on_confirm
        cp.cancel = None
        cp.open(root)

    def on_load_session(self):
        self._prompt_load_session_file()

    def _prompt_load_session_file(self):
        root = App.get_running_app().root

        def on_confirm(popup, dest):
            if not self._guard_session_mutation():
                return
            try:
                from ..core.io_import import load_session_from_path

                self.session, report = load_session_from_path(dest)
                self._clear_construct_selection()
                self._refresh_feature_ui()
                popup.dismiss()
                msg = tr._("Loaded %(n)d features:\n%(path)s") % {
                    "n": report.imported,
                    "path": dest,
                }
                if report.warnings:
                    preview = "\n".join(report.warnings[:3])
                    if len(report.warnings) > 3:
                        preview += tr._("\n…and %(more)d more warnings") % {
                            "more": len(report.warnings) - 3,
                        }
                    msg = f"{msg}\n{preview}"
                self._toast(msg)
            except OSError as e:
                root.show_message_popup(tr._("Could not read:\n%s") % e, False)
            except Exception as e:
                root.show_message_popup(tr._("Invalid session file:\n%s") % e, False)

        open_local_file_picker(
            title=tr._("Load session"),
            default_name="cmm_workbench_export.json",
            size_hint=(0.82, 0.82),
            on_confirm=on_confirm,
            confirm_label=tr._("Load"),
            filters=[p for patterns in _SESSION_FILE_FILTERS.values() for p in patterns],
        )

    def _prompt_save_export_file(self, export_kind: str = "JSON"):
        root = App.get_running_app().root
        kind = export_kind.strip().upper() if isinstance(export_kind, str) else "JSON"
        if kind not in ("JSON", "CSV", "DXF"):
            kind = "JSON"
        stems = {
            "JSON": "cmm_workbench_export.json",
            "CSV": "cmm_workbench_export.csv",
            "DXF": "cmm_workbench_export.dxf",
        }

        def on_confirm(popup, dest):
            def write(path: str):
                if not self._guard_session_mutation():
                    return
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

            confirm_overwrite_then(dest, write)

        open_local_file_picker(
            title=tr._("Save export (%s)") % kind,
            default_name=stems[kind],
            size_hint=(0.82, 0.85),
            on_confirm=on_confirm,
            filters=_SESSION_FILE_FILTERS[kind],
        )
