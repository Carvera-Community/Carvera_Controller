import json

import pytest

from carveracontroller.addons.keyboard_shortcuts.bindings import (
    ACTION_BY_ID,
    KeyChord,
    ShortcutBindings,
    chord_from_event,
    format_chord,
    format_chord_parts,
)

INITIALIZED_EMPTY_JSON = '{"bindings":{},"version":1}'


def test_requested_defaults():
    bindings = ShortcutBindings()

    assert bindings.binding_for("open_start_job") is None
    assert bindings.binding_for("open_online_docs") == KeyChord("f1")
    assert bindings.binding_for("open_mdi") == KeyChord("m", ("ctrl",))
    assert bindings.binding_for("open_gcode") == KeyChord("g", ("ctrl",))
    assert bindings.binding_for("open_file_browser") == KeyChord("o", ("ctrl",))
    assert bindings.binding_for("toggle_keyboard_jogging") == KeyChord("j", ("ctrl",))
    assert bindings.binding_for("switch_jog_mode") == KeyChord("k", ("ctrl",))
    assert bindings.binding_for("mdi_send") == KeyChord("enter", ("ctrl",))
    assert bindings.binding_for("mdi_newline") == KeyChord("enter")
    assert bindings.binding_for("jog_x_positive") == KeyChord("right")
    assert bindings.binding_for("jog_a_positive") is None
    assert bindings.binding_for("jog_y_positive") == KeyChord("down")
    assert bindings.binding_for("jog_y_negative") == KeyChord("up")
    assert ACTION_BY_ID["jog_y_positive"].label == "Jog Y+"
    assert ACTION_BY_ID["jog_y_negative"].label == "Jog Y−"
    assert ACTION_BY_ID["open_gcode"].label == "Open / Focus G-Code"
    assert ACTION_BY_ID["switch_jog_mode"].label == "Switch Jog Mode"
    assert ACTION_BY_ID["switch_jog_mode"].category == "Global"

    inverted = ShortcutBindings(invert_y_axis_jogging=True)
    assert inverted.binding_for("jog_y_positive") == KeyChord("up")
    assert inverted.binding_for("jog_y_negative") == KeyChord("down")
    assert inverted.default_for("jog_y_positive") == KeyChord("up")
    assert inverted.default_for("jog_y_negative") == KeyChord("down")
    assert set(json.loads(inverted.to_json())["bindings"]) == {"jog_y_positive", "jog_y_negative"}

    inverted.reset_all()
    assert inverted.binding_for("jog_y_positive") == KeyChord("up")
    assert inverted.binding_for("jog_y_negative") == KeyChord("down")
    assert set(json.loads(inverted.to_json())["bindings"]) == {"jog_y_positive", "jog_y_negative"}


def test_saved_shortcut_map_does_not_reseed_y_bindings_from_invert():
    initialized = ShortcutBindings.from_json(INITIALIZED_EMPTY_JSON, invert_y_axis_jogging=True)
    assert initialized.binding_for("jog_y_positive") == KeyChord("down")
    assert initialized.binding_for("jog_y_negative") == KeyChord("up")
    assert initialized.default_for("jog_y_positive") == KeyChord("up")
    assert initialized.default_for("jog_y_negative") == KeyChord("down")
    assert initialized.to_json() == INITIALIZED_EMPTY_JSON

    customized = ShortcutBindings.from_json(
        '{"version":1,"bindings":{"open_online_docs":{"key":"f2","modifiers":[]}}}',
        invert_y_axis_jogging=True,
    )
    assert customized.binding_for("jog_y_positive") == KeyChord("down")
    assert customized.binding_for("open_online_docs") == KeyChord("f2")


def test_empty_config_is_uninitialized_and_versioned_empty_is_not():
    assert ShortcutBindings.from_json("").to_json() == INITIALIZED_EMPTY_JSON
    assert ShortcutBindings.from_json(None, invert_y_axis_jogging=True).binding_for("jog_y_positive") == KeyChord("up")
    assert ShortcutBindings.from_json("", invert_y_axis_jogging=True).binding_for("jog_y_positive") == KeyChord("up")


def test_sparse_round_trip_merges_with_defaults():
    bindings = ShortcutBindings()
    bindings.assign("open_online_docs", KeyChord("d", ("ctrl", "shift")))
    bindings.assign("jog_a_positive", KeyChord("]"))

    raw = bindings.to_json()
    payload = json.loads(raw)
    assert set(payload["bindings"]) == {"jog_a_positive", "open_online_docs"}

    restored = ShortcutBindings.from_json(raw)
    assert restored.binding_for("open_online_docs") == KeyChord("d", ("ctrl", "shift"))
    assert restored.binding_for("jog_a_positive") == KeyChord("]")
    assert restored.binding_for("mdi_send") == KeyChord("enter", ("ctrl",))


@pytest.mark.parametrize("raw", ["{", "[]", '{"version":99,"bindings":{}}', '{"version":1,"bindings":[]}'])
def test_invalid_config_falls_back_to_defaults(raw):
    assert ShortcutBindings.from_json(raw).binding_for("open_online_docs") == KeyChord("f1")


def test_unknown_actions_are_ignored_for_forward_compatibility():
    raw = '{"version":1,"bindings":{"future_action":{"key":"f2","modifiers":[]}}}'
    assert ShortcutBindings.from_json(raw).to_json() == INITIALIZED_EMPTY_JSON


def test_conflicting_persisted_config_falls_back_to_defaults():
    raw = '{"version":1,"bindings":{"open_start_job":{"key":"f1","modifiers":[]}}}'

    bindings = ShortcutBindings.from_json(raw)

    assert bindings.binding_for("open_start_job") is None
    assert bindings.binding_for("open_online_docs") == KeyChord("f1")


def test_invalid_persisted_action_does_not_discard_valid_overrides():
    raw = (
        '{"version":1,"bindings":{'
        '"open_online_docs":{"key":"f2","modifiers":[]},'
        '"jog_a_positive":{"key":"not-a-key","modifiers":[]}'
        "}}"
    )

    bindings = ShortcutBindings.from_json(raw)

    assert bindings.binding_for("open_online_docs") == KeyChord("f2")
    assert bindings.binding_for("jog_a_positive") is None


def test_event_normalisation_ignores_lock_modifiers_and_uses_physical_punctuation_key():
    assert chord_from_event(44, ["ctrl", "capslock"], "<") == KeyChord(",", ("ctrl",))
    assert chord_from_event(13, ["numlock"], "\r") == KeyChord("enter")
    assert chord_from_event(271, ["ctrl"], "\r") == KeyChord("enter", ("ctrl",))


@pytest.mark.parametrize(
    "key,scancode,codepoint",
    [
        (305, 224, "i"),  # Kivy left Ctrl keycode
        (306, 228, "ij"),  # Kivy right Ctrl keycode
        (ord("i"), 224, "i"),  # SDL keycode quirk reported by some providers
    ],
)
def test_modifier_keydown_is_not_misread_as_generated_text(key, scancode, codepoint):
    assert chord_from_event(key, ["ctrl"], codepoint, scancode) is None


def test_ctrl_then_enter_captures_the_complete_chord():
    assert chord_from_event(13, ["ctrl"], "\r", 40) == KeyChord("enter", ("ctrl",))


def test_modifier_only_chord_is_rejected_by_the_model():
    with pytest.raises(ValueError, match="non-modifier"):
        KeyChord("lctrl")


def test_modifier_matching_is_exact():
    bindings = ShortcutBindings()
    assert bindings.action_for(KeyChord("enter", ("ctrl",)), "mdi").action_id == "mdi_send"
    assert bindings.action_for(KeyChord("enter", ("ctrl", "shift")), "mdi") is None


def test_primary_modifier_resolves_by_platform():
    chord = KeyChord(",", ("primary",))
    assert chord.matches(KeyChord(",", ("ctrl",)), platform="linux")
    assert chord.matches(KeyChord(",", ("meta",)), platform="darwin")
    assert not chord.matches(KeyChord(",", ("ctrl",)), platform="darwin")
    assert format_chord_parts(chord, platform="linux") == ("Ctrl", ",")
    assert format_chord_parts(chord, platform="darwin") == ("Cmd", ",")
    assert format_chord(chord, platform="linux") == "Ctrl+,"
    assert format_chord(chord, platform="darwin") == "Cmd+,"


def test_conflicts_rejected_in_overlapping_contexts():
    bindings = ShortcutBindings()
    with pytest.raises(ValueError, match="Open Online Documentation"):
        bindings.assign("open_start_job", KeyChord("f1"))


def test_mdi_and_jogging_may_reuse_a_chord():
    bindings = ShortcutBindings()
    bindings.assign("jog_a_positive", KeyChord("enter"))
    assert bindings.binding_for("jog_a_positive") == KeyChord("enter")
    assert bindings.binding_for("mdi_newline") == KeyChord("enter")


def test_unbind_and_reset():
    bindings = ShortcutBindings()
    bindings.assign("open_online_docs", None)
    assert bindings.binding_for("open_online_docs") is None
    bindings.reset("open_online_docs")
    assert bindings.binding_for("open_online_docs") == KeyChord("f1")
    assert bindings.to_json() == INITIALIZED_EMPTY_JSON
