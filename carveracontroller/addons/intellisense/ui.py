"""Floating IntelliSense popups for the G-code list and MDI input."""

from __future__ import annotations

import sys
import weakref
from collections.abc import Iterable

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from carveracontroller.addons.intellisense.engine import (
    MdiAnalysis,
    analyze_mdi_input,
    explain_line,
    explain_signature,
    highlight_mdi_line,
)
from carveracontroller.addons.tooltips.Tooltips import is_blocked_by_modal

_POPUP_MAX_WIDTH = 440
_POPUP_MAX_HEIGHT = 320
_SUGGESTION_ROW_HEIGHT = 28


def machine_settings() -> dict:
    try:
        app = App.get_running_app()
        root = getattr(app, "root", None) if app else None
        if root is None:
            return {}
        settings = dict(getattr(root, "setting_list", {}) or {})
        pending = getattr(root, "setting_change_list", {}) or {}
        settings.update(pending)
        return settings
    except Exception:
        return {}


def highlight_colors() -> dict | None:
    try:
        app = App.get_running_app()
        root = getattr(app, "root", None) if app else None
        if root is None:
            return None
        return getattr(root, "gcode_highlight_colors", None)
    except Exception:
        return None


class IntellisensePopupBase(BoxLayout):
    showing = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opacity = 0
        self.disabled = True

    def display(self):
        if is_blocked_by_modal():
            self.hide()
            return
        if self.parent is None:
            Window.add_widget(self)
        self.opacity = 1
        self.disabled = False
        self.showing = True

    def hide(self):
        if self.parent is not None:
            self.parent.remove_widget(self)
        self.opacity = 0
        self.disabled = True
        self.showing = False


class IntellisensePopup(IntellisensePopupBase):
    markup_text = StringProperty("")

    def set_content(self, text: str):
        self.markup_text = text
        label = self.ids.get("body")
        if label is None:
            return
        label.text = text
        label.text_size = (dp(_POPUP_MAX_WIDTH) - dp(28), None)
        label.texture_update()
        self._fit_to_content()

    def _fit_to_content(self):
        label = self.ids.get("body")
        if label is None:
            return
        width = min(max(label.texture_size[0] + dp(24), dp(180)), dp(_POPUP_MAX_WIDTH))
        height = min(label.texture_size[1] + dp(24), dp(_POPUP_MAX_HEIGHT))
        self.size = (width, height)

    def hide(self):
        super().hide()
        self.markup_text = ""


class MDISuggestionRow(BoxLayout):
    command_name = StringProperty("")
    summary = StringProperty("")
    highlighted_name = StringProperty("")
    selected = BooleanProperty(False)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            apply_mdi_suggestion(self.command_name)
            return True
        return super().on_touch_down(touch)


class MDICompletionPopup(IntellisensePopupBase):
    selected_index = NumericProperty(0)
    suggestion_count = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opacity = 0
        self.disabled = True
        self._analysis: MdiAnalysis | None = None
        self._suggestions = []

    def set_analysis(self, analysis: MdiAnalysis, colors: dict | None, settings: dict):
        self._analysis = analysis
        self._suggestions = list(analysis.suggestions) if analysis.mode == "suggest" else []
        self.suggestion_count = len(self._suggestions)
        body = self.ids.body
        help_label = self.ids.help_label
        body.clear_widgets()

        if analysis.mode == "suggest":
            self.selected_index = min(self.selected_index, max(len(self._suggestions) - 1, 0))
            help_label.opacity = 0
            help_label.size_hint_y = None
            help_label.height = 0
            help_label.text = ""
            body.size_hint_y = 1
            for index, command in enumerate(self._suggestions):
                body.add_widget(
                    MDISuggestionRow(
                        command_name=command.name,
                        summary=command.description,
                        highlighted_name=highlight_mdi_line(command.name, colors),
                        selected=index == self.selected_index,
                    )
                )
            self.height = dp(12) + len(self._suggestions) * dp(_SUGGESTION_ROW_HEIGHT)
            return

        body.size_hint_y = None
        body.height = 0
        help_label.opacity = 1
        help_label.size_hint_y = 1
        command = analysis.parsed.commands[0].command if analysis.parsed and analysis.parsed.commands else None
        text = ""
        if command is not None:
            text = explain_signature(command, parsed=analysis.parsed, settings=settings, colors=colors)
        help_label.text = text
        help_label.text_size = (self.width - dp(24) if self.width else dp(_POPUP_MAX_WIDTH) - dp(28), None)
        help_label.texture_update()
        self.height = min(help_label.texture_size[1] + dp(24), dp(_POPUP_MAX_HEIGHT))

    def move_selection(self, delta: int) -> bool:
        if not self._suggestions:
            return False
        self.selected_index = (self.selected_index + delta) % len(self._suggestions)
        rows = [child for child in reversed(self.ids.body.children) if isinstance(child, MDISuggestionRow)]
        for index, child in enumerate(rows):
            child.selected = index == self.selected_index
        return True

    def current_command_name(self) -> str | None:
        if not self._suggestions:
            return None
        if 0 <= self.selected_index < len(self._suggestions):
            return self._suggestions[self.selected_index].name
        return self._suggestions[0].name

    def hide(self):
        super().hide()
        self._analysis = None
        self._suggestions = []
        self.selected_index = 0


class _IntellisenseHost:
    def __init__(self):
        self.gcode_popup = IntellisensePopup()
        self.mdi_popup = MDICompletionPopup()
        self._gcode_anchor: Widget | None = None
        self._gcode_reason = ""
        self._mdi_input = None
        self._window_bound = False
        self._hover_rows = weakref.WeakSet()
        self._hover_bound = False
        self._overlay_bound = False

    def _ensure_window_bind(self):
        if self._window_bound:
            return
        Window.bind(on_touch_down=self._on_window_touch, on_key_down=self._on_window_key)
        self._window_bound = True
        self._ensure_overlay_bind()

    def _ensure_overlay_bind(self):
        if self._overlay_bound:
            return
        Window.bind(children=self._on_window_children)
        self._overlay_bound = True

    def _on_window_children(self, _window, _children):
        if is_blocked_by_modal():
            self._dismiss_for_overlay()

    def _dismiss_for_overlay(self):
        for row in tuple(self._hover_rows):
            cancel_gcode_hover(row, hide=False)
        self.hide_gcode()
        self.hide_mdi()

    def _release_window_bind_if_idle(self):
        if not self._window_bound or self.gcode_popup.showing or self.mdi_popup.showing:
            return
        Window.unbind(on_touch_down=self._on_window_touch, on_key_down=self._on_window_key)
        self._window_bound = False

    def register_hover_row(self, row: Widget):
        self._hover_rows.add(row)
        if not self._hover_bound:
            Window.bind(mouse_pos=self._on_window_mouse_pos)
            self._hover_bound = True
        self._ensure_overlay_bind()

    def _on_window_mouse_pos(self, _window, pos):
        if is_blocked_by_modal():
            self._dismiss_for_overlay()
            return
        for row in tuple(self._hover_rows):
            if row.get_root_window() and _row_explainable(row) and row.collide_point(*row.to_widget(*pos)):
                schedule_gcode_hover(row)
            else:
                cancel_gcode_hover(row)

    def show_gcode(self, row: Widget, reason: str = "select"):
        if is_blocked_by_modal(row):
            self._dismiss_for_overlay()
            return
        if not _row_explainable(row):
            if reason == "select":
                self.hide_gcode(row)
            return
        text = _row_plain_text(row)
        explanation = explain_line(
            text,
            settings=machine_settings(),
            colors=highlight_colors(),
            preceding_lines=_preceding_lines(row),
        )
        if not explanation:
            if reason == "select":
                self.hide_gcode(row)
            return
        if reason == "hover" and self._gcode_anchor is row and self.gcode_popup.showing:
            return
        self._ensure_window_bind()
        self._gcode_anchor = row
        self._gcode_reason = reason
        self.gcode_popup.set_content(explanation)
        self._place_near(self.gcode_popup, row, prefer="right")
        self.gcode_popup.display()

    def hide_gcode(self, row: Widget | None = None):
        if row is not None and self._gcode_anchor is not row:
            return
        self.gcode_popup.hide()
        self._gcode_anchor = None
        self._gcode_reason = ""
        self._release_window_bind_if_idle()

    def update_mdi(self, textinput):
        if is_blocked_by_modal(textinput):
            self.hide_mdi()
            return
        if not getattr(textinput, "focus", False):
            self.hide_mdi()
            return
        analysis = analyze_mdi_input(_mdi_line_at_cursor(textinput))
        if analysis.mode == "empty":
            self.hide_mdi()
            return
        self._ensure_window_bind()
        self._mdi_input = textinput
        width = max(getattr(textinput, "width", 0) or 0, dp(280))
        self.mdi_popup.width = min(width, dp(_POPUP_MAX_WIDTH) + dp(80))
        self.mdi_popup.set_analysis(analysis, highlight_colors(), machine_settings())
        self._place_near(self.mdi_popup, textinput, prefer="above")
        self.mdi_popup.display()

    def hide_mdi(self):
        self.mdi_popup.hide()
        self._mdi_input = None
        self._release_window_bind_if_idle()

    def apply_current_suggestion(self) -> bool:
        name = self.mdi_popup.current_command_name()
        if not name or self._mdi_input is None:
            return False
        apply_mdi_suggestion(name, self._mdi_input)
        return True

    def move_mdi_selection(self, delta: int) -> bool:
        if not self.mdi_popup.showing or self.mdi_popup.suggestion_count == 0:
            return False
        return self.mdi_popup.move_selection(delta)

    def _place_near(self, popup: Widget, anchor: Widget, prefer: str):
        if not anchor.get_root_window():
            return
        ax, ay = anchor.to_window(anchor.x, anchor.y)
        width, height = popup.size
        window_w, window_h = Window.size
        if prefer == "right":
            x = ax + anchor.width + dp(8)
            y = ay + anchor.height - height
            if x + width > window_w - dp(8):
                x = max(dp(8), ax - width - dp(8))
        else:
            x = ax
            y = ay + anchor.height + dp(6)
            if y + height > window_h - dp(8):
                y = ay - height - dp(6)
        x = min(max(x, dp(8)), max(window_w - width - dp(8), dp(8)))
        y = min(max(y, dp(8)), max(window_h - height - dp(8), dp(8)))
        popup.pos = (x, y)

    def _on_window_touch(self, _window, touch):
        if self.gcode_popup.showing:
            if self.gcode_popup.collide_point(*touch.pos):
                return False
            if self._gcode_anchor and _anchor_contains(self._gcode_anchor, touch.pos):
                return False
            self.hide_gcode()
        if self.mdi_popup.showing:
            if self.mdi_popup.collide_point(*touch.pos):
                return False
            if self._mdi_input and _anchor_contains(self._mdi_input, touch.pos):
                return False
            self.hide_mdi()
        return False

    def _on_window_key(self, _window, key, *_args):
        if key == 27:
            if self.mdi_popup.showing:
                self.hide_mdi()
                return True
            if self.gcode_popup.showing:
                self.hide_gcode()
                return True
        return False


_host: _IntellisenseHost | None = None


def get_host() -> _IntellisenseHost:
    global _host
    if _host is None:
        _host = _IntellisenseHost()
    return _host


class IntellisenseExplainRowMixin:
    """Hover and selection command-explanation popup for recycle-view rows."""

    def bind_intellisense_hover(self):
        if getattr(self, "_intel_hover_bound", False) or sys.platform == "ios":
            return
        get_host().register_hover_row(self)
        self._intel_hover_bound = True

    def intellisense_on_recycle(self):
        cancel_gcode_hover(self)
        _cancel_selection_show(self)
        hide_gcode_explain(self)
        self._intel_user_selected = False

    def intellisense_on_selection(self, is_selected: bool):
        _cancel_selection_show(self)
        if not is_selected or not _row_explainable(self):
            self._intel_user_selected = False
            hide_gcode_explain(self)
            return
        self._intel_user_selected = True

        def _show(_dt):
            self._intel_selection_show = None
            if self._intel_user_selected and self.get_root_window() and _row_explainable(self):
                show_gcode_explain(self, reason="select")

        self._intel_selection_show = _show
        Clock.schedule_once(_show, 0)


def show_gcode_explain(row: Widget, reason: str = "select"):
    get_host().show_gcode(row, reason)


def hide_gcode_explain(row: Widget | None = None):
    get_host().hide_gcode(row)


def update_mdi_intellisense(textinput):
    get_host().update_mdi(textinput)


def hide_mdi_intellisense():
    get_host().hide_mdi()


def handle_mdi_intellisense_key(textinput, key, modifiers) -> bool:
    host = get_host()
    if not host.mdi_popup.showing:
        return False
    if key == 27:
        host.hide_mdi()
        return True
    if key == 9:
        return host.apply_current_suggestion()
    if key == 273 and "ctrl" not in modifiers:
        if host.mdi_popup.suggestion_count:
            return host.move_mdi_selection(-1)
        return False
    if key == 274 and "ctrl" not in modifiers:
        if host.mdi_popup.suggestion_count:
            return host.move_mdi_selection(1)
        return False
    return False


def apply_mdi_suggestion(command_name: str, textinput=None):
    if textinput is None:
        textinput = get_host()._mdi_input
    if textinput is None:
        return
    lines = textinput.text.split("\n")
    row = textinput.cursor[1] if textinput.cursor else len(lines) - 1
    if row < 0 or row >= len(lines):
        row = max(len(lines) - 1, 0)
    line = lines[row]
    lead_len = len(line) - len(line.lstrip())
    stripped = line.lstrip()
    token = stripped.split(None, 1)[0] if stripped else ""
    after = stripped[len(token) :] if token else stripped
    if after and not after.startswith(" "):
        after = " " + after
    if not after:
        after = " "
    lines[row] = line[:lead_len] + command_name + after
    textinput.text = "\n".join(lines)
    cursor_col = lead_len + len(command_name) + (1 if after.startswith(" ") else 0)
    textinput.cursor = (cursor_col, row)
    Clock.schedule_once(lambda _dt: update_mdi_intellisense(textinput), 0)


def _mdi_line_at_cursor(textinput) -> str:
    text = getattr(textinput, "text", "") or ""
    if not text:
        return ""
    lines = text.split("\n")
    cursor = getattr(textinput, "cursor", None)
    row = cursor[1] if cursor else len(lines) - 1
    if row < 0 or row >= len(lines):
        return lines[-1]
    return lines[row]


def _row_plain_text(row: Widget) -> str:
    return (getattr(row, "plain_text", None) or getattr(row, "text", "") or "").strip()


def _preceding_lines(row: Widget) -> Iterable[str]:
    line_no = getattr(row, "line_no", None)
    if line_no:
        try:
            app = App.get_running_app()
            root = getattr(app, "root", None) if app else None
            lines = getattr(root, "lines", None) or []
            end = max(int(line_no) - 1, 0)
            return (str(lines[index]).rstrip("\r\n") for index in range(end - 1, -1, -1))
        except (TypeError, ValueError):
            return ()
    index = getattr(row, "index", None)
    rv = _recycle_view_of(row)
    if index is None or rv is None:
        return ()
    return (
        str(rv.data[position].get("text") or "")
        for position in range(int(index) - 1, -1, -1)
        if rv.data[position].get("highlight")
    )


def _recycle_view_of(row: Widget):
    widget = getattr(row, "parent", None)
    while widget is not None:
        if hasattr(widget, "data") and hasattr(widget, "view_adapter"):
            return widget
        widget = getattr(widget, "parent", None)
    return None


def _row_explainable(row: Widget) -> bool:
    """G-code file rows always explain. MDI history only explains sent commands."""
    if not _row_plain_text(row):
        return False
    if not hasattr(row, "highlight"):
        return True
    return bool(row.highlight)


def _anchor_contains(anchor: Widget, window_pos) -> bool:
    if not anchor.get_root_window():
        return False
    return anchor.collide_point(*anchor.to_widget(*window_pos))


def schedule_gcode_hover(row: Widget):
    if sys.platform == "ios":
        return
    cancel_gcode_hover(row, hide=False)
    delay = 0.5
    app = App.get_running_app()
    if app is not None:
        delay = float(getattr(app, "tooltip_delay", 0.5) or 0.5)

    def _show(_dt):
        if is_blocked_by_modal(row):
            hide_gcode_explain(row)
            return
        if row.get_root_window() and _row_explainable(row):
            show_gcode_explain(row, reason="hover")

    row._intel_hover_show = _show
    Clock.schedule_once(_show, delay)


def _cancel_selection_show(row: Widget):
    callback = getattr(row, "_intel_selection_show", None)
    if callback is not None:
        Clock.unschedule(callback)
        row._intel_selection_show = None


def cancel_gcode_hover(row: Widget, hide: bool = True):
    callback = getattr(row, "_intel_hover_show", None)
    if callback is not None:
        Clock.unschedule(callback)
        row._intel_hover_show = None
    if hide:
        host = get_host()
        if host._gcode_reason == "hover" and host._gcode_anchor is row:
            hide_gcode_explain(row)
