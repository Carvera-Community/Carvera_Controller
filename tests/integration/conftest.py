"""Integration test fixtures for Kivy app testing.

Provides a session-scoped fixture that boots the full MakeraApp with mocked
hardware, plus helpers for screenshot capture and comparison.
"""

import os
import shutil
import tempfile
import threading
import time

# Isolate Kivy config to a temp directory so tests don't mutate the user's
# real Kivy config. Must be set BEFORE any Kivy import.
_kivy_home = tempfile.mkdtemp(prefix="kivy_test_")
os.environ["KIVY_HOME"] = _kivy_home
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_LOG_MODE", "MIXED")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "0")

import pytest
from PIL import Image, ImageChops

from kivy.config import Config

# Set window size before the window is created
Config.set("graphics", "width", "1920")
Config.set("graphics", "height", "1080")
Config.set("graphics", "fullscreen", "0")
Config.set("kivy", "exit_on_escape", "0")
Config.set("kivy", "pause_on_minimize", "0")
Config.set("input", "mouse", "mouse,multitouch_on_demand")

from kivy.base import EventLoop
from kivy.clock import Clock

REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "reference")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def pump_frames(count=10, sleep=0):
    """Advance the Kivy event loop by `count` frames.

    This allows Clock.schedule_once callbacks to fire and the UI to settle.
    If `sleep` is given (seconds), sleep that long between frames so that
    Kivy's clock sees real elapsed time — needed for animations and
    interval-scheduled callbacks.
    """
    for _ in range(count):
        if sleep:
            time.sleep(sleep)
        EventLoop.idle()
        Clock.tick()


def apply_machine_state(app):
    """Push current CNC.vars into the UI widgets and let the UI settle.

    Sets config_loaded=True to prevent updateStatus from attempting to
    download config from a non-existent machine when state is "Idle".
    """
    app.root.config_loaded = True
    app.root.updateStatus()
    pump_frames(20, sleep=0.05)  # 20 frames * 50ms = ~1 second


def load_gcode_file(app, filepath):
    """Load a gcode file into the app, replicating the threaded load flow.

    load_gcode_file must run in a background thread because it blocks on
    load_event.wait() while the UI thread processes scheduled callbacks.
    We pump frames from here to service those callbacks.
    """
    loader = threading.Thread(target=app.root.load_gcode_file, args=(filepath,), daemon=True)
    loader.start()
    # Pump frames while the loader thread runs, so Clock.schedule_once
    # callbacks (load_start, load_page, load_gcodes, load_end) get processed
    while loader.is_alive():
        EventLoop.idle()
        Clock.tick()
        time.sleep(0.02)
    # Let the UI fully settle after loading completes
    pump_frames(30, sleep=0.05)
    # Dismiss any popups that the load process opened (progress, file browser)
    if app.root.progress_popup.parent:
        app.root.progress_popup.dismiss()
    if app.root.file_popup.parent:
        app.root.file_popup.dismiss()
    pump_frames(10, sleep=0.05)


def capture_screenshot(app, name):
    """Capture the full window to a PNG file in the output directory.

    Uses Window.screenshot() which captures the OpenGL framebuffer, including
    popups and overlays that are children of Window rather than app.root.
    Window.screenshot() auto-appends a counter to the filename, so we rename
    the result to the exact path we want.
    """
    from kivy.core.window import Window

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{name}.png")

    # Window.screenshot inserts a counter: "name.png" -> "name0001.png"
    actual_path = Window.screenshot(name=filepath)

    # Rename the counter-suffixed file to the exact path we want
    if actual_path and actual_path != filepath:
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(actual_path, filepath)

    return filepath


def compare_screenshots(name):
    """Compare an output screenshot against its reference baseline.

    Saves a diff image on failure for debugging.
    """
    ref_path = os.path.join(REFERENCE_DIR, f"{name}.png")
    out_path = os.path.join(OUTPUT_DIR, f"{name}.png")

    if not os.path.exists(ref_path):
        pytest.skip(f"No reference screenshot for '{name}'. " f"Run with --update-references to create one.")

    ref = Image.open(ref_path).convert("RGB")
    out = Image.open(out_path).convert("RGB")

    assert ref.size == out.size, f"Screenshot size mismatch: reference={ref.size}, actual={out.size}"

    diff = ImageChops.difference(ref, out)
    bbox = diff.getbbox()

    if bbox is not None:
        diff_path = os.path.join(OUTPUT_DIR, f"{name}_DIFF.png")
        diff.save(diff_path)
        pytest.fail(f"Visual difference detected in '{name}'. " f"Diff region: {bbox}. See {diff_path}")


def save_reference(name):
    """Copy an output screenshot to become the new reference baseline."""
    os.makedirs(REFERENCE_DIR, exist_ok=True)
    src = os.path.join(OUTPUT_DIR, f"{name}.png")
    dst = os.path.join(REFERENCE_DIR, f"{name}.png")
    shutil.copy2(src, dst)


def pytest_addoption(parser):
    parser.addoption(
        "--update-references",
        action="store_true",
        default=False,
        help="Update reference screenshots instead of comparing against them.",
    )


@pytest.fixture(scope="session")
def update_references(request):
    return request.config.getoption("--update-references")


@pytest.fixture(scope="session")
def kivy_app():
    """Boot the full MakeraApp with mocked hardware.

    This mirrors the startup sequence in main.py:main() but avoids calling
    app.run(), which would block forever in the Kivy event loop. Instead we
    use _run_prepare() to build the widget tree and manually pump frames.
    """
    from carveracontroller import translation
    from carveracontroller.main import (
        MakeraApp,
        load_constants,
        set_config_defaults,
        load_app_configs,
        load_halt_translations,
        app_base_path,
        register_fonts,
        register_images,
    )
    from carveracontroller.translation import tr
    import carveracontroller.main as main_module

    # Replicate main() startup sequence (main.py:6470-6494)
    translation.init(None)
    load_constants()
    set_config_defaults(tr.lang)
    load_app_configs()

    # Suppress hardware access and network requests AFTER config sections exist
    Config.set("carvera", "show_update", "0")
    Config.set("carvera", "address", "")
    Config.set("carvera", "pendant_type", "None")

    main_module.HALT_REASON = load_halt_translations(tr)

    base_path = app_base_path()
    register_fonts(base_path)
    register_images(base_path)

    # Create the app and build its widget tree without entering the event loop
    EventLoop.ensure_window()
    app = MakeraApp()
    app._run_prepare()

    # Disable screen transition animations so page switches are instant
    from kivy.uix.screenmanager import NoTransition

    app.root.content.transition = NoTransition()
    app.root.cmd_manager.transition = NoTransition()

    # Let the UI settle with real elapsed time so timed callbacks complete
    # (blink_state @ 0.5s, viewport updates @ 0.25s, etc.)
    pump_frames(60, sleep=0.05)  # 60 frames * 50ms = ~3 seconds

    yield app

    # Teardown: stop background threads and close the event loop
    app.root.stop.set()  # signals monitorSerial to exit
    app.stop()
    EventLoop.close()

    # Clean up temp Kivy home
    shutil.rmtree(_kivy_home, ignore_errors=True)
