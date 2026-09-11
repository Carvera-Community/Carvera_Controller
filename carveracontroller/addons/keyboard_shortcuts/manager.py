"""Runtime routing for configurable keyboard shortcuts."""

from __future__ import annotations

import logging

from kivy.config import Config
from kivy.core.window import Window
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput

from carveracontroller.translation import tr

from .bindings import KeyChord, ShortcutBindings, chord_from_event, format_chord

logger = logging.getLogger(__name__)


def _invert_y_axis_from_config() -> bool:
    return Config.get("carvera", "invert_y_axis_jogging", fallback="0") == "1"


def _shortcut_config_raw() -> str:
    return Config.get("carvera", "keyboard_shortcuts", fallback="") or ""


class ShortcutManager:
    """Own the application-level key handlers and dispatch by context."""

    def __init__(self, root):
        self.root = root
        self.bindings = self._bindings_from_config()
        self.paused = False
        self._installed = False
        self._held_global_keys: set[int] = set()
        self._held_jog_keys: set[int] = set()
        self._suppressed_jog_keys: set[int] = set()
        self._active_jog_key: int | None = None

    def install(self) -> None:
        if self._installed:
            return
        Window.bind(
            on_key_down=self.on_key_down,
            on_key_up=self.on_key_up,
            on_minimize=self.on_window_inactive,
            on_hide=self.on_window_inactive,
            focus=self.on_window_focus,
            children=self.on_window_children,
        )
        self._installed = True
        self.update_mdi_hint()

    def uninstall(self) -> None:
        if not self._installed:
            return
        self.release_all_jogs()
        Window.unbind(
            on_key_down=self.on_key_down,
            on_key_up=self.on_key_up,
            on_minimize=self.on_window_inactive,
            on_hide=self.on_window_inactive,
            focus=self.on_window_focus,
            children=self.on_window_children,
        )
        self._held_global_keys.clear()
        self._held_jog_keys.clear()
        self._suppressed_jog_keys.clear()
        self._installed = False

    @staticmethod
    def _bindings_from_config() -> ShortcutBindings:
        return ShortcutBindings.from_json(
            _shortcut_config_raw(),
            invert_y_axis_jogging=_invert_y_axis_from_config(),
        )

    @classmethod
    def seed_config_if_uninitialized(cls) -> None:
        if _shortcut_config_raw():
            return
        bindings = ShortcutBindings.from_json("", invert_y_axis_jogging=_invert_y_axis_from_config())
        Config.set("carvera", "keyboard_shortcuts", bindings.to_json())
        Config.write()

    def on_window_children(self, _window, children) -> None:
        for child in children:
            if not isinstance(child, ModalView) or not getattr(child, "_is_open", False):
                continue
            if hasattr(child, "allows_external_jog") and child.allows_external_jog():
                continue
            self.release_all_jogs()
            return

    def reload_from_config(self) -> None:
        self.release_all_jogs()
        self.bindings = self._bindings_from_config()
        self.update_mdi_hint()

    def update_mdi_hint(self) -> None:
        mdi = getattr(self.root, "manual_cmd", None)
        if mdi is None:
            return
        send_binding = self.bindings.binding_for("mdi_send")
        if send_binding is None:
            mdi.hint_text = tr._("Enter command...")
        else:
            mdi.hint_text = tr._("Enter command... <{0} to send>").format(format_chord(send_binding))

    def on_window_inactive(self, *_args) -> None:
        self.release_all_jogs()
        # Focus loss can prevent the matching key-up from reaching Kivy.
        self._held_global_keys.clear()
        self._held_jog_keys.clear()
        self._suppressed_jog_keys.clear()

    def on_window_focus(self, _window, focused) -> None:
        if not focused:
            self.on_window_inactive()

    def on_key_down(self, _window, key, scancode, codepoint, modifiers):
        if self.paused:
            return False
        chord = chord_from_event(key, modifiers, codepoint, scancode)
        if chord is None:
            return False

        global_action = self.bindings.action_for(chord, "global")
        if global_action is not None:
            if key in self._held_global_keys:
                return True
            if self._text_producing_global_blocked_while_typing(chord):
                return False
            handled = self._dispatch_global(global_action.action_id)
            if handled:
                self._held_global_keys.add(key)
            return handled

        jog_action = self.bindings.action_for(chord, "jogging")
        if jog_action is not None:
            if key in self._held_jog_keys:
                return True
            if key in self._suppressed_jog_keys:
                return False
            if (
                self._text_input_has_focus()
                or not getattr(self.root, "keyboard_jog_control", False)
                or not self._can_jog_with_keyboard()
            ):
                # Keep repeats from starting a jog if the context becomes
                # eligible before this physical key is released.
                self._suppressed_jog_keys.add(key)
                return False
            self._held_jog_keys.add(key)
            self._start_jog(key, jog_action.action_id)
            return True
        return False

    def on_key_up(self, _window, key, *_args):
        was_global = key in self._held_global_keys
        self._held_global_keys.discard(key)
        was_held = key in self._held_jog_keys
        self._held_jog_keys.discard(key)
        was_suppressed = key in self._suppressed_jog_keys
        self._suppressed_jog_keys.discard(key)
        if key != self._active_jog_key:
            return was_global or (was_held and not was_suppressed)
        self._active_jog_key = None
        controller = getattr(self.root, "controller", None)
        if controller is None:
            return False
        controller.stopContinuousJog()
        return True

    def handle_mdi_keydown(self, widget, key, modifiers, text="") -> bool:
        if self.paused or not widget.focus:
            return False
        chord = chord_from_event(key, modifiers, text)
        if chord is None:
            return False
        action = self.bindings.action_for(chord, "mdi")
        if action is None:
            # Multiline TextInput inserts a newline for Enter on its own.
            # Consume its built-in Enter only while newline is explicitly remapped.
            return chord.key == "enter" and self.bindings.binding_for("mdi_newline") is not None
        if action.action_id == "mdi_send":
            if self.root.can_send_mdi_command():
                widget.send_mdi_command()
            return True
        if action.action_id == "mdi_newline":
            widget.insert_text("\n")
            return True
        return False

    def _dispatch_global(self, action_id: str) -> bool:
        self.release_all_jogs()
        if action_id == "open_online_docs":
            self.root.open_online_docs()
            return True
        if action_id == "open_settings":
            if not self.root._is_popup_open() and not self.root.manual_cmd.focus:
                self.root.config_popup.open()
                return True
        elif action_id == "open_mdi":
            if not self.root._is_popup_open():
                self.root.open_mdi()
                return True
        elif action_id == "open_gcode":
            if not self.root._is_popup_open():
                self.root.open_gcode()
                return True
        elif action_id == "open_file_browser":
            return bool(self.root.open_file_browser())
        elif action_id == "toggle_keyboard_jogging":
            return bool(self.root.toggle_keyboard_jog_control())
        elif action_id == "switch_jog_mode":
            return bool(self.root.toggle_jog_mode())
        elif action_id == "open_start_job":
            return bool(self.root.open_start_job_popup())
        return False

    def _text_producing_global_blocked_while_typing(self, chord: KeyChord) -> bool:
        command_modifiers = {"primary", "ctrl", "alt", "meta"}
        produces_text = len(chord.key) == 1 or chord.key == "spacebar"
        return produces_text and not command_modifiers.intersection(chord.modifiers) and self._text_input_has_focus()

    def _text_input_has_focus(self) -> bool:
        for child in Window.children:
            widgets = child.walk() if hasattr(child, "walk") else (child,)
            if any(isinstance(widget, TextInput) and widget.focus for widget in widgets):
                return True
        return False

    def _can_jog_with_keyboard(self) -> bool:
        return bool(
            getattr(self.root, "keyboard_jog_control", False)
            and self.root.is_jogging_enabled()
            and not self._text_input_has_focus()
        )

    def _start_jog(self, key: int, action_id: str) -> None:
        # Do not switch axes while another physical jog key is still held.
        # Continuous-jog cancellation is asynchronous, so starting the second
        # direction immediately would be ignored by the controller anyway.
        if self._active_jog_key is not None:
            return
        self._active_jog_key = key
        try:
            self.root.perform_keyboard_jog(action_id)
        except Exception:
            self._active_jog_key = None
            logger.exception("Failed to execute keyboard jog action %s", action_id)

    def release_all_jogs(self) -> None:
        if self._active_jog_key is None:
            return
        self._active_jog_key = None
        controller = getattr(self.root, "controller", None)
        if controller is not None:
            controller.stopContinuousJog()
