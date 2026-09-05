import sys
import webbrowser

from kivy.app import App
from kivy.clock import Clock
from kivy.compat import string_types
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput

# Minimum tooltip box width for short labels (matches previous wrap floor).
TOOLTIP_MIN_WIDTH = 200
# Wrap long tooltip text at this width so multi-line content stays readable.
TOOLTIP_MAX_WIDTH = 360


def is_blocked_by_modal(widget=None):
    """True when a Popup or ModalView is on the Window and widget is not inside it."""
    try:
        children = Window.children
    except Exception:
        return False
    for child in children:
        if not isinstance(child, (Popup, ModalView)):
            continue
        if widget is None:
            return True
        try:
            current = widget
            depth = 0
            while current is not None and depth < 20:
                if current is child:
                    return False
                current = getattr(current, "parent", None)
                depth += 1
            return True
        except Exception:
            return True
    return False


def _compute_tooltip_box_size(
    text_width, text_height, image_width, image_height, *, has_text, has_image, horizontal, spacing=15
):
    """Return (width, height) for a tooltip given content metrics and layout."""
    pad = 20
    if horizontal and has_image:
        gap = spacing if has_text else 0
        width = text_width + image_width + pad + gap
        if has_text:
            width = max(width, TOOLTIP_MIN_WIDTH + pad)
        height = max(text_height, image_height) + pad
        return width, height

    width = max(text_width + pad, image_width + pad, TOOLTIP_MIN_WIDTH + pad if has_text else 0)
    height = text_height + image_height + pad
    return width, height


class Tooltip(BoxLayout):
    pass


class ToolTipContentLabel(Label):
    """Tooltip text label that sizes to content, wrapping only when needed."""

    min_width = TOOLTIP_MIN_WIDTH
    max_width = TOOLTIP_MAX_WIDTH

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text_size = (None, None)

    def on_text(self, *args):
        self.refresh_text_size()

    def refresh_text_size(self):
        """Size to the longest line, wrapping only when past max_width."""
        if not self.text:
            self.text_size = (None, None)
            return

        # Measure natural (unwrapped) width first.
        self.text_size = (None, None)
        self.texture_update()
        natural_width = self.texture_size[0]

        if natural_width > self.max_width:
            self.text_size = (self.max_width, None)
            self.texture_update()


class ToolTipSwitch(Switch):
    tooltip_txt = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty("")
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        self._tooltip = None
        super().__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == "ios":
            return
        fbind = self.fbind
        fbind("tooltip_cls", self._build_tooltip)
        fbind("tooltip_txt", self._update_tooltip)
        fbind("tooltip_image", self._update_image)
        fbind("tooltip_image_size", self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()

    def _is_blocked_by_modal(self):
        return is_blocked_by_modal(self)

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ""
            self._tooltip.ids.tooltip_label.size = (0, 0)

        self._update_tooltip_size()

    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ""
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, *_args):
        if not self._tooltip:
            return

        tooltip_image = self._tooltip.ids.tooltip_image
        if self.tooltip_image_size:
            tooltip_image.size = self.tooltip_image_size
        elif self.tooltip_image:
            tooltip_image.size = tooltip_image.texture_size
        else:
            tooltip_image.size = (0, 0)

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        # Keep a stable minimum width for short labels; long text can grow up to max wrap.
        new_width = max(text_width + 20, image_width + 20, TOOLTIP_MIN_WIDTH + 20 if tooltip_label.text else 0)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return

        if not self.get_root_window():
            self.close_tooltip()
            return

        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return

        if self.disabled:
            self.close_tooltip()
            return

        if self._is_blocked_by_modal():
            self.close_tooltip()
            return

        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width, TOOLTIP_MIN_WIDTH if self.tooltip_txt else 0)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def close_tooltip(self, *args):
        if self._tooltip:  # for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipTextInput(TextInput):
    tooltip_txt = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty("")
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        self._tooltip = None
        super().__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == "ios":
            return
        fbind = self.fbind
        fbind("tooltip_cls", self._build_tooltip)
        fbind("tooltip_txt", self._update_tooltip)
        fbind("tooltip_image", self._update_image)
        fbind("tooltip_image_size", self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()

    def on_input_focus(self, instance, value):
        if value:
            App.get_running_app().root.toggle_keyboard_jog_control(True)

    def _is_blocked_by_modal(self):
        return is_blocked_by_modal(self)

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ""
            self._tooltip.ids.tooltip_label.size = (0, 0)

        self._update_tooltip_size()

    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ""
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, *_args):
        if not self._tooltip:
            return

        tooltip_image = self._tooltip.ids.tooltip_image
        if self.tooltip_image_size:
            tooltip_image.size = self.tooltip_image_size
        elif self.tooltip_image:
            tooltip_image.size = tooltip_image.texture_size
        else:
            tooltip_image.size = (0, 0)

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        # Keep a stable minimum width for short labels; long text can grow up to max wrap.
        new_width = max(text_width + 20, image_width + 20, TOOLTIP_MIN_WIDTH + 20 if tooltip_label.text else 0)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return

        if not self.get_root_window():
            self.close_tooltip()
            return

        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return

        if self.disabled:
            self.close_tooltip()
            return

        if self._is_blocked_by_modal():
            self.close_tooltip()
            return

        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width, TOOLTIP_MIN_WIDTH if self.tooltip_txt else 0)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def close_tooltip(self, *args):
        if self._tooltip:  # for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipButton(Button):
    tooltip_txt = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty("")
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None, allownone=True)
    # Optional generated texture (e.g. tool silhouettes). Takes precedence over
    # tooltip_image when set.
    tooltip_texture = ObjectProperty(None, allownone=True)
    # Optional callable invoked on first hover to defer CPU rasterization.
    # Must return ``(texture, display_size)`` where ``display_size`` is the
    # intended Image size in display pixels (a supersampled texture may be
    # larger than that; do not use texture.size for layout).
    tooltip_texture_provider = ObjectProperty(None, allownone=True)
    tooltip_radius = NumericProperty(0.2)
    tooltip_horizontal = BooleanProperty(False)
    tooltip_markup = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._tooltip = None
        self._hover_pos = None
        super().__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == "ios":
            return
        fbind = self.fbind
        fbind("tooltip_cls", self._build_tooltip)
        fbind("tooltip_txt", self._update_tooltip)
        fbind("tooltip_image", self._update_image)
        fbind("tooltip_texture", self._update_image)
        fbind("tooltip_image_size", self._update_image_size)
        fbind("tooltip_horizontal", self._update_tooltip_layout)
        fbind("tooltip_markup", self._update_tooltip_markup)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()

    def _is_blocked_by_modal(self):
        return is_blocked_by_modal(self)

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_tooltip_layout()
        self._update_tooltip_markup()
        self._update_image()
        self._update_tooltip()

    def _update_tooltip_layout(self, *largs):
        if not self._tooltip:
            return
        self._tooltip.orientation = "horizontal" if self.tooltip_horizontal else "vertical"
        self._update_tooltip_size()

    def _update_tooltip_markup(self, *largs):
        if not self._tooltip:
            return
        self._tooltip.ids.tooltip_label.markup = self.tooltip_markup
        self._update_tooltip_size()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ""
            self._tooltip.ids.tooltip_label.size = (0, 0)

        self._update_tooltip_size()

    def _has_tooltip_image(self):
        return bool(self.tooltip_texture is not None or self.tooltip_image or self.tooltip_texture_provider is not None)

    def _ensure_tooltip_texture(self):
        """Build a deferred tooltip texture if a provider is set.

        Returns True when a texture was built, meaning the tooltip box needs
        to be measured again.
        """
        if self.tooltip_texture is not None or self.tooltip_texture_provider is None:
            return False
        texture, display_size = self.tooltip_texture_provider()
        # Size first so the box is measured correctly when texture assignment
        # triggers _update_image / _update_image_size.
        self.tooltip_image_size = display_size
        self.tooltip_texture = texture
        return True

    def _update_image(self, *largs):
        if not self._tooltip:
            return
        image_widget = self._tooltip.ids.tooltip_image
        if self.tooltip_texture is not None:
            # Clear any path-based source first so an async load cannot overwrite
            # the generated texture we assign next.
            if image_widget.source:
                image_widget.source = ""
            image_widget.texture = self.tooltip_texture
            image_widget.visible = True
        elif self.tooltip_image:
            image_widget.texture = None
            image_widget.source = self.tooltip_image
            image_widget.visible = True
        else:
            image_widget.source = ""
            image_widget.texture = None
            image_widget.size = (0, 0)
            image_widget.visible = False
        self._update_image_size()

    def _update_image_size(self, *_args):
        if not self._tooltip:
            return

        tooltip_image = self._tooltip.ids.tooltip_image
        if self.tooltip_image_size:
            tooltip_image.size = self.tooltip_image_size
        elif self._has_tooltip_image():
            tooltip_image.size = tooltip_image.texture_size
        else:
            tooltip_image.size = (0, 0)
        self._update_tooltip_size()

    def _update_tooltip_size(self):
        if not self._tooltip:
            return
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width, new_height = _compute_tooltip_box_size(
            text_width,
            text_height,
            image_width,
            image_height,
            has_text=bool(tooltip_label.text),
            has_image=self._has_tooltip_image(),
            horizontal=self.tooltip_horizontal,
            spacing=self._tooltip.spacing,
        )

        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return

        if not self.get_root_window():
            self.close_tooltip()
            return

        if not self.tooltip_txt and not self._has_tooltip_image():
            self.close_tooltip()
            return

        if self.disabled:
            self.close_tooltip()
            return

        if self._is_blocked_by_modal():
            self.close_tooltip()
            return

        pos = args[1]
        self._layout_tooltip_at(pos)

        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            self._hover_pos = pos
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def _layout_tooltip_at(self, pos):
        """Size the tooltip box for its current content and place it near ``pos``."""
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        tooltip_width, tooltip_height = _compute_tooltip_box_size(
            text_width,
            text_height,
            image_width,
            image_height,
            has_text=bool(self.tooltip_txt),
            has_image=self._has_tooltip_image(),
            horizontal=self.tooltip_horizontal,
            spacing=self._tooltip.spacing,
        )
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

    def close_tooltip(self, *args):
        if self._tooltip:  # for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        # Rasterizing is expensive, so it waits until the hover delay has
        # elapsed rather than running on every mouse move across the widget.
        # The box then has to be re-measured around the new image.
        if self._ensure_tooltip_texture() and self._hover_pos is not None:
            self._layout_tooltip_at(self._hover_pos)
        Window.add_widget(self._tooltip)


class ToolTipDropDown(DropDown):
    tooltip_txt = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty("")
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        self._tooltip = None
        super().__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == "ios":
            return
        fbind = self.fbind
        fbind("tooltip_cls", self._build_tooltip)
        fbind("tooltip_txt", self._update_tooltip)
        fbind("tooltip_image", self._update_image)
        fbind("tooltip_image_size", self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()

    def _is_blocked_by_modal(self):
        return is_blocked_by_modal(self)

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ""
            self._tooltip.ids.tooltip_label.size = (0, 0)

        self._update_tooltip_size()

    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ""
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, *_args):
        if not self._tooltip:
            return

        tooltip_image = self._tooltip.ids.tooltip_image
        if self.tooltip_image_size:
            tooltip_image.size = self.tooltip_image_size
        elif self.tooltip_image:
            tooltip_image.size = tooltip_image.texture_size
        else:
            tooltip_image.size = (0, 0)

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        # Keep a stable minimum width for short labels; long text can grow up to max wrap.
        new_width = max(text_width + 20, image_width + 20, TOOLTIP_MIN_WIDTH + 20 if tooltip_label.text else 0)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return

        if not self.get_root_window():
            self.close_tooltip()
            return

        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return

        if self.disabled:
            self.close_tooltip()
            return

        if self._is_blocked_by_modal():
            self.close_tooltip()
            return

        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width, TOOLTIP_MIN_WIDTH if self.tooltip_txt else 0)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def close_tooltip(self, *args):
        if self._tooltip:  # for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipLabel(Label):
    tooltip_txt = StringProperty("")
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty("")
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        self._tooltip = None
        super().__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == "ios":
            return
        fbind = self.fbind
        fbind("tooltip_cls", self._build_tooltip)
        fbind("tooltip_txt", self._update_tooltip)
        fbind("tooltip_image", self._update_image)
        fbind("tooltip_image_size", self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()

    def _is_blocked_by_modal(self):
        return is_blocked_by_modal(self)

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)

        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ""
            self._tooltip.ids.tooltip_label.size = (0, 0)

        self._update_tooltip_size()

    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ""
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, *_args):
        if not self._tooltip:
            return

        tooltip_image = self._tooltip.ids.tooltip_image
        if self.tooltip_image_size:
            tooltip_image.size = self.tooltip_image_size
        elif self.tooltip_image:
            tooltip_image.size = tooltip_image.texture_size
        else:
            tooltip_image.size = (0, 0)

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        # Keep a stable minimum width for short labels; long text can grow up to max wrap.
        new_width = max(text_width + 20, image_width + 20, TOOLTIP_MIN_WIDTH + 20 if tooltip_label.text else 0)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return

        if not self.get_root_window():
            self.close_tooltip()
            return

        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return

        if self.disabled:
            self.close_tooltip()
            return

        if self._is_blocked_by_modal():
            self.close_tooltip()
            return

        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width, TOOLTIP_MIN_WIDTH if self.tooltip_txt else 0)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip)
        self.close_tooltip()
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def close_tooltip(self, *args):
        if self._tooltip:  # for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class HelpButton(ButtonBehavior, BoxLayout):
    image_source = StringProperty("data/open_iconic_UI/oi--question-mark.png")
    helpPath = StringProperty("https://carvera-community.gitbook.io/docs")
    background_normal = StringProperty("atlas://data/images/defaulttheme/button")
    background_down = StringProperty("atlas://data/images/defaulttheme/button_pressed")
    background_disabled_normal = StringProperty("atlas://data/images/defaulttheme/button_disabled")
    background_disabled_down = StringProperty("atlas://data/images/defaulttheme/button_disabled_pressed")
    border = ListProperty([16, 16, 16, 16])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(on_release=self.open_link)
        fbind = self.fbind

    def open_link(self, *args):
        webbrowser.open(self.helpPath)
