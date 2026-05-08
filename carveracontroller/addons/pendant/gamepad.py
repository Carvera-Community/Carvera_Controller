from __future__ import annotations

import configparser
import json
import logging
from typing import Callable, Dict, List, Optional, Tuple

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.config import Config

from carveracontroller.translation import tr

from .sdl_joystick_hotplug import ensure_sdl_joysticks_open

logger = logging.getLogger(__name__)

# Standard HID joystick axis range
AXIS_MAX = 32767

# Preset bindings for common controllers
PRESETS: List[Tuple[str, dict]] = [
    ("Xbox 360 / Xbox One", {
        "axes": {
            "0": "jog_x",
            "1": "jog_y",
            "4": "jog_z",
            "3": "jog_a",
        },
        "triggers": {
            "2:+": "feed_minus",   # LT
            "5:+": "feed_plus",    # RT
        },
        "buttons": {
            "4": "step_size_down",   # LB
            "5": "step_size_up",     # RB
            "6": "mode_toggle",      # Back / View
            "7": "spindle_on_off",   # Start / Menu
        },
        "hat": {},
    }),

    ("PlayStation (DS4 / DualSense)", {
        "axes": {
            "0": "jog_x",
            "1": "jog_y",
            "5": "jog_z",
            "2": "jog_a",
        },
        "triggers": {
            "3:+": "feed_minus",   # L2
            "4:+": "feed_plus",    # R2
        },
        "buttons": {
            "4": "step_size_down",   # L1
            "5": "step_size_up",     # R1
            "8": "mode_toggle",      # Share / Create
            "9": "spindle_on_off",   # Options
        },
        "hat": {},
    }),

    ("Nintendo Switch Pro", {
        "axes": {
            "0": "jog_x",
            "1": "jog_y",
            "3": "jog_z",
            "2": "jog_a",
        },
        "triggers": {},
        "buttons": {
            "4": "step_size_down",   # L
            "5": "step_size_up",     # R
            "6": "feed_minus",       # ZL
            "7": "feed_plus",        # ZR
            "8": "mode_toggle",      # Minus
            "9": "spindle_on_off",   # Plus
        },
        "hat": {},
    }),
]


def preset_names() -> List[str]:
    """Return the ordered list of available preset names."""
    return [name for name, _ in PRESETS]


def preset_bindings(name: str) -> Optional[dict]:
    """Return a deep copy of the bindings dict for the named preset, or None."""
    for preset_name, bindings in PRESETS:
        if preset_name == name:
            return json.loads(json.dumps(bindings))
    return None

# Human-readable labels for actions (used by the bindings configuration UI)
ACTION_LABELS = {
    "jog_x": "Jog X",
    "jog_y": "Jog Y",
    "jog_z": "Jog Z",
    "jog_a": "Jog A",
    "feed_plus": "Feed Override +",
    "feed_minus": "Feed Override -",
    "spindle_plus": "Spindle Override +",
    "spindle_minus": "Spindle Override -",
    "start_pause": "Start / Pause",
    "stop": "Stop",
    "reset": "E-Stop / Reset",
    "mode_toggle": "Mode Toggle (Step/Continuous)",
    "probe_z": "Probe Z",
    "m_home": "Machine Home",
    "w_home": "Work Home",
    "safe_z": "Safe Z",
    "spindle_on_off": "Spindle On/Off",
    "step_size_up": "Step Size +",
    "step_size_down": "Step Size -",
    "macro_1": "Macro 1",
    "macro_2": "Macro 2",
    "macro_3": "Macro 3",
    "macro_4": "Macro 4",
    "macro_5": "Macro 5",
    "macro_6": "Macro 6",
    "macro_7": "Macro 7",
    "macro_8": "Macro 8",
    "macro_9": "Macro 9",
    "macro_10": "Macro 10",
}


def hat_axis_pair(direction: str) -> Optional[Tuple[str, str]]:
    """Return left+right or up+down for ``direction``, or None if unknown."""
    if direction in ("left", "right"):
        return ("left", "right")
    if direction in ("up", "down"):
        return ("up", "down")
    return None


# Ordered list of actions grouped by category for the binding UI
BINDING_GROUPS = [
    ("Jogging", ["jog_x", "jog_y", "jog_z", "jog_a"]),
    ("Overrides", ["feed_plus", "feed_minus", "spindle_plus", "spindle_minus"]),
    ("Controls", ["start_pause", "stop", "reset", "mode_toggle",
                  "probe_z", "m_home", "w_home", "safe_z",
                  "spindle_on_off", "step_size_up", "step_size_down"]),
    ("Macros", ["macro_1", "macro_2", "macro_3", "macro_4", "macro_5",
                "macro_6", "macro_7", "macro_8", "macro_9", "macro_10"]),
]

def format_input_label(input_type: str, input_id: str) -> str:
    """Return a human-readable label for a raw gamepad input."""
    if input_type == "axis":
        return tr._("Axis {0}").format(input_id)
    elif input_type == "trigger":
        axis_id, direction = split_trigger_id(input_id)
        if direction in ("+", "-"):
            return tr._("Trigger Axis {0}{1}").format(axis_id, direction)
        return tr._("Trigger Axis {0}").format(axis_id)
    elif input_type == "button":
        return tr._("Button {0}").format(input_id)
    elif input_type == "hat":
        return tr._("D-Pad {0}").format(input_id.capitalize())
    return f"{input_type} {input_id}"


def trigger_input_id(axis_id: int, direction: str) -> str:
    """Return the binding key for a directional axis trigger."""
    if direction not in ("+", "-"):
        raise ValueError(f"Invalid trigger direction: {direction}")
    return f"{axis_id}:{direction}"


def split_trigger_id(input_id: str) -> Tuple[str, Optional[str]]:
    """Split a trigger binding key into axis id and optional direction."""
    axis_id, sep, direction = input_id.partition(":")
    if sep and direction in ("+", "-"):
        return axis_id, direction
    return input_id, None


def default_bindings() -> dict:
    """Return the default gamepad binding configuration (Xbox 360 / Xbox One)."""
    return preset_bindings(PRESETS[0][0])


class GamepadBindings:
    """Resolves raw gamepad inputs to logical action names via a binding map.

    The binding map is a JSON-serialisable dict with four top-level keys:

    ``axes``     — continuous joystick axes (thumbsticks).
                   Key: axis index as a string (e.g. ``"0"``).
                   Value: action name (e.g. ``"jog_x"``).
                   Only the four jog actions (``jog_x/y/z/a``) make sense here;
                   the axis value is passed through the deadzone and fed to the
                   jog handler continuously while the stick is held.

    ``triggers`` — one-shot actions fired when an axis crosses the deadzone in
                   one direction.  Unlike ``axes``, each direction of the same
                   physical axis can be bound independently.
                   Key: ``"<axis_index>:<direction>"`` where direction is ``+``
                   or ``-`` (e.g. ``"2:+"`` for the positive half of axis 2).
                   Value: action name (e.g. ``"feed_plus"``).
                   A bare axis index without a direction (e.g. ``"2"``) is also
                   accepted as a fallback and treated as the ``+`` direction.

    ``buttons``  — one-shot actions fired on button-down events.
                   Key: button index as a string (e.g. ``"4"``).
                   Value: action name (e.g. ``"step_size_up"``).

    ``hat``      — one-shot or jog actions fired by the D-Pad (hat switch).
                   Key: one of ``"up"``, ``"down"``, ``"left"``, ``"right"``.
                   Value: action name.  If the action starts with ``"jog_"``,
                   continuous-jog semantics are applied while the direction is
                   held; otherwise it fires as a one-shot button action.
                   The same jog action may appear on several directions (e.g.
                   ``"left"`` and ``"right"`` both bound to ``"jog_x"``).
                   When assigning a jog action via the bindings UI (any action
                   whose name starts with ``"jog_"``), **both** directions along
                   the same D-Pad axis as the key you press are written at once
                   (left+right if you press left or right, up+down if you press
                   up or down; see ``hat_axis_pair()``).

    Example (minimal custom config)::

        {
            "axes":     {"1": "jog_y"},
            "triggers": {"2:-": "feed_minus", "5:+": "feed_plus"},
            "buttons":  {"4": "step_size_down", "5": "step_size_up"},
            "hat":      {"left": "jog_x", "right": "jog_x",
                         "up": "jog_z", "down": "jog_z"}
        }
    """

    def __init__(self, bindings: Optional[dict] = None) -> None:
        self._bindings = bindings or default_bindings()

    @classmethod
    def from_config(cls) -> GamepadBindings:
        try:
            raw = Config.get("carvera", "gamepad_bindings")
        except (configparser.NoSectionError, configparser.NoOptionError):
            return cls()
        if raw:
            try:
                return cls(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid gamepad_bindings config, using defaults")
        return cls()

    def axis_action(self, axis_id: int) -> Optional[str]:
        return self._bindings.get("axes", {}).get(str(axis_id))

    def trigger_action(self, axis_id: int, direction: str) -> Optional[str]:
        trigger_map = self._bindings.get("triggers", {})
        action = trigger_map.get(trigger_input_id(axis_id, direction))
        if action:
            return action

        # If the requested direction is "+" also check for fallback bindings
        # where the axis ID is used directly as the key (without direction).
        if direction == "+":
            return trigger_map.get(str(axis_id))

        return None

    def button_action(self, button_id: int) -> Optional[str]:
        return self._bindings.get("buttons", {}).get(str(button_id))

    def hat_action(self, dx: int, dy: int) -> Optional[str]:
        hat_map = self._bindings.get("hat", {})
        if dy > 0:
            return hat_map.get("up")
        if dy < 0:
            return hat_map.get("down")
        if dx < 0:
            return hat_map.get("left")
        if dx > 0:
            return hat_map.get("right")
        return None

    def axes_items(self):
        """Return an iterable of (axis_id_str, action) pairs for axes."""
        return self._bindings.get("axes", {}).items()

    def to_dict(self) -> dict:
        return self._bindings


class GamepadManager:
    """
    Gamepad input manager that listens to Kivy Window joystick events
    and translates them into callbacks via configurable bindings.
    """

    def __init__(self, bindings: Optional[GamepadBindings] = None,
                 deadzone: float = 0.15) -> None:
        self._bindings = bindings or GamepadBindings()
        self._deadzone = max(0.01, min(deadzone, 0.99))
        self._active_stick: Optional[int] = None
        self._connected = False

        # Current normalised axis values (axis_id -> float in -1..1)
        self._axis_values: Dict[int, float] = {}

        # Track which jog axes are "held" past the deadzone (for step-mode
        # one-press-one-move). Maps action name -> direction sign (+1/-1).
        self._held_axes: Dict[str, int] = {}

        # Track trigger "held" state for one-shot behaviour
        self._held_triggers: Dict[str, bool] = {}

        # Track hat held state
        self._hat_held: Dict[str, bool] = {}

        # When True, axis/button/trigger/hat events are received (for
        # connection detection) but no action callbacks are fired.  Set while
        # GamepadBindingsPopup is open so machine commands cannot fire during
        # configuration.
        self._paused: bool = False

        # Callbacks (set by the pendant class)
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_jog_axis: Optional[Callable[[str, float], None]] = None
        self.on_jog_stop: Optional[Callable[[str], None]] = None
        self.on_button_action: Optional[Callable[[str], None]] = None

        self._joystick_rescan_ev = Clock.schedule_interval(
            self._rescan_sdl_joysticks, 1.0)
        ensure_sdl_joysticks_open()
        self._bind_events()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def deadzone(self) -> float:
        return self._deadzone

    @deadzone.setter
    def deadzone(self, value: float) -> None:
        self._deadzone = max(0.01, min(value, 0.99))

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        value = bool(value)
        if value == self._paused:
            return

        if value:
            self._release_all_inputs()

        self._paused = value

    def _release_all_inputs(self) -> None:
        held_actions = list(self._held_axes.keys())
        self._axis_values.clear()
        self._held_axes.clear()
        self._held_triggers.clear()
        self._hat_held.clear()

        for action in held_actions:
            if self.on_jog_stop:
                self.on_jog_stop(action)

    def close(self) -> None:
        if self._joystick_rescan_ev is not None:
            self._joystick_rescan_ev.cancel()
            self._joystick_rescan_ev = None
        self._release_all_inputs()
        self._unbind_events()
        self._active_stick = None
        self._connected = False

    def _rescan_sdl_joysticks(self, _dt: float) -> None:
        ensure_sdl_joysticks_open()

    def _bind_events(self) -> None:
        logger.info("GamepadManager: binding on_joy_* events on Window")
        Window.bind(
            on_joy_axis=self._on_joy_axis,
            on_joy_hat=self._on_joy_hat,
            on_joy_button_down=self._on_joy_button_down,
            on_joy_button_up=self._on_joy_button_up,
        )

    def _unbind_events(self) -> None:
        Window.unbind(
            on_joy_axis=self._on_joy_axis,
            on_joy_hat=self._on_joy_hat,
            on_joy_button_down=self._on_joy_button_down,
            on_joy_button_up=self._on_joy_button_up,
        )

    def _ensure_connected(self, stickid: int) -> None:
        """Track connection state based on first received event."""
        if self._active_stick is None:
            self._active_stick = stickid
        if stickid != self._active_stick:
            return
        if not self._connected:
            self._connected = True
            logger.info(f"Gamepad connected (stick id {stickid})")
            if self.on_connect:
                self.on_connect()

    def _normalise(self, value: int) -> float:
        return max(-1.0, min(1.0, value / AXIS_MAX))

    def _apply_deadzone(self, value: float) -> float:
        if abs(value) < self._deadzone:
            return 0.0
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - self._deadzone) / (1.0 - self._deadzone)

    # Kivy event handlers
    def _on_joy_axis(self, win, stickid: int, axisid: int, value: int) -> None:
        logger.debug(f"on_joy_axis: stick={stickid} axis={axisid} value={value}")
        self._ensure_connected(stickid)
        if stickid != self._active_stick:
            return
        if self.paused:
            return

        normalised = self._normalise(value)

        # Check if this axis is a trigger. Positive and negative trigger
        # directions are handled separately so each can release cleanly.
        positive_trigger_action = self._bindings.trigger_action(axisid, "+")
        negative_trigger_action = self._bindings.trigger_action(axisid, "-")
        if positive_trigger_action or negative_trigger_action:
            if positive_trigger_action:
                self._handle_trigger(positive_trigger_action, normalised)
            if negative_trigger_action:
                self._handle_trigger(negative_trigger_action, -normalised)
            return

        # Check if this axis is a jog axis
        action = self._bindings.axis_action(axisid)
        if not action:
            return

        filtered = self._apply_deadzone(normalised)
        prev = self._axis_values.get(axisid, 0.0)
        was_active = abs(prev) > 0
        is_active = abs(filtered) > 0

        rising_edge = is_active and not was_active
        falling_edge = not is_active and was_active

        # Update hold state before notifying pendant so is_axis_held is accurate.
        if rising_edge:
            direction = 1 if filtered > 0 else -1
            self._held_axes[action] = direction
        elif falling_edge:
            self._held_axes.pop(action, None)
            if self.on_jog_stop:
                self.on_jog_stop(action)

        self._axis_values[axisid] = filtered

        if is_active and self.on_jog_axis:
            self.on_jog_axis(action, filtered)

    def _handle_trigger(self, action: str, normalised: float) -> None:
        """Triggers fire a one-shot action when they cross the deadzone."""
        active = normalised > self._deadzone
        was_held = self._held_triggers.get(action, False)

        if active and not was_held:
            self._held_triggers[action] = True
            if self.on_button_action:
                self.on_button_action(action)
        elif not active and was_held:
            self._held_triggers[action] = False

    def _on_joy_hat(self, win, stickid: int, hatid: int, value) -> None:
        logger.debug(f"on_joy_hat: stick={stickid} hat={hatid} value={value}")
        self._ensure_connected(stickid)
        if stickid != self._active_stick:
            return
        if self.paused:
            return

        dx, dy = value if isinstance(value, (tuple, list)) else (0, 0)

        # Release any previously held hat directions that are no longer active
        still_pressed = {
            "up": dy > 0, "down": dy < 0,
            "left": dx < 0, "right": dx > 0,
        }
        for direction in list(self._hat_held.keys()):
            if self._hat_held[direction] and not still_pressed.get(direction, False):
                self._hat_held[direction] = False
                hat_action = self._bindings.hat_action(
                    -1 if direction == "left" else 1 if direction == "right" else 0,
                    1 if direction == "up" else -1 if direction == "down" else 0,
                )
                if hat_action:
                    self._held_axes.pop(hat_action, None)
                    if hat_action.startswith("jog_") and self.on_jog_stop:
                        self.on_jog_stop(hat_action)

        # Press new hat directions
        for direction, cond in [("up", dy > 0), ("down", dy < 0),
                                ("left", dx < 0), ("right", dx > 0)]:
            if cond and not self._hat_held.get(direction, False):
                self._hat_held[direction] = True
                hat_dx = -1 if direction == "left" else 1 if direction == "right" else 0
                hat_dy = 1 if direction == "up" else -1 if direction == "down" else 0
                action = self._bindings.hat_action(hat_dx, hat_dy)
                if action:
                    if action.startswith("jog_"):
                        if self.on_jog_axis:
                            sign = 1.0 if direction in ("up", "right") else -1.0
                            self.on_jog_axis(action, sign)
                        self._held_axes[action] = 1 if direction in ("up", "right") else -1
                    elif self.on_button_action:
                        self.on_button_action(action)

    def _on_joy_button_down(self, win, stickid: int, buttonid: int) -> None:
        logger.debug(f"on_joy_button_down: stick={stickid} button={buttonid}")
        self._ensure_connected(stickid)
        if stickid != self._active_stick:
            return
        if self.paused:
            return

        action = self._bindings.button_action(buttonid)
        if action and self.on_button_action:
            self.on_button_action(action)

    def _on_joy_button_up(self, win, stickid: int, buttonid: int) -> None:
        if stickid != self._active_stick:
            return
        # Do nothing

    def is_axis_held(self, action: str) -> bool:
        return action in self._held_axes

    def held_axis_direction(self, action: str) -> int:
        return self._held_axes.get(action, 0)

    def axis_value(self, action: str) -> float:
        """Return the current filtered value for a jog axis action."""
        for axis_id, act in ((int(k), v) for k, v in self._bindings.axes_items()):
            if act == action:
                return self._axis_values.get(axis_id, 0.0)
        return 0.0
