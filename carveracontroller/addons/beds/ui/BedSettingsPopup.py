"""Picker for the bed shown in the G-code viewer."""

from __future__ import annotations

import uuid

from kivy.app import App
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.beds.catalog import (
    CUSTOM_CATALOG_ID,
    is_known_machine,
    plate_by_id,
    plates_for_machine,
)
from carveracontroller.addons.beds.materials import DEFAULT_MATERIAL
from carveracontroller.addons.beds.placement import default_origin_xy
from carveracontroller.addons.beds.store import (
    copy_custom_mesh,
    delete_bed,
    get_bed,
    list_beds,
    load_store,
    replace_custom_mesh,
    save_store,
    selected_id,
    set_selected_id,
    upsert_bed,
)
from carveracontroller.addons.beds.ui.BedEditorPopup import BedEditorPopup
from carveracontroller.translation import tr

NONE_LABEL = "(none)"


def _bed_spinner_label(bed: dict) -> str:
    name = bed.get("name") or tr._("Bed")
    try:
        z_val = float(bed.get("mcs_z") or 0.0)
    except (TypeError, ValueError):
        z_val = 0.0
    z_txt = str(int(z_val)) if z_val == int(z_val) else f"{z_val:g}"
    return f"{name}  (Z={z_txt})"


class BedSettingsPopup(ModalView):
    """Select, add, modify, or delete beds for the connected machine."""

    modify_disabled = BooleanProperty(True)
    delete_disabled = BooleanProperty(True)
    help_text = StringProperty("")

    def __init__(self, **kwargs):
        self._store = load_store()
        self._applied_selected_id = None
        self._pending_selected_id = None
        self._bed_pairs: list[tuple[str, str | None]] = []
        self._editor = BedEditorPopup()
        super().__init__(**kwargs)
        self.help_text = tr._(
            "Choose the current bed for this machine. Position is in machine coordinates, "
            "the viewer places it using the live WCS origin."
        )
        self.bind(on_open=self._on_open, on_dismiss=self._on_dismiss)

    def _machine(self) -> str:
        app = App.get_running_app()
        return (getattr(app, "model", "") or "").strip() if app is not None else ""

    def _on_open(self, *_args):
        self._store = load_store()
        machine = self._machine()
        self._applied_selected_id = selected_id(self._store, machine)
        self._pending_selected_id = self._applied_selected_id
        self._refresh_spinner()
        self._fit_popup_height()

    def _on_dismiss(self, *_args):
        self._write_selection_to_spinner(self._applied_selected_id)
        try:
            App.get_running_app().root.restore_keyboard_jog_control()
        except Exception:
            pass

    def _fit_popup_height(self, *_args):
        from kivy.core.window import Window

        try:
            extra = dp(16 + 10 + 36 + 8 + 48 + 24)
            help_h = float(self.ids.lbl_help.height)
            wanted = extra + help_h + dp(48)
            cap = Window.height * 0.5
            self.height = min(max(wanted, dp(220)), cap)
        except Exception:
            self.height = dp(260)

    def _refresh_spinner(self) -> None:
        machine = self._machine()
        beds = list_beds(self._store, machine)
        self._bed_pairs = [(tr._(NONE_LABEL), None)]
        for bed in beds:
            self._bed_pairs.append((_bed_spinner_label(bed), bed["id"]))
        self.ids.spn_bed.values = [label for label, _bid in self._bed_pairs]
        self._write_selection_to_spinner(self._pending_selected_id)
        self._sync_action_buttons()

    def _write_selection_to_spinner(self, bed_id: str | None) -> None:
        for label, item_id in self._bed_pairs:
            if item_id == bed_id:
                self.ids.spn_bed.text = label
                return
        self.ids.spn_bed.text = self._bed_pairs[0][0] if self._bed_pairs else tr._(NONE_LABEL)

    def _id_from_spinner(self) -> str | None:
        text = self.ids.spn_bed.text
        for label, item_id in self._bed_pairs:
            if label == text:
                return item_id
        return None

    def on_bed_selected(self) -> None:
        self._pending_selected_id = self._id_from_spinner()
        self._sync_action_buttons()

    def _sync_action_buttons(self) -> None:
        has_bed = self._pending_selected_id is not None
        self.modify_disabled = not has_bed
        self.delete_disabled = not has_bed

    def _default_add_values(self) -> dict:
        machine = self._machine()
        plates = plates_for_machine(machine)
        plate = plates[0] if plates else None
        from carveracontroller.CNC import CNC

        x, y = default_origin_xy(
            float(CNC.vars.get("anchor1_x") or 0.0),
            float(CNC.vars.get("anchor1_y") or 0.0),
            float(CNC.vars.get("anchor_width") or 15.0),
        )
        return {
            "name": plate.label if plate is not None else tr._("Bed"),
            "catalog_id": plate.id if plate is not None else CUSTOM_CATALOG_ID,
            "material": plate.default_material if plate is not None else DEFAULT_MATERIAL,
            "mcs_x": x,
            "mcs_y": y,
            "mcs_z": None,
            "mesh_file": None,
        }

    def on_add(self) -> None:
        machine = self._machine()
        if not is_known_machine(machine):
            return
        self._editor.open_for_add(machine, self._default_add_values(), self._on_editor_save_add)

    def on_modify(self) -> None:
        machine = self._machine()
        bed = get_bed(self._store, machine, self._pending_selected_id)
        if bed is None:
            return
        self._editor.open_for_modify(machine, dict(bed), self._on_editor_save_modify)

    def _on_editor_save_add(self, payload: dict) -> None:
        self._commit_editor_payload(payload, is_new=True)

    def _on_editor_save_modify(self, payload: dict) -> None:
        self._commit_editor_payload(payload, is_new=False)

    def _commit_editor_payload(self, payload: dict, is_new: bool) -> None:
        machine = self._machine()
        catalog_id = payload.get("catalog_id")
        mesh_file = payload.get("mesh_file")
        custom_src = payload.get("custom_src")
        try:
            if catalog_id == CUSTOM_CATALOG_ID:
                if custom_src:
                    if is_new or not mesh_file:
                        mesh_file = copy_custom_mesh(custom_src)
                    else:
                        mesh_file = replace_custom_mesh(self._store, mesh_file, custom_src, skip_id=payload.get("id"))
                elif not mesh_file:
                    raise FileNotFoundError(tr._("Choose a custom .obj file."))
            else:
                mesh_file = None
                if plate_by_id(catalog_id) is None:
                    raise ValueError(tr._("Unknown plate model."))
            bed = {
                "id": payload.get("id") or str(uuid.uuid4()),
                "name": payload["name"],
                "catalog_id": catalog_id,
                "mesh_file": mesh_file,
                "material": payload["material"],
                "mcs_x": payload["mcs_x"],
                "mcs_y": payload["mcs_y"],
                "mcs_z": payload["mcs_z"],
            }
            upsert_bed(self._store, machine, bed)
            save_store(self._store)
            self._pending_selected_id = bed["id"]
            self._refresh_spinner()
            self._sync_viewer_if_applied(bed["id"])
        except (OSError, ValueError, FileNotFoundError) as exc:
            app = App.get_running_app()
            if app is not None and getattr(app, "root", None) is not None:
                app.root.show_message_popup(str(exc), False)

    def on_delete(self) -> None:
        machine = self._machine()
        bed = get_bed(self._store, machine, self._pending_selected_id)
        if bed is None:
            return
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        if root is None or not hasattr(root, "confirm_popup"):
            return
        popup = root.confirm_popup
        popup.lb_title.text = tr._("Delete bed")
        popup.lb_content.text = tr._("Delete '%s'?") % (bed.get("name") or "")
        bed_id = bed["id"]

        def confirm():
            self._commit_delete(machine, bed_id)

        popup.confirm = confirm
        popup.cancel = None
        popup.open(root)

    def _commit_delete(self, machine: str, bed_id: str) -> None:
        was_applied = self._applied_selected_id == bed_id
        delete_bed(self._store, machine, bed_id)
        save_store(self._store)
        if self._pending_selected_id == bed_id:
            self._pending_selected_id = None
        if was_applied:
            self._applied_selected_id = None
        self._refresh_spinner()
        if was_applied:
            self._push_bed_to_viewer()

    def _push_bed_to_viewer(self) -> bool:
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        if root is None or not hasattr(root, "apply_bed_settings"):
            return False
        return bool(root.apply_bed_settings())

    def _sync_viewer_if_applied(self, bed_id: str | None) -> None:
        """Refresh the 3D view when the bed currently shown is edited."""
        if bed_id is not None and bed_id == self._applied_selected_id:
            self._push_bed_to_viewer()

    def on_apply_and_close(self) -> None:
        machine = self._machine()
        set_selected_id(self._store, machine, self._id_from_spinner())
        save_store(self._store)
        self._applied_selected_id = selected_id(self._store, machine)
        # apply_bed_settings already shows a specific error if the mesh is missing.
        if not self._push_bed_to_viewer():
            return
        self.dismiss()
