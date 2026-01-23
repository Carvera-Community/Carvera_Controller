from kivy.uix.settings import SettingItem
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.textinput import TextInput
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
import json

from carveracontroller.translation import tr


class ColorPreview(Widget):
    """A simple widget that displays a color preview."""
    def __init__(self, color=(0, 1, 1, 1), **kwargs):
        super().__init__(**kwargs)
        self._color = color
        with self.canvas:
            self._bg_color = Color(*self._color)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_color(self, color):
        self._color = color
        self._bg_color.rgba = color


class SettingColorPicker(SettingItem):
    """A custom settings item that provides a color picker."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(60)

        # Parse initial color value
        self._current_color = self._parse_color(self.value)

        # Wrapper for vertical centering
        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        inner = BoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint=(1, None),
            height=dp(40),
            padding=[dp(10), 0]
        )

        # Color preview widget
        self.color_preview = ColorPreview(
            color=self._current_color,
            size_hint=(None, 1),
            width=dp(60)
        )

        # Color value label
        self.color_label = Label(
            text=self._format_color(self._current_color),
            halign='left',
            valign='middle',
            size_hint=(1, 1),
        )

        # Button to open color picker
        btn = Button(text=tr._("Pick Color..."), size_hint=(None, 1), width=dp(130))
        btn.bind(on_release=self.open_popup)

        inner.add_widget(self.color_preview)
        inner.add_widget(self.color_label)
        inner.add_widget(btn)
        wrapper.add_widget(inner)
        self.add_widget(wrapper)

    def _parse_color(self, value):
        """Parse a color string like '0,255,255,255' or '0,1,1,1' into an RGBA tuple (0-1 range)."""
        try:
            if not value:
                return (0, 1, 1, 1)  # Default cyan
            parts = [float(x.strip()) for x in value.split(',')]
            if len(parts) == 3:
                parts.append(1.0)  # Add alpha if missing
            # If values are > 1, assume 0-255 range
            if any(p > 1 for p in parts[:3]):
                return (parts[0]/255, parts[1]/255, parts[2]/255, parts[3] if parts[3] <= 1 else parts[3]/255)
            return tuple(parts)
        except Exception:
            return (0, 1, 1, 1)  # Default cyan

    def _format_color(self, color):
        """Format color tuple as a readable string."""
        r, g, b, a = color
        return f"R:{int(r*255)} G:{int(g*255)} B:{int(b*255)}"

    def _color_to_string(self, color):
        """Convert color tuple to storage string (0-255 range)."""
        r, g, b, a = color
        return f"{int(r*255)},{int(g*255)},{int(b*255)},{int(a*255)}"

    def open_popup(self, *args):
        """Open the color picker popup."""
        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))

        # Color picker widget
        self.picker = ColorPicker(color=self._current_color)
        content.add_widget(self.picker)

        # Buttons
        btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))

        popup = Popup(
            title=self.title or tr._("Select Color"),
            content=content,
            size_hint=(0.8, 0.9),
            auto_dismiss=False
        )

        save_btn = Button(text=tr._("Save"))
        save_btn.bind(on_release=lambda *a: self._save_and_close(popup))

        cancel_btn = Button(text=tr._("Cancel"))
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())

        # Reset to default button
        reset_btn = Button(text=tr._("Reset to Default"))
        reset_btn.bind(on_release=lambda *a: self._reset_to_default())

        btns.add_widget(cancel_btn)
        btns.add_widget(reset_btn)
        btns.add_widget(save_btn)
        content.add_widget(btns)

        popup.open()
        self._popup = popup

    def _reset_to_default(self):
        """Reset color to default cyan."""
        default_color = (0, 1, 1, 1)
        self.picker.color = default_color

    def _save_and_close(self, popup):
        """Save the selected color and close the popup."""
        self._current_color = self.picker.color
        new_value = self._color_to_string(self._current_color)

        self.color_preview.set_color(self._current_color)
        self.color_label.text = self._format_color(self._current_color)

        self.panel.set_value(self.section, self.key, new_value)
        self.value = new_value

        popup.dismiss()

    def on_value(self, instance, value):
        """Called when the value changes."""
        if hasattr(self, 'color_preview'):
            self._current_color = self._parse_color(value)
            self.color_preview.set_color(self._current_color)
            self.color_label.text = self._format_color(self._current_color)

class SettingGCodeSnippet(SettingItem):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(80)

        # Wrapper: ensure the content is centered vertically
        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        # And split it horizontally into two parts:
        # 1. Block with preview of the G-code snippet name
        # 2. Button to open the editor popup
        inner = BoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint=(1, None),
            height=dp(40),
            padding=[dp(10), 0]
        )

        self.preview = Label(
            text=self._get_name(self.value),
            halign='left',
            valign='middle',
            size_hint=(1, 1),
            text_size=(None, None),
        )

        btn = Button(text=tr._("Open editor…"), size_hint=(None, 1), width=dp(130))
        btn.bind(on_release=self.open_popup)

        inner.add_widget(self.preview)
        inner.add_widget(btn)
        wrapper.add_widget(inner)
        self.add_widget(wrapper)

    def _get_name(self, value):
        try:
            obj = json.loads(value)
            return obj.get("name", tr._("<unnamed>"))
        except Exception:
            return tr._("<invalid>")

    def _update_text_size(self, instance, width):
        instance.text_size = (width - dp(20), None)

    def _update_height(self, instance, size):
        instance.height = size[1]

    def open_popup(self, *args):
        try:
            obj = json.loads(self.value or '{}')
        except Exception:
            obj = {}

        name = obj.get("name", "")
        gcode = obj.get("gcode", "")

        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))

        self.name_input = TextInput(
            text=name,
            multiline=False,
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(Label(text=tr._("Name:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.name_input)

        self.gcode_input = TextInput(
            text=gcode,
            size_hint=(1, 1)
        )
        content.add_widget(Label(text=tr._("G-code:"), size_hint_y=None, height=dp(20)))
        content.add_widget(self.gcode_input)

        btns = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        popup = Popup(
            title=self.title or tr._("Edit command"),
            content=content,
            size_hint=(0.8, 0.8),
            auto_dismiss=False
        )

        save_btn = Button(text=tr._("Save"))
        save_btn.bind(on_release=lambda *a: self._save_and_close(popup))

        cancel_btn = Button(text=tr._("Cancel"))
        cancel_btn.bind(on_release=lambda *a: popup.dismiss())

        btns.add_widget(cancel_btn)
        btns.add_widget(save_btn)
        content.add_widget(btns)

        popup.open()
        self._popup = popup

    def _save_and_close(self, popup):
        obj = {
            "name": self.name_input.text.strip(),
            "gcode": self.gcode_input.text.strip()
        }

        new_value = json.dumps(obj)

        self.panel.set_value(self.section, self.key, new_value)

        self.value = new_value
        self.on_value(self, new_value)

        popup.dismiss()

    def on_value(self, instance, value):
        if hasattr(self, 'preview'):
            self.preview.text = self._get_name(value)
