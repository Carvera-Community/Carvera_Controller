"""Cut-simulation overlay for the G-code viewer."""

from __future__ import annotations

from kivy.animation import Animation
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Rotate, Translate
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
from carveracontroller.ui.theme import DARK, get_theme, watch_theme

EYE_ICON_SOURCE = "data/eye.png"


class _HudIconToolTip(ToolTipButton):
    """Invisible tooltip host that hit-tests the icon without drawing chrome."""

    def __init__(self, **kwargs):
        kwargs.setdefault("text", "")
        kwargs.setdefault("opacity", 0)
        kwargs.setdefault("size_hint", (1, 1))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)
        self.canvas.before.clear()

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False


class SimStatsHudIcon(ButtonBehavior, Widget):
    """HUD glyph drawn without the gray tooltip-button background."""

    icon_source = StringProperty(EYE_ICON_SOURCE)
    icon_active = BooleanProperty(True)
    tooltip_txt = StringProperty("")

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        super().__init__(**kwargs)
        icon = dp(18)
        with self.canvas:
            PushMatrix()
            self._translate = Translate(0, 0)
            theme = get_theme()
            self._color = Color(*theme.icon)
            self._icon = Rectangle(source=self.icon_source, size=(icon, icon))
            PopMatrix()
        self._tip = _HudIconToolTip()
        self.add_widget(self._tip)
        self._stop_theme = watch_theme(self._apply_theme)
        self.bind(
            pos=self._layout,
            size=self._layout,
            icon_active=self._sync_icon,
            icon_source=self._sync_source,
            tooltip_txt=self._sync_tooltip,
        )
        self._layout()
        self._sync_icon()
        self._sync_source()
        self._sync_tooltip()

    def _layout(self, *_args) -> None:
        self._translate.x = self.x
        self._translate.y = self.y
        icon = dp(18)
        self._icon.size = (icon, icon)
        self._icon.pos = (self.width * 0.5 - icon / 2.0, self.height * 0.5 - icon / 2.0)
        self._tip.pos = self.pos
        self._tip.size = self.size

    def _apply_theme(self, theme) -> None:
        self._sync_icon(theme=theme)

    def _sync_icon(self, *_args, theme=None) -> None:
        if theme is None:
            theme = get_theme()
        if self.icon_active:
            self._color.rgba = list(theme.icon)
        else:
            hidden = list(theme.text_muted)
            hidden[3] = 0.9
            self._color.rgba = hidden

    def _sync_source(self, *_args) -> None:
        self._icon.source = self.icon_source

    def _sync_tooltip(self, *_args) -> None:
        self._tip.tooltip_txt = self.tooltip_txt


class CarveSpinner(Widget):
    """Short rotating arc shown while the stock carver is working."""

    angle = NumericProperty(0.0)
    spinning = BooleanProperty(False)
    line_rgba = ListProperty(list(DARK["active_color"]))

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        if "line_rgba" not in kwargs:
            kwargs["line_rgba"] = list(get_theme().active_color)
        super().__init__(**kwargs)
        with self.canvas:
            self._color = Color(*self.line_rgba)
            PushMatrix()
            self._translate = Translate(0, 0)
            self._rotate = Rotate(angle=0, origin=(0, 0))
            self._arc = Line(circle=(0, 0, 1, 0, 280), width=1.25, cap="round")
            PopMatrix()
        self.bind(
            pos=self._layout,
            size=self._layout,
            angle=self._apply_angle,
            spinning=self._on_spinning,
            line_rgba=self._apply_color,
        )
        self._layout()
        self.opacity = 1.0 if self.spinning else 0.0
        self._stop_theme = watch_theme(self._apply_theme_spinner)

    def _apply_theme_spinner(self, theme) -> None:
        self.line_rgba = list(theme.active_color)

    def _apply_color(self, *_args) -> None:
        self._color.rgba = self.line_rgba

    def _layout(self, *_args) -> None:
        self._translate.x = self.x
        self._translate.y = self.y
        cx = self.width * 0.5
        cy = self.height * 0.5
        radius = max(min(self.width, self.height) * 0.38, 1.0)
        self._rotate.origin = (cx, cy)
        self._arc.circle = (cx, cy, radius, 0, 280)
        self._apply_angle()

    def _apply_angle(self, *_args) -> None:
        self._rotate.angle = float(self.angle)
        self._rotate.origin = (self.width * 0.5, self.height * 0.5)

    def _on_spinning(self, _instance, spinning: bool) -> None:
        Animation.cancel_all(self, "angle")
        self.opacity = 1.0 if spinning else 0.0
        if spinning:
            self._spin()

    def _spin(self, *_args) -> None:
        if not self.spinning:
            return
        anim = Animation(angle=self.angle + 360.0, duration=0.75, t="linear")
        anim.bind(on_complete=self._spin)
        anim.start(self)


class SimStatsHud(BoxLayout):
    """Simulation title, carving spinner, stock cog, mesh eye, and stats."""

    stats_text = StringProperty("")
    carving = BooleanProperty(False)
    mesh_visible = BooleanProperty(True)
    hud_visible = BooleanProperty(False)

    def _is_hidden(self) -> bool:
        return (not self.hud_visible) or self.opacity <= 0

    def on_touch_down(self, touch):
        if self._is_hidden():
            return False
        if self.collide_point(*touch.pos):
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
