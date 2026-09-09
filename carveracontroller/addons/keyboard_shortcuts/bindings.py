"""Shortcut definitions, normalisation, persistence, and conflict detection."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass

from kivy.core.window import Keyboard

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
VALID_MODIFIERS = frozenset({"ctrl", "alt", "shift", "meta", "primary"})
LOCK_MODIFIERS = frozenset({"capslock", "numlock", "scrolllock", "mode"})
MODIFIER_ORDER = ("primary", "ctrl", "alt", "shift", "meta")
MODIFIER_KEY_NAMES = frozenset(
    {
        "alt",
        "alt-gr",
        "ctrl",
        "lalt",
        "lctrl",
        "lmeta",
        "lshift",
        "lsuper",
        "meta",
        "ralt",
        "rctrl",
        "rmeta",
        "rshift",
        "rsuper",
        "shift",
        "super",
    }
)
MODIFIER_KEY_CODES = frozenset(code for name in MODIFIER_KEY_NAMES if (code := Keyboard.keycodes.get(name)) is not None)
MODIFIER_SCANCODES = frozenset(range(224, 232))

KEY_ALIASES = {
    "comma": ",",
    "numpadenter": "enter",
    "return": "enter",
    "pgup": "pageup",
    "pgdown": "pagedown",
    "esc": "escape",
}

# Prefer Kivy names/aliases over SDL scancodes.
PREFERRED_KEY_NAMES = {
    9: "tab",
    13: "enter",
    27: "escape",
    32: "spacebar",
    44: ",",
    271: "enter",
    273: "up",
    274: "down",
    275: "right",
    276: "left",
    280: "pageup",
    281: "pagedown",
}
for _number in range(1, 16):
    _name = f"f{_number}"
    _code = Keyboard.keycodes.get(_name)
    if _code is not None:
        PREFERRED_KEY_NAMES[_code] = _name


def _normalise_key_name(key: str) -> str:
    raw = str(key).strip().lower()
    value = KEY_ALIASES.get(raw, raw)
    if len(value) == 1:
        return value
    if value not in Keyboard.keycodes:
        raise ValueError(f"Unknown key: {key}")
    return value


def _normalise_modifiers(modifiers) -> tuple[str, ...]:
    values = {str(modifier).lower() for modifier in modifiers}
    values -= LOCK_MODIFIERS
    unknown = values - VALID_MODIFIERS
    if unknown:
        raise ValueError(f"Unknown modifiers: {', '.join(sorted(unknown))}")
    if "primary" in values and ({"ctrl", "meta"} & values):
        raise ValueError("Primary cannot be combined with Ctrl or Meta")
    return tuple(modifier for modifier in MODIFIER_ORDER if modifier in values)


@dataclass(frozen=True)
class KeyChord:
    """One non-modifier key and its exact modifier set."""

    key: str
    modifiers: tuple[str, ...] = ()

    def __post_init__(self):
        key = _normalise_key_name(self.key)
        if key in MODIFIER_KEY_NAMES:
            raise ValueError("A shortcut requires a non-modifier key")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "modifiers", _normalise_modifiers(self.modifiers))

    def to_dict(self) -> dict:
        return {"key": self.key, "modifiers": list(self.modifiers)}

    @classmethod
    def from_dict(cls, value: dict) -> KeyChord:
        if not isinstance(value, dict) or not isinstance(value.get("key"), str):
            raise ValueError("A shortcut must contain a key name")
        modifiers = value.get("modifiers", [])
        if not isinstance(modifiers, list):
            raise ValueError("Shortcut modifiers must be a list")
        return cls(value["key"], tuple(modifiers))

    def resolved_modifiers(self, platform: str | None = None) -> frozenset[str]:
        resolved = set(self.modifiers)
        if "primary" in resolved:
            resolved.remove("primary")
            resolved.add("meta" if (platform or sys.platform) == "darwin" else "ctrl")
        return frozenset(resolved)

    def matches(self, other: KeyChord, platform: str | None = None) -> bool:
        return self.key == other.key and self.resolved_modifiers(platform) == other.resolved_modifiers(platform)


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    label: str
    category: str
    context: str
    default: KeyChord | None


ACTIONS = (
    ActionDefinition("open_start_job", "Open Start Job", "Global", "global", None),
    ActionDefinition("open_online_docs", "Open Online Documentation", "Global", "global", KeyChord("f1")),
    ActionDefinition("open_settings", "Open Settings", "Global", "global", KeyChord(",", ("primary",))),
    ActionDefinition("open_mdi", "Open / Focus MDI", "Global", "global", KeyChord("m", ("ctrl",))),
    ActionDefinition("open_file_browser", "Open File Browser", "Global", "global", KeyChord("o", ("ctrl",))),
    ActionDefinition(
        "toggle_keyboard_jogging",
        "Toggle Keyboard Jogging",
        "Global",
        "global",
        KeyChord("j", ("ctrl",)),
    ),
    ActionDefinition("jog_x_positive", "Jog X+", "Jogging", "jogging", KeyChord("right")),
    ActionDefinition("jog_x_negative", "Jog X−", "Jogging", "jogging", KeyChord("left")),
    ActionDefinition("jog_y_positive", "Jog Y+", "Jogging", "jogging", KeyChord("down")),
    ActionDefinition("jog_y_negative", "Jog Y−", "Jogging", "jogging", KeyChord("up")),
    ActionDefinition("jog_z_positive", "Jog Z+", "Jogging", "jogging", KeyChord("pageup")),
    ActionDefinition("jog_z_negative", "Jog Z−", "Jogging", "jogging", KeyChord("pagedown")),
    ActionDefinition("jog_a_positive", "Jog A+", "Jogging", "jogging", None),
    ActionDefinition("jog_a_negative", "Jog A−", "Jogging", "jogging", None),
    ActionDefinition("mdi_send", "Send Command", "MDI", "mdi", KeyChord("enter", ("ctrl",))),
    ActionDefinition("mdi_newline", "Insert New Line", "MDI", "mdi", KeyChord("enter")),
)
ACTION_BY_ID = {action.action_id: action for action in ACTIONS}
BINDING_GROUPS = tuple(
    (category, tuple(action.action_id for action in ACTIONS if action.category == category))
    for category in ("Global", "Jogging", "MDI")
)


def key_name_from_code(key_code: int, codepoint: str = "") -> str | None:
    if key_code in PREFERRED_KEY_NAMES:
        return PREFERRED_KEY_NAMES[key_code]
    if codepoint and len(codepoint) == 1 and codepoint.isprintable():
        return codepoint.lower()
    if 32 <= key_code <= 126:
        return chr(key_code).lower()
    names = [name for name, code in Keyboard.keycodes.items() if code == key_code]
    if not names:
        return None
    return min(names, key=lambda name: (len(name), name))


def is_modifier_key_event(key_code: int, scancode: int | None = None) -> bool:
    return key_code in MODIFIER_KEY_CODES or scancode in MODIFIER_SCANCODES


def chord_from_event(key_code: int, modifiers, codepoint: str = "", scancode: int | None = None) -> KeyChord | None:
    if is_modifier_key_event(key_code, scancode):
        return None
    key_name = key_name_from_code(key_code, codepoint)
    if key_name is None:
        return None
    try:
        return KeyChord(key_name, tuple(modifiers))
    except ValueError:
        return None


def format_chord_parts(chord: KeyChord, platform: str | None = None) -> tuple[str, ...]:
    """Return the display label for each physical key in a chord."""
    modifier_labels = {
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "meta": "Cmd" if (platform or sys.platform) == "darwin" else "Meta",
        "primary": "Cmd" if (platform or sys.platform) == "darwin" else "Ctrl",
    }
    key_labels = {
        "enter": "Enter",
        "escape": "Escape",
        "spacebar": "Space",
        "pageup": "Page Up",
        "pagedown": "Page Down",
        "left": "Left",
        "right": "Right",
        "up": "Up",
        "down": "Down",
        "tab": "Tab",
        ",": ",",
    }
    parts = [modifier_labels[modifier] for modifier in chord.modifiers]
    key_label = key_labels.get(chord.key, chord.key.upper())
    parts.append(key_label)
    return tuple(parts)


def format_chord(chord: KeyChord | None, platform: str | None = None) -> str:
    if chord is None:
        return "Unbound"
    return "+".join(format_chord_parts(chord, platform))


def _contexts_overlap(first: str, second: str) -> bool:
    return first == second or "global" in (first, second)


class ShortcutBindings:
    """Resolved shortcut map with sparse, forward-compatible persistence."""

    def __init__(
        self,
        bindings: dict[str, KeyChord | None] | None = None,
        *,
        invert_y_axis_jogging: bool = False,
    ):
        defaults = {action.action_id: action.default for action in ACTIONS}
        if bindings:
            defaults.update({key: value for key, value in bindings.items() if key in ACTION_BY_ID})
        self._bindings = dict(defaults)
        self.set_invert_y_axis_jogging(invert_y_axis_jogging)

    @classmethod
    def from_json(cls, raw: str | None, *, invert_y_axis_jogging: bool = False) -> ShortcutBindings:
        if not raw:
            return cls(invert_y_axis_jogging=invert_y_axis_jogging)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("version") != CONFIG_VERSION:
                raise ValueError("Unsupported shortcut config version")
            overrides = payload.get("bindings", {})
            if not isinstance(overrides, dict):
                raise ValueError("Shortcut bindings must be an object")
            parsed = {}
            for action_id, value in overrides.items():
                if action_id not in ACTION_BY_ID:
                    continue
                try:
                    parsed[action_id] = None if value is None else KeyChord.from_dict(value)
                except (TypeError, ValueError) as exc:
                    logger.warning("Ignoring invalid keyboard shortcut %s: %s", action_id, exc)
            bindings = cls(parsed, invert_y_axis_jogging=invert_y_axis_jogging)
            for action in ACTIONS:
                chord = bindings.binding_for(action.action_id)
                if chord is not None and bindings.conflict_for(action.action_id, chord) is not None:
                    raise ValueError("Shortcut config contains conflicting bindings")
            return bindings
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Invalid keyboard_shortcuts config, using defaults: %s", exc)
            return cls(invert_y_axis_jogging=invert_y_axis_jogging)

    def to_json(self) -> str:
        overrides = {}
        for action in ACTIONS:
            binding = self._bindings[action.action_id]
            if binding == action.default:
                continue
            overrides[action.action_id] = None if binding is None else binding.to_dict()
        if not overrides:
            return ""
        return json.dumps({"version": CONFIG_VERSION, "bindings": overrides}, separators=(",", ":"), sort_keys=True)

    def copy(self) -> ShortcutBindings:
        return ShortcutBindings(
            dict(self._bindings),
            invert_y_axis_jogging=self._invert_y_axis_jogging,
        )

    def set_invert_y_axis_jogging(self, inverted: bool) -> None:
        self._invert_y_axis_jogging = inverted
        self._defaults = {action.action_id: action.default for action in ACTIONS}
        self._defaults["jog_y_positive"] = KeyChord("up" if inverted else "down")
        self._defaults["jog_y_negative"] = KeyChord("down" if inverted else "up")

    def default_for(self, action_id: str) -> KeyChord | None:
        return self._defaults[action_id]

    def binding_for(self, action_id: str) -> KeyChord | None:
        return self._bindings[action_id]

    def action_for(self, chord: KeyChord, context: str) -> ActionDefinition | None:
        for action in ACTIONS:
            if action.context != context:
                continue
            binding = self._bindings[action.action_id]
            if binding is not None and binding.matches(chord):
                return action
        return None

    def conflict_for(self, action_id: str, chord: KeyChord) -> ActionDefinition | None:
        target = ACTION_BY_ID[action_id]
        for action in ACTIONS:
            if action.action_id == action_id or not _contexts_overlap(target.context, action.context):
                continue
            binding = self._bindings[action.action_id]
            if binding is not None and binding.matches(chord):
                return action
        return None

    def assign(self, action_id: str, chord: KeyChord | None) -> None:
        if action_id not in ACTION_BY_ID:
            raise KeyError(action_id)
        if chord is not None:
            conflict = self.conflict_for(action_id, chord)
            if conflict is not None:
                raise ValueError(f"{format_chord(chord)} is already assigned to {conflict.label}")
        self._bindings[action_id] = chord

    def reset(self, action_id: str) -> None:
        self._bindings[action_id] = self._defaults[action_id]

    def reset_all(self) -> None:
        self._bindings = dict(self._defaults)
