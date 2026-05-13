"""Resolve feature coordinates and dependency IDs for constructions and DXF."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .session import FeatureKind, ProbeScanFeature

XY = tuple[float, float]


def index_by_id(features: Iterable[ProbeScanFeature]) -> dict[str, ProbeScanFeature]:
    return {f.id: f for f in features}


def payload_referenced_feature_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("a_id", "b_id", "segment_a_id", "segment_b_id",
                "point_id", "circle_id", "circle_a_id", "circle_b_id"):
        v = payload.get(key)
        if v:
            ids.append(str(v))
    verts = payload.get("vertex_feature_ids")
    if isinstance(verts, list):
        ids.extend(str(v) for v in verts if v)
    src = payload.get("source_ids")
    if isinstance(src, list):
        ids.extend(str(v) for v in src if v)
    return ids


def referenced_feature_ids(feature: ProbeScanFeature) -> list[str]:
    return payload_referenced_feature_ids(feature.payload)


def features_referencing_id(features: Iterable[ProbeScanFeature], target_id: str) -> list[str]:
    holders: list[str] = []
    for f in features:
        if target_id in referenced_feature_ids(f):
            holders.append(f.id)
    return holders


def resolve_xy(vertex: ProbeScanFeature) -> XY | None:
    """Vertices for constructions: POINT, CORNER, CIRCLE center, DERIVED_POINT."""
    p = vertex.payload
    if vertex.kind == FeatureKind.POINT:
        return float(p["x"]), float(p["y"])
    if vertex.kind == FeatureKind.CORNER:
        return float(p["x"]), float(p["y"])
    if vertex.kind == FeatureKind.CIRCLE:
        return float(p["cx"]), float(p["cy"])
    if vertex.kind == FeatureKind.DERIVED_POINT:
        return float(p["x"]), float(p["y"])
    return None


def segment_endpoints(
    by_id: dict[str, ProbeScanFeature],
    seg: ProbeScanFeature,
    resolve: Callable[[ProbeScanFeature], XY | None] = resolve_xy,
) -> tuple[XY, XY] | None:
    """Return ((x1,y1),(x2,y2)) for a SEGMENT feature."""
    if seg.kind != FeatureKind.SEGMENT:
        return None
    a = by_id.get(str(seg.payload.get("a_id", "")))
    b = by_id.get(str(seg.payload.get("b_id", "")))
    if not a or not b:
        return None
    pa = resolve(a)
    pb = resolve(b)
    if pa is None or pb is None:
        return None
    return pa, pb


def resolve_circle(feature: ProbeScanFeature) -> tuple[float, float, float] | None:
    """Return (cx, cy, r) for CIRCLE or DERIVED_CIRCLE features, else None."""
    p = feature.payload
    if feature.kind == FeatureKind.CIRCLE:
        cx = float(p.get("cx", 0.0))
        cy = float(p.get("cy", 0.0))
        dx = float(p.get("diameter_x", 0.0))
        dy = float(p.get("diameter_y", 0.0))
        r = (dx + dy) / 4.0  # average radius
        return cx, cy, r
    if feature.kind == FeatureKind.DERIVED_CIRCLE:
        cx = float(p.get("cx", 0.0))
        cy = float(p.get("cy", 0.0))
        r = float(p.get("r", 0.0))
        return cx, cy, r
    return None
