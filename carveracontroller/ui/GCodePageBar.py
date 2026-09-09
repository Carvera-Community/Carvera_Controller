"""Compact G-code file pager for the File workspace command pane."""

from __future__ import annotations

import sys
from typing import NamedTuple

from kivy.app import App
from kivy.clock import mainthread
from kivy.factory import Factory
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton

DEFAULT_PAGE_SIZE = 10000


class GCodePageBarState(NamedTuple):
    visible: bool
    page_label: str
    range_label: str
    start: int
    end: int


def gcode_page_bar_state(curr_page, total_pages, line_count, page_size) -> GCodePageBarState:
    """Return pager labels and visibility for a G-code file page."""
    curr = max(1, int(curr_page or 1))
    total = max(1, int(total_pages or 1))
    size = max(1, int(page_size or 1))
    count = max(0, int(line_count or 0))
    start = (curr - 1) * size + 1
    end = min(curr * size, count) if count else 0
    range_label = f"{start}–{end}" if count and end >= start else ""
    return GCodePageBarState(
        visible=int(total_pages or 0) > 1,
        page_label=f"{curr} / {total}",
        range_label=range_label,
        start=start,
        end=end,
    )


def _max_load_lines() -> int:
    main_mod = sys.modules.get("carveracontroller.main")
    if main_mod is None:
        return DEFAULT_PAGE_SIZE
    try:
        return max(1, int(getattr(main_mod, "MAX_LOAD_LINES", DEFAULT_PAGE_SIZE) or DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE


class GCodePageBarButton(BoxLayout, ToolTipButton):
    icon = StringProperty("")
    icon_size = NumericProperty(18)


class GCodePageBar(BoxLayout):
    page_label = StringProperty("1 / 1")
    range_label = StringProperty("")
    bar_visible = BooleanProperty(False)
    backward_disabled = BooleanProperty(True)
    forward_disabled = BooleanProperty(True)

    def on_kv_post(self, base_widget):
        self._bind_app()

    def _bind_app(self):
        app = App.get_running_app()
        if app is None:
            return
        app.bind(
            curr_page=self._refresh_labels,
            total_pages=self._refresh_labels,
            loading_page=self._refresh_labels,
            state=self._refresh_labels,
        )
        root = getattr(app, "root", None)
        if root is not None:
            root.bind(selected_file_line_count=self._refresh_labels)
        self._refresh_labels()

    @mainthread
    def _refresh_labels(self, *_args):
        app = App.get_running_app()
        if app is None:
            return
        root = getattr(app, "root", None)
        line_count = int(getattr(root, "selected_file_line_count", 0) or 0) if root is not None else 0
        state = gcode_page_bar_state(app.curr_page, app.total_pages, line_count, _max_load_lines())
        machine_busy = app.state not in ("Idle", "N/A")
        self.page_label = state.page_label
        self.range_label = state.range_label
        self.bar_visible = state.visible
        self.backward_disabled = bool(app.loading_page or app.curr_page == 1 or machine_busy)
        self.forward_disabled = bool(app.loading_page or app.curr_page == app.total_pages or machine_busy)

    def go_first_page(self):
        self._call_controller("first_page")

    def go_previous_page(self):
        self._call_controller("previous_page")

    def go_next_page(self):
        self._call_controller("next_page")

    def go_last_page(self):
        self._call_controller("last_page")

    def _call_controller(self, name):
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        method = getattr(root, name, None) if root is not None else None
        if callable(method):
            method()


if "GCodePageBar" not in Factory.classes:
    Factory.register("GCodePageBar", cls=GCodePageBar)
if "GCodePageBarButton" not in Factory.classes:
    Factory.register("GCodePageBarButton", cls=GCodePageBarButton)
