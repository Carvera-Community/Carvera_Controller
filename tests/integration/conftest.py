"""Integration test fixtures for Kivy app testing.

Provides a session-scoped fixture that boots the full MakeraApp with mocked
hardware, plus helpers for screenshot capture and comparison.
"""

import os
import shutil
import tempfile
import threading
import time
from contextlib import suppress

# Isolate Kivy config to a temp directory so tests don't mutate the user's
# real Kivy config. Must be set BEFORE any Kivy import.
_kivy_home = tempfile.mkdtemp(prefix="kivy_test_")
os.environ["KIVY_HOME"] = _kivy_home
os.environ.setdefault("KIVY_DPI", "96")
os.environ.setdefault("KIVY_METRICS_DENSITY", "1")
os.environ.setdefault("KIVY_METRICS_FONTSCALE", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_LOG_MODE", "MIXED")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "0")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

import pytest
from kivy.animation import Animation
from kivy.config import Config
from PIL import Image, ImageChops

# Set window size before the window is created
Config.set("graphics", "width", "1920")
Config.set("graphics", "height", "1080")
Config.set("graphics", "fullscreen", "0")
Config.set("kivy", "exit_on_escape", "0")
Config.set("kivy", "pause_on_minimize", "0")
Config.set("input", "mouse", "mouse,multitouch_on_demand")

import kivy.uix.widget as kivy_widget
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.lang import Builder

from tests.integration.visual_references import create_visual_reference_config

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
VISUAL_MAX_CHANNEL_DELTA = 4
VISUAL_MAX_CHANGED_PIXEL_RATIO = 0.005


def _start_animation_at_end(self, widget):
    for prop_name, value in self.animated_properties.items():
        with suppress(Exception):
            setattr(widget, prop_name, value)
    with suppress(Exception):
        self.dispatch("on_complete", widget)


Animation.start = _start_animation_at_end


def _disable_scrolling_label_marquee():
    from carveracontroller.custom_widgets import ScrollingLabel

    for method_name in ("_start_marquee", "_start_marquee_anim", "_evaluate_fit", "_check_after_shrink"):

        def _noop(self, *_args, **_kwargs):
            return None

        _noop.__name__ = method_name
        setattr(ScrollingLabel, method_name, _noop)


def _safe_widget_destructor(uid, _ref):
    if uid not in kivy_widget._widget_destructors:
        return
    del kivy_widget._widget_destructors[uid]
    Builder.unbind_widget(uid)


kivy_widget._widget_destructor = _safe_widget_destructor


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


def force_render_to_backbuffer():
    """Render the current Kivy frame into the back buffer for screenshot capture."""
    from kivy.core.window import Window

    Window.canvas.ask_update()
    Builder.sync()
    Clock.tick_draw()
    Builder.sync()
    Window.dispatch("on_draw")


def apply_machine_state(app):
    """Push current CNC.vars into the UI widgets and let the UI settle.

    Sets config_loaded=True to prevent updateStatus from attempting to
    download config from a non-existent machine when state is "Idle".
    """
    app.root.config_loaded = True
    app.root.updateStatus()
    freeze_animated_status(app)
    pump_frames(5)
    freeze_animated_status(app)


def show_content_page(app, page_name):
    """Switch the main content page and wait for the visual tree to settle."""
    app.root.content.transition.direction = "right" if page_name == "File" else "left"
    app.root.content.current = page_name
    pump_frames(5)


def stabilize_gcode_viewer(app):
    """Render loaded gcode from the app's default full-toolpath view."""
    viewer = app.root.gcode_viewer
    viewer.set_display_offset(app.root.content.x, app.root.content.y)
    app.root.gcode_play_to_end()
    viewer.restore_default_view()
    viewer._on_frame_tick(0)
    viewer.canvas.ask_update()
    pump_frames(5)


def freeze_animated_status(app):
    """Pin cyclic/blinking status widgets to deterministic display states."""
    Clock.unschedule(app.root.blink_state)
    Clock.unschedule(app.root.switch_status)
    app.root.heartbeat_time = time.time()
    app.root.status_index = 0
    app.root.holding = 0
    app.root.pausing = 0
    app.root.waiting = 0
    app.root.tooling = 0
    for slot in getattr(app.root, "control_list", {}).values():
        if isinstance(slot, list) and slot:
            slot[0] = 0
    app.root.updateStatus()


def stop_residual_marquees(app):
    """Reset ScrollingLabel offsets that may have been scheduled before the freeze."""
    from kivy.core.window import Window

    from carveracontroller.custom_widgets import ScrollingLabel

    def reset_in_tree(widget):
        if isinstance(widget, ScrollingLabel):
            if widget._marquee_anim is not None:
                with suppress(Exception):
                    widget._marquee_anim.cancel(widget)
                widget._marquee_anim = None
            widget.scroll_x = 0
        for child in widget.children:
            reset_in_tree(child)

    reset_in_tree(app.root)
    for child in list(Window.children):
        reset_in_tree(child)


def redraw_gcode_viewer(app):
    """Push the loaded gcode viewer to a settled frame before screenshot capture."""
    viewer = getattr(app.root, "gcode_viewer", None)
    if viewer is None or viewer.lengths is None or len(viewer.lengths) <= 1:
        return
    with suppress(Exception):
        viewer.display_count = viewer.get_total_distance()
    viewer.dynamic_display = False
    viewer._scene_dirty = True
    viewer._proj_dirty = True
    with suppress(Exception):
        viewer._on_frame_tick(None)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_kivy_home, ignore_errors=True)


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

    freeze_animated_status(app)
    stop_residual_marquees(app)
    redraw_gcode_viewer(app)
    EventLoop.idle()
    Clock.tick()
    force_render_to_backbuffer()
    filepath = os.path.join(OUTPUT_DIR, f"{name}.png")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Window.screenshot inserts a counter: "name.png" -> "name0001.png"
    actual_path = Window.screenshot(name=filepath)

    # Rename the counter-suffixed file to the exact path we want
    if actual_path and actual_path != filepath:
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(actual_path, filepath)

    return filepath


def save_or_compare_reference(name, visual_reference_config, update_references):
    if update_references:
        save_reference(name, visual_reference_config)
    else:
        compare_screenshots(name, visual_reference_config)


def compare_screenshots(name, visual_reference_config):
    """Compare an output screenshot against its reference baseline.

    Saves a diff image on failure for debugging.
    """
    visual_reference_config.skip_if_missing(name)
    ref_path = visual_reference_config.reference_path(name)
    out_path = os.path.join(OUTPUT_DIR, f"{name}.png")

    ref = Image.open(ref_path).convert("RGB")
    out = Image.open(out_path).convert("RGB")

    assert ref.size == out.size, f"Screenshot size mismatch: reference={ref.size}, actual={out.size}"

    diff = ImageChops.difference(ref, out)
    bbox = diff.getbbox()

    if bbox is not None:
        max_channel_delta = max(channel_max for _channel_min, channel_max in diff.getextrema())
        changed_pixels = sum(1 for pixel in diff.getdata() if pixel != (0, 0, 0))
        changed_pixel_ratio = changed_pixels / (ref.size[0] * ref.size[1])
        if max_channel_delta <= VISUAL_MAX_CHANNEL_DELTA:
            return

        diff_path = os.path.join(OUTPUT_DIR, f"{name}_DIFF.png")
        diff.save(diff_path)
        amplified_diff_path = os.path.join(OUTPUT_DIR, f"{name}_DIFF_X16.png")
        diff.point(lambda value: min(value * 16, 255)).save(amplified_diff_path)
        changed_percent = changed_pixel_ratio * 100
        pytest.fail(
            f"Visual difference detected in '{name}'. Diff region: {bbox}. "
            f"Changed pixels: {changed_pixels} ({changed_percent:.3f}%), "
            f"max channel delta: {max_channel_delta}. See {diff_path}."
        )


def save_reference(name, visual_reference_config):
    """Copy an output screenshot to become the new reference baseline."""
    src = os.path.join(OUTPUT_DIR, f"{name}.png")
    dst = visual_reference_config.reference_path(name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def pytest_addoption(parser):
    parser.addoption(
        "--update-references",
        action="store_true",
        default=False,
        help="Update reference screenshots in the selected visual reference mode.",
    )
    parser.addoption(
        "--visual-reference-mode",
        choices=("local", "committed"),
        default="local",
        help=(
            "Reference screenshot source: local uses the ignored host-local directory, "
            "committed uses tracked Linux container baselines."
        ),
    )
    parser.addoption(
        "--visual-run",
        action="store_true",
        default=False,
        help="Run visual regression tests. The visual runner sets this while isolating each test process.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "visual_reference(name): screenshot reference name used for early missing-reference checks.",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    marker = item.get_closest_marker("visual_reference")
    if marker is None or not item.config.getoption("--visual-run"):
        return

    reference_config = create_visual_reference_config(
        item.config.getoption("--visual-reference-mode"),
        item.config.getoption("--update-references"),
    )
    reference_config.skip_if_missing(marker.args[0])


def pytest_collection_modifyitems(items):
    run_visual = items[0].config.getoption("--visual-run") if items else False
    skip_visual = pytest.mark.skip(reason="run visual regression tests with scripts/visual_tests.py")
    for item in items:
        path = item.path
        if run_visual or not (path.name.startswith("test_visual_regression") and path.suffix == ".py"):
            continue
        item.add_marker(skip_visual)


@pytest.fixture(scope="session")
def update_references(request):
    return request.config.getoption("--update-references")


@pytest.fixture(scope="session")
def visual_reference_config(request):
    return create_visual_reference_config(
        request.config.getoption("--visual-reference-mode"),
        request.config.getoption("--update-references"),
    )


@pytest.fixture(autouse=True)
def disable_modal_animations(monkeypatch):
    """Make popup screenshots deterministic by disabling ModalView fades."""
    from kivy.uix.modalview import ModalView

    original_open = ModalView.open
    original_dismiss = ModalView.dismiss

    def open_without_animation(self, *_args, **kwargs):
        kwargs["animation"] = False
        return original_open(self, *_args, **kwargs)

    def dismiss_without_animation(self, *_args, **kwargs):
        kwargs["animation"] = False
        return original_dismiss(self, *_args, **kwargs)

    monkeypatch.setattr(ModalView, "open", open_without_animation)
    monkeypatch.setattr(ModalView, "dismiss", dismiss_without_animation)


@pytest.fixture(scope="session")
def kivy_app():
    """Boot the full MakeraApp with mocked hardware.

    The visual runner invokes pytest once per screenshot test, so this
    session-scoped fixture creates one app instance per isolated process.
    """

    import carveracontroller.main as main_module
    from carveracontroller import translation
    from carveracontroller.main import (
        MakeraApp,
        app_base_path,
        load_app_configs,
        load_constants,
        load_halt_translations,
        register_fonts,
        register_images,
        set_config_defaults,
    )
    from carveracontroller.translation import tr

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

    EventLoop.ensure_window()
    _disable_scrolling_label_marquee()
    app = MakeraApp()
    app._run_prepare()

    from kivy.uix.screenmanager import NoTransition

    app.root.content.transition = NoTransition()
    app.root.cmd_manager.transition = NoTransition()

    pump_frames(10)
    freeze_animated_status(app)

    yield app

    app.root.stop.set()
    app.stop()
    EventLoop.close()
