"""Stock settings popup — configure stock shape and cut simulation."""

from __future__ import annotations

import math

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.stock.simulator.carver_select import (
    BACKEND_CYLINDRICAL,
    BACKEND_HEIGHTMAP,
    BACKEND_VOXEL,
    DEFAULT_CARVER_MODE,
    MODE_AUTO,
    MODE_CYLINDRICAL,
    MODE_HEIGHTMAP,
    MODE_VOXEL,
    normalize_carver_mode,
    recommend_carver,
)
from carveracontroller.addons.stock.simulator.simulation_quality import (
    DEFAULT_CHECKPOINT_LEVEL,
    DEFAULT_VOXEL_RESOLUTION,
    RESOLUTION_LEVELS,
    format_cell_size_mm,
    pick_cell_size_mm,
)
from carveracontroller.addons.stock.stock_defaults import (
    DEFAULT_DIAMETER_MM,
    DEFAULT_HEIGHT_MM,
    DEFAULT_LENGTH_MM,
    DEFAULT_WIDTH_MM,
    default_settings,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_material import (
    DEFAULT_MATERIAL,
    MATERIAL_ACRYLIC,
    MATERIAL_ACRYLIC_BICOLOR,
    MATERIAL_ALUMINUM,
    MATERIAL_BEIGE,
    MATERIAL_COPPER,
    MATERIAL_PCB,
    MATERIAL_WOOD,
    normalize_stock_material,
)
from carveracontroller.addons.stock.stock_origin import (
    CORNER_BC,
    CORNER_BL,
    CORNER_BR,
    CORNER_CENTER,
    CORNER_FC,
    CORNER_LC,
    CORNER_RC,
    CORNER_TL,
    CORNER_TR,
    Z_BOTTOM,
    Z_CENTER,
    Z_TOP,
    StockOrigin,
)
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock, RotaryCylindricalStock
from carveracontroller.translation import tr


def _stock_corner_pairs():
    return [
        (tr._("Front-left"), CORNER_BL),
        (tr._("Front-center"), CORNER_FC),
        (tr._("Front-right"), CORNER_BR),
        (tr._("Center-left"), CORNER_LC),
        (tr._("Center"), CORNER_CENTER),
        (tr._("Center-right"), CORNER_RC),
        (tr._("Back-left"), CORNER_TL),
        (tr._("Back-center"), CORNER_BC),
        (tr._("Back-right"), CORNER_TR),
    ]


def _rotary_x_end_pairs():
    return [
        (tr._("X min (left end)"), CORNER_LC),
        (tr._("X max (right end)"), CORNER_RC),
        (tr._("X center"), CORNER_CENTER),
    ]


def _z_reference_pairs():
    return [
        (tr._("Top of stock (Z0 = top)"), Z_TOP),
        (tr._("Center of stock (Z0 = mid-height)"), Z_CENTER),
        (tr._("Bottom of stock (Z0 = bottom)"), Z_BOTTOM),
    ]


def _rotary_z_pairs():
    return [
        (tr._("Axis center (Z0 = A axis)"), Z_CENTER),
    ]


def _shape_kind_pairs(rotary: bool = False):
    if rotary:
        return [
            (tr._("Rectangular"), "rectangular"),
            (tr._("Cylinder"), RotaryCylindricalStock.kind),
        ]
    return [
        (tr._("Rectangular"), "rectangular"),
        (tr._("Cylinder"), "cylindrical"),
    ]


def _resolution_size_label(level: str, cell_mm: float | None, carver: str) -> str:
    """Caption for one quality level, with real cell size when known."""
    if cell_mm is None:
        return {
            "low": tr._("Low (faster)"),
            "medium": tr._("Medium"),
            "high": tr._("High (finer)"),
        }[level]
    size_txt = format_cell_size_mm(cell_mm)
    kind = str(carver).strip().lower()
    if kind == BACKEND_VOXEL:
        token = tr._("%s mm/voxel") % size_txt
    elif kind == BACKEND_CYLINDRICAL:
        token = tr._("%s mm along X, %s mm at OD") % (size_txt, size_txt)
    else:
        token = tr._("%s mm/cell") % size_txt
    if level == "low":
        return tr._("Low (~%s, faster)") % token
    if level == "high":
        return tr._("High (~%s, finer)") % token
    return tr._("Medium (~%s)") % token


def _voxel_resolution_pairs(carver: str = BACKEND_VOXEL, bounds: StockBounds | None = None):
    """Low/medium/high labels; include mm/cell when stock size is known."""
    sizes = None
    if bounds is not None:
        sizes = {level: pick_cell_size_mm(bounds, carver=carver, level=level) for level in RESOLUTION_LEVELS}
    return [
        (_resolution_size_label(level, None if sizes is None else sizes[level], carver), level)
        for level in RESOLUTION_LEVELS
    ]


def _checkpoint_level_pairs():
    return [
        (tr._("Low (less memory, coarser scrubbing)"), "low"),
        (tr._("Medium"), "medium"),
        (tr._("High (more memory, smoother scrubbing)"), "high"),
    ]


def _auto_carver_label(backend: str | None = None) -> str:
    """Spinner caption for Auto, including the backend it would pick."""
    names = {
        BACKEND_HEIGHTMAP: tr._("heightmap"),
        BACKEND_CYLINDRICAL: tr._("cylindrical"),
        BACKEND_VOXEL: tr._("voxels"),
    }
    name = names.get(str(backend or "").strip().lower())
    if name:
        return tr._("Auto (%s)") % name
    return tr._("Auto")


def _carver_mode_pairs(recommended: str | None = None):
    return [
        (_auto_carver_label(recommended), MODE_AUTO),
        (tr._("Heightmap (fast / no undercuts)"), MODE_HEIGHTMAP),
        (tr._("Cylindrical (fast / no undercuts)"), MODE_CYLINDRICAL),
        (tr._("Voxels (slower / undercuts)"), MODE_VOXEL),
    ]


def _material_pairs():
    return [
        (tr._("Default"), MATERIAL_BEIGE),
        (tr._("PCB"), MATERIAL_PCB),
        (tr._("Wood"), MATERIAL_WOOD),
        (tr._("Acrylic"), MATERIAL_ACRYLIC),
        (tr._("Bi-color acrylic"), MATERIAL_ACRYLIC_BICOLOR),
        (tr._("Aluminum"), MATERIAL_ALUMINUM),
        (tr._("Copper"), MATERIAL_COPPER),
    ]


def _parse_positive_float(text: str, label: str) -> float:
    t = (text or "").strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    value = float(t)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(tr._("%s must be a finite positive number") % label)
    return value


def _parse_finite_float(text: str, label: str) -> float:
    t = (text or "").strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    value = float(t)
    if not math.isfinite(value):
        raise ValueError(tr._("%s must be a finite number") % label)
    return value


def _format_mm(value) -> str:
    """Render a millimetre value without a spurious trailing ``.0``."""
    v = float(value)
    if v == int(v):
        return str(int(v))
    return str(v)


def _deref_widget(widget):
    """Return a strong widget ref from a Kv id (WeakProxy) or *widget* itself.

    Dead proxies raise ``ReferenceError``; treat those as missing.
    """
    if widget is None:
        return None
    try:
        return widget.__self__
    except ReferenceError:
        return None
    except AttributeError:
        return widget


# Cap modal height on small screens (Facing preset-list pattern).
_MAX_HEIGHT_FRAC = 0.72
_MIN_SCROLL_HEIGHT = 120


class StockSettingsPopup(ModalView):
    """Configure stock shape, origin, and cut-simulation toggles (session-only)."""

    simulation_available = BooleanProperty(True)
    simulation_hint = StringProperty("")
    rotary_mode = BooleanProperty(False)
    has_off_axis_y = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._corner_pairs = None
        self._z_pairs = None
        self._shape_pairs = None
        self._voxel_resolution_pairs = None
        self._checkpoint_level_pairs = None
        self._carver_mode_pairs = None
        self._material_pairs = None
        self._fit_event = None
        # Snapshot seeds the form and is the Cancel/dismiss restore baseline.
        self._settings_snapshot: dict = default_settings()
        super().__init__(**kwargs)
        self._pin_detachable_rows()
        self.bind(on_open=self._on_open, on_dismiss=self._on_dismiss)
        self.bind(simulation_available=self._schedule_fit_popup_height)
        self.bind(rotary_mode=self._on_rotary_mode)
        self.bind(has_off_axis_y=self._on_off_axis_y)
        self.simulation_hint = tr._("Cut simulation needs tool geometry from CAM comments in the loaded G-code file.")
        self._ensure_lists()
        self._populate_spinner_choices()
        self._write_settings_to_ui(self._settings_snapshot)
        self.ids.chk_show_stock.bind(active=self._on_show_stock_active)
        self.ids.spn_shape.bind(text=self._on_shape_text)
        if "spn_carver_mode" in self.ids:
            self.ids.spn_carver_mode.bind(text=self._on_carver_mode_text)
        for field in ("txt_width", "txt_length", "txt_height"):
            if field in self.ids:
                self.ids[field].bind(text=self._on_dimension_text)
        if "form_body" in self.ids:
            self.ids.form_body.bind(minimum_height=self._schedule_fit_popup_height)
        if "lbl_help" in self.ids:
            self.ids.lbl_help.bind(height=self._schedule_fit_popup_height)

    def _ensure_lists(self):
        if getattr(self, "_corner_pairs", None) is None:
            self._corner_pairs = _rotary_x_end_pairs() if self.rotary_mode else _stock_corner_pairs()
        if getattr(self, "_z_pairs", None) is None:
            self._z_pairs = _rotary_z_pairs() if self.rotary_mode else _z_reference_pairs()
        if getattr(self, "_shape_pairs", None) is None:
            self._shape_pairs = _shape_kind_pairs(rotary=self.rotary_mode)
        if getattr(self, "_voxel_resolution_pairs", None) is None:
            self._voxel_resolution_pairs = _voxel_resolution_pairs(BACKEND_VOXEL)
        if getattr(self, "_checkpoint_level_pairs", None) is None:
            self._checkpoint_level_pairs = _checkpoint_level_pairs()
        if getattr(self, "_carver_mode_pairs", None) is None:
            self._carver_mode_pairs = _carver_mode_pairs()
        if getattr(self, "_material_pairs", None) is None:
            self._material_pairs = _material_pairs()

    def _path_recommendation(self, mode: str = MODE_AUTO):
        """Recommend a carver for spinner filtering and resolution labels."""
        tool_table, scale = self._viewer_tools()
        return recommend_carver(
            mode=mode,
            has_4axis=bool(self.rotary_mode),
            has_off_axis_y=bool(getattr(self, "has_off_axis_y", False)),
            tool_table=tool_table,
            tool_unit_scale=scale,
        )

    def _effective_carver_for_resolution_labels(self) -> str:
        """Backend whose cell-count labels should be shown for the resolution spinner."""
        mode = self._carver_mode_from_ui()
        rec = self._path_recommendation(mode)
        return rec.backend

    def _refresh_carver_spinner_options(self) -> None:
        """Offer Auto + only carvers compatible with the loaded path."""
        if "spn_carver_mode" not in self.ids:
            return
        self._ensure_lists()
        rec = self._path_recommendation(MODE_AUTO)
        current = self._carver_mode_from_ui()
        self._carver_mode_pairs = _carver_mode_pairs(rec.backend)
        allowed_modes = {MODE_AUTO} | set(rec.allowed)
        pairs = [(lab, val) for lab, val in self._carver_mode_pairs if val in allowed_modes]
        if not pairs:
            pairs = list(self._carver_mode_pairs)
        self.ids.spn_carver_mode.values = [lab for lab, _ in pairs]
        if current not in allowed_modes:
            self.ids.spn_carver_mode.text = self._label_for_value(pairs, MODE_AUTO)
        else:
            # Keep selection if still listed; refresh Auto caption from the new pairs.
            self.ids.spn_carver_mode.text = self._label_for_value(pairs, current)

    def _bounds_for_resolution_preview(self) -> StockBounds | None:
        """AABB size from the form (origin is irrelevant for cell size)."""
        ids = getattr(self, "ids", None)
        if not ids or "txt_width" not in ids or "txt_height" not in ids:
            return None
        try:
            kind = self._shape_kind_from_ui()
            if kind == RotaryCylindricalStock.kind:
                diameter = _parse_positive_float(ids.txt_width.text, tr._("Diameter"))
                length = _parse_positive_float(ids.txt_height.text, tr._("Length"))
                return StockBounds(0.0, 0.0, 0.0, length, diameter, diameter)
            if kind == "cylindrical":
                diameter = _parse_positive_float(ids.txt_width.text, tr._("Diameter"))
                height = _parse_positive_float(ids.txt_height.text, tr._("Height"))
                return StockBounds(0.0, 0.0, 0.0, diameter, diameter, height)
            width = _parse_positive_float(ids.txt_width.text, tr._("Width"))
            height = _parse_positive_float(ids.txt_height.text, tr._("Height"))
            if "txt_length" not in ids:
                return None
            length = _parse_positive_float(ids.txt_length.text, tr._("Length"))
            return StockBounds(0.0, 0.0, 0.0, width, length, height)
        except (TypeError, ValueError, AttributeError):
            return None

    def _refresh_resolution_spinner_labels(self) -> None:
        """Update Low/Medium/High captions for the selected carver and stock size."""
        if "spn_voxel_resolution" not in self.ids:
            return
        level = self._voxel_resolution_from_ui()
        carver = self._effective_carver_for_resolution_labels()
        self._voxel_resolution_pairs = _voxel_resolution_pairs(
            carver,
            bounds=self._bounds_for_resolution_preview(),
        )
        self.ids.spn_voxel_resolution.values = [lab for lab, _ in self._voxel_resolution_pairs]
        self.ids.spn_voxel_resolution.text = self._label_for_value(self._voxel_resolution_pairs, level)

    def _pin_detachable_rows(self) -> None:
        """Keep a strong ref to rows that leave the layout so they can be re-added.

        Kv ``ids`` are WeakProxy; storing ``self.ids.foo`` does not keep the
        widget alive after ``remove_widget``. Kivy requires ``id.__self__``:
        https://kivy.org/doc/stable/guide/lang.html#referencing-widgets
        """
        ids = getattr(self, "ids", None)
        if not ids:
            return
        for name in ("row_length", "row_z_ref"):
            if name not in ids:
                continue
            widget = _deref_widget(ids[name])
            if widget is not None:
                setattr(self, f"_pinned_{name}", widget)

    def _row(self, name: str):
        pinned = getattr(self, f"_pinned_{name}", None)
        if pinned is not None:
            return pinned
        ids = getattr(self, "ids", None)
        if not ids or name not in ids:
            return None
        return _deref_widget(ids[name])

    def _row_in_form(self, name: str) -> bool:
        ids = getattr(self, "ids", None)
        if not ids or "dim_form" not in ids:
            return False
        row = self._row(name)
        return row is not None and row in ids["dim_form"].children

    def _on_open(self, *_args):
        self._refresh_simulation_availability()
        self._refresh_carver_spinner_options()
        self._refresh_resolution_spinner_labels()
        Window.bind(size=self._schedule_fit_popup_height)
        self._schedule_fit_popup_height()

    def _on_dismiss(self, *_args):
        """Discard any unapplied edits.

        Runs whether the popup was closed via Apply (a no-op — the snapshot
        was just updated to match), Cancel, or the hardware back button —
        so the form always reflects the last *applied* settings next time
        it's opened.
        """
        Window.unbind(size=self._schedule_fit_popup_height)
        if self._fit_event is not None:
            self._fit_event.cancel()
            self._fit_event = None
        self._write_settings_to_ui(self._settings_snapshot)
        try:
            App.get_running_app().root.restore_keyboard_jog_control()
        except Exception:
            pass

    def _schedule_fit_popup_height(self, *_args) -> None:
        if self._fit_event is not None:
            self._fit_event.cancel()
        self._fit_event = Clock.schedule_once(self._fit_popup_height, 0)

    def _fit_popup_height(self, *_args) -> None:
        """Size to content, then clamp to a fraction of the window with scroll.

        ``content_box`` fills the modal (``size_hint: 1, 1``) so the ModalView
        background always covers title, form, and buttons. The ScrollView takes
        the remaining space between help and the footer.
        """
        self._fit_event = None
        ids = self.ids
        if "content_box" not in ids or "form_body" not in ids:
            return
        if "lbl_title" not in ids or "lbl_help" not in ids or "btn_row" not in ids:
            return
        content_box = ids.content_box
        pad_top, pad_bottom = content_box.padding[1], content_box.padding[3]
        # Fixed frame around the scrolling form: padding, title, help, buttons,
        # and the three spacings between those four content_box children.
        frame_h = (
            float(pad_top)
            + float(pad_bottom)
            + float(ids.lbl_title.height)
            + float(ids.lbl_help.height)
            + float(ids.btn_row.height)
            + float(content_box.spacing) * 3
        )
        form_h = max(
            float(ids.form_body.minimum_height),
            float(ids.form_body.height),
            float(dp(_MIN_SCROLL_HEIGHT)),
        )
        max_h = float(Window.height) * _MAX_HEIGHT_FRAC
        self.height = min(frame_h + form_h, max_h)

    def _on_show_stock_active(self, _instance, active: bool) -> None:
        """Cut simulation requires visible stock — clear simulate when show is off."""
        if not active and "chk_simulate" in self.ids:
            self.ids.chk_simulate.active = False

    def _on_rotary_mode(self, *_args) -> None:
        self._corner_pairs = None
        self._z_pairs = None
        self._shape_pairs = None
        self._ensure_lists()
        if "spn_shape" in getattr(self, "ids", {}):
            self._update_dimension_field_visibility()
            self._populate_spinner_choices()
        self._refresh_carver_spinner_options()
        self._refresh_resolution_spinner_labels()

    def _on_off_axis_y(self, *_args) -> None:
        self._refresh_carver_spinner_options()
        self._refresh_resolution_spinner_labels()

    def _on_shape_text(self, *_args) -> None:
        self._update_dimension_field_visibility()
        self._refresh_resolution_spinner_labels()

    def _on_dimension_text(self, *_args) -> None:
        self._refresh_resolution_spinner_labels()

    def _shape_kind_from_ui(self) -> str:
        text = self.ids.spn_shape.text
        for lab, val in self._shape_pairs:
            if lab == text:
                return val
        return "rectangular"

    def _is_cylinder_kind(self, kind: str | None = None) -> bool:
        k = kind if kind is not None else self._shape_kind_from_ui()
        return k in ("cylindrical", RotaryCylindricalStock.kind)

    def _update_rotary_origin_visibility(self) -> None:
        ids = getattr(self, "ids", None) or {}
        if "lbl_corner" in ids:
            ids["lbl_corner"].text = tr._("Origin X") if self.rotary_mode else tr._("WCS origin")
        row = self._row("row_z_ref")
        form = ids.get("dim_form")
        if row is None or form is None:
            return
        if self.rotary_mode:
            if row in form.children:
                form.remove_widget(row)
        else:
            if row.parent is None:
                corner_row = ids.get("row_corner")
                if corner_row is not None and corner_row in form.children:
                    idx = form.children.index(corner_row)
                    form.add_widget(row, index=idx)
                else:
                    form.add_widget(row)
            row.height = dp(40)
            row.opacity = 1
            row.disabled = False
        self._schedule_fit_popup_height()

    def _update_dimension_field_visibility(self) -> None:
        """Show Width/Length for rectangular; Diameter for cylindrical.

        Length is removed from the layout (not merely disabled) so the parent
        spacing collapses and no blank row remains.
        """
        ids = self.ids
        kind = self._shape_kind_from_ui()
        cylindrical = self._is_cylinder_kind(kind)
        rotary = bool(getattr(self, "rotary_mode", False))
        if "lbl_width" in ids:
            if cylindrical:
                ids.lbl_width.text = tr._("Diameter (mm)")
            elif rotary:
                ids.lbl_width.text = tr._("Length X (mm)")
            else:
                ids.lbl_width.text = tr._("Width (mm)")
        if "lbl_height" in ids:
            if cylindrical and rotary:
                ids.lbl_height.text = tr._("Length (mm)")
            elif rotary:
                ids.lbl_height.text = tr._("Height Z (mm)")
            else:
                ids.lbl_height.text = tr._("Height (mm)")
        row = self._row("row_length")
        form = ids.get("dim_form")
        if row is None or form is None:
            self._update_rotary_origin_visibility()
            return
        hide_length = cylindrical
        if hide_length:
            if row in form.children:
                form.remove_widget(row)
        else:
            if row.parent is None:
                # Insert Length just above Height (Kivy children are reverse-order).
                height_row = ids.get("row_height")
                if height_row is not None and height_row in form.children:
                    idx = form.children.index(height_row)
                    form.add_widget(row, index=idx + 1)
                else:
                    form.add_widget(row)
            row.height = dp(40)
            row.opacity = 1
            row.disabled = False
            if "lbl_length" in ids:
                ids["lbl_length"].text = tr._("Width Y (mm)") if rotary else tr._("Length (mm)")
        self._update_rotary_origin_visibility()
        self._schedule_fit_popup_height()

    def reset_for_loaded_file(self, shape=None, origin=None, show_stock: bool = False) -> dict:
        """Reset session toggles for a newly loaded file; optionally replace shape/origin.

        Cut simulation is always forced off. Stock preview is off unless
        *show_stock* is true (CAM-header stock was applied).

        Used when a new G-code file loads. Must not read the live form — dirty
        or invalid mid-edit fields would otherwise be committed (or wipe the
        applied baseline via a defaults fallback).

        Quality / playback-mesh flags are kept from the last applied snapshot.
        When *shape* / *origin* are provided (auto-init), they overwrite the
        previous file's dimensions; otherwise those fields are left as-is.
        """
        settings = dict(self._settings_snapshot)
        settings["show_stock"] = bool(show_stock)
        settings["simulate_cut"] = False
        settings["material"] = normalize_stock_material(settings.get("material"))
        if shape is not None:
            settings["shape"] = shape.to_dict()
        if origin is not None:
            settings["origin"] = origin.to_dict()
        self._write_settings_to_ui(settings)
        self._settings_snapshot = dict(settings)
        return settings

    def _refresh_simulation_availability(self):
        app = App.get_running_app()
        viewer = None
        if app is not None and getattr(app, "root", None) is not None:
            viewer = getattr(app.root, "gcode_viewer", None)
        if viewer is not None:
            self.simulation_available = bool(viewer.simulation_available())
            return
        tool_table, _scale = self._viewer_tools()
        self.simulation_available = bool(tool_table)

    def _populate_spinner_choices(self):
        self._ensure_lists()
        ids = self.ids
        ids.spn_shape.values = [lab for lab, _ in self._shape_pairs]
        ids.spn_corner.values = [lab for lab, _ in self._corner_pairs]
        if self._row_in_form("row_z_ref"):
            ids["spn_z_ref"].values = [lab for lab, _ in self._z_pairs]
        ids.spn_voxel_resolution.values = [lab for lab, _ in self._voxel_resolution_pairs]
        ids.spn_checkpoint_level.values = [lab for lab, _ in self._checkpoint_level_pairs]
        if "spn_carver_mode" in ids:
            ids.spn_carver_mode.values = [lab for lab, _ in self._carver_mode_pairs]
        if "spn_material" in ids:
            ids.spn_material.values = [lab for lab, _ in self._material_pairs]

    def _label_for_value(self, pairs, value, fallback: str | None = None) -> str:
        for label, val in pairs:
            if val == value:
                return label
        return fallback if fallback is not None else pairs[0][0]

    def _write_settings_to_ui(self, settings: dict) -> None:
        """Populate the form fields from a settings dict (inverse of :meth:`read_settings_from_ui`)."""
        self._ensure_lists()
        ids = self.ids
        shape = settings.get("shape") or {}
        origin = settings.get("origin") or {}
        kind = shape.get("kind", "rectangular")

        ids.spn_shape.text = self._label_for_value(self._shape_pairs, kind)
        self._update_dimension_field_visibility()
        if kind in ("cylindrical", RotaryCylindricalStock.kind):
            ids.txt_width.text = _format_mm(shape.get("diameter_mm", DEFAULT_DIAMETER_MM))
            length_or_height = shape.get("length_mm", shape.get("height_mm", DEFAULT_HEIGHT_MM))
            ids.txt_height.text = _format_mm(length_or_height)
        else:
            ids.txt_width.text = _format_mm(shape.get("width_mm", DEFAULT_WIDTH_MM))
            if self._row_in_form("row_length"):
                ids["txt_length"].text = _format_mm(shape.get("length_mm", DEFAULT_LENGTH_MM))
            ids.txt_height.text = _format_mm(shape.get("height_mm", DEFAULT_HEIGHT_MM))
        ids.spn_corner.text = self._label_for_value(self._corner_pairs, origin.get("xy_corner"))
        if self._row_in_form("row_z_ref"):
            ids["spn_z_ref"].text = self._label_for_value(self._z_pairs, origin.get("z_reference"))
        ids.txt_offset_x.text = _format_mm(origin.get("offset_x_mm", 0.0))
        ids.txt_offset_y.text = _format_mm(origin.get("offset_y_mm", 0.0))
        ids.txt_offset_z.text = _format_mm(origin.get("offset_z_mm", 0.0))
        ids.chk_show_stock.active = bool(settings.get("show_stock", False))
        ids.chk_simulate.active = bool(settings.get("simulate_cut", False))
        if "chk_mesh_while_playing" in ids:
            ids.chk_mesh_while_playing.active = bool(settings.get("mesh_while_playing", False))
        ids.spn_voxel_resolution.text = self._label_for_value(
            self._voxel_resolution_pairs,
            settings.get("voxel_resolution", DEFAULT_VOXEL_RESOLUTION),
        )
        ids.spn_checkpoint_level.text = self._label_for_value(
            self._checkpoint_level_pairs,
            settings.get("checkpoint_level", DEFAULT_CHECKPOINT_LEVEL),
        )
        if "spn_carver_mode" in ids:
            ids.spn_carver_mode.text = self._label_for_value(
                self._carver_mode_pairs,
                normalize_carver_mode(settings.get("carver_mode", DEFAULT_CARVER_MODE)),
            )
        if "spn_material" in ids:
            ids.spn_material.text = self._label_for_value(
                self._material_pairs,
                normalize_stock_material(settings.get("material", DEFAULT_MATERIAL)),
            )
        self._refresh_carver_spinner_options()
        self._refresh_resolution_spinner_labels()

    def _corner_from_ui(self) -> str:
        text = self.ids.spn_corner.text
        for lab, val in self._corner_pairs:
            if lab == text:
                return val
        return CORNER_LC if getattr(self, "rotary_mode", False) else CORNER_BL

    def _z_from_ui(self) -> str:
        text = self.ids.spn_z_ref.text
        for lab, val in self._z_pairs:
            if lab == text:
                return val
        return Z_TOP

    def _voxel_resolution_from_ui(self) -> str:
        text = self.ids.spn_voxel_resolution.text
        for lab, val in self._voxel_resolution_pairs:
            if lab == text:
                return val
        return DEFAULT_VOXEL_RESOLUTION

    def _checkpoint_level_from_ui(self) -> str:
        text = self.ids.spn_checkpoint_level.text
        for lab, val in self._checkpoint_level_pairs:
            if lab == text:
                return val
        return DEFAULT_CHECKPOINT_LEVEL

    def _carver_mode_from_ui(self) -> str:
        if "spn_carver_mode" not in self.ids:
            return DEFAULT_CARVER_MODE
        text = self.ids.spn_carver_mode.text
        for lab, val in self._carver_mode_pairs:
            if lab == text:
                return val
        # Stale "Auto (...)" caption after the recommended backend changed.
        if (text or "").startswith(tr._("Auto")):
            return MODE_AUTO
        return DEFAULT_CARVER_MODE

    def _material_from_ui(self) -> str:
        if "spn_material" not in self.ids:
            return DEFAULT_MATERIAL
        text = self.ids.spn_material.text
        for lab, val in self._material_pairs:
            if lab == text:
                return val
        return DEFAULT_MATERIAL

    def _on_carver_mode_text(self, *_args) -> None:
        self._refresh_resolution_spinner_labels()

    def _viewer_tools(self):
        """Tool table and unit scale from the loaded file, if any."""
        app = App.get_running_app()
        if app is None or getattr(app, "root", None) is None:
            return None, 1.0
        viewer = getattr(app.root, "gcode_viewer", None)
        if viewer is None:
            return None, 1.0
        return (
            getattr(viewer, "tool_table", None),
            float(getattr(viewer, "tool_unit_scale", 1.0) or 1.0),
        )

    def read_settings_from_ui(self) -> dict:
        height = _parse_positive_float(self.ids.txt_height.text, tr._("Height"))
        kind = self._shape_kind_from_ui()
        if kind == RotaryCylindricalStock.kind:
            diameter = _parse_positive_float(self.ids.txt_width.text, tr._("Diameter"))
            shape = RotaryCylindricalStock(diameter_mm=diameter, length_mm=height)
        elif kind == "cylindrical":
            diameter = _parse_positive_float(self.ids.txt_width.text, tr._("Diameter"))
            shape = CylindricalStock(diameter_mm=diameter, height_mm=height)
        else:
            width = _parse_positive_float(self.ids.txt_width.text, tr._("Width"))
            length = _parse_positive_float(self.ids.txt_length.text, tr._("Length"))
            shape = RectangularStock(width_mm=width, length_mm=length, height_mm=height)
        z_ref = Z_CENTER if getattr(self, "rotary_mode", False) else self._z_from_ui()
        origin = StockOrigin(
            xy_corner=self._corner_from_ui(),
            z_reference=z_ref,
            offset_x_mm=_parse_finite_float(self.ids.txt_offset_x.text, tr._("Offset X")),
            offset_y_mm=_parse_finite_float(self.ids.txt_offset_y.text, tr._("Offset Y")),
            offset_z_mm=_parse_finite_float(self.ids.txt_offset_z.text, tr._("Offset Z")),
        )
        simulate = bool(self.ids.chk_simulate.active) and self.simulation_available
        mesh_while_playing = False
        if "chk_mesh_while_playing" in self.ids:
            mesh_while_playing = bool(self.ids.chk_mesh_while_playing.active)
        return {
            "shape": shape.to_dict(),
            "origin": origin.to_dict(),
            "show_stock": bool(self.ids.chk_show_stock.active),
            "simulate_cut": simulate,
            "mesh_while_playing": mesh_while_playing,
            "voxel_resolution": self._voxel_resolution_from_ui(),
            "checkpoint_level": self._checkpoint_level_from_ui(),
            "carver_mode": self._carver_mode_from_ui(),
            "material": self._material_from_ui(),
        }

    def on_apply_and_close(self):
        try:
            settings = self.read_settings_from_ui()
        except (TypeError, ValueError) as exc:
            app = App.get_running_app()
            if app is not None and getattr(app, "root", None) is not None:
                app.root.show_message_popup(str(exc), False)
            return
        app = App.get_running_app()
        applied = False
        if app is not None and getattr(app, "root", None) is not None:
            root = app.root
            if hasattr(root, "apply_stock_settings"):
                applied = bool(root.apply_stock_settings(settings))
        if not applied:
            if app is not None and getattr(app, "root", None) is not None:
                app.root.show_message_popup(tr._("Failed to apply stock settings."), False)
            return
        self._settings_snapshot = settings
        self.dismiss()
