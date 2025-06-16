from typing import Callable
from ...CNC import CNC
from ...Controller import Controller
from . import whb04

from kivy.clock import Clock
from kivy.uix.settings import SettingItem
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton


class Pendant:
    def __init__(self, controller: Controller, cnc: CNC,
                 is_jogging_enabled: Callable[[], None],
                 report_connection: Callable[[], None],
                 report_disconnection: Callable[[], None]) -> None:
        self._controller = controller
        self._cnc = cnc

        self._is_jogging_enabled = is_jogging_enabled
        self._report_connection = report_connection
        self._report_disconnection = report_disconnection

    def close(self) -> None:
        pass

    def executor(self, f: Callable[[], None]) -> None:
        Clock.schedule_once(lambda _: f(), 0)

class NonePendant(Pendant):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class WHB04(Pendant):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._is_spindle_running = False

        self._daemon = whb04.Daemon(self.executor)

        self._daemon.on_connect = self._handle_connect
        self._daemon.on_disconnect = self._handle_disconnect
        self._daemon.on_update = self._handle_display_update
        self._daemon.on_jog = self._handle_jogging
        self._daemon.on_button_press = self._handle_button_press

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

    def _handle_jogging(self, daemon: whb04.Daemon, steps: int) -> None:
        if not self._is_jogging_enabled():
            return

        distance = steps * daemon.step_size_value
        axis = daemon.active_axis_name

        if axis not in "XYZA":
            return

        self._controller.jog(f"{axis}{distance}")

    def _handle_button_press(self, daemon: whb04.Daemon, button: whb04.Button) -> None:
        if button == whb04.Button.S_ON_OFF:
            self._is_spindle_running = not self._is_spindle_running
            self._controller.setSpindleSwitch(self._is_spindle_running)

        if button == whb04.Button.RESET:
            self._controller.estopCommand()


SUPPORTED_PENDANTS = {
    "None": NonePendant,
    "WHB04": WHB04
}


class SettingPendantSelector(SettingItem):
    def __init__(self, **kwargs):
        self.spinner = Spinner(text="None", values=list(SUPPORTED_PENDANTS.keys()), size_hint=(1, None), height='36dp')
        super().__init__(**kwargs)
        self.spinner.bind(text=self.on_spinner_select)
        self.add_widget(self.spinner)

    def on_spinner_select(self, spinner, text):
        self.panel.set_value(self.section, self.key, text)

    def on_value(self, instance, value):
        if self.spinner.text != value:
            self.spinner.text = value
