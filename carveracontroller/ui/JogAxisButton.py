"""Jog keys whose caption can color the axis letter.

``JogAxisButton`` is the plain key. ``JogAxisTipButton`` is the same key with
an axis-motion tooltip; the control page uses it for X, Y, and A.
"""

from kivy.properties import StringProperty
from kivy.uix.button import Button

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
from carveracontroller.ui.theme import get_theme, watch_theme
from carveracontroller.ui.themes import jog_axis_markup


def _show_jog_axis_caption(widget, caption: str, theme) -> None:
    """Show ``caption`` on ``widget``, coloring only the axis letter when asked.

    A color tag would keep the letter in the axis color, so the coloring is
    applied only while the key is enabled. A disabled pad paints ``disabled_color``.
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
    """Jog key. ``axis_label`` is the caption; the letter is colored when that behavior is on."""

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
