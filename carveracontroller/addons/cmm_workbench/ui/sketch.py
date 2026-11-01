"""2D XY preview of probe-scan features (active work XY plane, mm)."""

from __future__ import annotations

import math
from collections.abc import Callable

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Translate
from kivy.metrics import dp
from kivy.uix.widget import Widget

from carveracontroller.ui.theme import get_theme, watch_theme

from ..core.features import (
    CircleGeom,
    CMMWorkbenchFeature,
    FeatureGeom,
    FeatureKind,
    LabelGeom,
    PointGeom,
    PolylineGeom,
    SegmentGeom,
    index_by_id,
    resolve_geometry,
)


def _cmm_selection_palette(theme) -> tuple[list, ...]:
    """Construction checkbox order: 1st, 2nd, 3rd, … in the XY preview."""
    return (
        list(theme.cmm_feature_1),
        list(theme.cmm_feature_2),
        list(theme.cmm_feature_3),
        list(theme.cmm_feature_4),
        list(theme.cmm_feature_5),
    )


def _ellipse_polyline_px(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    px: Callable[[float, float], tuple[float, float]],
) -> list[float]:
    """Closed ellipse/circle outline as Kivy Line ``points`` (widget-local px)."""
    pts: list[float] = []
    for i in range(33):
        t = 2 * math.pi * i / 32
        wx = cx + rx * math.cos(t)
        wy = cy + ry * math.sin(t)
        a, b = px(wx, wy)
        pts.extend([a, b])
    return pts


class CMMWorkbenchPreviewSketch(Widget):
    """Redraw when features or table/focus/selection state change via ``set_features``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._features: list[CMMWorkbenchFeature] = []
        self._hidden_ids: set[str] = set()
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
        self._stop_theme = watch_theme(lambda _theme: self._redraw())

    def set_features(
        self,
        feats: list[CMMWorkbenchFeature],
        *,
        focus_id: str | None = None,
        selection_ids: list[str] | None = None,
        hidden_ids: set[str] | None = None,
    ):
        self._features = list(feats)
        self._hidden_ids = set(hidden_ids) if hidden_ids else set()
        self._focus_id = focus_id
        self._selection_ids = list(selection_ids) if selection_ids is not None else []
        self._redraw()

    def _is_visible(self, f: CMMWorkbenchFeature) -> bool:
        return f.id not in self._hidden_ids

    def _draw_texture_label(
        self,
        text: str,
        cx: float,
        cy: float,
        *,
        font_size: float,
        color: tuple[float, float, float, float],
        y_offset: float = 0.0,
    ) -> None:
        """Draw a centered Kivy text texture at widget-local pixel coords."""
        theme = get_theme()
        text_outline = list(theme.sketch_text_outline)
        try:
            label = CoreLabel(
                text=text,
                font_size=font_size,
                bold=True,
                color=color[:4],
                outline_width=1,
                outline_color=text_outline,
            )
        except TypeError:
            label = CoreLabel(
                text=text,
                font_size=font_size,
                bold=True,
                color=color[:4],
            )
        label.refresh()
        tex = label.texture
        if tex is None or tex.width < 1:
            return
        tw, th = tex.size
        Color(1, 1, 1, 1)
        Rectangle(
            texture=tex,
            pos=(cx - tw * 0.5, cy - th * 0.5 + y_offset),
            size=(tw, th),
        )

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

    def _seg_dist_px(self, x1: float, y1: float, x2: float, y2: float, tx: float, ty: float) -> float:
        """Screen-pixel distance from (tx, ty) to segment (x1,y1)-(x2,y2)."""
        u1, v1 = self._world_to_px(x1, y1)
        u2, v2 = self._world_to_px(x2, y2)
        dx, dy = u2 - u1, v2 - v1
        L2 = dx * dx + dy * dy
        if L2 < 1e-6:
            return math.hypot(tx - u1, ty - v1)
        t = max(0.0, min(1.0, ((tx - u1) * dx + (ty - v1) * dy) / L2))
        return math.hypot(tx - u1 - t * dx, ty - v1 - t * dy)

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

    def _hit_radius_for_feature(self, f: CMMWorkbenchFeature, by_id: dict[str, CMMWorkbenchFeature]) -> float:
        """Screen-space hit radius in pixels for a given feature."""
        sc = abs(self._last_scale)
        geom = resolve_geometry(f, by_id)
        if isinstance(geom, LabelGeom):
            return max(dp(24), sc * 0.85)
        if isinstance(geom, PointGeom) or geom is None:
            return max(dp(18), sc * 0.65)
        if isinstance(geom, CircleGeom):
            if geom.kind == FeatureKind.ELLIPSE:
                rep_r = (geom.rx + geom.ry) / 2.0
            else:
                rep_r = geom.rx
            ring_px = max(rep_r * sc, dp(8))
            return max(dp(26), dp(16) + ring_px * 0.42)
        # SegmentGeom, PolylineGeom
        return dp(20)

    def _distance_to_feature_px(self, f: CMMWorkbenchFeature, by_id: dict, tx: float, ty: float) -> float:
        """Minimum screen-pixel distance from (tx, ty) to feature geometry."""
        geom = resolve_geometry(f, by_id)
        if geom is None:
            return float("inf")
        if isinstance(geom, (PointGeom, LabelGeom)):
            u, v = self._world_to_px(geom.x, geom.y)
            return math.hypot(tx - u, ty - v)
        if isinstance(geom, CircleGeom):
            return self._circle_hit_distance_px(geom.cx, geom.cy, geom.rx, geom.ry, tx, ty)
        if isinstance(geom, SegmentGeom):
            return self._seg_dist_px(geom.x1, geom.y1, geom.x2, geom.y2, tx, ty)
        if isinstance(geom, PolylineGeom):
            if len(geom.vertices) < 2:
                return float("inf")
            edges = list(zip(geom.vertices, geom.vertices[1:]))
            if geom.closed:
                edges.append((geom.vertices[-1], geom.vertices[0]))
            return min(self._seg_dist_px(ax, ay, bx, by, tx, ty) for (ax, ay), (bx, by) in edges)
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
            if not self._is_visible(f):
                continue
            d = self._distance_to_feature_px(f, by_id, tx, ty)
            hr = self._hit_radius_for_feature(f, by_id)
            if d <= hr and d < best_dist:
                best_dist = d
                best_id = f.id
        if best_id is not None and self.on_feature_tap is not None:
            self.on_feature_tap(best_id)
            return True
        return super().on_touch_down(touch)

    def _draw_feature_highlight(
        self,
        f: CMMWorkbenchFeature,
        by_id: dict[str, CMMWorkbenchFeature],
        px,
        scale: float,
        rgba: tuple[float, float, float, float],
        lw: float,
    ) -> None:
        geom = resolve_geometry(f, by_id)
        if geom is None:
            return
        Color(*rgba)
        if isinstance(geom, PointGeom):
            u, v = px(geom.x, geom.y)
            if geom.kind == FeatureKind.CORNER:
                s = max(5.5, abs(scale) * 0.52)
                Line(
                    points=[u - s, v - s, u + s, v - s, u + s, v + s, u - s, v + s, u - s, v - s],
                    width=lw,
                )
            else:
                s = max(5.0, abs(scale) * 0.58)
                Line(points=[u - s, v, u + s, v], width=lw)
                Line(points=[u, v - s, u, v + s], width=lw)
        elif isinstance(geom, LabelGeom):
            u, v = px(geom.x, geom.y)
            s = max(4.0, abs(scale) * 0.45)
            Line(points=[u - s, v, u + s, v], width=lw)
            Line(points=[u, v - s, u, v + s], width=lw)
        elif isinstance(geom, CircleGeom):
            Line(
                points=_ellipse_polyline_px(geom.cx, geom.cy, geom.rx, geom.ry, px),
                width=lw,
            )
        elif isinstance(geom, SegmentGeom):
            u1, v1 = px(geom.x1, geom.y1)
            u2, v2 = px(geom.x2, geom.y2)
            Line(points=[u1, v1, u2, v2], width=lw)
        elif isinstance(geom, PolylineGeom):
            pts_px: list[float] = []
            for vx, vy in geom.vertices:
                a, b = px(vx, vy)
                pts_px.extend([a, b])
            if len(pts_px) >= 4:
                line_pts = pts_px + pts_px[:2] if geom.closed and len(pts_px) >= 6 else pts_px
                Line(points=line_pts, width=lw)

    def _selection_badge_anchor_px(
        self,
        f: CMMWorkbenchFeature,
        by_id: dict[str, CMMWorkbenchFeature],
        px,
    ) -> tuple[float, float] | None:
        geom = resolve_geometry(f, by_id)
        if geom is None:
            return None
        if isinstance(geom, (PointGeom, LabelGeom)):
            return px(geom.x, geom.y)
        if isinstance(geom, CircleGeom):
            return px(geom.cx, geom.cy)
        if isinstance(geom, SegmentGeom):
            return px((geom.x1 + geom.x2) * 0.5, (geom.y1 + geom.y2) * 0.5)
        if isinstance(geom, PolylineGeom):
            if not geom.vertices:
                return None
            cx = sum(v[0] for v in geom.vertices) / len(geom.vertices)
            cy = sum(v[1] for v in geom.vertices) / len(geom.vertices)
            return px(cx, cy)
        return None

    def _selection_badge_layout_px(
        self,
        f: CMMWorkbenchFeature,
        by_id: dict[str, CMMWorkbenchFeature],
        px,
        scale: float,
        iw: float,
        ih: float,
        ord_idx: int,
        au: float,
        av: float,
    ) -> tuple[float, float]:
        """Screen-pixel position for an order badge, kept away from mark geometry."""
        geom = resolve_geometry(f, by_id)
        sc = abs(scale)

        if isinstance(geom, (PointGeom, LabelGeom)):
            if isinstance(geom, PointGeom) and geom.kind == FeatureKind.CORNER:
                s = max(5.5, sc * 0.52)
                clear = s * math.sqrt(2) + dp(14)
            else:
                s = max(5.0, sc * 0.58)
                clear = s + dp(14)
            if isinstance(geom, LabelGeom):
                clear += dp(10)
            ang = math.pi / 4 + (ord_idx % 4) * (math.pi / 2) + (ord_idx // 4) * 0.22
            return au + math.cos(ang) * clear, av + math.sin(ang) * clear

        # For non-point geometries, compute a radial offset from canvas centre.
        cx_s = iw * 0.5
        cy_s = ih * 0.5
        dx, dy = au - cx_s, av - cy_s
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            dx, dy = 1.0, 0.0
        else:
            dx /= dist
            dy /= dist
        perp_x, perp_y = -dy, dx

        if isinstance(geom, CircleGeom):
            if geom.kind == FeatureKind.ELLIPSE:
                rw = max(geom.rx, geom.ry, 1e-6)
            else:
                rw = max(geom.rx, 1e-6)
            badge_off = sc * rw + dp(14)
        elif isinstance(geom, SegmentGeom):
            u1, v1 = px(geom.x1, geom.y1)
            u2, v2 = px(geom.x2, geom.y2)
            slen = math.hypot(u2 - u1, v2 - v1)
            badge_off = max(dp(16), slen * 0.28 + dp(12))
        elif isinstance(geom, PolylineGeom) and geom.vertices:
            cx = sum(v[0] for v in geom.vertices) / len(geom.vertices)
            cy = sum(v[1] for v in geom.vertices) / len(geom.vertices)
            max_wd = max(math.hypot(vx - cx, vy - cy) for vx, vy in geom.vertices)
            badge_off = max(dp(16), max_wd * sc + dp(12))
        else:
            badge_off = dp(14)

        tang = (ord_idx % 5) * dp(4)
        return au + dx * badge_off + perp_x * tang, av + dy * badge_off + perp_y * tang

    def _draw_selection_order_badges(
        self,
        by_id: dict[str, CMMWorkbenchFeature],
        px,
        scale: float,
        iw: float,
        ih: float,
    ) -> None:
        theme = get_theme()
        palette = _cmm_selection_palette(theme)
        sketch_outline = list(theme.sketch_outline)
        font_size = max(dp(11), min(dp(16), abs(scale) * 0.38))
        for ord_idx, fid in enumerate(self._selection_ids):
            sf = by_id.get(fid)
            if sf is None or not self._is_visible(sf):
                continue
            anchor = self._selection_badge_anchor_px(sf, by_id, px)
            if anchor is None:
                continue
            au, av = anchor
            tu, tv = self._selection_badge_layout_px(sf, by_id, px, scale, iw, ih, ord_idx, au, av)

            col = palette[ord_idx % len(palette)]
            try:
                label = CoreLabel(
                    text=str(ord_idx + 1),
                    font_size=font_size,
                    bold=True,
                    color=col[:4],
                    outline_width=1,
                    outline_color=sketch_outline,
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
        for f in self._features:
            if not self._is_visible(f):
                continue
            geom = resolve_geometry(f, by_id)
            if isinstance(geom, (PointGeom, LabelGeom)):
                xs.append(geom.x)
                ys.append(geom.y)
                if isinstance(geom, LabelGeom):
                    pad = max(4.0, len(geom.text) * 0.45)
                    xs.extend([geom.x - pad, geom.x + pad])
                    ys.extend([geom.y - pad, geom.y + pad])
            elif isinstance(geom, CircleGeom):
                xs.extend([geom.cx - geom.rx, geom.cx + geom.rx])
                ys.extend([geom.cy - geom.ry, geom.cy + geom.ry])
            elif isinstance(geom, SegmentGeom):
                xs.extend([geom.x1, geom.x2])
                ys.extend([geom.y1, geom.y2])
            elif isinstance(geom, PolylineGeom):
                for vx, vy in geom.vertices:
                    xs.append(vx)
                    ys.append(vy)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _redraw(self, *args):
        self.canvas.clear()
        theme = get_theme()
        palette = _cmm_selection_palette(theme)
        iw = max(self.width, 1.0)
        ih = max(self.height, 1.0)

        with self.canvas:
            PushMatrix()
            Translate(self.x, self.y)
            Color(*theme.sketch_bg)
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
            arm = 22.0
            edge_m = 4.0
            lx = ux0
            ly = uy0
            inside_x = edge_m <= lx <= iw - edge_m
            inside_y = edge_m <= ly <= ih - edge_m
            half_h = min(arm, max(lx - edge_m, 0), max(iw - lx - edge_m, 0))
            half_v = min(arm, max(ly - edge_m, 0), max(ih - ly - edge_m, 0))
            Color(*theme.sketch_axes)
            if inside_y and half_h >= 2.0:
                Line(points=[lx - half_h, ly, lx + half_h, ly], width=1.0)
            if inside_x and half_v >= 2.0:
                Line(points=[lx, ly - half_v, lx, ly + half_v], width=1.0)

            by_id = index_by_id(self._features)
            # Precompute all geometries once for both drawing passes.
            feature_geoms: list[tuple[CMMWorkbenchFeature, FeatureGeom]] = [
                (f, resolve_geometry(f, by_id)) for f in self._features if self._is_visible(f)
            ]

            # First pass: constructed/derived geometry (drawn underneath)
            for f, geom in feature_geoms:
                if isinstance(geom, SegmentGeom):
                    u1, v1 = px(geom.x1, geom.y1)
                    u2, v2 = px(geom.x2, geom.y2)
                    Color(*theme.cmm_feature_5)
                    Line(points=[u1, v1, u2, v2], width=1.4)

                elif isinstance(geom, PolylineGeom):
                    pts_px: list[float] = []
                    for vx, vy in geom.vertices:
                        a, b = px(vx, vy)
                        pts_px.extend([a, b])
                    if len(pts_px) >= 4:
                        Color(*theme.cmm_polyline)
                        line_pts = pts_px + pts_px[:2] if geom.closed and len(pts_px) >= 6 else pts_px
                        Line(points=line_pts, width=1.3)

                elif isinstance(geom, CircleGeom) and geom.kind == FeatureKind.DERIVED_CIRCLE:
                    Color(*theme.cmm_derived_circle)
                    Line(
                        points=_ellipse_polyline_px(geom.cx, geom.cy, geom.rx, geom.ry, px),
                        width=1.2,
                    )

                elif isinstance(geom, PointGeom) and geom.kind == FeatureKind.DERIVED_POINT:
                    u, v = px(geom.x, geom.y)
                    s = max(3.0, abs(scale) * 0.45)
                    Color(*theme.cmm_derived_point)
                    Line(points=[u - s, v, u + s, v], width=1.5)
                    Line(points=[u, v - s, u, v + s], width=1.5)

            # Second pass: probed features (drawn on top)
            for f, geom in feature_geoms:
                if isinstance(geom, PointGeom) and geom.kind == FeatureKind.POINT:
                    u, v = px(geom.x, geom.y)
                    s = max(3.0, abs(scale) * 0.4)
                    Color(*theme.cmm_probed_point)
                    Line(points=[u - s, v, u + s, v], width=1.4)
                    Line(points=[u, v - s, u, v + s], width=1.4)

                elif isinstance(geom, CircleGeom) and geom.kind in (FeatureKind.CIRCLE, FeatureKind.ELLIPSE):
                    Color(*theme.cmm_circle)
                    Line(
                        points=_ellipse_polyline_px(geom.cx, geom.cy, geom.rx, geom.ry, px),
                        width=1.2,
                    )

                elif isinstance(geom, PointGeom) and geom.kind == FeatureKind.CORNER:
                    u, v = px(geom.x, geom.y)
                    s = max(4.0, abs(scale) * 0.45)
                    Color(*theme.cmm_corner)
                    Line(
                        points=[u - s, v - s, u + s, v - s, u + s, v + s, u - s, v + s, u - s, v - s],
                        width=1.2,
                    )

                elif isinstance(geom, LabelGeom) and geom.kind == FeatureKind.ANGLE:
                    u, v = px(geom.x, geom.y)
                    s = max(3.0, abs(scale) * 0.4)
                    Color(*theme.cmm_angle_mark)
                    Line(points=[u - s, v, u + s, v], width=1.3)
                    Line(points=[u, v - s, u, v + s], width=1.3)
                    font_size = max(dp(10), min(dp(15), abs(scale) * 0.42))
                    self._draw_texture_label(
                        geom.text,
                        u,
                        v,
                        font_size=font_size,
                        color=list(theme.cmm_angle_label),
                        y_offset=dp(6),
                    )

            # Selection highlights and order badges
            for ord_idx, fid in enumerate(self._selection_ids):
                sf = by_id.get(fid)
                if sf is None or not self._is_visible(sf):
                    continue
                col = palette[ord_idx % len(palette)]
                self._draw_feature_highlight(sf, by_id, px, scale, col, 2.2)

            if self._focus_id:
                ff = by_id.get(self._focus_id)
                if ff is not None and self._is_visible(ff):
                    self._draw_feature_highlight(ff, by_id, px, scale, list(theme.sketch_focus), 3.0)

            if self._selection_ids:
                self._draw_selection_order_badges(by_id, px, scale, iw, ih)

            PopMatrix()

        self.canvas.ask_update()
