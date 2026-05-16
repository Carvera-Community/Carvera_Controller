"""
Stock rectangle in WCS when a chosen stock corner is at the origin.
"""

CORNER_BL = "bl"
CORNER_BR = "br"
CORNER_TL = "tl"
CORNER_TR = "tr"

def stock_rect_from_origin_corner(
    width_mm: float,
    length_mm: float,
    corner: str,
) -> tuple[float, float, float, float]:
    """Axis-aligned stock in work XY as (min_x, min_y, max_x, max_y)."""
    w = width_mm
    sl = length_mm
    c = corner.strip().lower()
    if c == CORNER_BL:
        return (0.0, 0.0, w, sl)
    if c == CORNER_BR:
        return (-w, 0.0, 0.0, sl)
    if c == CORNER_TL:
        return (0.0, -sl, w, 0.0)
    if c == CORNER_TR:
        return (-w, -sl, 0.0, 0.0)
    raise ValueError("stock corner must be bl, br, tl, or tr")


def rect_with_xy_margin(
    rect: tuple[float, float, float, float],
    margin_x: float,
    margin_y: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    return (
        x0 - margin_x,
        y0 - margin_y,
        x1 + margin_x,
        y1 + margin_y,
    )
