"""Drives the welcome card, practice view, and spotlight steps."""

from __future__ import annotations

import logging
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.uix.screenmanager import NoTransition
from kivy.uix.scrollview import ScrollView

from carveracontroller.Controller import NOT_CONNECTED, STATECOLOR
from carveracontroller.translation import tr
from carveracontroller.ui.file_browser.sources import LOCATION_DEVICE
from carveracontroller.ui.tutorial.overlay import TourOverlay
from carveracontroller.ui.tutorial.placement import Rect
from carveracontroller.ui.tutorial.policy import (
    CONFIRM_DISCONNECT,
    DEMO,
    REFUSE,
    WELCOME,
    resolve_skip,
    tour_start_decision,
)
from carveracontroller.ui.tutorial.session import (
    demo_is_active,
    set_demo_active,
    write_sample_gcode,
)
from carveracontroller.ui.tutorial.steps import TOUR_STEPS, TourStep

logger = logging.getLogger(__name__)

REFUSE_MESSAGE = "Finish or stop the current job before starting the tour."
DISCONNECT_MESSAGE = "The tour uses a simulated machine and will disconnect. Continue?"


def apply_demo_readout(root) -> None:
    """Paint a fixed Idle snapshot over the top bar without touching machine state."""
    app = App.get_running_app()
    if app is None:
        return
    app.state = "Idle"
    status = getattr(root, "status_data_view", None)
    if status is not None:
        status.main_text = "Idle"
        status.minr_text = "practice"
        status.color = STATECOLOR["Idle"]
    _pair(getattr(root, "x_data_view", None), "12.000", "48.000")
    _pair(getattr(root, "y_data_view", None), "8.000", "24.000")
    _pair(getattr(root, "z_data_view", None), "5.000", "-1.000")
    _pair(getattr(root, "a_data_view", None), "0.000", "0.000")
    _pair(getattr(root, "feed_data_view", None), "1000", "100 %")
    spindle = getattr(root, "spindle_laser_data_view", None)
    if spindle is not None:
        spindle.main_text = "0"
        spindle.minr_text = "100 %"
        if hasattr(spindle, "scale"):
            spindle.scale = 100
    _pair(getattr(root, "tool_data_view", None), "1", "TLO: 0.000")
    _pair(getattr(root, "coord_system_data_view", None), "G54", "0.000°")


def _pair(widget, main: str, minor: str) -> None:
    if widget is None:
        return
    widget.main_text = main
    widget.minr_text = minor


class Tutorial:
    """Welcome card, then the practice spotlight"""

    def __init__(self, root):
        self.root = root
        self.phase: str | None = None
        self.index = 0
        self._waiting_on_update = False
        self._coord_open = False
        self._files_open = False
        self._saved_browser: dict | None = None
        self._open_dropdown_name: str | None = None
        self._loaded_demo = False
        self._demo_path = ""
        self._load_thread = None
        self._saved_local = ""
        self._saved_remote = ""
        self._saved_show_bar = False
        self._layout_token = 0
        self._in_layout = False
        self._saved_transitions: dict[int, tuple] = {}
        self.overlay = TourOverlay()
        self.overlay.on_skip = self.skip
        self.overlay.on_back = self.back
        self.overlay.on_next = self.next
        self.overlay.on_show = self.show_around
        self.overlay.on_done = self.finish
        self.overlay.on_usb = lambda: self._finish_and_connect(self._connect_usb)
        self.overlay.on_wifi = lambda: self._finish_and_connect(self._connect_wifi)
        self.overlay.on_ip = lambda: self._finish_and_connect(self._connect_ip)
        self.overlay.on_relayout = self._layout_current

    def schedule_if_needed(self) -> None:
        if Config.get("carvera", "tutorial_completed", fallback="1") != "0":
            return
        Clock.schedule_once(self._maybe_show_welcome, 0)

    def open_from_menu(self) -> None:
        if self.phase is not None:
            return
        decision = self._decision()
        if decision == REFUSE:
            self.root.show_message_popup(REFUSE_MESSAGE, False)
            return
        if decision == CONFIRM_DISCONNECT:
            self._ask_disconnect(self.start_demo)
            return
        self.start_demo()

    def show_around(self) -> None:
        decision = self._decision()
        if decision == REFUSE:
            self.root.show_message_popup(REFUSE_MESSAGE, False)
            return
        if decision == CONFIRM_DISCONNECT:
            self._ask_disconnect(self.start_demo)
            return
        self.start_demo()

    def start_demo(self) -> None:
        if self._decision() == REFUSE:
            self.root.show_message_popup(REFUSE_MESSAGE, False)
            return
        self._disconnect_for_tour()
        app = App.get_running_app()
        self._saved_local = app.selected_local_filename if app is not None else ""
        self._saved_remote = app.selected_remote_filename if app is not None else ""
        self._saved_show_bar = bool(app.show_gcode_ctl_bar) if app is not None else False
        self._loaded_demo = False
        self._demo_path = ""
        self._load_thread = None
        set_demo_active(True)
        self.phase = DEMO
        apply_demo_readout(self.root)
        self.overlay.open()
        self.index = 0
        self._show_step(0)

    def skip(self) -> None:
        if self.phase is None:
            return
        result = resolve_skip(self.phase)
        if result.teardown:
            self.teardown()
        if result.mark_complete:
            self._mark_completed()
        self._close_overlay()

    def finish(self) -> None:
        if self.phase == DEMO:
            self.teardown()
        self._mark_completed()
        self._close_overlay()

    def back(self) -> None:
        if self.phase != DEMO or self.index <= 0:
            return
        self._show_step(self.index - 1)

    def next(self) -> None:
        if self.phase != DEMO:
            return
        if self.index >= len(TOUR_STEPS) - 1:
            self.finish()
            return
        self._show_step(self.index + 1)

    def teardown(self) -> None:
        if not demo_is_active() and self.phase != DEMO:
            return
        set_demo_active(False)
        self._restore_transitions()
        self._close_dropdown()
        self._close_file_browser()
        self._close_coord_popup()
        root = self.root
        # Leave the painted Idle state in place. updateStatus then refreshes the
        # status button back to N/A, and the suppress flag keeps the reconnect popup closed.
        root._suppress_reconnect_popup = True
        try:
            self._restore_files()
            root.updateStatus()
        finally:
            root._suppress_reconnect_popup = False
        self.phase = None

    def _maybe_show_welcome(self, *_args) -> None:
        if self.phase is not None:
            return
        if Config.get("carvera", "tutorial_completed", fallback="1") != "0":
            return
        popup = getattr(self.root, "upgrade_popup", None)
        if popup is not None and getattr(popup, "_is_open", False):
            if not self._waiting_on_update:
                self._waiting_on_update = True
                popup.bind(on_dismiss=self._after_update_popup)
            return
        self._show_welcome()

    def _after_update_popup(self, *_args) -> None:
        self._waiting_on_update = False
        Clock.schedule_once(self._maybe_show_welcome, 0)

    def _show_welcome(self) -> None:
        if self.phase is not None:
            return
        if Config.get("carvera", "tutorial_completed", fallback="1") != "0":
            return
        self.phase = WELCOME
        self.overlay.open()
        self.overlay.show_welcome()

    def _show_step(self, index: int) -> None:
        self.index = index
        step = TOUR_STEPS[index]
        self._prepare_step(step)
        self.overlay.show_step(step, index, len(TOUR_STEPS))
        self._layout_token += 1
        token = self._layout_token
        Clock.schedule_once(lambda _dt, token=token, step=step: self._layout_step(step, token), 0)

    def _prepare_step(self, step: TourStep) -> None:
        root = self.root
        if step.screen:
            self._switch_screen(getattr(root, "content", None), step.screen)
        if step.popup == "coord":
            self._close_file_browser()
            self._close_dropdown()
            self._open_coord_popup()
        elif step.popup == "files":
            if self._coord_open:
                self._close_coord_popup()
            self._close_dropdown()
            self._open_file_browser()
        else:
            if self._coord_open:
                self._close_coord_popup()
            if self._files_open:
                self._close_file_browser()
        if step.dropdown:
            self._open_dropdown(step.dropdown)
        else:
            self._close_dropdown()
        if step.step_id in ("gcode_mdi", "toolpath"):
            self._ensure_sample()
            app = App.get_running_app()
            if app is not None:
                app.show_gcode_ctl_bar = True
            self._switch_screen(getattr(root, "cmd_manager", None), "gcode_cmd_page")

    def _switch_screen(self, manager, name: str) -> None:
        """Change screens without the slide, so the spotlight is not measured mid-animation."""
        if manager is None or manager.current == name:
            return
        key = id(manager)
        if key not in self._saved_transitions and not isinstance(manager.transition, NoTransition):
            self._saved_transitions[key] = (manager, manager.transition)
            manager.transition = NoTransition()
        manager.current = name

    def _restore_transitions(self) -> None:
        for manager, transition in self._saved_transitions.values():
            manager.transition = transition
        self._saved_transitions.clear()

    def _screens_settled(self) -> bool:
        root = self.root
        for manager in (getattr(root, "content", None), getattr(root, "cmd_manager", None)):
            transition = getattr(manager, "transition", None)
            if transition is not None and getattr(transition, "is_active", False):
                return False
        return True

    def _layout_current(self) -> None:
        if self._in_layout:
            return
        if self.phase != DEMO:
            self.overlay.layout_target(self.overlay._target)
            return
        if self.index < 0 or self.index >= len(TOUR_STEPS):
            return
        self._layout_step(TOUR_STEPS[self.index], self._layout_token, attempt=1)

    def _layout_step(self, step: TourStep, token: int, attempt: int = 0) -> None:
        if self._in_layout or token != self._layout_token or self.phase != DEMO:
            return
        self._in_layout = True
        try:
            self._layout_step_body(step, token, attempt)
        finally:
            self._in_layout = False

    def _layout_step_body(self, step: TourStep, token: int, attempt: int) -> None:
        widgets = self._target_widgets(step)
        if step.dropdown and self._open_dropdown_name:
            dd_name = step.dropdown.split(":")[0]
            dropdown = getattr(self.root, dd_name, None)
            if dropdown is not None and dropdown.parent is not None:
                widgets.append(dropdown)
        for widget in widgets:
            _reveal(widget)
        rects = _measure_targets(widgets)
        missing = len(rects) < len(widgets)
        settled = self._screens_settled()
        # A screen slide keeps widget positions moving for about 400ms. Measuring
        # then freezes the spotlight short of where the controls come to rest.
        if settled and attempt >= 2 and rects and (not missing or attempt >= 12):
            self.overlay.layout_targets(rects)
            self.overlay.bring_to_front()
        if attempt < 12 and (not settled or attempt < 5 or missing):
            Clock.schedule_once(
                lambda _dt, token=token, step=step, attempt=attempt: self._layout_step(step, token, attempt + 1),
                0,
            )

    def _target_widgets(self, step: TourStep) -> list:
        root = self.root
        found = []
        popups = (getattr(root, "coord_popup", None), getattr(root, "file_popup", None))
        for target_id in step.target_ids:
            widget = root.ids.get(target_id) if hasattr(root, "ids") else None
            if widget is None:
                for popup in popups:
                    if popup is None:
                        continue
                    widget = popup.ids.get(target_id)
                    if widget is not None:
                        break
            if widget is not None:
                found.append(widget)
        return found

    def _ensure_sample(self) -> None:
        if self._loaded_demo:
            return
        directory = getattr(self.root, "temp_dir", None) or "."
        try:
            self._demo_path = write_sample_gcode(directory)
        except OSError:
            logger.exception("Could not write the practice toolpath")
            return
        app = App.get_running_app()
        if app is not None:
            app.selected_local_filename = self._demo_path
            app.selected_remote_filename = ""
        self._loaded_demo = True
        thread = threading.Thread(target=self.root.load_gcode_file, args=(self._demo_path,), daemon=True)
        self._load_thread = thread
        thread.start()

    def _restore_files(self) -> None:
        app = App.get_running_app()
        if app is not None:
            app.show_gcode_ctl_bar = self._saved_show_bar
        if not self._loaded_demo:
            return
        saved_local = self._saved_local
        saved_remote = self._saved_remote
        self._loaded_demo = False
        # A tiny file can finish on the loader thread before Skip, with load_end
        # still queued. Cancel it so that callback clears the sample instead of
        # painting it after the tour is gone.
        self.root.load_canceled = True
        thread = self._load_thread
        if thread is not None and thread.is_alive():
            threading.Thread(
                target=self._finish_restore_after_load,
                args=(thread, saved_local, saved_remote),
                daemon=True,
            ).start()
            return
        Clock.schedule_once(lambda _dt: self._after_sample_load(saved_local, saved_remote), 0)

    def _finish_restore_after_load(self, thread: threading.Thread, saved_local: str, saved_remote: str) -> None:
        thread.join(timeout=5)
        Clock.schedule_once(lambda _dt: self._after_sample_load(saved_local, saved_remote), 0)

    def _after_sample_load(self, saved_local: str, saved_remote: str) -> None:
        if demo_is_active():
            return
        self._delete_demo_file()
        self._apply_restored_files(saved_local, saved_remote)

    def _apply_restored_files(self, saved_local: str, saved_remote: str, tries: int = 0) -> None:
        if demo_is_active():
            return
        root = self.root
        if getattr(root, "loading_file", False) and tries < 20:
            Clock.schedule_once(lambda _dt: self._apply_restored_files(saved_local, saved_remote, tries + 1), 0.05)
            return
        root.load_canceled = False
        app = App.get_running_app()
        if saved_local and os.path.isfile(saved_local):
            if app is not None:
                app.selected_local_filename = saved_local
                app.selected_remote_filename = saved_remote
            threading.Thread(target=root.load_gcode_file, args=(saved_local,), daemon=True).start()
            return
        if hasattr(root, "clear_selection"):
            root.clear_selection()
        if app is not None:
            app.selected_local_filename = saved_local
            app.selected_remote_filename = saved_remote

    def _delete_demo_file(self) -> None:
        path = self._demo_path
        self._demo_path = ""
        if not path or path == self._saved_local or not os.path.isfile(path):
            return
        try:
            os.remove(path)
        except OSError:
            logger.exception("Could not remove the practice toolpath")

    def _open_file_browser(self) -> None:
        popup = getattr(self.root, "file_popup", None)
        if popup is None:
            return
        self._ensure_sample()
        if not self._files_open:
            self._saved_browser = {
                "location": popup.location,
                "device_dir": popup.device_dir,
                "firmware": popup.firmware_mode,
                "multi": popup.multi_select_mode,
                "search": popup.search_text,
                "highlight": popup._highlight_path,
                "device_paths": list(popup.selected_device_paths),
                "device_file": popup.selected_device_file,
            }
            self._files_open = True
        popup.firmware_mode = False
        popup.multi_select_mode = False
        popup.search_text = ""
        popup.ios_device_mode = False
        popup.title_text = tr._("File Browser")
        popup.location = LOCATION_DEVICE
        directory = os.path.dirname(self._demo_path) if self._demo_path else ""
        if directory:
            popup.list_device_dir(directory, remember=False)
            popup._highlight_path = self._demo_path
            popup._apply_selected_paths([self._demo_path])
            popup._rebuild_list()
            popup._sync_chrome()
        if not popup._is_open:
            popup.open()

    def _close_file_browser(self) -> None:
        if not self._files_open:
            return
        popup = getattr(self.root, "file_popup", None)
        saved = self._saved_browser
        self._files_open = False
        self._saved_browser = None
        if popup is None:
            return
        if saved:
            popup.location = saved["location"]
            popup.device_dir = saved["device_dir"]
            popup.firmware_mode = saved["firmware"]
            popup.multi_select_mode = saved["multi"]
            popup.search_text = saved["search"]
            popup._highlight_path = saved["highlight"]
            popup.selected_device_paths = list(saved["device_paths"])
            popup.selected_device_file = saved["device_file"]
        if popup._is_open:
            popup.dismiss()

    def _open_dropdown(self, spec: str) -> None:
        """Open a status-bar dropdown.  *spec* is ``"attr_name:anchor_id"``."""
        parts = spec.split(":")
        if len(parts) != 2:
            return
        dd_name, anchor_id = parts
        if self._open_dropdown_name == dd_name:
            return
        self._close_dropdown()
        root = self.root
        dropdown = getattr(root, dd_name, None)
        anchor = root.ids.get(anchor_id) if hasattr(root, "ids") else None
        if dropdown is None or anchor is None:
            return
        dropdown.auto_dismiss = False
        dropdown.open(anchor)
        self._open_dropdown_name = dd_name

    def _close_dropdown(self) -> None:
        if self._open_dropdown_name is None:
            return
        dropdown = getattr(self.root, self._open_dropdown_name, None)
        if dropdown is not None:
            dropdown.dismiss()
            dropdown.auto_dismiss = True
        self._open_dropdown_name = None

    def _open_coord_popup(self) -> None:
        popup = self.root.coord_popup
        popup.mode = "Run"
        popup.load_config()
        if not popup._is_open:
            popup.open()
        self._set_run_enabled(False)
        self._coord_open = True

    def _close_coord_popup(self) -> None:
        popup = getattr(self.root, "coord_popup", None)
        self._set_run_enabled(True)
        if popup is not None and self._coord_open and popup._is_open:
            popup.dismiss()
        self._coord_open = False

    def _set_run_enabled(self, enabled: bool) -> None:
        popup = getattr(self.root, "coord_popup", None)
        if popup is None:
            return
        button = popup.ids.get("config_run_action")
        if button is not None:
            button.disabled = not enabled

    def _decision(self) -> str:
        app = App.get_running_app()
        state = app.state if app is not None else NOT_CONNECTED
        controller = getattr(self.root, "controller", None)
        link_busy = False
        if controller is not None:
            link_busy = controller.stream is not None or bool(getattr(controller, "_connecting", False))
        if getattr(self.root, "_usb_connect_in_progress", False):
            link_busy = True
        return tour_start_decision(state, link_busy=link_busy)

    def _disconnect_for_tour(self) -> None:
        root = self.root
        controller = getattr(root, "controller", None)
        busy = controller is not None and (
            controller.stream is not None or bool(getattr(controller, "_connecting", False))
        )
        if not busy and not getattr(root, "_usb_connect_in_progress", False):
            return
        root._suppress_reconnect_popup = True
        try:
            root.close()
        finally:
            root._suppress_reconnect_popup = False

    def _ask_disconnect(self, on_yes) -> None:
        popup = self.root.confirm_popup
        popup.lb_title.text = "Getting started"
        popup.lb_content.text = DISCONNECT_MESSAGE
        popup.cancel = lambda *_a: None
        popup.confirm = lambda *_a: on_yes()
        popup.open()

    def _finish_and_connect(self, action) -> None:
        self.finish()
        Clock.schedule_once(lambda _dt: action(), 0)

    def _connect_usb(self) -> None:
        self.root.open_comports_drop_down(self.root.status_data_view)

    def _connect_wifi(self) -> None:
        self.root.open_wifi_conn_drop_down(self.root.status_data_view)

    def _connect_ip(self) -> None:
        self.root.manually_input_ip()

    def _mark_completed(self) -> None:
        Config.set("carvera", "tutorial_completed", "1")
        Config.write()

    def _close_overlay(self) -> None:
        self._layout_token += 1
        self.overlay.close()
        if self.phase == WELCOME:
            self.phase = None


def _window_rect(widget) -> Rect | None:
    if widget is None:
        return None
    try:
        # to_window() treats the first call as parent coordinates. widget.pos
        # is already in that space; (0, 0) would be the parent's origin.
        # ScrollView children still come out right: their pos is in the
        # unscrolled content, and ScrollView.to_parent adds the scroll.
        x, y = widget.to_window(widget.x, widget.y)
        right, top = widget.to_window(widget.right, widget.top)
    except Exception:
        return None
    return Rect(float(x), float(y), float(right - x), float(top - y))


def _measure_targets(widgets) -> list[Rect]:
    rects: list[Rect] = []
    for widget in widgets:
        rect = _clip_to_scroll(widget, _window_rect(widget))
        if rect is not None and rect.w > 1 and rect.h > 1:
            rects.append(rect)
    return rects


def _clip_to_scroll(widget, rect: Rect | None) -> Rect | None:
    """Drop the part of a target that is scrolled outside its ScrollView."""
    if rect is None:
        return None
    parent = widget.parent
    seen: set[int] = set()
    while parent is not None and id(parent) not in seen:
        seen.add(id(parent))
        if isinstance(parent, ScrollView):
            try:
                x, y = parent.to_window(parent.x, parent.y)
                right, top = parent.to_window(parent.right, parent.top)
            except Exception:
                return rect
            return _intersection(rect, Rect(float(x), float(y), float(right - x), float(top - y)))
        parent = parent.parent
    return rect


def _intersection(a: Rect, b: Rect) -> Rect | None:
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.right(), b.right())
    y1 = min(a.top(), b.top())
    if x1 - x0 <= 1 or y1 - y0 <= 1:
        return None
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _reveal(widget) -> None:
    """Scroll the nearest ScrollView so the target is on screen.

    Window.parent is the window itself, so the walk has to stop on a cycle.
    """
    parent = widget.parent
    seen: set[int] = set()
    while parent is not None and id(parent) not in seen:
        seen.add(id(parent))
        if isinstance(parent, ScrollView):
            parent.scroll_to(widget, animate=False)
            return
        parent = parent.parent
