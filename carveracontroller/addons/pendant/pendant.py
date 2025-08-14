import json
from typing import Callable

import logging
logger = logging.getLogger(__name__)

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller

from kivy.clock import Clock
from kivy.uix.settings import SettingItem
from kivy.uix.spinner import Spinner
from kivy.uix.anchorlayout import AnchorLayout
from kivy.config import Config

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
            # There are no absolute positions for the rotational axis, hence ma
            # instead of wa is used.
            daemon.set_display_position(whb04.Axis.A, self._cnc.vars["ma"])
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
                feed = 10000

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
                self._controller.jog(f"{axis}{distance}")

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


SUPPORTED_PENDANTS = {
    "None": NonePendant
}

if WHB04_SUPPORTED:
    SUPPORTED_PENDANTS["WHB04"] = WHB04


class SettingPendantSelector(SettingItem):
    def __init__(self, **kwargs):
        # Wrapper to ensure the content is centered vertically
        wrapper = AnchorLayout(anchor_y='center', anchor_x='left')

        self.spinner = Spinner(text="None", values=list(SUPPORTED_PENDANTS.keys()), size_hint=(1, None), height='36dp')
        super().__init__(**kwargs)
        self.spinner.bind(text=self.on_spinner_select)
        wrapper.add_widget(self.spinner)
        self.add_widget(wrapper)

    def on_spinner_select(self, spinner, text):
        self.panel.set_value(self.section, self.key, text)

    def on_value(self, instance, value):
        if self.spinner.text != value:
            self.spinner.text = value
