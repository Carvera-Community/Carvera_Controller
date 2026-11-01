"""Theme settings page: pick a palette, edit a draft, and preview it.

Apply writes a changed draft as Custom and switches the interface. Cancel
reloads the theme that was open.
"""

from __future__ import annotations

import json
import logging

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import ContentPanel, SettingItem, SettingsPanel
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget

from carveracontroller.addons.keyboard_shortcuts.ui import _CategoryHeader, _CategorySection
from carveracontroller.translation import tr
from carveracontroller.ui.fonts import (
    ARIALUNI,
    STYLE_ROMAN,
    WEIGHT_REGULAR,
    FontSpecError,
    available_families,
    available_styles,
    available_weights,
    font_choice,
    font_index,
    resolve_font,
    split_font_spec,
)
from carveracontroller.ui.fonts.dropdown import FontFaceChoice, FontFamilyField
from carveracontroller.ui.theme import Theme, get_theme, watch_theme
from carveracontroller.ui.themes import (
    BEHAVIOR_KEYS,
    CUSTOM_THEME,
    DEFAULT_THEME,
    ThemeError,
    clear_theme_cache,
    custom_theme_document,
    format_hex_color,
    list_themes,
    load_behaviors,
    load_font_specs,
    parse_hex_color,
    theme_extends,
    theme_title,
    token_sections,
    user_themes_dir,
)
from carveracontroller.ui.themes.preview import PREVIEW_GAP, PREVIEW_PANE_WIDTH, ThemePreview
from carveracontroller.ui.themes.token_descriptions import TOKEN_DESCRIPTIONS, token_description

logger = logging.getLogger(__name__)

CONTROL_HEIGHT = dp(32)
MIN_PANE_HEIGHT = dp(180)
TAB_STRIP_HEIGHT = CONTROL_HEIGHT
FIELDS_BAR_WIDTH = dp(8)
# The scrollbar is painted over the list. This inset keeps it off the revert button.
FIELDS_SCROLL_GUTTER = FIELDS_BAR_WIDTH + dp(4)
REVERT_ICON = "data/history.png"

_BEHAVIOR_CAPTIONS = {
    "jog_pad_axis_colors": "Jog pad axis colors",
    "jog_pad_sign_colors": "Jog pad sign colors",
    "jog_pad_axis_background": "Jog pad axis background",
    "group_main_menu": "Group main menu buttons",
}

_SECTION_TITLES = {
    "colors": "Main colors",
    "machine": "Machine state",
    "fonts": "Fonts",
    "behaviors": "Behaviors",
    "axis": "Axes",
    "map": "Preview Map",
    "gcode": "G-code",
    "sketch": "Sketch",
    "cmm": "CMM",
    "facing": "Facing",
    "viewer": "Viewer",
    "graph": "Monitoring graph",
    "speed_colormap": "Speed colors",
    "tooltip": "Tooltip",
    "scroll": "Scroll bar",
    "layout": "Layout",
}


_cached_name_column_width: float | None = None


def _name_column_width() -> float:
    """Width that fits the longest token name and its one-line description."""
    global _cached_name_column_width
    if _cached_name_column_width is not None:
        return _cached_name_column_width
    probe = Label(font_name=ARIALUNI, font_size=sp(11))
    width = 0.0
    for text in TOKEN_DESCRIPTIONS.values():
        probe.text = str(text)
        probe.texture_update()
        width = max(width, float(probe.texture_size[0]))
    probe.font_size = sp(15)
    for key in TOKEN_DESCRIPTIONS:
        probe.text = key
        probe.texture_update()
        width = max(width, float(probe.texture_size[0]))
    _cached_name_column_width = width + dp(8)
    return _cached_name_column_width


def _control_cluster_width() -> float:
    """Swatch, value field, revert button, and the gaps between them."""
    return dp(28) + dp(112) + CONTROL_HEIGHT + dp(6) * 3


def fields_pane_width() -> float:
    """Minimum width of the value list once every description fits on one line."""
    return _name_column_width() + _control_cluster_width() + dp(18) + FIELDS_SCROLL_GUTTER


def preview_shown_for_width(width: float) -> bool:
    """True when both the value list and the preview fit beside each other."""
    return width >= fields_pane_width() + PREVIEW_GAP + PREVIEW_PANE_WIDTH


def _center_input_text(field, *_args) -> None:
    """Keep a single-line field's text in the vertical middle of its box."""
    line = field.line_height or field.font_size
    pad_y = max((field.height - line) / 2, dp(2))
    padding = [dp(6), pad_y, dp(6), pad_y]
    if [float(value) for value in field.padding] != padding:
        field.padding = padding


def _section_title(group: str) -> str:
    return tr._(_SECTION_TITLES.get(group, group.replace("_", " ").title()))


def _category_tab(group: str, toggle_group: str) -> ToggleButton:
    """A tab sized to its label. Only one tab in ``toggle_group`` stays down."""
    tab = ToggleButton(
        text=_section_title(group),
        group=toggle_group,
        allow_no_selection=False,
        size_hint=(None, 1),
        font_name=ARIALUNI,
        font_size=sp(13),
        padding=(dp(12), dp(4)),
    )
    tab.texture_update()
    tab.width = float(tab.texture_size[0]) + dp(24)
    return tab


def _format_number(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(value)


def _parse_number(text: str):
    number = float(text)
    if number.is_integer():
        return int(number)
    return number


def _open_color_picker(initial_rgba, on_color) -> None:
    """Modal Kivy color picker; ``on_color`` receives an RGBA tuple in 0–1 range."""
    content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
    picker = ColorPicker(color=list(initial_rgba))
    content.add_widget(picker)
    buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
    popup = Popup(
        title=tr._("Select Color"),
        content=content,
        size_hint=(0.75, 0.88),
        auto_dismiss=False,
    )

    def _cancel(*_args):
        popup.dismiss()

    def _confirm(*_args):
        on_color(picker.color)
        popup.dismiss()

    cancel = Button(text=tr._("Cancel"))
    cancel.bind(on_release=_cancel)
    ok = Button(text=tr._("OK"))
    ok.bind(on_release=_confirm)
    buttons.add_widget(cancel)
    buttons.add_widget(ok)
    content.add_widget(buttons)
    popup.open()


class _IconButton(ButtonBehavior, BoxLayout):
    """Square MDI button with the same fill and radius as other controls."""

    def __init__(self, icon_source: str, on_release=None, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(CONTROL_HEIGHT, CONTROL_HEIGHT),
            padding=dp(6),
            **kwargs,
        )
        with self.canvas.before:
            self.fill_color = Color(*get_theme().button_fill("normal", "normal", False, True))
            self.fill_rect = RoundedRectangle(radius=[dp(4)])
        self._image = Image(
            source=icon_source,
            allow_stretch=True,
            keep_ratio=True,
            color=list(get_theme().icon_tint("normal", "normal", False, True)),
        )
        self.add_widget(self._image)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas, state=self._paint)
        if on_release is not None:
            self.bind(on_release=on_release)
        watch_theme(self._paint)
        self._paint()

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size

    def _paint(self, *_args) -> None:
        theme = get_theme()
        self.fill_color.rgba = theme.button_fill("normal", self.state, False, True)
        self._image.color = theme.icon_tint("normal", self.state, False, True)


class _ColorSwatch(ButtonBehavior, Widget):
    """Color preview. A click opens the color picker."""

    def __init__(self, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(dp(28), CONTROL_HEIGHT),
            pos_hint={"center_y": 0.5},
            **kwargs,
        )
        with self.canvas:
            self.swatch_color = Color(1, 1, 1, 1)
            self.swatch_rect = RoundedRectangle(radius=[dp(4)])
        self.bind(pos=self._place, size=self._place)

    def _place(self, *_args) -> None:
        self.swatch_rect.pos = self.pos
        self.swatch_rect.size = self.size


class _DescribedRow:
    _name_column: BoxLayout
    _name: Label
    _description: Label | None

    def _fit_labels(self, *_args) -> None:
        width = max(float(self._name_column.width), float(_name_column_width()))
        self._name.text_size = (width, None)
        self._name.texture_update()
        self._name.height = max(dp(18), float(self._name.texture_size[1]))
        desc_height = 0.0
        if self._description is not None:
            self._description.text_size = (width, None)
            self._description.texture_update()
            desc_height = float(self._description.texture_size[1])
            self._description.height = desc_height
        self.height = max(CONTROL_HEIGHT + dp(8), self._name.height + desc_height + dp(2))

    def _apply_description_theme(self, theme) -> None:
        if self._description is not None:
            self._description.color = list(theme.text_muted)


class _TokenField(_DescribedRow, BoxLayout):
    def __init__(self, key, color, on_change, on_revert, color_for_picker, **kwargs):
        super().__init__(size_hint_y=None, height=CONTROL_HEIGHT + dp(8), spacing=dp(6), **kwargs)
        self.key = key
        self.color = color
        self._on_change = on_change
        self._on_revert = on_revert
        self._color_for_picker = color_for_picker
        self._loading = False
        self.swatch_color = None
        self._name_column = BoxLayout(
            orientation="vertical",
            size_hint_x=1,
            size_hint_min_x=_name_column_width(),
            spacing=0,
        )
        self._name = Label(
            text=key,
            font_name=ARIALUNI,
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle",
            shorten=False,
        )
        self._name_column.add_widget(self._name)
        description_text = token_description(key)
        self._description = None
        if description_text:
            self._description = Label(
                text=description_text,
                font_name=ARIALUNI,
                font_size=sp(11),
                color=list(get_theme().text_muted),
                size_hint_y=None,
                height=dp(16),
                halign="left",
                valign="middle",
                shorten=False,
            )
            self._name_column.add_widget(self._description)
            watch_theme(self._apply_description_theme)
        self._name_column.bind(width=self._fit_labels)
        self.add_widget(self._name_column)
        self.swatch = None
        if color:
            self.swatch = _ColorSwatch()
            self.swatch.bind(on_release=self._open_picker)
            self.swatch_color = self.swatch.swatch_color
            self.add_widget(self.swatch)
        self.field = TextInput(
            multiline=False,
            write_tab=False,
            font_name=ARIALUNI,
            size_hint=(None, None),
            size=(dp(112), CONTROL_HEIGHT),
            pos_hint={"center_y": 0.5},
            padding=[dp(6), dp(6)],
        )
        self.field.bind(text=self._changed, size=_center_input_text)
        self.add_widget(self.field)
        self.revert = _IconButton(REVERT_ICON, on_release=lambda *_args: self._on_revert(self.key))
        self.revert.pos_hint = {"center_y": 0.5}
        self.add_widget(self.revert)
        self._fit_labels()

    def show(self, value) -> None:
        """Display ``value`` without treating the assignment as an edit."""
        self._loading = True
        try:
            if self.color:
                self.field.text = format_hex_color(value)
                self.swatch_color.rgba = value
            else:
                self.field.text = _format_number(value)
        finally:
            self._loading = False

    def paint(self, value) -> None:
        if self.color and self.swatch_color is not None:
            self.swatch_color.rgba = value

    def _changed(self, _field, text):
        if not self._loading:
            self._on_change(self.key, text)

    def _open_picker(self, *_args):
        rgba = self._color_for_picker(self.key)
        _open_color_picker(rgba, self._picked)

    def _picked(self, rgba) -> None:
        text = format_hex_color(rgba)
        if self.field.text != text:
            self.field.text = text
        else:
            self._on_change(self.key, text)


class _FontFieldRow(_DescribedRow, BoxLayout):
    def __init__(self, caption, role, families, on_revert, **kwargs):
        super().__init__(size_hint_y=None, height=CONTROL_HEIGHT * 2 + dp(12), spacing=dp(6), **kwargs)
        self.role = role
        self._same = tr._("Same as default")
        choices = []
        seen = set()
        if role != "default":
            choices.append(self._same)
            seen.add(self._same)
        for name in families:
            if name not in seen:
                choices.append(name)
                seen.add(name)
        text = ARIALUNI if role == "default" else self._same
        desc_key = f"font_{role}"
        self._name_column = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            width=_name_column_width(),
            height=dp(34),
            pos_hint={"center_y": 0.5},
            spacing=0,
        )
        self._name = Label(
            text=caption,
            font_name=ARIALUNI,
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle",
            shorten=False,
        )
        self._name_column.add_widget(self._name)
        description_text = token_description(desc_key)
        self._description = None
        if description_text:
            self._description = Label(
                text=description_text,
                font_name=ARIALUNI,
                font_size=sp(11),
                color=list(get_theme().text_muted),
                size_hint_y=None,
                height=dp(16),
                halign="left",
                valign="middle",
                shorten=False,
            )
            self._name_column.add_widget(self._description)
            watch_theme(self._apply_description_theme)
        self._name_column.bind(width=self._fit_labels)
        self.add_widget(self._name_column)
        self.field = FontFamilyField(text=text, values=choices, size_hint=(1, None), height=CONTROL_HEIGHT)
        self.weight = FontFaceChoice(
            text=WEIGHT_REGULAR,
            values=[WEIGHT_REGULAR],
            size_hint=(1, None),
            height=CONTROL_HEIGHT,
        )
        self.style = FontFaceChoice(
            text=STYLE_ROMAN,
            values=[STYLE_ROMAN],
            size_hint=(1, None),
            height=CONTROL_HEIGHT,
        )
        faces = BoxLayout(orientation="horizontal", spacing=dp(4), size_hint_y=None, height=CONTROL_HEIGHT)
        faces.add_widget(self.weight)
        faces.add_widget(self.style)
        self._controls = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint=(1, None),
            height=CONTROL_HEIGHT * 2 + dp(4),
            pos_hint={"center_y": 0.5},
        )
        self._controls.add_widget(self.field)
        self._controls.add_widget(faces)
        self.revert = _IconButton(REVERT_ICON, on_release=lambda *_args: on_revert(role))
        self.revert.pos_hint = {"center_y": 0.5}
        self.add_widget(self._controls)
        self.add_widget(self.revert)
        self.refresh(None)
        self._fit_labels()

    def _fit_labels(self, *_args) -> None:
        _DescribedRow._fit_labels(self, *_args)
        text_height = self._name.height
        if self._description is not None:
            text_height += self._description.height
        self._name_column.height = text_height
        self.height = max(self.height, CONTROL_HEIGHT * 2 + dp(12))

    def spec(self):
        """Family, face object, path, or ``""`` when this role follows the default."""
        text = self.field.text.strip()
        if self.role != "default" and text == self._same:
            return ""
        if self.role == "default" and not text:
            return ARIALUNI
        return font_choice(text, self.weight.text, self.style.text)

    def show(self, spec, default_row=None) -> None:
        """Select ``spec``. An empty optional role shows "Same as default"."""
        if self.role != "default" and spec in (None, ""):
            self.field.text = self._same
            self.refresh(default_row)
            return
        try:
            family, weight, style = split_font_spec(spec or ARIALUNI)
        except FontSpecError:
            family, weight, style = ARIALUNI, WEIGHT_REGULAR, STYLE_ROMAN
        if family not in self.field.values:
            self.field.values = [*self.field.values, family]
        self.field.text = family
        self.refresh(default_row, keep=(weight, style))

    def refresh(self, default_row, keep=None) -> None:
        """List the faces of the selected family. "Same as default" mirrors that row."""
        following = self.role != "default" and self.field.text.strip() == self._same
        if following and default_row is not None:
            family = default_row.field.text.strip()
            weight = default_row.weight.text or WEIGHT_REGULAR
            style = default_row.style.text or STYLE_ROMAN
        elif following:
            family = ""
            weight, style = WEIGHT_REGULAR, STYLE_ROMAN
        else:
            family = self.field.text.strip()
            if keep:
                weight, style = keep
            else:
                weight = self.weight.text or WEIGHT_REGULAR
                style = self.style.text or STYLE_ROMAN
        weights = available_weights(family)
        styles = available_styles(family, weight if weight in weights else WEIGHT_REGULAR)
        if not following and weight not in weights:
            if keep:
                weights = [*weights, weight]
            else:
                weight = weights[0]
                styles = available_styles(family, weight)
        if not following and style not in styles:
            if keep:
                styles = [*styles, style]
            else:
                style = styles[0]
        if following and weight not in weights:
            weights = [*weights, weight]
        if following and style not in styles:
            styles = [*styles, style]
        self.weight.values = weights
        self.weight.text = weight
        self.style.values = styles
        self.style.text = style
        self.weight.disabled = following
        self.style.disabled = following


class _BehaviorFieldRow(_DescribedRow, BoxLayout):
    def __init__(self, caption, key, on_toggle, on_revert, **kwargs):
        super().__init__(size_hint_y=None, height=CONTROL_HEIGHT + dp(8), spacing=dp(6), **kwargs)
        self.key = key
        self._name_column = BoxLayout(
            orientation="vertical",
            size_hint_x=1,
            size_hint_min_x=_name_column_width(),
            spacing=0,
        )
        self._name = Label(
            text=caption,
            font_name=ARIALUNI,
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle",
            shorten=False,
        )
        self._name_column.add_widget(self._name)
        description_text = token_description(key)
        self._description = None
        if description_text:
            self._description = Label(
                text=description_text,
                font_name=ARIALUNI,
                font_size=sp(11),
                color=list(get_theme().text_muted),
                size_hint_y=None,
                height=dp(16),
                halign="left",
                valign="middle",
                shorten=False,
            )
            self._name_column.add_widget(self._description)
            watch_theme(self._apply_description_theme)
        self._name_column.bind(width=self._fit_labels)
        self.add_widget(self._name_column)
        self.switch = Switch(
            active=False,
            size_hint=(None, None),
            size=(dp(83), CONTROL_HEIGHT),
            pos_hint={"center_y": 0.5},
        )
        self.switch.bind(active=lambda _switch, value: on_toggle(key, value))
        self.revert = _IconButton(REVERT_ICON, on_release=lambda *_args: on_revert(key))
        self.revert.pos_hint = {"center_y": 0.5}
        self.add_widget(self.switch)
        self.add_widget(self.revert)
        self._fit_labels()


class SettingThemeEditor(SettingItem):
    # Kivy's ``value`` is an untyped ObjectProperty. This editor stores a theme name.
    value: str
    _baseline: dict
    _baseline_fonts: dict
    _baseline_behaviors: dict
    _sections: dict
    _section_tabs: dict

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # This page is the whole row, so drop SettingItem's title column.
        if self.content is not None:
            self.content.size_hint_x = 1
            content_parent = self.content.parent
            if content_parent is not None:
                for sibling in tuple(content_parent.children):
                    if sibling != self.content:
                        content_parent.remove_widget(sibling)

        self._loading = False
        self._font_refresh = False
        self._syncing_value = False
        self._committing = False
        self._force_reload = False
        self._selected = ""
        self._opened_name = ""
        self._title_to_name = {}
        self._rows = {}
        self._baseline = {}
        self._baseline_fonts = {}
        self._baseline_behaviors = {}
        self._preview_visible = True
        self._active_section = ""
        self._sections = {}
        self._section_tabs = {}
        self._tab_group = f"theme-sections-{id(self)}"
        self._viewport_scroll = None
        self._panel_hooks = False
        self._pane_height = MIN_PANE_HEIGHT
        self.draft = Theme(DEFAULT_THEME)

        self._editor_height = self._measure_editor_height()
        self.size_hint_y = None
        self.height = self._editor_height
        self.bind(height=self._keep_editor_height)

        layout = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(10), dp(8)],
            size_hint_y=None,
            height=self._editor_height,
        )
        self._editor_layout = layout

        chooser = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._spinner = Spinner(text="", values=[], size_hint_x=1)
        self._spinner.bind(text=self._on_theme_text)
        chooser.add_widget(self._spinner)
        layout.add_widget(chooser)
        self._chooser = chooser

        self._body_row = BoxLayout(
            orientation="horizontal",
            spacing=PREVIEW_GAP,
            size_hint_y=None,
            height=self._pane_height,
        )
        self._body_row.bind(width=self._on_body_width)

        self._fields_pane = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_x=1,
            size_hint_min_x=fields_pane_width(),
        )
        self._tab_scroll = ScrollView(
            do_scroll_y=False,
            size_hint_y=None,
            height=TAB_STRIP_HEIGHT,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        self._tab_strip = BoxLayout(orientation="horizontal", size_hint=(None, 1), spacing=dp(4))
        self._tab_strip.bind(minimum_width=self._tab_strip.setter("width"))
        self._tab_scroll.add_widget(self._tab_strip)
        self._tab_scroll.bind(width=self._keep_active_tab_visible)
        self._tab_strip.bind(width=self._keep_active_tab_visible)
        self._fields_scroll = ScrollView(
            do_scroll_x=False,
            size_hint_y=None,
            bar_width=FIELDS_BAR_WIDTH,
            scroll_type=["bars", "content"],
        )
        self._fields_column = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            padding=[0, 0, FIELDS_SCROLL_GUTTER, 0],
        )
        self._fields_column.bind(minimum_height=self._sync_fields_column_height)
        self._fields_scroll.add_widget(self._fields_column)
        self._fields_pane.add_widget(self._tab_scroll)
        self._fields_pane.add_widget(self._fields_scroll)

        self._preview_column = BoxLayout(
            orientation="vertical",
            size_hint_x=None,
            width=PREVIEW_PANE_WIDTH,
            size_hint_y=None,
            height=self._pane_height,
        )
        self._preview_header = _CategoryHeader(text=f"[b]{tr._('Preview')}[/b]")
        self._preview_scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(8),
            scroll_type=["bars", "content"],
        )
        with self._preview_scroll.canvas.before:
            self._preview_backdrop = Color(*self.draft.bg)
            self._preview_backdrop_rect = Rectangle()
        self._preview_scroll.bind(pos=self._sync_preview_backdrop, size=self._sync_preview_backdrop)
        self.preview = ThemePreview(self.draft)
        self.preview.backdrop_color = self._preview_backdrop
        self.preview.refresh(self.draft)
        self._preview_scroll.add_widget(self.preview)
        self._preview_column.add_widget(self._preview_header)
        self._preview_column.add_widget(self._preview_scroll)
        self._body_row.add_widget(self._fields_pane)
        self._body_row.add_widget(self._preview_column)

        sections = token_sections()
        for group, keys in sections:
            section = _CategorySection()
            for key in keys:
                color = isinstance(getattr(self.draft, key), list)
                row = _TokenField(
                    key,
                    color,
                    self.set_token,
                    self.revert_token,
                    self._draft_color,
                )
                self._rows[key] = row
                section.add_widget(row)
            self._register_section(group, section)

        fonts_section = _CategorySection()
        self._font_fields = {}
        families = available_families()
        for role, caption in (
            ("default", tr._("Default font")),
            ("top_bar", tr._("Top bar font")),
            ("jog_pad", tr._("Jog pad font")),
            ("code_list", tr._("Code list font")),
        ):
            row = _FontFieldRow(caption, role, families, self.revert_font)
            self._font_fields[role] = row
            fonts_section.add_widget(row)
        self.font_default_field = self._font_fields["default"]
        self.font_top_bar_field = self._font_fields["top_bar"]
        self.font_jog_pad_field = self._font_fields["jog_pad"]
        self.font_code_list_field = self._font_fields["code_list"]
        self._register_section("fonts", fonts_section)
        for field in self._font_fields.values():
            field.field.bind(text=self._on_font_choice)
            field.weight.bind(text=self._on_font_choice)
            field.style.bind(text=self._on_font_choice)

        behaviors_section = _CategorySection()
        self._behavior_fields = {}
        for key in BEHAVIOR_KEYS:
            row = _BehaviorFieldRow(
                tr._(_BEHAVIOR_CAPTIONS.get(key, key)),
                key,
                self._on_behavior,
                self.revert_behavior,
            )
            self._behavior_fields[key] = row
            behaviors_section.add_widget(row)
        self._register_section("behaviors", behaviors_section)
        first = next(iter(self._sections))
        self._section_tabs[first].state = "down"

        layout.add_widget(self._body_row)

        self.add_widget(layout)
        self._sync_fields_column_height()
        self._apply_pane_heights()
        self.draft.bind(
            revision=self._on_draft_changed,
            font_default=self._on_draft_changed,
            font_top_bar=self._on_draft_changed,
            font_jog_pad=self._on_draft_changed,
            font_code_list=self._on_draft_changed,
            **dict.fromkeys(BEHAVIOR_KEYS, self._on_draft_changed),
        )
        self._opened_name = self._initial_name()
        self._load_form(self._opened_name)
        self.bind(value=self._on_external_value)
        self.bind(parent=self._on_parent_changed)
        Window.bind(size=self._sync_viewport_height)
        Clock.schedule_once(self._sync_viewport_height, 0)
        Clock.schedule_once(self._restore_editor_height, 0)
        Clock.schedule_once(lambda _dt: self._on_body_width(self._body_row, self._body_row.width), 0)

    def _register_section(self, group: str, section) -> None:
        """Keep ``section`` off the tree until its tab is selected."""
        self._sections[group] = section
        tab = _category_tab(group, self._tab_group)
        tab.bind(state=lambda _tab, state, name=group: self._on_tab_state(name, state))
        self._section_tabs[group] = tab
        self._tab_strip.add_widget(tab)

    def _on_tab_state(self, group: str, state: str) -> None:
        if state == "down":
            self._show_section(group)

    def _show_section(self, group: str) -> None:
        """Mount one category. Hidden rows stay alive so edits and Apply still see them.

        Kivy only clears a toggle group on a click, so a programmatic selection
        has to release the other tabs itself.
        """
        section = self._sections[group]
        if self._active_section != group or section.parent is not self._fields_column:
            current = self._sections.get(self._active_section)
            if current is not None and current.parent is self._fields_column:
                self._fields_column.remove_widget(current)
            self._fields_column.add_widget(section)
            self._active_section = group
            self._sync_fields_column_height()
            self._fields_scroll.scroll_y = 1
            Clock.schedule_once(lambda _dt: self._reveal_tab(group), 0)
        for name, tab in self._section_tabs.items():
            wanted = "down" if name == group else "normal"
            if tab.state != wanted:
                tab.state = wanted

    def _keep_active_tab_visible(self, *_args) -> None:
        if self._active_section:
            self._reveal_tab(self._active_section)

    def _reveal_tab(self, group: str) -> None:
        tab = self._section_tabs.get(group)
        scroll = self._tab_scroll
        strip = self._tab_strip
        if tab is None or scroll.width < 1 or strip.width < 1:
            return
        span = float(strip.width) - float(scroll.width)
        if span <= 1:
            scroll.scroll_x = 0
            return
        # tab.x follows the strip, which the scroll view moves. Measure inside the strip.
        left = float(tab.x) - float(strip.x)
        right = left + float(tab.width)
        visible_left = float(scroll.scroll_x) * span
        visible_right = visible_left + float(scroll.width)
        if left < visible_left:
            scroll.scroll_x = max(0.0, left / span)
        elif right > visible_right:
            scroll.scroll_x = min(1.0, max(0.0, (right - float(scroll.width)) / span))

    @staticmethod
    def _column_height(column) -> float:
        children = column.children
        if not children:
            return 0
        return sum(child.height for child in children) + float(column.spacing) * (len(children) - 1)

    def _sync_fields_column_height(self, *_args) -> None:
        needed = self._column_height(self._fields_column)
        if needed > 0:
            self._fields_column.height = needed

    def _sync_preview_backdrop(self, *_args) -> None:
        self._preview_backdrop_rect.pos = self._preview_scroll.pos
        self._preview_backdrop_rect.size = self._preview_scroll.size

    def _apply_pane_heights(self) -> None:
        self._body_row.height = self._pane_height
        self._fields_pane.height = self._pane_height
        tabs = float(self._tab_scroll.height)
        gap = float(self._fields_pane.spacing)
        self._fields_scroll.height = max(0.0, self._pane_height - tabs - gap)
        self._preview_column.height = self._pane_height
        title = float(self._preview_header.height)
        self._preview_scroll.height = max(0.0, self._pane_height - title)

    def _fixed_header_height(self) -> float:
        return dp(16 + 40 + 8)

    def _measure_editor_height(self) -> float:
        return self._fixed_header_height() + float(self._pane_height)

    def _content_panel(self):
        node = self.parent
        while node is not None:
            if isinstance(node, ContentPanel):
                return node
            node = node.parent
        return None

    def _panel_chrome(self) -> float:
        """Height the settings panel uses for its title, padding, and gaps."""
        panel = self.parent
        if not isinstance(panel, SettingsPanel):
            return 0.0
        title_height = 0.0
        for child in panel.children:
            if child is self:
                continue
            title_height = max(title_height, float(child.height))
        padding = panel.padding
        vertical_pad = float(padding[1]) + float(padding[3])
        spacing = panel.spacing
        gap = float(spacing[1] if isinstance(spacing, (list, tuple)) else spacing)
        gaps = max(0, len(panel.children) - 1) * gap
        return title_height + vertical_pad + gaps

    def _hook_viewport(self) -> None:
        """Follow the settings panel into the modal so the page can use its real height."""
        panel = self.parent if isinstance(self.parent, SettingsPanel) else None
        if panel is not None and not self._panel_hooks:
            panel.bind(height=self._sync_viewport_height, parent=self._on_panel_parent)
            self._panel_hooks = True
        scroll = self._content_panel()
        if scroll is not None and scroll is not self._viewport_scroll:
            if self._viewport_scroll is not None:
                self._viewport_scroll.unbind(height=self._sync_viewport_height)
            self._viewport_scroll = scroll
            scroll.bind(height=self._sync_viewport_height)

    def _viewport_height(self) -> float:
        # The panel height follows this page, so measure the modal scroller instead.
        scroll = self._content_panel()
        if scroll is not None and scroll.height > dp(120):
            return float(scroll.height)
        return 0.0

    def _sync_viewport_height(self, *_args) -> None:
        self._hook_viewport()
        viewport = self._viewport_height()
        # The scroller is not ready yet. Keep the minimum until the panel is attached.
        if viewport <= 0:
            return
        available = viewport - self._panel_chrome() - self._fixed_header_height()
        self._pane_height = max(MIN_PANE_HEIGHT, available)
        self._apply_pane_heights()
        self._editor_height = self._measure_editor_height()
        self._restore_editor_height(0)

    def _on_parent_changed(self, _instance, parent) -> None:
        if parent is not None:
            self._sync_viewport_height()

    def _on_panel_parent(self, _panel, parent) -> None:
        if parent is not None:
            self._sync_viewport_height()

    def _apply_pane_widths(self, width: float) -> None:
        show = preview_shown_for_width(width)
        self._preview_visible = show
        if show:
            self._fields_pane.size_hint_x = 1
            self._fields_pane.size_hint_min_x = fields_pane_width()
            self._preview_column.disabled = False
            self._preview_column.opacity = 1
            self._preview_column.size_hint_x = None
            self._preview_column.width = PREVIEW_PANE_WIDTH
            if self._preview_column.parent is None:
                self._body_row.add_widget(self._preview_column)
        else:
            self._preview_column.disabled = True
            self._preview_column.opacity = 0
            self._preview_column.size_hint_x = None
            self._preview_column.width = 0
            if self._preview_column.parent is not None:
                self._body_row.remove_widget(self._preview_column)
            self._fields_pane.size_hint_x = 1
            self._fields_pane.size_hint_min_x = None

    def _on_body_width(self, _row, width) -> None:
        if width <= 0:
            return
        self._apply_pane_widths(width)

    def _draft_color(self, key):
        return getattr(self.draft, key)

    def _keep_editor_height(self, _instance, height) -> None:
        if height != self._editor_height:
            Clock.schedule_once(self._restore_editor_height, 0)

    def _restore_editor_height(self, _dt) -> None:
        self.height = self._editor_height
        self._editor_layout.height = self._editor_height

    def _initial_name(self) -> str:
        names = [name for name, _title in list_themes()]
        current = str(self.value or "")
        if current in names:
            return current
        if DEFAULT_THEME in names:
            return DEFAULT_THEME
        return names[0]

    def _draft_is_dirty(self) -> bool:
        """True when the draft or a font field differs from the selected theme."""
        for key, baseline in self._baseline.items():
            current = getattr(self.draft, key)
            if isinstance(baseline, list):
                if format_hex_color(current) != format_hex_color(baseline):
                    return True
            elif current != baseline:
                return True
        for role, row in self._font_fields.items():
            text = row.spec()
            if role == "default":
                text = text or ARIALUNI
            baseline = self._baseline_fonts.get(role) or (ARIALUNI if role == "default" else "")
            if text != baseline:
                return True
        for key, row in self._behavior_fields.items():
            if bool(row.switch.active) != bool(self._baseline_behaviors.get(key)):
                return True
        return False

    def _on_draft_changed(self, *_args):
        if not self._loading:
            self.preview.refresh(self.draft)
            self._mark_pending()

    def _on_theme_text(self, _spinner, text):
        if self._loading:
            return
        name = self._title_to_name.get(text)
        if not name or name == self._selected:
            return
        # Choosing a palette drops unsaved edits. Apply stores the choice.
        self._load_form(name)

    def _on_external_value(self, _instance, value):
        """Reload when Cancel restores the snapshot. Ignore our own writes."""
        if self._syncing_value or self._loading:
            return
        name = str(value or "")
        if not name or name == self._selected:
            return
        self._load_form(name)

    def _on_font_choice(self, _field, _text) -> None:
        if self._loading or self._font_refresh:
            return
        self._font_refresh = True
        try:
            for row in self._font_fields.values():
                row.refresh(self.font_default_field)
            self._apply_font_fields()
            self._mark_pending()
        finally:
            self._font_refresh = False

    def _apply_font_fields(self) -> None:
        index = font_index()
        default = self.font_default_field.spec() or ARIALUNI
        self.draft.font_default = resolve_font(default, index)
        for role, row in self._font_fields.items():
            if role == "default":
                continue
            text = row.spec()
            setattr(self.draft, f"font_{role}", resolve_font(text or default, index))

    def _snapshot_baseline(self) -> None:
        self._baseline = {}
        for key in self._rows:
            value = getattr(self.draft, key)
            self._baseline[key] = list(value) if isinstance(value, list) else value
        specs = load_font_specs(self._selected)
        self._baseline_fonts = {
            role: (specs.get(role) or ARIALUNI) if role == "default" else (specs.get(role) or "")
            for role in self._font_fields
        }
        self._baseline_behaviors = {key: bool(load_behaviors(self._selected)[key]) for key in self._behavior_fields}

    def revert_token(self, key: str) -> None:
        """Reset one token on the draft to the selected theme's loaded baseline."""
        baseline = self._baseline.get(key)
        if baseline is None:
            return
        current = getattr(self.draft, key)
        if isinstance(baseline, list):
            if format_hex_color(current) == format_hex_color(baseline):
                return
        elif current == baseline:
            return
        patch = list(baseline) if isinstance(baseline, list) else baseline
        self.draft.apply({key: patch})
        row = self._rows.get(key)
        if row is not None:
            row.show(getattr(self.draft, key))

    def revert_font(self, role: str) -> None:
        """Reset one font role on the draft to the selected theme's loaded baseline."""
        baseline = self._baseline_fonts.get(role)
        if baseline is None:
            return
        field = self._font_fields.get(role)
        if field is None:
            return
        current_text = field.spec()
        if role == "default":
            current_text = current_text or ARIALUNI
        if current_text == baseline:
            return
        field.show(baseline, self.font_default_field)
        self._apply_font_fields()

    def _on_behavior(self, key: str, active: bool) -> None:
        if self._loading:
            return
        setattr(self.draft, key, bool(active))

    def revert_behavior(self, key: str) -> None:
        """Reset one behavior on the draft to the selected theme's loaded baseline."""
        if key not in self._baseline_behaviors:
            return
        row = self._behavior_fields.get(key)
        if row is None:
            return
        baseline = bool(self._baseline_behaviors[key])
        if bool(row.switch.active) == baseline:
            return
        row.switch.active = baseline

    def set_token(self, key, text) -> bool:
        """Apply one field to the draft when it parses. An invalid entry is left unchanged."""
        text = str(text).strip()
        current = getattr(self.draft, key)
        try:
            if isinstance(current, list):
                value = parse_hex_color(text)
                unchanged = format_hex_color(current) == format_hex_color(value)
            else:
                value = _parse_number(text)
                unchanged = current == value
        except (ThemeError, ValueError):
            return False
        if not unchanged:
            self.draft.apply({key: value})
        row = self._rows.get(key)
        if row is not None:
            row.paint(getattr(self.draft, key))
        return True

    def _load_form(self, name: str) -> None:
        self._loading = True
        try:
            self._selected = name
            self.draft.apply_palette(name)
            self._refresh_spinner()
            title = theme_title(name)
            if title in self._spinner.values:
                self._spinner.text = title
            for key, row in self._rows.items():
                row.show(getattr(self.draft, key))
            specs = load_font_specs(name)
            for role, row in self._font_fields.items():
                row.show(specs.get(role) or "", self.font_default_field)
            flags = load_behaviors(name)
            for key, row in self._behavior_fields.items():
                row.switch.active = bool(flags[key])
            self._snapshot_baseline()
            self.preview.refresh(self.draft)
        finally:
            self._loading = False
        self._mark_pending()

    def _refresh_spinner(self) -> None:
        self._title_to_name = {}
        titles = []
        for name, title in list_themes():
            shown = title if title not in self._title_to_name else f"{title} ({name})"
            self._title_to_name[shown] = name
            titles.append(shown)
        self._spinner.values = titles

    def _settings_root(self):
        """The running interface, when it tracks deferred settings."""
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        if root is None or not hasattr(root, "controller_setting_change_list"):
            return None
        if not hasattr(root, "setting_change_list"):
            return None
        return root

    def _refresh_apply(self, root) -> None:
        popup = getattr(root, "config_popup", None)
        button = getattr(popup, "btn_apply", None) if popup is not None else None
        if button is None:
            return
        pending = bool(root.controller_setting_change_list or root.setting_change_list)
        button.disabled = not pending

    def on_value(self, instance, value):
        """Keep the name on the widget. The settings file waits until the window exists.

        Startup can retarget a theme that failed to load while ``App.build()``
        is still running. Writing the setting then asks ``on_config_change``
        for a window Kivy has not assigned yet.
        """
        if self._settings_root() is None:
            return
        super().on_value(instance, value)

    def _assign_value(self, name: str) -> None:
        """Store ``name`` without treating the write as a Cancel restore."""
        if str(self.value or "") == str(name):
            return
        self._syncing_value = True
        try:
            self.value = name
        finally:
            self._syncing_value = False

    def _target_name(self) -> str:
        """Theme Apply should store: Custom when the draft differs, else the selection."""
        if self._draft_is_dirty():
            return CUSTOM_THEME
        return self._selected

    def _mark_pending(self) -> None:
        """Enable Apply when the selection or the draft differs from the opened theme.

        A dirty edit of the theme that is already selected keeps the same config
        value, so the settings panel would otherwise treat it as unchanged.
        """
        if self._loading:
            return
        target = self._target_name()
        self._assign_value(target)
        root = self._settings_root()
        if root is None or getattr(root, "config_loading", False):
            return
        if self._committing:
            root.controller_setting_change_list["theme"] = target
            self._refresh_apply(root)
            return
        if self._draft_is_dirty() and target == self._opened_name:
            root.controller_setting_change_list["theme"] = target
            self._refresh_apply(root)
        elif not self._draft_is_dirty() and target == self._opened_name:
            root.controller_setting_change_list.pop("theme", None)
            self._refresh_apply(root)

    def consume_force_reload(self) -> bool:
        """True when Apply must reload Custom because its file was just rewritten."""
        force = self._force_reload
        self._force_reload = False
        return force

    def commit_for_apply(self) -> None:
        """Write the draft as Custom when it differs from the selected theme.

        A clean selection only updates ``value``. The settings popup stores that
        name and switches the interface. A missing user-themes directory is logged
        and does not switch the selection to Custom.
        """
        if not self._draft_is_dirty():
            self._force_reload = False
            return
        directory = user_themes_dir()
        if directory is None:
            logger.warning("Cannot save a custom theme: user themes directory is not set")
            self._force_reload = False
            self._assign_value(self._opened_name)
            root = self._settings_root()
            if root is not None and not getattr(root, "config_loading", False):
                root.controller_setting_change_list.pop("theme", None)
                self._refresh_apply(root)
            return
        tokens = self.draft.to_dict()
        tokens.pop("name", None)
        document = custom_theme_document(
            tokens,
            {role: row.spec() for role, row in self._font_fields.items()},
            {key: bool(row.switch.active) for key, row in self._behavior_fields.items()},
            self._extends_to_save(),
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "custom.json"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        clear_theme_cache()
        self._force_reload = True
        self._committing = True
        try:
            self._opened_name = CUSTOM_THEME
            self._assign_value(CUSTOM_THEME)
            self._load_form(CUSTOM_THEME)
        finally:
            self._committing = False

    def finish_apply(self) -> None:
        """Remember the theme Apply just stored, so the next edit starts clean."""
        self._force_reload = False
        name = str(self.value or self._selected)
        self._opened_name = name
        if self._selected != name or self._draft_is_dirty():
            self._load_form(name)
        else:
            self._mark_pending()

    def revert_pending(self) -> None:
        """Drop the draft and show the theme that was open when editing started."""
        self._force_reload = False
        self._load_form(self._opened_name)
        root = self._settings_root()
        if root is None or getattr(root, "config_loading", False):
            return
        root.controller_setting_change_list.pop("theme", None)
        self._refresh_apply(root)

    def _extends_to_save(self) -> str | None:
        """Theme this Custom snapshot is based on.

        Editing a built-in records that theme. Editing Custom keeps the parent
        already stored in ``custom.json``.
        """
        if self._selected and self._selected != CUSTOM_THEME:
            return self._selected
        try:
            return theme_extends(CUSTOM_THEME)
        except ThemeError:
            return None

    def on_touch_down(self, touch):
        # SettingItem would grab the whole row. Inner buttons and fields need the click.
        return FloatLayout.on_touch_down(self, touch)

    def on_touch_up(self, touch):
        return FloatLayout.on_touch_up(self, touch)
