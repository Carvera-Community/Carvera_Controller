"""Parser for tool tables written by the Fusion 360 Makera post processor.

The post processor's `dumpToolInformation()` CPS function writes one comment
line per tool, on its own line, with the following layout:

T<number>  <description>  <vendor>  <productId>  D=<diameter>
  [CR=<cornerRadius>] [SD=<shaftDiameter>] [TD=<tipDiameter>] [FL=<fluteLength>]
  [SL=<shoulderLength>] [BL=<bodyLength>] [TP=<threadPitch>] [TAPER=<angle>deg]
  [- ZMIN=<zmin>] - <toolTypeName>

TAPER is Fusion's taperAngle in degrees: per-side from the tool axis for mills,
or the included tip/point angle for drills (converted to per-side on parse).

Stock and origin, when present:

(@F360|STOCK|id=box|width=<float>|depth=<float>|height=<float>)
(@F360|STOCK|id=cylinder|width=<float>|depth=<float>|height=<float>|diameter=<float>)
(@F360|STOCK|id=tube|width=<float>|depth=<float>|height=<float>|diameter=<float>)
(@F360|ORIGIN|type_name=<camelCase>|x=<float>|y=<float>|z=<float>)

``width`` is the X extent and ``depth`` is the Y extent.
"""

import logging
import re

from carveracontroller.addons.cam.metadata import CamMetadata, CamStock
from carveracontroller.addons.cam.parsers.base import CamHeaderParser
from carveracontroller.addons.cam.parsers.makera_studio import parse_origin_type_name
from carveracontroller.addons.stock.stock_origin import named_origin_relative_to_center
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType, resolve_tool_type

logger = logging.getLogger(__name__)

# Tool type names as exported by the getToolTypeName() function of Fusion.
TOOL_TYPE_NAME_MAP = {
    "flat end mill": ToolType.FLAT_END_MILL,
    "ball end mill": ToolType.BALL_END_MILL,
    "bull nose end mill": ToolType.BULL_NOSE_END_MILL,
    "radius mill": ToolType.RADIUS_MILL,
    "chamfer mill": ToolType.CHAMFER_MILL,
    "tapered mill": ToolType.TAPERED_MILL,
    "lollipop mill": ToolType.LOLLIPOP_MILL,
    "thread mill": ToolType.THREAD_MILL,
    "drill": ToolType.DRILL,
}

_NUMBER = r"[-+]?\d+\.?\d*"

TOOL_LINE_RE = re.compile(
    r"^T(?P<number>\d+)\s+(?P<middle>.*?)\s+D=(?P<diameter>" + _NUMBER + r")"
    r"(?:\s+CR=(?P<corner_radius>" + _NUMBER + r"))?"
    r"(?:\s+SD=(?P<shaft_diameter>" + _NUMBER + r"))?"
    r"(?:\s+TD=(?P<tip_diameter>" + _NUMBER + r"))?"
    r"(?:\s+FL=(?P<flute_length>" + _NUMBER + r"))?"
    r"(?:\s+SL=(?P<shoulder_length>" + _NUMBER + r"))?"
    r"(?:\s+BL=(?P<body_length>" + _NUMBER + r"))?"
    r"(?:\s+TP=(?P<thread_pitch>" + _NUMBER + r"))?"
    r"(?:\s+TAPER=(?P<taper>" + _NUMBER + r")deg)?"
    r"(?:\s*-\s*ZMIN=" + _NUMBER + r")?"
    r"\s*-\s*(?P<type_name>.+?)\s*$",
    re.IGNORECASE,
)

_FIELD_SPLIT_RE = re.compile(r"\s{2,}")

_F360_PREFIX = "@F360|"
_STOCK_TAG = "STOCK"
_ORIGIN_TAG = "ORIGIN"


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _positive_or_none(value):
    if value is None or value <= 0:
        return None
    return value


def _taper_angle_from_fusion(tool_type, taper_deg):
    """Return Fusion TAPER as angle from the tool axis (per side), in degrees.

    For mills, Fusion's taperAngle is already per-side. For drills, TAPER is the
    included tip/point angle, so convert to per-side.
    """
    if taper_deg is None:
        return None
    if tool_type is ToolType.DRILL:
        return taper_deg / 2.0
    return taper_deg


def _infer_shank_diameter(tool_type, diameter, corner_radius=None):
    """Infer shank diameter from Fusion cutting geometry.

    Returns None when diameter is missing or the type's shaft cannot be derived
    from cutting geometry alone (tapered tip/lollipop ball).
    """
    if diameter is None or diameter <= 0:
        return None
    if tool_type is ToolType.RADIUS_MILL:
        return diameter + 2.0 * (corner_radius or 0.0)
    if tool_type in (ToolType.TAPERED_MILL, ToolType.LOLLIPOP_MILL):
        return None
    return diameter


def _extract_full_line_comment(line):
    """Return the text of a comment if the whole (stripped) line is one, else None."""
    if len(line) >= 2 and line[0] == "(" and line[-1] == ")":
        return line[1:-1]
    if line.startswith(";"):
        return line[1:]
    return None


def _parse_f360_fields(comment_text):
    """Return (tag, fields_dict) for an `@F360|TAG|k=v|...` payload, or None."""
    stripped = comment_text.strip()
    if not stripped.startswith(_F360_PREFIX):
        return None

    parts = stripped[len(_F360_PREFIX) :].split("|")
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


def _origin_corner_from_type_name(type_name):
    """Return ``(xy_corner, z_reference)`` for a Fusion ORIGIN ``type_name``."""
    parsed = parse_origin_type_name(type_name)
    if parsed is not None:
        return parsed
    if (type_name or "").strip().lower() == "custom":
        return "center", "top"
    if type_name:
        logger.warning(f"Unrecognised Fusion 360 origin type_name {type_name!r}; defaulting to bl/top")
    return "bl", "top"


def _infer_cylinder_axis(x_mm, y_mm, z_mm):
    """Return ``x``, ``y``, or ``z`` when one axis is clearly the cylinder axis."""
    if x_mm is None or y_mm is None or z_mm is None:
        return None
    xy = abs(x_mm - y_mm)
    xz = abs(x_mm - z_mm)
    yz = abs(y_mm - z_mm)
    if xy == xz == yz:
        return None
    if xy <= xz and xy <= yz:
        return "z"
    if xz <= yz:
        return "y"
    return "x"


def _build_cam_stock(stock_fields, origin_fields):
    """Build a CamStock from Fusion STOCK/ORIGIN field dicts, or None."""
    stock_id = (stock_fields.get("id") or "").strip().lower()
    origin_type = (origin_fields or {}).get("type_name") or ""
    xy_corner, z_reference = _origin_corner_from_type_name(origin_type)

    if stock_id == "box":
        width_mm = _positive_or_none(_to_float(stock_fields.get("width")))
        length_mm = _positive_or_none(_to_float(stock_fields.get("depth")))
        height_mm = _positive_or_none(_to_float(stock_fields.get("height")))
        if width_mm is None or length_mm is None or height_mm is None:
            logger.warning("Ignoring Fusion 360 box STOCK with missing or non-positive width/depth/height")
            return None
        kind = "rectangular"
        diameter_mm = None
        dx, dy, dz = width_mm, length_mm, height_mm
    elif stock_id in ("cylinder", "tube"):
        diameter_mm = _positive_or_none(_to_float(stock_fields.get("diameter")))
        if diameter_mm is None:
            logger.warning(f"Ignoring Fusion 360 {stock_id} STOCK with missing or non-positive diameter")
            return None
        x_mm = _positive_or_none(_to_float(stock_fields.get("width")))
        y_mm = _positive_or_none(_to_float(stock_fields.get("depth")))
        z_mm = _positive_or_none(_to_float(stock_fields.get("height")))
        axis = _infer_cylinder_axis(x_mm, y_mm, z_mm)
        if axis == "y":
            logger.warning(f"Ignoring Fusion 360 {stock_id} STOCK with unsupported Y-axis orientation")
            return None
        if axis == "x":
            is_rotary = True
        elif axis == "z":
            is_rotary = False
        else:
            is_rotary = z_reference == "center"
        if is_rotary:
            length_mm = x_mm
            if length_mm is None:
                logger.warning(f"Ignoring Fusion 360 rotary {stock_id} STOCK with missing or non-positive width")
                return None
            if (origin_type or "").strip().lower() == "custom":
                xy_corner, z_reference = "center", "center"
            kind = "rotary_cylindrical"
            width_mm = None
            height_mm = None
            dx, dy, dz = length_mm, diameter_mm, diameter_mm
        else:
            height_mm = z_mm
            if height_mm is None:
                logger.warning(f"Ignoring Fusion 360 mill {stock_id} STOCK with missing or non-positive height")
                return None
            kind = "cylindrical"
            width_mm = None
            length_mm = None
            dx, dy, dz = diameter_mm, diameter_mm, height_mm
    else:
        if stock_id:
            logger.warning(f"Ignoring unrecognised Fusion 360 STOCK id {stock_id!r}")
        return None

    if origin_fields:
        origin_x = _to_float(origin_fields.get("x"))
        origin_y = _to_float(origin_fields.get("y"))
        origin_z = _to_float(origin_fields.get("z"))
        if origin_x is None:
            origin_x = 0.0
        if origin_y is None:
            origin_y = 0.0
        if origin_z is None:
            origin_z = 0.0
        geo_x, geo_y, geo_z = named_origin_relative_to_center(dx, dy, dz, xy_corner, z_reference)
        offset_x_mm = geo_x - origin_x
        offset_y_mm = geo_y - origin_y
        offset_z_mm = geo_z - origin_z
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


class Fusion360MakeraParser(CamHeaderParser):
    name = "fusion360_makera"

    def parse(self, lines):
        return self.parse_metadata(lines).tool_table

    def parse_metadata(self, lines, unit_scale=1.0) -> CamMetadata:
        tool_table = {}
        stock_fields = None
        origin_fields = None

        for raw_line in self.iter_header_lines(lines):
            line = raw_line.strip()
            if not line:
                continue

            comment_text = _extract_full_line_comment(line)
            if comment_text is None:
                continue

            parsed = _parse_f360_fields(comment_text)
            if parsed is not None:
                tag, fields = parsed
                if tag == _STOCK_TAG:
                    if stock_fields is None:
                        stock_fields = fields
                elif tag == _ORIGIN_TAG:
                    if origin_fields is None:
                        origin_fields = fields
                continue

            match = TOOL_LINE_RE.match(comment_text.strip())
            if not match:
                continue

            number = int(match.group("number"))
            if number in tool_table:
                # Only the first occurrence of a given tool should be used.
                logger.debug(f"Ignoring duplicate tool table comment for T{number}: {line}")
                continue

            tool_def = self._build_tool_definition(number, match)
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

        stock = None
        if stock_fields is not None:
            stock = _build_cam_stock(stock_fields, origin_fields)
            if stock is not None:
                stock = stock.scaled(unit_scale)
                logger.info(
                    f"Detected Fusion 360 stock: {stock.kind} "
                    f"origin {stock.xy_corner}/{stock.z_reference} "
                    f"offset=({stock.offset_x_mm:g}, {stock.offset_y_mm:g}, {stock.offset_z_mm:g})"
                )

        return CamMetadata(parser_name=self.name, tool_table=tool_table, stock=stock)

    @staticmethod
    def _build_tool_definition(number, match):
        middle = match.group("middle").strip()
        fields = [field for field in _FIELD_SPLIT_RE.split(middle) if field]
        description = fields[0] if len(fields) > 0 else ""
        vendor = fields[1] if len(fields) > 1 else ""
        product_id = fields[2] if len(fields) > 2 else ""

        type_name = match.group("type_name").strip()
        tool_type = resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP)
        diameter = _to_float(match.group("diameter"))
        corner_radius = _to_float(match.group("corner_radius"))
        shaft_diameter = _positive_or_none(_to_float(match.group("shaft_diameter")))
        tip_diameter = _to_float(match.group("tip_diameter"))
        flute_length = _positive_or_none(_to_float(match.group("flute_length")))
        shoulder_length = _positive_or_none(_to_float(match.group("shoulder_length")))
        body_length = _positive_or_none(_to_float(match.group("body_length")))
        thread_pitch = _positive_or_none(_to_float(match.group("thread_pitch")))

        return ToolDefinition(
            number=number,
            tool_type=tool_type,
            diameter=diameter,
            shank_diameter=shaft_diameter
            if shaft_diameter is not None
            else _infer_shank_diameter(tool_type, diameter, corner_radius),
            tip_diameter=tip_diameter,
            corner_radius=corner_radius,
            taper_angle_deg=_taper_angle_from_fusion(tool_type, _to_float(match.group("taper"))),
            length=body_length if body_length is not None else shoulder_length,
            flute_length=flute_length,
            shoulder_length=shoulder_length,
            thread_pitch=thread_pitch,
            description=description,
            vendor=vendor,
            product_id=product_id,
            type_name=type_name,
        )
