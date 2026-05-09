"""
Initial facing wizard values.
"""

from typing import Any

from .facing_gcode import MILLING_CLIMB, PATTERN_RASTER_X
from .stock_geometry import CORNER_BL

DEFAULT_PROBE_TOOL_T = 999990
DEFAULT_M6_COLLET = None

DEFAULT_STOCK_ORIGIN_CORNER = CORNER_BL
DEFAULT_PATTERN = PATTERN_RASTER_X
DEFAULT_MILLING_DIRECTION = MILLING_CLIMB

DEFAULT_CHK_PROBE = False
DEFAULT_CHK_FINISH = True

# Text inputs by widget id
DEFAULT_TXT: dict[str, str] = {
    "txt_w": "100",
    "txt_l": "80",
    "txt_mx": "1",
    "txt_my": "1",
    "txt_mz": "0",
    "txt_clear": "5",
    "txt_tool_d": "6",
    "txt_spindle": "12000",
    "txt_rough_f": "1200",
    "txt_rough_plunge": "400",
    "txt_rough_step": "3",
    "txt_rough_doc": "1",
    "txt_rough_total": "2",
    "txt_finish_f": "600",
    "txt_finish_step": "0.6",
    "txt_finish_depth": "0.15",
    "txt_grid_nx": "3",
    "txt_grid_ny": "3",
    "txt_probe_approach": "3",
    "txt_probe_travel": "-35",
    "txt_probe_f": "120",
    "txt_probe_inset": "1",
    "txt_m6_t": "1",
    "txt_tlo_r": "",
    "txt_m491_x": "",
    "txt_m491_y": "",
    "txt_m491_z": "",
}


def default_preset_data(*, schema_version: int) -> dict[str, Any]:
    """Baseline preset dict for merging stored JSON and for normalize_preset_data."""
    d: dict[str, Any] = {
        "schema_version": schema_version,
        "stock_origin_corner": DEFAULT_STOCK_ORIGIN_CORNER,
        "pattern": DEFAULT_PATTERN,
        "milling_direction": DEFAULT_MILLING_DIRECTION,
        "probe_tool_t": DEFAULT_PROBE_TOOL_T,
        "m6_collet": DEFAULT_M6_COLLET,
        "chk_probe": DEFAULT_CHK_PROBE,
        "chk_finish": DEFAULT_CHK_FINISH,
    }
    d.update(DEFAULT_TXT)
    return d
