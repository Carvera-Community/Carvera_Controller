"""Persisted per-machine bed list (~/.kivy/beds.json)."""

from __future__ import annotations

import os
import shutil
import uuid
from typing import Any

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils

from .catalog import CUSTOM_CATALOG_ID, KNOWN_MACHINES, plate_by_id
from .materials import DEFAULT_MATERIAL, normalize_bed_material

STORE_FILENAME = "beds.json"
STORE_VERSION = 1
MESHES_SUBDIR = os.path.join("beds", "meshes")


def custom_meshes_dir() -> str:
    return os.path.join(ConfigUtils.CONFIG_DIR, MESHES_SUBDIR)


def _empty_machine() -> dict[str, Any]:
    return {"selected_id": None, "beds": []}


def _empty_store() -> dict[str, Any]:
    return {
        "version": STORE_VERSION,
        "machines": {model: _empty_machine() for model in KNOWN_MACHINES},
    }


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _normalize_bed(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    bed_id = raw.get("id")
    if not isinstance(bed_id, str) or not bed_id.strip():
        bed_id = str(uuid.uuid4())
    catalog_id = raw.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id.strip():
        catalog_id = CUSTOM_CATALOG_ID
    catalog_id = catalog_id.strip()
    mesh_file = raw.get("mesh_file")
    if mesh_file is not None:
        if not isinstance(mesh_file, str) or not mesh_file.strip():
            mesh_file = None
        else:
            mesh_file = os.path.basename(mesh_file.strip())
    if catalog_id != CUSTOM_CATALOG_ID:
        mesh_file = None
        if plate_by_id(catalog_id) is None:
            catalog_id = CUSTOM_CATALOG_ID
    return {
        "id": bed_id.strip(),
        "name": name.strip(),
        "catalog_id": catalog_id,
        "mesh_file": mesh_file,
        "material": normalize_bed_material(raw.get("material", DEFAULT_MATERIAL)),
        "mcs_x": _finite_float(raw.get("mcs_x")),
        "mcs_y": _finite_float(raw.get("mcs_y")),
        "mcs_z": _finite_float(raw.get("mcs_z")),
    }


def _normalize_machine(raw: Any) -> dict[str, Any]:
    out = _empty_machine()
    if not isinstance(raw, dict):
        return out
    beds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("beds") or []:
        bed = _normalize_bed(item)
        if bed is None or bed["id"] in seen:
            continue
        seen.add(bed["id"])
        beds.append(bed)
    out["beds"] = beds
    selected = raw.get("selected_id")
    if isinstance(selected, str) and selected.strip() and selected.strip() in seen:
        out["selected_id"] = selected.strip()
    else:
        out["selected_id"] = None
    return out


def load_store() -> dict[str, Any]:
    raw = ConfigUtils.load_config(STORE_FILENAME)
    store = _empty_store()
    if not isinstance(raw, dict):
        return store
    machines = raw.get("machines")
    if not isinstance(machines, dict):
        return store
    for model in KNOWN_MACHINES:
        store["machines"][model] = _normalize_machine(machines.get(model))
    store["version"] = int(raw.get("version", STORE_VERSION) or STORE_VERSION)
    return store


def save_store(store: dict[str, Any]) -> None:
    payload = _empty_store()
    machines = store.get("machines") if isinstance(store, dict) else {}
    if isinstance(machines, dict):
        for model in KNOWN_MACHINES:
            payload["machines"][model] = _normalize_machine(machines.get(model))
    ConfigUtils.save_config(payload, STORE_FILENAME)


def machine_state(store: dict[str, Any], model: str) -> dict[str, Any]:
    machines = store.setdefault("machines", {})
    key = (model or "").strip()
    if key not in KNOWN_MACHINES:
        return _empty_machine()
    state = machines.get(key)
    if not isinstance(state, dict):
        state = _empty_machine()
        machines[key] = state
    return state


def list_beds(store: dict[str, Any], model: str) -> list[dict[str, Any]]:
    return list(machine_state(store, model).get("beds") or [])


def get_bed(store: dict[str, Any], model: str, bed_id: str | None) -> dict[str, Any] | None:
    if not bed_id:
        return None
    for bed in list_beds(store, model):
        if bed.get("id") == bed_id:
            return bed
    return None


def selected_id(store: dict[str, Any], model: str) -> str | None:
    sid = machine_state(store, model).get("selected_id")
    return sid if isinstance(sid, str) and sid else None


def set_selected_id(store: dict[str, Any], model: str, bed_id: str | None) -> None:
    state = machine_state(store, model)
    if bed_id and get_bed(store, model, bed_id) is not None:
        state["selected_id"] = bed_id
    else:
        state["selected_id"] = None


def upsert_bed(store: dict[str, Any], model: str, bed: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_bed(bed)
    if normalized is None:
        raise ValueError("invalid bed")
    state = machine_state(store, model)
    beds: list[dict[str, Any]] = state.setdefault("beds", [])
    for i, existing in enumerate(beds):
        if existing.get("id") == normalized["id"]:
            old_mesh = existing.get("mesh_file")
            beds[i] = normalized
            if old_mesh and old_mesh != normalized.get("mesh_file"):
                _drop_unreferenced_mesh(store, old_mesh)
            return normalized
    beds.append(normalized)
    return normalized


def _mesh_referenced(store: dict[str, Any], mesh_file: str, skip_id: str | None = None) -> bool:
    if not mesh_file:
        return False
    for model in KNOWN_MACHINES:
        for bed in list_beds(store, model):
            if skip_id and bed.get("id") == skip_id:
                continue
            if bed.get("mesh_file") == mesh_file:
                return True
    return False


def delete_custom_mesh_file(mesh_file: str | None) -> None:
    if not mesh_file:
        return
    path = os.path.join(custom_meshes_dir(), os.path.basename(mesh_file))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _drop_unreferenced_mesh(store: dict[str, Any], mesh_file: str | None, skip_id: str | None = None) -> None:
    if mesh_file and not _mesh_referenced(store, mesh_file, skip_id=skip_id):
        delete_custom_mesh_file(mesh_file)


def delete_bed(store: dict[str, Any], model: str, bed_id: str) -> bool:
    state = machine_state(store, model)
    beds: list[dict[str, Any]] = state.get("beds") or []
    for i, bed in enumerate(beds):
        if bed.get("id") != bed_id:
            continue
        mesh_file = bed.get("mesh_file")
        beds.pop(i)
        if state.get("selected_id") == bed_id:
            state["selected_id"] = None
        _drop_unreferenced_mesh(store, mesh_file)
        return True
    return False


def copy_custom_mesh(src_path: str) -> str:
    """Copy *src_path* into the config mesh folder. Returns the stored filename."""
    if not src_path or not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)
    dest_dir = custom_meshes_dir()
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.obj"
    dest = os.path.join(dest_dir, filename)
    shutil.copy2(src_path, dest)
    return filename


def replace_custom_mesh(
    store: dict[str, Any], old_mesh_file: str | None, src_path: str, skip_id: str | None = None
) -> str:
    """Copy a new custom mesh and drop the previous file when unused."""
    filename = copy_custom_mesh(src_path)
    if old_mesh_file and old_mesh_file != filename:
        _drop_unreferenced_mesh(store, old_mesh_file, skip_id=skip_id)
    return filename


def resolve_mesh_path(bed: dict[str, Any] | None) -> str | None:
    """Absolute path to the OBJ for a saved bed, or None if it cannot be resolved."""
    if not isinstance(bed, dict):
        return None
    catalog_id = bed.get("catalog_id")
    if catalog_id == CUSTOM_CATALOG_ID:
        mesh_file = bed.get("mesh_file")
        if not isinstance(mesh_file, str) or not mesh_file.strip():
            return None
        path = os.path.join(custom_meshes_dir(), os.path.basename(mesh_file))
        return path if os.path.isfile(path) else None
    plate = plate_by_id(catalog_id)
    if plate is None:
        return None
    path = plate.mesh_path()
    return path if os.path.isfile(path) else None
