"""Top-down XY sketch for facing wizard preview (work coordinates, mm)."""

import math

from kivy.factory import Factory
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    PopMatrix,
    PushMatrix,
    Rectangle,
    Translate,
)
from kivy.uix.widget import Widget

from .facing_gcode import FacingEnvelope
from .probe_grid_gcode import ProbeGridGeometry


class FacingXYPreviewSketch(Widget):
    """Redraw when pos/size change via geometry setter."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *args):
        self.canvas.clear()
        iw = max(self.width, 1.0)
        ih = max(self.height, 1.0)

        with self.canvas:
            PushMatrix()
            Translate(self.x, self.y)
            Color(0.12, 0.12, 0.13, 1)
            Rectangle(pos=(0, 0), size=(iw, ih))

            g = getattr(self, "_geom", None)
            if not g:
                PopMatrix()
            else:
                stock_rect = g.get("stock_rect")
                machining_rect = g.get("machining_rect")
                facing = g.get("facing")
                probe_geom: ProbeGridGeometry | None = g.get("probe_geom")
                toolpath = g.get("toolpath")
                if not stock_rect:
                    PopMatrix()
                else:
                    self._draw_geometry_inner(
                        iw,
                        ih,
                        stock_rect,
                        machining_rect,
                        facing,
                        probe_geom,
                        toolpath,
                    )
                    PopMatrix()

        self.canvas.ask_update()

    def _draw_geometry_inner(
        self,
        iw: float,
        ih: float,
        stock_rect,
        machining_rect,
        facing,
        probe_geom: ProbeGridGeometry | None,
        toolpath,
    ):
        min_x, min_y, max_x, max_y = self._bbox(
            stock_rect, machining_rect, facing, probe_geom, toolpath
        )
        pad_frac = 0.06
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        min_x -= span_x * pad_frac
        max_x += span_x * pad_frac
        min_y -= span_y * pad_frac
        max_y += span_y * pad_frac
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)

        scale = min(iw / span_x, ih / span_y) * 0.92
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0

        def px(wx: float, wy: float) -> tuple[float, float]:
            return (
                iw / 2.0 + (wx - cx) * scale,
                ih / 2.0 + (wy - cy) * scale,
            )

        nx0, ny0, nx1, ny1 = stock_rect
        if (
            machining_rect is not None
            and not self._same_rect(stock_rect, machining_rect)
        ):
            mx0, my0, mx1, my1 = machining_rect
            p_bl = px(mx0, my0)
            p_br = px(mx1, my0)
            p_tr = px(mx1, my1)
            p_tl = px(mx0, my1)
            # Kivy Line(dash_length=…) seems to be unreliable, draw dashes explicitly.
            dash_px = max(5.0, abs(scale) * 1.15)
            gap_px = max(3.0, abs(scale) * 0.75)
            Color(0.48, 0.48, 0.5, 0.75)
            for a, b in ((p_bl, p_br), (p_br, p_tr), (p_tr, p_tl), (p_tl, p_bl)):
                for seg in self._dash_segment_pairs(a, b, dash_px, gap_px):
                    Line(points=seg, width=1)

        flat_stock = self._rect_line(nx0, ny0, nx1, ny1, px)
        Color(0.62, 0.62, 0.65, 1)
        Line(points=flat_stock, width=1.75)

        if probe_geom is not None:
            gx0, gx1 = probe_geom.inset_x0, probe_geom.inset_x1
            gy0, gy1 = probe_geom.inset_y0, probe_geom.inset_y1
            Color(0.35, 0.55, 0.85, 1)
            Line(
                points=self._rect_line(gx0, gy0, gx1, gy1, px),
                width=1,
            )
            pr = max(scale * 0.35, 1.5)
            Color(0.45, 0.65, 0.95, 1)
            for wy in probe_geom.ys:
                for wx in probe_geom.xs:
                    cxp, cyp = px(wx, wy)
                    Ellipse(pos=(cxp - pr, cyp - pr), size=(2 * pr, 2 * pr))

        if facing is not None:
            fx0, fy0, fx1, fy1 = (
                facing.facing_xa,
                facing.facing_ya,
                facing.facing_xb,
                facing.facing_yb,
            )
            Color(0.92, 0.35, 0.28, 1)
            Line(
                points=self._rect_line(fx0, fy0, fx1, fy1, px),
                width=1.5,
            )

        if toolpath:
            flat = []
            step = max(1, len(toolpath) // 400)
            for i in range(0, len(toolpath), step):
                x, y = toolpath[i]
                qx, qy = px(x, y)
                flat.extend([qx, qy])
            Color(0.95, 0.72, 0.35, 0.65)
            Line(points=flat, width=1)

        ox0, oy0 = px(0.0, 0.0)
        nw = max(abs(nx1 - nx0), 1e-6)
        nh = max(abs(ny1 - ny0), 1e-6)
        arm_x = max(min(span_x * 0.09, nw * 0.24), nw * 0.06)
        arm_y = max(min(span_y * 0.09, nh * 0.24), nh * 0.06)
        ox_x, oy_x = px(arm_x, 0.0)
        ox_y, oy_y = px(0.0, arm_y)
        orad = max(min(scale * 1.1, 8.0), 4.5)
        Color(0.93, 0.93, 0.96, 0.95)
        Ellipse(pos=(ox0 - orad, oy0 - orad), size=(2 * orad, 2 * orad))
        Color(0.22, 0.22, 0.24, 1)
        Ellipse(pos=(ox0 - orad * 0.35, oy0 - orad * 0.35), size=(orad * 0.7, orad * 0.7))
        Color(0.35, 0.78, 0.42, 1)
        Line(points=[ox0, oy0, ox_x, oy_x], width=2.8)
        Color(0.95, 0.55, 0.28, 1)
        Line(points=[ox0, oy0, ox_y, oy_y], width=2.8)

    @staticmethod
    def _dash_segment_pairs(
        pa: tuple[float, float],
        pb: tuple[float, float],
        dash_px: float,
        gap_px: float,
    ) -> list[list[float]]:
        """Screen-space dash segments as separate polylines [x0,y0,x1,y1]."""
        x0, y0 = pa
        x1, y1 = pb
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1.0:
            return []
        ux, uy = dx / length, dy / length
        out: list[list[float]] = []
        t = 0.0
        draw = True
        while t < length - 1e-6:
            if draw:
                seg_end = min(t + dash_px, length)
                out.append(
                    [
                        x0 + ux * t,
                        y0 + uy * t,
                        x0 + ux * seg_end,
                        y0 + uy * seg_end,
                    ]
                )
                t = seg_end
            else:
                t = min(t + gap_px, length)
            draw = not draw
        return out

    @staticmethod
    def _same_rect(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
        eps: float = 1e-6,
    ) -> bool:
        return all(abs(a[i] - b[i]) < eps for i in range(4))

    @staticmethod
    def _rect_line(x0: float, y0: float, x1: float, y1: float, px):
        c1 = px(x0, y0)
        c2 = px(x1, y0)
        c3 = px(x1, y1)
        c4 = px(x0, y1)
        return [
            c1[0],
            c1[1],
            c2[0],
            c2[1],
            c3[0],
            c3[1],
            c4[0],
            c4[1],
            c1[0],
            c1[1],
        ]

    @staticmethod
    def _bbox(stock_rect, machining_rect, facing, probe_geom, toolpath):
        sx0, sy0, sx1, sy1 = stock_rect
        min_x, max_x = min(sx0, sx1), max(sx0, sx1)
        min_y, max_y = min(sy0, sy1), max(sy0, sy1)
        if machining_rect is not None:
            ex0, ey0, ex1, ey1 = machining_rect
            min_x = min(min_x, ex0, ex1)
            max_x = max(max_x, ex0, ex1)
            min_y = min(min_y, ey0, ey1)
            max_y = max(max_y, ey0, ey1)
        if facing is not None:
            min_x = min(min_x, facing.facing_xa, facing.facing_xb)
            max_x = max(max_x, facing.facing_xa, facing.facing_xb)
            min_y = min(min_y, facing.facing_ya, facing.facing_yb)
            max_y = max(max_y, facing.facing_ya, facing.facing_yb)
        if probe_geom is not None:
            min_x = min(min_x, probe_geom.inset_x0, probe_geom.inset_x1)
            max_x = max(max_x, probe_geom.inset_x0, probe_geom.inset_x1)
            min_y = min(min_y, probe_geom.inset_y0, probe_geom.inset_y1)
            max_y = max(max_y, probe_geom.inset_y0, probe_geom.inset_y1)
            for wy in probe_geom.ys:
                for wx in probe_geom.xs:
                    min_x = min(min_x, wx)
                    max_x = max(max_x, wx)
                    min_y = min(min_y, wy)
                    max_y = max(max_y, wy)
        if toolpath:
            for x, y in toolpath:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
        min_x = min(min_x, 0.0)
        min_y = min(min_y, 0.0)
        max_x = max(max_x, 0.0)
        max_y = max(max_y, 0.0)
        return min_x, min_y, max_x, max_y

    def set_geometry(
        self,
        *,
        stock_rect: tuple[float, float, float, float] | None,
        machining_rect: tuple[float, float, float, float] | None = None,
        facing: FacingEnvelope | None = None,
        probe_geom: ProbeGridGeometry | None = None,
        toolpath: list[tuple[float, float]] | None = None,
    ):
        if stock_rect is None:
            self._geom = None
        else:
            self._geom = {
                "stock_rect": stock_rect,
                "machining_rect": machining_rect,
                "facing": facing,
                "probe_geom": probe_geom,
                "toolpath": toolpath,
            }
        self._redraw()

    def clear_geometry(self):
        self._geom = None
        self._redraw()


Factory.register("FacingSketch", cls=FacingXYPreviewSketch)
