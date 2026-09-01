"""Parser for tool tables written by the FreeCAD Makera post processor.

The post processor writes a comment block at the top of the G-code file:

(@FC|TOOL|number=<int>|name=<string>|vendor=<string>|id=<string>|type=<ShapeType>|diameter=<float>|shankdiameter=<float>|tipdiameter=<float>|cornerradius=<float>|flutelength=<float>|shoulderlength=<float>|length=<float>|pitch=<float>|cuttingedgeangle=<float>|tipangle=<float>|taperangle=<float>)

`type` is FreeCAD's native ShapeType (Endmill, Ballend, Drill, VBit, ...).

Angle fields are FreeCAD's raw values in degrees:
- tipangle: included drill tip angle
- taperangle: included taper angle (Tapered Ball Nose)
- cuttingedgeangle: included V/chamfer cutting-edge angle

The parser converts those included angles to per-side degrees for ToolDefinition.

Stock and origin, when present:

(@FC|STOCK|id=box|width=<float>|depth=<float>|height=<float>)
(@FC|STOCK|id=cylinder|width=<float>|depth=<float>|height=<float>|diameter=<float>)
(@FC|ORIGIN|type_name=<camelCase>|x=<float>|y=<float>|z=<float>)

``width`` is the X extent and ``depth`` is the Y extent. ORIGIN ``type_name``
follows ``topFrontLeft``, ``topCenter``, ``custom``, etc. Coordinates are the
WCS origin relative to the stock centre, in document units.
"""

import logging

from carveracontroller.addons.cam.metadata import CamMetadata, CamStock
from carveracontroller.addons.cam.parsers.base import CamHeaderParser
from carveracontroller.addons.cam.parsers.makera_studio import parse_origin_type_name
from carveracontroller.addons.stock.stock_origin import named_origin_relative_to_center
from carveracontroller.addons.tool_visualization.tool_definition import (
    ToolDefinition,
    ToolType,
    resolve_tool_type,
)

logger = logging.getLogger(__name__)

# FreeCAD ShapeType / shape filename stems as written in `type=`.
TOOL_TYPE_NAME_MAP = {
    "endmill": ToolType.FLAT_END_MILL,
    "ballend": ToolType.BALL_END_MILL,
    "bullnose": ToolType.BULL_NOSE_END_MILL,
    "chamfer": ToolType.CHAMFER_MILL,
    "vbit": ToolType.CHAMFER_MILL,
    "v-bit": ToolType.CHAMFER_MILL,
    "drill": ToolType.DRILL,
    "threadmill": ToolType.THREAD_MILL,
    "thread-mill": ToolType.THREAD_MILL,
    "thread mill": ToolType.THREAD_MILL,
    "taperedballnose": ToolType.TAPERED_MILL,
    "tapered ball nose": ToolType.TAPERED_MILL,
    "radius": ToolType.RADIUS_MILL,
    "radius mill": ToolType.RADIUS_MILL,
}

_TOOL_TAG = "TOOL"
_STOCK_TAG = "STOCK"
_ORIGIN_TAG = "ORIGIN"


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


def _extract_fc_payload(line):
    """Return the `@FC|...` payload from a FreeCAD tool-table comment, else None."""
    stripped = line.strip()
    if stripped.startswith("(@FC|") and stripped.endswith(")"):
        return stripped[1:-1]
    if stripped.startswith(";@FC|"):
        return stripped[1:]
    return None


def _parse_fc_fields(line):
    """Return (tag, fields_dict) for an `@FC|TAG|k=v|...` payload, or None."""
    payload = _extract_fc_payload(line)
    if payload is None or not payload.startswith("@FC|"):
        return None

    parts = payload[len("@FC|") :].split("|")
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


def _included_to_per_side(angle_deg):
    """Convert an included tip/taper angle to per-side degrees."""
    if angle_deg is None or angle_deg <= 0:
        return None
    # Guard against bad FreeCAD library data (e.g. drills with angle > 180).
    if angle_deg > 180:
        return None
    return angle_deg / 2.0


def _origin_corner_from_type_name(type_name):
    """Return ``(xy_corner, z_reference)`` for a FreeCAD ORIGIN ``type_name``."""
    parsed = parse_origin_type_name(type_name)
    if parsed is not None:
        return parsed
    if (type_name or "").strip().lower() == "custom":
        return "center", "top"
    if type_name:
        logger.warning(f"Unrecognised FreeCAD origin type_name {type_name!r}; defaulting to bl/top")
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
    """Build a CamStock from FreeCAD STOCK/ORIGIN field dicts, or None."""
    stock_id = (stock_fields.get("id") or "").strip().lower()
    origin_type = (origin_fields or {}).get("type_name") or ""
    xy_corner, z_reference = _origin_corner_from_type_name(origin_type)

    if stock_id == "box":
        width_mm = _positive_or_none(_to_float(stock_fields.get("width")))
        length_mm = _positive_or_none(_to_float(stock_fields.get("depth")))
        height_mm = _positive_or_none(_to_float(stock_fields.get("height")))
        if width_mm is None or length_mm is None or height_mm is None:
            logger.warning("Ignoring FreeCAD box STOCK with missing or non-positive width/depth/height")
            return None
        kind = "rectangular"
        diameter_mm = None
        dx, dy, dz = width_mm, length_mm, height_mm
    elif stock_id == "cylinder":
        diameter_mm = _positive_or_none(_to_float(stock_fields.get("diameter")))
        if diameter_mm is None:
            logger.warning("Ignoring FreeCAD cylinder STOCK with missing or non-positive diameter")
            return None
        x_mm = _positive_or_none(_to_float(stock_fields.get("width")))
        y_mm = _positive_or_none(_to_float(stock_fields.get("depth")))
        z_mm = _positive_or_none(_to_float(stock_fields.get("height")))
        axis = _infer_cylinder_axis(x_mm, y_mm, z_mm)
        if axis == "y":
            logger.warning("Ignoring FreeCAD cylinder STOCK with unsupported Y-axis orientation")
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
                logger.warning("Ignoring FreeCAD rotary cylinder STOCK with missing or non-positive width")
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
                logger.warning("Ignoring FreeCAD mill cylinder STOCK with missing or non-positive height")
                return None
            kind = "cylindrical"
            width_mm = None
            length_mm = None
            dx, dy, dz = diameter_mm, diameter_mm, height_mm
    else:
        if stock_id:
            logger.warning(f"Ignoring unrecognised FreeCAD STOCK id {stock_id!r}")
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


def _taper_angle_from_fields(fields, tool_type):
    """Return per-side taper in degrees from FreeCAD angle fields."""
    tip_angle = _included_to_per_side(_to_float(fields.get("tipangle")))
    if tip_angle is not None and tool_type is ToolType.DRILL:
        return tip_angle

    taper_angle = _included_to_per_side(_to_float(fields.get("taperangle")))
    if taper_angle is not None:
        return taper_angle

    cutting_edge_angle = _included_to_per_side(_to_float(fields.get("cuttingedgeangle")))
    if cutting_edge_angle is None:
        return None

    if tool_type in (
        ToolType.CHAMFER_MILL,
        ToolType.ENGRAVING,
        ToolType.DRILL,
        ToolType.TAPERED_MILL,
    ):
        return cutting_edge_angle
    return None


class FreeCADMakeraParser(CamHeaderParser):
    name = "freecad_makera"

    def parse(self, lines):
        return self.parse_metadata(lines).tool_table

    def parse_metadata(self, lines, unit_scale=1.0) -> CamMetadata:
        tool_table = {}
        stock_fields = None
        origin_fields = None
        saw_fc_marker = False

        for raw_line in self.iter_header_lines(lines):
            parsed = _parse_fc_fields(raw_line)
            if parsed is None:
                # Keep scanning header comments; Fusion-style lines must not
                # make us bail before we see any @FC markers.
                continue

            saw_fc_marker = True
            tag, fields = parsed
            if tag == _TOOL_TAG:
                number = _to_int(fields.get("number"))
                if number is None:
                    continue
                if number in tool_table:
                    logger.debug(f"Ignoring duplicate FreeCAD tool comment for T{number}: {raw_line.strip()}")
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

        if not saw_fc_marker:
            return CamMetadata(parser_name=self.name, tool_table={}, stock=None)

        stock = None
        if stock_fields is not None:
            stock = _build_cam_stock(stock_fields, origin_fields)
            if stock is not None:
                stock = stock.scaled(unit_scale)
                logger.info(
                    f"Detected FreeCAD stock: {stock.kind} "
                    f"origin {stock.xy_corner}/{stock.z_reference} "
                    f"offset=({stock.offset_x_mm:g}, {stock.offset_y_mm:g}, {stock.offset_z_mm:g})"
                )

        return CamMetadata(parser_name=self.name, tool_table=tool_table, stock=stock)

    @staticmethod
    def _build_tool_definition(number, fields):
        type_name = fields.get("type", "") or ""
        tool_type = resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP)
        diameter = _to_float(fields.get("diameter"))
        tip_diameter = _to_float(fields.get("tipdiameter"))
        corner_radius = _to_float(fields.get("cornerradius"))
        shank_diameter = _positive_or_none(_to_float(fields.get("shankdiameter")))

        # Tapered ball nose is a ball tip (CR = D/2) with a conical taper above.
        if tool_type is ToolType.TAPERED_MILL:
            if diameter is not None and diameter > 0 and (corner_radius is None or corner_radius <= 0):
                corner_radius = diameter / 2.0

        return ToolDefinition(
            number=number,
            tool_type=tool_type,
            diameter=diameter,
            shank_diameter=shank_diameter,
            tip_diameter=tip_diameter,
            corner_radius=corner_radius,
            taper_angle_deg=_taper_angle_from_fields(fields, tool_type),
            length=_positive_or_none(_to_float(fields.get("length"))),
            flute_length=_positive_or_none(_to_float(fields.get("flutelength"))),
            shoulder_length=_positive_or_none(_to_float(fields.get("shoulderlength"))),
            thread_pitch=_positive_or_none(_to_float(fields.get("pitch"))),
            description=fields.get("name", "") or "",
            vendor=fields.get("vendor", "") or "",
            product_id=fields.get("id", "") or "",
            type_name=type_name,
        )
