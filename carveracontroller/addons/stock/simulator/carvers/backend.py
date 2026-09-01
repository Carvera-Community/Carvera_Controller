"""Shared protocol and helpers for stock carver backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# GPU mesh patches use (i, j, k) tile keys for all backends.
TileKey = tuple[int, int, int]

DEFAULT_TILE_SIZE = 16


@runtime_checkable
class CarverBackend(Protocol):
    """Occupancy + carve + mesh surface used by :class:`StockSimulator`."""

    kind: str
    cell_size: float

    def reset_occupancy(self) -> set[TileKey]:
        """Clear to uncut stock. Returns tiles that should remesh."""
        ...

    def clone_empty(self) -> CarverBackend:
        """Empty clone with the same bounds/resolution (bake grid)."""
        ...

    def carve_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
    ) -> set[TileKey]:
        """Carve one segment; return dirty tile keys."""
        ...

    def snapshot_full(self) -> object:
        """Full checkpoint payload (non-FULL / full heightfield)."""
        ...

    def snapshot_changed(self, keys: set[TileKey]) -> object:
        """Delta payload for ``keys`` since the last checkpoint."""
        ...

    def restore(self, payload: object) -> set[TileKey]:
        """Restore from a full or delta payload. Returns dirty keys."""
        ...

    def copy_tiles(self, keys: set[TileKey]) -> CarverBackend:
        """Deep-copy selected tiles for unlocked meshing."""
        ...

    def mesh_tiles(self, keys: set[TileKey]) -> dict[TileKey, tuple | None]:
        """Build GPU mesh buffers for dirty tiles (``None`` = remove)."""
        ...

    def expand_dirty(self, dirty: set[TileKey]) -> set[TileKey]:
        """Expand dirty set with neighbours needed for correct remesh."""
        ...

    def initial_surface_keys(self) -> set[TileKey]:
        """Tiles that must remesh for the uncut solid shell."""
        ...

    def all_non_full_keys(self) -> set[TileKey]:
        """Keys that differ from the implicit full-solid state."""
        ...

    def engrave_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
        power_s: float | None = None,
    ) -> bool:
        """Paint a laser stroke into the decal map. No occupancy change."""
        ...

    def laser_gpu_payload(self) -> tuple[int, int, bytes, str] | None:
        """``(width, height, luminance, mode)`` or ``None`` if never engraved."""
        ...

    def take_laser_dirty(self) -> bool:
        """True if the laser map changed since the last take (then clears)."""
        ...

    def hud_stats(self) -> dict:
        """Fields merged into the simulator HUD snapshot."""
        ...
