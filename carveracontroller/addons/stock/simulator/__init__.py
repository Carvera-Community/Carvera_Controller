"""Stock cut-simulation worker and carver backends."""

from .carvers.voxel.carve import (
    _constant_profile_radius,
    _max_profile_radius,
    _resolve_profile,
    _voxels_inside_tool,
    carve_segment_into_grid,
)
from .carvers.voxel.checkpoints import CheckpointStore, _pack_chunk_state, _unpack_chunk_state
from .carvers.voxel.occupancy import _expand_dirty_with_neighbors
from .worker import (
    _MERGE_TOL_VOXEL_FRAC,
    DEFAULT_MESH_THROTTLE_S,
    MAX_MESH_TILES_PER_EMIT,
    PLAY_MESH_THROTTLE_S,
    PathSnapshot,
    StockSimulator,
    _can_extend_collinear_merge,
    _clamp_collinear_run_end,
    _point_to_segment_dist_sq,
)

__all__ = [
    "DEFAULT_MESH_THROTTLE_S",
    "MAX_MESH_TILES_PER_EMIT",
    "PLAY_MESH_THROTTLE_S",
    "PathSnapshot",
    "StockSimulator",
    "CheckpointStore",
    "carve_segment_into_grid",
    "_expand_dirty_with_neighbors",
    "_resolve_profile",
    "_constant_profile_radius",
    "_max_profile_radius",
    "_voxels_inside_tool",
    "_pack_chunk_state",
    "_unpack_chunk_state",
    "_MERGE_TOL_VOXEL_FRAC",
    "_can_extend_collinear_merge",
    "_clamp_collinear_run_end",
    "_point_to_segment_dist_sq",
]
