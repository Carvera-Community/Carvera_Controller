"""Floating color-scheme picker and path-visibility legend for the G-code viewer."""

from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, ObjectProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.dropdown import DropDown
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from carveracontroller.addons.tool_visualization.icon_builder import build_tool_legend_icon, build_tool_tooltip_icon
from carveracontroller.addons.tool_visualization.tooltip_builder import format_tool_tooltip, format_tool_type_label
from carveracontroller.addons.tooltips.Tooltips import ToolTipButton, is_blocked_by_modal
from carveracontroller.CNC import LASER_TOOL_NUMBER, PROBE_3D_TOOL_NUMBER, ZPROBE_TOOL_NUMBER
from carveracontroller.GcodeViewer import (
    COLOR_SCHEME_BY_SPEED,
    COLOR_SCHEME_BY_TOOL,
    COLOR_SCHEME_BY_TYPE,
    COLOR_SCHEME_BY_Z,
    VISIBILITY_BUCKET_COUNT,
    VISIBILITY_MAX_TOOLS,
    speed_colormap_rgb,
    tool_palette_rgb,
)
from carveracontroller.translation import tr
from carveracontroller.Utils import second2hour

LEGEND_PANEL_MAX_HEIGHT = dp(280)
HEADER_HEIGHT = dp(36)
PANEL_BOTTOM_PADDING = dp(6)
LEGEND_ROW_HEIGHT = dp(24)
LEGEND_TOOL_ROW_HEIGHT = dp(42)
LEGEND_TOOL_ICON_SIZE = dp(34)
LEGEND_ROW_SPACING = dp(2)
LEGEND_GRID_PAD_Y = dp(4) + dp(2)
DURATION_LABEL_WIDTH = dp(52)

LABEL_VISIBLE = (250 / 255, 250 / 255, 250 / 255, 1.0)
LABEL_HIDDEN = (110 / 255, 110 / 255, 110 / 255, 1.0)
TIME_UNAVAILABLE_TEXT = tr._("n/a")
SWATCH_HIDDEN_ALPHA = 0.35
EYE_VISIBLE_COLOR = (250 / 255, 250 / 255, 250 / 255, 1.0)
EYE_HIDDEN_COLOR = (60 / 255, 60 / 255, 60 / 255, 1.0)
EYE_ICON_SIZE = dp(14)
EYE_ICON_SOURCE = "data/eye.png"

# Static legend icons for special tools that are not in the tool table.
SPECIAL_TOOL_LEGEND_ICONS = {
    LASER_TOOL_NUMBER: "data/laser.png",
    PROBE_3D_TOOL_NUMBER: "data/probe.png",
    ZPROBE_TOOL_NUMBER: "data/probe.png",
}


def _tool_legend_label(tool):
    tool_num = int(tool)
    if tool_num == LASER_TOOL_NUMBER:
        return tr._("Laser")
    if tool_num == ZPROBE_TOOL_NUMBER:
        return tr._("Probe")
    if tool_num == PROBE_3D_TOOL_NUMBER:
        return tr._("3D Probe")
    return f"T{tool_num}"


def _tool_static_icon_source(tool):
    """Return a static icon path for a special tool, or None."""
    try:
        return SPECIAL_TOOL_LEGEND_ICONS.get(int(tool))
    except (TypeError, ValueError):
        return None


def _entry_has_legend_icon(entry):
    """True when this legend entry can show a tool silhouette / static icon."""
    if entry.get("tool_def") is not None:
        return True
    if entry.get("kind") == "tool":
        return _tool_static_icon_source(entry.get("tool", entry.get("key"))) is not None
    return False


def _mix_towards_grey(rgba, amount=0.55):
    """Grey an active color so hidden+active stays distinct from plain hidden."""
    grey = LABEL_HIDDEN
    return tuple(c * (1.0 - amount) + grey[i] * amount for i, c in enumerate(rgba[:3])) + (
        rgba[3] if len(rgba) > 3 else 1.0,
    )


def legend_label_color(visible, is_active=False, active_color=None):
    """White / active_color, or greyed variants when paths are hidden."""
    if is_active and active_color is not None:
        base = tuple(float(c) for c in active_color[:4])
        if len(base) < 4:
            base = (*base[:3], 1.0)
        return base if visible else _mix_towards_grey(base)
    return LABEL_VISIBLE if visible else LABEL_HIDDEN


def build_legend_entries(color_scheme, gcode_viewer, used_tools):
    """Return legend entries for the active scheme.

    Each entry is a dict with:
      label, color, key, kind
    and optionally tool, tool_def for tool rows.
    """
    entries = []
    if color_scheme == COLOR_SCHEME_BY_TYPE:
        entries.append(
            {
                "label": tr._("Rapid (G0)"),
                "color": (1.0, 0.0, 0.0, 1.0),
                "kind": "rapid",
                "key": "rapid",
            }
        )
        entries.append(
            {
                "label": tr._("Feed (G1)"),
                "color": (0.0, 1.0, 0.0, 1.0),
                "kind": "feed",
                "key": "feed",
            }
        )
        return entries

    if color_scheme == COLOR_SCHEME_BY_TOOL:
        # Keep in sync with the shader tool filter (VISIBILITY_MAX_TOOLS).
        tools = sorted({int(t) for t in (used_tools or []) if int(t) >= 0})[:VISIBILITY_MAX_TOOLS]
        for tool in tools:
            label = _tool_legend_label(tool)
            rgb = tool_palette_rgb(tool)
            entries.append(
                {
                    "label": label,
                    "color": (*rgb, 1.0),
                    "kind": "tool",
                    "key": int(tool),
                    "tool": int(tool),
                }
            )
        return entries

    if color_scheme == COLOR_SCHEME_BY_SPEED:
        feed_min = float(getattr(gcode_viewer, "feed_min", 0.0) or 0.0)
        feed_max = float(getattr(gcode_viewer, "feed_max", 0.0) or 0.0)
        if feed_max <= feed_min:
            feed_max = feed_min + 1.0

        for step in range(0, VISIBILITY_BUCKET_COUNT):
            t = step / 10.0
            feed = feed_min + t * (feed_max - feed_min)
            rgb = speed_colormap_rgb(t)
            entries.append(
                {
                    "label": f"{feed:.0f} mm/min",
                    "color": (*rgb, 1.0),
                    "kind": "speed_bucket",
                    "key": step,
                }
            )
        entries.append(
            {
                "label": tr._("Rapid (G0)"),
                "color": (1.0, 0.0, 0.0, 1.0),
                "kind": "rapid",
                "key": "rapid",
            }
        )
        return entries

    if color_scheme == COLOR_SCHEME_BY_Z:
        z_min = float(getattr(gcode_viewer, "z_min_mm", 0.0) or 0.0)
        z_max = float(getattr(gcode_viewer, "z_max_mm", 0.0) or 0.0)
        if z_max <= z_min:
            z_max = z_min + 1.0

        # Top = higher Z (shallower); bottom = lower Z (deeper).
        for step in range(0, VISIBILITY_BUCKET_COUNT):
            t = 1.0 - step / 10.0
            z_val = z_min + t * (z_max - z_min)
            rgb = speed_colormap_rgb(t)
            z_str = f"{z_val:.3f}"
            if step == 0:
                label = tr._("≥ Z {} mm").format(z_str)
            elif step == 10:
                label = tr._("≤ Z {} mm").format(z_str)
            else:
                label = f"Z {z_str} mm"
            entries.append(
                {
                    "label": label,
                    "color": (*rgb, 1.0),
                    "kind": "z_bucket",
                    "key": step,
                }
            )
        return entries

    raise ValueError(f"Invalid color scheme: {color_scheme}")


class _ColorSwatch(Widget):
    color = ListProperty([1.0, 1.0, 1.0, 1.0])

    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(14), dp(14)), **kwargs)
        with self.canvas:
            self._color = Color(1, 1, 1, 1)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_rect, size=self._sync_rect, color=self._sync_color)
        self._sync_color()

    def _sync_rect(self, *_args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _sync_color(self, *_args):
        c = self.color
        a = c[3] if len(c) > 3 else 1.0
        self._color.rgba = (float(c[0]), float(c[1]), float(c[2]), float(a))


def _legend_content_height(row_heights):
    """Total legend content height for a sequence of row heights."""
    if not row_heights:
        return 0
    return sum(row_heights) + max(0, len(row_heights) - 1) * LEGEND_ROW_SPACING + LEGEND_GRID_PAD_Y


def _format_legend_duration(duration_sec):
    """Return display text for a legend duration; None means time unavailable."""
    if duration_sec is None:
        return None
    return second2hour(max(0, int(round(float(duration_sec)))))


def _tool_legend_title(entry_label, tool_def):
    """Primary legend line: tool number plus type when known."""
    type_label = format_tool_type_label(tool_def) if tool_def is not None else ""
    if type_label:
        return f"{entry_label} · {type_label}"
    return entry_label


def _tool_legend_name(tool_def):
    """Secondary legend line: tool name/description when present."""
    if tool_def is None:
        return ""
    return (tool_def.description or "").strip()


class _RowHoverToolTip(ToolTipButton):
    """Zero-size tooltip host that hit-tests its parent legend row."""

    def __init__(self, **kwargs):
        kwargs.setdefault("text", "")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (0, 0))
        kwargs.setdefault("opacity", 0)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("border", (0, 0, 0, 0))
        kwargs.setdefault("color", (0, 0, 0, 0))
        kwargs.setdefault("tooltip_markup", True)
        kwargs.setdefault("tooltip_horizontal", True)
        kwargs.setdefault("tooltip_delay", 0.25)
        super().__init__(**kwargs)
        app = App.get_running_app()
        if app is not None and hasattr(app, "show_tooltips"):
            self.show_tooltips = app.show_tooltips
            app.bind(show_tooltips=self.setter("show_tooltips"))

    def on_parent(self, instance, parent):
        # Detached hosts must stop listening; otherwise a pending hover from a
        # previous legend (e.g. under an open Spinner dropdown) can still fire.
        if parent is None:
            Clock.unschedule(self.display_tooltip)
            self.close_tooltip()
            try:
                Window.unbind(mouse_pos=self.on_mouse_pos)
            except Exception:
                pass

    def collide_point(self, x, y):
        parent = self.parent
        if parent is None:
            return False
        return parent.collide_point(x, y)

    def to_widget(self, x, y, relative=False):
        parent = self.parent
        if parent is None:
            return super().to_widget(x, y, relative)
        return parent.to_widget(x, y, relative)

    def _is_blocked_by_overlay(self):
        """True when a Spinner dropdown (or modal) is open over the legend."""
        if is_blocked_by_modal(self):
            return True
        # Spinner menus attach a DropDown to Window; suppress while any is open
        # so the row under the menu does not keep a pending hover tooltip.
        return any(isinstance(child, DropDown) for child in Window.children)

    def on_mouse_pos(self, *args):
        if self.parent is None or self._is_blocked_by_overlay():
            Clock.unschedule(self.display_tooltip)
            self.close_tooltip()
            return
        super().on_mouse_pos(*args)

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False


class LegendRow(BoxLayout):
    """Clickable legend row that toggles path visibility for one category."""

    visible = BooleanProperty(True)
    is_active_tool = BooleanProperty(False)
    entry_kind = StringProperty("")
    entry_key = ObjectProperty(None, allownone=True)

    def __init__(
        self,
        entry,
        visible,
        is_active_tool,
        active_color,
        on_toggle,
        document_unit="mm",
        show_icon_column=False,
        **kwargs,
    ):
        tool_def = entry.get("tool_def")
        tool_name = _tool_legend_name(tool_def)
        static_icon = None
        if entry.get("kind") == "tool":
            static_icon = _tool_static_icon_source(entry.get("tool", entry.get("key")))
        # Keep mixed tool rows aligned: reserve icon/taller height whenever any
        # tool in the list can show an icon (defs and/or static icons like laser).
        use_tool_row = show_icon_column or tool_def is not None or static_icon is not None
        row_height = LEGEND_TOOL_ROW_HEIGHT if use_tool_row else LEGEND_ROW_HEIGHT

        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=row_height,
            spacing=dp(6),
            **kwargs,
        )
        self.entry_kind = entry["kind"]
        self.entry_key = entry["key"]
        self._on_toggle = on_toggle
        self._base_swatch = list(entry["color"])
        self.visible = visible
        self.is_active_tool = is_active_tool
        self._active_color = active_color
        self._duration_sec = entry.get("duration_sec")
        self._duration_available = self._duration_sec is not None
        self._name_label = None
        self._press_pos = None

        swatch_holder = AnchorLayout(
            size_hint=(None, None),
            size=(dp(14), row_height),
            anchor_x="left",
            anchor_y="center",
        )
        self._swatch = _ColorSwatch(color=list(entry["color"]))
        swatch_holder.add_widget(self._swatch)
        self.add_widget(swatch_holder)

        self._icon = None
        if show_icon_column or tool_def is not None or static_icon is not None:
            icon_holder = AnchorLayout(
                size_hint=(None, None),
                size=(LEGEND_TOOL_ICON_SIZE, row_height),
                anchor_x="center",
                anchor_y="center",
            )
            if tool_def is not None:
                try:
                    icon_size = (LEGEND_TOOL_ICON_SIZE, LEGEND_TOOL_ICON_SIZE)
                    texture, display_size = build_tool_legend_icon(tool_def, size=icon_size)
                    self._icon = Image(
                        texture=texture,
                        size_hint=(None, None),
                        size=display_size,
                        allow_stretch=True,
                        keep_ratio=True,
                    )
                    icon_holder.add_widget(self._icon)
                except Exception:
                    self._icon = None
            elif static_icon is not None:
                self._icon = Image(
                    source=static_icon,
                    size_hint=(None, None),
                    size=(LEGEND_TOOL_ICON_SIZE, LEGEND_TOOL_ICON_SIZE),
                    allow_stretch=True,
                    keep_ratio=True,
                )
                icon_holder.add_widget(self._icon)
            # else: empty spacer so labels stay aligned with icon-bearing rows
            self.add_widget(icon_holder)

        label_box = BoxLayout(
            orientation="vertical",
            size_hint_x=1,
            size_hint_y=None,
            height=row_height,
            spacing=0,
            padding=(0, dp(2) if tool_name else 0),
        )
        self._label = Label(
            text=_tool_legend_title(entry["label"], tool_def),
            halign="left",
            valign="middle",
            font_size="12sp",
            size_hint_y=1,
            shorten=True,
            shorten_from="right",
        )
        self._label.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        label_box.add_widget(self._label)

        if tool_name:
            self._name_label = Label(
                text=tool_name,
                halign="left",
                valign="middle",
                font_size="10sp",
                size_hint_y=1,
                shorten=True,
                shorten_from="right",
                color=LABEL_HIDDEN,
            )
            self._name_label.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            label_box.add_widget(self._name_label)

        self.add_widget(label_box)

        duration_text = _format_legend_duration(self._duration_sec)
        self._duration = Label(
            text=TIME_UNAVAILABLE_TEXT if duration_text is None else duration_text,
            halign="right",
            valign="middle",
            font_size="11sp",
            size_hint=(None, None),
            size=(DURATION_LABEL_WIDTH, row_height),
            color=LABEL_HIDDEN,
        )
        self._duration.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        self.add_widget(self._duration)

        eye_holder = AnchorLayout(
            size_hint=(None, None),
            size=(EYE_ICON_SIZE, row_height),
            anchor_x="center",
            anchor_y="center",
        )
        self._eye = Image(
            source=EYE_ICON_SOURCE,
            size_hint=(None, None),
            size=(EYE_ICON_SIZE, EYE_ICON_SIZE),
            allow_stretch=True,
            keep_ratio=True,
            color=EYE_VISIBLE_COLOR,
        )
        eye_holder.add_widget(self._eye)
        self.add_widget(eye_holder)

        # Always append a same-sized trailing slot (real tooltip host or a
        # zero-size spacer) so every row has the same number of BoxLayout
        # children/gaps.
        if tool_def is not None:
            self.add_widget(
                _RowHoverToolTip(
                    tooltip_txt=format_tool_tooltip(tool_def, unit=document_unit),
                    tooltip_texture_provider=partial(build_tool_tooltip_icon, tool_def),
                )
            )
        else:
            self.add_widget(Widget(size_hint=(None, None), size=(0, 0)))

        self._sync_appearance()
        self.bind(visible=self._sync_appearance, is_active_tool=self._sync_appearance)

    def on_touch_down(self, touch):
        # Mouse wheel must not count as a click (visibility flicker while scrolling).
        if getattr(touch, "is_mouse_scrolling", False):
            return super().on_touch_down(touch)
        if self.collide_point(*touch.pos):
            self._press_pos = (touch.x, touch.y)
            touch.ud["legend_row"] = self
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if getattr(touch, "is_mouse_scrolling", False):
            self._press_pos = None
            return super().on_touch_up(touch)
        if touch.ud.get("legend_row") is self and self.collide_point(*touch.pos):
            press = self._press_pos
            self._press_pos = None
            if press is not None and abs(touch.x - press[0]) < dp(8) and abs(touch.y - press[1]) < dp(8):
                if callable(self._on_toggle):
                    self._on_toggle(self.entry_kind, self.entry_key)
                return True
        self._press_pos = None
        return super().on_touch_up(touch)

    def set_active_color(self, active_color):
        self._active_color = active_color
        self._sync_appearance()

    def _sync_appearance(self, *_args):
        color = legend_label_color(self.visible, self.is_active_tool, self._active_color)
        self._label.color = color
        if self._name_label is not None:
            # Name stays slightly quieter than the title, but still greys when hidden.
            if self.visible:
                if self.is_active_tool and self._active_color is not None:
                    self._name_label.color = _mix_towards_grey(color, amount=0.35)
                else:
                    self._name_label.color = LABEL_HIDDEN
            else:
                self._name_label.color = LABEL_HIDDEN
        # Unavailable times stay grey; available times follow row visibility coloring.
        self._duration.color = LABEL_HIDDEN if not self._duration_available else color
        swatch = list(self._base_swatch)
        if not self.visible:
            swatch[3] = SWATCH_HIDDEN_ALPHA
        self._swatch.color = swatch
        if self._icon is not None:
            if self.visible:
                self._icon.color = (1, 1, 1, 1)
            else:
                self._icon.color = (0.55, 0.55, 0.55, 1)
        self._eye.color = EYE_VISIBLE_COLOR if self.visible else EYE_HIDDEN_COLOR


class GcodeColorSchemePanel(BoxLayout):
    """Dropdown plus scrollable, toggleable legend for toolpath colors / visibility."""

    any_visible = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._makera_root = None
        self._entry_count = 0
        app = App.get_running_app()
        if app is not None:
            app.bind(tool=self._on_active_tool_changed, active_color=self._on_active_color_changed)

    def _is_hidden(self):
        return not self.opacity

    def on_touch_down(self, touch):
        if self._is_hidden():
            return False
        # Always consume wheel events over the panel so the 3D viewer behind it
        # does not zoom, even when the legend content does not need scrolling.
        if self.collide_point(*touch.pos) and getattr(touch, "is_mouse_scrolling", False):
            super().on_touch_down(touch)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._is_hidden():
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._is_hidden():
            return False
        return super().on_touch_up(touch)

    def _on_active_tool_changed(self, *_args):
        if self._makera_root is not None:
            self._refresh_active_tool_highlight()

    def _on_active_color_changed(self, *_args):
        if self._makera_root is not None:
            self._refresh_active_tool_highlight()

    def _refresh_active_tool_highlight(self):
        app = App.get_running_app()
        active_tool = int(getattr(app, "tool", -1) or -1) if app else -1
        active_color = list(getattr(app, "active_color", LABEL_VISIBLE)) if app else list(LABEL_VISIBLE)
        legend_box = self.ids.get("legend_box")
        if legend_box is None:
            return
        for child in legend_box.children:
            if isinstance(child, LegendRow) and child.entry_kind == "tool":
                child.is_active_tool = int(child.entry_key) == active_tool
                child.set_active_color(active_color)

    def apply_visibility(self, makera_root):
        """Update row eye states in place without rebuilding (keeps scroll position)."""
        self._makera_root = makera_root
        legend_box = self.ids.get("legend_box")
        if legend_box is None:
            return

        any_vis = False
        for child in legend_box.children:
            if isinstance(child, LegendRow):
                visible = makera_root.is_legend_entry_visible(child.entry_kind, child.entry_key)
                child.visible = visible
                any_vis = any_vis or visible
        self.any_visible = any_vis

        viewer = getattr(makera_root, "gcode_viewer", None)
        scheme = getattr(viewer, "color_scheme", COLOR_SCHEME_BY_TYPE) if viewer else COLOR_SCHEME_BY_TYPE
        self._sync_scheme_spinner(makera_root, scheme)

    def refresh(self, makera_root):
        self._makera_root = makera_root
        legend_box = self.ids.legend_box
        legend_box.clear_widgets()
        viewer = makera_root.gcode_viewer
        if viewer is None:
            self.any_visible = False
            return

        scheme = getattr(viewer, "color_scheme", COLOR_SCHEME_BY_TYPE)
        used_tools = getattr(makera_root, "used_tools", None)
        entries = build_legend_entries(scheme, viewer, used_tools)
        durations = viewer.get_legend_durations(scheme)
        tool_table = getattr(makera_root, "tool_table", {}) or {}
        document_unit = getattr(makera_root, "document_unit", "mm")
        app = App.get_running_app()
        active_tool = int(getattr(app, "tool", -1) or -1) if app else -1
        active_color = list(getattr(app, "active_color", LABEL_VISIBLE)) if app else list(LABEL_VISIBLE)

        for entry in entries:
            if entry["kind"] == "tool":
                entry["tool_def"] = tool_table.get(int(entry["tool"]))
            if durations is None:
                entry["duration_sec"] = None
            else:
                entry["duration_sec"] = float(durations.get((entry["kind"], entry["key"]), 0.0))

        # Reserve a blank icon slot only when at least one tool can show an icon
        # (parsed tool defs and/or static icons such as laser.png).
        show_icon_column = any(_entry_has_legend_icon(entry) for entry in entries)

        any_vis = False
        row_heights = []
        for entry in entries:
            visible = makera_root.is_legend_entry_visible(entry["kind"], entry["key"])
            any_vis = any_vis or visible
            is_active = entry["kind"] == "tool" and int(entry["key"]) == active_tool
            row = LegendRow(
                entry,
                visible=visible,
                is_active_tool=is_active,
                active_color=active_color,
                on_toggle=makera_root.toggle_gcode_visibility_entry,
                document_unit=document_unit,
                show_icon_column=show_icon_column,
            )
            legend_box.add_widget(row)
            row_heights.append(row.height)

        self.any_visible = any_vis
        self._entry_count = len(entries)
        self._row_heights = row_heights
        self._sync_scheme_spinner(makera_root, scheme)
        Clock.schedule_once(self._finish_layout, 0)

    def _sync_scheme_spinner(self, makera_root, scheme):
        """Refresh spinner labels so modified schemes show a trailing star."""
        spinner = self.ids.get("gcode_color_scheme_spinner")
        if spinner is None:
            return
        labels = makera_root.gcode_scheme_spinner_labels()
        selected = makera_root.gcode_scheme_spinner_label(scheme)
        if list(spinner.values) != list(labels):
            spinner.values = labels
        if spinner.text != selected:
            spinner.text = selected

    def _finish_layout(self, _dt=None):
        legend_box = self.ids.get("legend_box")
        scroll = self.ids.get("legend_scroll")
        if legend_box is None or scroll is None:
            return

        row_heights = getattr(self, "_row_heights", None)
        if not row_heights:
            row_heights = [child.height for child in reversed(list(legend_box.children))]
        content_h = _legend_content_height(row_heights)
        legend_box.height = content_h
        legend_box.do_layout()

        chrome_h = HEADER_HEIGHT + PANEL_BOTTOM_PADDING
        max_scroll_h = max(LEGEND_PANEL_MAX_HEIGHT - chrome_h, 0)
        needs_scroll = content_h > max_scroll_h + 0.5
        scroll_h = max_scroll_h if needs_scroll else content_h

        scroll.size_hint_y = None
        scroll.height = scroll_h
        scroll.do_scroll_y = needs_scroll

        self.do_layout()
        scroll.scroll_y = 1
