"""Jog keys whose caption and face can follow the axis color.

``JogAxisButton`` is the plain key. ``JogAxisTipButton`` is the same key with
an axis-motion tooltip; the control page uses it for X, Y, and A.
"""

from kivy.properties import StringProperty
from kivy.uix.button import Button

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
from carveracontroller.ui.theme import get_theme, watch_theme
from carveracontroller.ui.themes import jog_axis_markup


def _show_jog_axis_caption(widget, caption: str, theme) -> None:
    """Show ``caption`` on ``widget``, coloring the letter and sign when asked.

    A color tag would keep those glyphs in the axis color, so the coloring is
    applied only while the key is enabled. A disabled pad paints ``disabled_color``.
    The axis-background behavior leaves the caption plain; the key face carries the color.
    """
    if widget.disabled:
        text, markup = caption, False
    else:
        text, markup = jog_axis_markup(caption, theme)
    if markup:
        widget.markup = True
        widget.text = text
        return
    widget.text = text
    widget.markup = False


def _refresh_jog_axis_label(widget, *_args) -> None:
    _show_jog_axis_caption(widget, widget.axis_label, get_theme())


def _bind_jog_axis_label(widget) -> None:
    widget.bind(axis_label=_refresh_jog_axis_label, disabled=_refresh_jog_axis_label)
    watch_theme(lambda _theme: _refresh_jog_axis_label(widget))


class JogAxisButton(Button):
    """Jog key. ``axis_label`` is the caption; axis behaviors color the letter, the sign, or the face."""

    axis_label = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bind_jog_axis_label(self)


class JogAxisTipButton(ToolTipButton):
    """Jog key that can show an axis-motion tooltip."""

    axis_label = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bind_jog_axis_label(self)
