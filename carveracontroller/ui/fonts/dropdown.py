"""Theme font controls.

A family opens a search list, because a machine can have hundreds of families.
Weight and style stay short dropdowns: a family only has a few faces.
"""

from __future__ import annotations

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput

from carveracontroller.translation import tr
from carveracontroller.ui.fonts.fonts import ARIALUNI
from carveracontroller.ui.theme import get_theme

_CONTROL_HEIGHT = dp(32)
_ROW_HEIGHT = dp(36)


def _font_query(text: str) -> str:
    """Family search key. Spaces, underscores, and hyphens are ignored."""
    return "".join(char for char in text.casefold() if char not in " _-")


def matching_font_families(families, query: str) -> list[str]:
    """Families whose name contains ``query``, in the original order."""
    needle = _font_query(query)
    names = [str(name) for name in families]
    if not needle:
        return names
    return [name for name in names if needle in _font_query(name)]


class _FontDropDown(DropDown):
    """Face list tall enough to scroll instead of covering the settings page."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_height = dp(320)


class _FontOption(SpinnerOption):
    def __init__(self, **kwargs):
        super().__init__(font_name=ARIALUNI, shorten=True, shorten_from="right", **kwargs)


class FontFaceChoice(Spinner):
    """Closed weight or style. The open list is only the faces of one family."""

    def __init__(self, **kwargs):
        super().__init__(
            font_name=ARIALUNI,
            shorten=True,
            shorten_from="right",
            halign="left",
            valign="middle",
            sync_height=True,
            option_cls=_FontOption,
            dropdown_cls=_FontDropDown,
            **kwargs,
        )
        self.bind(size=self._align_text)

    def _align_text(self, *_args) -> None:
        self.text_size = (max(0.0, self.width - dp(16)), self.height)


class _FontFamilyOption(RecycleDataViewBehavior, Label):
    """One family name. A drag still scrolls the list."""

    chosen = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(
            font_name=ARIALUNI,
            shorten=True,
            shorten_from="right",
            halign="left",
            valign="middle",
            **kwargs,
        )
        with self.canvas.before:
            self._fill = Color(0, 0, 0, 0)
            self._rect = Rectangle()
        self.bind(pos=self._place, size=self._place, chosen=self._paint)

    def _place(self, *_args) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size
        self.text_size = (max(0.0, self.width - dp(16)), self.height)
        self._paint()

    def _paint(self, *_args) -> None:
        theme = get_theme()
        self.color = list(theme.text)
        if self.chosen:
            color = list(theme.accent)
            color[3] = 0.28
            self._fill.rgba = color
        else:
            self._fill.rgba = (0, 0, 0, 0)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        result = super().refresh_view_attrs(rv, index, data)
        self._paint()
        return result

    def on_touch_down(self, touch):
        if "button" in touch.profile and str(touch.button).startswith("scroll"):
            return super().on_touch_down(touch)
        if self.collide_point(*touch.pos):
            touch.ud["font_family_pick"] = (self.text, touch.pos)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        remembered = touch.ud.get("font_family_pick")
        if remembered and self.collide_point(*touch.pos):
            name, start = remembered
            moved = abs(touch.x - start[0]) > dp(8) or abs(touch.y - start[1]) > dp(8)
            recycle = getattr(self.parent, "recycleview", None)
            if name == self.text and not moved and recycle is not None:
                recycle.dispatch("on_choose", self.text)
                return True
        return super().on_touch_up(touch)


class _FontFamilyList(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_choose")
        layout = RecycleBoxLayout(
            default_size=(None, _ROW_HEIGHT),
            default_size_hint=(1, None),
            size_hint_y=None,
            orientation="vertical",
            spacing=dp(2),
        )
        layout.bind(minimum_height=layout.setter("height"))
        self.add_widget(layout)
        # viewclass is stored on the layout. Setting it earlier is ignored.
        self.viewclass = _FontFamilyOption

    def on_choose(self, _name) -> None:
        pass


class _FontFamilyPopup(Popup):
    """Search field over the installed families. Only visible rows are built."""

    def __init__(self, families, current, on_choose, **kwargs):
        self._families = list(families)
        self._current = current
        self._on_choose = on_choose
        root = BoxLayout(orientation="vertical", spacing=dp(6))
        self.search = TextInput(
            multiline=False,
            write_tab=False,
            hint_text=tr._("Search fonts"),
            font_name=ARIALUNI,
            size_hint_y=None,
            height=_CONTROL_HEIGHT,
            padding=[dp(8), dp(8)],
        )
        self.search.bind(text=self._on_query, on_text_validate=self._choose_first)
        self.count = Label(
            font_name=ARIALUNI,
            font_size=sp(12),
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle",
        )
        self.count.bind(size=self._align_count)
        self.list = _FontFamilyList()
        self.empty = Label(
            text=tr._("No matching fonts"),
            font_name=ARIALUNI,
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        root.add_widget(self.search)
        root.add_widget(self.count)
        root.add_widget(self.list)
        root.add_widget(self.empty)
        super().__init__(
            title=tr._("Choose a font"),
            content=root,
            size_hint=(None, None),
            size=(
                min(dp(440), max(dp(280), Window.width - dp(24))),
                min(dp(520), max(dp(320), Window.height - dp(24))),
            ),
            **kwargs,
        )
        self.list.bind(on_choose=self._choose)
        self._apply_query("")
        self.bind(on_open=self._focus_search)

    def _align_count(self, label, size) -> None:
        label.text_size = size
        label.color = list(get_theme().text_muted)

    def _focus_search(self, *_args) -> None:
        self.search.focus = True
        Clock.schedule_once(self._scroll_to_current, 0)

    def _on_query(self, _field, text) -> None:
        self._apply_query(text)
        self.list.scroll_y = 1

    def _apply_query(self, text) -> None:
        matches = matching_font_families(self._families, text)
        self.list.data = [{"text": name, "chosen": name == self._current} for name in matches]
        if _font_query(text):
            self.count.text = tr._("{} matches").format(len(matches))
        else:
            self.count.text = tr._("{} fonts").format(len(self._families))
        self.empty.opacity = 0 if matches else 1
        self.empty.height = 0 if matches else _CONTROL_HEIGHT

    def _scroll_to_current(self, *_args) -> None:
        if _font_query(self.search.text) or not self._current:
            return
        names = [row["text"] for row in self.list.data]
        if self._current not in names:
            return
        index = names.index(self._current)
        row = _ROW_HEIGHT + dp(2)
        content = len(names) * row
        view = float(self.list.height)
        if content <= view or view <= 0:
            self.list.scroll_y = 1
            return
        offset = min(max(0.0, index * row - view * 0.3), content - view)
        self.list.scroll_y = 1 - offset / (content - view)

    def _choose_first(self, *_args) -> None:
        if not _font_query(self.search.text) or not self.list.data:
            return
        self._choose(self.list, self.list.data[0]["text"])

    def _choose(self, _list, name) -> None:
        self._on_choose(name)
        self.dismiss(animation=False)


class FontFamilyField(Button):
    """Chosen family. Opening it searches the list instead of listing every font."""

    values = ListProperty([])

    def __init__(self, **kwargs):
        self._popup = None
        super().__init__(
            font_name=ARIALUNI,
            shorten=True,
            shorten_from="right",
            halign="left",
            valign="middle",
            **kwargs,
        )
        self.bind(size=self._align_text, on_release=self._open)

    def _align_text(self, *_args) -> None:
        self.text_size = (max(0.0, self.width - dp(16)), self.height)

    def _open(self, *_args) -> None:
        if self._popup is not None:
            self._popup.dismiss()
        self._popup = _FontFamilyPopup(self.values, self.text, self._choose)
        self._popup.open(animation=False)

    def _choose(self, name) -> None:
        self.text = name
