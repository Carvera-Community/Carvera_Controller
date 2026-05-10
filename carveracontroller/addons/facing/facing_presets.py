"""
Named facing wizard presets storage
"""

import uuid
from typing import Any

# Reuse probing addon ConfigUtils for save_config / load_config
from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils

from . import facing_wizard_defaults as default_values
from .facing_gcode import (
    MILLING_BOTH,
    MILLING_CLIMB,
    MILLING_CONVENTIONAL,
    PATTERN_RASTER_X,
    PATTERN_RASTER_Y,
    PATTERN_SPIRAL,
)
from .stock_geometry import CORNER_BL, CORNER_BR, CORNER_TL, CORNER_TR

PRESET_FILENAME = "facing-wizard-presets.json"
STORE_VERSION = 1
PRESET_SCHEMA_VERSION = 1

TXT_KEYS = tuple(default_values.DEFAULT_TXT.keys())

DEFAULT_PRESET_DATA: dict[str, Any] = default_values.default_preset_data(schema_version=PRESET_SCHEMA_VERSION)


def load_store() -> dict[str, Any]:
    raw = ConfigUtils.load_config(PRESET_FILENAME)
    if not raw:
        return {"version": STORE_VERSION, "presets": []}
    presets = raw.get("presets")
    if not isinstance(presets, list):
        presets = []
    out: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        data = item.get("data")
        pid = item.get("id")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(data, dict):
            continue
        if not isinstance(pid, str) or not pid:
            pid = str(uuid.uuid4())
        out.append({"id": pid, "name": name.strip(), "data": data})
    return {"version": int(raw.get("version", STORE_VERSION)), "presets": out}


def save_store(store: dict[str, Any]) -> None:
    payload = {
        "version": STORE_VERSION,
        "presets": store.get("presets", []),
    }
    ConfigUtils.save_config(payload, PRESET_FILENAME)


def sorted_preset_names(store: dict[str, Any]) -> list[str]:
    names = [p["name"] for p in store.get("presets", []) if isinstance(p, dict) and "name" in p]
    return sorted(names, key=lambda s: s.lower())


def get_preset_by_name(store: dict[str, Any], name: str) -> dict[str, Any] | None:
    name = name.strip()
    for p in store.get("presets", []):
        if isinstance(p, dict) and p.get("name") == name:
            return p
    return None


def upsert_preset(store: dict[str, Any], name: str, data: dict[str, Any]) -> None:
    name = name.strip()
    blob = normalize_preset_data(data)
    presets: list[dict[str, Any]] = store.setdefault("presets", [])
    for p in presets:
        if isinstance(p, dict) and p.get("name") == name:
            p["data"] = blob
            return
    presets.append({"id": str(uuid.uuid4()), "name": name, "data": blob})


def delete_preset_by_name(store: dict[str, Any], name: str) -> bool:
    name = name.strip()
    presets: list = store.get("presets", [])
    for i, p in enumerate(presets):
        if isinstance(p, dict) and p.get("name") == name:
            presets.pop(i)
            return True
    return False


def normalize_preset_data(data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_PRESET_DATA)
    if not isinstance(data, dict):
        return merged
    for k in DEFAULT_PRESET_DATA:
        if k in data:
            merged[k] = data[k]
    corner = str(
        merged.get("stock_origin_corner", default_values.DEFAULT_STOCK_ORIGIN_CORNER)
    ).strip().lower()
    if corner not in {CORNER_BL, CORNER_BR, CORNER_TL, CORNER_TR}:
        corner = default_values.DEFAULT_STOCK_ORIGIN_CORNER
    merged["stock_origin_corner"] = corner

    pat = str(merged.get("pattern", default_values.DEFAULT_PATTERN)).strip().lower()
    if pat not in {PATTERN_RASTER_X, PATTERN_RASTER_Y, PATTERN_SPIRAL}:
        pat = default_values.DEFAULT_PATTERN
    merged["pattern"] = pat

    mill = str(merged.get("milling_direction", default_values.DEFAULT_MILLING_DIRECTION)).strip().lower()
    if mill not in {MILLING_CLIMB, MILLING_CONVENTIONAL, MILLING_BOTH}:
        mill = default_values.DEFAULT_MILLING_DIRECTION
    merged["milling_direction"] = mill

    try:
        merged["probe_tool_t"] = int(merged["probe_tool_t"])
    except (TypeError, ValueError):
        merged["probe_tool_t"] = default_values.DEFAULT_PROBE_TOOL_T

    mc = merged.get("m6_collet")
    if mc is not None:
        try:
            merged["m6_collet"] = int(mc)
        except (TypeError, ValueError):
            merged["m6_collet"] = None

    merged["chk_probe"] = bool(merged.get("chk_probe", default_values.DEFAULT_CHK_PROBE))
    merged["chk_finish"] = bool(merged.get("chk_finish", default_values.DEFAULT_CHK_FINISH))
    merged["chk_ext_port"] = bool(merged.get("chk_ext_port", default_values.DEFAULT_CHK_EXT_PORT))

    for tk in TXT_KEYS:
        if tk not in merged or merged[tk] is None:
            merged[tk] = DEFAULT_PRESET_DATA[tk]
        else:
            merged[tk] = str(merged[tk])

    try:
        s_ext = int(round(float(merged["txt_ext_port_s"].replace(",", "."))))
    except (TypeError, ValueError):
        s_ext = int(default_values.DEFAULT_TXT["txt_ext_port_s"])
    merged["txt_ext_port_s"] = str(max(0, min(100, s_ext)))

    try:
        d_s = int(round(float(merged["txt_spindle_dwell"].replace(",", "."))))
    except (TypeError, ValueError):
        d_s = int(default_values.DEFAULT_TXT["txt_spindle_dwell"])
    merged["txt_spindle_dwell"] = str(max(0, d_s))

    if pat == PATTERN_SPIRAL and mill == MILLING_BOTH:
        merged["milling_direction"] = MILLING_CLIMB

    merged["schema_version"] = PRESET_SCHEMA_VERSION
    return merged


def _collet_code_from_popup(popup: Any) -> Any:
    popup._ensure_wizard_lists()
    for _label, code in popup._m6_collet_pairs_list:
        if popup.ids.spn_m6_collet.text == _label:
            return code
    return None


def preset_data_from_popup(popup: Any) -> dict[str, Any]:
    """Snapshot current wizard state (stable enums / values)."""
    popup._ensure_wizard_lists()
    ids = popup.ids
    data = {
        "schema_version": PRESET_SCHEMA_VERSION,
        "stock_origin_corner": popup._stock_origin_corner_from_ui(),
        "pattern": popup._pattern_from_ui(),
        "milling_direction": popup._milling_direction_from_ui(),
        "probe_tool_t": popup._probe_tool_t_from_ui(),
        "m6_collet": _collet_code_from_popup(popup),
        "chk_probe": bool(ids.chk_probe.active),
        "chk_finish": bool(ids.chk_finish.active),
        "chk_ext_port": bool(ids.chk_ext_port.active),
    }
    for tk in TXT_KEYS:
        data[tk] = getattr(ids, tk).text
    if data["pattern"] == PATTERN_SPIRAL and data["milling_direction"] == MILLING_BOTH:
        data["milling_direction"] = MILLING_CLIMB
    return normalize_preset_data(data)


def _label_for_value(pairs: list, value: Any) -> str | None:
    for lab, val in pairs:
        if val == value:
            return lab
    return None


def apply_preset_data(popup: Any, data: dict[str, Any]) -> None:
    """Apply normalized preset to wizard widgets"""
    blob = normalize_preset_data(data)
    popup._ensure_wizard_lists()
    ids = popup.ids

    for tk in TXT_KEYS:
        getattr(ids, tk).text = blob[tk]

    ids.chk_probe.active = blob["chk_probe"]
    ids.chk_finish.active = blob["chk_finish"]
    ids.chk_ext_port.active = blob["chk_ext_port"]

    pat = blob["pattern"]
    ids.raster_x_btn.state = "down" if pat == PATTERN_RASTER_X else "normal"
    ids.raster_y_btn.state = "down" if pat == PATTERN_RASTER_Y else "normal"
    ids.raster_spiral_btn.state = "down" if pat == PATTERN_SPIRAL else "normal"

    popup._sync_milling_spinner_for_pattern()

    corner_lab = _label_for_value(popup._stock_corner_pairs_list, blob["stock_origin_corner"])
    if corner_lab and corner_lab in ids.spn_stock_corner.values:
        ids.spn_stock_corner.text = corner_lab
    else:
        ids.spn_stock_corner.text = popup._stock_corner_pairs_list[0][0]

    mill_lab = _label_for_value(popup._milling_direction_pairs_list, blob["milling_direction"])
    if mill_lab and mill_lab in ids.spn_milling_dir.values:
        ids.spn_milling_dir.text = mill_lab

    probe_lab = _label_for_value(popup._probe_tool_pairs_list, blob["probe_tool_t"])
    if probe_lab and probe_lab in ids.spn_probe_tool.values:
        ids.spn_probe_tool.text = probe_lab
    else:
        ids.spn_probe_tool.text = popup._probe_tool_pairs_list[0][0]

    collet_code = blob["m6_collet"]
    collet_lab = None
    for lab, code in popup._m6_collet_pairs_list:
        if code == collet_code:
            collet_lab = lab
            break
    if collet_lab is not None and collet_lab in ids.spn_m6_collet.values:
        ids.spn_m6_collet.text = collet_lab
    else:
        ids.spn_m6_collet.text = popup._m6_collet_pairs_list[0][0]
