"""SDL joystick hotplug must follow a controller that reconnects with a new instance id."""

import sys

import pytest

from carveracontroller.addons.pendant import sdl_joystick_hotplug as hotplug


class _WasInit:
    def __init__(self, mask: int) -> None:
        self._mask = mask

    def __call__(self, _flags: int) -> int:
        return self._mask


class _Dll:
    def __init__(self, mask: int) -> None:
        self.SDL_WasInit = _WasInit(mask)


def test_darwin_candidates_try_the_loaded_sdl_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hotplug.sys, "platform", "darwin")
    monkeypatch.setattr(hotplug, "_kivy_window_module_path", lambda: "/kivy/window.so")
    monkeypatch.setattr(hotplug, "_darwin_loaded_sdl2_paths", lambda: ["/kivy/.dylibs/SDL2"])
    monkeypatch.setattr(hotplug, "find_library", lambda _name: "/opt/homebrew/lib/libSDL2.dylib")

    paths = hotplug._sdl2_candidate_paths()

    assert paths[0] == "/kivy/.dylibs/SDL2"
    assert "/opt/homebrew/lib/libSDL2.dylib" in paths[1:]


@pytest.mark.skipif(sys.platform != "darwin", reason="dyld image list")
def test_loaded_sdl_is_the_kivy_copy():
    hotplug._kivy_window_module_path()
    paths = hotplug._darwin_loaded_sdl2_paths()
    assert any(path.endswith("/kivy/.dylibs/SDL2") for path in paths)


def test_load_sdl2_skips_a_different_uninitialized_library(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hotplug, "_sdl2_dll", None)
    monkeypatch.setattr(hotplug, "_sdl2_candidate_paths", lambda: ["other-sdl", "kivy-sdl"])
    opened: list[str] = []

    def open_library(path: str) -> _Dll:
        opened.append(path)
        mask = 0 if path == "other-sdl" else hotplug._KIVY_SDL_BITS
        return _Dll(mask)

    monkeypatch.setattr(hotplug, "CDLL", open_library)

    loaded = hotplug._load_sdl2()

    assert opened == ["other-sdl", "kivy-sdl"]
    assert loaded is not None
    assert loaded.SDL_WasInit(0) == hotplug._KIVY_SDL_BITS


def test_rescan_forgets_a_stick_that_is_no_longer_present(monkeypatch: pytest.MonkeyPatch):
    from carveracontroller.addons.pendant.gamepad import GamepadManager

    manager = GamepadManager.__new__(GamepadManager)
    manager._active_stick = 0
    manager._connected = True
    manager._held_axes = {}
    manager._axis_values = {}
    manager._held_triggers = {}
    manager._hat_held = {}
    manager.on_jog_stop = None
    monkeypatch.setattr(
        "carveracontroller.addons.pendant.gamepad.ensure_sdl_joysticks_open",
        lambda: {4},
    )

    manager._rescan_sdl_joysticks(0)

    assert manager._active_stick is None
    assert manager._connected is False


def test_rescan_keeps_the_stick_that_is_still_present(monkeypatch: pytest.MonkeyPatch):
    from carveracontroller.addons.pendant.gamepad import GamepadManager

    manager = GamepadManager.__new__(GamepadManager)
    manager._active_stick = 0
    manager._connected = True
    monkeypatch.setattr(
        "carveracontroller.addons.pendant.gamepad.ensure_sdl_joysticks_open",
        lambda: {0},
    )

    manager._rescan_sdl_joysticks(0)

    assert manager._active_stick == 0
    assert manager._connected is True
