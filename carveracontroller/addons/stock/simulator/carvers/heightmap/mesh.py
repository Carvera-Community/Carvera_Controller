"""Heightmap meshing via the native stock extension.

Cut simulation requires the native extension (see
``GcodeViewer.simulation_available``), so there is no Python fallback here:
``mesh_heightmap_region`` raises if the extension is not built.
"""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.simulator.mesh_format import default_stock_color

# Occupancy sentinel shared with HeightmapBackend (imported from this module).
_OUTSIDE = np.float32(-1e30)


def mesh_heightmap_region(backend, x0: int, y0: int, x1: int, y1: int):
    """Build Kivy quad meshes for cells ``[x0:x1, y0:y1]``.

    Flat corners share vertices; every height step gets a vertical skirt
    (or the stock boundary does), so the shell is watertight.
    """
    if x0 >= x1 or y0 >= y1:
        return []
    from carveracontroller.addons.stock.simulator import native as native_mod

    patch = np.ascontiguousarray(backend._read_patch(x0 - 1, y0 - 1, x1 + 1, y1 + 1), dtype=np.float32)
    vs = float(backend.cell_size)
    return native_mod.mesh_heightmap_patch(
        patch,
        gw=x1 - x0,
        gh=y1 - y0,
        x0=int(x0),
        y0=int(y0),
        nx=int(backend.nx),
        ny=int(backend.ny),
        origin_x=float(backend.bounds.min_x) + x0 * vs,
        origin_y=float(backend.bounds.min_y) + y0 * vs,
        min_z=float(backend.bounds.min_z),
        cell=vs,
        color=default_stock_color(),
    )
