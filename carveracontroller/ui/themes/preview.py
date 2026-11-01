"""Live theme preview: samples painted from a draft, not from the applied theme."""

from __future__ import annotations

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from carveracontroller.addons.intellisense.engine import highlight_mdi_line
from carveracontroller.translation import tr
from carveracontroller.ui.themes import gcode_syntax_colors, jog_axis_markup

PREVIEW_PANE_WIDTH = dp(400)
PREVIEW_GAP = dp(12)
_CONTROL_HEIGHT = dp(32)
_PREVIEW_ICON = "data/cog.png"
_CLOSE_ICON = "data/close.png"
_RUN_ICON = "data/play.png"
_DELETE_ICON = "data/delete.png"
_ACTION_HEIGHT = dp(40)
JOG_PREVIEW_SIDE = dp(88)
_AXIS_LETTERS = ("X", "Y", "Z", "A")
_GCODE_PREVIEW_LINES = (
    "(Setup)",
    "T1 M6",
    "G17",
    "G0 Z5.000",
    "M3 S10000",
    "N20 G1 X10 F600",
    "G2 I1 J0",
    "O100 sub",
    "#100 gt 5",
)


class _Painted(BoxLayout):
    """A label on a flat fill. Built without Button or TextInput, which follow ``app.theme``."""

    def __init__(self, text, fill, foreground, font_name, border=None, width=None, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(dp(120) if width is None else width, _CONTROL_HEIGHT),
            **kwargs,
        )
        with self.canvas.before:
            self.border_color = Color(*(border if border is not None else (0, 0, 0, 0)))
            self.border_line = Line(width=dp(1))
            self.fill_color = Color(*fill)
            self.fill_rect = RoundedRectangle(radius=[dp(4)])
        self.plain = text
        self.label = Label(text=text, color=list(foreground), font_name=font_name, halign="center", valign="middle")
        self.label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        self.add_widget(self.label)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_args):
        inset = dp(1)
        self.fill_rect.pos = (self.x + inset, self.y + inset)
        self.fill_rect.size = (max(self.width - 2 * inset, 0), max(self.height - 2 * inset, 0))
        self.border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(4))


class _PaintedAction(BoxLayout):
    """Dialog footer button: a leading icon and the fill ``PopupActionButton`` paints."""

    def __init__(self, text, icon_source, role, theme, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint=(None, None),
            height=_ACTION_HEIGHT,
            padding=[dp(10), 0],
            spacing=dp(10),
            **kwargs,
        )
        self.role = role
        with self.canvas.before:
            self.fill_color = Color(1, 1, 1, 1)
            self.fill_rect = RoundedRectangle()
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self._icon = Image(
            source=icon_source,
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(None, None),
            size=(dp(20), dp(20)),
            pos_hint={"center_y": 0.5},
        )
        self.label = Label(
            text=text,
            font_name=theme.font_default,
            size_hint=(None, None),
            height=_ACTION_HEIGHT,
            halign="left",
            valign="middle",
        )
        self.label.bind(texture_size=self._fit_label)
        self.add_widget(self._icon)
        self.add_widget(self.label)
        self.paint(theme)

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size

    def _fit_label(self, *_args) -> None:
        width = float(self.label.texture_size[0])
        self.label.width = width
        self.label.text_size = (width, self.height)
        # PopupActionButton adds dp(50) around an icon: both insets, the glyph, and the trailing pad.
        self.width = width + dp(50)

    def paint(self, theme) -> None:
        self.fill_color.rgba = theme.button_fill(self.role, "normal", False, True)
        self.fill_rect.radius = [dp(theme.radius_m)]
        self.label.color = list(theme.button_text(self.role, "normal", False, True))
        self.label.font_name = theme.font_default
        self._icon.color = theme.icon_tint(self.role, "normal", False, True)


class _PaintedIcon(Widget):
    def __init__(self, icon_source, fill, foreground, border=None, **kwargs):
        super().__init__(size_hint=(None, None), size=(_CONTROL_HEIGHT, _CONTROL_HEIGHT), **kwargs)
        with self.canvas.before:
            self.border_color = Color(*(border if border is not None else (0, 0, 0, 0)))
            self.border_line = Line(width=dp(1))
            self.fill_color = Color(*fill)
            self.fill_rect = RoundedRectangle(radius=[dp(4)])
        self._icon = Image(
            source=icon_source,
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(None, None),
            size=(dp(18), dp(18)),
            color=list(foreground),
        )
        self.add_widget(self._icon)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self._sync_canvas()

    def _sync_canvas(self, *_args):
        inset = dp(1)
        self.fill_rect.pos = (self.x + inset, self.y + inset)
        self.fill_rect.size = (max(self.width - 2 * inset, 0), max(self.height - 2 * inset, 0))
        self.border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(4))
        self._icon.center = self.center


class _GcodePreviewRow(BoxLayout):
    def __init__(self, number, selected=False, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(22),
            spacing=dp(4),
            padding=[dp(4), 0],
            **kwargs,
        )
        self.selected = selected
        with self.canvas.before:
            self.fill_color = Color(1, 1, 1, 1)
            self.fill_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.number = Label(
            text=str(number),
            size_hint_x=None,
            width=dp(36),
            font_size=sp(12),
            halign="left",
            valign="middle",
        )
        self.number.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        self.code = Label(markup=True, font_size=sp(12), halign="left", valign="middle")
        self.code.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        self.add_widget(self.number)
        self.add_widget(self.code)

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size


class _GcodePreviewSample(BoxLayout):
    def __init__(self, theme, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(1), padding=dp(2), size_hint_y=None, **kwargs)
        with self.canvas.before:
            self.fill_color = Color(1, 1, 1, 1)
            self.fill_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas, minimum_height=self.setter("height"))
        self.rows = [_GcodePreviewRow(index, selected=index == 4) for index in range(1, len(_GCODE_PREVIEW_LINES) + 1)]
        for row in self.rows:
            self.add_widget(row)
        self.refresh(theme)

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size

    @property
    def text(self) -> str:
        return "\n".join(row.code.text for row in self.rows)

    def refresh(self, theme) -> None:
        colors = gcode_syntax_colors(theme)
        self.fill_color.rgba = theme.panel_inset
        for row, line in zip(self.rows, _GCODE_PREVIEW_LINES):
            row.fill_color.rgba = theme.gcode_list_element_selected if row.selected else theme.gcode_list_element
            row.number.color = list(theme.text_secondary)
            row.number.font_name = theme.font_code_list
            row.code.font_name = theme.font_code_list
            row.code.color = list(theme.text)
            row.code.text = highlight_mdi_line(line, colors)


class _AxisChip(BoxLayout):
    def __init__(self, letter, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint=(None, None),
            size=(dp(86), dp(48)),
            padding=(dp(4), dp(2)),
            spacing=dp(2),
            **kwargs,
        )
        with self.canvas.before:
            self.fill_color = Color(0, 0, 0, 0)
            self.fill_rect = RoundedRectangle(radius=[0])
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.letter = Label(text=letter, font_size=sp(18), size_hint_x=0.36, halign="center", valign="middle")
        self.letter.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        values = BoxLayout(orientation="vertical")
        self.value = Label(text="1.000", font_size=sp(13), halign="right", valign="middle")
        self.minor = Label(text="2.000", font_size=sp(10), halign="right", valign="middle")
        for label in (self.value, self.minor):
            label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        values.add_widget(self.value)
        values.add_widget(self.minor)
        self.add_widget(self.letter)
        self.add_widget(values)

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size

    def paint(self, fill, axis_color, text_color, muted, font_name, radius) -> None:
        self.fill_color.rgba = fill
        self.fill_rect.radius = [dp(radius)]
        self.letter.color = list(axis_color)
        self.letter.font_name = font_name
        self.value.color = list(text_color)
        self.value.font_name = font_name
        self.minor.color = list(muted)
        self.minor.font_name = font_name


class _SampleBar(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            padding=[dp(8), dp(4)],
            size_hint_y=None,
            height=dp(56),
            **kwargs,
        )
        with self.canvas.before:
            self.fill_color = Color(0, 0, 0, 0)
            self.fill_rect = RoundedRectangle(radius=[dp(8), dp(8), 0, 0])
            self.border_color = Color(0, 0, 0, 0)
            self.border_line = Line(points=[], width=dp(1))
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_args) -> None:
        self.fill_rect.pos = self.pos
        self.fill_rect.size = self.size
        self.border_line.points = [self.x, self.y, self.right, self.y]


class ThemePreview(BoxLayout):
    def __init__(self, theme, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=[0, dp(12), 0, dp(8)],
            spacing=dp(8),
            size_hint=(1, None),
            **kwargs,
        )
        with self.canvas.before:
            self.bg_color = Color(*theme.bg)
            self.bg_rect = Rectangle()
        self.backdrop_color = None
        self.bind(pos=self._sync_background, size=self._sync_background, minimum_height=self.setter("height"))
        self.bar = _SampleBar()
        self.axis_row = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            height=dp(48),
            spacing=dp(6),
            pos_hint={"center_y": 0.5},
        )
        self.axis_chips = [_AxisChip(letter) for letter in _AXIS_LETTERS]
        for chip in self.axis_chips:
            self.axis_row.add_widget(chip)
        self.axis_row.width = sum(chip.width for chip in self.axis_chips) + dp(6) * (len(self.axis_chips) - 1)
        self.bar.add_widget(self.axis_row)

        self.body = self._label(tr._("Body text"), theme.text, theme.font_default)
        self.muted = self._label(tr._("Muted"), theme.text_muted, theme.font_default)
        self.text_block = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(42), spacing=dp(2))
        self.text_block.add_widget(self.body)
        self.text_block.add_widget(self.muted)

        self.close_button = _PaintedAction(tr._("Close"), _CLOSE_ICON, "normal", theme)
        self.run_button = _PaintedAction(tr._("Run"), _RUN_ICON, "primary", theme)
        self.delete_button = _PaintedAction(tr._("Delete"), _DELETE_ICON, "danger", theme)
        icon_fill = theme.button_fill("normal", "normal", False, True)
        icon_tint = theme.icon_tint("normal", "normal", False, True)
        self.icon_button = _PaintedIcon(_PREVIEW_ICON, icon_fill, icon_tint, border=theme.border)
        self.icon_button.pos_hint = {"center_y": 0.5}
        self.actions = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            height=_ACTION_HEIGHT,
            spacing=dp(8),
        )
        for sample in (self.close_button, self.run_button, self.delete_button, self.icon_button):
            self.actions.add_widget(sample)
            sample.bind(width=self._fit_actions)
        self._fit_actions()

        jog_fill = theme.button_fill("normal", "normal", False, True)
        jog_text = theme.button_text("normal", "normal", False, True)
        self.jog_x = _Painted("X+", jog_fill, jog_text, theme.font_jog_pad, width=JOG_PREVIEW_SIDE)
        self.jog_y = _Painted("Y+", jog_fill, jog_text, theme.font_jog_pad, width=JOG_PREVIEW_SIDE)
        jog_font = min(sp(24), max(sp(16), JOG_PREVIEW_SIDE * 0.28))
        for key in (self.jog_x, self.jog_y):
            key.height = JOG_PREVIEW_SIDE
            key.label.font_size = jog_font
        self.jog_row = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            height=JOG_PREVIEW_SIDE,
            spacing=dp(8),
        )
        self.jog_row.add_widget(self.jog_x)
        self.jog_row.add_widget(self.jog_y)
        self.jog_row.width = JOG_PREVIEW_SIDE * 2 + dp(8)

        self.field = _Painted(
            "12.50",
            theme.field_bg,
            theme.text,
            theme.font_default,
            border=theme.border,
            width=dp(120),
        )
        self.gcode_sample = _GcodePreviewSample(theme)

        self._page = BoxLayout(
            orientation="vertical",
            padding=[dp(12), 0, dp(12), dp(4)],
            spacing=dp(10),
            size_hint_y=None,
        )
        self._page.add_widget(self.text_block)
        self._page.add_widget(self.actions)
        self._page.add_widget(self.jog_row)
        self._page.add_widget(self.field)
        self._page.add_widget(self.gcode_sample)
        self._page.bind(minimum_height=self._page.setter("height"))
        self.add_widget(self.bar)
        self.add_widget(self._page)
        self.refresh(theme)

    def _fit_actions(self, *_args) -> None:
        buttons = self.actions.children
        gaps = dp(8) * max(len(buttons) - 1, 0)
        self.actions.width = sum(button.width for button in buttons) + gaps

    @staticmethod
    def _label(text, color, font_name):
        label = Label(
            text=text,
            color=list(color),
            font_name=font_name,
            size_hint=(None, None),
            height=dp(20),
            halign="left",
            valign="middle",
        )
        label.bind(texture_size=lambda widget, size: setattr(widget, "width", size[0] + dp(2)))
        return label

    def _sync_background(self, *_args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def refresh(self, theme) -> None:
        self.bg_color.rgba = theme.bg
        if self.backdrop_color is not None:
            self.backdrop_color.rgba = theme.bg
        self.body.color = theme.text
        self.body.font_name = theme.font_default
        self.muted.color = theme.text_muted
        self.muted.font_name = theme.font_default
        for action in (self.close_button, self.run_button, self.delete_button):
            action.paint(theme)
        self.bar.fill_color.rgba = theme.bg
        self.bar.border_color.rgba = theme.border
        top_fill = theme.button_fill("normal", "normal", False, True)
        top_text = theme.button_text("normal", "normal", False, True)
        for letter, chip in zip(_AXIS_LETTERS, self.axis_chips):
            axis_color = getattr(theme, f"axis_{letter.lower()}")
            chip.paint(top_fill, axis_color, top_text, theme.text_muted, theme.font_top_bar, theme.top_bar_radius)
        for key in (self.jog_x, self.jog_y):
            key.fill_color.rgba = theme.jog_axis_fill(key.plain, "normal", False, True)
            key.label.color = list(theme.jog_axis_text(key.plain, "normal", False, True))
            key.label.font_name = theme.font_jog_pad
            key.fill_rect.radius = [dp(theme.pad_radius)]
            text, markup = jog_axis_markup(key.plain, theme)
            if markup:
                key.label.markup = True
                key.label.text = text
            else:
                key.label.text = key.plain
                key.label.markup = False
        self.icon_button.fill_color.rgba = theme.button_fill("normal", "normal", False, True)
        self.icon_button.border_color.rgba = theme.border
        self.icon_button._icon.color = theme.icon_tint("normal", "normal", False, True)
        self.field.fill_color.rgba = theme.field_bg
        self.field.border_color.rgba = theme.border
        self.field.label.color = theme.text
        self.field.label.font_name = theme.font_default
        self.gcode_sample.refresh(theme)
