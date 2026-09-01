"""Unit tests for StockSettingsPopup session reset (no Kivy widget tree)."""

import pytest

from carveracontroller.addons.stock.ui.StockSettingsPopup import (
    StockSettingsPopup,
    _deref_widget,
    _parse_finite_float,
    _parse_positive_float,
    _rotary_x_end_pairs,
    _shape_kind_pairs,
    _stock_corner_pairs,
    _z_reference_pairs,
)


def test_reset_for_loaded_file_uses_snapshot_not_ui():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "rectangular", "width_mm": 150, "length_mm": 80, "height_mm": 20},
        "origin": {
            "xy_corner": "BL",
            "z_reference": "top",
            "offset_x_mm": 1.5,
            "offset_y_mm": -2.0,
            "offset_z_mm": 0.25,
        },
        "show_stock": True,
        "simulate_cut": True,
        "mesh_while_playing": False,
        "voxel_resolution": "high",
        "checkpoint_level": "medium",
        "carver_mode": "voxel",
        "material": "pcb",
    }
    popup._settings_snapshot = dict(custom)
    written = []
    popup._write_settings_to_ui = lambda s: written.append(dict(s))

    out = popup.reset_for_loaded_file()

    assert out["shape"]["width_mm"] == 150
    assert out["origin"]["xy_corner"] == "BL"
    assert out["origin"]["offset_x_mm"] == 1.5
    assert out["origin"]["offset_y_mm"] == -2.0
    assert out["origin"]["offset_z_mm"] == 0.25
    assert out["voxel_resolution"] == "high"
    assert out["checkpoint_level"] == "medium"
    assert out["carver_mode"] == "voxel"
    assert out["material"] == "pcb"
    assert out["show_stock"] is False
    assert out["simulate_cut"] is False
    assert out["mesh_while_playing"] is False
    assert popup._settings_snapshot == out
    assert written == [out]


def test_reset_for_loaded_file_defaults_missing_material_to_beige():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "rectangular", "width_mm": 50, "length_mm": 40, "height_mm": 5},
        "origin": {"xy_corner": "BL", "z_reference": "top"},
        "show_stock": True,
        "simulate_cut": True,
    }
    popup._settings_snapshot = dict(custom)
    popup._write_settings_to_ui = lambda _s: None

    out = popup.reset_for_loaded_file()

    assert out["material"] == "beige"
    assert out["show_stock"] is False


def test_carver_mode_from_settings_defaults_auto():
    from carveracontroller.addons.stock.stock_defaults import (
        carver_mode_from_settings,
        default_settings,
    )

    assert default_settings()["carver_mode"] == "auto"
    assert carver_mode_from_settings({}) == "auto"
    assert carver_mode_from_settings({"carver_mode": "heightmap"}) == "heightmap"
    assert carver_mode_from_settings({"carver_mode": "NOPE"}) == "auto"


def test_material_from_settings_defaults_beige():
    from carveracontroller.addons.stock.stock_defaults import default_settings, material_from_settings

    assert default_settings()["material"] == "beige"
    assert material_from_settings({}) == "beige"
    assert material_from_settings({"material": "aluminum"}) == "aluminum"
    assert material_from_settings({"material": "NOPE"}) == "beige"


def test_auto_carver_label_includes_backend():
    from carveracontroller.addons.stock.simulator.carver_select import (
        BACKEND_CYLINDRICAL,
        BACKEND_HEIGHTMAP,
        BACKEND_VOXEL,
    )
    from carveracontroller.addons.stock.ui.StockSettingsPopup import _auto_carver_label

    assert _auto_carver_label(BACKEND_HEIGHTMAP) == "Auto (heightmap)"
    assert _auto_carver_label(BACKEND_CYLINDRICAL) == "Auto (cylindrical)"
    assert _auto_carver_label(BACKEND_VOXEL) == "Auto (voxels)"
    assert _auto_carver_label(None) == "Auto"


def test_material_pairs_cover_known_presets():
    from carveracontroller.addons.stock.stock_material import KNOWN_MATERIALS
    from carveracontroller.addons.stock.ui.StockSettingsPopup import _material_pairs

    pairs = _material_pairs()
    values = [val for _lab, val in pairs]
    assert values == list(KNOWN_MATERIALS)
    assert pairs[0] == ("Default", "beige")
    assert [lab for lab, _val in pairs] == [
        "Default",
        "PCB",
        "Wood",
        "Acrylic",
        "Bi-color acrylic",
        "Aluminum",
        "Copper",
    ]
    assert ("PCB", "pcb") in pairs


def test_carver_spinner_filters_incompatible_modes():
    """3-axis jobs must not offer cylindrical; 4-axis jobs must not offer heightmap."""
    from carveracontroller.addons.stock.simulator.carver_select import (
        MODE_AUTO,
        MODE_CYLINDRICAL,
        MODE_HEIGHTMAP,
        MODE_VOXEL,
    )
    from carveracontroller.addons.stock.ui.StockSettingsPopup import (
        StockSettingsPopup,
        _carver_mode_pairs,
    )

    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.rotary_mode = False
    popup.simulation_available = True
    popup._carver_mode_pairs = _carver_mode_pairs()
    popup._voxel_resolution_pairs = [("Low", "low")]
    spinner = type("S", (), {"values": [], "text": ""})()
    popup.ids = {"spn_carver_mode": spinner}
    popup._viewer_tools = lambda: (None, 1.0)

    popup._refresh_carver_spinner_options()
    values = set(spinner.values)
    assert any("Auto" in v or "auto" in v.lower() for v in values) or MODE_AUTO in [
        val for lab, val in _carver_mode_pairs() if lab in values
    ]
    labels = list(spinner.values)
    assert "Auto (heightmap)" in labels
    assert spinner.text == "Auto (heightmap)"
    assert not any("Cylindrical" in lab for lab in labels)
    assert any("Heightmap" in lab for lab in labels)
    assert any("Voxel" in lab for lab in labels)
    assert popup._carver_mode_from_ui() == MODE_AUTO

    popup.rotary_mode = True
    spinner.text = ""
    popup._refresh_carver_spinner_options()
    labels = list(spinner.values)
    assert "Auto (cylindrical)" in labels
    assert spinner.text == "Auto (cylindrical)"
    assert any("Cylindrical" in lab for lab in labels)
    assert not any("Heightmap" in lab for lab in labels)
    assert MODE_HEIGHTMAP not in {val for lab, val in popup._carver_mode_pairs if lab in labels}
    assert MODE_CYLINDRICAL in {val for lab, val in popup._carver_mode_pairs if lab in labels}
    assert MODE_VOXEL in {val for lab, val in popup._carver_mode_pairs if lab in labels}

    popup.has_off_axis_y = True
    spinner.text = ""
    popup._refresh_carver_spinner_options()
    labels = list(spinner.values)
    assert "Auto (voxels)" in labels
    assert spinner.text == "Auto (voxels)"
    assert any("Cylindrical" in lab for lab in labels)
    assert not any("Heightmap" in lab for lab in labels)


def test_reset_for_loaded_file_preserves_cylindrical_shape():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "cylindrical", "diameter_mm": 75, "height_mm": 15},
        "origin": {"xy_corner": "center", "z_reference": "bottom"},
        "show_stock": True,
        "simulate_cut": True,
        "voxel_resolution": "medium",
        "checkpoint_level": "high",
    }
    popup._settings_snapshot = dict(custom)
    written = []
    popup._write_settings_to_ui = lambda s: written.append(dict(s))

    out = popup.reset_for_loaded_file()

    assert out["shape"]["kind"] == "cylindrical"
    assert out["shape"]["diameter_mm"] == 75
    assert out["shape"]["height_mm"] == 15
    assert out["show_stock"] is False
    assert out["simulate_cut"] is False
    assert written == [out]


def test_reset_for_loaded_file_preserves_mesh_while_playing():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "rectangular", "width_mm": 50, "length_mm": 40, "height_mm": 5},
        "origin": {"xy_corner": "BL", "z_reference": "top"},
        "show_stock": True,
        "simulate_cut": True,
        "mesh_while_playing": True,
        "voxel_resolution": "low",
        "checkpoint_level": "low",
    }
    popup._settings_snapshot = dict(custom)
    popup._write_settings_to_ui = lambda _s: None

    out = popup.reset_for_loaded_file()

    assert out["mesh_while_playing"] is True
    assert out["show_stock"] is False
    assert out["simulate_cut"] is False


def test_reset_for_loaded_file_when_toggles_already_off():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "rectangular", "width_mm": 50, "length_mm": 40, "height_mm": 5},
        "origin": {"xy_corner": "TR", "z_reference": "bottom"},
        "show_stock": False,
        "simulate_cut": False,
        "voxel_resolution": "low",
        "checkpoint_level": "low",
    }
    popup._settings_snapshot = dict(custom)
    written = []
    popup._write_settings_to_ui = lambda s: written.append(dict(s))

    out = popup.reset_for_loaded_file()

    assert out["shape"]["length_mm"] == 40
    assert out["show_stock"] is False
    assert out["simulate_cut"] is False
    assert written == [out]
    assert popup._settings_snapshot == out


def test_reset_for_loaded_file_overwrites_shape_and_origin():
    from carveracontroller.addons.stock.stock_origin import StockOrigin
    from carveracontroller.addons.stock.stock_shape import RectangularStock

    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "cylindrical", "diameter_mm": 75, "height_mm": 15},
        "origin": {"xy_corner": "center", "z_reference": "bottom", "offset_x_mm": 9.0},
        "show_stock": True,
        "simulate_cut": True,
        "mesh_while_playing": True,
        "voxel_resolution": "high",
        "checkpoint_level": "medium",
    }
    popup._settings_snapshot = dict(custom)
    written = []
    popup._write_settings_to_ui = lambda s: written.append(dict(s))

    shape = RectangularStock(width_mm=100.0, length_mm=50.0, height_mm=10.0)
    origin = StockOrigin(xy_corner="bl", z_reference="top", offset_x_mm=0.0, offset_y_mm=1.5)
    out = popup.reset_for_loaded_file(shape=shape, origin=origin)

    assert out["shape"]["kind"] == "rectangular"
    assert out["shape"]["width_mm"] == 100.0
    assert out["shape"]["length_mm"] == 50.0
    assert out["origin"]["xy_corner"] == "bl"
    assert out["origin"]["z_reference"] == "top"
    assert out["origin"]["offset_y_mm"] == 1.5
    assert out["voxel_resolution"] == "high"
    assert out["checkpoint_level"] == "medium"
    assert out["mesh_while_playing"] is True
    assert out["show_stock"] is False
    assert out["simulate_cut"] is False
    assert written == [out]
    assert popup._settings_snapshot == out


def test_reset_for_loaded_file_can_show_stock_without_simulation():
    from carveracontroller.addons.stock.stock_origin import StockOrigin
    from carveracontroller.addons.stock.stock_shape import RectangularStock

    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    custom = {
        "shape": {"kind": "cylindrical", "diameter_mm": 75, "height_mm": 15},
        "origin": {"xy_corner": "center", "z_reference": "bottom", "offset_x_mm": 9.0},
        "show_stock": False,
        "simulate_cut": True,
        "mesh_while_playing": True,
        "voxel_resolution": "high",
        "checkpoint_level": "medium",
    }
    popup._settings_snapshot = dict(custom)
    written = []
    popup._write_settings_to_ui = lambda s: written.append(dict(s))

    shape = RectangularStock(width_mm=100.0, length_mm=50.0, height_mm=10.0)
    origin = StockOrigin(xy_corner="bl", z_reference="top")
    out = popup.reset_for_loaded_file(shape=shape, origin=origin, show_stock=True)

    assert out["show_stock"] is True
    assert out["simulate_cut"] is False
    assert written == [out]
    assert popup._settings_snapshot == out


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "Infinity", "1e999"])
def test_parse_positive_float_rejects_non_finite(text):
    with pytest.raises(ValueError, match="finite positive"):
        _parse_positive_float(text, "Width")


def test_parse_positive_float_rejects_non_positive():
    with pytest.raises(ValueError, match="finite positive"):
        _parse_positive_float("0", "Width")
    with pytest.raises(ValueError, match="finite positive"):
        _parse_positive_float("-1", "Width")


def test_parse_positive_float_accepts_normal_values():
    assert _parse_positive_float("12.5", "Width") == 12.5
    assert _parse_positive_float("1,5", "Width") == 1.5


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "Infinity", "1e999"])
def test_parse_finite_float_rejects_non_finite(text):
    with pytest.raises(ValueError, match="finite number"):
        _parse_finite_float(text, "Offset X")


def test_parse_finite_float_accepts_zero_and_negative():
    assert _parse_finite_float("0", "Offset X") == 0.0
    assert _parse_finite_float("-3.25", "Offset Y") == -3.25
    assert _parse_finite_float("1,5", "Offset Z") == 1.5


def test_parse_finite_float_rejects_empty():
    with pytest.raises(ValueError, match="required"):
        _parse_finite_float("  ", "Offset X")


class _ChildList(list):
    """List that mimics Kivy ``children`` membership for remove/insert tests."""


class _RowStub:
    def __init__(self):
        self.parent = None
        self.height = 40
        self.opacity = 1
        self.disabled = False


class _FormStub:
    def __init__(self, children):
        self.children = _ChildList(children)

    def remove_widget(self, child):
        self.children.remove(child)
        child.parent = None

    def add_widget(self, child, index=0):
        self.children.insert(index, child)
        child.parent = self


def test_update_dimension_field_visibility_removes_length_for_cylinder():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup._shape_pairs = [("Rectangular", "rectangular"), ("Cylinder", "cylindrical")]
    popup._fit_event = None
    popup._schedule_fit_popup_height = lambda *_a: None

    row_length = _RowStub()
    row_height = _RowStub()
    form = _FormStub([row_height, row_length])
    row_length.parent = form
    row_height.parent = form
    txt_length = type("T", (), {"disabled": False})()
    lbl_width = type("L", (), {"text": "Width (mm)"})()
    spn_shape = type("S", (), {"text": "Cylinder"})()

    popup.ids = {
        "dim_form": form,
        "row_length": row_length,
        "row_height": row_height,
        "txt_length": txt_length,
        "lbl_width": lbl_width,
        "spn_shape": spn_shape,
    }

    popup._update_dimension_field_visibility()

    assert row_length not in form.children
    assert row_length.parent is None
    assert lbl_width.text == "Diameter (mm)"
    assert form.children == [row_height]


def test_update_dimension_field_visibility_restores_length_for_rectangular():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup._shape_pairs = [("Rectangular", "rectangular"), ("Cylinder", "cylindrical")]
    popup._fit_event = None
    popup._schedule_fit_popup_height = lambda *_a: None

    row_length = _RowStub()
    row_height = _RowStub()
    form = _FormStub([row_height])
    row_height.parent = form
    txt_length = type("T", (), {"disabled": True})()
    lbl_width = type("L", (), {"text": "Diameter (mm)"})()
    spn_shape = type("S", (), {"text": "Rectangular"})()

    popup.ids = {
        "dim_form": form,
        "row_length": row_length,
        "row_height": row_height,
        "txt_length": txt_length,
        "lbl_width": lbl_width,
        "spn_shape": spn_shape,
    }

    popup._update_dimension_field_visibility()

    assert row_length in form.children
    assert form.children.index(row_length) == form.children.index(row_height) + 1
    assert lbl_width.text == "Width (mm)"


class _FieldStub:
    def __init__(self, text="", *, disabled=False, active=False):
        self.text = text
        self.disabled = disabled
        self.active = active
        self.values = []


class _WeakProxyStub:
    """Stand-in for Kivy ``ids`` WeakProxy: getattr/setattr go through ``__self__``."""

    def __init__(self, obj):
        object.__setattr__(self, "_obj", obj)

    @property
    def __self__(self):
        obj = object.__getattribute__(self, "_obj")
        if obj is None:
            raise ReferenceError("weakly-referenced object no longer exists")
        return obj

    def __getattr__(self, name):
        return getattr(self.__self__, name)

    def __setattr__(self, name, value):
        setattr(self.__self__, name, value)


def test_deref_widget_unwraps_self():
    real = _FieldStub("axis")
    proxy = _WeakProxyStub(real)
    assert _deref_widget(proxy) is real
    assert _deref_widget(real) is real
    object.__setattr__(proxy, "_obj", None)
    assert _deref_widget(proxy) is None


def test_pin_detachable_rows_stores_row_referent_not_proxy():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    real = _RowStub()
    popup.ids = {"row_z_ref": _WeakProxyStub(real), "row_length": _RowStub()}
    popup._pin_detachable_rows()
    assert popup._pinned_row_z_ref is real
    object.__setattr__(popup.ids["row_z_ref"], "_obj", None)
    assert popup._row("row_z_ref") is real


def test_write_settings_skips_detached_z_ref_spinner():
    """Dismiss must not touch Origin Z after rotary mode has removed that row."""
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.rotary_mode = True
    popup._shape_pairs = [("Rectangular", "rectangular"), ("Cylinder", "rotary_cylindrical")]
    popup._corner_pairs = [("X min (left end)", "BL")]
    popup._z_pairs = [("Axis center (Z0 = A axis)", "center")]
    popup._voxel_resolution_pairs = [("Low", "low")]
    popup._checkpoint_level_pairs = [("Low", "low")]
    popup._fit_event = None
    popup._schedule_fit_popup_height = lambda *_a: None

    row_z_ref = _RowStub()
    row_corner = _RowStub()
    row_height = _RowStub()
    form = _FormStub([row_height, row_z_ref, row_corner])
    row_z_ref.parent = form
    row_corner.parent = form
    row_height.parent = form
    spn_z_ref = _FieldStub("Top")
    proxy = _WeakProxyStub(spn_z_ref)
    popup.ids = {
        "dim_form": form,
        "row_z_ref": row_z_ref,
        "row_corner": row_corner,
        "row_height": row_height,
        "lbl_corner": _FieldStub("WCS origin"),
        "txt_width": _FieldStub("50"),
        "txt_height": _FieldStub("10"),
        "txt_offset_x": _FieldStub("0"),
        "txt_offset_y": _FieldStub("0"),
        "txt_offset_z": _FieldStub("0"),
        "spn_shape": _FieldStub("Cylinder"),
        "spn_corner": _FieldStub("X min (left end)"),
        "spn_z_ref": proxy,
        "spn_voxel_resolution": _FieldStub("Low"),
        "spn_checkpoint_level": _FieldStub("Low"),
        "chk_show_stock": _FieldStub(active=False),
        "chk_simulate": _FieldStub(active=False),
        "lbl_width": _FieldStub("Width (mm)"),
        "lbl_height": _FieldStub("Height (mm)"),
    }
    popup._pinned_row_z_ref = row_z_ref

    popup._update_rotary_origin_visibility()
    assert row_z_ref not in form.children
    object.__setattr__(proxy, "_obj", None)

    popup._write_settings_to_ui(
        {
            "shape": {"kind": "rotary_cylindrical", "diameter_mm": 44, "length_mm": 70},
            "origin": {"xy_corner": "BL", "z_reference": "center"},
            "show_stock": False,
            "simulate_cut": False,
            "voxel_resolution": "low",
            "checkpoint_level": "low",
        }
    )

    assert spn_z_ref.text == "Top"
    assert popup.ids["txt_width"].text == "44"
    assert popup.ids["txt_height"].text == "70"


def test_write_settings_skips_detached_length_field():
    """Dismiss must not touch Length after cylinder mode has removed that row."""
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.rotary_mode = False
    popup._shape_pairs = [("Rectangular", "rectangular"), ("Cylinder", "cylindrical")]
    popup._corner_pairs = [("BL", "BL")]
    popup._z_pairs = [("Top", "top")]
    popup._voxel_resolution_pairs = [("Low", "low")]
    popup._checkpoint_level_pairs = [("Low", "low")]
    popup._fit_event = None
    popup._schedule_fit_popup_height = lambda *_a: None

    row_length = _RowStub()
    row_height = _RowStub()
    row_z_ref = _RowStub()
    form = _FormStub([row_height, row_length, row_z_ref])
    row_length.parent = form
    row_height.parent = form
    row_z_ref.parent = form
    txt_length = _FieldStub("100")
    popup.ids = {
        "dim_form": form,
        "row_length": row_length,
        "row_height": row_height,
        "row_z_ref": row_z_ref,
        "row_corner": _RowStub(),
        "txt_length": txt_length,
        "txt_width": _FieldStub("50"),
        "txt_height": _FieldStub("10"),
        "txt_offset_x": _FieldStub("0"),
        "txt_offset_y": _FieldStub("0"),
        "txt_offset_z": _FieldStub("0"),
        "spn_shape": _FieldStub("Cylinder"),
        "spn_corner": _FieldStub("BL"),
        "spn_z_ref": _FieldStub("Top"),
        "spn_voxel_resolution": _FieldStub("Low"),
        "spn_checkpoint_level": _FieldStub("Low"),
        "chk_show_stock": _FieldStub(active=False),
        "chk_simulate": _FieldStub(active=False),
        "lbl_width": _FieldStub("Width (mm)"),
        "lbl_height": _FieldStub("Height (mm)"),
        "lbl_corner": _FieldStub("WCS origin"),
    }
    popup._pinned_row_length = row_length
    popup._pinned_row_z_ref = row_z_ref

    popup._update_dimension_field_visibility()
    assert row_length not in form.children

    popup._write_settings_to_ui(
        {
            "shape": {"kind": "cylindrical", "diameter_mm": 20, "height_mm": 40},
            "origin": {"xy_corner": "BL", "z_reference": "top"},
            "show_stock": False,
            "simulate_cut": False,
            "voxel_resolution": "low",
            "checkpoint_level": "low",
        }
    )

    assert txt_length.text == "100"
    assert popup.ids["txt_height"].text == "40"
    assert popup.ids["txt_width"].text == "20"


def test_update_rotary_origin_visibility_removes_z_ref_row():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.rotary_mode = True
    popup._fit_event = None
    popup._schedule_fit_popup_height = lambda *_a: None

    row_z_ref = _RowStub()
    row_corner = _RowStub()
    form = _FormStub([row_z_ref, row_corner])
    row_z_ref.parent = form
    row_corner.parent = form
    lbl_corner = _FieldStub("WCS origin")
    popup.ids = {
        "dim_form": form,
        "row_z_ref": row_z_ref,
        "row_corner": row_corner,
        "lbl_corner": lbl_corner,
        "spn_z_ref": _FieldStub("Top"),
    }

    popup._update_rotary_origin_visibility()

    assert row_z_ref not in form.children
    assert lbl_corner.text == "Origin X"


def test_shape_kind_pairs_rotary_maps_cylinder_to_x_axis_bar():
    mill_kinds = [val for _lab, val in _shape_kind_pairs(rotary=False)]
    rotary_kinds = [val for _lab, val in _shape_kind_pairs(rotary=True)]
    assert mill_kinds == ["rectangular", "cylindrical"]
    assert rotary_kinds == ["rectangular", "rotary_cylindrical"]


class _SizedStub:
    def __init__(self, height: float, **extra):
        self.height = height
        for key, value in extra.items():
            setattr(self, key, value)


def test_fit_popup_height_clamps_to_window_fraction(monkeypatch):
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup._fit_event = None
    popup.ids = {
        "content_box": _SizedStub(0.0, padding=(16, 16, 16, 16), spacing=10),
        "form_body": _SizedStub(500.0, minimum_height=500.0),
        "lbl_title": _SizedStub(36.0),
        "lbl_help": _SizedStub(48.0),
        "btn_row": _SizedStub(44.0),
    }
    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.Window",
        type("W", (), {"height": 400.0}),
    )
    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.dp",
        lambda value: float(value),
    )

    popup._fit_popup_height()

    assert popup.height == pytest.approx(400.0 * 0.72)


def test_fit_popup_height_uses_content_when_short(monkeypatch):
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup._fit_event = None
    popup.ids = {
        "content_box": _SizedStub(0.0, padding=(16, 16, 16, 16), spacing=10),
        "form_body": _SizedStub(200.0, minimum_height=200.0),
        "lbl_title": _SizedStub(36.0),
        "lbl_help": _SizedStub(48.0),
        "btn_row": _SizedStub(44.0),
    }
    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.Window",
        type("W", (), {"height": 900.0}),
    )
    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.dp",
        lambda value: float(value),
    )

    popup._fit_popup_height()

    # padding 32 + title 36 + help 48 + buttons 44 + 3*spacing 30 + form 200
    assert popup.height == pytest.approx(390.0)


def test_on_apply_and_close_commits_snapshot_only_on_success(monkeypatch):
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    old = {
        "shape": {"kind": "rectangular", "width_mm": 50, "length_mm": 40, "height_mm": 5},
        "origin": {"xy_corner": "bl", "z_reference": "top"},
        "show_stock": False,
        "simulate_cut": False,
        "voxel_resolution": "low",
        "checkpoint_level": "low",
    }
    new = dict(old)
    new["show_stock"] = True
    popup._settings_snapshot = dict(old)
    popup.read_settings_from_ui = lambda: dict(new)
    dismissed = []
    popup.dismiss = lambda: dismissed.append(True)

    class Root:
        def __init__(self):
            self.messages = []
            self.apply_result = False

        def apply_stock_settings(self, settings):
            return self.apply_result

        def show_message_popup(self, message, ok):
            self.messages.append((message, ok))

    root = Root()
    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.App.get_running_app",
        lambda: type("A", (), {"root": root})(),
    )

    root.apply_result = False
    popup.on_apply_and_close()
    assert popup._settings_snapshot == old
    assert dismissed == []
    assert root.messages

    root.messages.clear()
    root.apply_result = True
    popup.on_apply_and_close()
    assert popup._settings_snapshot == new
    assert dismissed == [True]
    assert root.messages == []


def test_on_apply_and_close_keeps_snapshot_when_viewer_missing(monkeypatch):
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    old = {
        "shape": {"kind": "rectangular", "width_mm": 50, "length_mm": 40, "height_mm": 5},
        "origin": {"xy_corner": "bl", "z_reference": "top"},
        "show_stock": False,
        "simulate_cut": False,
        "voxel_resolution": "low",
        "checkpoint_level": "low",
    }
    popup._settings_snapshot = dict(old)
    popup.read_settings_from_ui = lambda: {**old, "show_stock": True}
    dismissed = []
    popup.dismiss = lambda: dismissed.append(True)

    monkeypatch.setattr(
        "carveracontroller.addons.stock.ui.StockSettingsPopup.App.get_running_app",
        lambda: None,
    )

    popup.on_apply_and_close()
    assert popup._settings_snapshot == old
    assert dismissed == []


def test_voxel_resolution_pairs_without_bounds_omit_precision():
    from carveracontroller.addons.stock.simulator.carver_select import BACKEND_HEIGHTMAP
    from carveracontroller.addons.stock.ui.StockSettingsPopup import _voxel_resolution_pairs

    pairs = _voxel_resolution_pairs(BACKEND_HEIGHTMAP)
    labels = [lab for lab, _ in pairs]
    assert labels == ["Low (faster)", "Medium", "High (finer)"]
    assert all("/ axis" not in lab for lab in labels)


def test_voxel_resolution_pairs_show_actual_cell_size():
    from carveracontroller.addons.stock.simulator.carver_select import BACKEND_HEIGHTMAP, BACKEND_VOXEL
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.ui.StockSettingsPopup import _voxel_resolution_pairs

    bounds = StockBounds(0, 0, 0, 42, 42, 1)
    hm = [lab for lab, _ in _voxel_resolution_pairs(BACKEND_HEIGHTMAP, bounds)]
    assert "0.21 mm/cell" in hm[0]
    assert "0.084 mm/cell" in hm[1]
    assert "0.05 mm/cell" in hm[2]
    assert hm[1] != hm[2]
    assert all("/ axis" not in lab for lab in hm)

    vx = [lab for lab, _ in _voxel_resolution_pairs(BACKEND_VOXEL, bounds)]
    assert "mm/voxel" in vx[0]
    assert "/ axis" not in vx[0]


def test_voxel_resolution_pairs_cylindrical_names_od():
    from carveracontroller.addons.stock.simulator.carver_select import BACKEND_CYLINDRICAL
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.ui.StockSettingsPopup import _voxel_resolution_pairs

    bounds = StockBounds(0, -25, -25, 80, 25, 25)
    cyl = [lab for lab, _ in _voxel_resolution_pairs(BACKEND_CYLINDRICAL, bounds)]
    assert "mm along X" in cyl[0]
    assert "mm at OD" in cyl[0]
    assert "mm/cell" not in cyl[0]
    assert "Low (~" in cyl[0] and "faster" in cyl[0]


def test_bounds_for_resolution_preview_from_form():
    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.rotary_mode = False
    popup._shape_pairs = [("Rectangular", "rectangular"), ("Cylinder", "cylindrical")]
    popup.ids = {
        "txt_width": _FieldStub("42"),
        "txt_length": _FieldStub("42"),
        "txt_height": _FieldStub("1"),
        "spn_shape": _FieldStub("Rectangular"),
    }
    bounds = popup._bounds_for_resolution_preview()
    assert bounds is not None
    assert bounds.size == (42.0, 42.0, 1.0)

    popup.ids["txt_width"].text = ""
    assert popup._bounds_for_resolution_preview() is None


def test_mill_origin_pairs_cover_twenty_seven_points():
    from carveracontroller.addons.stock.stock_origin import (
        CORNER_BC,
        CORNER_BL,
        CORNER_FC,
        CORNER_LC,
        CORNER_RC,
        Z_BOTTOM,
        Z_CENTER,
        Z_TOP,
    )

    corners = {val: lab for lab, val in _stock_corner_pairs()}
    assert corners[CORNER_BL] == "Front-left"
    assert corners[CORNER_LC] == "Center-left"
    assert corners[CORNER_FC] == "Front-center"
    assert corners[CORNER_RC] == "Center-right"
    assert corners[CORNER_BC] == "Back-center"
    assert len(corners) == 9

    z_vals = {val: lab for lab, val in _z_reference_pairs()}
    assert z_vals[Z_TOP]
    assert "Center of stock" in z_vals[Z_CENTER]
    assert z_vals[Z_BOTTOM]


def test_rotary_x_end_pairs_use_left_and_right_center():
    from carveracontroller.addons.stock.stock_origin import CORNER_CENTER, CORNER_LC, CORNER_RC

    values = [val for _lab, val in _rotary_x_end_pairs()]
    assert values == [CORNER_LC, CORNER_RC, CORNER_CENTER]


def test_corner_from_ui_mismatch_falls_back_mill_bl_rotary_lc():
    from carveracontroller.addons.stock.stock_origin import CORNER_BL, CORNER_LC

    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup.ids = {"spn_corner": type("S", (), {"text": "not-a-label"})()}

    popup.rotary_mode = False
    popup._corner_pairs = _stock_corner_pairs()
    assert popup._corner_from_ui() == CORNER_BL

    popup.rotary_mode = True
    popup._corner_pairs = _rotary_x_end_pairs()
    assert popup._corner_from_ui() == CORNER_LC


def test_label_for_value_round_trips_left_center_and_z_center():
    from carveracontroller.addons.stock.stock_origin import CORNER_LC, Z_CENTER

    popup = StockSettingsPopup.__new__(StockSettingsPopup)
    popup._corner_pairs = _stock_corner_pairs()
    popup._z_pairs = _z_reference_pairs()

    corner_label = popup._label_for_value(popup._corner_pairs, CORNER_LC)
    z_label = popup._label_for_value(popup._z_pairs, Z_CENTER)
    assert corner_label == "Center-left"
    assert "Center of stock" in z_label

    popup.ids = {"spn_corner": type("S", (), {"text": corner_label})()}
    popup.rotary_mode = False
    assert popup._corner_from_ui() == CORNER_LC

    popup.ids["spn_z_ref"] = type("S", (), {"text": z_label})()
    assert popup._z_from_ui() == Z_CENTER
