"""Procedural generation of very basic 3D tool meshes.
Each tool is approximated by revolving a simple 2D profile.
"""

import math

from carveracontroller.addons.tool_visualization.tool_definition import ToolType

FLUTE_COLOR = (0.85, 0.65, 0.15, 0.45)
SHANK_COLOR = (0.5, 0.5, 0.52, 0.3)

VERTEX_FORMAT = [
    (b"v_pos", 3, "float"),
    (b"v_normal", 3, "float"),
    (b"v_color", 4, "float"),
    (b"v_tc0", 2, "float"),
]

FLOATS_PER_VERTEX = 12
RADIAL_SEGMENTS = 20
ROUND_SEGMENTS = 10
DEFAULT_TAPER_ANGLE_DEG = 30.0
DEFAULT_DRILL_TAPER_ANGLE_DEG = 59.0

# Factor used to compute overall stick-out when length metadata is missing.
LENGTH_DIAMETER_FACTOR = 6.0

# When flute length is missing, inferred/fallback flute height is capped to this
# multiple of diameter so long stick-outs are not painted entirely as cutting.
FALLBACK_FLUTE_DIAMETER_FACTOR = 4.0

# Flute -> shank blend: axial rise per unit radial change (~45°), capped as a
# fraction of the available shank length so some cylinder remains above.
SHANK_TRANSITION_SLOPE = 1.0
SHANK_TRANSITION_MAX_FRACTION = 0.5

# When flute is tip-inferred and shoulder metadata is missing, extend
# a short cutting-diameter body before the shank so the tip does not
# jump straight into the handle. Capped to half the remaining stick-out.
INFERRED_SHOULDER_DIAMETER_FACTOR = 1.0
INFERRED_SHOULDER_MAX_FRACTION = 0.5

# Shank kept above the cutting body when stick-out metadata is missing and only
# shoulder/flute lengths are known. Those describe the cutting end alone, so
# without this the tool would stop right where its flutes end (e.g. a V-bit
# drawn as a bare cone). Expressed as a multiple of the larger of the cutting
# and shank diameters.
FALLBACK_STICKOUT_DIAMETER_FACTOR = 1.0

# Undercut neck diameter of a lollipop mill as a fraction of the ball diameter.
# Parsers cannot infer a shaft size for this type, so this is always what draws
# the neck; real undercutting end mills sit around 0.55-0.6 of the cutter Ø.
LOLLIPOP_NECK_DIAMETER_FACTOR = 0.55

# Minimum radius and length for tools to be visible on screen.
MIN_VISIBLE_RADIUS = 0.02
MIN_SHANK_LENGTH = 0.05

# Fixed on-screen size for tools with no CAM metadata (scaled viewer coordinates,
# where the toolpath bbox spans 2.0 on its largest side). Height follows the same
# stick-out ratio as a tool that only declares a diameter, so the no-metadata
# pointer stays in the same ballpark as a real one instead of towering over the job.
FALLBACK_TOOL_DISPLAY_RADIUS = 0.04
FALLBACK_TOOL_DISPLAY_HEIGHT = FALLBACK_TOOL_DISPLAY_RADIUS * 2.0 * LENGTH_DIAMETER_FACTOR


def _segment_tangent(profile, start, end):
    z0, r0 = profile[start]
    z1, r1 = profile[end]
    return (z1 - z0, r1 - r0)


def _ring_tangent(profile, index):
    """Tangent in the (z, radius) plane used for normals at a profile ring."""
    z, r = profile[index]
    if r <= 1e-9:
        if index + 1 < len(profile):
            return _segment_tangent(profile, index, index + 1)
        return _segment_tangent(profile, index - 1, index)
    if index > 0 and profile[index - 1][1] <= 1e-9:
        return _segment_tangent(profile, index - 1, index)
    if index + 1 < len(profile) and profile[index + 1][1] <= 1e-9:
        return _segment_tangent(profile, index, index + 1)
    if index == 0:
        return _segment_tangent(profile, index, index + 1)
    if index == len(profile) - 1:
        return _segment_tangent(profile, index - 1, index)
    z_prev, r_prev = profile[index - 1]
    z_next, r_next = profile[index + 1]
    return (z_next - z_prev, r_next - r_prev)


def _surface_normal(dz, dr, theta):
    """Outward normal for a surface of revolution at angle theta.

    Derived from cross(circumferential_tangent, profile_tangent) for a profile
    segment with delta (dz, dr) in the (z, radius) plane.
    """
    nx = dz * math.cos(theta)
    ny = dz * math.sin(theta)
    nz = -dr
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _profile_color(index, shank_start_index):
    return SHANK_COLOR if index >= shank_start_index else FLUTE_COLOR


def _add_vertex(positions, normals, colors, x, y, z, nx, ny, nz, color):
    positions.extend([x, y, z])
    normals.extend([nx, ny, nz])
    colors.extend(color)
    return (len(positions) // 3) - 1


def _build_side_ring(positions, normals, colors, z, radius, dz, dr, segments, color):
    """Add one ring of side-wall vertices with smooth analytical normals."""
    ring_indices = []
    for j in range(segments):
        theta = 2.0 * math.pi * j / segments
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        nx, ny, nz = _surface_normal(dz, dr, theta)
        idx = _add_vertex(positions, normals, colors, radius * cos_t, radius * sin_t, z, nx, ny, nz, color)
        ring_indices.append(idx)
    return ring_indices


def _build_cap_ring(positions, normals, colors, z, radius, nz_sign, segments, color):
    """Add a ring of cap vertices with a flat face normal (±Z)."""
    ring_indices = []
    for j in range(segments):
        theta = 2.0 * math.pi * j / segments
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        idx = _add_vertex(positions, normals, colors, radius * cos_t, radius * sin_t, z, 0.0, 0.0, nz_sign, color)
        ring_indices.append(idx)
    return ring_indices


def _pack_vertices(positions, normals, colors):
    vertices = []
    for i in range(len(positions) // 3):
        p = 3 * i
        c = 4 * i
        vertices.extend(
            [
                positions[p],
                positions[p + 1],
                positions[p + 2],
                normals[p],
                normals[p + 1],
                normals[p + 2],
                colors[c],
                colors[c + 1],
                colors[c + 2],
                colors[c + 3],
                0.0,
                0.0,
            ]
        )
    return vertices


def _coincident_profile_points(profile, start, end):
    z0, r0 = profile[start]
    z1, r1 = profile[end]
    return abs(z0 - z1) <= 1e-9 and abs(r0 - r1) <= 1e-9


def _build_revolve_mesh(profile, segments=RADIAL_SEGMENTS, shank_start_index=None):
    """Revolve a `(z, radius)` profile (sorted by increasing z) into a triangle mesh.

    A profile point with `radius <= 0` is treated as a single point on the
    axis (e.g. a pointed tip, or the pole of a ball nose) rather than a ring.

    Vertices are indexed and share smooth analytical normals derived from the
    profile tangent. Flat end caps use separate vertices with ±Z normals.

    Profile points at index >= `shank_start_index` are colored as SHANK_COLOR;
    earlier points keep the flute FLUTE_COLOR. When omitted, the whole tool is color
    using FLUTE_COLOR.
    """
    if len(profile) < 2:
        raise ValueError("A tool profile needs at least two points")

    if shank_start_index is None:
        shank_start_index = len(profile)

    positions = []
    normals = []
    colors = []
    indices = []

    side_rings = []
    for i, (z, r) in enumerate(profile):
        if r <= 1e-9:
            side_rings.append(None)
        else:
            dz, dr = _ring_tangent(profile, i)
            color = _profile_color(i, shank_start_index)
            side_rings.append(_build_side_ring(positions, normals, colors, z, r, dz, dr, segments, color))

    # Side walls, connecting each consecutive pair of profile points.
    for i in range(len(profile) - 1):
        # Duplicate rings at the flute/shank boundary create a hard color edge
        # without emitting a degenerate zero-area quad.
        if _coincident_profile_points(profile, i, i + 1):
            continue
        ring_a = side_rings[i]
        ring_b = side_rings[i + 1]
        if ring_a is None and ring_b is None:
            continue
        if ring_a is None:
            z_apex = profile[i][0]
            dz, dr = _segment_tangent(profile, i, i + 1)
            nx, ny, nz = _surface_normal(dz, dr, 0.0)
            color = _profile_color(i, shank_start_index)
            apex_idx = _add_vertex(positions, normals, colors, 0.0, 0.0, z_apex, nx, ny, nz, color)
            for j in range(segments):
                b0 = ring_b[j]
                b1 = ring_b[(j + 1) % segments]
                indices.extend([apex_idx, b0, b1])
        elif ring_b is None:
            z_apex = profile[i + 1][0]
            dz, dr = _segment_tangent(profile, i, i + 1)
            nx, ny, nz = _surface_normal(dz, dr, 0.0)
            color = _profile_color(i + 1, shank_start_index)
            apex_idx = _add_vertex(positions, normals, colors, 0.0, 0.0, z_apex, nx, ny, nz, color)
            for j in range(segments):
                a0 = ring_a[j]
                a1 = ring_a[(j + 1) % segments]
                indices.extend([a0, a1, apex_idx])
        else:
            for j in range(segments):
                a0 = ring_a[j]
                a1 = ring_a[(j + 1) % segments]
                b1 = ring_b[(j + 1) % segments]
                b0 = ring_b[j]
                indices.extend([a0, a1, b1, a0, b1, b0])

    # Flat caps use their own vertices so side-wall normals are not overwritten.
    z_bottom, r_bottom = profile[0]
    if r_bottom > 1e-9:
        bottom_color = _profile_color(0, shank_start_index)
        center_idx = _add_vertex(positions, normals, colors, 0.0, 0.0, z_bottom, 0.0, 0.0, -1.0, bottom_color)
        cap_ring = _build_cap_ring(positions, normals, colors, z_bottom, r_bottom, -1.0, segments, bottom_color)
        for j in range(segments):
            indices.extend([center_idx, cap_ring[(j + 1) % segments], cap_ring[j]])

    z_top, r_top = profile[-1]
    if r_top > 1e-9:
        top_color = _profile_color(len(profile) - 1, shank_start_index)
        center_idx = _add_vertex(positions, normals, colors, 0.0, 0.0, z_top, 0.0, 0.0, 1.0, top_color)
        cap_ring = _build_cap_ring(positions, normals, colors, z_top, r_top, 1.0, segments, top_color)
        for j in range(segments):
            indices.extend([center_idx, cap_ring[j], cap_ring[(j + 1) % segments]])

    return _pack_vertices(positions, normals, colors), indices, VERTEX_FORMAT


def _tool_diameter(tool_def, scale):
    diameter = getattr(tool_def, "diameter", None) if tool_def else None
    if diameter and diameter > 0:
        return diameter
    return fallback_tool_dimensions(scale)[0]


def effective_tool_diameter(tool_def, scale):
    """Return the outer cutting diameter used for sizing and proportions."""
    diameter = _tool_diameter(tool_def, scale)
    if tool_def and getattr(tool_def, "tool_type", None) is ToolType.RADIUS_MILL:
        corner_radius = getattr(tool_def, "corner_radius", None) or 0.0
        if corner_radius > 0:
            return diameter + 2.0 * corner_radius
    return diameter


def _fallback_stickout_extra(tool_def, diameter):
    """Shank height to add above a cutting-end length used as overall stick-out."""
    shank_diameter = 2.0 * _shank_radius(tool_def, diameter / 2.0)
    return max(diameter, shank_diameter) * FALLBACK_STICKOUT_DIAMETER_FACTOR


def profile_length(tool_def, scale, diameter, shared_length=None):
    """Return the overall stick-out to draw, in file units.

    Shoulder and flute lengths only describe the cutting end, so when the file
    has no stick-out they are extended by a short shank instead of being used
    as-is (post-processors commonly export `sticklength=0`).
    """
    if tool_def:
        length = getattr(tool_def, "length", None)
        if length is not None and length > 0:
            return length
        shoulder_length = getattr(tool_def, "shoulder_length", None)
        if shoulder_length is not None and shoulder_length > 0:
            return shoulder_length + _fallback_stickout_extra(tool_def, diameter)
        flute_length = getattr(tool_def, "flute_length", None)
        if flute_length is not None and flute_length > 0:
            return flute_length + _fallback_stickout_extra(tool_def, diameter)
    if shared_length is not None and shared_length > 0:
        return shared_length
    if tool_def and getattr(tool_def, "diameter", None) and tool_def.diameter > 0:
        return diameter * LENGTH_DIAMETER_FACTOR
    return fallback_tool_dimensions(scale)[1]


def _chamfer_cone_height(diameter, taper_angle_deg=DEFAULT_TAPER_ANGLE_DEG, tip_diameter=0.0):
    """Axial height of the conical cutting tip for chamfer / engraving tools.
    Note that taper_angle_deg is the Fusion-style angle from the tool axis (per side),
    """
    radius = diameter / 2.0
    tip_radius = max(tip_diameter or 0.0, 0.0) / 2.0
    tip_radius = min(tip_radius, radius)

    # Angle from the tool axis
    alpha = math.radians(taper_angle_deg)
    alpha = min(max(alpha, math.radians(5.0)), math.radians(85.0))

    if tip_radius <= 1e-9:
        return radius / math.tan(alpha)
    radial_rise = radius - tip_radius
    if radial_rise <= 1e-9:
        return 0.0
    return radial_rise / math.tan(alpha)


def _lollipop_neck_radius(diameter):
    return diameter / 2.0 * LOLLIPOP_NECK_DIAMETER_FACTOR


def _lollipop_ball_join_z(diameter):
    """Z where the spherical cutter meets the neck cylinder."""
    radius = diameter / 2.0
    neck_radius = _lollipop_neck_radius(diameter)
    theta_join = math.acos(neck_radius / radius)
    return radius + radius * math.sin(theta_join)


def _infer_flute_length(tool_def):
    """Guess flute length from tip geometry when CAM metadata omits it:
    - Chamfer / engraving / drill: Cone height from diameter + taper (+ tip Ø)
    - Lollipop: Sphere -> neck join
    - Ball end: One diameter (hemisphere + short cylinder)
    - Thread mill: One tooth ≈ pitch

    Returns None when the type has no reliable tip-only cue (e.g. flat end mill).
    Only used when building the mesh, this doesn't change tool definitions.
    """
    if not tool_def:
        return None

    tool_type = getattr(tool_def, "tool_type", None)
    diameter = getattr(tool_def, "diameter", None)
    if diameter is None or diameter <= 0:
        return None

    if tool_type is ToolType.LOLLIPOP_MILL:
        return _lollipop_ball_join_z(diameter)

    if tool_type in (ToolType.CHAMFER_MILL, ToolType.ENGRAVING, ToolType.DRILL):
        taper = _safe_taper_angle_deg(tool_def)
        tip_diameter = _safe_tip_diameter(tool_def, diameter)
        height = _chamfer_cone_height(diameter, taper, tip_diameter)
        return height if height > 1e-9 else None

    if tool_type is ToolType.BALL_END_MILL:
        # Hemisphere plus a short matching cylinder — distinctive tip region.
        return diameter

    if tool_type is ToolType.THREAD_MILL:
        return _safe_thread_pitch(tool_def, diameter)

    return None


def _inferred_shoulder_length(tool_def, flute, overall):
    """Short cutting-diameter body above an inferred flute tip."""
    available = overall - flute
    if available <= 1e-9:
        return flute

    diameter = getattr(tool_def, "diameter", None) or 0.0
    extra = min(
        max(diameter, 0.0) * INFERRED_SHOULDER_DIAMETER_FACTOR,
        available * INFERRED_SHOULDER_MAX_FRACTION,
        available,
    )
    return flute + extra


def resolve_section_lengths(tool_def, fallback_overall):
    """Return `(flute_z, shoulder_z, overall_z)` in file units.

    - flute_z: cutting flutes (gold)
    - shoulder_z: end of cutting-diameter body; shank blend starts here
    - overall_z: total stick-out (sticklength)

    When flute length is missing, tip-defined tools (chamfer, lollipop, etc.) get a
    geometry-based guess, otherwise flute falls back to shoulder/overall and is
    capped to FALLBACK_FLUTE_DIAMETER_FACTOR × diameter. When shoulder is also
    missing after a tip inference, a short cutting-diameter shoulder is added so
    the shank does not start at the tip. Explicit flute with no shoulder still
    steps at the flute length. Missing stick-out comes from `fallback_overall`
    (see `profile_length`).
    """
    if not tool_def:
        return fallback_overall, fallback_overall, fallback_overall

    overall = getattr(tool_def, "length", None)
    flute = getattr(tool_def, "flute_length", None)
    shoulder = getattr(tool_def, "shoulder_length", None)
    diameter = getattr(tool_def, "diameter", None) or 0.0

    if overall is None or overall <= 0:
        overall = fallback_overall

    flute_was_inferred = False
    if flute is None or flute <= 0:
        inferred = _infer_flute_length(tool_def)
        if inferred is not None and inferred > 0:
            flute = inferred
            flute_was_inferred = True
        elif shoulder is not None and shoulder > 0:
            flute = shoulder
        else:
            flute = overall
        if diameter > 0:
            flute = min(flute, diameter * FALLBACK_FLUTE_DIAMETER_FACTOR)

    flute = min(flute, overall)

    if shoulder is None or shoulder <= 0:
        if flute_was_inferred:
            shoulder = _inferred_shoulder_length(tool_def, flute, overall)
        else:
            shoulder = flute

    shoulder = min(max(shoulder, flute), overall)
    return flute, shoulder, overall


def _shank_radius(tool_def, cutting_radius):
    shank_diameter = getattr(tool_def, "shank_diameter", None) if tool_def else None
    if shank_diameter is not None and shank_diameter > 0:
        return shank_diameter / 2.0
    return cutting_radius


def _safe_tip_diameter(tool_def, diameter):
    tip_diameter = getattr(tool_def, "tip_diameter", None) if tool_def else None
    if tip_diameter is None or tip_diameter < 0:
        return 0.0
    tip = min(tip_diameter, diameter)
    # Drills are pointed; tip Ø matching cutting Ø is treated as unset.
    if getattr(tool_def, "tool_type", None) is ToolType.DRILL and tip >= diameter - 1e-9:
        return 0.0
    return tip


def _append_shank_geometry(points, shoulder_z, overall_z, shank_radius):
    """Append a conical blend + cylindrical shank above `shoulder_z`.

    When the shank radius differs from the body, a short ~45° cone joins them
    instead of a hard radial step. Returns the extended profile list.
    """
    if not points:
        return points

    points = list(points)
    last_z, last_r = points[-1]
    shoulder_z = max(shoulder_z, last_z)
    if shoulder_z > last_z + 1e-9:
        points.append((shoulder_z, last_r))
        last_z, last_r = shoulder_z, last_r

    if overall_z <= shoulder_z + 1e-9:
        return points

    available = overall_z - shoulder_z
    radial_delta = abs(shank_radius - last_r)
    if radial_delta > 1e-9:
        transition = min(
            radial_delta * SHANK_TRANSITION_SLOPE,
            available * SHANK_TRANSITION_MAX_FRACTION,
            available,
        )
        if transition > 1e-9:
            points.append((shoulder_z + transition, shank_radius))
        else:
            points.append((shoulder_z, shank_radius))

    points.append((overall_z, shank_radius))
    return points


def _safe_corner_radius(tool_def, diameter, tool_type=None):
    corner_radius = getattr(tool_def, "corner_radius", None) if tool_def else None
    if not corner_radius or corner_radius <= 0:
        return 0.0
    if tool_type is ToolType.RADIUS_MILL:
        return corner_radius
    return min(corner_radius, diameter / 2.0)


def _safe_taper_angle_deg(tool_def):
    angle = getattr(tool_def, "taper_angle_deg", None) if tool_def else None
    if angle is None or angle < 0 or angle >= 180:
        tool_type = getattr(tool_def, "tool_type", None) if tool_def else None
        if tool_type is ToolType.DRILL:
            return DEFAULT_DRILL_TAPER_ANGLE_DEG
        return DEFAULT_TAPER_ANGLE_DEG
    return angle


def _safe_thread_depth(tool_def, diameter):
    thread_depth = getattr(tool_def, "thread_depth", None) if tool_def else None
    if not thread_depth or thread_depth <= 0:
        # No parser-provided value: assume a sensible depth based on diameter.
        thread_depth = diameter / 10.0
    return min(thread_depth, diameter / 2.0)


def _safe_thread_pitch(tool_def, diameter):
    thread_pitch = getattr(tool_def, "thread_pitch", None) if tool_def else None
    if not thread_pitch or thread_pitch <= 0:
        # No parser-provided value: assume a sensible pitch based on diameter.
        thread_pitch = diameter / 5.0
    return thread_pitch


def _flat_end_mill_profile(diameter, length, **_kwargs):
    radius = diameter / 2.0
    return [(0.0, radius), (length, radius)]


def _thread_mill_profile(diameter, length, thread_depth=0.0, thread_pitch=0.0, **_kwargs):
    # Thread mills are represented as basic single-point cutters: a flat
    # minor-diameter base, rising over half a pitch to the major diameter
    # (the single cutting tooth), then back down to the minor diameter
    # before continuing as a plain cylindrical shank.
    major_radius = diameter / 2.0
    depth = thread_depth if thread_depth > 0 else diameter / 10.0
    depth = min(depth, major_radius)
    minor_radius = major_radius - depth

    pitch = thread_pitch if thread_pitch > 0 else diameter / 5.0
    pitch = min(pitch, length) if length > 0 else pitch
    half_pitch = pitch / 2.0

    points = [(0.0, minor_radius), (half_pitch, major_radius), (pitch, minor_radius)]
    if length > pitch:
        points.append((length, minor_radius))
    return points


def _ball_end_mill_profile(diameter, length, **_kwargs):
    radius = diameter / 2.0
    points = []
    for i in range(ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = radius * math.cos(theta)
        points.append((z, r))
    if length > radius + 1e-9:
        points.append((length, radius))
    return points


def _bull_nose_profile(diameter, length, corner_radius=0.0, **_kwargs):
    radius = diameter / 2.0
    corner_radius = corner_radius if corner_radius else radius * 0.25
    corner_radius = min(corner_radius, radius)
    flat_radius = radius - corner_radius

    points = [(0.0, max(flat_radius, 0.0))]
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = corner_radius + corner_radius * math.sin(theta)
        r = flat_radius + corner_radius * math.cos(theta)
        points.append((z, r))

    min_length = points[-1][0] + diameter * 0.5
    points.append((max(length, min_length), radius))
    return points


def _radius_mill_profile(diameter, length, corner_radius=0.0, **_kwargs):
    # For radius mills the supplied `diameter` is the flat-bottom diameter.
    # The outer cutting diameter is flat_diameter + 2 * corner_radius.
    flat_radius = diameter / 2.0
    corner_radius = corner_radius if corner_radius else flat_radius * 0.25
    full_radius = flat_radius + corner_radius
    full_diameter = diameter + 2.0 * corner_radius

    if corner_radius <= 1e-9:
        return _flat_end_mill_profile(diameter, length)

    # Concave corner arc: centre at (z=0, r=full_radius), sweeping from
    # the flat bottom out to the full cutting diameter.
    points = [(0.0, flat_radius)]
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = math.pi - (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = corner_radius * math.sin(theta)
        r = full_radius + corner_radius * math.cos(theta)
        points.append((z, r))

    min_length = points[-1][0] + full_diameter * 0.5
    points.append((max(length, min_length), full_radius))
    return points


def _chamfer_or_tapered_profile(diameter, length, taper_angle_deg=DEFAULT_TAPER_ANGLE_DEG, tip_diameter=0.0, **_kwargs):
    """Flat-tip (or pointed) conical profile for chamfer mills and engraving bits.

    `taper_angle_deg` is the angle from the tool axis (as defined in, for instance, Fusion).
    """
    radius = diameter / 2.0
    tip_radius = max(tip_diameter or 0.0, 0.0) / 2.0
    tip_radius = min(tip_radius, radius)
    cone_height = _chamfer_cone_height(diameter, taper_angle_deg, tip_diameter)

    if tip_radius <= 1e-9:
        points = [(0.0, 0.0), (cone_height, radius)]
    else:
        points = [(0.0, tip_radius)]
        if cone_height > 1e-9:
            points.append((cone_height, radius))

    if length > points[-1][0]:
        points.append((length, radius))
    return points


def _tapered_mill_profile(diameter, length, corner_radius=0.0, taper_angle_deg=DEFAULT_TAPER_ANGLE_DEG, **_kwargs):
    """Bull-nose tip of diameter `D`, then a conical taper."""
    tip_radius = diameter / 2.0
    # Per-side angle from the axis (Fusion "Taper angle").
    alpha = math.radians(taper_angle_deg)
    alpha = min(max(alpha, 0.0), math.radians(85.0))

    max_corner = tip_radius / max(math.cos(alpha), 1e-6)
    corner_radius = min(max(corner_radius or 0.0, 0.0), max_corner)

    if corner_radius <= 1e-9:
        # Sharp flat tip at diameter D, then straight taper.
        points = [(0.0, tip_radius)]
        end_radius = tip_radius + length * math.tan(alpha)
        points.append((max(length, diameter * 0.5), end_radius))
        return points

    # Fillet between the flat tip and the cone: same construction as a bull
    # nose, but the arc stops at theta=-alpha where it meets the taper.
    flat_radius = tip_radius - corner_radius * math.cos(alpha)
    theta_start = -math.pi / 2.0
    theta_end = -alpha

    points = [(0.0, max(flat_radius, 0.0))]
    for i in range(1, ROUND_SEGMENTS + 1):
        t = i / ROUND_SEGMENTS
        theta = theta_start + (theta_end - theta_start) * t
        z = corner_radius + corner_radius * math.sin(theta)
        r = flat_radius + corner_radius * math.cos(theta)
        points.append((z, max(r, 0.0)))

    z_tan, r_tan = points[-1]
    # Continue along the taper for the remaining tool length.
    total_length = max(length, z_tan + diameter * 0.5)
    end_radius = r_tan + (total_length - z_tan) * math.tan(alpha)
    points.append((total_length, end_radius))
    return points


def _lollipop_profile(diameter, length, **_kwargs):
    """Full spherical cutter with a thinner cylindrical neck above the undercut."""
    radius = diameter / 2.0
    neck_radius = _lollipop_neck_radius(diameter)
    theta_join = math.acos(neck_radius / radius)

    points = []
    # Lower hemisphere: south pole -> equator (guarantees full cutting diameter).
    for i in range(ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = max(radius * math.cos(theta), 0.0)
        points.append((z, r))

    # Upper hemisphere: equator -> neck join (skip duplicate equator point).
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = theta_join * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = max(radius * math.cos(theta), 0.0)
        points.append((z, r))

    # Snap the join so the cylinder meets the ball at exactly neck_radius.
    ball_join_z = points[-1][0]
    points[-1] = (ball_join_z, neck_radius)

    # Neck extension is optional: overall stick-out above the ball is added by
    # the shoulder/shank pass when flute length ends at the sphere.
    if length > ball_join_z + 1e-9:
        points.append((length, neck_radius))
    return points


DEFAULT_PROFILE_BUILDER = _chamfer_or_tapered_profile
PROFILE_BUILDERS = {
    ToolType.FLAT_END_MILL: _flat_end_mill_profile,
    ToolType.THREAD_MILL: _thread_mill_profile,
    ToolType.BALL_END_MILL: _ball_end_mill_profile,
    ToolType.BULL_NOSE_END_MILL: _bull_nose_profile,
    ToolType.RADIUS_MILL: _radius_mill_profile,
    ToolType.CHAMFER_MILL: _chamfer_or_tapered_profile,
    ToolType.ENGRAVING: _chamfer_or_tapered_profile,
    ToolType.TAPERED_MILL: _tapered_mill_profile,
    ToolType.LOLLIPOP_MILL: _lollipop_profile,
    ToolType.DRILL: _chamfer_or_tapered_profile,
}


def fallback_tool_dimensions(scale):
    """Return (diameter, length) in file units for the no-metadata fallback mesh.

    Values are chosen so that, after multiplication by `scale`, the mesh keeps
    a constant on-screen footprint regardless of file units or job bbox.
    """
    if not scale or scale <= 0:
        scale = 1.0
    diameter = FALLBACK_TOOL_DISPLAY_RADIUS * 2.0 / scale
    length = FALLBACK_TOOL_DISPLAY_HEIGHT / scale
    return diameter, length


def fallback_tool_profile(scale):
    """Pointed fallback profile with a fixed on-screen size."""
    diameter, length = fallback_tool_dimensions(scale)
    return _chamfer_or_tapered_profile(diameter, length)


def _tool_profile_with_shank(tool_def, length=None, scale=1.0):
    """Return `(profile, color_shank_start_index)` for a tool definition.

    Geometry sections (when metadata allows):
    - tip -> flute_z: cutting flutes at tool diameter (gold)
    - flute_z -> shoulder_z: same diameter body / shoulder (gray)
    - shoulder_z -> overall_z: blend + handle/shank diameter (gray)

    Falls back to a basic pointed (chamfer-like) profile when `tool_def` is
    None or its type is unknown/unsupported (see DEFAULT_PROFILE_BUILDER).
    Missing diameters use the fixed on-screen fallback size.
    """
    diameter = _tool_diameter(tool_def, scale)
    effective_diameter = effective_tool_diameter(tool_def, scale)
    fallback_overall = profile_length(tool_def, scale, effective_diameter, length)
    flute_z, shoulder_z, overall_z = resolve_section_lengths(tool_def, fallback_overall)
    tool_type = getattr(tool_def, "tool_type", ToolType.UNKNOWN) if tool_def else ToolType.UNKNOWN
    corner_radius = _safe_corner_radius(tool_def, diameter, tool_type)
    taper_angle_deg = _safe_taper_angle_deg(tool_def)
    tip_diameter = _safe_tip_diameter(tool_def, diameter)
    thread_depth = _safe_thread_depth(tool_def, diameter)
    thread_pitch = _safe_thread_pitch(tool_def, diameter)

    builder = PROFILE_BUILDERS.get(tool_type, DEFAULT_PROFILE_BUILDER)

    profile = builder(
        diameter,
        flute_z,
        corner_radius=corner_radius,
        taper_angle_deg=taper_angle_deg,
        tip_diameter=tip_diameter,
        thread_depth=thread_depth,
        thread_pitch=thread_pitch,
    )

    profile = list(profile)
    last_z, last_r = profile[-1]
    # Tip geometry (e.g. ball nose) may already exceed the requested flute length.
    flute_tip_z = max(flute_z, last_z)
    if flute_tip_z > last_z + 1e-9:
        profile.append((flute_tip_z, last_r))
        last_z, last_r = flute_tip_z, last_r
    else:
        flute_tip_z = last_z

    shoulder_z = max(shoulder_z, flute_tip_z)
    overall_z = max(overall_z, shoulder_z)

    has_non_flute = overall_z > flute_tip_z + 1e-9
    if has_non_flute:
        color_start = len(profile)
        # Coincident ring -> hard gold/gray edge at the end of the flutes.
        profile.append((flute_tip_z, last_r))
    else:
        color_start = len(profile)

    if shoulder_z > flute_tip_z + 1e-9:
        profile.append((shoulder_z, last_r))

    cutting_radius = last_r
    profile = _append_shank_geometry(
        profile,
        shoulder_z,
        overall_z,
        _shank_radius(tool_def, cutting_radius),
    )
    return profile, color_start


def tool_profile(tool_def, length=None, scale=1.0):
    """Return the (unscaled) profile for a tool definition."""
    profile, _shank_start = _tool_profile_with_shank(tool_def, length=length, scale=scale)
    return profile


def _scale_profile(profile, scale):
    """Scale profile into viewer units, with a per-tool radius visibility floor.

    If this tool's scaled radius would be below MIN_VISIBLE_RADIUS, enlarge only
    that tool (uniformly in Z and R) so it stays visible. Other tools are
    unaffected.
    """
    if not scale or scale <= 0:
        scale = 1.0
    scaled_profile = [(z * scale, r * scale) for z, r in profile]

    max_radius = max((r for _z, r in scaled_profile), default=0.0)
    if 0.0 < max_radius < MIN_VISIBLE_RADIUS:
        boost = MIN_VISIBLE_RADIUS / max_radius
        scaled_profile = [(z * boost, r * boost) for z, r in scaled_profile]

    total_length = scaled_profile[-1][0] if scaled_profile else 0.0
    if total_length < MIN_SHANK_LENGTH:
        shank_radius = scaled_profile[-1][1]
        scaled_profile = scaled_profile[:-1] + [(MIN_SHANK_LENGTH, shank_radius)]

    return scaled_profile


def build_tool_mesh(tool_def, scale=1.0, length=None):
    profile, shank_start = _tool_profile_with_shank(tool_def, length=length, scale=scale)
    scaled_profile = _scale_profile(profile, scale)
    return _build_revolve_mesh(scaled_profile, shank_start_index=shank_start)


def build_default_tool_mesh(scale=1.0):
    """Mesh used for tools with no metadata (fixed on-screen size)."""
    profile = fallback_tool_profile(scale)
    scaled_profile = _scale_profile(profile, scale)
    return _build_revolve_mesh(scaled_profile)


def build_tool_meshes(tool_table, scale=1.0):
    """Build a mesh for every tool in `tool_table`, plus a default mesh for
    tools with no metadata.

    Tools without stick-out metadata use LENGTH_DIAMETER_FACTOR × their own
    diameter. Tools that provide length / shoulder / flute use those heights.
    Each tool is scaled independently; only tools below MIN_VISIBLE_RADIUS get
    a per-tool visibility floor.

    The default (no-metadata) mesh keeps a fixed on-screen size, independent
    of file units.

    Returns `(tool_meshes, default_mesh)`.
    """
    default_profile = fallback_tool_profile(scale)

    if tool_table:
        tool_meshes = {}
        for number, tool_def in tool_table.items():
            profile, shank_start = _tool_profile_with_shank(tool_def, scale=scale)
            tool_meshes[number] = _build_revolve_mesh(
                _scale_profile(profile, scale),
                shank_start_index=shank_start,
            )
    else:
        tool_meshes = {}

    default_mesh = _build_revolve_mesh(_scale_profile(default_profile, scale))
    return tool_meshes, default_mesh
