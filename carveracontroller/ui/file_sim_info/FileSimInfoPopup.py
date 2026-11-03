"""Modal file stats and programmed MRR chart."""

from __future__ import annotations

import logging
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.properties import BooleanProperty, NumericProperty, StringProperty  # noqa: E402
from kivy.uix.modalview import ModalView  # noqa: E402

from carveracontroller.translation import tr  # noqa: E402
from carveracontroller.ui.file_sim_info.summary import (  # noqa: E402
    FileSimSummary,
    mrr_at_time,
    summarize_file_sim,
    vertex_at_time,
)
from carveracontroller.ui.theme import get_theme, watch_theme  # noqa: E402
from carveracontroller.Utils import second2hour  # noqa: E402

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_S = 0.5


class FileSimInfoPopup(ModalView):
    show_empty = BooleanProperty(True)
    wide = BooleanProperty(False)  # two-column layout, driven by the width in the .kv
    caption_hint = NumericProperty(0.34)
    file_caption = StringProperty("")
    time_caption = StringProperty("")
    length_caption = StringProperty("")
    volume_caption = StringProperty("")
    peak_caption = StringProperty("")
    average_caption = StringProperty("")
    file_text = StringProperty("")
    time_text = StringProperty("")
    length_text = StringProperty("")
    volume_text = StringProperty("")
    peak_text = StringProperty("")
    average_text = StringProperty("")
    coverage_text = StringProperty("")
    # Cursor line and tooltip over the chart (window coordinates, see the .kv).
    hover_visible = BooleanProperty(False)
    hover_x = NumericProperty(0.0)
    hover_y0 = NumericProperty(0.0)
    hover_y1 = NumericProperty(0.0)
    hover_text = StringProperty("")

    def __init__(self, **kwargs):
        self._plotted: list[tuple[Any, int | None]] = []
        self._chart_series: tuple = ()
        self._vertex_times = None
        self._label_size = 11.0
        self._refresh_event = None
        self._stop_theme = None
        self._signature = None
        self._last_key = None
        super().__init__(**kwargs)
        self._build_chart()
        self.bind(on_open=self._on_open, on_dismiss=self._on_dismiss)

    def _build_chart(self) -> None:
        chart = self.ids.get("chart")
        if chart is None:
            return
        self._label_size = float(dp(8)) * 1.2
        fig, ax = plt.subplots(1, 1, figsize=(6.4, 3.2))
        ax.set_xlabel(tr._("Estimated time (min)"), fontsize=self._label_size)
        ax.set_ylabel(tr._("MRR (mm³/min)"), fontsize=self._label_size)
        # Re-run the tight layout on every draw, so that the axis labels keep
        # fitting when the figure is resized with the window.
        if hasattr(fig, "set_layout_engine"):
            fig.set_layout_engine("tight", pad=0.45)
        else:
            fig.set_tight_layout({"pad": 0.45})  # type: ignore[attr-defined]
        chart.fast_draw = False
        chart.figure = fig
        self._apply_chart_theme()

    def _on_open(self, *_args) -> None:
        if self._stop_theme is not None:
            self._stop_theme()
        self._stop_theme = watch_theme(self._apply_chart_theme)
        self.hover_visible = False
        Window.unbind(mouse_pos=self._on_mouse_pos)
        Window.bind(mouse_pos=self._on_mouse_pos)
        self.refresh()
        self._stop_refresh()
        self._refresh_event = Clock.schedule_interval(self._on_refresh_tick, _REFRESH_INTERVAL_S)

    def _on_dismiss(self, *_args) -> None:
        self._stop_refresh()
        Window.unbind(mouse_pos=self._on_mouse_pos)
        self.hover_visible = False
        if self._stop_theme is not None:
            self._stop_theme()
            self._stop_theme = None
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        restore = getattr(root, "restore_keyboard_jog_control", None)
        if restore is not None:
            try:
                restore()
            except Exception:
                logger.exception("failed to restore keyboard jog")

    def _locate_on_chart(self, pos):
        """Chart time (minutes) under a window position, with the plot area bounds.

        Returns ``(time_min, x, y0, y1)``, the last three in window coordinates, or None
        when the position is outside of the plot area or there is nothing to point at.
        """
        chart = self.ids.get("chart") if getattr(self, "ids", None) else None
        if chart is None or chart.figure is None or not chart.figure.axes:
            return None
        if self.show_empty or not self._chart_series or self._vertex_times is None:
            return None
        if not chart.collide_point(*pos):
            return None
        ax = chart.figure.axes[0]
        box = ax.get_window_extent()
        px = pos[0] - chart.x
        py = pos[1] - chart.y
        if not (box.x0 <= px <= box.x1 and box.y0 <= py <= box.y1):
            return None
        time_min = float(ax.transData.inverted().transform_point((px, py))[0])
        return time_min, float(chart.x + px), float(chart.y + box.y0), float(chart.y + box.y1)

    def _on_mouse_pos(self, _window, pos) -> None:
        located = self._locate_on_chart(pos)
        if located is None:
            self.hover_visible = False
            return
        time_min, x, y0, y1 = located
        lines = [second2hour(max(time_min, 0.0) * 60.0)]
        hit = mrr_at_time(self._chart_series, time_min)
        if hit is not None:
            value, series = hit
            text = tr._("%s mm³/min") % _format_number(value)
            lines.append(f"{text} ({series.label})" if series.label else text)
        lines.append(tr._("Click to show in the preview"))
        self.hover_text = "\n".join(lines)
        self.hover_x, self.hover_y0, self.hover_y1 = x, y0, y1
        self.hover_visible = True

    def on_touch_down(self, touch):
        if not getattr(touch, "is_mouse_scrolling", False) and getattr(touch, "button", "left") == "left":
            located = self._locate_on_chart(touch.pos)
            if located is not None and self._jump_to_time(located[0]):
                return True
        return super().on_touch_down(touch)

    def _jump_to_time(self, time_min: float) -> bool:
        """Close the popup and put the preview playhead where the file is at ``time_min``."""
        vertex = vertex_at_time(self._vertex_times, time_min)
        viewer = self._viewer()
        seek = getattr(viewer, "seek_to_vertex", None)
        if vertex is None or seek is None:
            return False
        try:
            if not seek(vertex):
                return False
        except Exception:
            logger.exception("failed to move the playhead")
            return False
        self.dismiss()
        return True

    def _stop_refresh(self) -> None:
        if self._refresh_event is not None:
            self._refresh_event.cancel()
            self._refresh_event = None

    def _summary_key(self):
        viewer = self._viewer()
        key_fn = getattr(viewer, "sim_summary_key", None)
        if key_fn is None:
            return None
        try:
            return key_fn()
        except Exception:
            logger.exception("failed to read the summary key")
            return None

    def _on_refresh_tick(self, _dt) -> None:
        key = self._summary_key()
        if key is not None and key == self._last_key:
            return  # inputs unchanged: skip the MRR copy, the summary and the redraw
        self._last_key = key
        summary = self._read_summary()
        signature = _summary_signature(summary)
        if signature == self._signature:
            return
        self._signature = signature
        self._apply_summary(summary)

    def refresh(self) -> None:
        self._last_key = self._summary_key()
        summary = self._read_summary()
        self._signature = _summary_signature(summary)
        self._apply_summary(summary)

    def _read_summary(self) -> FileSimSummary:
        viewer = self._viewer()
        if viewer is None or not hasattr(viewer, "sim_file_summary"):
            return summarize_file_sim()
        try:
            return viewer.sim_file_summary()
        except Exception:
            logger.exception("failed to summarize the open file")
            return summarize_file_sim()

    def _viewer(self):
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        return getattr(root, "gcode_viewer", None) if root is not None else None

    def _apply_summary(self, summary: FileSimSummary) -> None:
        partial = summary.bake_coverage is not None and summary.bake_coverage < 1.0
        self.show_empty = not summary.has_path
        self.file_caption = tr._("File")
        self.time_caption = tr._("Estimated time")
        self.length_caption = tr._("Path length")
        self.volume_caption = tr._("Removed volume (partial)") if partial else tr._("Removed volume")
        self.peak_caption = tr._("Peak MRR (partial)") if partial else tr._("Peak MRR")
        self.average_caption = tr._("Average cutting MRR (partial)") if partial else tr._("Average cutting MRR")
        self.file_text = summary.filename or "—"
        self.time_text = (
            tr._("Still computing") if summary.estimated_sec is None else second2hour(summary.estimated_sec)
        )
        self.length_text = _measure(summary.path_length_mm, tr._("%s mm"))
        self.volume_text = _measure(summary.removed_volume_mm3, tr._("%s mm³"))
        self.peak_text = _measure(summary.peak_mrr, tr._("%s mm³/min"))
        self.average_text = _measure(summary.average_cutting_mrr, tr._("%s mm³/min"))
        self.coverage_text = _coverage_text(summary)
        self._chart_series = summary.chart_series
        self._vertex_times = summary.vertex_times_min
        self._paint_chart(summary)

    def _apply_chart_theme(self, theme=None) -> None:
        chart = self.ids.get("chart") if getattr(self, "ids", None) else None
        if chart is None or chart.figure is None or not chart.figure.axes:
            return
        if theme is None:
            theme = get_theme()
        fig = chart.figure
        ax = fig.axes[0]
        background = tuple(theme.graph_bg)
        axis = tuple(theme.graph_axis)
        spine = tuple(theme.graph_spine)
        line = tuple(theme.graph_line_1)
        fig.patch.set_facecolor(background)
        ax.set_facecolor(background)
        ax.tick_params(colors=axis, labelsize=self._label_size)
        ax.xaxis.label.set_color(axis)
        ax.yaxis.label.set_color(line)
        ax.xaxis.label.set_fontsize(self._label_size)
        ax.yaxis.label.set_fontsize(self._label_size)
        ax.set_xlabel(tr._("Estimated time (min)"))
        ax.set_ylabel(tr._("MRR (mm³/min)"))
        for name in ("top", "right"):
            ax.spines[name].set_visible(False)
        for name in ("bottom", "left"):
            ax.spines[name].set_color(spine)
            ax.spines[name].set_visible(True)
        has_tools = any(tool is not None for _line, tool in self._plotted)
        for plotted, tool_number in self._plotted:
            plotted.set_color(_series_color(theme, tool_number, has_tools))
        legend = ax.get_legend()
        if legend is not None:
            for text in legend.get_texts():
                text.set_color(axis)
            frame = legend.get_frame()
            frame.set_facecolor(background)
            frame.set_edgecolor(background)
        if chart.figcanvas is not None:
            chart.figcanvas.draw()

    def _paint_chart(self, summary: FileSimSummary) -> None:
        chart = self.ids.get("chart") if getattr(self, "ids", None) else None
        if chart is None or chart.figure is None or not chart.figure.axes:
            return
        ax = chart.figure.axes[0]
        self._clear_plotted(ax)
        theme = get_theme()
        has_tools = any(series.tool_number is not None for series in summary.chart_series)
        labeled = []
        for series in summary.chart_series:
            color = _series_color(theme, series.tool_number, has_tools)
            (line,) = ax.plot(
                series.times_min,
                series.mrr,
                linewidth=1.5,
                color=color,
                label=series.label or "_nolegend_",
            )
            self._plotted.append((line, series.tool_number))
            if series.label:
                labeled.append(line)
        if labeled:
            legend = ax.legend(
                labeled, [line.get_label() for line in labeled], frameon=False, fontsize=self._label_size
            )
            for text in legend.get_texts():
                text.set_color(tuple(theme.graph_axis))
        times = [series.times_min for series in summary.chart_series if series.times_min.size]
        values = [series.mrr for series in summary.chart_series if series.mrr.size]
        finite_time = np.concatenate([item[np.isfinite(item)] for item in times]) if times else np.empty(0)
        finite = np.concatenate([item[np.isfinite(item)] for item in values]) if values else np.empty(0)
        if finite_time.size == 0 or finite.size == 0:
            ax.set_xlim(0.0, 1.0)
            ax.set_ylim(0.0, 1.0)
        else:
            start = float(finite_time.min())
            end = float(finite_time.max())
            if end <= start:
                end = start + 1.0
            pad = (end - start) * 0.02
            ax.set_xlim(start - pad, end + pad)
            ax.set_ylim(0.0, max(float(finite.max()) * 1.08, 1.0))
        chart.xmin, chart.xmax = ax.get_xlim()
        chart.ymin, chart.ymax = ax.get_ylim()
        if chart.figcanvas is not None:
            chart.figcanvas.draw()

    def _clear_plotted(self, ax) -> None:
        for line, _tool in self._plotted:
            line.remove()
        self._plotted = []
        legend = ax.get_legend()
        if legend is not None:
            legend.remove()


def _summary_signature(summary: FileSimSummary):
    return (
        summary.filename,
        summary.has_path,
        summary.estimated_sec,
        summary.path_length_mm,
        summary.removed_volume_mm3,
        summary.peak_mrr,
        summary.average_cutting_mrr,
        summary.bake_coverage,
        tuple((series.label, int(series.mrr.shape[0])) for series in summary.chart_series),
    )


def _series_color(theme, tool_number: int | None, has_tools: bool):
    if tool_number is None:
        return tuple(theme.text_muted) if has_tools else tuple(theme.graph_line_1)
    # Same wrapping palette as the toolpath (viewer_tool_color_1..10).
    index = (int(tool_number) - 1) % 10
    color = getattr(theme, f"viewer_tool_color_{index + 1}")
    return (float(color[0]), float(color[1]), float(color[2]), 1.0)


def _format_number(value: float) -> str:
    number = abs(float(value))
    if number >= 100.0:
        digits = 1
    elif number >= 10.0:
        digits = 2
    else:
        digits = 3
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    if not text:
        text = "0"
    return ("-" if value < 0.0 else "") + text


def _measure(value: float | None, template: str) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return template % _format_number(value)


def _coverage_text(summary: FileSimSummary) -> str:
    if not summary.has_path:
        return ""
    if summary.bake_coverage is None:
        return tr._("Material removal has not been simulated.")
    if summary.bake_coverage >= 1.0:
        return tr._("MRR measured for the whole toolpath")
    percent = int(math.floor(summary.bake_coverage * 100.0 + 1e-9))
    return tr._("MRR measured for %d%% of cutting moves") % percent
