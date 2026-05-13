"""Export probe scan sessions to JSON, CSV, and DXF."""

from __future__ import annotations

import csv
import io
import os
import tempfile

import ezdxf

from .feature_resolve import index_by_id, resolve_xy, segment_endpoints
from .session import FeatureKind, ProbeScanSession

_DXF_LAYERS = (
    "PROBED_POINTS",
    "PROBED_CENTERS",
    "PROBED_CORNERS",
    "CONSTRUCTED_SEGMENTS",
    "CONSTRUCTED_POLYLINES",
    "CONSTRUCTED_CIRCLES",
    "CONSTRUCTED_POINTS",
)


def export_json(session: ProbeScanSession) -> str:
    return session.dumps()


def export_csv(session: ProbeScanSession) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "kind", "label", "coord_sys", "x", "y", "z", "extra"])
    for f in session.features:
        p = f.payload
        x = p.get("x", p.get("cx", ""))
        y = p.get("y", p.get("cy", ""))
        z = p.get("z", "")
        extra_keys = {
            "x",
            "y",
            "z",
            "cx",
            "cy",
            "r",
            "diameter_x",
            "diameter_y",
        }
        extra = {k: v for k, v in p.items() if k not in extra_keys}
        w.writerow([f.id, f.kind.value, f.label, f.coord_sys.value, x, y, z, str(extra)])
    return buf.getvalue()


def export_dxf(session: ProbeScanSession) -> str:
    """Write a layered DXF (R2010) as a string for clipboard or disk."""
    doc = ezdxf.new("R2010", setup=True)
    for lyr in _DXF_LAYERS:
        if lyr not in doc.layers:
            doc.layers.new(lyr)

    msp = doc.modelspace()
    feats = session.features
    by_id = index_by_id(feats)

    for f in feats:
        p = f.payload
        if f.kind == FeatureKind.POINT:
            x = float(p.get("x", 0))
            y = float(p.get("y", 0))
            z = float(p.get("z", 0))
            msp.add_point((x, y, z), dxfattribs={"layer": "PROBED_POINTS"})
        elif f.kind == FeatureKind.CIRCLE:
            cx = float(p.get("cx", 0))
            cy = float(p.get("cy", 0))
            dx = float(p.get("diameter_x", 0))
            dy = float(p.get("diameter_y", 0))
            r = max(dx, dy) / 2.0
            msp.add_point((cx, cy, 0.0), dxfattribs={"layer": "PROBED_CENTERS"})
            if r > 0:
                msp.add_circle((cx, cy), r, dxfattribs={"layer": "PROBED_CENTERS"})
        elif f.kind == FeatureKind.CORNER:
            msp.add_point(
                (float(p.get("x", 0)), float(p.get("y", 0)), 0.0),
                dxfattribs={"layer": "PROBED_CORNERS"},
            )
        elif f.kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if not ends:
                continue
            (x1, y1), (x2, y2) = ends
            msp.add_line(
                (x1, y1, 0.0),
                (x2, y2, 0.0),
                dxfattribs={"layer": "CONSTRUCTED_SEGMENTS"},
            )
        elif f.kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list):
                continue
            coords: list[tuple[float, float]] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                pt = resolve_xy(wf) if wf else None
                if pt:
                    coords.append(pt)
            if len(coords) < 2:
                continue
            closed = bool(p.get("closed"))
            msp.add_lwpolyline(
                coords,
                dxfattribs={"layer": "CONSTRUCTED_POLYLINES"},
                close=closed,
            )
        elif f.kind == FeatureKind.DERIVED_CIRCLE:
            cx = float(p.get("cx", 0))
            cy = float(p.get("cy", 0))
            r = float(p.get("r", 0))
            if r > 0:
                msp.add_circle((cx, cy), r, dxfattribs={"layer": "CONSTRUCTED_CIRCLES"})
        elif f.kind == FeatureKind.DERIVED_POINT:
            msp.add_point(
                (
                    float(p.get("x", 0)),
                    float(p.get("y", 0)),
                    float(p.get("z", 0)),
                ),
                dxfattribs={"layer": "CONSTRUCTED_POINTS"},
            )

    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        doc.saveas(path)
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
