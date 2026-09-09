"""Render tool silhouette icons into Kivy textures from real geometry.

Tooltip and legend icons are generated on demand from ``ToolDefinition``
profiles (same source as the 3D viewer), cropped with body or thumb framing,
and cached by geometry signature + pixel size.

Pixels are rasterized on the CPU and uploaded with ``Texture.blit_buffer``.
"""

from __future__ import annotations

from array import array
from collections import OrderedDict

from kivy.graphics.texture import Texture
from kivy.metrics import Metrics, dp

from carveracontroller.addons.tool_visualization.icon_geometry import (
    FRAMING_BODY,
    FRAMING_THUMB,
    build_icon_geometry,
    geometry_cache_key,
)
from carveracontroller.addons.tool_visualization.mesh_builder import FLUTE_COLOR, SHANK_COLOR

# Normalized float RGBA. Opaque variants of the 3D viewer colors (those carry
# transparency for GL blending); the rasterizer converts to 0..255.
ICON_FLUTE_COLOR = (FLUTE_COLOR[0], FLUTE_COLOR[1], FLUTE_COLOR[2], 1.0)
ICON_SHANK_COLOR = (SHANK_COLOR[0], SHANK_COLOR[1], SHANK_COLOR[2], 1.0)
ICON_OUTLINE_COLOR = (45 / 255, 45 / 255, 45 / 255, 1.0)

# Silhouette outline stroke width in dp (scaled with density / supersampling).
ICON_OUTLINE_WIDTH_DP = 1.25

# Default tooltip body icon size in dp. Tall so the extended shank crop reads
# clearly beside the tooltip text.
_TOOLTIP_ICON_DP = (52, 104)

# Soften edges under linear filtering on 1x displays; skip on HiDPI so a
# first-hover raster stays cheap (pixel count already scales with density).
_SUPERSAMPLE_1X = 2
_SUPERSAMPLE_HIDPI = 1

# Bound GPU memory from cached tooltip textures (~86 KB each at 1x).
_CACHE_MAX = 16
_texture_cache: OrderedDict[tuple, Texture] = OrderedDict()


def tooltip_icon_size():
    """Return ``(width, height)`` display pixels for a tooltip body icon."""
    return (dp(_TOOLTIP_ICON_DP[0]), dp(_TOOLTIP_ICON_DP[1]))


def _to_bytes_rgba(color):
    return (
        int(round(color[0] * 255)),
        int(round(color[1] * 255)),
        int(round(color[2] * 255)),
        int(round(color[3] * 255)),
    )


def _supersample_factor():
    return _SUPERSAMPLE_HIDPI if Metrics.density >= 2 else _SUPERSAMPLE_1X


def _put_pixel(buf, width, height, x, y, rgba):
    """Overwrite a pixel; ``(x, y)`` origin is bottom-left.

    Every icon color is opaque, so painter's-order overwrite is enough and no
    alpha compositing is needed.
    """
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    i = (y * width + x) * 4
    buf[i] = rgba[0]
    buf[i + 1] = rgba[1]
    buf[i + 2] = rgba[2]
    buf[i + 3] = rgba[3]


def _fill_triangle(buf, width, height, tri, rgba):
    """Fill a triangle with a flat color using barycentric scan conversion."""
    (x0, y0), (x1, y1), (x2, y2) = tri
    min_x = max(int(min(x0, x1, x2)), 0)
    max_x = min(int(max(x0, x1, x2)) + 1, width - 1)
    min_y = max(int(min(y0, y1, y2)), 0)
    max_y = min(int(max(y0, y1, y2)) + 1, height - 1)
    if max_x < min_x or max_y < min_y:
        return

    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-12:
        return

    for y in range(min_y, max_y + 1):
        py = y + 0.5
        for x in range(min_x, max_x + 1):
            px = x + 0.5
            w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
            w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
            w2 = 1.0 - w0 - w1
            if w0 >= 0.0 and w1 >= 0.0 and w2 >= 0.0:
                _put_pixel(buf, width, height, x, y, rgba)


def _stamp_coverage(coverage, width, height, x0, y0, x1, y1, thickness):
    """Stamp a thick line segment into a coverage set of flat buffer indices.

    ``thickness`` is the half-width in render pixels, matching Kivy ``Line``.
    """
    dx = x1 - x0
    dy = y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-9:
        return
    radius = max(thickness, 1.0)
    r2 = radius * radius

    def _cover(cx, cy):
        min_x = max(int(cx - radius), 0)
        max_x = min(int(cx + radius) + 1, width - 1)
        min_y = max(int(cy - radius), 0)
        max_y = min(int(cy + radius) + 1, height - 1)
        for y in range(min_y, max_y + 1):
            ddy = (y + 0.5) - cy
            row = y * width
            for x in range(min_x, max_x + 1):
                ddx = (x + 0.5) - cx
                if ddx * ddx + ddy * ddy <= r2:
                    coverage.add(row + x)

    steps = max(int(length * 2), 1)
    for s in range(steps + 1):
        t = s / steps
        _cover(x0 + dx * t, y0 + dy * t)


def _draw_outline(buf, width, height, outline, rgba, thickness):
    """Stroke the outline as an outside rim around the already-painted fill."""
    if len(outline) < 2:
        return
    coverage = set()
    for i in range(len(outline) - 1):
        x0, y0 = outline[i]
        x1, y1 = outline[i + 1]
        _stamp_coverage(coverage, width, height, x0, y0, x1, y1, thickness)
    for index in coverage:
        i = index * 4
        if buf[i + 3] != 0:
            continue
        _put_pixel(buf, width, height, index % width, index // width, rgba)


def _scale_triangles(triangles, width, height):
    return [tuple((x * width, y * height) for x, y in tri) for tri in triangles]


def _scale_outline(outline, width, height):
    return [(x * width, y * height) for x, y in outline]


def _normalize_size(size):
    """Return ``(width, height)`` display pixels from a ``(w, h)`` pair."""
    width = max(int(round(size[0])), 1)
    height = max(int(round(size[1])), 1)
    return width, height


def _rasterize_icon(geometry, width, height):
    """Return an RGBA ``array('B')`` buffer for the icon at display size."""
    factor = _supersample_factor()
    render_w = max(int(round(width * factor)), 1)
    render_h = max(int(round(height * factor)), 1)
    buf = array("B", [0]) * (render_w * render_h * 4)

    flute = _scale_triangles(geometry["flute_triangles"], render_w, render_h)
    shank = _scale_triangles(geometry["shank_triangles"], render_w, render_h)
    outline = _scale_outline(geometry["outline"], render_w, render_h)

    flute_rgba = _to_bytes_rgba(ICON_FLUTE_COLOR)
    shank_rgba = _to_bytes_rgba(ICON_SHANK_COLOR)
    outline_rgba = _to_bytes_rgba(ICON_OUTLINE_COLOR)

    for tri in flute:
        _fill_triangle(buf, render_w, render_h, tri, flute_rgba)
    for tri in shank:
        _fill_triangle(buf, render_w, render_h, tri, shank_rgba)
    # The geometry is scaled by both density and supersampling, so the stroke
    # has to follow or it degrades into a hairline on HiDPI displays.
    _draw_outline(buf, render_w, render_h, outline, outline_rgba, dp(ICON_OUTLINE_WIDTH_DP) * factor)

    return buf, render_w, render_h


def _render_icon_texture(geometry, width, height):
    """Rasterize ``geometry`` and upload it to a new Texture."""
    buf, render_w, render_h = _rasterize_icon(geometry, width, height)
    texture = Texture.create(size=(render_w, render_h), colorfmt="rgba")
    texture.blit_buffer(buf, colorfmt="rgba", bufferfmt="ubyte")
    # Buffer y=0 is the tip (bottom). OpenGL/Kivy Rectangle also treat the
    # first uploaded row as v=0 at the bottom, so no flip is needed.
    texture.mag_filter = "linear"
    texture.min_filter = "linear"

    # Hand-uploaded buffers are not restored after a GL context reset unless
    # we re-blit ourselves (important on Android pause/resume).
    def _reload(tex, _buf=buf):
        tex.blit_buffer(_buf, colorfmt="rgba", bufferfmt="ubyte")

    texture.add_reload_observer(_reload)
    return texture


def build_tool_tooltip_icon_texture(tool_def, size=None):
    """Return a cached body-framed Kivy Texture for a tooltip icon.

    ``size`` is ``(width, height)`` display pixels. Defaults to
    ``tooltip_icon_size()`` so the texture matches the dp-scaled display size.

    The returned texture may be supersampled (larger than ``size``); callers
    that need the display size should prefer ``build_tool_tooltip_icon``.
    """
    if size is None:
        size = tooltip_icon_size()
    width, height = _normalize_size(size)
    key = (geometry_cache_key(tool_def, framing=FRAMING_BODY), width, height)
    cached = _texture_cache.get(key)
    if cached is not None:
        _texture_cache.move_to_end(key)
        return cached

    box_aspect = width / float(height)
    geometry = build_icon_geometry(tool_def, framing=FRAMING_BODY, box_aspect=box_aspect)
    texture = _render_icon_texture(geometry, width, height)
    _texture_cache[key] = texture
    while len(_texture_cache) > _CACHE_MAX:
        _texture_cache.popitem(last=False)
    return texture


def build_tool_tooltip_icon(tool_def, size=None):
    """Return ``(texture, display_size)`` for a tooltip body icon.

    ``display_size`` is the intended widget size in display pixels. The
    texture may be supersampled larger than that; tooltip consumers should
    size the Image from ``display_size``, not ``texture.size``.
    """
    if size is None:
        size = tooltip_icon_size()
    width, height = _normalize_size(size)
    texture = build_tool_tooltip_icon_texture(tool_def, size=(width, height))
    return texture, (width, height)


def build_tool_legend_icon(tool_def, size=None):
    """Return ``(texture, display_size)`` for a compact thumb-framed legend icon."""
    if size is None:
        size = (dp(20), dp(20))
    width, height = _normalize_size(size)
    key = (geometry_cache_key(tool_def, framing=FRAMING_THUMB), width, height)
    cached = _texture_cache.get(key)
    if cached is not None:
        _texture_cache.move_to_end(key)
        return cached, (width, height)

    box_aspect = width / float(height)
    geometry = build_icon_geometry(tool_def, framing=FRAMING_THUMB, box_aspect=box_aspect)
    texture = _render_icon_texture(geometry, width, height)
    _texture_cache[key] = texture
    while len(_texture_cache) > _CACHE_MAX:
        _texture_cache.popitem(last=False)
    return texture, (width, height)


def clear_tool_icon_cache():
    """Drop all cached icon textures (mainly for tests)."""
    _texture_cache.clear()
