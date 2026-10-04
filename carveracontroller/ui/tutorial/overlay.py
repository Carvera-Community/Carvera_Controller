"""Spotlight dimmer, banner, and step card."""

from __future__ import annotations

import webbrowser

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from carveracontroller.addons.tooltips.Tooltips import Tooltip, set_tooltips_suppressed
from carveracontroller.documentation import resolve_documentation_url
from carveracontroller.ui.common.action_button import PopupActionButton
from carveracontroller.ui.tutorial.placement import (
    BUTTON_ROW_H,
    Placement,
    Rect,
    merge_overlapping_holes,
    place_banner,
    place_card,
    spotlight_hole,
)
from carveracontroller.ui.tutorial.steps import TourStep

BANNER_TEXT = "Demo mode (not connected)"
DOCS_URL = "https://carvera-community.gitbook.io/docs"
ACCENT = (50 / 255, 164 / 255, 206 / 255, 1)
CARD_BG = (38 / 255, 40 / 255, 46 / 255, 1)
BANNER_BG = (14 / 255, 28 / 255, 36 / 255, 0.96)


class _Dimmer(Widget):
    """Dim the window, leaving one clear rectangle per target."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.holes: list[Rect] = []
        self.bind(pos=self._redraw, size=self._redraw)

    def set_holes(self, holes: list[Rect]) -> None:
        self.holes = holes
        self._redraw()

    def _redraw(self, *_args) -> None:
        self.canvas.before.clear()
        bounds = Rect(self.x, self.y, self.width, self.height)
        holes = [hole for hole in self.holes if hole.w > 1 and hole.h > 1]
        pieces = _subtract_holes(bounds, holes) if holes else [bounds]
        with self.canvas.before:
            Color(0, 0, 0, 0.55)
            for piece in pieces:
                Rectangle(pos=(piece.x, piece.y), size=(piece.w, piece.h))
            if not holes:
                return
            Color(*ACCENT)
            for hole in holes:
                Line(rectangle=(hole.x, hole.y, hole.w, hole.h), width=1.4)


class TourOverlay(FloatLayout):
    """Full-window layer. Touches outside the card are swallowed."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode = "welcome"
        self.step: TourStep | None = None
        self.index = 0
        self.count = 0
        self.banner_visible = False
        self._targets: list[Rect] = []
        self._target: Rect | None = None
        self._holes: list[Rect] = []
        self.on_skip = None
        self.on_back = None
        self.on_next = None
        self.on_show = None
        self.on_done = None
        self.on_usb = None
        self.on_wifi = None
        self.on_ip = None
        self.on_relayout = None
        self._bringing = False
        self._link_cursor = False
        self._cursor_unsupported = False
        self._reset_scroll = False
        Window.bind(mouse_pos=self._on_mouse_pos)
        self._applying = False

        self.dimmer = _Dimmer(size_hint=(1, 1))
        self.banner = Label(
            text=BANNER_TEXT,
            size_hint=(None, None),
            color=(0.85, 0.95, 1, 1),
            bold=True,
            font_size=dp(15),
            halign="center",
            valign="middle",
        )
        with self.banner.canvas.before:
            Color(*BANNER_BG)
            self._banner_bg = Rectangle()
        self.banner.bind(pos=self._sync_banner_bg, size=self._sync_banner_bg)

        self.card = BoxLayout(
            orientation="vertical",
            padding=(dp(18), dp(16), dp(18), dp(16)),
            spacing=dp(12),
            size_hint=(None, None),
        )
        with self.card.canvas.before:
            Color(*CARD_BG)
            self._card_bg = RoundedRectangle(radius=[dp(8), dp(8), dp(8), dp(8)])
            Color(*ACCENT)
            self._card_accent = Rectangle()
        self.card.bind(pos=self._sync_card_bg, size=self._sync_card_bg)

        self.header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(10))
        self.step_icon = Image(
            size_hint=(None, None),
            size=(dp(26), dp(26)),
            fit_mode="contain",
            pos_hint={"center_y": 0.5},
        )
        self.title = Label(
            text="",
            bold=True,
            font_size=dp(18),
            color=(1, 1, 1, 1),
            halign="left",
            valign="middle",
        )
        self.title.bind(size=self._sync_title_text_size)
        self.counter = Label(
            text="",
            size_hint_x=None,
            width=dp(64),
            font_size=dp(14),
            color=(0.7, 0.8, 0.86, 1),
            halign="right",
            valign="middle",
        )
        self.counter.bind(size=self._sync_counter_text_size)
        self.header.add_widget(self.step_icon)
        self.header.add_widget(self.title)
        self.header.add_widget(self.counter)

        self.body = Label(
            text="",
            size_hint=(None, None),
            width=dp(420),
            font_size=dp(16),
            color=(0.92, 0.93, 0.95, 1),
            halign="left",
            valign="top",
        )
        self.body.text_size = (self.body.width, None)
        self.body.bind(texture_size=self._body_height)
        self.body_scroll = ScrollView(do_scroll_x=False, bar_width=dp(6), size_hint_y=1)
        self.body_scroll.add_widget(self.body)
        self.body_scroll.bind(size=self._sync_body_width)
        self.extra = BoxLayout(orientation="vertical", size_hint_y=None, height=0, spacing=dp(8))
        self.buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(BUTTON_ROW_H),
            spacing=dp(8),
        )

        self.card.add_widget(self.header)
        self.card.add_widget(self.body_scroll)
        self.card.add_widget(self.extra)
        self.card.add_widget(self.buttons)

        self.add_widget(self.dimmer)
        self.add_widget(self.banner)
        self.add_widget(self.card)
        self.bind(size=self._on_overlay_size)

    def open(self) -> None:
        set_tooltips_suppressed(True)
        _dismiss_tooltips()
        if self.parent is None:
            self.size = Window.size
            Window.add_widget(self)

    def close(self) -> None:
        set_tooltips_suppressed(False)
        self._set_link_cursor(False)
        if self.parent is not None:
            self.parent.remove_widget(self)

    def bring_to_front(self) -> None:
        parent = self.parent
        if parent is None or self._bringing:
            return
        children = getattr(parent, "children", None)
        if children and children[0] is self:
            return
        self._bringing = True
        try:
            parent.remove_widget(self)
            parent.add_widget(self)
        finally:
            self._bringing = False

    def show_welcome(self) -> None:
        self.mode = "welcome"
        self.step = None
        self.banner_visible = False
        self._targets = []
        self._target = None
        self._holes = []
        self._set_icon("data/hand-wave.png")
        self.title.text = "Welcome to the Community Controller!"
        self.counter.text = ""
        self.counter.width = 0
        self.body.markup = True
        self.body.text = (
            "This short tour will guide you through the basic controls "
            "of the controller using simulated data.\n\n"
            "Feel free to skip it if you already know the workflow.\n"
            "You will also be able to access the tour again from the help menu later.\n\n"
            "If you need more information our documentation is available at "
            f"[ref={DOCS_URL}][color=#32a4ce][u]{DOCS_URL}[/u][/color][/ref]"
        )
        self._rebuild_buttons()
        self._reset_scroll = True
        self._scroll_body_to_top()
        self.layout_target(None)

    def show_step(self, step: TourStep, index: int, count: int) -> None:
        self.mode = "step"
        self.step = step
        self.index = index
        self.count = count
        self.banner_visible = True
        self.card.opacity = 0
        self._set_icon(step.icon)
        self.counter.width = dp(64)
        self.title.text = step.title
        self.counter.text = f"{index + 1} / {count}"
        self.body.markup = False
        self.body.text = step.body
        self._reset_scroll = True
        self._scroll_body_to_top()
        self._rebuild_buttons()

    def layout_target(self, target: Rect | None) -> None:
        self.layout_targets([] if target is None else [target])

    def layout_targets(self, targets: list[Rect]) -> None:
        self._targets = list(targets)
        self._target = _union(self._targets) if self._targets else None
        self._apply_layout()
        self.card.opacity = 1

    def on_touch_down(self, touch):
        if self._open_body_link(touch.pos):
            return True
        if self.card.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        if self.card.collide_point(*touch.pos):
            return super().on_touch_move(touch)
        return True

    def on_touch_up(self, touch):
        if self.card.collide_point(*touch.pos):
            return super().on_touch_up(touch)
        return True

    def _on_overlay_size(self, *_args) -> None:
        if self._bringing or self._applying:
            return
        if self.on_relayout is not None and self.mode == "step":
            self.on_relayout()
        else:
            self._apply_layout()

    def _apply_layout(self) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            self._apply_layout_body()
        finally:
            self._applying = False

    def _apply_layout_body(self) -> None:
        app = App.get_running_app()
        safe = (0.0, 0.0, 0.0, 0.0)
        if app is not None:
            padding = getattr(app, "safe_area_padding", None) or (0, 0, 0, 0)
            safe = (float(padding[0]), float(padding[1]), float(padding[2]), float(padding[3]))
        window_w = float(self.width or Window.width)
        window_h = float(self.height or Window.height)
        self._holes = [
            spotlight_hole(rect, window_width=window_w, window_height=window_h, min_size=float(dp(28)))
            for rect in self._targets
        ]
        hole = (
            spotlight_hole(self._target, window_width=window_w, window_height=window_h, min_size=float(dp(28)))
            if self._target is not None
            else None
        )
        banner_h = float(dp(36)) if self.banner_visible else 0.0
        card_safe = safe
        if banner_h:
            banner = place_banner(window_w, window_h, safe, hole, banner_h)
            self.banner.opacity = 1
            self.banner.size = (banner.w, banner.h)
            self.banner.pos = (banner.x, banner.y)
            if banner.y > window_h / 2.0:
                card_safe = (safe[0], safe[1] + banner_h, safe[2], safe[3])
            else:
                card_safe = (safe[0], safe[1], safe[2], safe[3] + banner_h)
        else:
            self.banner.opacity = 0
            self.banner.size = (0, 0)
        pref_w = min(float(dp(520)), max(float(dp(380)), window_w * 0.36))
        pref_h = min(float(dp(320)), max(float(dp(260)), window_h * 0.38))
        # Header, padding, the three gaps around the empty extra row, buttons,
        # and about three lines of body. Density scaling grows this with the type.
        button_h = float(dp(BUTTON_ROW_H))
        min_h = float(dp(16) * 2 + dp(12) * 3 + dp(36)) + button_h + float(dp(72))
        min_w = float(dp(280))
        placement = place_card(
            window_width=window_w,
            window_height=window_h,
            safe=card_safe,
            target=self._target,
            holes=tuple(self._holes),
            preferred_size=(pref_w, pref_h),
            min_size=(min_w, min_h),
            margin=float(dp(12)),
            gap=float(dp(12)),
            compact_width=float(dp(720)),
            short_height=float(dp(640)),
            min_hole=float(dp(28)),
        )
        self._apply_placement(placement)

    def _apply_placement(self, placement: Placement) -> None:
        self.dimmer.set_holes(merge_overlapping_holes(self._holes))
        card = placement.card
        self.card.size = (max(card.w, 1), max(card.h, 1))
        self.card.pos = (card.x, card.y)
        self.buttons.height = min(float(self.card.height), float(dp(BUTTON_ROW_H)))
        self._sync_body_width()
        if self._reset_scroll:
            self._reset_scroll = False
            self._scroll_body_to_top()
            # The label height follows the texture on the next frame. Reset again
            # after that, or a step opened at the bottom stays there.
            Clock.schedule_once(self._scroll_body_to_top, 0)

    def _rebuild_buttons(self) -> None:
        self.buttons.clear_widgets()
        self.extra.clear_widgets()
        self.extra.height = 0
        if self.mode == "welcome":
            self.buttons.add_widget(self._button("Show me around", self.on_show, "data/eye.png", primary=True))
            self.buttons.add_widget(self._button("Skip", self.on_skip, "data/close.png"))
            return
        step = self.step
        self.buttons.add_widget(self._button("Back", self.on_back, "data/back.png", disabled=self.index <= 0))
        if step is not None and step.kind == "connect":
            self._add_connect_actions()
            self.buttons.add_widget(self._button("Done", self.on_done, "data/check.png", primary=True))
            return
        self.buttons.add_widget(self._button("Next", self.on_next, "data/forward.png", primary=True))
        self.buttons.add_widget(self._button("Skip", self.on_skip, "data/close.png"))

    def _add_connect_actions(self) -> None:
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        row.add_widget(self._button("USB", self.on_usb, "data/link-variant.png"))
        row.add_widget(self._button("Scan Wi-Fi", self.on_wifi, "data/WIFI.png"))
        row.add_widget(self._button("Enter IP", self.on_ip, "data/pencil.png"))
        self.extra.add_widget(row)
        self.extra.height = dp(44)

    def _button(self, text: str, handler, icon: str = "", primary: bool = False, disabled: bool = False):
        button = PopupActionButton(btn_text=text, icon=icon, flat=True, primary=primary, disabled=disabled)
        if handler is not None:
            button.bind(on_release=lambda *_a, handler=handler: handler())
        return button

    def _set_icon(self, source: str) -> None:
        self.step_icon.source = source or ""
        if source:
            self.step_icon.size = (dp(26), dp(26))
            self.step_icon.opacity = 1
        else:
            self.step_icon.size = (0, 0)
            self.step_icon.opacity = 0

    def _sync_card_bg(self, *_args) -> None:
        self._card_bg.pos = self.card.pos
        self._card_bg.size = self.card.size
        accent_h = float(dp(3))
        self._card_accent.pos = (self.card.x, self.card.top - accent_h)
        self._card_accent.size = (self.card.width, accent_h)

    def _sync_banner_bg(self, *_args) -> None:
        self._banner_bg.pos = self.banner.pos
        self._banner_bg.size = self.banner.size
        self.banner.text_size = self.banner.size

    def _sync_title_text_size(self, instance, size) -> None:
        instance.text_size = size

    def _sync_counter_text_size(self, instance, size) -> None:
        instance.text_size = size

    def _scroll_body_to_top(self, *_args) -> None:
        scroll = self.body_scroll
        effect = scroll.effect_y
        if effect is not None:
            # A flick still in motion would pull the next step back down.
            effect.velocity = 0
            effect.is_manual = False
        scroll.scroll_y = 1
        scroll._update_effect_y_bounds()

    def _sync_body_width(self, *_args) -> None:
        # Keep the wrap width independent of the scrollbar, or the bar appearing
        # changes the wrap, which changes the height, which toggles the bar.
        width = max(1.0, float(self.body_scroll.width) - float(self.body_scroll.bar_width))
        if abs(float(self.body.width) - width) > 0.5:
            self.body.width = width
        self.body.text_size = (self.body.width, None)

    def _on_mouse_pos(self, _window, pos) -> None:
        self._set_link_cursor(self._body_ref_at(pos) is not None)

    def _set_link_cursor(self, link: bool) -> None:
        if link == self._link_cursor or self._cursor_unsupported:
            return
        self._link_cursor = link
        try:
            Window.set_system_cursor("hand" if link else "arrow")
        except Exception:
            self._cursor_unsupported = True

    def _open_body_link(self, pos) -> bool:
        ref = self._body_ref_at(pos)
        if not ref:
            return False
        webbrowser.open(resolve_documentation_url(ref), new=2)
        return True

    def _body_ref_at(self, pos) -> str | None:
        label = self.body
        refs = getattr(label, "refs", None)
        texture = label.texture_size
        if self.parent is None or not label.markup or not refs or not texture[0] or not texture[1]:
            return None
        # Ref boxes are relative to the top-left of the texture. The label sits
        # in a scroll view, so widget.pos is not its on-screen position.
        tw = float(texture[0])
        th = float(texture[1])
        cx, cy = label.center
        px, py = float(pos[0]), float(pos[1])
        for ref, zones in refs.items():
            for left, top, right, bottom in zones:
                x1 = cx - tw * 0.5 + float(left)
                x2 = cx - tw * 0.5 + float(right)
                y1 = cy + th * 0.5 - float(bottom)
                y2 = cy + th * 0.5 - float(top)
                wx1, wy1 = label.to_window(x1, y1)
                wx2, wy2 = label.to_window(x2, y2)
                if min(wx1, wx2) - 2 <= px <= max(wx1, wx2) + 2 and min(wy1, wy2) - 2 <= py <= max(wy1, wy2) + 2:
                    return str(ref)
        return None

    def _body_height(self, instance, texture_size) -> None:
        height = float(texture_size[1])
        if abs(float(instance.height) - height) > 0.5:
            instance.height = height


def _dismiss_tooltips() -> None:
    for child in list(Window.children):
        if isinstance(child, Tooltip):
            Window.remove_widget(child)


def _union(rects: list[Rect]) -> Rect:
    x0 = min(rect.x for rect in rects)
    y0 = min(rect.y for rect in rects)
    x1 = max(rect.right() for rect in rects)
    y1 = max(rect.top() for rect in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _subtract_holes(bounds: Rect, holes: list[Rect]) -> list[Rect]:
    pieces = [bounds]
    for hole in holes:
        remaining: list[Rect] = []
        for piece in pieces:
            remaining.extend(_subtract_one(piece, hole))
        pieces = remaining
    return pieces


def _subtract_one(rect: Rect, hole: Rect) -> list[Rect]:
    if rect.w <= 0.5 or rect.h <= 0.5:
        return []
    if hole.right() <= rect.x or rect.right() <= hole.x or hole.top() <= rect.y or rect.top() <= hole.y:
        return [rect]
    pieces: list[Rect] = []
    if hole.y > rect.y:
        pieces.append(Rect(rect.x, rect.y, rect.w, hole.y - rect.y))
    hole_top = hole.top()
    if hole_top < rect.top():
        pieces.append(Rect(rect.x, hole_top, rect.w, rect.top() - hole_top))
    band_y = max(rect.y, hole.y)
    band_h = min(rect.top(), hole.top()) - band_y
    if band_h > 0.5:
        if hole.x > rect.x:
            pieces.append(Rect(rect.x, band_y, min(hole.x, rect.right()) - rect.x, band_h))
        hole_right = hole.right()
        if hole_right < rect.right():
            x = max(hole_right, rect.x)
            pieces.append(Rect(x, band_y, rect.right() - x, band_h))
    return [piece for piece in pieces if piece.w > 0.5 and piece.h > 0.5]
