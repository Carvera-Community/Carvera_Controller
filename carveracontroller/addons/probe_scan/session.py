"""Session feature model for probe scan."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CoordSys(str, Enum):
    WCS = "wcs"


class FeatureKind(str, Enum):
    POINT = "point"
    CIRCLE = "circle"
    CORNER = "corner"
    ANGLE = "angle"
    SEGMENT = "segment"
    POLYLINE = "polyline"
    DERIVED_CIRCLE = "derived_circle"
    DERIVED_POINT = "derived_point"


@dataclass
class ProbeScanFeature:
    """One measured or constructed feature."""

    id: str
    kind: FeatureKind
    label: str
    coord_sys: CoordSys
    payload: dict[str, Any] = field(default_factory=dict)
    created_ts: float = field(default_factory=lambda: time.time())

    @staticmethod
    def new_point(
        label: str,
        x: float,
        y: float,
        z: float,
        *,
        source: str = "wcs",
        coord_sys: CoordSys = CoordSys.WCS,
    ) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.POINT,
            label=label,
            coord_sys=coord_sys,
            payload={
                "x": x,
                "y": y,
                "z": z,
                "source": source,
            },
        )

    @staticmethod
    def new_circle(
        label: str,
        cx: float,
        cy: float,
        d_x: float,
        d_y: float,
        *,
        coord_sys: CoordSys = CoordSys.WCS,
    ) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.CIRCLE,
            label=label,
            coord_sys=coord_sys,
            payload={
                "cx": cx,
                "cy": cy,
                "diameter_x": d_x,
                "diameter_y": d_y,
            },
        )

    @staticmethod
    def new_corner(
        label: str,
        x: float,
        y: float,
        *,
        coord_sys: CoordSys = CoordSys.WCS,
    ) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.CORNER,
            label=label,
            coord_sys=coord_sys,
            payload={"x": x, "y": y},
        )

    @staticmethod
    def new_angle(
        label: str,
        degrees: float,
        *,
        probe_variant: str = "",
    ) -> ProbeScanFeature:
        """``degrees`` mirrors firmware ``#153`` for M465 (documented as degrees)."""
        payload: dict[str, Any] = {"degrees": float(degrees)}
        if probe_variant:
            payload["probe_variant"] = str(probe_variant)
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.ANGLE,
            label=label,
            coord_sys=CoordSys.WCS,
            payload=payload,
        )

    @staticmethod
    def new_segment(label: str, a_id: str, b_id: str) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.SEGMENT,
            label=label,
            coord_sys=CoordSys.WCS,
            payload={"a_id": str(a_id), "b_id": str(b_id)},
        )

    @staticmethod
    def new_polyline(
        label: str,
        vertex_feature_ids: list[str],
        *,
        closed: bool = False,
    ) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.POLYLINE,
            label=label,
            coord_sys=CoordSys.WCS,
            payload={
                "vertex_feature_ids": [str(v) for v in vertex_feature_ids],
                "closed": closed,
            },
        )

    @staticmethod
    def new_derived_circle(
        label: str,
        source_ids: tuple[str, str, str],
        cx: float,
        cy: float,
        r: float,
    ) -> ProbeScanFeature:
        a, b, c = source_ids
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.DERIVED_CIRCLE,
            label=label,
            coord_sys=CoordSys.WCS,
            payload={
                "source_ids": [a, b, c],
                "cx": cx,
                "cy": cy,
                "r": r,
            },
        )

    @staticmethod
    def new_derived_point(
        label: str,
        segment_a_id: str,
        segment_b_id: str,
        x: float,
        y: float,
    ) -> ProbeScanFeature:
        return ProbeScanFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.DERIVED_POINT,
            label=label,
            coord_sys=CoordSys.WCS,
            payload={
                "segment_a_id": str(segment_a_id),
                "segment_b_id": str(segment_b_id),
                "x": x,
                "y": y,
                "z": 0.0,
            },
        )


SESSION_FORMAT_VERSION = 1


@dataclass
class ProbeScanSession:
    """Full scan session for save/load and export."""

    version: int = SESSION_FORMAT_VERSION
    unit_mm: bool = True
    wcs_note: str = "G54"
    features: list[ProbeScanFeature] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return {
            "version": self.version,
            "unit_mm": self.unit_mm,
            "wcs_note": self.wcs_note,
            "features": [
                {
                    **asdict(f),
                    "kind": f.kind.value,
                    "coord_sys": f.coord_sys.value,
                }
                for f in self.features
            ],
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> ProbeScanSession:
        feats: list[ProbeScanFeature] = []
        for row in data.get("features", []):
            k = row.get("kind")
            if isinstance(k, FeatureKind):
                kind_enum = k
            else:
                try:
                    kind_enum = FeatureKind(str(k))
                except ValueError:
                    logger.warning(
                        "Probe scan session: skip feature with invalid kind %r",
                        k,
                    )
                    continue
            cs_raw = row.get("coord_sys", CoordSys.WCS.value)
            try:
                coord = CoordSys(cs_raw)
            except ValueError:
                coord = CoordSys.WCS
            feat = ProbeScanFeature(
                id=row.get("id", str(uuid.uuid4())),
                kind=kind_enum,
                label=row.get("label", ""),
                coord_sys=coord,
                payload=dict(row.get("payload", {})),
                created_ts=float(row.get("created_ts", time.time())),
            )
            feats.append(feat)
        return cls(
            # Always create a session with the current format version.
            version=SESSION_FORMAT_VERSION,
            unit_mm=bool(data.get("unit_mm", True)),
            wcs_note=str(data.get("wcs_note", "G54")),
            features=feats,
        )

    def dumps(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    @classmethod
    def loads(cls, s: str) -> ProbeScanSession:
        return cls.from_json_dict(json.loads(s))
