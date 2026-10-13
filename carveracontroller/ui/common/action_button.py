"""Shared icon button used by popups and dialogs."""

from kivy.app import App
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton


class PopupActionButton(ToolTipButton):
    """Standard app Button with an optional leading icon and tinted variants."""

    icon = StringProperty("")
    btn_text = StringProperty("")
    primary = BooleanProperty(False)
    destructive = BooleanProperty(False)
    flat = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._watched_theme = None
        super().__init__(**kwargs)
        self.bind(
            state=self._sync_colors,
            primary=self._sync_colors,
            destructive=self._sync_colors,
            disabled=self._sync_colors,
            flat=self._sync_colors,
            role=self._sync_colors,
            pos=self._redraw_flat,
            size=self._redraw_flat,
            texture=self._redraw_flat,
            texture_size=self._redraw_flat,
            color=self._redraw_flat,
            icon=self._redraw_flat,
        )
        self._bind_theme()
        self._sync_colors()

    def _bind_theme(self):
        app = App.get_running_app()
        if app is None:
            return
        app.fbind("theme", self._on_app_theme)
        self._on_app_theme(app, getattr(app, "theme", None))

    def _on_app_theme(self, _app, theme):
        if self._watched_theme is not None:
            self._watched_theme.unbind(revision=self._sync_colors)
        self._watched_theme = theme
        if theme is not None:
            theme.bind(revision=self._sync_colors)
        self._sync_colors()

    def _sync_colors(self, *_args):
        app = App.get_running_app()
        theme = getattr(app, "theme", None) if app else None
        if theme is None:
            return
        # Flat buttons paint their own fill, so ask for the text that suits a visible fill.
        self.color = theme.button_text(self.role, self.state, self.disabled, True)
        self.background_normal = ""
        self.background_down = ""
        self.background_disabled_normal = ""
        self.background_disabled_down = ""
        self.background_color = [0, 0, 0, 0]
        self._redraw_flat()

    def _redraw_flat(self, *_args):
        """Paint the flat fill and left-align the label to the 10dp icon inset."""
        if not self.flat:
            return
        app = App.get_running_app()
        theme = getattr(app, "theme", None) if app else None
        if theme is None:
            return
        # chrome is off for flat buttons; ask for the visible fill directly.
        fill = theme.button_fill(self.role, self.state, self.disabled, True)
        inset = dp(10)
        icon_size = dp(20) if self.icon else 0
        text_x = self.x + inset + (icon_size + inset if self.icon else 0)
        text_h = self.texture_size[1] if self.texture_size else 0
        self.canvas.clear()
        with self.canvas:
            Color(rgba=fill)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(theme.radius_m)])
            if self.texture:
                Color(rgba=self.color)
                Rectangle(
                    texture=self.texture,
                    size=self.texture_size,
                    pos=(text_x, self.center_y - text_h / 2.0),
                )

    def on_parent(self, _instance, parent):
        if parent is None:
            self.close_tooltip()
            Window.unbind(mouse_pos=self.on_mouse_pos)


if "PopupActionButton" not in Factory.classes:
    Factory.register("PopupActionButton", cls=PopupActionButton)
