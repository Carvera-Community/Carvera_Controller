"""Gamepad bindings for stick jog and one-direction jog inputs."""

from carveracontroller.addons.pendant.gamepad import (
    AXIS_MAX,
    GamepadBindings,
    GamepadManager,
    apply_captured_binding,
    captured_axis_binding,
)


def _empty_bindings():
    return {"axes": {}, "triggers": {}, "buttons": {}, "hat": {}}


def _manager(bindings):
    manager = GamepadManager.__new__(GamepadManager)
    manager._bindings = GamepadBindings(bindings)
    manager._deadzone = 0.15
    manager._active_stick = 0
    manager._connected = True
    manager._axis_values = {}
    manager._held_axes = {}
    manager._held_triggers = {}
    manager._hat_held = {}
    manager._paused = False
    manager.on_connect = None
    events = {"jog": [], "stop": [], "button": []}
    manager.on_jog_axis = lambda action, value: events["jog"].append((action, value))
    manager.on_jog_stop = lambda action: events["stop"].append(action)
    manager.on_button_action = lambda action: events["button"].append(action)
    return manager, events


def test_directional_button_press_and_release():
    manager, events = _manager(_empty_bindings() | {"buttons": {"4": "jog_z_plus", "5": "jog_z_minus"}})

    manager._on_joy_button_down(None, 0, 4)

    assert events["jog"] == [("jog_z_plus", 1.0)]
    assert manager.is_axis_held("jog_z_plus")
    assert manager.held_axis_direction("jog_z_plus") == 1

    manager._on_joy_button_up(None, 0, 4)

    assert events["stop"] == ["jog_z_plus"]
    assert not manager.is_axis_held("jog_z_plus")


def test_plus_and_minus_buttons_do_not_cancel_each_other():
    manager, events = _manager(_empty_bindings() | {"buttons": {"4": "jog_z_plus", "5": "jog_z_minus"}})

    manager._on_joy_button_down(None, 0, 4)
    manager._on_joy_button_down(None, 0, 5)
    manager._on_joy_button_up(None, 0, 5)

    assert events["jog"] == [("jog_z_plus", 1.0), ("jog_z_minus", -1.0)]
    assert events["stop"] == ["jog_z_minus"]
    assert manager.is_axis_held("jog_z_plus")
    assert manager.held_axis_direction("jog_z_minus") == 0


def test_repeated_button_down_does_not_start_again():
    manager, events = _manager(_empty_bindings() | {"buttons": {"4": "jog_x_minus"}})

    manager._on_joy_button_down(None, 0, 4)
    manager._on_joy_button_down(None, 0, 4)

    assert events["jog"] == [("jog_x_minus", -1.0)]
    assert events["stop"] == []


def test_one_shot_buttons_are_unchanged():
    manager, events = _manager(_empty_bindings() | {"buttons": {"0": "stop"}})

    manager._on_joy_button_down(None, 0, 0)
    manager._on_joy_button_up(None, 0, 0)

    assert events["button"] == ["stop"]
    assert events["jog"] == []
    assert events["stop"] == []


def test_paused_manager_stops_a_held_button_and_ignores_further_presses():
    manager, events = _manager(_empty_bindings() | {"buttons": {"4": "jog_z_plus"}})
    manager._on_joy_button_down(None, 0, 4)

    manager.paused = True

    assert events["stop"] == ["jog_z_plus"]
    assert not manager.is_axis_held("jog_z_plus")

    events["jog"].clear()
    events["stop"].clear()
    manager._on_joy_button_down(None, 0, 4)
    manager._on_joy_button_up(None, 0, 4)
    manager.paused = False
    manager._on_joy_button_up(None, 0, 4)

    assert events["jog"] == []
    assert events["stop"] == []


def test_directional_trigger_starts_and_stops_with_the_deadzone():
    bindings = _empty_bindings()
    bindings["triggers"] = {"2:+": "jog_a_plus", "3:-": "jog_a_minus"}
    manager, events = _manager(bindings)

    manager._on_joy_axis(None, 0, 2, AXIS_MAX)
    manager._on_joy_axis(None, 0, 2, AXIS_MAX)
    manager._on_joy_axis(None, 0, 2, 0)

    assert events["jog"] == [("jog_a_plus", 1.0)]
    assert events["stop"] == ["jog_a_plus"]

    events["jog"].clear()
    events["stop"].clear()
    manager._on_joy_axis(None, 0, 3, -AXIS_MAX)
    manager._on_joy_axis(None, 0, 3, 0)

    assert events["jog"] == [("jog_a_minus", -1.0)]
    assert events["stop"] == ["jog_a_minus"]


def test_one_shot_trigger_does_not_jog():
    manager, events = _manager(_empty_bindings() | {"triggers": {"2:+": "feed_plus"}})

    manager._on_joy_axis(None, 0, 2, AXIS_MAX)
    manager._on_joy_axis(None, 0, 2, AXIS_MAX)
    manager._on_joy_axis(None, 0, 2, 0)

    assert events["button"] == ["feed_plus"]
    assert events["jog"] == []
    assert events["stop"] == []


def test_hat_directional_binding_uses_the_action_sign():
    manager, events = _manager(_empty_bindings() | {"hat": {"up": "jog_y_minus"}})

    manager._on_joy_hat(None, 0, 0, (0, 1))
    manager._on_joy_hat(None, 0, 0, (0, 0))

    assert events["jog"] == [("jog_y_minus", -1.0)]
    assert events["stop"] == ["jog_y_minus"]
    assert not manager.is_axis_held("jog_y_minus")


def test_hat_pair_still_jogs_both_directions_of_one_axis():
    manager, events = _manager(_empty_bindings() | {"hat": {"left": "jog_x", "right": "jog_x"}})

    manager._on_joy_hat(None, 0, 0, (-1, 0))
    assert events["jog"] == [("jog_x", -1.0)]
    assert manager.held_axis_direction("jog_x") == -1

    manager._on_joy_hat(None, 0, 0, (1, 0))

    assert events["stop"] == ["jog_x"]
    assert events["jog"][1] == ("jog_x", 1.0)
    assert manager.held_axis_direction("jog_x") == 1


def test_hat_one_shot_is_unchanged():
    manager, events = _manager(_empty_bindings() | {"hat": {"up": "start_pause"}})

    manager._on_joy_hat(None, 0, 0, (0, 1))
    manager._on_joy_hat(None, 0, 0, (0, 0))

    assert events["button"] == ["start_pause"]
    assert events["jog"] == []
    assert events["stop"] == []


def test_stick_jog_is_unchanged():
    manager, events = _manager(_empty_bindings() | {"axes": {"0": "jog_x"}})
    held_during_callback = []
    manager.on_jog_axis = lambda action, value: (
        events["jog"].append((action, value)),
        held_during_callback.append(manager.is_axis_held(action)),
    )

    manager._on_joy_axis(None, 0, 0, AXIS_MAX)
    manager._on_joy_axis(None, 0, 0, AXIS_MAX)
    manager._on_joy_axis(None, 0, 0, 0)

    assert events["jog"] == [("jog_x", 1.0), ("jog_x", 1.0)]
    assert held_during_callback == [True, True]
    assert events["stop"] == ["jog_x"]
    assert not manager.is_axis_held("jog_x")


def test_captured_axis_claims_a_whole_stick_or_one_trigger_half():
    assert captured_axis_binding("jog_x", 0, -0.9) == ("axes", "0")
    assert captured_axis_binding("jog_z_plus", 2, 0.8) == ("triggers", "2:+")
    assert captured_axis_binding("jog_z_minus", 2, -0.8) == ("triggers", "2:-")
    assert captured_axis_binding("feed_plus", 5, 0.8) == ("triggers", "5:+")


def test_binding_a_stick_clears_trigger_halves_on_that_axis():
    bindings = _empty_bindings()
    bindings["triggers"] = {"2:+": "feed_plus", "2:-": "feed_minus", "5:+": "feed_plus"}

    apply_captured_binding(bindings, "jog_z", "axes", "2")

    assert bindings["axes"] == {"2": "jog_z"}
    assert bindings["triggers"] == {"5:+": "feed_plus"}


def test_binding_a_trigger_half_keeps_the_other_half_and_clears_the_stick():
    bindings = _empty_bindings()
    bindings["axes"] = {"2": "jog_z"}
    bindings["triggers"] = {"2:-": "feed_minus"}

    apply_captured_binding(bindings, "jog_z_plus", "triggers", "2:+")

    assert "2" not in bindings["axes"]
    assert bindings["triggers"] == {"2:-": "feed_minus", "2:+": "jog_z_plus"}


def test_binding_a_button_replaces_the_previous_owner_and_the_action():
    bindings = _empty_bindings()
    bindings["buttons"] = {"4": "stop", "5": "jog_z_plus"}

    apply_captured_binding(bindings, "jog_z_plus", "buttons", "4")

    assert bindings["buttons"] == {"4": "jog_z_plus"}


def test_bidirectional_hat_binding_writes_both_directions():
    bindings = _empty_bindings()
    bindings["buttons"] = {"1": "jog_x"}

    apply_captured_binding(bindings, "jog_x", "hat", "left")

    assert bindings["buttons"] == {}
    assert bindings["hat"] == {"left": "jog_x", "right": "jog_x"}


def test_directional_hat_binding_is_a_single_direction():
    bindings = _empty_bindings()

    apply_captured_binding(bindings, "jog_y_plus", "hat", "up")

    assert bindings["hat"] == {"up": "jog_y_plus"}


def test_single_hat_direction_clears_the_rest_of_a_bidirectional_pair():
    bindings = _empty_bindings()
    bindings["hat"] = {"left": "jog_x", "right": "jog_x", "up": "start_pause"}

    apply_captured_binding(bindings, "jog_x_minus", "hat", "left")

    assert bindings["hat"] == {"up": "start_pause", "left": "jog_x_minus"}


def test_replacing_one_hat_direction_clears_a_jog_pair_for_other_actions_too():
    bindings = _empty_bindings()
    bindings["hat"] = {"up": "jog_z", "down": "jog_z"}

    apply_captured_binding(bindings, "start_pause", "hat", "down")

    assert bindings["hat"] == {"down": "start_pause"}
