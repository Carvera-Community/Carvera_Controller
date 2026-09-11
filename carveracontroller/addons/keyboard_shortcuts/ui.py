"""Kivy settings widget for editing keyboard shortcuts."""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.settings import SettingItem

from carveracontroller.translation import tr

from .bindings import (
    ACTION_BY_ID,
    BINDING_GROUPS,
    MODIFIER_KEY_NAMES,
    ShortcutBindings,
    chord_from_event,
    format_chord,
    format_chord_parts,
    is_modifier_key_event,
)


class _CategoryHeader(Label):
    """A prominent heading separating one shortcut context."""

    def __init__(self, **kwargs):
        kwargs.setdefault("markup", True)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(36))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("color", (0.94, 0.94, 0.96, 1))
        kwargs.setdefault("padding", (dp(4), dp(3)))
        super().__init__(**kwargs)
        with self.canvas.after:
            Color(52 / 255, 166 / 255, 208 / 255, 1)
            self._underline = Rectangle(pos=self.pos, size=(self.width, dp(1)))
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(size=self._sync_text_size)
        self._sync_text_size()

    def _sync_canvas(self, *_args) -> None:
        self._underline.pos = self.pos
        self._underline.size = (self.width, dp(1))

    def _sync_text_size(self, *_args) -> None:
        self.text_size = (max(0, self.width - dp(8)), self.height - dp(6))


class _CategorySection(BoxLayout):
    """Container that keeps a category heading and its rows together."""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("spacing", dp(4))
        kwargs.setdefault("padding", [dp(4), dp(6), dp(4), dp(10)])
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))


class _KeyCap(Label):
    """Compact keyboard-key visualization sized to its label."""

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("height", dp(27))
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("color", (0.96, 0.96, 0.98, 1))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("padding", (dp(8), dp(2)))
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0.28, 0.29, 0.31, 1)
            self._background = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(5)])
        with self.canvas.after:
            Color(0.47, 0.49, 0.52, 1)
            self._outline = Line(rounded_rectangle=(*self.pos, *self.size, dp(5)), width=1)
        self.bind(texture_size=self._sync_width, pos=self._sync_canvas, size=self._sync_canvas)
        self._sync_width()

    def _sync_width(self, *_args) -> None:
        self.width = max(dp(30), self.texture_size[0] + dp(16))

    def _sync_canvas(self, *_args) -> None:
        self._background.pos = self.pos
        self._background.size = self.size
        self._outline.rounded_rectangle = (*self.pos, *self.size, dp(5))


class _ShortcutChordDisplay(AnchorLayout):
    """Centered row of keycaps for one shortcut chord."""

    def __init__(self, chord=None, **kwargs):
        kwargs.setdefault("anchor_x", "center")
        kwargs.setdefault("anchor_y", "center")
        super().__init__(**kwargs)
        self.key_labels = ()
        self._keycaps = []
        self._content = BoxLayout(
            size_hint=(None, None),
            height=dp(27),
            spacing=dp(3),
        )
        self._content.bind(minimum_width=self._content.setter("width"))
        self.add_widget(self._content)
        self.set_chord(chord)

    def set_chord(self, chord) -> None:
        self._content.clear_widgets()
        self._keycaps = []
        if chord is None:
            self.key_labels = ()
            unbound = Label(
                text=tr._("Unbound"),
                size_hint=(None, None),
                size=(dp(72), dp(27)),
                color=(0.62, 0.62, 0.65, 1),
                font_size=sp(13),
            )
            self._content.add_widget(unbound)
            return

        self.key_labels = format_chord_parts(chord)
        for index, label in enumerate(self.key_labels):
            if index:
                self._content.add_widget(
                    Label(
                        text="+",
                        size_hint=(None, None),
                        size=(dp(10), dp(27)),
                        color=(0.68, 0.68, 0.7, 1),
                        font_size=sp(12),
                    )
                )
            keycap = _KeyCap(text=label)
            self._keycaps.append(keycap)
            self._content.add_widget(keycap)


class SettingKeyboardShortcuts(SettingItem):
    """Inline categorized shortcut editor with deferred settings semantics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # SettingItem's stock rule creates a title/control row. This setting is
        # the whole page, so collapse its label and use the complete row.
        self.content.size_hint_x = 1
        content_parent = self.content.parent
        for sibling in tuple(content_parent.children):
            if sibling != self.content:
                content_parent.remove_widget(sibling)
        self._bindings = ShortcutBindings.from_json(
            self.value,
            invert_y_axis_jogging=self._invert_y_axis_jogging(),
        )
        self._listening_for = None
        self._listening_button = None
        self._capture_manager = None
        self._capture_modal = None
        self._capture_panel = None
        self._manager_was_paused = False
        self._binding_displays = {}

        row_count = sum(len(actions) for _, actions in BINDING_GROUPS)
        self.size_hint_y = None
        # Establish the complete height before SettingsPanel first measures
        # this item. Kivy updates nested BoxLayout minimum heights over several
        # layout passes, which is too late for the panel's initial measurement.
        self._editor_height = dp(
            16  # editor vertical padding
            + len(BINDING_GROUPS) * (16 + 36)  # section padding and headers
            + row_count * (40 + 4)  # action rows and section spacing
            + len(BINDING_GROUPS) * 14  # spacing between sections/footer
            + 42  # footer
        )
        self.height = self._editor_height
        self.bind(height=self._keep_editor_height)

        layout = BoxLayout(
            orientation="vertical",
            spacing=dp(14),
            padding=[dp(10), dp(8)],
            size_hint_y=None,
            height=self._editor_height,
        )
        self._editor_layout = layout
        for category, actions in BINDING_GROUPS:
            section = _CategorySection()
            header = _CategoryHeader(text=f"[b]{tr._(category)}[/b]")
            section.add_widget(header)
            for action_id in actions:
                section.add_widget(self._build_action_row(action_id))
            layout.add_widget(section)

        app = App.get_running_app()
        if app is not None:
            app.bind(invert_y_axis_jogging=self._on_invert_y_axis_jogging)

        footer = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self._error_label = Label(halign="left", valign="middle")
        self._error_label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        reset_all = Button(text=tr._("Reset All"), size_hint_x=None, width=dp(120))
        reset_all.bind(on_release=self._reset_all)
        footer.add_widget(self._error_label)
        footer.add_widget(reset_all)
        layout.add_widget(footer)
        self.add_widget(layout)
        layout.bind(minimum_height=self._set_editor_height)
        Clock.schedule_once(self._restore_editor_height, 0)

    def _set_editor_height(self, _layout, minimum_height) -> None:
        self._editor_height = max(self._editor_height, minimum_height)
        self._restore_editor_height(0)

    def _keep_editor_height(self, _instance, height) -> None:
        if height != self._editor_height:
            Clock.schedule_once(self._restore_editor_height, 0)

    def _restore_editor_height(self, _dt) -> None:
        self._editor_height = max(self._editor_height, self._editor_layout.minimum_height)
        self.height = self._editor_height
        self._editor_layout.height = self._editor_height

    def _build_action_row(self, action_id: str):
        action = ACTION_BY_ID[action_id]
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6), padding=[dp(5), 0])
        name = Label(text=tr._(action.label), size_hint_x=0.36, halign="left", valign="middle")
        name.bind(size=lambda widget, size: setattr(widget, "text_size", size))

        binding = _ShortcutChordDisplay(
            chord=self._bindings.binding_for(action_id),
            size_hint_x=0.24,
        )
        self._binding_displays[action_id] = binding

        bind_button = Button(text=tr._("Bind..."), size_hint_x=0.16)
        bind_button.bind(on_release=lambda button, selected=action_id: self._start_capture(selected, button))
        unbind_button = Button(text=tr._("Unbind"), size_hint_x=0.12)
        unbind_button.bind(on_release=lambda *_args, selected=action_id: self._assign(selected, None))
        reset_button = Button(text=tr._("Reset"), size_hint_x=0.12)
        reset_button.bind(on_release=lambda *_args, selected=action_id: self._reset(selected))

        row.add_widget(name)
        row.add_widget(binding)
        row.add_widget(bind_button)
        row.add_widget(unbind_button)
        row.add_widget(reset_button)
        return row

    def _shortcut_manager(self):
        app = App.get_running_app()
        root = getattr(app, "root", None) if app is not None else None
        return getattr(root, "shortcut_manager", None)

    @staticmethod
    def _invert_y_axis_jogging() -> bool:
        app = App.get_running_app()
        return bool(getattr(app, "invert_y_axis_jogging", False))

    def _on_invert_y_axis_jogging(self, _app, inverted) -> None:
        self._bindings.set_invert_y_axis_jogging(bool(inverted))

    def _start_capture(self, action_id: str, button) -> None:
        self._stop_capture()
        self._listening_for = action_id
        self._listening_button = button
        button.text = tr._("Press keys...")
        self._error_label.text = tr._("Press a key combination, or Escape to cancel.")
        manager = self._shortcut_manager()
        if manager is not None:
            self._capture_manager = manager
            self._manager_was_paused = manager.paused
            manager.paused = True
            manager.release_all_jogs()
        modal = self._containing_modal()
        if modal is not None:
            modal.bind(on_dismiss=self._on_capture_modal_dismiss)
            self._capture_modal = modal
        self.panel.bind(parent=self._on_capture_panel_parent)
        self._capture_panel = self.panel
        Window.bind(on_key_down=self._capture_key)

    def _stop_capture(self) -> None:
        if self._listening_for is None:
            return
        Window.unbind(on_key_down=self._capture_key)
        if self._capture_modal is not None:
            self._capture_modal.unbind(on_dismiss=self._on_capture_modal_dismiss)
            self._capture_modal = None
        if self._capture_panel is not None:
            self._capture_panel.unbind(parent=self._on_capture_panel_parent)
            self._capture_panel = None
        if self._listening_button is not None:
            self._listening_button.text = tr._("Bind...")
        manager = self._capture_manager
        if manager is not None:
            manager.paused = self._manager_was_paused
            self._capture_manager = None
        self._listening_for = None
        self._listening_button = None
        self._error_label.text = ""

    def _containing_modal(self):
        widget = self.parent
        while widget is not None:
            if isinstance(widget, ModalView):
                return widget
            widget = widget.parent
        return None

    def _on_capture_modal_dismiss(self, *_args) -> None:
        self._stop_capture()

    def _on_capture_panel_parent(self, _panel, parent) -> None:
        if parent is None:
            self._stop_capture()

    def _capture_key(self, _window, key, scancode, codepoint, modifiers):
        if key == 27:
            self._error_label.text = ""
            self._stop_capture()
            return True
        if is_modifier_key_event(key, scancode):
            return True
        chord = chord_from_event(key, modifiers, codepoint, scancode)
        if chord is None or chord.key in MODIFIER_KEY_NAMES:
            self._error_label.text = tr._("Press a non-modifier key to complete the shortcut.")
            return True
        action_id = self._listening_for
        if action_id is None:
            return False
        conflict = self._bindings.conflict_for(action_id, chord)
        if conflict is not None:
            self._error_label.text = tr._("{0} is already assigned to {1}.").format(
                format_chord(chord), tr._(conflict.label)
            )
            return True
        self._bindings.assign(action_id, chord)
        self._commit()
        self._error_label.text = ""
        self._stop_capture()
        return True

    def _assign(self, action_id: str, chord) -> None:
        self._stop_capture()
        self._bindings.assign(action_id, chord)
        self._commit()
        self._error_label.text = ""

    def _reset(self, action_id: str) -> None:
        self._stop_capture()
        default = self._bindings.default_for(action_id)
        conflict = self._bindings.conflict_for(action_id, default) if default is not None else None
        if conflict is not None:
            self._error_label.text = tr._("Default conflicts with {0}; unbind it first.").format(tr._(conflict.label))
            return
        self._bindings.reset(action_id)
        self._commit()
        self._error_label.text = ""

    def _reset_all(self, *_args) -> None:
        self._stop_capture()
        self._bindings.reset_all()
        self._commit()
        self._error_label.text = ""

    def _commit(self) -> None:
        new_value = self._bindings.to_json()
        previous_value = self.value
        matches_saved_value = str(self.panel.get_value(self.section, self.key)) == str(new_value)
        self.panel.set_value(self.section, self.key, new_value)
        self.value = new_value
        if str(previous_value) != str(new_value) and matches_saved_value and self.panel.settings is not None:
            # DeferredSettingsPanel normally dispatches this notification.
            # When a user returns to the saved value it exits early because
            # Config already contains that value, so explicitly clear the
            # pending-change bookkeeping.
            self.panel.settings.dispatch("on_config_change", self.panel.config, self.section, self.key, new_value)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        for action_id, display in self._binding_displays.items():
            display.set_chord(self._bindings.binding_for(action_id))

    def on_value(self, _instance, value) -> None:
        self._bindings = ShortcutBindings.from_json(
            value,
            invert_y_axis_jogging=self._invert_y_axis_jogging(),
        )
        if hasattr(self, "_binding_displays"):
            self._refresh_labels()

    def on_parent(self, _instance, parent) -> None:
        if parent is None and hasattr(self, "_listening_for"):
            self._stop_capture()

    def on_touch_down(self, touch):
        # SettingItem highlights and grabs the whole row on every click. This
        # editor contains real buttons, so dispatch directly to its children.
        return FloatLayout.on_touch_down(self, touch)

    def on_touch_up(self, touch):
        return FloatLayout.on_touch_up(self, touch)
