from __future__ import annotations

from enum import Enum
import struct
import threading
import time
from typing import Callable, List, Optional
import platform

import hid

# On Windows, the pendant is represented by two devices, meanwhile on Linux
# the pendant is a single device. Let's abstract this away into the PendantHid class:
if platform.system() == "Windows":
    class PendantHid:
        def __init__(self, devices: List[hid.DeviceInfo]) -> None:
            assert len(devices) == 2, "Two devices are expected"

            read_path, write_path = None, None
            for dev in devices:
                path_str = dev["path"].decode() if isinstance(dev["path"], bytes) else dev["path"]
                if "col01" in path_str.lower():
                    read_path = dev["path"]
                elif "col02" in path_str.lower():
                    write_path = dev["path"]

            if read_path and write_path:
                self.read_dev = hid.Device(path=read_path)
                self.write_dev = hid.Device(path=write_path)
            else:
                raise RuntimeError("Cannot open pendant HIDs")

        def read(self, *args, **kwargs):
            return self.read_dev.read(*args, **kwargs)

        def send_feature_report(self, data):
            return self.write_dev.send_feature_report(data)

        def close(self):
            self.read_dev.close()
            self.write_dev.close()

        def __enter__(self):
            self.read_dev.__enter__()
            self.write_dev.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.read_dev.__exit__(exc_type, exc_val, exc_tb)
            self.write_dev.__exit__(exc_type, exc_val, exc_tb)
else:
    class PendantHid(hid.Device):
        def __init__(self, devices: List[hid.DeviceInfo]) -> None:
            unique_paths = {dev["path"] for dev in devices}
            assert len(unique_paths) == 1, "Only one device is expected"
            super().__init__(path=devices[0]["path"])


class Button(Enum):
    RESET = 0x01
    STOP = 0x02
    START_PAUSE = 0x03
    FEED_PLUS = 0x04
    FEED_MINUS = 0x05
    SPINDLE_PLUS = 0x06
    SPINDLE_MINUS = 0x07
    M_HOME = 0x08
    SAFE_Z = 0x09
    W_HOME = 0x0a
    S_ON_OFF = 0x0b
    FN = 0x0c
    PROBE_Z = 0x0d
    MACRO_10 = 0x10
    MODE_CONTINUOUS = 0x0e
    MODE_STEP = 0x0f

class Axis(Enum):
    OFF = 0x06
    X = 0x11
    Y = 0x12
    Z = 0x13
    A = 0x14
    B = 0x15
    C = 0x16

class StepSize(Enum):
    STEP_0_001 = 0x0d
    STEP_0_01 = 0x0e
    STEP_0_1 = 0x0f
    STEP_1 = 0x10
    PERCENT_60 = 0x1a
    PERCENT_100 = 0x1b
    LEAD = 0x9b

class StepIndicator(Enum):
    CONTINUOUS = 0x00
    STEP = 0x01
    MPG = 0x02
    PERCENT = 0x03

class Daemon:
    """
    A class that establishes a connection to the WHB04 pedant, receives messages
    and invokes callbacks.
    """

    DEVICE_IDS = [
        (0x10ce, 0xeb93)
    ]

    def __init__(self, callback_executor: Callable[[Callable[[], None]], None] = lambda f: f()) -> None:
        """
        Params:

        - callback_executor: a function that receives an invokable and it is
          supposed to invoke it. E.g., in a way safe for GUI.
        """
        self._is_running = False
        self._pressed_buttons = set()
        self._active_axis = Axis.OFF
        self._step_size = StepSize.LEAD

        # Wheel movement tracking for improved stopping detection
        self._last_step_time = 0.0  # Timestamp of last step
        self._last_step_delta = 0  # Delta steps from last packet
        self._wheel_steps_per_second = 0.0  # Current steps per second rate
        self._wheel_active_threshold = 30.0  # Steps per second threshold for wheel activity
        self._last_wheel_activity_time = 0.0  # Timestamp of last wheel activity
        self._wheel_inactivity_timeout = 0.2  # Timeout in seconds before considering wheel inactive
        self._last_decay_check_time = 0.0  # Timestamp of last decay check

        self._display_position = {
            Axis.X: 0.0,
            Axis.Y: 0.0,
            Axis.Z: 0.0,
            Axis.A: 0.0,
            Axis.B: 0.0,
            Axis.C: 0.0
        }
        self._display_feedrate = 0
        self._display_spindle_speed = 0
        self._display_step_indicator = StepIndicator.CONTINUOUS
        self._display_reset = False
        self._display_workpiece_coords = False

        self.callback_executor = callback_executor

        self.on_connect: Optional[Callable[[Daemon], None]] = None
        self.on_disconnect: Optional[Callable[[Daemon], None]] = None
        self.on_button_press: Optional[Callable[[Daemon, Button], None]] = None
        self.on_button_release: Optional[Callable[[Daemon, Button], None]] = None
        self.on_jog: Optional[Callable[[Daemon, int], None]] = None
        self.on_axis_change: Optional[Callable[[Daemon, Axis], None]] = None
        self.on_step_size_change: Optional[Callable[[Daemon, StepSize], None]] = None
        self.on_update: Optional[Callable[[Daemon], None]] = None
        self.on_stop_jog: Optional[Callable[[Daemon], None]] = None

    def start(self) -> None:
        self._daemon_thread = threading.Thread(target=self._thread_loop, daemon=True)
        self._is_running = True
        self._daemon_thread.start()

    def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        self._daemon_thread.join()

    @property
    def pressed_buttons(self) -> set[Button]:
        """
        Returns a set of currently pressed buttons.
        """
        return self._pressed_buttons

    @property
    def active_axis(self) -> Axis:
        """
        Returns the currently active axis.
        """
        return self._active_axis

    @property
    def active_axis_name(self) -> str:
        """
        Returns the name of the currently active axis.
        This is a convenience method to get the axis name.
        """
        return {
            Axis.OFF: "OFF",
            Axis.X: "X",
            Axis.Y: "Y",
            Axis.Z: "Z",
            Axis.A: "A",
            Axis.B: "B",
            Axis.C: "C"
        }[self.active_axis]

    @property
    def step_size(self) -> StepSize:
        """
        Returns the currently active step size.
        """
        return self._step_size

    @property
    def step_size_value(self) -> float:
        """
        Returns the step size value as a float.
        This is a convenience method to get the step size value.
        """
        if self._display_step_indicator == StepIndicator.STEP:
            if self._step_size == StepSize.STEP_0_001:
                return 0.001
            elif self._step_size == StepSize.STEP_0_01:
                return 0.01
            elif self._step_size == StepSize.STEP_0_1:
                return 0.1
            elif self._step_size == StepSize.STEP_1:
                return 1.0
            return 0
        elif self._display_step_indicator == StepIndicator.CONTINUOUS:
            if self._step_size == StepSize.STEP_0_001:
                return 0.02
            elif self._step_size == StepSize.STEP_0_01:
                return 0.05
            elif self._step_size == StepSize.STEP_0_1:
                return 0.1
            elif self._step_size == StepSize.STEP_1:
                return 0.3
            elif self._step_size == StepSize.PERCENT_60:
                return 0.6
            elif self._step_size == StepSize.PERCENT_100:
                return 1.0
            return 0

    @property
    def wheel_steps_per_second(self) -> float:
        """
        Returns the current steps per second rate of the wheel.
        This can be used for debugging and monitoring wheel activity.
        """
        return self._wheel_steps_per_second

    @property
    def wheel_is_active(self) -> bool:
        """
        Returns True if the wheel is actively turning.
        In step mode, returns True for any non-zero delta.
        In continuous mode, returns True only if steps per second rate is above threshold.
        """
        if self._display_step_indicator == StepIndicator.STEP:
            # In step mode, we don't use speed-based detection
            # This property is not really applicable for step mode
            return True
        else:
            # In continuous mode, use speed-based detection
            return self._wheel_steps_per_second >= self._wheel_active_threshold

    def set_display_position(self, axis: Axis, value: float) -> None:
        """
        Sets the display position for the given axis.
        """
        if axis not in self._display_position:
            raise ValueError(f"Invalid axis: {axis}")
        self._display_position[axis] = value

    def set_display_feedrate(self, feedrate: int) -> None:
        """
        Sets the display feedrate.
        """
        if feedrate < 0 or feedrate > 65535:
            raise ValueError("Feedrate outside range")
        self._display_feedrate = int(feedrate)

    def set_display_spindle_speed(self, speed: int) -> None:
        """
        Sets the display spindle speed.
        """
        if speed < 0 or speed > 65535:
            raise ValueError("Spindle speed outside range")
        self._display_spindle_speed = int(speed)

    def set_display_step_indicator(self, indicator: StepIndicator) -> None:
        """
        Sets the display step indicator.
        """
        if not isinstance(indicator, StepIndicator):
            raise ValueError("Invalid step indicator")
        self._display_step_indicator = indicator

    def set_display_reset(self, reset: bool) -> None:
        """
        Sets the display reset state.
        """
        if not isinstance(reset, bool):
            raise ValueError("Reset must be a boolean value")
        self._display_reset = reset

    def set_display_machine_coords(self) -> None:
        """
        Sets the display to show machine coordinates.
        """
        self._display_workpiece_coords = False

    def set_display_workpiece_coords(self) -> None:
        """
        Sets the display to show workpiece coordinates.
        """
        self._display_workpiece_coords = True

    def _thread_loop(self) -> None:
        while self._is_running:
            try:
                device = self._connect()
                if device is None:
                    continue

                with device as guarded_device:
                    if self.on_connect is not None:
                        self.callback_executor(lambda: self.on_connect(self))
                    self._device_loop(guarded_device)
            except Exception:
                # Exception means the device was disconnected or an error occurred.
                # Let's just try again
                pass
            finally:
                if self.on_disconnect is not None:
                        self.callback_executor(lambda: self.on_disconnect(self))

    def _connect(self, poll_interval: float = 0.1) -> Optional[PendantHid]:
        while self._is_running:
            devices = [d for d in hid.enumerate() if (d["vendor_id"], d["product_id"]) in self.DEVICE_IDS]
            if len(devices) > 0:
                return PendantHid(devices)
            time.sleep(poll_interval)

        return None

    def _device_loop(self, device: PendantHid) -> None:
        while self._is_running:
            data = device.read(8, timeout=100)
            if len(data) > 0:
                self._process_input_packet(data)
            
            # Check for wheel inactivity and apply decay (runs continuously)
            current_time = time.time()
            if current_time - self._last_decay_check_time > 0.05:  # Check every 100ms
                time_since_last_activity = current_time - self._last_wheel_activity_time
                if time_since_last_activity > self._wheel_inactivity_timeout:
                    # Apply decay factor when wheel has been inactive
                    self._wheel_steps_per_second = 0
                self._last_decay_check_time = current_time
            
            if self._wheel_steps_per_second == 0:
                if self.on_stop_jog is not None:
                    self.callback_executor(lambda: self.on_stop_jog(self))

            if self.on_update is not None:
                self.callback_executor(lambda: self.on_update(self))
            self._refresh_display(device)

    def _process_input_packet(self, data: bytes) -> None:
        """
        Processes the input packet received from the device.
        This method should be overridden to handle specific data processing.
        """
        if len(data) != 8:
            return

        header, random_byte, button1, button2, step_rotary, \
             axis_rotary, jog_delta, crc = struct.unpack('BBBBBBbB', data)

        # As the checksum has not been reverse engineered yet, we will ignore it
        # for now and just check the header.
        if header != 0x04:
            return

        pressed_buttons = set()
        if button1 != 0:
            pressed_buttons.add(Button(button1))
        if button2 != 0:
            pressed_buttons.add(Button(button2))
        newly_pressed = pressed_buttons - self._pressed_buttons
        newly_released = self._pressed_buttons - pressed_buttons
        self._pressed_buttons = pressed_buttons

        has_axis_change = False
        try:
            active_axis = Axis(axis_rotary)
            has_axis_change = active_axis != self._active_axis
            self._active_axis = active_axis
        except ValueError:
            # We ignore error as quick rotary changes may lead to
            # invalid axis values.
            pass

        has_step_size_change = False
        try:
            step_rotary = StepSize(step_rotary)
            has_step_size_change = step_rotary != self._step_size
            self._step_size = step_rotary
        except ValueError:
            # We ignore error as quick rotary changes may lead to
            # invalid step size values.
            pass

        # We make sure that any callback is executed after fully updating the
        # internal state of the daemon so the callback can use the methods.
        for button in newly_pressed:
            print(f"WHB04 Daemon: Button pressed - {button.name}")
            if self.on_button_press is not None:
                self.callback_executor(lambda b=button: self.on_button_press(self, b))
        for button in newly_released:
            print(f"WHB04 Daemon: Button released - {button.name}")
            if self.on_button_release is not None:
                self.callback_executor(lambda b=button: self.on_button_release(self, b))

        if has_axis_change and self.on_axis_change is not None:
            print(f"WHB04 Daemon: Axis changed to {self._active_axis.name}")
            self.callback_executor(lambda a=self._active_axis: self.on_axis_change(self, a))

        if has_step_size_change and self.on_step_size_change is not None:
            print(f"WHB04 Daemon: Step size changed to {self._step_size.name}")
            self.callback_executor(lambda s=self._step_size: self.on_step_size_change(self, s))
        
        # Track wheel movement for improved stopping detection (only in continuous mode)
        current_time = time.time()
        
        if jog_delta != 0:
            # Update last activity time when we see actual movement
            self._last_wheel_activity_time = current_time
            
            # Store current step info for next calculation
            if self._last_step_time > 0:
                # Calculate rate based on time between this step and last step
                time_span = current_time - self._last_step_time
                if time_span > 0:
                    # Use the current delta steps for rate calculation
                    self._wheel_steps_per_second = abs(jog_delta) / time_span
                else:
                    self._wheel_steps_per_second = 0.0
            else:
                # First step, can't calculate rate yet
                self._wheel_steps_per_second = 0.0
            
            # Update for next iteration
            self._last_step_time = current_time
            self._last_step_delta = abs(jog_delta)
        
        # Determine if wheel is actively turning based on steps per second rate (only in continuous mode)
        # In step mode, always trigger jog for any non-zero delta
        # In continuous mode, only trigger if wheel is active
        should_trigger_jog = False
        if self._display_step_indicator == StepIndicator.STEP:
            # Step mode: trigger for any non-zero delta
            should_trigger_jog = jog_delta != 0
        else:
            # Continuous mode: trigger only if wheel is active
            should_trigger_jog = self.wheel_is_active
        
        if should_trigger_jog:
            if self.on_jog is not None:
                self.callback_executor(lambda d=jog_delta: self.on_jog(self, d))

    def _refresh_display(self, device: PendantHid) -> None:
        """
        Refreshes the display of the pedant.
        This method should be overridden to implement specific display logic.
        """
        display_flags = 0
        display_flags |= self._display_step_indicator.value
        if self._display_reset:
            display_flags |= 0x40
        if self._display_workpiece_coords:
            display_flags |= 0x80

        data = struct.pack('<HBB', 0xfdfe, 0xfe, display_flags)

        LIN_AXES = [Axis.X, Axis.Y, Axis.Z]
        ROT_AXES = [Axis.A, Axis.B, Axis.C]
        visible_axes = LIN_AXES if self._active_axis in LIN_AXES else ROT_AXES
        for coord in [self._display_position[a] for a in visible_axes]:
            coord_abs = abs(coord)
            coord_sign = 1 if coord < 0 else 0
            scaled_coord = int(round(coord_abs * 10000))
            integer_part = scaled_coord // 10000
            fraction_part = scaled_coord % 10000

            data += struct.pack('<HH',
                              integer_part & 0xFFFF,
                              (fraction_part & 0x7FFF) | (coord_sign << 15))

        data += struct.pack('<HH',
                            self._display_feedrate & 0xFFFF,
                            self._display_spindle_speed & 0xFFFF)

        # Add padding
        while len(data) < 21:
            data += b"\x00"

        # Split into packets of 7 bytes each
        for i in range(3):
            start_idx = i * 7
            end_idx = min(start_idx + 7, len(data))
            packet_data = data[start_idx:end_idx]

            # Pad to 7 bytes if needed
            while len(packet_data) < 7:
                packet_data += b'\x00'

            # Add report ID (0x06) at the beginning
            packet = b'\x06' + packet_data
            device.send_feature_report(packet)



if __name__ == "__main__":
    daemon = Daemon()

    daemon.set_display_step_indicator(StepIndicator.STEP)
    daemon.set_display_machine_coords()

    positions = {
        Axis.X: 0,
        Axis.Y: 0,
        Axis.Z: 0,
        Axis.A: 0
    }

    def update_jog(daemon: Daemon, jog_steps: int):
        distance = jog_steps * daemon.step_size_value
        positions[daemon.active_axis] += distance
        daemon.set_display_position(daemon.active_axis, positions[daemon.active_axis])


    daemon.on_connect = lambda _: print("Device connected")
    daemon.on_disconnect = lambda _: print("Device disconnected")
    daemon.on_button_press = lambda _, button: print(f"Button {button.name} pressed")
    daemon.on_button_release = lambda _, button: print(f"Button {button.name} released")
    daemon.on_jog = update_jog
    daemon.on_axis_change = lambda _, axis: print(f"Active axis changed to {axis.name}")
    daemon.on_step_size_change = lambda d, step_size: print(f"Step size changed to {step_size.name}/ {d.step_size_value}")


    daemon.start()
    while True:
        time.sleep(1)
