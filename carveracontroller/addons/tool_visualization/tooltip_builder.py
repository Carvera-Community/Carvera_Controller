"""Format tool definitions as toolbar tooltip text for the G-code viewer."""

from carveracontroller.addons.tool_visualization.tool_definition import ToolType
from carveracontroller.CNC import escape_gcode_markup
from carveracontroller.translation import tr
from carveracontroller.ui.theme import get_theme, rgba_to_hex

TOOL_TYPE_MSGIDS = {
    ToolType.FLAT_END_MILL: "Flat End Mill",
    ToolType.BALL_END_MILL: "Ball End Mill",
    ToolType.BULL_NOSE_END_MILL: "Bull Nose End Mill",
    ToolType.RADIUS_MILL: "Radius Mill",
    ToolType.CHAMFER_MILL: "Chamfer Mill",
    ToolType.ENGRAVING: "Engraving",
    ToolType.TAPERED_MILL: "Tapered Mill",
    ToolType.LOLLIPOP_MILL: "Lollipop Mill",
    ToolType.THREAD_MILL: "Thread Mill",
    ToolType.DRILL: "Drill",
}

# Title / labels sizes
_TITLE_SIZE = "17sp"
_DESCRIPTION_SIZE = "13sp"
_CATALOG_SIZE = "12sp"


# Dim grey for labels and separators; values stay at the default colour.
def _label_color_hex() -> str:
    return rgba_to_hex(get_theme().text_label)


_MAX_ITEMS_PER_LINE = 3
_MAX_LINE_CHARS = 42
_SEP_PLAIN = " · "


def format_tool_type_label(tool_def):
    """Return a localized tool-type label, or the raw CAM type name."""
    # Prefer our canonical labels when the type is known
    msgid = TOOL_TYPE_MSGIDS.get(tool_def.tool_type)
    if msgid:
        return tr._(msgid)
    # Unknown types: keep the raw CAM name as-is
    return (tool_def.type_name or "").strip()


def _is_meaningful(value):
    """Return True when a numeric field should be shown (present and non-zero)."""
    return value is not None and value != 0


def _unit_label(unit):
    return "in" if unit == "in" else "mm"


def _format_linear_value(value, unit):
    return tr._("{value:g} {unit}").format(value=value, unit=_unit_label(unit))


def _make_item(label, value_str, *, markup):
    """Return ``(plain_text, display_text)`` for one dimension item."""
    plain = f"{label} {value_str}"
    if markup:
        display = f"[color=#{_label_color_hex()}]{escape_gcode_markup(label)}[/color] {escape_gcode_markup(value_str)}"
    else:
        display = plain
    return plain, display


def _pack_group(items, *, markup):
    """Greedily pack items onto lines (max items / char budget)."""
    if not items:
        return []

    sep_display = f" [color=#{_label_color_hex()}]·[/color] " if markup else _SEP_PLAIN
    lines = []
    current_plain = []
    current_display = []

    for plain, display in items:
        if not current_plain:
            current_plain = [plain]
            current_display = [display]
            continue

        candidate_len = sum(len(part) for part in current_plain) + len(plain) + len(current_plain) * len(_SEP_PLAIN)
        if len(current_plain) >= _MAX_ITEMS_PER_LINE or candidate_len > _MAX_LINE_CHARS:
            lines.append(sep_display.join(current_display))
            current_plain = [plain]
            current_display = [display]
        else:
            current_plain.append(plain)
            current_display.append(display)

    if current_display:
        lines.append(sep_display.join(current_display))
    return lines


def _format_dimension_lines(tool_def, *, unit="mm", markup=True):
    """Build grouped dimension rows, skipping redundant/noise fields."""
    geometry = []
    lengths = []
    thread = []

    if tool_def.diameter is not None:
        geometry.append(_make_item("Ø", _format_linear_value(tool_def.diameter, unit), markup=markup))

    # Shank is noise when it matches the cutting diameter (common inferred default).
    if _is_meaningful(tool_def.shank_diameter) and tool_def.shank_diameter != tool_def.diameter:
        geometry.append(_make_item(tr._("Shank"), _format_linear_value(tool_def.shank_diameter, unit), markup=markup))

    if _is_meaningful(tool_def.corner_radius):
        geometry.append(
            _make_item(
                tr._("Corner radius"),
                _format_linear_value(tool_def.corner_radius, unit),
                markup=markup,
            )
        )

    # Tip Ø is noise when it matches the cutting diameter (flat/ball/drill exports).
    if _is_meaningful(tool_def.tip_diameter) and tool_def.tip_diameter != tool_def.diameter:
        geometry.append(
            _make_item(
                tr._("Tip diameter"),
                _format_linear_value(tool_def.tip_diameter, unit),
                markup=markup,
            )
        )

    if _is_meaningful(tool_def.taper_angle_deg):
        taper_value = tr._("{value:g}°").format(value=tool_def.taper_angle_deg)
        geometry.append(_make_item(tr._("Taper"), taper_value, markup=markup))

    if _is_meaningful(tool_def.length):
        lengths.append(_make_item(tr._("Length"), _format_linear_value(tool_def.length, unit), markup=markup))

    if _is_meaningful(tool_def.flute_length):
        lengths.append(_make_item(tr._("Flute"), _format_linear_value(tool_def.flute_length, unit), markup=markup))

    if _is_meaningful(tool_def.shoulder_length):
        lengths.append(
            _make_item(
                tr._("Shoulder"),
                _format_linear_value(tool_def.shoulder_length, unit),
                markup=markup,
            )
        )

    if _is_meaningful(tool_def.thread_pitch):
        thread.append(_make_item(tr._("Pitch"), _format_linear_value(tool_def.thread_pitch, unit), markup=markup))

    if _is_meaningful(tool_def.thread_depth):
        thread.append(
            _make_item(
                tr._("Thread depth"),
                _format_linear_value(tool_def.thread_depth, unit),
                markup=markup,
            )
        )

    lines = []
    for group in (geometry, lengths, thread):
        lines.extend(_pack_group(group, markup=markup))
    return lines


def _format_catalog_line(tool_def):
    return tool_def.vendor or ""


def format_tool_tooltip(tool_def, *, markup=True, unit="mm"):
    """Return multi-line tooltip text for a parsed tool, or an empty string.

    When *markup* is True (default), the string includes Kivy Label markup for
    hierarchy (larger title, dim labels). Pass markup=False for plain text
    consumers such as the tool-change confirm popup.

    *unit* is ``"mm"`` or ``"in"`` and is appended to linear dimensions.
    """
    if tool_def is None:
        return ""

    title = f"T{tool_def.number}"
    type_label = format_tool_type_label(tool_def)
    if type_label:
        title = f"{title} · {type_label}"

    description = tool_def.description or ""
    catalog = _format_catalog_line(tool_def)

    if markup:
        title = f"[size={_TITLE_SIZE}]{escape_gcode_markup(title)}[/size]"
        if description:
            description = f"[size={_DESCRIPTION_SIZE}]{escape_gcode_markup(description)}[/size]"
        if catalog:
            catalog = (
                f"[size={_CATALOG_SIZE}][color=#{_label_color_hex()}]{escape_gcode_markup(catalog)}[/color][/size]"
            )
    else:
        # Plain path: identity fields stay as-is (already plain).
        pass

    identity = [title]
    if description:
        identity.append(description)
    if catalog:
        identity.append(catalog)

    sections = ["\n".join(identity)]

    dimension_lines = _format_dimension_lines(tool_def, unit=unit, markup=markup)
    if dimension_lines:
        sections.append("\n".join(dimension_lines))

    return "\n\n".join(sections)
