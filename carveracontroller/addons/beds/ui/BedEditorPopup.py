"""Add / modify a single bed."""

from __future__ import annotations

import math
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.beds.catalog import (
    CUSTOM_CATALOG_ID,
    plate_by_id,
    plates_for_machine,
)
from carveracontroller.addons.beds.materials import (
    DEFAULT_MATERIAL,
    KNOWN_MATERIALS,
    normalize_bed_material,
)
from carveracontroller.addons.beds.mesh_loader import read_obj_metadata
from carveracontroller.addons.beds.store import resolve_mesh_path
from carveracontroller.translation import tr
from carveracontroller.ui.LocalFilePicker import open_local_file_picker

CUSTOM_LABEL = "Custom…"


def _parse_finite_float(text: str, label: str) -> float:
    t = (text or "").strip().replace(",", ".")
    if not t:
        raise ValueError(tr._("%s is required") % label)
    value = float(t)
    if not math.isfinite(value):
        raise ValueError(tr._("%s must be a finite number") % label)
    return value


def _format_mm(value: float) -> str:
    v = float(value)
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def _optional_mm_text(value) -> str:
    """Format a millimetre field; ``None`` leaves the input empty (user must type it)."""
    if value is None:
        return ""
    return _format_mm(float(value))


class BedEditorPopup(ModalView):
    """Create or edit one saved bed."""

    title_text = StringProperty("")
    custom_file_hint = StringProperty("")
    thickness_hint = StringProperty("")
    browse_disabled = BooleanProperty(True)

    def __init__(self, **kwargs):
        self._machine = ""
        self._on_save = None
        self._editing_id = None
        self._original_mesh_file = None
        self._pending_custom_src = None
        self._model_pairs: list[tuple[str, str]] = []
        self._material_pairs: list[tuple[str, str]] = []
        self._suppress_model_change = False
        super().__init__(**kwargs)
        self.bind(on_open=self._on_open)

    def _on_open(self, *_args):
        self._fit_popup_height()

    def _fit_popup_height(self, *_args):
        from kivy.core.window import Window

        try:
            body = self.ids.form_body
            extra = dp(16 + 10 + 36 + 8 + 48 + 16)
            wanted = extra + float(body.minimum_height)
            cap = Window.height * 0.78
            self.height = min(max(wanted, dp(280)), cap)
        except Exception:
            self.height = dp(420)

    def open_for_add(self, machine: str, defaults: dict, on_save) -> None:
        self._machine = machine
        self._on_save = on_save
        self._editing_id = None
        self._original_mesh_file = None
        self._pending_custom_src = None
        self.title_text = tr._("Add bed")
        self.open()
        Clock.schedule_once(lambda *_: self._populate(defaults), 0)

    def open_for_modify(self, machine: str, bed: dict, on_save) -> None:
        self._machine = machine
        self._on_save = on_save
        self._editing_id = bed.get("id")
        self._original_mesh_file = bed.get("mesh_file")
        self._pending_custom_src = None
        self.title_text = tr._("Modify bed")
        self.open()
        Clock.schedule_once(lambda *_: self._populate(bed), 0)

    def _populate(self, data: dict) -> None:
        self._model_pairs = [(p.label, p.id) for p in plates_for_machine(self._machine)]
        self._model_pairs.append((tr._(CUSTOM_LABEL), CUSTOM_CATALOG_ID))
        self._material_pairs = [
            (tr._("MDF"), "mdf"),
            (tr._("Aluminum"), "aluminum"),
        ]
        self.ids.spn_model.values = [label for label, _cid in self._model_pairs]
        self.ids.spn_material.values = [label for label, _mid in self._material_pairs]

        catalog_id = data.get("catalog_id") or (self._model_pairs[0][1] if self._model_pairs else CUSTOM_CATALOG_ID)
        self._suppress_model_change = True
        self.ids.ti_name.text = data.get("name") or ""
        self._set_spinner_by_id(self.ids.spn_model, self._model_pairs, catalog_id)
        self._set_spinner_by_id(
            self.ids.spn_material,
            self._material_pairs,
            normalize_bed_material(data.get("material", DEFAULT_MATERIAL)),
        )
        self.ids.txt_mcs_x.text = _format_mm(float(data.get("mcs_x") or 0.0))
        self.ids.txt_mcs_y.text = _format_mm(float(data.get("mcs_y") or 0.0))
        self.ids.txt_mcs_z.text = _optional_mm_text(data.get("mcs_z"))
        self._suppress_model_change = False
        self._sync_custom_ui()
        if catalog_id == CUSTOM_CATALOG_ID:
            mesh_path = resolve_mesh_path(data)
            if mesh_path:
                self.custom_file_hint = os.path.basename(mesh_path)
            elif data.get("mesh_file"):
                self.custom_file_hint = os.path.basename(str(data.get("mesh_file")))
            else:
                self.custom_file_hint = tr._("No file selected")
        self._refresh_thickness_hint()
        self._fit_popup_height()

    def _set_spinner_by_id(self, spinner, pairs, value: str) -> None:
        for label, item_id in pairs:
            if item_id == value:
                spinner.text = label
                return
        spinner.text = pairs[0][0] if pairs else ""

    def _id_from_spinner(self, spinner, pairs) -> str | None:
        text = spinner.text
        for label, item_id in pairs:
            if label == text:
                return item_id
        return pairs[0][1] if pairs else None

    def on_model_selected(self) -> None:
        if self._suppress_model_change:
            return
        catalog_id = self._id_from_spinner(self.ids.spn_model, self._model_pairs)
        self._sync_custom_ui()
        if catalog_id and catalog_id != CUSTOM_CATALOG_ID:
            plate = plate_by_id(catalog_id)
            if plate is not None:
                self._set_spinner_by_id(self.ids.spn_material, self._material_pairs, plate.default_material)
                if not (self.ids.ti_name.text or "").strip():
                    self.ids.ti_name.text = plate.label
        else:
            self._set_spinner_by_id(self.ids.spn_material, self._material_pairs, DEFAULT_MATERIAL)
        self._refresh_thickness_hint()

    def _sync_custom_ui(self) -> None:
        catalog_id = self._id_from_spinner(self.ids.spn_model, self._model_pairs)
        is_custom = catalog_id == CUSTOM_CATALOG_ID
        self.browse_disabled = not is_custom
        if not is_custom:
            self.custom_file_hint = ""
            self._pending_custom_src = None

    def on_browse(self) -> None:
        def on_confirm(popup, dest: str):
            if not dest.lower().endswith(".obj"):
                app = App.get_running_app()
                if app is not None and getattr(app, "root", None) is not None:
                    app.root.show_message_popup(tr._("Please choose a .obj file."), False)
                return
            if not os.path.isfile(dest):
                app = App.get_running_app()
                if app is not None and getattr(app, "root", None) is not None:
                    app.root.show_message_popup(tr._("File not found:\n%s") % dest, False)
                return
            popup.dismiss()
            self._pending_custom_src = dest
            self.custom_file_hint = os.path.basename(dest)
            self._refresh_thickness_hint()

        open_local_file_picker(
            title=tr._("Select bed model"),
            default_name="bed.obj",
            on_confirm=on_confirm,
            confirm_label=tr._("Select"),
            filters=["*.obj"],
        )

    def _thickness_source_path(self) -> str | None:
        catalog_id = self._id_from_spinner(self.ids.spn_model, self._model_pairs)
        if catalog_id == CUSTOM_CATALOG_ID:
            if self._pending_custom_src and os.path.isfile(self._pending_custom_src):
                return self._pending_custom_src
            if self._original_mesh_file:
                return resolve_mesh_path(
                    {
                        "catalog_id": CUSTOM_CATALOG_ID,
                        "mesh_file": self._original_mesh_file,
                    }
                )
            return None
        plate = plate_by_id(catalog_id)
        if plate is None:
            return None
        path = plate.mesh_path()
        return path if os.path.isfile(path) else None

    def _refresh_thickness_hint(self) -> None:
        path = self._thickness_source_path()
        thickness = None
        if path:
            meta = read_obj_metadata(path)
            raw = meta.get("thickness_mm")
            if isinstance(raw, (int, float)):
                thickness = abs(float(raw))
            else:
                bbox_min = meta.get("bbox_min")
                bbox_max = meta.get("bbox_max")
                if isinstance(bbox_min, tuple) and isinstance(bbox_max, tuple):
                    thickness = abs(float(bbox_max[2] - bbox_min[2]))
        origin_txt = tr._("Origin is the front-left top corner (the surface you probe).")
        if thickness and thickness > 0:
            self.thickness_hint = (
                origin_txt
                + " "
                + (
                    tr._("Plate thickness is %s mm, so the bottom sits at Z − %s.")
                    % (_format_mm(thickness), _format_mm(thickness))
                )
            )
        else:
            self.thickness_hint = origin_txt

    def on_cancel(self) -> None:
        self.dismiss()

    def on_save(self) -> None:
        try:
            name = (self.ids.ti_name.text or "").strip()
            if not name:
                raise ValueError(tr._("Name is required"))
            catalog_id = self._id_from_spinner(self.ids.spn_model, self._model_pairs)
            if not catalog_id:
                raise ValueError(tr._("Plate model is required"))
            material = self._id_from_spinner(self.ids.spn_material, self._material_pairs)
            material = normalize_bed_material(material)
            if material not in KNOWN_MATERIALS:
                material = DEFAULT_MATERIAL
            mcs_x = _parse_finite_float(self.ids.txt_mcs_x.text, tr._("Machine X"))
            mcs_y = _parse_finite_float(self.ids.txt_mcs_y.text, tr._("Machine Y"))
            mcs_z = _parse_finite_float(self.ids.txt_mcs_z.text, tr._("Machine Z"))
            if catalog_id == CUSTOM_CATALOG_ID:
                if not self._pending_custom_src and not self._original_mesh_file:
                    raise ValueError(tr._("Choose a custom .obj file."))
        except (TypeError, ValueError) as exc:
            app = App.get_running_app()
            if app is not None and getattr(app, "root", None) is not None:
                app.root.show_message_popup(str(exc), False)
            return

        payload = {
            "id": self._editing_id,
            "name": name,
            "catalog_id": catalog_id,
            "material": material,
            "mcs_x": mcs_x,
            "mcs_y": mcs_y,
            "mcs_z": mcs_z,
            "mesh_file": self._original_mesh_file if catalog_id == CUSTOM_CATALOG_ID else None,
            "custom_src": self._pending_custom_src,
        }
        if callable(self._on_save):
            self._on_save(payload)
        self.dismiss()
