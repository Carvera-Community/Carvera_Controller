from carveracontroller.translation import tr


"""
Stock rectangle in WCS when a chosen stock corner is at the origin.
"""

STOCK_ORIGIN_CORNER_BL = "bl"
STOCK_ORIGIN_CORNER_BR = "br"
STOCK_ORIGIN_CORNER_TL = "tl"
STOCK_ORIGIN_CORNER_TR = "tr"
STOCK_ORIGIN_CORNER_CEN = "center"


def stock_origin_pairs():
    return [
        (tr._("Bottom-left (+X width, +Y length)"), STOCK_ORIGIN_CORNER_BL),
        (tr._("Bottom-right (-X width, +Y length)"), STOCK_ORIGIN_CORNER_BR),
        (tr._("Top-left (+X width, -Y length)"), STOCK_ORIGIN_CORNER_TL),
        (tr._("Top-right (-X width, -Y length)"), STOCK_ORIGIN_CORNER_TR),
        (tr._("Center (X width / 2, Y length / 2)"), STOCK_ORIGIN_CORNER_CEN),
    ]


def stock_rect_from_origin_corner(
    width_mm: float,
    length_mm: float,
    corner: str,
) -> tuple[float, float, float, float]:
    """Axis-aligned stock in work XY as (min_x, min_y, max_x, max_y)."""
    w = width_mm
    sl = length_mm
    c = corner.strip().lower()
    if c == STOCK_ORIGIN_CORNER_BL:
        return (0.0, 0.0, w, sl)
    if c == STOCK_ORIGIN_CORNER_BR:
        return (-w, 0.0, 0.0, sl)
    if c == STOCK_ORIGIN_CORNER_TL:
        return (0.0, -sl, w, 0.0)
    if c == STOCK_ORIGIN_CORNER_TR:
        return (-w, -sl, 0.0, 0.0)
    if c == STOCK_ORIGIN_CORNER_CEN:
        return (-w / 2, -sl / 2, w / 2, sl / 2)
    raise ValueError("stock corner must be bl, br, tl, or tr, cen")


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
