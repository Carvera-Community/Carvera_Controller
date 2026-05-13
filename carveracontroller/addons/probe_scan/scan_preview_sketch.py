"""2D XY preview of probe-scan features (active work XY plane, mm)."""

from __future__ import annotations

import math
from collections.abc import Callable

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Translate
from kivy.metrics import dp
from kivy.uix.widget import Widget

from .feature_resolve import index_by_id, resolve_xy, segment_endpoints
from .session import FeatureKind, ProbeScanFeature

# Construction checkbox order: 1st, 2nd, 3rd, … in the XY preview.
_SEL_ORDER_PALETTE: tuple[tuple[float, float, float, float], ...] = (
    (0.98, 0.72, 0.15, 1.0),
    (0.25, 0.78, 1.0, 1.0),
    (0.45, 0.95, 0.35, 1.0),
    (1.0, 0.35, 0.85, 1.0),
    (0.75, 0.55, 0.95, 1.0),
)


class ProbeScanPreviewSketch(Widget):
    """Redraw when features or table/focus/selection state change via ``set_features``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._features: list[ProbeScanFeature] = []
        self._focus_id: str | None = None
        self._selection_ids: list[str] = []
        # Last computed transform parameters – set during _redraw, used by hit-test.
        self._last_scale: float = 1.0
        self._last_cx: float = 0.0
        self._last_cy: float = 0.0
        self._last_iw: float = 1.0
        self._last_ih: float = 1.0
        self._has_valid_transform: bool = False
        # Callback: called with the feature id (str) when user taps a feature.
        self.on_feature_tap: Callable[[str], None] | None = None
        self.bind(pos=self._redraw, size=self._redraw)

    def set_features(
        self,
        feats: list[ProbeScanFeature],
        *,
        focus_id: str | None = None,
        selection_ids: list[str] | None = None,
    ):
        self._features = list(feats)
        self._focus_id = focus_id
        self._selection_ids = list(selection_ids) if selection_ids is not None else []
        self._redraw()

    def _world_to_px(self, wx: float, wy: float) -> tuple[float, float]:
        """Widget-local pixel coordinates for a world point (uses last transform)."""
        iw, ih = self._last_iw, self._last_ih
        return (
            iw / 2.0 + (wx - self._last_cx) * self._last_scale,
            ih / 2.0 + (wy - self._last_cy) * self._last_scale,
        )

    def _px_to_world(self, lx: float, ly: float) -> tuple[float, float]:
        """Inverse of ``_world_to_px`` using the last redraw transform."""
        iw, ih = self._last_iw, self._last_ih
        sc = self._last_scale
        if abs(sc) < 1e-12:
            return self._last_cx, self._last_cy
        wx = self._last_cx + (lx - iw / 2.0) / sc
        wy = self._last_cy + (ly - ih / 2.0) / sc
        return wx, wy

    def _hit_radius_for_feature(self, f: ProbeScanFeature) -> float:
        """Screen-space hit radius in pixels for a given feature."""
        sc = abs(self._last_scale)
        p = f.payload
        if f.kind in (
            FeatureKind.POINT,
            FeatureKind.CORNER,
            FeatureKind.DERIVED_POINT,
            FeatureKind.ANGLE,
        ):
            return max(dp(18), sc * 0.65)
        if f.kind == FeatureKind.CIRCLE:
            rdx = float(p.get("diameter_x", 0)) / 2.0
            rdy = float(p.get("diameter_y", 0)) / 2.0
            ring_px = max((rdx + rdy) / 2.0 * sc, dp(8))
            # Generous band: thin on-screen rings are hard to tap otherwise.
            return max(dp(26), dp(16) + ring_px * 0.42)
        if f.kind == FeatureKind.DERIVED_CIRCLE:
            ring_px = max(float(p.get("r", 0)) * sc, dp(8))
            return max(dp(26), dp(16) + ring_px * 0.42)
        if f.kind in (FeatureKind.SEGMENT, FeatureKind.POLYLINE):
            return dp(20)
        return dp(18)

    def _circle_hit_distance_px(
        self,
        cx_: float,
        cy_: float,
        rdx: float,
        rdy: float,
        tx: float,
        ty: float,
    ) -> float:
        """Pixel distance from tap to the nearest of: ellipse outline or circle centre."""
        ux, vy = self._world_to_px(cx_, cy_)
        dist_centre_px = math.hypot(tx - ux, ty - vy)
        aa = max(rdx, 1e-9)
        bb = max(rdy, 1e-9)
        wx, wy = self._px_to_world(tx, ty)
        nx = (wx - cx_) / aa
        ny = (wy - cy_) / bb
        rho = math.hypot(nx, ny)
        sc = abs(self._last_scale)
        dist_ring_px = abs(rho - 1.0) * min(aa, bb) * sc
        return min(dist_centre_px, dist_ring_px)

    def _distance_to_feature_px(
        self, f: ProbeScanFeature, by_id: dict, tx: float, ty: float
    ) -> float:
        """Minimum screen-pixel distance from (tx, ty) to feature geometry."""
        p = f.payload

        def pt_dist(wx, wy):
            u, v = self._world_to_px(wx, wy)
            return math.hypot(tx - u, ty - v)

        def seg_dist(x1, y1, x2, y2):
            u1, v1 = self._world_to_px(x1, y1)
            u2, v2 = self._world_to_px(x2, y2)
            dx, dy = u2 - u1, v2 - v1
            L2 = dx * dx + dy * dy
            if L2 < 1e-6:
                return math.hypot(tx - u1, ty - v1)
            t = max(0.0, min(1.0, ((tx - u1) * dx + (ty - v1) * dy) / L2))
            return math.hypot(tx - u1 - t * dx, ty - v1 - t * dy)

        if f.kind in (FeatureKind.POINT, FeatureKind.CORNER, FeatureKind.DERIVED_POINT):
            return pt_dist(float(p.get("x", 0)), float(p.get("y", 0)))
        if f.kind == FeatureKind.CIRCLE:
            cx_ = float(p.get("cx", 0))
            cy_ = float(p.get("cy", 0))
            rdx = float(p.get("diameter_x", 0)) / 2.0
            rdy = float(p.get("diameter_y", 0)) / 2.0
            return self._circle_hit_distance_px(cx_, cy_, rdx, rdy, tx, ty)
        if f.kind == FeatureKind.DERIVED_CIRCLE:
            cx_ = float(p.get("cx", 0))
            cy_ = float(p.get("cy", 0))
            r = float(p.get("r", 0))
            return self._circle_hit_distance_px(cx_, cy_, r, r, tx, ty)
        if f.kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if not ends:
                return float("inf")
            (x1, y1), (x2, y2) = ends
            return seg_dist(x1, y1, x2, y2)
        if f.kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list) or len(verts) < 2:
                return float("inf")
            pts: list[tuple[float, float]] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                pt = resolve_xy(wf) if wf else None
                if pt:
                    pts.append(pt)
            if len(pts) < 2:
                return float("inf")
            closed = bool(p.get("closed"))
            edges = list(zip(pts, pts[1:]))
            if closed:
                edges.append((pts[-1], pts[0]))
            return min(seg_dist(ax, ay, bx, by) for (ax, ay), (bx, by) in edges)
        return float("inf")

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self._has_valid_transform or not self._features:
            return super().on_touch_down(touch)
        tx = touch.x - self.x
        ty = touch.y - self.y
        by_id = index_by_id(self._features)
        best_id: str | None = None
        best_dist = float("inf")
        for f in self._features:
            d = self._distance_to_feature_px(f, by_id, tx, ty)
            hr = self._hit_radius_for_feature(f)
            if d <= hr and d < best_dist:
                best_dist = d
                best_id = f.id
        if best_id is not None and self.on_feature_tap is not None:
            self.on_feature_tap(best_id)
            return True
        return super().on_touch_down(touch)

    def _draw_feature_highlight(
        self,
        f: ProbeScanFeature,
        by_id: dict[str, ProbeScanFeature],
        px,
        scale: float,
        rgba: tuple[float, float, float, float],
        lw: float,
    ) -> None:
        kind = f.kind
        if kind == FeatureKind.ANGLE:
            return
        p = f.payload
        Color(*rgba)
        if kind in (FeatureKind.POINT, FeatureKind.DERIVED_POINT):
            x = float(p.get("x", 0))
            y = float(p.get("y", 0))
            u, v = px(x, y)
            s = max(5.0, abs(scale) * 0.58)
            Line(points=[u - s, v, u + s, v], width=lw)
            Line(points=[u, v - s, u, v + s], width=lw)
        elif kind == FeatureKind.CORNER:
            x = float(p.get("x", 0))
            y = float(p.get("y", 0))
            u, v = px(x, y)
            s = max(5.5, abs(scale) * 0.52)
            Line(
                points=[
                    u - s,
                    v - s,
                    u + s,
                    v - s,
                    u + s,
                    v + s,
                    u - s,
                    v + s,
                    u - s,
                    v - s,
                ],
                width=lw,
            )
        elif kind == FeatureKind.CIRCLE:
            cx_ = float(p.get("cx", 0))
            cy_ = float(p.get("cy", 0))
            rdx = float(p.get("diameter_x", 0)) / 2.0
            rdy = float(p.get("diameter_y", 0)) / 2.0
            pts_circ: list[float] = []
            for i in range(33):
                t = 2 * math.pi * i / 32
                wx = cx_ + rdx * math.cos(t)
                wy = cy_ + rdy * math.sin(t)
                a, b = px(wx, wy)
                pts_circ.extend([a, b])
            Line(points=pts_circ, width=lw)
        elif kind == FeatureKind.DERIVED_CIRCLE:
            cx_ = float(p.get("cx", 0))
            cy_ = float(p.get("cy", 0))
            r = float(p.get("r", 0))
            ovals: list[float] = []
            for i in range(33):
                t = 2 * math.pi * i / 32
                wx = cx_ + r * math.cos(t)
                wy = cy_ + r * math.sin(t)
                u, vv = px(wx, wy)
                ovals.extend([u, vv])
            Line(points=ovals, width=lw)
        elif kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if not ends:
                return
            (x1, y1), (x2, y2) = ends
            u1, v1 = px(x1, y1)
            u2, v2 = px(x2, y2)
            Line(points=[u1, v1, u2, v2], width=lw)
        elif kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list):
                return
            pts_px: list[float] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                pt = resolve_xy(wf) if wf else None
                if pt:
                    a, b = px(pt[0], pt[1])
                    pts_px.extend([a, b])
            if len(pts_px) >= 4:
                line_pts = pts_px
                if p.get("closed") and len(pts_px) >= 6:
                    line_pts = pts_px + pts_px[:2]
                Line(points=line_pts, width=lw)

    def _selection_badge_anchor_px(
        self,
        f: ProbeScanFeature,
        by_id: dict[str, ProbeScanFeature],
        px,
    ) -> tuple[float, float] | None:
        kind = f.kind
        if kind == FeatureKind.ANGLE:
            return None
        p = f.payload
        if kind in (FeatureKind.POINT, FeatureKind.DERIVED_POINT, FeatureKind.CORNER):
            return px(float(p.get("x", 0)), float(p.get("y", 0)))
        if kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
            return px(float(p.get("cx", 0)), float(p.get("cy", 0)))
        if kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if not ends:
                return None
            (x1, y1), (x2, y2) = ends
            return px((x1 + x2) * 0.5, (y1 + y2) * 0.5)
        if kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list):
                return None
            xs: list[float] = []
            ys: list[float] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                pt = resolve_xy(wf) if wf else None
                if pt:
                    xs.append(pt[0])
                    ys.append(pt[1])
            if not xs:
                return None
            return px(sum(xs) / len(xs), sum(ys) / len(ys))
        return None

    def _selection_badge_layout_px(
        self,
        f: ProbeScanFeature,
        by_id: dict[str, ProbeScanFeature],
        px,
        scale: float,
        iw: float,
        ih: float,
        ord_idx: int,
        au: float,
        av: float,
    ) -> tuple[float, float]:
        """Screen-pixel position for an order badge, kept away from mark geometry."""
        kind = f.kind
        sc = abs(scale)
        p = f.payload

        if kind in (FeatureKind.POINT, FeatureKind.DERIVED_POINT):
            s = max(5.0, sc * 0.58)
            clear = s + dp(14)
            ang = (
                math.pi / 4
                + (ord_idx % 4) * (math.pi / 2)
                + (ord_idx // 4) * 0.22
            )
            return au + math.cos(ang) * clear, av + math.sin(ang) * clear

        if kind == FeatureKind.CORNER:
            s = max(5.5, sc * 0.52)
            clear = s * math.sqrt(2) + dp(14)
            ang = (
                math.pi / 4
                + (ord_idx % 4) * (math.pi / 2)
                + (ord_idx // 4) * 0.22
            )
            return au + math.cos(ang) * clear, av + math.sin(ang) * clear

        cx_s = iw * 0.5
        cy_s = ih * 0.5
        dx, dy = au - cx_s, av - cy_s
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            dx, dy = 1.0, 0.0
            dist = 1.0
        else:
            dx /= dist
            dy /= dist
        perp_x, perp_y = -dy, dx

        if kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
            if kind == FeatureKind.CIRCLE:
                rdx = float(p.get("diameter_x", 0)) / 2.0
                rdy = float(p.get("diameter_y", 0)) / 2.0
                rw = max(rdx, rdy, 1e-6)
            else:
                rw = max(float(p.get("r", 0)), 1e-6)
            badge_off = sc * rw + dp(14)
        elif kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if ends:
                (x1, y1), (x2, y2) = ends
                u1, v1 = px(x1, y1)
                u2, v2 = px(x2, y2)
                slen = math.hypot(u2 - u1, v2 - v1)
                badge_off = max(dp(16), slen * 0.28 + dp(12))
            else:
                badge_off = dp(16)
        elif kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list):
                badge_off = dp(16)
            else:
                wxs: list[float] = []
                wys: list[float] = []
                for vid in verts:
                    wf = by_id.get(str(vid))
                    pt = resolve_xy(wf) if wf else None
                    if pt:
                        wxs.append(pt[0])
                        wys.append(pt[1])
                if not wxs:
                    badge_off = dp(16)
                else:
                    mx = sum(wxs) / len(wxs)
                    my = sum(wys) / len(wys)
                    max_wd = max(
                        math.hypot(wx - mx, wy - my) for wx, wy in zip(wxs, wys)
                    )
                    badge_off = max(dp(16), max_wd * sc + dp(12))
        else:
            badge_off = dp(14)

        tang = (ord_idx % 5) * dp(4)
        return au + dx * badge_off + perp_x * tang, av + dy * badge_off + perp_y * tang

    def _draw_selection_order_badges(
        self,
        by_id: dict[str, ProbeScanFeature],
        px,
        scale: float,
        iw: float,
        ih: float,
    ) -> None:
        font_size = max(dp(11), min(dp(16), abs(scale) * 0.38))
        for ord_idx, fid in enumerate(self._selection_ids):
            sf = by_id.get(fid)
            if sf is None:
                continue
            anchor = self._selection_badge_anchor_px(sf, by_id, px)
            if anchor is None:
                continue
            au, av = anchor
            tu, tv = self._selection_badge_layout_px(
                sf, by_id, px, scale, iw, ih, ord_idx, au, av
            )

            col = _SEL_ORDER_PALETTE[ord_idx % len(_SEL_ORDER_PALETTE)]
            try:
                label = CoreLabel(
                    text=str(ord_idx + 1),
                    font_size=font_size,
                    bold=True,
                    color=col[:4],
                    outline_width=1,
                    outline_color=(0.0, 0.0, 0.0, 1.0),
                )
            except TypeError:
                label = CoreLabel(
                    text=str(ord_idx + 1),
                    font_size=font_size,
                    bold=True,
                    color=col[:4],
                )
            label.refresh()
            tex = label.texture
            if tex is None or tex.width < 1:
                continue
            tw, th = tex.size
            Color(1, 1, 1, 1)
            Rectangle(
                texture=tex,
                pos=(tu - tw * 0.5, tv - th * 0.5),
                size=(tw, th),
            )

    def _bbox(self):
        xs: list[float] = []
        ys: list[float] = []
        by_id = index_by_id(self._features)

        def add_xy(x: float, y: float) -> None:
            xs.append(x)
            ys.append(y)

        for f in self._features:
            p = f.payload
            if f.kind == FeatureKind.POINT:
                add_xy(float(p.get("x", 0)), float(p.get("y", 0)))
            elif f.kind == FeatureKind.CIRCLE:
                cx = float(p.get("cx", 0))
                cy = float(p.get("cy", 0))
                rdx = float(p.get("diameter_x", 0)) / 2.0
                rdy = float(p.get("diameter_y", 0)) / 2.0
                xs.extend([cx - rdx, cx + rdx])
                ys.extend([cy - rdy, cy + rdy])
            elif f.kind == FeatureKind.CORNER:
                add_xy(float(p.get("x", 0)), float(p.get("y", 0)))
            elif f.kind == FeatureKind.SEGMENT:
                ends = segment_endpoints(by_id, f)
                if ends:
                    (x1, y1), (x2, y2) = ends
                    add_xy(x1, y1)
                    add_xy(x2, y2)
            elif f.kind == FeatureKind.POLYLINE:
                verts = p.get("vertex_feature_ids") or []
                if not isinstance(verts, list):
                    continue
                for vid in verts:
                    wf = by_id.get(str(vid))
                    pt = resolve_xy(wf) if wf else None
                    if pt:
                        add_xy(pt[0], pt[1])
            elif f.kind == FeatureKind.DERIVED_CIRCLE:
                cx_ = float(p.get("cx", 0))
                cy_ = float(p.get("cy", 0))
                r = float(p.get("r", 0))
                add_xy(cx_ - r, cy_ - r)
                add_xy(cx_ + r, cy_ + r)
            elif f.kind == FeatureKind.DERIVED_POINT:
                add_xy(float(p.get("x", 0)), float(p.get("y", 0)))

        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _redraw(self, *args):
        self.canvas.clear()
        iw = max(self.width, 1.0)
        ih = max(self.height, 1.0)

        with self.canvas:
            PushMatrix()
            Translate(self.x, self.y)
            Color(0.12, 0.12, 0.13, 1)
            Rectangle(pos=(0, 0), size=(iw, ih))

            bb = self._bbox()
            if bb is None or not self._features:
                self._has_valid_transform = False
                PopMatrix()
                self.canvas.ask_update()
                return

            min_x, min_y, max_x, max_y = bb
            pad = 6.0
            min_x -= pad
            max_x += pad
            min_y -= pad
            max_y += pad
            span_x = max(max_x - min_x, 1e-6)
            span_y = max(max_y - min_y, 1e-6)
            scale = min(iw / span_x, ih / span_y) * 0.88
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0

            # Save transform for hit-testing in on_touch_down.
            self._last_scale = scale
            self._last_cx = cx
            self._last_cy = cy
            self._last_iw = iw
            self._last_ih = ih
            self._has_valid_transform = True

            def px(wx: float, wy: float) -> tuple[float, float]:
                return (
                    iw / 2.0 + (wx - cx) * scale,
                    ih / 2.0 + (wy - cy) * scale,
                )

            ux0, uy0 = px(0.0, 0.0)
            # Axis arms: inset so strokes (and aa) stay inside the sketch rect.
            arm = 22.0
            edge_m = 4.0
            lx = ux0
            ly = uy0
            inside_x = edge_m <= lx <= iw - edge_m
            inside_y = edge_m <= ly <= ih - edge_m
            half_h = min(arm, max(lx - edge_m, 0), max(iw - lx - edge_m, 0))
            half_v = min(arm, max(ly - edge_m, 0), max(ih - ly - edge_m, 0))
            Color(0.28, 0.29, 0.32, 1)
            # Horizontal ruler only if origin lies within usable vertical band (otherwise
            # the segment is off-screen horizontally and still rasterizes into neighbors).
            if inside_y and half_h >= 2.0:
                Line(points=[lx - half_h, ly, lx + half_h, ly], width=1.0)
            if inside_x and half_v >= 2.0:
                Line(points=[lx, ly - half_v, lx, ly + half_v], width=1.0)

            by_id = index_by_id(self._features)

            for f in self._features:
                if f.kind == FeatureKind.SEGMENT:
                    ends = segment_endpoints(by_id, f)
                    if not ends:
                        continue
                    (x1, y1), (x2, y2) = ends
                    u1, v1 = px(x1, y1)
                    u2, v2 = px(x2, y2)
                    Color(0.75, 0.55, 0.95, 1)
                    Line(points=[u1, v1, u2, v2], width=1.4)

                elif f.kind == FeatureKind.POLYLINE:
                    p = f.payload
                    verts = p.get("vertex_feature_ids") or []
                    if not isinstance(verts, list):
                        continue
                    pts_px: list[float] = []
                    for vid in verts:
                        wf = by_id.get(str(vid))
                        pt = resolve_xy(wf) if wf else None
                        if pt:
                            a, b = px(pt[0], pt[1])
                            pts_px.extend([a, b])
                    if len(pts_px) >= 4:
                        Color(0.45, 0.72, 0.55, 1)
                        line_pts = pts_px
                        if p.get("closed") and len(pts_px) >= 6:
                            line_pts = pts_px + pts_px[:2]
                        Line(points=line_pts, width=1.3)

                elif f.kind == FeatureKind.DERIVED_CIRCLE:
                    p = f.payload
                    cx_ = float(p.get("cx", 0))
                    cy_ = float(p.get("cy", 0))
                    r = float(p.get("r", 0))
                    Color(0.9, 0.55, 0.35, 1)
                    ovals: list[float] = []
                    for i in range(33):
                        t = 2 * math.pi * i / 32
                        wx = cx_ + r * math.cos(t)
                        wy = cy_ + r * math.sin(t)
                        u, vv = px(wx, wy)
                        ovals.extend([u, vv])
                    Line(points=ovals, width=1.2)

                elif f.kind == FeatureKind.DERIVED_POINT:
                    p = f.payload
                    x = float(p.get("x", 0))
                    y = float(p.get("y", 0))
                    u, v = px(x, y)
                    s = max(3.0, abs(scale) * 0.45)
                    Color(0.95, 0.92, 0.4, 1)
                    Line(points=[u - s, v, u + s, v], width=1.5)
                    Line(points=[u, v - s, u, v + s], width=1.5)

            for f in self._features:
                if f.kind == FeatureKind.POINT:
                    x = float(f.payload.get("x", 0))
                    y = float(f.payload.get("y", 0))
                    u, v = px(x, y)
                    s = max(3.0, abs(scale) * 0.4)
                    Color(0.35, 0.85, 0.95, 1)
                    Line(points=[u - s, v, u + s, v], width=1.4)
                    Line(points=[u, v - s, u, v + s], width=1.4)
                elif f.kind == FeatureKind.CIRCLE:
                    cx_ = float(f.payload.get("cx", 0))
                    cy_ = float(f.payload.get("cy", 0))
                    rdx = float(f.payload.get("diameter_x", 0)) / 2.0
                    rdy = float(f.payload.get("diameter_y", 0)) / 2.0
                    Color(0.55, 0.8, 0.45, 1)
                    pts_circ: list[float] = []
                    for i in range(33):
                        t = 2 * math.pi * i / 32
                        wx = cx_ + rdx * math.cos(t)
                        wy = cy_ + rdy * math.sin(t)
                        a, b = px(wx, wy)
                        pts_circ.extend([a, b])
                    Line(points=pts_circ, width=1.2)
                elif f.kind == FeatureKind.CORNER:
                    x = float(f.payload.get("x", 0))
                    y = float(f.payload.get("y", 0))
                    u, v = px(x, y)
                    Color(0.95, 0.75, 0.35, 1)
                    s = max(4.0, abs(scale) * 0.45)
                    Line(
                        points=[
                            u - s,
                            v - s,
                            u + s,
                            v - s,
                            u + s,
                            v + s,
                            u - s,
                            v + s,
                            u - s,
                            v - s,
                        ],
                        width=1.2,
                    )

            for ord_idx, fid in enumerate(self._selection_ids):
                sf = by_id.get(fid)
                if sf is None:
                    continue
                col = _SEL_ORDER_PALETTE[ord_idx % len(_SEL_ORDER_PALETTE)]
                self._draw_feature_highlight(sf, by_id, px, scale, col, 2.2)

            if self._focus_id:
                ff = by_id.get(self._focus_id)
                if ff is not None:
                    self._draw_feature_highlight(
                        ff, by_id, px, scale, (1.0, 1.0, 1.0, 0.93), 3.0
                    )

            if self._selection_ids:
                self._draw_selection_order_badges(by_id, px, scale, iw, ih)

            PopMatrix()

        self.canvas.ask_update()
