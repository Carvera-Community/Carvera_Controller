import json
from typing import Callable, Optional

import logging
logger = logging.getLogger(__name__)

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.translation import tr

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import SettingItem
from kivy.uix.spinner import Spinner
from kivy.uix.anchorlayout import AnchorLayout
from kivy.config import Config

from . import gamepad as gamepad_module


class OverrideController:
    def __init__(self, get_value: Callable[[], float],
                 set_value: Callable[[float], None],
                 min_limit: int = 0, max_limit: int = 200,
                 step: int = 10) -> None:
        self._get_value = get_value
        self._set_value = set_value
        self._min_limit = min_limit
        self._max_limit = max_limit
        self._step = step

    def on_increase(self) -> None:
        new_value = min(self._get_value() + self._step, self._max_limit)
        self._set_value(new_value)

    def on_decrease(self) -> None:
        new_value = max(self._get_value() - self._step, self._min_limit)
        self._set_value(new_value)

class Pendant:
    """
    Base class for pendant devices.
    
    The pendant system supports UI updates through callback functions:
    - update_ui_on_button_press: Called when any button is pressed with the button action
    - update_ui_on_jog_stop: Called when jogging stops
    
    Button actions include:
    - "reset", "stop", "start_pause": Control buttons
    - "mode_continuous", "mode_step": Jog mode buttons  
    - "feed_plus", "feed_minus", "spindle_plus", "spindle_minus": Override buttons
    - "m_home", "safe_z", "w_home": Movement buttons
    - "spindle_on_off", "probe_z": Function buttons
    """
    def __init__(self, controller: Controller, cnc: CNC,
                 feed_override: OverrideController,
                 spindle_override: OverrideController,
                 is_jogging_enabled: Callable[[], None],
                 handle_run_pause_resume: Callable[[], None],
                 handle_probe_z: Callable[[], None],
                 open_probing_popup: Callable[[], None],
                 report_connection: Callable[[], None],
                 report_disconnection: Callable[[], None],
                 update_ui_on_button_press: Callable[[str], None] = None,
                 update_ui_on_jog_stop: Callable[[], None] = None) -> None:
        self._controller = controller
        self._cnc = cnc
        self._feed_override = feed_override
        self._spindle_override = spindle_override

        self._is_jogging_enabled = is_jogging_enabled
        self._handle_run_pause_resume = handle_run_pause_resume
        self._handle_probe_z = handle_probe_z
        self._open_probing_popup = open_probing_popup
        self._report_connection = report_connection
        self._report_disconnection = report_disconnection
        self._update_ui_on_button_press = update_ui_on_button_press
        self._update_ui_on_jog_stop = update_ui_on_jog_stop
        self._jog_mode = Controller.JOG_MODE_STEP

    def close(self) -> None:
        pass

    def executor(self, f: Callable[[], None]) -> None:
        Clock.schedule_once(lambda _: f(), 0)

    def run_macro(self, macro_id: int) -> None:
        macro_key = f"pendant_macro_{macro_id}"
        macro_value = Config.get("carvera", macro_key)

        if not macro_value:
            logger.warning(f"No macro defined for ID {macro_id}")
            return

        macro_value = json.loads(macro_value)

        try:
            lines = macro_value.get("gcode", "").splitlines()
            for l in lines:
                l = l.strip()
                if l == "":
                    continue
                self._controller.sendGCode(l)
        except Exception as e:
            logger.error(f"Failed to run macro {macro_id}: {e}")


class NonePendant(Pendant):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


try:
    from . import whb04
    WHB04_SUPPORTED = True
except Exception as e:
    logger.warning(f"WHB04 pendant not supported: {e}")
    WHB04_SUPPORTED = False

if WHB04_SUPPORTED:
    class WHB04(Pendant):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)

            self._is_spindle_running = False
            self._last_jog_direction = 0  # Track previous jog direction (0 = no direction, positive = CW, negative = CCW)

            self._daemon = whb04.Daemon(self.executor)

            self._daemon.on_connect = self._handle_connect
            self._daemon.on_disconnect = self._handle_disconnect
            self._daemon.on_update = self._handle_display_update
            self._daemon.on_jog = self._handle_jogging
            self._daemon.on_button_press = self._handle_button_press
            self._daemon.on_stop_jog = self._handle_stop_jog

            self._daemon.start()

        def _handle_connect(self, daemon: whb04.Daemon) -> None:
            daemon.set_display_step_indicator(whb04.StepIndicator.STEP)
            self._report_connection()

        def _handle_disconnect(self, daemon: whb04.Daemon) -> None:
            self._report_disconnection()

        def _handle_display_update(self, daemon: whb04.Daemon) -> None:
            daemon.set_display_position(whb04.Axis.X, self._cnc.vars["wx"])
            daemon.set_display_position(whb04.Axis.Y, self._cnc.vars["wy"])
            daemon.set_display_position(whb04.Axis.Z, self._cnc.vars["wz"])
            daemon.set_display_position(whb04.Axis.A, self._cnc.vars["wa"])
            daemon.set_display_feedrate(self._cnc.vars["curfeed"])
            daemon.set_display_spindle_speed(self._cnc.vars["curspindle"])
            
            # Update the step indicator to reflect current jog mode
            if self._controller.jog_mode == self._controller.JOG_MODE_CONTINUOUS:
                self._jog_mode = self._controller.JOG_MODE_CONTINUOUS
                daemon.set_display_step_indicator(whb04.StepIndicator.CONTINUOUS)
            else:
                self._jog_mode = self._controller.JOG_MODE_STEP
                daemon.set_display_step_indicator(whb04.StepIndicator.STEP)

        def _handle_jogging(self, daemon: whb04.Daemon, steps: int) -> None:
            if not self._is_jogging_enabled():
                return

            axis = daemon.active_axis_name

            if axis not in "XYZA":
                return
            
            if self._controller.jog_mode != self._jog_mode:
                self._controller.jog_mode = self._jog_mode
            
            # Detect direction change for continuous jog
            if self._controller.jog_mode == self._controller.JOG_MODE_CONTINUOUS:
                # Determine current direction (positive = CW, negative = CCW)
                current_direction = 1 if steps > 0 else (-1 if steps < 0 else 0)
                
                # Check if direction has changed and continuous jog is active
                if (self._last_jog_direction != 0 and 
                    current_direction != 0 and 
                    self._last_jog_direction != current_direction and
                    self._controller.continuous_jog_active):
                    self._controller.stopContinuousJog()
                
                # Update direction tracking
                if current_direction != 0:
                    self._last_jog_direction = current_direction
                
                distance = steps
                feed = self._controller.jog_speed * daemon.step_size_value
            else:
                # Reset direction tracking for step mode
                self._last_jog_direction = 0
                distance = steps * daemon.step_size_value

            # Jog as fast as you can as the machine should follow the pendant as
            # closely as possible. We choose some reasonably high speed here,
            # the machine will limit itself to the maximum speed it can handle.
            if self._controller.jog_mode == self._controller.JOG_MODE_CONTINUOUS:
                if not self._controller.continuous_jog_active:
                    if feed > 0 and self._controller.jog_speed < 10000:
                        if axis == "Z":
                            feed = min(800*daemon.step_size_value, feed)
                        self._controller.startContinuousJog(f"{axis}{distance}", feed)
                    elif feed == 0 or self._controller.jog_speed == 10000:
                        if axis == "Z":
                            self._controller.startContinuousJog(f"{axis}{distance}", 800 * daemon.step_size_value)
                        else:
                            self._controller.startContinuousJog(f"{axis}{distance}", None, f"S{daemon.step_size_value}")
            else:
                if daemon.step_size == whb04.StepSize.LEAD:
                    self._controller.jog(f"{axis}{round(steps * 0.1,3)}", round(abs(steps * 0.1 / 0.05) * 60 * 0.97, 3))
                else:
                    self._controller.jog(f"{axis}{round(distance, 3)}")

        def _handle_button_press(self, daemon: whb04.Daemon, button: whb04.Button) -> None:
            is_fn_pressed = whb04.Button.FN in daemon.pressed_buttons
            is_action_primary = Config.get("carvera", "pendant_primary_button_action") == "Key-specific Action"

            should_run_action = is_fn_pressed
            if is_action_primary:
                should_run_action = not should_run_action

            if button == whb04.Button.RESET:
                self._controller.estopCommand()
                if self._update_ui_on_button_press:
                    self._update_ui_on_button_press("reset")
            if button == whb04.Button.STOP:
                self._controller.abortCommand()
                if self._update_ui_on_button_press:
                    self._update_ui_on_button_press("stop")
            if button == whb04.Button.START_PAUSE:
                self._handle_run_pause_resume()
                if self._update_ui_on_button_press:
                    self._update_ui_on_button_press("start_pause")

            # Handle jog mode switching buttons (these work regardless of FN state)
            if button == whb04.Button.MODE_CONTINUOUS:
                if not self._controller.is_community_firmware:
                    return
                self._controller.setJogMode(self._controller.JOG_MODE_CONTINUOUS)
                self._jog_mode = self._controller.JOG_MODE_CONTINUOUS
                if self._update_ui_on_button_press:
                    self._update_ui_on_button_press("mode_continuous")
            if button == whb04.Button.MODE_STEP:
                self._controller.setJogMode(Controller.JOG_MODE_STEP)
                self._jog_mode = Controller.JOG_MODE_STEP
                if self._update_ui_on_button_press:
                    self._update_ui_on_button_press("mode_step")

            if should_run_action:
                if button == whb04.Button.FEED_PLUS:
                    self._feed_override.on_increase()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("feed_plus")
                if button == whb04.Button.FEED_MINUS:
                    self._feed_override.on_decrease()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("feed_minus")
                if button == whb04.Button.SPINDLE_PLUS:
                    self._spindle_override.on_increase()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("spindle_plus")
                if button == whb04.Button.SPINDLE_MINUS:
                    self._spindle_override.on_decrease()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("spindle_minus")
                if button == whb04.Button.M_HOME:
                    self._controller.gotoMachineHome()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("m_home")
                if button == whb04.Button.SAFE_Z:
                    self._controller.gotoSafeZ()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("safe_z")
                if button == whb04.Button.W_HOME:
                    self._controller.gotoWCSHome()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("w_home")
                if button == whb04.Button.S_ON_OFF:
                    self._is_spindle_running = not self._is_spindle_running
                    self._controller.setSpindleSwitch(self._is_spindle_running)
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("spindle_on_off")
                if button == whb04.Button.PROBE_Z:
                    self._handle_probe_z()
                    if self._update_ui_on_button_press:
                        self._update_ui_on_button_press("probe_z")
                if button == whb04.Button.MACRO_10:  # macro-10 has no action so it should always run
                    self.run_macro(10)
            else:
                MACROS = [
                    whb04.Button.FEED_PLUS,
                    whb04.Button.FEED_MINUS,
                    whb04.Button.SPINDLE_PLUS,
                    whb04.Button.SPINDLE_MINUS,
                    whb04.Button.M_HOME,
                    whb04.Button.SAFE_Z,
                    whb04.Button.W_HOME,
                    whb04.Button.S_ON_OFF,
                    whb04.Button.PROBE_Z,
                    whb04.Button.MACRO_10
                ]
                if button not in MACROS:
                    return
                macro_idx = 1 + MACROS.index(button)
                self.run_macro(macro_idx)

        def _handle_stop_jog(self, daemon: whb04.Daemon) -> None:
            if self._controller.continuous_jog_active:
                self._controller.stopContinuousJog()
                if self._update_ui_on_jog_stop:
                    self._update_ui_on_jog_stop()


class GamepadPendant(Pendant):
    DEFAULT_MAX_JOG_SPEED = 3000        # mm/min
    DEFAULT_Z_MAX_SPEED = 800           # mm/min cap for Z in continuous mode
    STEP_SIZES = [0.01, 0.1, 1.0, 10.0] # step sizes in mm
    STEP_SIZE_SPEED_FRACTION = {        # speed fractions for continuous jog
        0.01: 0.02,
        0.1:  0.10,
        1.0:  0.30,
        10.0: 1.0,
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._last_jog_direction = {}  # action -> direction sign
        self._active_continuous_jog_action: Optional[str] = None

        deadzone = 0.15
        try:
            deadzone = float(Config.get("carvera", "gamepad_deadzone"))
        except Exception:
            pass

        self._step_index = 1  # Start at 0.1mm

        try:
            self._max_jog_speed = float(Config.get("carvera", "gamepad_max_jog_speed"))
        except Exception:
            self._max_jog_speed = self.DEFAULT_MAX_JOG_SPEED

        self._invert_x = Config.getboolean("carvera", "gamepad_invert_x", fallback=False)
        self._invert_y = Config.getboolean("carvera", "gamepad_invert_y", fallback=False)
        self._invert_z = Config.getboolean("carvera", "gamepad_invert_z", fallback=False)
        self._invert_a = Config.getboolean("carvera", "gamepad_invert_a", fallback=False)

        bindings = gamepad_module.GamepadBindings.from_config()
        self._manager = gamepad_module.GamepadManager(bindings=bindings, deadzone=deadzone)
        self._manager.on_connect = self._handle_connect
        self._manager.on_jog_axis = self._handle_jog_axis
        self._manager.on_jog_stop = self._handle_jog_stop
        self._manager.on_button_action = self._handle_button_action

    def close(self) -> None:
        if self._controller.stream is not None:
            self._controller.stream.send(b"\031")
        self._controller.continuous_jog_active = False
        self._active_continuous_jog_action = None
        self._manager.close()
        self._report_disconnection()

    @property
    def current_step_size(self) -> float:
        return self.STEP_SIZES[self._step_index]

    def _cycle_step_size(self, direction: int) -> None:
        n = len(self.STEP_SIZES)
        new_index = max(0, min(n - 1, self._step_index + direction))
        if new_index == self._step_index:
            return
        self._step_index = new_index
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("step_size_changed")

    def _continuous_feed_for_axis(self, axis: str) -> float:
        frac = self.STEP_SIZE_SPEED_FRACTION[self.current_step_size]
        cap = self._max_jog_speed
        if axis == "Z":
            cap = min(cap, self.DEFAULT_Z_MAX_SPEED)
        return frac * cap

    # Callbacks
    def _handle_connect(self) -> None:
        self._report_connection()

    def _handle_jog_axis(self, action: str, value: float) -> None:
        if not self._is_jogging_enabled():
            return

        axis_letter = self._action_to_axis(action)
        if axis_letter is None:
            return

        if value == 0.0:
            return

        value = self._apply_inversion(axis_letter, value)
        direction = 1 if value > 0 else -1

        if self._controller.jog_mode == Controller.JOG_MODE_STEP:
            self._handle_step_jog(action, axis_letter, direction)
        else:
            self._handle_continuous_jog(action, axis_letter, value, direction)

    def _handle_step_jog(self, action: str, axis: str, direction: int) -> None:
        if self._manager.is_axis_held(action) and self._last_jog_direction.get(action) == direction:
            return

        self._last_jog_direction[action] = direction
        distance = self.current_step_size * direction
        self._controller.jog(f"{axis}{round(distance, 4)}")

    def _handle_continuous_jog(self, action: str, axis: str,
                               value: float, direction: int) -> None:
        prev_direction = self._last_jog_direction.get(action, 0)
        self._last_jog_direction[action] = direction

        if prev_direction != 0 and prev_direction != direction \
                and self._controller.continuous_jog_active \
                and action == self._active_continuous_jog_action:
            self._controller.stopContinuousJog()

        if self._controller.continuous_jog_active:
            return

        feed = self._continuous_feed_for_axis(axis)

        if self._controller.jog_mode != Controller.JOG_MODE_CONTINUOUS:
            self._controller.setJogMode(Controller.JOG_MODE_CONTINUOUS)

        self._controller.startContinuousJog(f"{axis}{direction}", feed)
        self._active_continuous_jog_action = action

    def _handle_jog_stop(self, action: str) -> None:
        self._last_jog_direction.pop(action, None)

        if action != self._active_continuous_jog_action:
            return

        self._active_continuous_jog_action = None
        if self._controller.continuous_jog_active:
            self._controller.stopContinuousJog()
            if self._update_ui_on_jog_stop:
                self._update_ui_on_jog_stop()

    def _handle_button_action(self, action: str) -> None:
        action_map = {
            "reset": self._do_reset,
            "stop": self._do_stop,
            "start_pause": self._do_start_pause,
            "mode_toggle": self._do_mode_toggle,
            "feed_plus": self._do_feed_plus,
            "feed_minus": self._do_feed_minus,
            "spindle_plus": self._do_spindle_plus,
            "spindle_minus": self._do_spindle_minus,
            "m_home": self._do_machine_home,
            "safe_z": self._do_safe_z,
            "w_home": self._do_work_home,
            "spindle_on_off": self._do_spindle_toggle,
            "probe_z": self._do_probe_z,
            "step_size_up": lambda: self._cycle_step_size(1),
            "step_size_down": lambda: self._cycle_step_size(-1),
        }

        # Macro buttons (macro_1 .. macro_10)
        if action.startswith("macro_"):
            try:
                macro_id = int(action.split("_", 1)[1])
                self.run_macro(macro_id)
            except (ValueError, IndexError):
                pass
            return

        handler = action_map.get(action)
        if handler:
            handler()

    # Action implementations

    def _do_reset(self) -> None:
        self._controller.estopCommand()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("reset")

    def _do_stop(self) -> None:
        self._controller.abortCommand()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("stop")

    def _do_start_pause(self) -> None:
        self._handle_run_pause_resume()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("start_pause")

    def _do_mode_toggle(self) -> None:
        if self._controller.jog_mode == Controller.JOG_MODE_STEP:
            if not self._controller.is_community_firmware:
                return
            self._controller.setJogMode(Controller.JOG_MODE_CONTINUOUS)
            if self._update_ui_on_button_press:
                self._update_ui_on_button_press("mode_continuous")
        else:
            self._controller.setJogMode(Controller.JOG_MODE_STEP)
            if self._update_ui_on_button_press:
                self._update_ui_on_button_press("mode_step")

    def _do_feed_plus(self) -> None:
        self._feed_override.on_increase()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("feed_plus")

    def _do_feed_minus(self) -> None:
        self._feed_override.on_decrease()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("feed_minus")

    def _do_spindle_plus(self) -> None:
        self._spindle_override.on_increase()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("spindle_plus")

    def _do_spindle_minus(self) -> None:
        self._spindle_override.on_decrease()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("spindle_minus")

    def _do_machine_home(self) -> None:
        self._controller.gotoMachineHome()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("m_home")

    def _do_safe_z(self) -> None:
        self._controller.gotoSafeZ()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("safe_z")

    def _do_work_home(self) -> None:
        self._controller.gotoWCSHome()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("w_home")

    def _do_spindle_toggle(self) -> None:
        if self._cnc.vars.get("lasermode"):
            return
        running = float(self._cnc.vars.get("curspindle", 0)) > 0.0
        self._controller.setSpindleSwitch(not running)
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("spindle_on_off")

    def _do_probe_z(self) -> None:
        self._handle_probe_z()
        if self._update_ui_on_button_press:
            self._update_ui_on_button_press("probe_z")

    # Helpers

    @staticmethod
    def _action_to_axis(action: str) -> Optional[str]:
        mapping = {
            "jog_x": "X", "jog_y": "Y",
            "jog_z": "Z", "jog_a": "A",
        }
        return mapping.get(action)

    def _apply_inversion(self, axis: str, value: float) -> float:
        if axis == "X" and self._invert_x:
            return -value
        if axis == "Y" and self._invert_y:
            return -value
        if axis == "Z" and self._invert_z:
            return -value
        if axis == "A" and self._invert_a:
            return -value
        return value

SUPPORTED_PENDANTS = {
    "None": NonePendant,
    "Gamepad": GamepadPendant,
}

if WHB04_SUPPORTED:
    SUPPORTED_PENDANTS["WHB04"] = WHB04

class SettingPendantSelector(SettingItem):
    # Populated by load_pendant_config from pendant_config.json.
    # Maps setting key -> list of pendant type names that should show it.
    # Keys absent from this map are always visible.
    pendant_types_map = {}

    def __init__(self, **kwargs):
        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        self.spinner = Spinner(text="None", values=list(SUPPORTED_PENDANTS.keys()), size_hint=(1, None), height='36dp')
        super().__init__(**kwargs)
        self.spinner.bind(text=self.on_spinner_select)
        wrapper.add_widget(self.spinner)
        self.add_widget(wrapper)
        self._widget_order = None

    def on_spinner_select(self, spinner, text):
        self.value = text
        self.panel.set_value(self.section, self.key, text)
        self._update_sibling_visibility(text)

    def on_value(self, instance, value):
        if self.spinner.text != value:
            self.spinner.text = value
        Clock.schedule_once(lambda _: self._update_sibling_visibility(value), 0)

    def _update_sibling_visibility(self, pendant_type: str) -> None:
        if not hasattr(self, 'panel') or self.panel is None:
            return

        if self._widget_order is None:
            self._widget_order = list(reversed(self.panel.children[:]))

        self.panel.clear_widgets()
        for widget in self._widget_order:
            key = getattr(widget, 'key', None)
            if key is not None and widget is not self:
                allowed = self.pendant_types_map.get(key)
                if allowed is not None and pendant_type not in allowed:
                    continue
            self.panel.add_widget(widget)


class GamepadBindingsPopup(Popup):
    """Interactive popup for configuring gamepad button/axis bindings."""

    AXIS_LISTEN_THRESHOLD = 0.6

    def __init__(self, current_bindings: dict, on_save: Callable[[dict], None],
                 manager=None, **kwargs) -> None:
        kwargs.setdefault("title", "Gamepad Bindings")
        kwargs.setdefault("size_hint", (0.9, 0.9))
        kwargs.setdefault("auto_dismiss", False)
        super().__init__(**kwargs)

        self._on_save = on_save
        self._manager = manager  # GamepadManager paused while popup is open
        self._bindings = json.loads(json.dumps(current_bindings))
        self._listening_for = None  # (action, category) when in listen mode
        self._listen_btn = None
        self._listen_label = None
        self._row_widgets = {}  # action -> (label_widget, bind_btn)

        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))

        scroll = ScrollView(size_hint=(1, 1))
        self._list_layout = BoxLayout(
            orientation='vertical', size_hint_y=None, spacing=dp(4), padding=[0, 0, dp(12), 0])
        self._list_layout.bind(minimum_height=self._list_layout.setter('height'))

        for group_name, actions in gamepad_module.BINDING_GROUPS:
            header = Label(
                text=f"[b]{tr._(group_name)}[/b]", markup=True,
                size_hint_y=None, height=dp(32), halign='left', valign='middle')
            header.bind(size=lambda w, s: setattr(w, 'text_size', s))
            self._list_layout.add_widget(header)

            for action in actions:
                self._add_action_row(action)

        scroll.add_widget(self._list_layout)
        root.add_widget(scroll)

        btn_bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))

        self._preset_spinner = Spinner(
            text=tr._("Load preset..."),
            values=gamepad_module.preset_names(),
            size_hint_x=0.45,
        )
        self._preset_spinner.bind(text=self._on_preset_selected)

        cancel_btn = Button(text=tr._("Cancel"))
        cancel_btn.bind(on_release=lambda *_: self._cancel())

        save_btn = Button(text=tr._("Save"))
        save_btn.bind(on_release=lambda *_: self._save())

        btn_bar.add_widget(self._preset_spinner)
        btn_bar.add_widget(cancel_btn)
        btn_bar.add_widget(save_btn)
        root.add_widget(btn_bar)

        self.content = root

    def open(self, *args, **kwargs) -> None:
        super().open(*args, **kwargs)
        if self._manager is not None:
            self._manager.paused = True

    def _add_action_row(self, action: str) -> None:
        label_text = tr._(gamepad_module.ACTION_LABELS.get(action, action))
        current = self._describe_binding(action)

        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(36),
                        spacing=dp(6))

        name_lbl = Label(text=label_text, size_hint_x=0.35, halign='left', valign='middle')
        name_lbl.bind(size=lambda w, s: setattr(w, 'text_size', s))

        binding_lbl = Label(text=current, size_hint_x=0.35, halign='center', valign='middle')
        binding_lbl.bind(size=lambda w, s: setattr(w, 'text_size', s))

        bind_btn = Button(text=tr._("Bind..."), size_hint_x=0.15)
        bind_btn.bind(on_release=lambda btn, a=action, bl=binding_lbl: self._start_listening(a, btn, bl))

        unbind_btn = Button(text=tr._("Unbind"), size_hint_x=0.15)
        unbind_btn.bind(on_release=lambda *_, a=action: self._unbind_action(a))

        row.add_widget(name_lbl)
        row.add_widget(binding_lbl)
        row.add_widget(bind_btn)
        row.add_widget(unbind_btn)
        self._list_layout.add_widget(row)
        self._row_widgets[action] = (binding_lbl, bind_btn)

    def _describe_binding(self, action: str) -> str:
        for category in ("axes", "triggers", "buttons"):
            mapping = self._bindings.get(category, {})
            for input_id, bound_action in mapping.items():
                if bound_action == action:
                    itype = "axis" if category == "axes" else \
                            "trigger" if category == "triggers" else "button"
                    return gamepad_module.format_input_label(itype, input_id)

        hat = self._bindings.get("hat", {})
        hat_dirs = [
            d for d in ("up", "down", "left", "right")
            if hat.get(d) == action
        ]
        if hat_dirs:
            return ", ".join(
                gamepad_module.format_input_label("hat", d) for d in hat_dirs)

        return tr._("Unbound")

    def _refresh_all_binding_labels(self) -> None:
        for act, (lbl, _) in self._row_widgets.items():
            lbl.text = self._describe_binding(act)

    def _start_listening(self, action: str, btn, binding_lbl) -> None:
        if self._listening_for is not None:
            self._stop_listening()

        self._listening_for = action
        self._listen_btn = btn
        self._listen_label = binding_lbl
        btn.text = tr._("Waiting...")
        Window.bind(
            on_joy_axis=self._listen_axis,
            on_joy_button_down=self._listen_button,
            on_joy_hat=self._listen_hat,
        )

    def _stop_listening(self) -> None:
        Window.unbind(
            on_joy_axis=self._listen_axis,
            on_joy_button_down=self._listen_button,
            on_joy_hat=self._listen_hat,
        )
        if self._listen_btn:
            self._listen_btn.text = tr._("Bind...")
        self._listening_for = None
        self._listen_btn = None
        self._listen_label = None

    def _apply_captured(self, category: str, input_id: str) -> None:
        action = self._listening_for
        if action is None:
            return

        # Axes and triggers share on_joy_axis events. Jog axes claim the
        # whole physical axis, while triggers only claim one direction.
        if category == "axes":
            self._bindings.get("axes", {}).pop(input_id, None)
            trigger_map = self._bindings.get("triggers", {})
            for key in list(trigger_map.keys()):
                trigger_axis_id, _ = gamepad_module.split_trigger_id(key)
                if trigger_axis_id == input_id:
                    del trigger_map[key]
            self._remove_action_binding(action)
            self._bindings.setdefault("axes", {})[input_id] = action
        elif category == "triggers":
            trigger_axis_id, trigger_direction = gamepad_module.split_trigger_id(input_id)
            self._bindings.get("axes", {}).pop(trigger_axis_id, None)
            trigger_map = self._bindings.get("triggers", {})
            trigger_map.pop(input_id, None)
            trigger_map.pop(trigger_axis_id, None)
            self._remove_action_binding(action)
            self._bindings.setdefault("triggers", {})[input_id] = action
        elif category == "buttons":
            self._bindings.get("buttons", {}).pop(input_id, None)
            self._remove_action_binding(action)
            self._bindings.setdefault("buttons", {})[input_id] = action
        elif category == "hat":
            pair = (gamepad_module.hat_axis_pair(input_id) if action.startswith("jog_") else None)
            if pair:
                # Jog on D-Pad: bind both directions on the same hat axis.
                self._remove_action_binding(action)
                hat_map = self._bindings.setdefault("hat", {})
                for d in pair:
                    hat_map.pop(d, None)
                for d in pair:
                    hat_map[d] = action
            else:
                self._bindings.get("hat", {}).pop(input_id, None)
                self._remove_action_binding(action)
                self._bindings.setdefault("hat", {})[input_id] = action
        else:
            return

        self._stop_listening()
        self._refresh_all_binding_labels()

    def _remove_action_binding(self, action: str) -> None:
        for cat in ("axes", "triggers", "buttons"):
            cat_map = self._bindings.get(cat, {})
            to_del = [k for k, v in cat_map.items() if v == action]
            for k in to_del:
                del cat_map[k]
        hat_map = self._bindings.get("hat", {})
        to_del = [k for k, v in hat_map.items() if v == action]
        for k in to_del:
            del hat_map[k]

    def _unbind_action(self, action: str) -> None:
        if self._listening_for is not None:
            self._stop_listening()
        self._remove_action_binding(action)
        self._refresh_all_binding_labels()

    def _listen_axis(self, win, stickid, axisid, value) -> None:
        normalised = max(-1.0, min(1.0, value / gamepad_module.AXIS_MAX))
        if abs(normalised) < self.AXIS_LISTEN_THRESHOLD:
            return
        action = self._listening_for
        if action is None:
            return
        # Only jog actions use continuous axis semantics; everything else
        # should be stored as a trigger (one-shot on threshold crossing).
        is_axis = action in ("jog_x", "jog_y", "jog_z", "jog_a")
        if is_axis:
            self._apply_captured("axes", str(axisid))
        else:
            direction = "+" if normalised > 0 else "-"
            trigger_id = gamepad_module.trigger_input_id(axisid, direction)
            self._apply_captured("triggers", trigger_id)

    def _listen_button(self, win, stickid, buttonid) -> None:
        self._apply_captured("buttons", str(buttonid))

    def _listen_hat(self, win, stickid, hatid, value) -> None:
        dx, dy = value if isinstance(value, (tuple, list)) else (0, 0)
        direction = None
        if dy > 0:
            direction = "up"
        elif dy < 0:
            direction = "down"
        elif dx < 0:
            direction = "left"
        elif dx > 0:
            direction = "right"
        if direction:
            self._apply_captured("hat", direction)

    def _on_preset_selected(self, spinner, name: str) -> None:
        if name not in gamepad_module.preset_names():
            return
        bindings = gamepad_module.preset_bindings(name)
        if bindings is None:
            return
        if self._listening_for is not None:
            self._stop_listening()
        self._bindings = bindings
        self._refresh_all_binding_labels()
        spinner.text = tr._("Load preset...")

    def _cancel(self) -> None:
        if self._listening_for is not None:
            self._stop_listening()
        self.dismiss()

    def _save(self) -> None:
        if self._listening_for is not None:
            self._stop_listening()
        self._on_save(self._bindings)
        self.dismiss()

    def on_dismiss(self) -> None:
        if self._listening_for is not None:
            self._stop_listening()
        if self._manager is not None:
            self._manager.paused = False


class SettingGamepadBindings(SettingItem):
    """Settings widget that opens the gamepad bindings configuration popup."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint_y = None
        self.height = dp(60)

        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        inner = BoxLayout(
            orientation='horizontal', spacing=dp(10),
            size_hint=(1, None), height=dp(40), padding=[dp(10), 0])

        self.summary_label = Label(
            text=self._get_summary(), halign='left', valign='middle',
            size_hint=(1, 1))
        self.summary_label.bind(
            size=lambda w, s: setattr(w, 'text_size', s))

        btn = Button(text=tr._("Configure..."), size_hint=(None, 1), width=dp(130))
        btn.bind(on_release=self._open_popup)

        inner.add_widget(self.summary_label)
        inner.add_widget(btn)
        wrapper.add_widget(inner)
        self.add_widget(wrapper)

    def _get_summary(self) -> str:
        raw = self.value if hasattr(self, 'value') else ""
        if not raw:
            return tr._("Default (Xbox 360)")
        try:
            json.loads(raw)
            return tr._("Custom")
        except Exception:
            return tr._("Default (Xbox 360)")

    def _open_popup(self, *args) -> None:
        try:
            current = json.loads(self.value) if self.value else None
        except Exception:
            current = None
        if current is None:
            current = gamepad_module.default_bindings()

        manager = None
        try:
            pendant = App.get_running_app().root.pendant
            if hasattr(pendant, '_manager'):
                manager = pendant._manager
        except Exception:
            pass

        popup = GamepadBindingsPopup(
            current_bindings=current,
            on_save=self._save_bindings,
            manager=manager)
        popup.open()

    def _save_bindings(self, bindings: dict) -> None:
        if bindings == gamepad_module.default_bindings():
            new_value = ""
        else:
            new_value = json.dumps(bindings)

        self.panel.set_value(self.section, self.key, new_value)
        self.value = new_value

    def on_value(self, instance, value):
        if hasattr(self, 'summary_label'):
            self.summary_label.text = self._get_summary()
