"""
Z-height grid probing

After each M466 Z probe, #156 holds probed Z (see https://carvera-community.gitbook.io/docs/firmware/supported-commands/mcodes/probing#m466-single-axis-probe-double-tap).
While probing the grid we track the highest sampled surface Z in local ``#105``
We then emit ``G10`` so work Z0 matches that peak.
"""

from dataclasses import dataclass

from carveracontroller.translation import tr

from .stock_geometry import stock_rect_from_origin_corner


@dataclass
class ProbeGridParams:
    stock_width_mm: float
    stock_length_mm: float
    stock_origin_corner: str
    margin_x_mm: float
    margin_y_mm: float
    clearance_z_mm: float
    approach_z_mm: float
    probe_z_travel_mm: float
    probe_feed_mm_min: float
    grid_nx: int
    grid_ny: int
    inset_mm: float
    probe_tool_t: int = 999990


@dataclass(frozen=True)
class ProbeGridGeometry:
    """Inset rectangle and probe grid coordinates (work coordinates)."""

    inset_x0: float
    inset_x1: float
    inset_y0: float
    inset_y1: float
    xs: tuple[float, ...]
    ys: tuple[float, ...]


def _lerp(a: float, b: float, n: int) -> list[float]:
    if n < 2:
        return [(a + b) / 2.0]
    span = b - a
    return [a + span * i / (n - 1) for i in range(n)]


def compute_probe_grid_xy(p: ProbeGridParams) -> ProbeGridGeometry:
    """Raises ValueError with the same rules as generate_probe_grid_gcode."""
    if p.grid_nx < 1 or p.grid_ny < 1:
        raise ValueError(tr._("Grid dimensions must be at least 1."))
    if p.probe_z_travel_mm >= -0.01:
        raise ValueError(tr._("Probe Z travel must be negative (e.g. -25)."))

    w = p.stock_width_mm
    sl = p.stock_length_mm
    ins = max(p.inset_mm, 0.0)

    nx0, ny0, nx1, ny1 = stock_rect_from_origin_corner(w, sl, p.stock_origin_corner)
    # Inset is measured from declared stock edges (stock_rect in WCS XY).
    x0 = nx0 + ins
    x1 = nx1 - ins
    y0 = ny0 + ins
    y1 = ny1 - ins
    if x0 >= x1 - 1e-6 or y0 >= y1 - 1e-6:
        raise ValueError(tr._("Probe grid area invalid after stock inset."))

    xs = _lerp(x0, x1, p.grid_nx)
    ys = _lerp(y0, y1, p.grid_ny)
    return ProbeGridGeometry(
        inset_x0=x0,
        inset_x1=x1,
        inset_y0=y0,
        inset_y1=y1,
        xs=tuple(xs),
        ys=tuple(ys),
    )


def probe_grid_z_datum_shift_after_probe_gcode() -> str:
    """
    Run after probe cycle and before facing M6/M491 while still at clearance:
    - ``#5023`` is current WCS Z
    - ``#105`` is the highest sampled surface Z tracked
    - ``G10 L20 P0`` sets the WCS origin so that highest point becomes Z=0.
    """
    return (
        "M400\n"
        "(Shift Z to highest grid sample)\n"
        "G10 L20 P0 Z[#5023-#105]"
    )


def generate_probe_grid_gcode(p: ProbeGridParams, *, end_program: bool = True) -> str:
    geom = compute_probe_grid_xy(p)
    xs = list(geom.xs)
    ys = list(geom.ys)

    lines: list[str] = []
    lines.append("(Z grid probe)")
    lines.append("(WCS XY origin = stock corner from wizard; Z0 nominal top)")
    lines.append("G21")
    lines.append("G90")
    lines.append("G17")
    lines.append("G94")
    lines.append(f"M6 T{p.probe_tool_t:d}")
    lines.append("(Tracking max Z value in #105)")
    lines.append("#105=-99999")

    lines.append(f"G0 Z{p.clearance_z_mm:.4f}")
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            lines.append(f"(Probe point {i + 1}x{j + 1} of {p.grid_nx}x{p.grid_ny})")
            lines.append(f"G0 X{x:.4f} Y{y:.4f}")
            lines.append(f"G0 Z{p.approach_z_mm:.4f}")
            lines.append(f"M466 Z{p.probe_z_travel_mm:.4f} F{p.probe_feed_mm_min:.1f}")
            lines.append("#105=[#156gt#105]*#156+[#156le#105]*#105")
            lines.append(f"G0 Z{p.clearance_z_mm:.4f}")

    if end_program:
        lines.append("M2")
    return "\n".join(lines) + "\n"
