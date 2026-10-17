"""Semantic theme tokens. Bind ``app.theme`` in Kv and Python instead of hard-coded colors."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from kivy.event import EventDispatcher
from kivy.graphics import BorderImage, Color, InstructionGroup, Line, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.settings import SettingOptions
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

from carveracontroller.ui.fonts import ARIALUNI, resolve_theme_fonts

logger = logging.getLogger(__name__)
from carveracontroller.ui.themes import (
    BASE_THEME,
    BEHAVIOR_KEYS,
    ThemeError,
    jog_axis_color,
    load_behaviors,
    load_fonts,
    load_palette,
    theme_names,
    theme_title,
)

# Bundled palettes. DARK is the full token set.
DARK: dict = load_palette(BASE_THEME)


class _Palettes(Mapping):
    """Read-only ``{name: palette}`` view over the JSON files in ``ui/themes/bundled``."""

    def __getitem__(self, name):
        try:
            return load_palette(name)
        except ThemeError:
            raise KeyError(name) from None

    def __iter__(self):
        return iter(theme_names())

    def __len__(self):
        return len(theme_names())


PALETTES = _Palettes()
COLOR_TOKENS = {key for key, value in DARK.items() if isinstance(value, list)}


def _normalize_color(value) -> list:
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError(f"Theme color must be 3 or 4 numbers, got {value!r}")
    channels = [float(channel) for channel in value]
    if len(channels) == 3:
        channels.append(1.0)
    if max(channels) > 1:
        channels = [channel / 255.0 for channel in channels[:3]] + [
            channels[3] if channels[3] <= 1 else channels[3] / 255.0
        ]
    return channels


class Theme(EventDispatcher):
    """Live token set. ``revision`` increments after any token change.

    Kv rules that call :meth:`button_fill` must pass ``app.theme.revision``
    so Kivy re-evaluates them. Reading tokens inside the method is not a
    Kv dependency on its own.
    """

    revision = NumericProperty(0)
    name = StringProperty("dark")
    # Kivy ``font_name`` values: the ARIALUNI alias or an absolute font file path.
    # They come from the theme's ``fonts`` and are not color tokens, so ``apply()``
    # leaves them alone. Other roles follow ``font_default`` unless the theme sets them.
    font_default = StringProperty(ARIALUNI)
    font_top_bar = StringProperty(ARIALUNI)
    font_jog_pad = StringProperty(ARIALUNI)
    font_code_list = StringProperty(ARIALUNI)
    # Theme behaviors are not palette tokens. ``apply()`` leaves them alone.
    jog_pad_axis_colors = BooleanProperty(False)
    jog_pad_sign_colors = BooleanProperty(False)
    jog_pad_axis_background = BooleanProperty(False)
    group_main_menu = BooleanProperty(False)

    def __init__(self, palette: str = BASE_THEME, **kwargs):
        self._applying = False
        self._remap: dict = {}
        super().__init__(**kwargs)
        self.apply(DARK, name=BASE_THEME)
        if palette != BASE_THEME:
            self.apply_palette(palette)
        else:
            self.apply_fonts(BASE_THEME)
            self.apply_behaviors(BASE_THEME)
        for key in (*DARK, *BEHAVIOR_KEYS):
            self.bind(**{key: self._on_token})

    def _on_token(self, *_args):
        if self._applying:
            return
        self.revision += 1

    def apply(self, values: dict, name: str | None = None) -> None:
        """Set any known tokens. Unknown keys are skipped."""
        unknown = sorted(key for key in values if key not in DARK and key != "name")
        if unknown:
            logger.warning("Ignoring unknown theme tokens: %s", ", ".join(unknown))
            values = {key: value for key, value in values.items() if key not in unknown}
        self._prepare_remap(values)
        self._applying = True
        try:
            for key, value in values.items():
                if key == "name":
                    self.name = str(value)
                    continue
                if key in COLOR_TOKENS:
                    setattr(self, key, _normalize_color(value))
                else:
                    setattr(self, key, value)
            if name is not None:
                self.name = name
        finally:
            self._applying = False
        self.revision += 1

    def _prepare_remap(self, values: dict) -> None:
        """Map a copied token color onto the same token after a palette switch."""
        remap: dict = {}
        for key in DARK:
            if key not in COLOR_TOKENS or key not in values:
                continue
            old = self._color_key(getattr(self, key))
            new = _normalize_color(values[key])
            if old != self._color_key(new):
                remap.setdefault(old, new)
        self._remap = remap

    # Pressed jog keys stay the axis hue, a step darker than the resting face.
    _AXIS_PRESS_SCALE = 0.75

    @staticmethod
    def _color_key(color) -> tuple:
        return tuple(round(float(channel), 3) for channel in color)

    @staticmethod
    def _pressed_axis_color(color) -> list:
        channels = [float(channel) for channel in color]
        if len(channels) == 3:
            channels.append(1.0)
        scale = Theme._AXIS_PRESS_SCALE
        return [channel * scale for channel in channels[:3]] + [channels[3]]

    @staticmethod
    def _srgb_luminance(value: float) -> float:
        value = float(value)
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    @staticmethod
    def _relative_luminance(color) -> float:
        red, green, blue = color[:3]
        return (
            0.2126 * Theme._srgb_luminance(red)
            + 0.7152 * Theme._srgb_luminance(green)
            + 0.0722 * Theme._srgb_luminance(blue)
        )

    @staticmethod
    def _contrast_ratio(left, right) -> float:
        lighter = Theme._relative_luminance(left)
        darker = Theme._relative_luminance(right)
        if lighter < darker:
            lighter, darker = darker, lighter
        return (lighter + 0.05) / (darker + 0.05)

    def _label_on_fill(self, fill) -> list:
        """``text`` or ``text_inverse``, whichever reads on ``fill``."""
        text = list(self.text)
        inverse = list(self.text_inverse)
        if self._contrast_ratio(text, fill) >= self._contrast_ratio(inverse, fill):
            return text
        return inverse

    def remap_color(self, color):
        """The new-palette color for ``color`` if it was a token of the old palette, else ``None``."""
        try:
            return list(self._remap.get(self._color_key(color), ())) or None
        except (TypeError, ValueError):
            return None

    def apply_palette(self, palette_name: str) -> None:
        try:
            values = PALETTES[palette_name]
        except KeyError:
            known = ", ".join(sorted(PALETTES))
            raise ValueError(f"Unknown theme palette {palette_name!r}. Known: {known}") from None
        self.apply_fonts(palette_name)
        # apply() bumps the revision, so jog keys see the new flag and colors together.
        self._applying = True
        try:
            self.apply_behaviors(palette_name)
        finally:
            self._applying = False
        self.apply(values, name=palette_name)

    def apply_fonts(self, palette_name: str) -> None:
        """Set each font role from the ``fonts`` of ``palette_name``.

        A theme that leaves a role out uses the resolved default font.
        """
        fonts = resolve_theme_fonts(load_fonts(palette_name))
        self.font_default = fonts["default"]
        self.font_top_bar = fonts["top_bar"]
        self.font_jog_pad = fonts["jog_pad"]
        self.font_code_list = fonts["code_list"]

    def apply_behaviors(self, palette_name: str) -> None:
        """Set each behavior flag from the ``behaviors`` of ``palette_name``."""
        flags = load_behaviors(palette_name)
        for key in BEHAVIOR_KEYS:
            setattr(self, key, flags[key])

    def to_dict(self) -> dict:
        """JSON-friendly snapshot of the current tokens."""
        data = {}
        for key in DARK:
            value = getattr(self, key)
            if isinstance(value, list):
                data[key] = list(value)
            else:
                data[key] = value
        data["name"] = self.name
        return data

    def button_fill(self, role, state, disabled, chrome, _revision=0):
        """Fill for a themed button. ``_revision`` is a Kv dependency only."""
        del _revision
        if not chrome:
            return [0, 0, 0, 0]
        if disabled:
            return list(self.control_disabled)
        down = state == "down"
        if role == "danger":
            return list(self.danger_down if down else self.danger)
        if role == "help":
            return list(self.help_down if down else self.help)
        if role == "primary":
            return list(self.primary_down if down else self.primary)
        if down:
            return list(self.accent)
        return list(self.control)

    def jog_axis_fill(self, caption, state, disabled, chrome, _revision=0):
        """Jog-key fill. The axis color when that background behavior is on."""
        base = self.button_fill("normal", state, disabled, chrome, _revision)
        if not chrome or disabled or not self.jog_pad_axis_background:
            return base
        color = jog_axis_color(self, caption)
        if color is None:
            return base
        if state == "down":
            return self._pressed_axis_color(color)
        return list(color)

    def jog_axis_text(self, caption, state, disabled, chrome, _revision=0):
        """Label color on :meth:`jog_axis_fill`. An axis face picks the readable text token."""
        if chrome and not disabled and self.jog_pad_axis_background and jog_axis_color(self, caption) is not None:
            return self._label_on_fill(self.jog_axis_fill(caption, state, False, True, _revision))
        return self.button_text("normal", state, disabled, chrome, _revision)

    def button_text(self, role, state, disabled, chrome, _revision=0):
        """Label color on :meth:`button_fill`. Saturated faces use ``text_on_fill``."""
        del _revision
        if disabled:
            return list(self.text_disabled)
        if chrome and (state == "down" or role in ("danger", "help", "primary")):
            return list(self.text_on_fill)
        return list(self.text)

    def icon_tint(self, role, state, disabled, chrome, _revision=0):
        """Monochrome icon tint. Plain faces use ``icon`` so light-gray artwork stays visible."""
        del _revision
        if disabled:
            return list(self.text_disabled)
        if chrome and (state == "down" or role in ("danger", "help", "primary")):
            return list(self.text_on_fill)
        return list(self.icon)

    def icon_rgba(self, colored, role, state, disabled, chrome, _revision=0):
        """Tint monochrome icons. Colored artwork stays white so its own pixels show through."""
        if colored:
            # Disabled fades the texture. The RGB stays white: a theme tint would recolor it.
            return [1, 1, 1, 0.4 if disabled else 1]
        return self.icon_tint(role, state, disabled, chrome, _revision)

    def selection_fill(self, alpha, _revision=0):
        """Accent with a caller-supplied alpha. ``_revision`` is a Kv dependency."""
        del _revision
        red, green, blue, _alpha = self.accent
        return [red, green, blue, float(alpha)]


def _declare(cls, name: str, prop) -> None:
    """Register a Kivy property added after the class statement.

    Assigning a Property later does not call ``__set_name__``, so Kv would
    not see the token. Call this before any instance of ``cls`` is created.
    """
    setattr(cls, name, prop)
    prop.__set_name__(cls, name)


def _install_theme_tokens() -> None:
    for key, value in DARK.items():
        if key in Theme.__dict__:
            continue
        if isinstance(value, list):
            _declare(Theme, key, ListProperty(list(value)))
        else:
            _declare(Theme, key, NumericProperty(value))


_install_theme_tokens()


def _same_color(left, right) -> bool:
    try:
        return len(left) == len(right) and all(abs(a - b) < 1e-4 for a, b in zip(left, right))
    except TypeError:
        return False


def follow_theme(widget, attr: str, value, kivy_default) -> bool:
    """Make ``widget.<attr>`` track a theme color until something else sets it.

    The color is taken over only while the property still holds the Kivy
    default or the value this function applied last. A label given its own
    color, in kv or Python, keeps it across theme changes.
    """
    applied = widget.__dict__.setdefault("_theme_applied", {})
    previous = applied.get(attr, kivy_default)
    followed = _same_color(getattr(widget, attr), previous)
    if followed:
        setattr(widget, attr, list(value))
    applied[attr] = list(value)
    return followed


def _kv_assigns_property(widget, name: str) -> bool:
    """True when a class rule assigns ``name``. That rule owns the property.

    ``follow_theme`` treats Kivy's default white as "unset". On the light
    palette ``text_on_fill`` is that same white, so a selected tab or badge
    would be repainted with body text. A rule that sets ``color`` is not unset.
    """
    return any(name in rule.properties for rule in Builder.match(widget))


def follow_theme_text(widget, value) -> None:
    """Give a plain ``Label`` the theme text color unless it has its own. Buttons paint their own text."""
    if isinstance(widget, Button) or _kv_assigns_property(widget, "color"):
        return
    follow_theme(widget, "color", value, (1, 1, 1, 1))


def sync_theme_text(widget, value, use_theme_text) -> None:
    """Button text color: follow ``theme_text`` unless the button chose its own color."""
    if use_theme_text:
        follow_theme(widget, "color", value, (1, 1, 1, 1))


def retheme_label(widget, value) -> None:
    """On a palette switch, follow theme text or remap a copied token color."""
    if isinstance(widget, Button) or _kv_assigns_property(widget, "color"):
        return
    if follow_theme(widget, "color", value, (1, 1, 1, 1)):
        return
    mapped = get_theme().remap_color(widget.color)
    if mapped is not None:
        widget.color = mapped


def follow_theme_popup(widget, value) -> None:
    """Default panel color of a ``ModalView`` or ``Popup`` that does not set its own."""
    # Popup inherits ModalView's white default. The translucent black Kivy
    # shows around a popup is overlay_color, a different property.
    follow_theme(widget, "background_color", value, (1, 1, 1, 1))


def _shaded_field_tint(canvas):
    """Tint of Kivy's shaded field image. Keep it transparent; removing the image breaks GL state."""
    children = list(canvas.children)
    for index, child in enumerate(children):
        if not isinstance(child, BorderImage):
            continue
        for earlier in reversed(children[:index]):
            if isinstance(earlier, Color):
                return earlier
    return None


def _field_corner_radii(widget):
    """Corner radii in pixels, clockwise from the top left.

    ``field_radii`` is four design-unit values. An empty list uses ``field_radius``
    for every corner.
    """
    custom = list(getattr(widget, "field_radii", []) or [])
    if len(custom) >= 4:
        return [dp(custom[0]), dp(custom[1]), dp(custom[2]), dp(custom[3])]
    return [dp(widget.field_radius)]


def _install_flat_text_field(widget) -> None:
    """Flat field fill at the front of canvas.before, so the cursor and text stay on top."""
    if getattr(widget, "_flat_field", False):
        return
    widget._flat_field = True
    canvas = widget.canvas.before
    shade = _shaded_field_tint(canvas)
    widget._field_shade = shade
    if shade is not None:
        shade.rgba = (0, 0, 0, 0)
    # Keep each shape with the texture bind Canvas.add inserts in front of it.
    # Pulling the rounded rect out on its own makes it sample the texture that
    # was bound last, so the previous label is stretched across the field.
    group = InstructionGroup()
    fill = Color(rgba=(0, 0, 0, 0))
    rect = RoundedRectangle()
    edge = Color(rgba=(0, 0, 0, 0))
    line = Line(width=dp(1))
    group.add(fill)
    group.add(rect)
    group.add(edge)
    group.add(line)
    canvas.insert(0, group)

    def sync(*_args):
        # Kv paints the shaded image with background_color. Put that color on
        # the flat shape and keep the image itself invisible.
        shade = widget._field_shade
        if shade is not None:
            shade.rgba = (0, 0, 0, 0)
        radii = _field_corner_radii(widget)
        fill.rgba = widget.background_color
        rect.pos = widget.pos
        rect.size = widget.size
        rect.radius = radii
        edge_rgba = list(widget.field_edge)
        if len(edge_rgba) == 3:
            edge_rgba.append(1.0)
        if len(widget.background_color) >= 4 and widget.background_color[3] <= 0:
            edge_rgba[3] = 0
        edge.rgba = edge_rgba
        if widget.width <= 0 or widget.height <= 0 or edge_rgba[3] <= 0:
            line.rounded_rectangle = (0, 0, 0, 0, 0)
            return
        if len(radii) >= 4:
            line.rounded_rectangle = (widget.x, widget.y, widget.width, widget.height, *radii[:4])
        else:
            line.rounded_rectangle = (widget.x, widget.y, widget.width, widget.height, radii[0])

    widget.bind(pos=sync, size=sync, background_color=sync, field_edge=sync, field_radius=sync, field_radii=sync)
    sync()


def install_theme_properties() -> None:
    """Add theme hooks to Kivy Label, ModalView, Button, TextInput and DropDown once, before widgets exist."""
    if "_controller_theme" not in Label.__dict__:
        # Kivy labels default to white text. theme.kv fills this from the
        # theme and follow_theme_text moves color with it.
        _declare(Label, "theme_label_color", ListProperty([1, 1, 1, 1]))
        label_init = Label.__init__

        def label_init_themed(self, **kwargs):
            label_init(self, **kwargs)
            # Kv binds its on_ handlers after it sets the first value, so the
            # starting color is applied here, once every rule has run.
            follow_theme_text(self, get_theme().text)

        Label.__init__ = label_init_themed
        Label._controller_theme = True

    if "_controller_theme" not in ModalView.__dict__:
        _declare(ModalView, "theme_popup_fill", ListProperty([1, 1, 1, 1]))
        modal_init = ModalView.__init__

        def modal_init_themed(self, **kwargs):
            modal_init(self, **kwargs)
            follow_theme_popup(self, get_theme().surface)

        ModalView.__init__ = modal_init_themed
        ModalView._controller_theme = True

    if "_controller_theme" not in Button.__dict__:
        _declare(Button, "role", StringProperty("normal"))
        _declare(Button, "chrome", BooleanProperty(True))
        _declare(Button, "use_theme_text", BooleanProperty(True))
        _declare(Button, "radius_dp", NumericProperty(-1))
        # Pixel radii, clockwise from the top left. Empty uses radius_dp or the theme.
        _declare(Button, "corner_radii", ListProperty([]))
        _declare(Button, "theme_fill", ListProperty([0, 0, 0, 0]))
        _declare(Button, "theme_text", ListProperty([1, 1, 1, 1]))
        # theme_text_sync rebind: on_ handlers miss the first value Kv sets from rules.
        _declare(Button, "theme_text_sync", ObjectProperty(None, allownone=True))
        Button.sync_theme_text = sync_theme_text
        Button._controller_theme = True

    if "_controller_theme" not in TextInput.__dict__:
        _declare(TextInput, "field_radius", NumericProperty(0))
        # Design units, clockwise from the top left. Empty uses field_radius.
        _declare(TextInput, "field_radii", ListProperty([]))
        _declare(TextInput, "field_edge", ListProperty([0, 0, 0, 0]))
        # The MDI command field turns this off; its row has no outline.
        _declare(TextInput, "show_field_edge", BooleanProperty(True))
        # Kv fills theme_field_fill from the theme. theme_field_sync copies it
        # onto background_color while the field is still using the theme fill.
        # An on_ handler would miss that first value and leave the white default.
        _declare(TextInput, "theme_field_fill", ListProperty([1, 1, 1, 1]))
        _declare(TextInput, "theme_field_sync", ObjectProperty(None, allownone=True))
        text_init = TextInput.__init__

        def text_init_themed(self, **kwargs):
            text_init(self, **kwargs)
            _install_flat_text_field(self)

        TextInput.__init__ = text_init_themed
        TextInput._controller_theme = True

    if "_controller_theme" not in DropDown.__dict__:
        # pad_menu insets text menus; menu_fill paints the panel. The main menu turns both off.
        _declare(DropDown, "pad_menu", BooleanProperty(True))
        _declare(DropDown, "menu_fill", BooleanProperty(True))
        original_init = DropDown.__init__

        def __init__(self, **kwargs):
            original_init(self, **kwargs)
            container = self.container
            if container is not None and not getattr(container, "_controller_theme_padded", False):
                container.spacing = dp(4)
                if self.pad_menu:
                    container.padding = [dp(6), dp(6), dp(6), dp(6)]
                elif not self.menu_fill:
                    gap = float(container.spacing[1])
                    container.padding = [0, gap, 0, gap]
                container._controller_theme_padded = True
            # Kv post runs inside the original constructor, before this spacing.
            # The main menu groups its buttons there, so reapply once the gap is in place.
            regroup = getattr(self, "_apply_menu_grouping", None)
            if regroup is not None:
                regroup()

        DropDown.__init__ = __init__
        DropDown._controller_theme = True


install_theme_properties()


_fallback_theme: Theme | None = None


def rgba_to_hex(rgba, *, with_hash: bool = False) -> str:
    """Convert a theme rgba (0–1 channels) to ``rrggbb`` for Kivy markup."""
    channels = _normalize_color(rgba)
    hex_rgb = "".join(f"{int(round(channel * 255)):02x}" for channel in channels[:3])
    if with_hash:
        return f"#{hex_rgb}"
    return hex_rgb


def heading_markup(title: str, detail: str, detail_color) -> str:
    """Bold ``title``, then ``detail`` in ``detail_color`` (a theme rgba)."""
    return f"[b]{title}[/b]\n[color={rgba_to_hex(detail_color)}]{detail}[/color]"


def machine_state_color(state: str) -> list:
    """Status label colour for a Grbl-style machine state name."""
    theme = get_theme()
    by_state = {
        "Idle": theme.machine_idle,
        "Pause": theme.machine_pause,
        "Run": theme.machine_run,
        "Tool": theme.machine_tool,
        "Hold": theme.machine_hold,
        "Alarm": theme.machine_alarm,
        "Home": theme.machine_home,
        "Wait": theme.machine_wait,
        "Disable": theme.machine_disable,
        "Sleep": theme.machine_sleep,
        "N/A": theme.machine_not_connected,
    }
    # dict.get(key, fallback) is Any | None when the fallback is Any, so list() rejects it.
    color = by_state.get(state)
    if color is None:
        color = theme.text_muted
    return list(color)


def get_theme() -> Theme:
    """Return ``app.theme``, or a default theme when no app is running."""
    global _fallback_theme
    from kivy.app import App

    app = App.get_running_app()
    theme = getattr(app, "theme", None) if app is not None else None
    if theme is not None:
        return theme
    if _fallback_theme is None:
        _fallback_theme = Theme()
    return _fallback_theme


def watch_theme(callback) -> Callable[[], None]:
    """Call ``callback(get_theme())`` on token changes. Returns a ``stop`` callable."""
    from kivy.app import App

    app = App.get_running_app()
    state = {"theme": None, "active": True}

    def fire(*_args):
        if state["active"]:
            callback(get_theme())

    def attach(_app, theme):
        previous = state["theme"]
        if previous is not None:
            previous.unbind(revision=fire)
        state["theme"] = theme
        if theme is not None:
            theme.bind(revision=fire)
        fire()

    if app is None:
        fire()
        return lambda: None

    app.fbind("theme", attach)
    attach(app, getattr(app, "theme", None))

    def stop():
        state["active"] = False
        app.funbind("theme", attach)
        if state["theme"] is not None:
            state["theme"].unbind(revision=fire)
            state["theme"] = None

    return stop


def _options_shown_value(_setting, value):
    """Text of an options row. Theme rows replace this with the palette title."""
    return value or ""


if "shown_value" not in SettingOptions.__dict__:
    SettingOptions.shown_value = _options_shown_value


class SettingTheme(SettingOptions):
    """Theme choice. The config keeps the palette name; the row and popup show its title."""

    def shown_value(self, value):
        return theme_title(value)

    def _create_popup(self, instance):
        super()._create_popup(instance)
        names = list(self.options)
        buttons = [child for child in reversed(self.popup.content.children) if isinstance(child, ToggleButton)]
        if len(buttons) != len(names):
            return
        for name, button in zip(names, buttons):
            button.text = theme_title(name)
            button.unbind(on_release=self._set_option)
            button.bind(on_release=lambda _button, chosen=name: self._choose(chosen))

    def _choose(self, name):
        self.value = name
        if self.popup is not None:
            self.popup.dismiss()
