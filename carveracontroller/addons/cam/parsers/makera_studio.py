"""Parser for metadata written by Makera Studio.

Makera Studio writes a `;@MKR|...` metadata block at the top of the G-code
file. Tools, stock, and origin are one line each:

;@MKR|TOOL|number=<int>|id=<string>|name=<string>|type=<string>|handlediameter=<float>|sticklength=<float>|shoulderlength=<float>|flutelength=<float>|diameter=<float>|tipdiameter=<float>|cornerradius=<float>|angle=<float>|halfAngle=<float>
;@MKR|STOCK|id=cuboid|length=<float>|width=<float>|height=<float>|diameter=<float>
;@MKR|ORIGIN|id=<int>|type_name=<camelCase>|x=<float>|y=<float>|z=<float>

STOCK ``id`` is ``cuboid`` (rectangular) or ``cylinder``. Unused fields are
still emitted (e.g. diameter on a cuboid) and must be ignored.

Makera's cuboid ``length`` is the X extent and ``width`` is the Y extent.

ORIGIN ``type_name`` follows ``topFrontLeft``, ``topCenter``, ``leftCenter``,
etc. Coordinates are the WCS origin relative to the stock centre, in document
units; they are converted to the viewer's named-corner + residual offset.
"""

import logging

from carveracontroller.addons.cam.metadata import CamMetadata, CamStock
from carveracontroller.addons.cam.parsers.base import CamHeaderParser
from carveracontroller.addons.stock.stock_origin import (
    CORNER_BC,
    CORNER_BL,
    CORNER_BR,
    CORNER_CENTER,
    CORNER_FC,
    CORNER_LC,
    CORNER_RC,
    CORNER_TL,
    CORNER_TR,
    named_origin_relative_to_center,
)
from carveracontroller.addons.tool_visualization.tool_definition import (
    ToolDefinition,
    ToolType,
    normalize_tool_type_name,
    resolve_tool_type,
)

logger = logging.getLogger(__name__)

# Tool type names as exported by Makera Studio (`type=` field).
TOOL_TYPE_NAME_MAP = {
    "flat end": ToolType.FLAT_END_MILL,
    "ball nose": ToolType.BALL_END_MILL,
    "v-bit": ToolType.CHAMFER_MILL,
    "engraving": ToolType.ENGRAVING,
    "bull nose": ToolType.BULL_NOSE_END_MILL,
    "drill": ToolType.DRILL,
    "thread": ToolType.THREAD_MILL,
    "tapered ball nose": ToolType.TAPERED_MILL,
}

_MKR_PREFIX = ";@MKR|"
_TOOL_TAG = "TOOL"
_STOCK_TAG = "STOCK"
_ORIGIN_TAG = "ORIGIN"

# Longest-first so "bottom" wins over "back"/"top" when scanning type_name.
_ORIGIN_KEYWORDS = ("bottom", "center", "front", "right", "left", "back", "top")
_X_TOKEN = {"left": "min", "right": "max"}
_Y_TOKEN = {"front": "min", "back": "max"}
_Z_TOKEN = {"top": "top", "bottom": "bottom"}


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _positive_or_none(value):
    if value is None or value <= 0:
        return None
    return value


def _parse_mkr_fields(line):
    """Return (tag, fields_dict) for a `;@MKR|TAG|k=v|...` line, or None."""
    stripped = line.strip()
    if not stripped.startswith(_MKR_PREFIX):
        return None

    parts = stripped[len(_MKR_PREFIX) :].split("|")
    if not parts:
        return None

    tag = parts[0]
    fields = {}
    for part in parts[1:]:
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            continue
        fields[key] = value
    return tag, fields


def _taper_angle_from_fields(fields):
    """Return Fusion-style taper: angle from the tool axis (per side), in degrees.

    Prefer `halfAngle` when set. Makera's `angle` is the included tip angle, so
    convert it to per-side when that is the only source.
    """
    half_angle = _to_float(fields.get("halfAngle"))
    if half_angle is not None and half_angle > 0:
        return half_angle
    angle = _to_float(fields.get("angle"))
    if angle is not None and angle > 0:
        return angle / 2.0
    return None


def _stick_length_from_fields(fields):
    """Overall stick-out: prefer sticklength, fall back to shoulderlength."""
    stick = _positive_or_none(_to_float(fields.get("sticklength")))
    if stick is not None:
        return stick
    return _positive_or_none(_to_float(fields.get("shoulderlength")))


def _origin_tokens(type_name):
    """Split a Makera origin type_name into keywords (top, front, left, ...)."""
    text = (type_name or "").strip().lower()
    tokens = []
    i = 0
    while i < len(text):
        matched = False
        for keyword in _ORIGIN_KEYWORDS:
            if text.startswith(keyword, i):
                tokens.append(keyword)
                i += len(keyword)
                matched = True
                break
        if not matched:
            i += 1
    return tokens


def _xy_corner_from_positions(x_pos, y_pos):
    if x_pos == "center" and y_pos == "center":
        return CORNER_CENTER
    if x_pos == "min" and y_pos == "min":
        return CORNER_BL
    if x_pos == "max" and y_pos == "min":
        return CORNER_BR
    if x_pos == "min" and y_pos == "max":
        return CORNER_TL
    if x_pos == "max" and y_pos == "max":
        return CORNER_TR
    if x_pos == "min" and y_pos == "center":
        return CORNER_LC
    if x_pos == "max" and y_pos == "center":
        return CORNER_RC
    if x_pos == "center" and y_pos == "min":
        return CORNER_FC
    if x_pos == "center" and y_pos == "max":
        return CORNER_BC
    return None


def parse_origin_type_name(type_name):
    """Return ``(xy_corner, z_reference)`` for a Makera ``type_name``, or None."""
    tokens = _origin_tokens(type_name)
    if not tokens:
        return None

    x_pos = None
    y_pos = None
    z_ref = None
    has_center = False
    for token in tokens:
        if token in _X_TOKEN:
            x_pos = _X_TOKEN[token]
        elif token in _Y_TOKEN:
            y_pos = _Y_TOKEN[token]
        elif token in _Z_TOKEN:
            z_ref = _Z_TOKEN[token]
        elif token == "center":
            has_center = True

    if x_pos is None:
        x_pos = "center" if has_center or y_pos is not None or z_ref is not None else None
    if y_pos is None:
        y_pos = "center" if has_center or x_pos is not None else None
    if z_ref is None:
        z_ref = "center" if has_center else "top"

    if x_pos is None or y_pos is None:
        return None

    xy_corner = _xy_corner_from_positions(x_pos, y_pos)
    if xy_corner is None:
        return None
    return xy_corner, z_ref


def _build_cam_stock(stock_fields, origin_fields):
    """Build a CamStock from Makera STOCK/ORIGIN field dicts, or None."""
    stock_id = (stock_fields.get("id") or "").strip().lower()
    origin_type = (origin_fields or {}).get("type_name") or ""
    parsed_origin = parse_origin_type_name(origin_type)
    if parsed_origin is not None:
        xy_corner, z_reference = parsed_origin
    else:
        if origin_type:
            logger.warning(f"Unrecognised Makera Studio origin type_name {origin_type!r}; defaulting to bl/top")
        xy_corner, z_reference = "bl", "top"

    if stock_id == "cuboid":
        # /!\ length -> X (our width_mm), width -> Y (our length_mm) /!\
        width_mm = _positive_or_none(_to_float(stock_fields.get("length")))
        length_mm = _positive_or_none(_to_float(stock_fields.get("width")))
        height_mm = _positive_or_none(_to_float(stock_fields.get("height")))
        if width_mm is None or length_mm is None or height_mm is None:
            logger.warning("Ignoring Makera Studio cuboid STOCK with missing or non-positive length/width/height")
            return None
        kind = "rectangular"
        diameter_mm = None
        dx, dy, dz = width_mm, length_mm, height_mm
    elif stock_id == "cylinder":
        diameter_mm = _positive_or_none(_to_float(stock_fields.get("diameter")))
        if diameter_mm is None:
            logger.warning("Ignoring Makera Studio cylinder STOCK with missing or non-positive diameter")
            return None
        # Cylinder is a 4-axis bar unless the origin is a mill top/bottom placement.
        is_rotary = parsed_origin is None or z_reference == "center"
        if is_rotary:
            length_mm = _positive_or_none(_to_float(stock_fields.get("length")))
            if length_mm is None:
                logger.warning("Ignoring Makera Studio rotary cylinder STOCK with missing or non-positive length")
                return None
            kind = "rotary_cylindrical"
            width_mm = None
            height_mm = None
            dx, dy, dz = length_mm, diameter_mm, diameter_mm
        else:
            height_mm = _positive_or_none(_to_float(stock_fields.get("height")))
            if height_mm is None:
                logger.warning("Ignoring Makera Studio mill cylinder STOCK with missing or non-positive height")
                return None
            kind = "cylindrical"
            width_mm = None
            length_mm = None
            dx, dy, dz = diameter_mm, diameter_mm, height_mm
    else:
        if stock_id:
            logger.warning(f"Ignoring unrecognised Makera Studio STOCK id {stock_id!r}")
        return None

    if origin_fields:
        mkr_x = _to_float(origin_fields.get("x"))
        mkr_y = _to_float(origin_fields.get("y"))
        mkr_z = _to_float(origin_fields.get("z"))
        if mkr_x is None:
            mkr_x = 0.0
        if mkr_y is None:
            mkr_y = 0.0
        if mkr_z is None:
            mkr_z = 0.0
        geo_x, geo_y, geo_z = named_origin_relative_to_center(dx, dy, dz, xy_corner, z_reference)
        offset_x_mm = geo_x - mkr_x
        offset_y_mm = geo_y - mkr_y
        offset_z_mm = geo_z - mkr_z
    else:
        offset_x_mm = 0.0
        offset_y_mm = 0.0
        offset_z_mm = 0.0

    return CamStock(
        kind=kind,
        width_mm=width_mm,
        length_mm=length_mm,
        height_mm=height_mm,
        diameter_mm=diameter_mm,
        xy_corner=xy_corner,
        z_reference=z_reference,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
        offset_z_mm=offset_z_mm,
    )


class MakeraStudioParser(CamHeaderParser):
    name = "makera_studio"

    def parse(self, lines):
        return self.parse_metadata(lines).tool_table

    def parse_metadata(self, lines, unit_scale=1.0) -> CamMetadata:
        tool_table = {}
        stock_fields = None
        origin_fields = None

        for raw_line in self.iter_header_lines(lines):
            parsed = _parse_mkr_fields(raw_line)
            if parsed is None:
                continue

            tag, fields = parsed
            if tag == _TOOL_TAG:
                number = _to_int(fields.get("number"))
                if number is None:
                    continue
                if number in tool_table:
                    logger.debug(f"Ignoring duplicate Makera Studio tool comment for T{number}: {raw_line.strip()}")
                    continue

                tool_def = self._build_tool_definition(number, fields)
                tool_table[number] = tool_def

                if tool_def.tool_type is ToolType.UNKNOWN:
                    logger.warning(
                        f"Detected T{number} ({tool_def.description!r}, D={tool_def.diameter}) "
                        f"with unrecognised tool type {tool_def.type_name!r}; defaulting to a basic pointed mesh"
                    )
                else:
                    dims = f"D={tool_def.diameter}, CR={tool_def.corner_radius}"
                    if tool_def.taper_angle_deg is not None:
                        dims += f", TAPER={tool_def.taper_angle_deg}"
                    logger.info(f"Detected T{number}: {tool_def.tool_type.value} ({dims}) - {tool_def.description!r}")
            elif tag == _STOCK_TAG:
                if stock_fields is None:
                    stock_fields = fields
            elif tag == _ORIGIN_TAG:
                if origin_fields is None:
                    origin_fields = fields

        stock = None
        if stock_fields is not None:
            stock = _build_cam_stock(stock_fields, origin_fields)
            if stock is not None:
                stock = stock.scaled(unit_scale)
                logger.info(
                    f"Detected Makera Studio stock: {stock.kind} "
                    f"origin {stock.xy_corner}/{stock.z_reference} "
                    f"offset=({stock.offset_x_mm:g}, {stock.offset_y_mm:g}, {stock.offset_z_mm:g})"
                )

        return CamMetadata(parser_name=self.name, tool_table=tool_table, stock=stock)

    @staticmethod
    def _build_tool_definition(number, fields):
        type_name = fields.get("type", "") or ""
        tool_type = resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP)
        handle_diameter = _positive_or_none(_to_float(fields.get("handlediameter")))
        diameter = _to_float(fields.get("diameter"))
        tip_diameter = _to_float(fields.get("tipdiameter"))
        corner_radius = _to_float(fields.get("cornerradius"))

        # Tapered Ball Nose is a ball tip (CR = D/2) with a conical taper above.
        if normalize_tool_type_name(type_name) == "tapered ball nose" and diameter is not None and diameter > 0:
            if corner_radius is None or corner_radius <= 0:
                corner_radius = diameter / 2.0

        return ToolDefinition(
            number=number,
            tool_type=tool_type,
            diameter=diameter,
            shank_diameter=handle_diameter,
            tip_diameter=tip_diameter,
            corner_radius=corner_radius,
            taper_angle_deg=_taper_angle_from_fields(fields),
            length=_stick_length_from_fields(fields),
            flute_length=_positive_or_none(_to_float(fields.get("flutelength"))),
            shoulder_length=_positive_or_none(_to_float(fields.get("shoulderlength"))),
            description=fields.get("name", "") or "",
            product_id=fields.get("id", "") or "",
            type_name=type_name,
        )
