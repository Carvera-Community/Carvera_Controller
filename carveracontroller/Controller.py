#!/usr/bin/python


import logging
import math
import re
import sys
import threading
import time
import webbrowser

logger = logging.getLogger(__name__)

try:
    from Queue import *
except ImportError:
    from queue import *

from functools import partial

from . import Utils
from .CNC import CMDPAT, CNC, LASER_TOOL_NUMBER, PARENPAT, SEMIPAT, ZPROBE_TOOL_NUMBER
from .machine.command_flow import CommandFlowControl
from .protocols import MessageKind, ProtocolSession
from .USBStream import USBStream
from .WIFIStream import WIFIStream

try:
    from kivy.app import App
    from kivy.clock import Clock
except ImportError:
    # Fallback if kivy is not available (e.g., during testing)
    Clock = None
    App = None

STREAM_POLL = 0.2  # s
DIAGNOSE_POLL = 0.5  # s
RX_BUFFER_SIZE = 128

GPAT = re.compile(r"[A-Za-z]\s*[-+]?\d+.*")
FEEDPAT = re.compile(r"^(.*)[fF](\d+\.?\d+)(.*)$")

STATUSPAT = re.compile(
    r"^<(\w*?),MPos:([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),WPos:([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),?(.*)>$"
)
POSPAT = re.compile(r"^\[(...):([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*):?(\d*)\]$")
TLOPAT = re.compile(r"^\[(...):([+\-]?\d*\.\d*)\]$")
DOLLARPAT = re.compile(r"^\[G\d* .*\]$")
SPLITPAT = re.compile(r"[:,]")
VARPAT = re.compile(r"^\$(\d+)=(\d*\.?\d*) *\(?.*")


WIKI = "https://github.com/vlachoudis/bCNC/wiki"

CONNECTED = "Wait"
NOT_CONNECTED = "N/A"

STATECOLORDEF = (155 / 255, 155 / 255, 155 / 255, 1)  # Default color for unknown types or not connected
STATECOLOR = {
    "Idle": (52 / 255, 152 / 255, 219 / 255, 1),
    "Run": (34 / 255, 153 / 255, 84 / 255, 1),
    "Tool": (34 / 255, 153 / 255, 84 / 255, 1),
    "Alarm": (231 / 255, 76 / 255, 60 / 255, 1),
    "Home": (247 / 255, 220 / 255, 111 / 255, 1),
    "Hold": (34 / 255, 153 / 255, 84 / 255, 1),
    "Wait": (247 / 255, 220 / 255, 111 / 255, 1),
    "Disable": (100 / 255, 100 / 255, 100 / 255, 1),
    "Sleep": (220 / 255, 220 / 255, 220 / 255, 1),
    "Pause": (52 / 255, 152 / 255, 219 / 255, 1),
    NOT_CONNECTED: (155 / 255, 155 / 255, 155 / 255, 1),
}

LOAD_DIR = 1
LOAD_RM = 2
LOAD_MV = 3
LOAD_MKDIR = 4
LOAD_WIFI = 7
LOAD_CONN_WIFI = 8

SEND_FILE = 1

CONN_USB = 0
CONN_WIFI = 1


# ==============================================================================
# Controller class
# ==============================================================================
class Controller:
    MSG_NORMAL = 0
    MSG_ERROR = 1
    MSG_INTERIOR = 2

    JOG_MODE_STEP = 0
    JOG_MODE_CONTINUOUS = 1

    stop = threading.Event()
    usb_stream = None
    wifi_stream = None
    stream = None
    modem = None
    connection_type = CONN_WIFI

    def __init__(self, cnc, callback, log_sent_receive=False):
        self.usb_stream = USBStream(log_sent_receive)
        self.wifi_stream = WIFIStream(log_sent_receive)

        # Paces queued command sends so bursts (resume-at-line, CMM Workbench,
        # probing sequences) cannot overrun the firmware's single pending-command
        # slot / shallow command queue. Drained by streamIO.
        self._cmd_flow = CommandFlowControl()

        # Reconnection properties
        self.reconnect_enabled = True
        self.reconnect_wait_time = 10
        self.reconnect_attempts = 3
        self.reconnect_countdown = 0
        self.reconnect_timer = None
        self.reconnect_callback = None
        self.cancel_reconnect_callback = None
        self._manual_disconnect = False

        # Global variables
        self.history = []
        self._historyPos = None

        # CNC.loadConfig(Utils.config)
        self.cnc = cnc

        self.execCallback = callback

        self.log = Queue()  # Log queue returned from GRBL
        self.queue = Queue()  # Command queue to be send to GRBL
        self.load_buffer = Queue()
        self.load_buffer_size = 0
        self.total_buffer_size = 0

        self.loadNUM = 0
        self.loadEOF = False
        self.loadERR = False
        self.loadCANCEL = False
        self.loadCANCELSENT = False

        self.sendNUM = 0
        self.sendEOF = False
        self.sendCANCEL = False

        self.thread = None

        self.posUpdate = False  # Update position
        self.diagnoseUpdate = False
        self._probeUpdate = False  # Update probe
        self._gUpdate = False  # Update $G
        self._update = None  # Generic update

        self.cleanAfter = False
        self._runLines = 0
        self._quit = 0  # Quit counter to exit program
        self._stop = False  # Raise to stop current run
        self._pause = False  # machine is on Hold
        self._alarm = True  # Display alarm message if true

        self._baud_upgrade_attempted = False
        self._baud_switch_in_progress = False
        self._refresh_heartbeat = False
        # True from open() start until streamIO is running (hides half-open links from heartbeat).
        self._connecting = False
        # Epoch seconds; while time.time() < this, heartbeat will not drop the link.
        # Used after USB DTR reset while the machine is still booting.
        self._heartbeat_grace_until = 0.0
        # True while streamIO is idle (paused / no stream); used to sync baud switch.
        self._stream_io_parked = True

        self._msg = None
        self._sumcline = 0
        self._lastFeed = 0
        self._newFeed = 0

        self._onStart = ""
        self._onStop = ""

        self.paused = False
        self.pausing = False

        self.diagnosing = False

        self.is_community_firmware = False

        # Connection-scoped comms protocol (detect on open; follows M485 switches)
        self.comms = ProtocolSession(on_change=self._on_comms_protocol_changed)

        # Jog related variables
        self.jog_mode = Controller.JOG_MODE_STEP
        self.jog_speed = 10000  # mm/min. A value of 0 here would suggest to use last used feed
        self.continuous_jog_active = False
        # True after Ctrl+Y until firmware acks (^Y) — suppresses keepalives without
        # allowing a new $J -c to start before the previous jog has stopped.
        self._continuous_jog_stopping = False

    @property
    def protocol_ready(self):
        return self.comms.ready

    def _on_comms_protocol_changed(self, name, uses_framed_transfer):
        """Keep transports' file-transfer mode aligned with the comms session."""
        if self.usb_stream is not None:
            self.usb_stream.uses_framed_transfer = uses_framed_transfer
        if self.wifi_stream is not None:
            self.wifi_stream.uses_framed_transfer = uses_framed_transfer
        if self.comms.ready:
            self.log.put((self.MSG_NORMAL, f"Using {name} communication protocol"))

    # ----------------------------------------------------------------------
    def quit(self, event=None):
        pass

    # ----------------------------------------------------------------------
    def loadConfig(self):
        pass

    # ----------------------------------------------------------------------
    def saveConfig(self):
        pass

    # ----------------------------------------------------------------------
    # Execute a line as gcode if pattern matches
    # @return True on success
    # False otherwise
    # ----------------------------------------------------------------------
    def executeGcode(self, line):
        if isinstance(line, tuple) or line[0] in ("$", "!", "~", "?", "(", "@") or GPAT.match(line):
            self.sendGCode(line)
            return True
        return False

    # ----------------------------------------------------------------------
    # Execute a single command
    # ----------------------------------------------------------------------
    def executeCommand(self, line, immediate=False):
        if not (self.stream and line):
            return
        if isinstance(line, str) and not line.endswith("\n"):
            line += "\n"
        # Soft `reset` over USB leaves the board powered (zombie state).
        if isinstance(line, str) and self.connection_type == CONN_USB and line.lower().startswith("reset"):
            self._notify_usb_reset_blocked()
            return
        # Queue by default so bursts are paced by streamIO (firmware holds one
        # pending command over WiFi and a 4-deep queue over USB). `immediate`
        # bypasses the queue for commands that cannot wait for the drain loop:
        # abort/suspend/resume, and baud/reset flows that run while streamIO is
        # parked or about to tear the link down.
        if immediate or not self._stream_io_running():
            self._send_command_now(line)
            return
        self._cmd_flow.enqueue(line)
        self._echo_command(line)

    def _stream_io_running(self):
        thread = self.thread
        return thread is not None and thread.is_alive() and not self.stop.is_set()

    def _send_command_now(self, line, echo=True):
        try:
            payload = line.encode() if isinstance(line, str) else line
            self.stream.send(self.comms.encode_command(payload))
            if echo:
                self._echo_command(line)
        except Exception:
            self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))

    def _echo_command(self, line):
        if not self.execCallback:
            return
        display = line if isinstance(line, str) else line.decode(errors="ignore")
        # Strip ".lz" suffix for display
        if display.endswith(".lz\n"):
            display = display[:-4] + "\n"
        self.execCallback(display)

    def _notify_usb_reset_blocked(self):
        if App is None or Clock is None:
            return
        app = App.get_running_app()
        if app is None or getattr(app, "root", None) is None:
            return
        root = app.root
        if hasattr(root, "show_usb_reset_blocked_popup"):
            Clock.schedule_once(lambda dt: root.show_usb_reset_blocked_popup(), 0)

    def executeRealtime(self, char):
        """Send a single-byte realtime control through the active protocol."""
        self.executeRealtimeSequence(char)

    def executeRealtimeSequence(self, *chars):
        """Send one or more realtime bytes in a single write.

        Smoothie continuous-jog keepalive is the digram ``?1``. Sending ``?`` and
        ``1`` as separate writes races with other commands and leaves orphaned
        ``1`` bytes in the firmware command buffer (seen as ``111…$J …``).
        """
        if not self.stream or not chars:
            return
        try:
            payload = bytearray()
            for char in chars:
                if isinstance(char, (bytes, bytearray)):
                    char = char[0]
                payload.extend(self.comms.encode_realtime(int(char)))
            self.stream.send(bytes(payload))
        except Exception:
            self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))

    def executeFileCommand(self, line):
        """Send an upload/download initiation command through the active protocol."""
        if self.stream and line:
            try:
                if isinstance(line, str) and not line.endswith("\n"):
                    line += "\n"
                payload = line.encode() if isinstance(line, str) else line
                self.stream.send(self.comms.encode_file_command(payload))
                if self.execCallback:
                    display = line if isinstance(line, str) else line.decode(errors="ignore")
                    if display.endswith(".lz\n"):
                        new_line = display[:-4] + "\n"
                    else:
                        new_line = display
                    self.execCallback(new_line)
            except Exception:
                self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))

    # ----------------------------------------------------------------------
    def autoCommand(
        self,
        margin=False,
        zprobe=False,
        zprobe_abs=False,
        leveling=False,
        goto_origin=False,
        z_probe_offset_x=0,
        z_probe_offset_y=0,
        i=3,
        j=3,
        h=5,
        buffer=False,
        auto_level_offsets=None,
        upcoming_tool=0,
    ):
        if not (margin or zprobe or leveling or goto_origin):
            return
        if auto_level_offsets is None:
            auto_level_offsets = [0, 0, 0, 0]
        if abs(CNC.vars["xmin"]) > CNC.vars["worksize_x"] or abs(CNC.vars["ymin"]) > CNC.vars["worksize_y"]:
            return
        cmd = "M495 X%gY%g" % (CNC.vars["xmin"], CNC.vars["ymin"])
        if margin:
            cmd = cmd + "C%gD%g" % (CNC.vars["xmax"], CNC.vars["ymax"])
            if buffer:
                cmd = "buffer " + cmd
            self.executeCommand(
                cmd
            )  # run margin command. Has to be two seperate commands to offset the start of the autolevel process
        cmd = "M495 X%gY%g" % (
            CNC.vars["xmin"] + auto_level_offsets[0],
            CNC.vars["ymin"] + auto_level_offsets[2],
        )  # reinitialize command with any autolevel offsets
        if zprobe:
            if zprobe_abs:
                cmd = "M495 X%gY%g" % (CNC.vars["xmin"], CNC.vars["ymin"])  # reset command for 4th axis
                cmd = cmd + "O0"
            else:
                cmd = cmd + "O%gF%g" % (z_probe_offset_x, z_probe_offset_y)
        if leveling:
            cmd = cmd + "A%gB%gI%dJ%dH%d" % (
                CNC.vars["xmax"] - (CNC.vars["xmin"] + auto_level_offsets[1] + auto_level_offsets[0]),
                CNC.vars["ymax"] - (CNC.vars["ymin"] + auto_level_offsets[3] + auto_level_offsets[2]),
                i,
                j,
                h,
            )
        if goto_origin:
            cmd = cmd + "P1"
            # Include the first tool number so firmware can do tool change/TLO before going to origin
            if upcoming_tool > 0:
                cmd = cmd + "T%d" % upcoming_tool
        cmd = cmd + "\n"
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def xyzProbe(self, height=9.0, diameter=3.175, buffer=False):
        cmd = "M495.3 H%g D%g" % (height, diameter)
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def pairWP(self):
        self.executeCommand("M471")

    def syncTime(self, *args):
        self.executeCommand("time " + str(int(time.time()) - time.timezone))

    def queryTime(self, *args):
        self.executeCommand("time")

    def queryVersion(self, *args):
        self.executeCommand("version")

    def queryModel(self, *args):
        self.executeCommand("model")

    def queryFtype(self, *args):
        self.executeCommand("ftype")

    # # ----------------------------------------------------------------------
    # def zProbeCommand(self, c=0, d=0, buffer=False):
    #     cmd = "M494 X%gY%gC%gD%g\n" % (CNC.vars['xmin'], CNC.vars['ymin'], c, d)
    #     if buffer:
    #         cmd = "buffer " + cmd
    #     self.executeCommand(cmd)

    # def autoLevelCommand(self, i=3, j=3, buffer=False):
    #     cmd = "M495 X%gY%gA%gB%gI%dJ%d\n" % (CNC.vars['xmin'], CNC.vars['ymin'], CNC.vars['xmax'] - CNC.vars['xmin'], CNC.vars['ymax'] - CNC.vars['ymin'], i, j)
    #     if buffer:
    #         cmd = "buffer " + cmd
    #     self.executeCommand(cmd)

    # def probeLevelCommand(self, i=3, j=3, buffer=False):
    #     cmd = "M496 X%gY%gA%gB%gI%dJ%d\n" % (CNC.vars['xmin'], CNC.vars['ymin'], CNC.vars['xmax'] - CNC.vars['xmin'], CNC.vars['ymax'] - CNC.vars['ymin'], i, j)
    #     if buffer:
    #         cmd = "buffer " + cmd
    #     self.executeCommand(cmd)

    def gotoClearance(self, buffer=False):
        cmd = "M496.1\n"
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def gotoWorkOrigin(self, buffer=False):
        cmd = "M496.2\n"
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def gotoAnchor1(self, buffer=False):
        cmd = "M496.3\n"
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def gotoAnchor2(self, buffer=False):
        cmd = "M496.4\n"
        if buffer:
            cmd = "buffer " + cmd
        self.executeCommand(cmd)

    def gotoPathOrigin(self, buffer=False):
        if abs(CNC.vars["xmin"]) <= CNC.vars["worksize_x"] and abs(CNC.vars["ymin"]) <= CNC.vars["worksize_y"]:
            cmd = "M496.5 X%gY%g\n" % (CNC.vars["xmin"], CNC.vars["ymin"])
            if buffer:
                cmd = "buffer " + cmd
            self.executeCommand(cmd)

    def gotoPosition(self, position, buffer=False):
        """Legacy method to route to appropriate goto method based on position string"""
        if position is None:
            return
        if position == "Clearance":
            self.gotoClearance(buffer)
        elif position == "Work Origin":
            self.gotoWorkOrigin(buffer)
        elif position == "Anchor1":
            self.gotoAnchor1(buffer)
        elif position == "Anchor2":
            self.gotoAnchor2(buffer)
        elif position == "Path Origin":
            self.gotoPathOrigin(buffer)

    def reset(self):
        self.executeCommand("reset\n", immediate=True)

    def change(self):
        app = App.get_running_app()
        if app.has_atc:
            self.executeCommand("M490.4\n")
        else:
            self.executeCommand("M490.2\n")

    def setFeedScale(self, scale):
        app = App.get_running_app()
        if (
            app.is_community_firmware and app.fw_version_digitized >= Utils.digitize_v("2.1.0")
        ) and app.root.instantFSoverride:
            self.executeCommand("$F S%d\n" % (scale))
            return
        self.executeCommand("M220 S%d\n" % (scale))

    def setLaserScale(self, scale):
        self.executeCommand("M325 S%d\n" % (scale))

    def setSpindleScale(self, scale):
        app = App.get_running_app()
        if (
            app.is_community_firmware and app.fw_version_digitized >= Utils.digitize_v("2.1.0")
        ) and app.root.instantFSoverride:
            self.executeCommand("$O S%d\n" % (scale))
            return
        self.executeCommand("M223 S%d\n" % (scale))

    def clearAutoLeveling(self):
        self.executeCommand("M370\n")

    def setSpindleSwitch(self, switch, rpm=None):
        if switch and rpm is not None:
            cmd = f"M3 S{int(rpm)}\n"
        elif switch and rpm is None:
            cmd = "M3\n"
        else:
            cmd = "M5\n"
        self.executeCommand(cmd)

    def setVacuumPower(self, power=0):
        if power > 0:
            self.executeCommand("M801 S%d\n" % (power))
        else:
            self.executeCommand("M802\n")

    def setSpindlefanPower(self, power=0):
        if power > 0:
            self.executeCommand("M811 S%d\n" % (power))
        else:
            self.executeCommand("M812\n")

    def setLaserPower(self, power=0):
        if power > 0:
            self.executeCommand("M3 S%g\n" % (power * 1.0 / 100))
        else:
            self.executeCommand("M5\n")

    def setLightSwitch(self, switch):
        if switch:
            self.executeCommand("M821\n")
        else:
            self.executeCommand("M822\n")

    def setExternalControl(self, pwm=100):
        if pwm > 0:
            self.executeCommand("M851 S%g\n" % (pwm))
        else:
            self.executeCommand("M852\n")

    def setToolSensorSwitch(self, switch):
        if switch:
            self.executeCommand("M831\n")
        else:
            self.executeCommand("M832\n")

    def setAirSwitch(self, switch):
        if switch:
            self.executeCommand("M7\n")
        else:
            self.executeCommand("M9\n")

    def setPWChargeSwitch(self, switch):
        if switch:
            self.executeCommand("M841\n")
        else:
            self.executeCommand("M842\n")

    def setVacuumMode(self, mode):
        if mode:
            self.executeCommand("M331\n")
        else:
            self.executeCommand("M332\n")

    def setExtOutMode(self, mode):
        if mode:
            self.executeCommand("M331.3\n")
        else:
            self.executeCommand("M332.3\n")

    def setLaserMode(self, mode):
        if mode:
            self.executeCommand("M321\n")
        else:
            self.executeCommand("M322\n")

    def setLaserTest(self, test):
        if test:
            self.executeCommand("M323\n")
        else:
            self.executeCommand("M324\n")

    def setConfigValue(self, key, value):
        if key and value:
            self.executeCommand("config-set sd %s %s\n" % (key, value))

    def dropToolCommand(self):
        self.executeCommand("M6T-1\n")

    def calibrateToolCommand(self):
        self.executeCommand("M491\n")

    def calibrate_tool_advanced_command(self, repeat_count=1, x_offset=0.0, y_offset=0.0):
        parts = ["M491"]
        if x_offset != 0:
            parts.append("X%g" % x_offset)
        if y_offset != 0:
            parts.append("Y%g" % y_offset)
        if repeat_count != 1:
            parts.append("R%d" % repeat_count)
        self.executeCommand(" ".join(parts) + "\n")

    def clampToolCommand(self):
        self.executeCommand("M490.1\n")

    def unclampToolCommand(self):
        self.executeCommand("M490.2\n")

    def change_tool_command(self, tool):
        if tool == "e":
            self.executeCommand("M6T%d\n" % ZPROBE_TOOL_NUMBER)
        elif tool == "r":
            self.executeCommand("M6T%d\n" % LASER_TOOL_NUMBER)
        elif tool == "m":
            # custom tool number
            pass
        else:
            self.executeCommand("M6T%s\n" % tool)

    def set_tool_command(self, tool):
        if tool == "e":
            self.executeCommand("M493.2T%d\n" % ZPROBE_TOOL_NUMBER)
        elif tool == "r":
            self.executeCommand("M493.2T%d\n" % LASER_TOOL_NUMBER)
        elif tool == "m":
            # custom tool number
            pass
        elif tool == "y":
            self.executeCommand("M493.2T-1\n")
        else:
            self.executeCommand("M493.2T%s\n" % tool)

    def bufferChangeToolCommand(self, tool):
        self.executeCommand("buffer M6T%s\n" % tool)

    # ------------------------------------------------------------------------------
    # escape special characters
    # ------------------------------------------------------------------------------
    def escape(self, value):
        """Escape special characters for protocol transmission"""
        return value.replace("?", "\x02").replace("&", "\x03").replace("!", "\x04").replace("~", "\x05")

    def lsCommand(self, ls_dir):
        ls_command = "ls -e -s %s\n" % ls_dir.replace(" ", "\x01")
        if "\\" in ls_dir:
            ls_command = "ls -e -s %s\n" % "/".join(ls_dir.split("\\")).replace(" ", "\x01")
        self.executeCommand(self.escape(ls_command))

    def catCommand(self, filename):
        cat_command = "cat %s -e\n" % filename.replace(" ", "\x01")
        if "\\" in filename:
            cat_command = "cat %s -e\n" % "/".join(filename.split("\\")).replace(" ", "\x01")
        self.executeCommand(self.escape(cat_command))

    def rmCommand(self, filename):
        rm_command = "rm %s -e\n" % filename.replace(" ", "\x01")
        if "\\" in filename:
            rm_command = "rm %s -e\n" % "/".join(filename.split("\\")).replace(" ", "\x01")
        self.executeCommand(self.escape(rm_command))

    def mvCommand(self, file, newfile):
        mv_command = "mv %s %s -e\n" % (file.replace(" ", "\x01"), newfile.replace(" ", "\x01"))
        if "\\" in file or "\\" in newfile:
            mv_command = "mv %s %s -e\n" % (
                "/".join(file.split("\\")).replace(" ", "\x01"),
                "/".join(newfile.split("\\")).replace(" ", "\x01"),
            )
        self.executeCommand(self.escape(mv_command))

    def mkdirCommand(self, dirname):
        mkdir_command = "mkdir %s -e\n" % dirname.replace(" ", "\x01")
        if "\\" in dirname:
            mkdir_command = "mkdir %s -e\n" % "/".join(dirname.split("\\")).replace(" ", "\x01")
        self.executeCommand(self.escape(mkdir_command))

    def md5Command(self, filename):
        md5_command = "md5sum %s -e\n" % filename.replace(" ", "\x01")
        if "\\" in filename:
            md5_command = "md5sum %s -e\n" % "/".join(filename.split("\\")).replace(" ", "\x01")
        self.executeCommand(self.escape(md5_command))

    def loadWiFiCommand(self):
        self.executeCommand("wlan -e\n")

    def disconnectWiFiCommand(self):
        self.executeCommand("wlan -d disconnect\n")

    def connectWiFiCommand(self, ssid, password):
        wifi_command = "wlan %s %s -e\n" % (ssid.replace(" ", "\x01"), password.replace(" ", "\x01"))
        self.executeCommand(self.escape(wifi_command))

    def loadConfigCommand(self):
        self.executeCommand("config-get-all -e\n")

    def restoreConfigCommand(self):
        self.executeCommand("config-restore\n")

    def defaultConfigCommand(self):
        self.executeCommand("config-default\n")

    def uploadCommand(self, filename):
        upload_command = "upload %s\n" % filename.replace(" ", "\x01")
        if "\\" in filename:
            upload_command = "upload %s\n" % "/".join(filename.split("\\")).replace(" ", "\x01")
        self.executeFileCommand(self.escape(upload_command))

    def downloadCommand(self, filename):
        download_command = "download %s\n" % filename.replace(" ", "\x01")
        if "\\" in filename:
            download_command = "download %s\n" % "/".join(filename.split("\\")).replace(" ", "\x01")
        self.executeFileCommand(self.escape(download_command))

    def suspendCommand(self):
        # Must not wait behind queued bursts: this is the user hitting pause.
        self.executeCommand("suspend\n", immediate=True)

    def resumeCommand(self):
        self.executeCommand("resume\n", immediate=True)

    def playCommand(self, filename, has_ocodes=False):
        flag = " -O" if has_ocodes else ""
        play_command = "play %s%s\n" % (filename.replace(" ", "\x01"), flag)
        if "\\" in filename:
            play_command = "play %s%s\n" % ("/".join(filename.split("\\")).replace(" ", "\x01"), flag)
        self.executeCommand(self.escape(play_command))

    def _binary_find_left(self, array, key):
        """
        Binary search to find the leftmost position where key could be inserted.
        Returns the index of the last element less than key, or -1 if key is smaller than all elements.
        """
        length = len(array)
        ans = length
        l = 0
        r = length - 1
        while l <= r:
            mid = (l + r) >> 1
            if array[mid] >= key:
                ans = mid
                r = mid - 1
            else:
                l = mid + 1
        return ans - 1

    def _get_line_position_from_gcode_viewer(self, line_number):
        """
        Get the X/Y/Z/A position for a specific line number from the loaded gcode file using GcodeViewer.

        Args:
            line_number: The line number (1-based) to get position for

        Returns:
            Tuple of (x, y, z, a) where x, y, z are floats and a is float or None.
            Returns (None, None, None, None) if position cannot be determined.
        """
        if App is None:
            return (None, None, None, None)

        try:
            app = App.get_running_app()
            if not app or not hasattr(app.root, "gcode_viewer") or not app.root.gcode_viewer:
                return (None, None, None, None)

            gcode_viewer = app.root.gcode_viewer

            # Check if gcode_viewer has the necessary data
            if not hasattr(gcode_viewer, "raw_linenumbers") or not gcode_viewer.raw_linenumbers:
                return (None, None, None, None)

            # Convert line_number to float for comparison (raw_linenumbers stores floats)
            line_num_float = float(line_number)

            # Find the vertex index for this line number using binary search
            left_pos = self._binary_find_left(gcode_viewer.raw_linenumbers, line_num_float)

            # Find the rightmost position with the same line number
            right_pos = left_pos
            while (
                right_pos < len(gcode_viewer.raw_linenumbers) - 1
                and gcode_viewer.raw_linenumbers[right_pos + 1] == line_num_float
            ):
                right_pos = right_pos + 1

            # Use the rightmost position (end of line) to get the final position
            vertex_idx = right_pos

            # Validate vertex index
            if vertex_idx < 0 or vertex_idx >= len(gcode_viewer.raw_linenumbers):
                return (None, None, None, None)

            # Get position from meshmanager (use raw_positions for unrotated G-code coordinates)
            if hasattr(gcode_viewer, "meshmanager") and gcode_viewer.meshmanager:
                # Use raw_positions array for unrotated G-code coordinates
                if hasattr(gcode_viewer.meshmanager, "raw_positions") and gcode_viewer.meshmanager.raw_positions:
                    pos_idx = vertex_idx * 3
                    if pos_idx + 2 < len(gcode_viewer.meshmanager.raw_positions):
                        x = gcode_viewer.meshmanager.raw_positions[pos_idx]
                        y = gcode_viewer.meshmanager.raw_positions[pos_idx + 1]
                        z = gcode_viewer.meshmanager.raw_positions[pos_idx + 2]

                        # Get angle if 4-axis
                        a = None
                        if (
                            hasattr(gcode_viewer.meshmanager, "angles_of_vertices")
                            and gcode_viewer.meshmanager.angles_of_vertices
                        ):
                            if vertex_idx < len(gcode_viewer.meshmanager.angles_of_vertices):
                                a = gcode_viewer.meshmanager.angles_of_vertices[vertex_idx]

                        return (x, y, z, a)
            else:
                # Fallback: use raw_positions array directly from gcode_viewer
                if hasattr(gcode_viewer, "raw_positions") and gcode_viewer.raw_positions:
                    pos_idx = vertex_idx * 3
                    if pos_idx + 2 < len(gcode_viewer.raw_positions):
                        x = gcode_viewer.raw_positions[pos_idx]
                        y = gcode_viewer.raw_positions[pos_idx + 1]
                        z = gcode_viewer.raw_positions[pos_idx + 2]

                        # Get angle if 4-axis
                        a = None
                        if hasattr(gcode_viewer, "angles_of_vertices") and gcode_viewer.angles_of_vertices:
                            if vertex_idx < len(gcode_viewer.angles_of_vertices):
                                a = gcode_viewer.angles_of_vertices[vertex_idx]

                        return (x, y, z, a)

            return (None, None, None, None)

        except Exception as e:
            logger.warning(f"Error getting line position from gcode_viewer for line {line_number}: {e}")
            return (None, None, None, None)

    def _find_m3_spindle_speed(self, lines, start_line):
        """
        Search backwards from start_line to find M3 commands and extract S (spindle speed) parameter.
        First checks the most recent M3 command, then searches backwards if no S parameter found.

        Args:
            lines: Gcode file lines (1-based line numbers index into this list)
            start_line: Line number to search backwards from (1-based)

        Returns:
            Spindle speed value as float, or None if not found
        """
        if not lines:
            return None

        try:
            # Ensure start_line is an integer
            try:
                start_line = int(start_line)
            except (ValueError, TypeError):
                logger.warning(f"Invalid start_line value: {start_line}")
                return None

            if start_line < 1 or start_line > len(lines):
                return None

            # First, find the most recent M3 command and check if it has S parameter.
            # Token matching normalizes zero-padded forms such as M03 without
            # confusing other M-codes such as M30.
            most_recent_m3_line = None
            for i in range(start_line - 2, -1, -1):
                has_m3, spindle_speed = self._m3_spindle_speed_from_line(lines[i])
                if has_m3:
                    most_recent_m3_line = i
                    if spindle_speed is not None:
                        return spindle_speed
                    # Found M3 but no S parameter, continue searching backwards
                    break

            # If we found M3 but no S parameter, search backwards for previous M3 with S
            if most_recent_m3_line is not None:
                for i in range(most_recent_m3_line - 1, -1, -1):
                    has_m3, spindle_speed = self._m3_spindle_speed_from_line(lines[i])
                    if has_m3 and spindle_speed is not None:
                        return spindle_speed

            return None

        except Exception as e:
            logger.warning(f"Error finding M3 spindle speed before line {start_line}: {e}")
            return None

    def _m3_spindle_speed_from_line(self, line):
        tokens = self._gcode_line_to_cmd_tokens(line)
        has_m3 = any(self._command_token_matches_base(token, "M3") for token in tokens)
        if not has_m3:
            return (False, None)

        for token in reversed(tokens):
            if token[:1].upper() != "S":
                continue
            try:
                return (True, float(token[1:]))
            except (ValueError, TypeError):
                continue
        return (True, None)

    def _find_last_feed_rate(self, lines=None, start_line=None, feed_lookup=None):
        """
        Return the feed rate (mm/min) in effect at start_line. Uses either pre-parsed
        feed data from the CNC parser or scans gcode lines.

        Args:
            lines: Gcode file lines (used when feed_lookup is None)
            start_line: Line number to search backwards from (1-based)
            feed_lookup: Optional dict mapping line_no (int) -> feed (float) from CNC
                         coordinates; when provided, lines is not scanned.

        Returns:
            Feed rate value as float, or None if not found
        """
        if feed_lookup is not None and start_line is not None:
            try:
                start_line = int(start_line)
            except (ValueError, TypeError):
                return None
            for line_no in range(start_line, 0, -1):
                if line_no in feed_lookup:
                    return feed_lookup[line_no]
            return None

        if not lines:
            return None

        try:
            # Ensure start_line is an integer
            try:
                start_line = int(start_line)
            except (ValueError, TypeError):
                logger.warning(f"Invalid start_line value: {start_line}")
                return None

            if start_line < 1 or start_line > len(lines):
                return None

            # F is modal independently of a motion command, so the most recent
            # feed word may be on a standalone or tightly packed G-code line.
            for i in range(start_line - 2, -1, -1):
                for token in reversed(self._gcode_line_to_cmd_tokens(lines[i])):
                    if token[:1].upper() != "F":
                        continue
                    try:
                        return float(token[1:])
                    except (ValueError, TypeError):
                        continue

            return None

        except Exception as e:
            logger.warning(f"Error finding feed rate before line {start_line}: {e}")
            return None

    def _gcode_line_to_cmd_tokens(self, original_line):
        """
        Split a physical line into G-code words the same way CNC.parseLine does.
        Handles multi-command blocks (e.g. 'G90 G94', 'G17 G21 G54') without false
        substring matches (e.g. G17 matching a search for G1).
        """
        line = original_line.strip()
        if not line or line[0] in ("%", "#", ";"):
            return []
        line = PARENPAT.sub("", line)
        line = SEMIPAT.sub("", line)
        if not line.strip():
            return []
        line = line.replace(" ", "")
        if not line:
            return []
        tokenized = CMDPAT.sub(r" \1", line).lstrip()
        return tokenized.split()

    def _command_token_matches_base(self, token, base_command):
        """True if token is the same modal word as base_command (G0/G00, but not G17 for G1)."""
        if not token or not base_command:
            return False
        t, b = token.upper(), base_command.upper()
        if t == b:
            return True
        if len(b) < 2 or len(t) < 2 or t[0] != b[0] or b[0] not in ("G", "M"):
            return False
        if "." in b or "." in t:
            return False
        try:
            return int(float(t[1:])) == int(float(b[1:]))
        except ValueError:
            return False

    def _is_tool_select_token(self, token):
        tu = token.upper()
        if len(tu) < 2 or tu[0] != "T":
            return False
        return tu[1:].isdigit()

    def _compose_m6_command_from_tokens(self, tokens, m6_index):
        """Build e.g. 'T4 M6' or 'M6 T4' from the line's tokens (same line as M6)."""
        parts = []
        if m6_index > 0 and self._is_tool_select_token(tokens[m6_index - 1]):
            parts.append(tokens[m6_index - 1].upper())
        parts.append(tokens[m6_index].upper())
        if m6_index + 1 < len(tokens) and self._is_tool_select_token(tokens[m6_index + 1]):
            parts.append(tokens[m6_index + 1].upper())
        return " ".join(parts)

    def _find_command_line_number(self, lines, start_line, gcode_command):
        """
        Search backwards from start_line to find the last occurrence of a gcode command.

        Args:
            lines: Gcode file lines (1-based line numbers index into this list)
            start_line: Line number to search backwards from (1-based)
            gcode_command: Literal gcode command to search for (e.g., "G20", "G21", "M3", "M6")
                          Can include parameters (e.g., "M3 S1000", "M6 T1")

        Returns:
            Tuple of (command_string, line_number). For M6, includes adjacent T on the same line
            (e.g. 'T4 M6'). Otherwise the matched modal word (e.g. G90 from 'G90 G94').
        """
        if not lines:
            return (None, None)

        try:
            # Ensure start_line is an integer
            try:
                start_line = int(start_line)
            except (ValueError, TypeError):
                logger.warning(f"Invalid start_line value: {start_line}")
                return (None, None)

            if start_line < 1 or start_line > len(lines):
                return (None, None)

            command_upper = gcode_command.upper().strip()
            base_command = command_upper.split()[0]

            for i in range(start_line - 2, -1, -1):
                tokens = self._gcode_line_to_cmd_tokens(lines[i])
                for ti in range(len(tokens) - 1, -1, -1):
                    token = tokens[ti]
                    if self._command_token_matches_base(token, base_command):
                        if base_command.upper() == "M6":
                            return (self._compose_m6_command_from_tokens(tokens, ti), i + 1)
                        return (token.upper(), i + 1)

        except Exception as e:
            logger.warning(f"Error finding command {gcode_command} before line {start_line}: {e}")

        return (None, None)

    def _has_movement_after_line(self, lines, after_line, before_start_line):
        """
        Return True if any G0–G3 command appears on a line strictly after after_line
        and before before_start_line.
        """
        for cmd in ("G0", "G1", "G2", "G3"):
            _, line_num = self._find_command_line_number(lines, before_start_line, cmd)
            if line_num is not None and line_num > after_line:
                return True
        return False

    def resume_playback_warnings(self, commands):
        """
        Inspect resume-at-line command preview and return missing-state warning keys.

        Returns a list that may include:
          - "tool_change": no M6 tool change in the recovery sequence
          - "feed": no G1 F feed rate restored
          - "spindle_speed": no M3 S spindle speed restored (skipped for laser/M321)
        """
        if not commands:
            return ["tool_change", "feed", "spindle_speed"]

        joined = "\n".join(commands).upper()
        warnings = []
        if not re.search(r"\bM0*6\b", joined):
            warnings.append("tool_change")
        if not re.search(r"\bG0*1\s+F\d", joined):
            warnings.append("feed")
        # Laser mode does not use spindle S recovery
        if not re.search(r"\bM321\b", joined) and not re.search(r"\bM0*3\s+S\d", joined):
            warnings.append("spindle_speed")
        return warnings

    def playStartLineCommand(self, filename, start_line, preview=False, lines=None, has_ocodes=False):
        # Build the play command with proper formatting
        flag = " -O" if has_ocodes else ""
        play_command = "play %s%s\n" % (filename.replace(" ", "\x01"), flag)
        if "\\" in filename:
            play_command = "play %s%s" % ("/".join(filename.split("\\")).replace(" ", "\x01"), flag)

        # Position to move to before start: derive from GcodeViewer state at (start_line - 1)
        try:
            start_line_int = int(start_line)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid start line: {start_line!r}")

        if not lines:
            raise ValueError("Gcode lines required for resume-at-line")

        # Use the line immediately before start_line so that _get_line_position_from_gcode_viewer
        # returns the machine state after executing through that line.
        prev_line = max(1, start_line_int - 1) if start_line_int is not None else None
        position = self._get_line_position_from_gcode_viewer(prev_line) if prev_line else (None, None, None, None)
        x, y, z, a = position

        app = App.get_running_app() if App is not None else None

        # Find additional commands to insert after "goto"
        # Note the use of buffer is to avoid the firmware bug https://github.com/Carvera-Community/Carvera_Community_Firmware/issues/211
        additional_commands = []
        m6_line = None

        if lines:
            # Search for G20 or G21 (unit mode) - take the last one found
            _, g20_line = self._find_command_line_number(lines, start_line, "G20")
            _, g21_line = self._find_command_line_number(lines, start_line, "G21")
            # Determine which was found last by checking which line number is higher
            if g20_line is not None and g21_line is not None:
                # Both found, take the one with higher line number (more recent)
                if g20_line > g21_line:
                    additional_commands.append("buffer G20")
                else:
                    additional_commands.append("buffer G21")
            elif g20_line:
                additional_commands.append("buffer G20")
            elif g21_line:
                additional_commands.append("buffer G21")

            # Absolute vs incremental distance mode (G90 / G91), including on shared lines e.g. G90 G94
            _, g90_line = self._find_command_line_number(lines, start_line, "G90")
            _, g91_line = self._find_command_line_number(lines, start_line, "G91")
            if g90_line is not None and g91_line is not None:
                if g90_line > g91_line:
                    additional_commands.append("buffer G90")
                elif g91_line > g90_line:
                    additional_commands.append("buffer G91")
                else:
                    # Same line: last G90/G91 word wins (e.g. G91 G90)
                    last_mode = None
                    try:
                        joint_line = lines[g90_line - 1]
                        for tok in self._gcode_line_to_cmd_tokens(joint_line):
                            tu = tok.upper()
                            if tu == "G90":
                                last_mode = "G90"
                            elif tu == "G91":
                                last_mode = "G91"
                    except IndexError as e:
                        logger.warning(
                            "Could not read line %s for G90/G91 tie-break: %s",
                            g90_line,
                            e,
                        )
                    if last_mode:
                        additional_commands.append(f"buffer {last_mode}")
            elif g90_line:
                additional_commands.append("buffer G90")
            elif g91_line:
                additional_commands.append("buffer G91")

            # Search for WCS coordinate space - find the last one used
            wcs_commands = [
                ("G54", self._find_command_line_number(lines, start_line, "G54")),
                ("G55", self._find_command_line_number(lines, start_line, "G55")),
                ("G56", self._find_command_line_number(lines, start_line, "G56")),
                ("G57", self._find_command_line_number(lines, start_line, "G57")),
                ("G58", self._find_command_line_number(lines, start_line, "G58")),
                ("G59", self._find_command_line_number(lines, start_line, "G59")),
                ("G59.1", self._find_command_line_number(lines, start_line, "G59.1")),
                ("G59.2", self._find_command_line_number(lines, start_line, "G59.2")),
                ("G59.3", self._find_command_line_number(lines, start_line, "G59.3")),
            ]
            # Find the WCS command with the highest line number (most recent)
            last_wcs = None
            last_wcs_line = 0
            for wcs_cmd, (wcs_cmd_str, wcs_line) in wcs_commands:
                if wcs_line is not None and wcs_line > last_wcs_line:
                    last_wcs = wcs_cmd
                    last_wcs_line = wcs_line
            if last_wcs:
                additional_commands.append(f"buffer {last_wcs}")

            # Search for M7 (air assist on) and M9 (air assist off)
            _, m7_line = self._find_command_line_number(lines, start_line, "M7")
            _, m9_line = self._find_command_line_number(lines, start_line, "M9")
            if m7_line is not None and m9_line is not None:
                if m7_line > m9_line:
                    additional_commands.append("buffer M7")
            elif m7_line:
                additional_commands.append("buffer M7")

            # Search for M6 (tool change)
            # +1 to start_line because would be silly to change to the previous tool only to change to something else
            # _find_command_line_number() only searchs backwards
            m6_cmd, m6_line = self._find_command_line_number(lines, start_line_int + 1, "M6")
            if m6_cmd:
                additional_commands.append(f"buffer {m6_cmd}")

            # Search for M3 (spindle on), M5 (spindle off), M321 (laser mode on), and M322 (laser mode off)
            m3_cmd, m3_line = self._find_command_line_number(lines, start_line, "M3")
            _, m5_line = self._find_command_line_number(lines, start_line, "M5")
            _, m321_line = self._find_command_line_number(lines, start_line, "M321")
            _, m322_line = self._find_command_line_number(lines, start_line, "M322")

            if (m321_line or 0) > max(
                m322_line or 0, m5_line or 0, m3_line or 0
            ):  # Yucky way to compare with vars that might be NoneType. Sorry
                # Laser mode was last used
                additional_commands.append("buffer M321")
            elif (m3_line or 0) > max(m321_line or 0, m5_line or 0):
                # Spindle mode was last used
                # Need to search for last spindle speed since it could have been set in a different command
                spindle_speed = self._find_m3_spindle_speed(lines, start_line)
                if spindle_speed is not None:
                    additional_commands.append(f"buffer M3 S{spindle_speed:.0f}")
                else:
                    additional_commands.append("buffer M3")

        # Add SafeZ movement (G53 G0 Z-2)
        # This should come after coordinate system setup but before position movement
        additional_commands.append("buffer G53 G0 Z-2")

        # Rapid XY first, then A. A combined G0 XY+A is often very slow because
        # the planner must synchronize all axes

        if x is not None or y is not None:
            g0_xy = "G0"
            if x is not None:
                g0_xy += f" X{x:.3f}"
            if y is not None:
                g0_xy += f" Y{y:.3f}"
            additional_commands.append(f"buffer {g0_xy}")

        # Only move A when CNC parser marked the loaded program as 4-axis
        if a is not None and app is not None and app.has_4axis:
            a_machine = a * -1  # need to flip positive to negative due to a "right hand rule" rotation in gcode viewer
            additional_commands.append(f"buffer G0 A{a_machine:.3f}")
        # Set the G1 feed modal
        feed_rate = None
        if lines:
            feed_rate = self._find_last_feed_rate(lines, start_line)
        if feed_rate:
            additional_commands.append(f"buffer G1 F{feed_rate:.0f}")

        # Add G1 movement into the Z position if tool change line is before than any movements
        # If no movements have occured between tool change and prev_line then the Z position isn't correct
        if z is not None and (m6_line is None or self._has_movement_after_line(lines, m6_line, start_line_int)):
            additional_commands.append(f"buffer G1 Z{z:.3f}")

        # the goto command in firmware is bugged in versions < 2.1.0c and Makera releases
        # the bug is that it goes to the end of the line specified instead of start.
        start_line_comment = ""

        if app is not None and not (
            app.is_community_firmware and app.fw_version_digitized >= Utils.digitize_v("2.1.0")
        ):
            start_line = int(start_line) - 1
            start_line_comment = ";using number-1 as goto is bugged and off by one in this fw version"

        commands = [
            "buffer M600",
            play_command,
            f"goto {start_line} {start_line_comment}",
        ]
        # Insert additional commands after "goto"
        commands.extend(additional_commands)
        commands.append("resume")

        if preview:
            # Replace \x01 with spaces for better readability in preview
            return [cmd.replace("\x01", " ") for cmd in commands]

        # Some times the machine seems to have a race condition when pausing before executing the next queued command
        # and the next command after M600 is run while the machine isn't fully paused, causing it to fail.
        # To avoid this problem we wait for the machine state to change to pause before executing the commands after "play"
        play_index = None
        for i, cmd in enumerate(commands):
            self.executeCommand(self.escape(cmd))
            if cmd.startswith("play"):
                play_index = i
                break

        if play_index is not None and play_index < len(commands) - 1:
            remaining_commands = commands[play_index + 1 :]
            self._wait_for_pause_and_continue_cmd_list_execution(remaining_commands)

    def _wait_for_pause_and_continue_cmd_list_execution(self, remaining_commands, dt=None):
        """Wait for machine to be paused, then execute remaining commands"""
        if CNC.vars.get("state") == "Pause":
            for cmd in remaining_commands:
                self.executeCommand(self.escape(cmd))
        else:
            # Not paused yet, check again in 0.1 seconds
            Clock.schedule_once(partial(self._wait_for_pause_and_continue_cmd_list_execution, remaining_commands), 0.1)

    def abortCommand(self):
        # Aborting cancels the intent of anything still queued; drop it and
        # jump the queue.
        self._cmd_flow.clear()
        self.executeCommand("abort\n", immediate=True)

    def feedholdCommand(self):
        self.executeRealtime(ord("!"))

    def toggleFeedholdCommand(self, holding):
        if holding:
            self.executeRealtime(ord("~"))
        else:
            self.executeRealtime(ord("!"))

    def cyclestartCommand(self):
        self.executeRealtime(ord("~"))

    def estopCommand(self):
        self.executeRealtime(0x18)

    # ----------------------------------------------------------------------
    def hardResetPre(self):
        self.executeCommand("reset\n", immediate=True)

    def hardResetAfter(self):
        time.sleep(6)

    def parseBracketAngle(
        self,
        line,
    ):
        # R: Rotation Angle; G: active Coord System;
        # <Idle|MPos:68.9980,-49.9240,40.0000,12.3456|WPos:68.9980,-49.9240,40.0000,5.3|R:0.0|G:0|F:12345.12,100.0|S:1.2,100.0|T:1|L:0>
        # F: Feed, overide | S: Spindle RPM
        # Comms delivers newline-trimmed text; keep delimiter extraction so a
        # trailing junk byte after '>' cannot poison the last field.
        start = line.find("<")
        end = line.rfind(">")
        if start < 0 or end <= start:
            raise ValueError(f"Malformed status report: {line!r}")
        ln = line[start + 1 : end]

        # split fields
        l = ln.split("|")

        # strip off status
        CNC.vars["state"] = l[0]

        # strip of rest into a dict of name: [values,...,]
        d = {a: [float(y) for y in b.split(",")] for a, b in [x.split(":") for x in l[1:]]}
        if "R" in d:
            CNC.vars["rotation_angle"] = float(d["R"][0])
            CNC.can_rotate_wcs = True
        else:
            CNC.vars["rotation_angle"] = 0.0
        if "G" in d:
            CNC.vars["active_coord_system"] = int(d["G"][0])
        if "C" in d:
            CNC.vars["MachineModel"] = int(d["C"][0])
            CNC.vars["FuncSetting"] = int(d["C"][1])
            CNC.vars["inch_mode"] = int(d["C"][2])
            CNC.vars["absolute_mode"] = int(d["C"][3])
        if CNC.vars["inch_mode"] != 999:
            if CNC.vars["inch_mode"] == 1:
                CNC.UnitScale = 25.4
            else:
                CNC.UnitScale = 1
        else:
            CNC.UnitScale = 1
        CNC.vars["mx"] = float(d["MPos"][0])
        CNC.vars["my"] = float(d["MPos"][1])
        CNC.vars["mz"] = float(d["MPos"][2])
        if len(d["MPos"]) > 3:
            CNC.vars["ma"] = float(d["MPos"][3])
        else:
            CNC.vars["ma"] = 0.0
        CNC.vars["wx"] = float(d["WPos"][0])
        CNC.vars["wy"] = float(d["WPos"][1])
        CNC.vars["wz"] = float(d["WPos"][2])
        if len(d["WPos"]) > 3:
            CNC.vars["wa"] = float(d["WPos"][3])
        else:
            CNC.vars["wa"] = 0.0
        CNC.vars["wcox"] = round(
            CNC.vars["mx"]
            - (
                math.cos(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wx"]
                - math.sin(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wy"]
            ),
            3,
        )
        CNC.vars["wcoy"] = round(
            CNC.vars["my"]
            - (
                math.sin(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wx"]
                + math.cos(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wy"]
            ),
            3,
        )
        CNC.vars["wcoz"] = round(CNC.vars["mz"] - CNC.vars["wz"], 3)
        CNC.vars["wcoa"] = round(CNC.vars["ma"] - CNC.vars["wa"], 3)
        if "F" in d:
            CNC.vars["curfeed"] = float(d["F"][0])
            CNC.vars["tarfeed"] = float(d["F"][1])
            CNC.vars["OvFeed"] = int(d["F"][2])
            if len(d["F"]) > 3:  # Analog type spindle reports temp via F status for some reason in FW <= 2.1.0
                CNC.vars["spindletemp"] = float(d["F"][3])
        if "S" in d:
            CNC.vars["curspindle"] = float(d["S"][0])
            CNC.vars["tarspindle"] = float(d["S"][1])
            CNC.vars["OvSpindle"] = float(d["S"][2])
            s_fields = d["S"]
            if len(s_fields) > 3:
                CNC.vars["vacuummode"] = int(s_fields[3])
            if len(s_fields) >= 9 or len(s_fields) == 5:
                CNC.vars["spindletemp"] = float(s_fields[4])
            if len(s_fields) >= 8:
                CNC.vars["extoutmode"] = int(s_fields[-1])
        if "T" in d:
            CNC.vars["tool"] = int(d["T"][0])
            CNC.vars["tlo"] = float(d["T"][1])
            if len(d["T"]) > 2:
                CNC.vars["target_tool"] = int(d["T"][2])
            else:
                CNC.vars["target_tool"] = -1
            if len(d["T"]) > 3:
                CNC.vars["target_collet_type"] = int(d["T"][3])
            else:
                CNC.vars["target_collet_type"] = 0
        else:
            CNC.vars["tool"] = -1
            CNC.vars["tlo"] = 0.0
            CNC.vars["target_tool"] = -1
            CNC.vars["target_collet_type"] = 0
        if "W" in d:
            CNC.vars["wpvoltage"] = float(d["W"][0])
        if "L" in d:
            CNC.vars["lasermode"] = int(d["L"][0])
            CNC.vars["laserstate"] = int(d["L"][1])
            CNC.vars["lasertesting"] = int(d["L"][2])
            CNC.vars["laserpower"] = float(d["L"][3])
            CNC.vars["laserscale"] = float(d["L"][4])
        if "P" in d:
            CNC.vars["playedlines"] = int(d["P"][0])
            CNC.vars["playedpercent"] = int(d["P"][1])
            CNC.vars["playedseconds"] = int(d["P"][2])
            if len(d["P"]) >= 4:
                CNC.vars["is_playing"] = int(d["P"][3])
        else:
            # not playing file
            CNC.vars["playedlines"] = -1
            CNC.vars["is_playing"] = 0

        if "A" in d:
            CNC.vars["atc_state"] = int(d["A"][0])
        else:
            CNC.vars["atc_state"] = 0

        if "O" in d:
            CNC.vars["max_delta"] = float(d["O"][0])
        else:
            CNC.vars["max_delta"] = 0.0

        if "H" in d:
            CNC.vars["halt_reason"] = int(d["H"][0])

        self.posUpdate = True

    def parseBigParentheses(self, line):
        # {S:0,5000|L:0,0|F:1,0|V:0,1|G:0|T:0|E:0,0,0,0,0,0|P:0,0|A:1,0|RSSI:-57}
        # Comms delivers newline-trimmed text; keep delimiter extraction so a
        # trailing junk byte after '}' cannot poison the last field.
        start = line.find("{")
        end = line.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Malformed diagnose report: {line!r}")
        ln = line[start + 1 : end]

        # split fields
        l = ln.split("|")

        # strip of rest into a dict of name: [values,...,]
        d = {}
        for x in l:
            if ":" in x:
                try:
                    a, b = x.split(":", 1)  # Split on first colon only
                    d[a] = [int(y) for y in b.split(",")]
                except (ValueError, IndexError) as e:
                    logger.warning(f"parseBigParentheses: Failed to parse line '{x}': {e}")
                    continue
        if "S" in d:
            CNC.vars["sw_spindle"] = int(d["S"][0])
            CNC.vars["sl_spindle"] = int(d["S"][1])
        if "L" in d:
            CNC.vars["sw_laser"] = int(d["L"][0])
            CNC.vars["sl_laser"] = int(d["L"][1])
        if "F" in d:
            CNC.vars["sw_spindlefan"] = int(d["F"][0])
            CNC.vars["sl_spindlefan"] = int(d["F"][1])
        if "V" in d:
            CNC.vars["sw_vacuum"] = int(d["V"][0])
            CNC.vars["sl_vacuum"] = int(d["V"][1])
        if "G" in d:
            CNC.vars["sw_light"] = int(d["G"][0])
        if "T" in d:
            CNC.vars["sw_tool_sensor_pwr"] = int(d["T"][0])
        if "R" in d:
            CNC.vars["sw_air"] = int(d["R"][0])
        if "C" in d:
            CNC.vars["sw_wp_charge_pwr"] = int(d["C"][0])

        if "E" in d:
            CNC.vars["st_x_min"] = int(d["E"][0])
            CNC.vars["st_x_max"] = int(d["E"][1])
            CNC.vars["st_y_min"] = int(d["E"][2])
            CNC.vars["st_y_max"] = int(d["E"][3])
            CNC.vars["st_z_max"] = int(d["E"][4])
            CNC.vars["st_cover"] = int(d["E"][5])
        if "P" in d:
            CNC.vars["st_probe"] = int(d["P"][0])
            CNC.vars["st_calibrate"] = int(d["P"][1])
        if "A" in d:
            CNC.vars["st_atc_home"] = int(d["A"][0])
            CNC.vars["st_tool_sensor"] = int(d["A"][1])
        if "I" in d:
            CNC.vars["st_e_stop"] = int(d["I"][0])
        if "RSSI" in d:
            CNC.vars["RSSI"] = int(d["RSSI"][0])

        self.diagnoseUpdate = True

    # ----------------------------------------------------------------------
    def help(self, event=None):
        webbrowser.open(WIKI, new=2)

    # ----------------------------------------------------------------------
    # Open serial port or wifi connect
    # ----------------------------------------------------------------------
    def _close_existing_connection(self):
        """Stop streamIO and close any active transport before opening a new one."""
        if self.stream is None and self.thread is None:
            return
        self.stopRun()
        thread = self.thread
        self.thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.comms.reset()
        self.clearRun()

    def open(self, conn_type, address):
        # init connection
        method = "USB serial" if conn_type == CONN_USB else "WiFi"
        # Single user-visible connect log (monitorSerial emits one MDI Received line).
        self.log.put((self.MSG_NORMAL, f"Connecting via {method}: {address}"))

        self.connection_type = conn_type
        # Persist the last connection target so callers can detect "same machine"
        # reconnects (e.g. for resume-at-line selection / loaded lines behavior).
        self.connection_address = address
        self._connecting = True
        self._heartbeat_grace_until = 0.0
        # Keep self.stream unset until open + protocol detect finish so heartbeat
        # cannot treat a half-open link as a live connection and tear it down.
        if conn_type == CONN_USB:
            transport = self.usb_stream
            self._baud_upgrade_attempted = False
        else:
            transport = self.wifi_stream

        try:
            # Switching WiFi ↔ USB (or reconnecting) must tear down the old link first.
            self._close_existing_connection()

            if not transport.open(address):
                self.log.put((self.MSG_ERROR, "Connection Failed!"))
                return False

            if conn_type == CONN_USB:
                # USB open toggles DTR and resets the machine; wait for firmware boot
                # before protocol probe / status polling.
                time.sleep(2.0)

            CNC.vars["state"] = CONNECTED
            CNC.vars["color"] = STATECOLOR[CNC.vars["state"]]
            self.log.put((self.MSG_NORMAL, "Connected to machine!"))
            self._gcount = 0
            self._alarm = True
            CNC.vars["alarm_message"] = ""
            # Reset manual disconnect flag when connection is established
            self._manual_disconnect = False
            try:
                self.clearRun()
            except Exception:
                self.log.put((self.MSG_ERROR, "Controller clear thread error!"))
            self.comms.detect_and_select(transport)
            self._cmd_flow.clear()
            self.stream = transport
            self.thread = threading.Thread(target=self.streamIO)
            self.thread.start()
            self._refresh_heartbeat = True
            # USB needs a longer post-reset grace; WiFi is usually ready immediately.
            self._heartbeat_grace_until = time.time() + (20.0 if conn_type == CONN_USB else 5.0)
            return True
        finally:
            self._connecting = False

    # ----------------------------------------------------------------------
    # Close connection port
    # ----------------------------------------------------------------------
    def close(self):
        if self.stream is None:
            return
        try:
            self.stopRun()
        except Exception:
            self.log.put((self.MSG_ERROR, "Controller stop thread error!"))
        self._runLines = 0
        time.sleep(0.5)
        self.thread = None
        self._cmd_flow.clear()
        try:
            self.stream.close()
        except Exception:
            self.log.put((self.MSG_ERROR, "Controller close stream error!"))
        self.stream = None
        self.comms.reset()
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[CNC.vars["state"]]

        # Start reconnection if enabled (WiFi or USB; callback resolves the method).
        if self.reconnect_enabled and self.reconnect_callback:
            self.start_reconnection()

    def close_manual(self):
        """Close connection manually (user initiated) - don't auto-reconnect"""
        if self.stream is None:
            return
        method = "USB serial" if self.connection_type == CONN_USB else "WiFi"
        address = self.connection_address or "unknown"
        self.log.put((self.MSG_NORMAL, f"Disconnected via {method}: {address}"))
        try:
            self.stopRun()
        except Exception:
            self.log.put((self.MSG_ERROR, "Controller stop thread error!"))
        self._runLines = 0
        time.sleep(0.5)
        self.thread = None
        self._cmd_flow.clear()
        try:
            self.stream.close()
        except Exception:
            self.log.put((self.MSG_ERROR, "Controller close stream error!"))
        self.stream = None
        self.comms.reset()
        # Set a flag to indicate this was a manual disconnection
        self._manual_disconnect = True
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[CNC.vars["state"]]

    def set_reconnection_config(self, enabled, wait_time, attempts):
        """Set reconnection configuration"""
        self.reconnect_enabled = enabled
        self.reconnect_wait_time = wait_time
        self.reconnect_attempts = attempts

    def set_reconnection_callbacks(self, reconnect_callback, cancel_callback, success_callback=None):
        """Set reconnection callbacks"""
        self.reconnect_callback = reconnect_callback
        self.cancel_reconnect_callback = cancel_callback
        self.reconnect_success_callback = success_callback

    def start_reconnection(self):
        """Start the reconnection process"""
        if not self.reconnect_enabled or not self.reconnect_callback:
            return

        self.reconnect_countdown = self.reconnect_wait_time
        self.reconnect_attempts_remaining = self.reconnect_attempts

        # Schedule the first reconnection attempt
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        self.reconnect_timer = threading.Timer(self.reconnect_wait_time, self.attempt_reconnect)
        self.reconnect_timer.start()

    def attempt_reconnect(self):
        """Attempt to reconnect"""
        self.reconnect_attempts_remaining -= 1

        # Try to reconnect using the callback
        if self.reconnect_callback:
            self.reconnect_callback()

        # Schedule next attempt if there are more attempts remaining
        if self.reconnect_attempts_remaining > 0:
            if self.reconnect_timer:
                self.reconnect_timer.cancel()
            self.reconnect_timer = threading.Timer(self.reconnect_wait_time, self.attempt_reconnect)
            self.reconnect_timer.start()
        else:
            # All attempts exhausted, call the cancel callback
            if self.cancel_reconnect_callback:
                self.cancel_reconnect_callback()

    def cancel_reconnection(self):
        """Cancel the reconnection process"""
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            self.reconnect_timer = None
        # Reset reconnection state
        self.reconnect_countdown = 0
        self.reconnect_attempts_remaining = 0
        if self.cancel_reconnect_callback:
            self.cancel_reconnect_callback()

    def notify_reconnection_success(self):
        """Notify that reconnection was successful"""
        if self.reconnect_success_callback:
            self.reconnect_success_callback()

    # ----------------------------------------------------------------------
    def stopRun(self):
        self.stop.set()

    # ----------------------------------------------------------------------
    def clearRun(self):
        self.stop.clear()

    # ----------------------------------------------------------------------
    # Send to controller a gcode or command
    # WARNING: it has to be a single line!
    # ----------------------------------------------------------------------
    def sendGCode(self, cmd):
        self.executeCommand(cmd)

    # ----------------------------------------------------------------------
    def sendHex(self, hexcode):
        if self.stream is None:
            return
        self.executeRealtime(int(hexcode, 16))

    def viewStatusReport(self, sio_status):
        if self.loadNUM == 0 and self.sendNUM == 0:
            if self.stream is None or not self.protocol_ready:
                return
            if self.continuous_jog_active and not self._continuous_jog_stopping:
                # Smoothie uses "?1"; Makera uses "?" + Ctrl+Z keepalive.
                # Always one write so keepalive can't be interleaved/orphaned.
                if self.comms.uses_framed_transfer:
                    self.executeRealtimeSequence(ord("?"), 0x1A)
                else:
                    self.executeRealtimeSequence(ord("?"), ord("1"))
            else:
                self.executeRealtime(ord("?"))
            self.sio_status = sio_status

    def viewDiagnoseReport(self, sio_diagnose):
        if self.loadNUM == 0 and self.sendNUM == 0:
            if self.stream is None or not self.protocol_ready:
                return
            self.executeCommand("diagnose\n")
            self.sio_diagnose = sio_diagnose

    # ----------------------------------------------------------------------
    def hardReset(self):
        self.busy()
        if self.stream is not None:
            self.hardResetPre()
            self.openClose()
            self.hardResetAfter()
        self.openClose()
        self.stopProbe()
        self._alarm = False
        CNC.vars["alarm_message"] = ""
        CNC.vars["_OvChanged"] = True  # force a feed change if any
        self.notBusy()

    def softReset(self, clearAlarm=True):
        self.executeRealtime(0x18)
        self.stopProbe()
        if clearAlarm:
            self._alarm = False
            CNC.vars["alarm_message"] = ""
        CNC.vars["_OvChanged"] = True  # force a feed change if any

    def unlock(self, clearAlarm=True):
        if clearAlarm:
            self._alarm = False
            CNC.vars["alarm_message"] = ""
        self.sendGCode("$X")

    def home(self, event=None):
        self.sendGCode("$H")

    def viewSettings(self):
        pass

    def viewParameters(self):
        self.sendGCode("$#")

    def viewWCS(self):
        self.sendGCode("get wcs")

    def viewState(self):
        self.sendGCode("$G")

    def viewBuild(self):
        self.executeCommand("version\n")
        self.sendGCode("$I")

    def viewStartup(self):
        pass

    def checkGcode(self):
        pass

    def grblHelp(self):
        self.executeCommand("help\n")

    def grblRestoreSettings(self):
        pass

    def grblRestoreWCS(self):
        pass

    def grblRestoreAll(self):
        pass

    # ----------------------------------------------------------------------
    def setJogMode(self, mode):
        """Set the jog mode (step or continuous)"""
        if not self.is_community_firmware:
            return

        if mode in [Controller.JOG_MODE_STEP, Controller.JOG_MODE_CONTINUOUS]:
            if self.continuous_jog_active:
                self.stopContinuousJog()
            self.jog_mode = mode

    def startContinuousJog(self, _dir, speed=None, scale_feed_override=None):
        """Start continuous jogging in the specified direction"""
        if (
            self.jog_mode != Controller.JOG_MODE_CONTINUOUS
            or self.continuous_jog_active
            or self._continuous_jog_stopping
        ):
            return
        self.continuous_jog_active = True
        self._continuous_jog_stopping = False
        if speed is None:
            if self.jog_speed > 0 and self.jog_speed < 10000:
                self.executeCommand(f"$J -c {_dir} F{self.jog_speed}")
            else:
                if scale_feed_override is not None:
                    self.executeCommand(f"$J -c {_dir} {scale_feed_override}")
                else:
                    self.executeCommand(f"$J -c {_dir}")
        else:
            self.executeCommand(f"$J -c {_dir} F{speed}")

    def stopContinuousJog(self):
        """Stop continuous jogging"""

        if self.jog_mode != Controller.JOG_MODE_CONTINUOUS:
            return

        # Send Ctrl+Y, then wait for firmware ^Y before allowing a new $J -c.
        # Mark stopping immediately so status polls stop sending keepalives that
        # would otherwise fight the stop request.
        if self.stream is not None and self.continuous_jog_active and not self._continuous_jog_stopping:
            self._continuous_jog_stopping = True
            self.executeRealtime(0x19)

    def _clear_continuous_jog_state(self):
        self.continuous_jog_active = False
        self._continuous_jog_stopping = False

    def jog(self, _dir, speed=None):
        if self.jog_mode == Controller.JOG_MODE_STEP:
            if speed is None:
                if self.jog_speed == 0:
                    self.executeCommand(f"$J {_dir}")
                else:
                    self.executeCommand(f"$J {_dir} F{self.jog_speed}")
            else:
                self.executeCommand(f"$J {_dir} F{speed}")
        elif self.jog_mode == Controller.JOG_MODE_CONTINUOUS:
            self.startContinuousJog(_dir)

    # ----------------------------------------------------------------------

    def goto(self, x=None, y=None, z=None):
        cmd = "G90G0"
        if x is not None:
            cmd += "X%g" % (x)
        if y is not None:
            cmd += "Y%g" % (y)
        if z is not None:
            cmd += "Z%g" % (z)
        self.sendGCode("%s" % (cmd))

    def gotoSafeZ(self):
        # using 2mm below the homing point as CA1 x-sag compensation could be a whole mm
        self.sendGCode("G53 G0 Z-2")

    def gotoMachineHome(self):
        self.gotoSafeZ()
        # CA1 x-sag compensation could be a whole mm in Y, so use 2mm to be safe. Same for X for consistency
        self.sendGCode("G53 G0 X-2 Y-2")

    def gotoWCSHome(self):
        self.gotoSafeZ()
        self.sendGCode("G53 G0 X%g Y%g" % (CNC.vars["wcox"], CNC.vars["wcoy"]))

    def wcs_set_a(self, a=None):
        cmd = "G10L20P0"
        if a is not None and abs(a) < 3600000.0:
            cmd += "A" + str(round(a, 5))

        self.sendGCode(cmd)

    def shrinkA(self):
        self.sendGCode("G92.4 A0 S0")

    def rapid_move_a(self, a=None):
        cmd = "G90G0"
        cmd += "X" + str(round(a, 5))
        cmd = "G92.4"
        cmd += " A " + str(round(a, 5)) + " R0"
        if a is not None and abs(a) < 3600000.0:
            self.sendGCode(cmd)

    def wcs_set(self, x=None, y=None, z=None, a=None):
        cmd = "G10L20P0"

        pos = ""
        if x is not None and abs(x) < 10000.0:
            pos += "X" + str(round(x, 4))
        if y is not None and abs(y) < 10000.0:
            pos += "Y" + str(round(y, 4))
        if z is not None and abs(z) < 10000.0:
            pos += "Z" + str(round(z, 4))
        if a is not None and abs(a) < 3600000.0:
            pos += "A" + str(round(a, 4))
        cmd += pos

        self.sendGCode(cmd)

    def wcsSetM(self, x=None, y=None, z=None, a=None):
        # p = WCS.index(CNC.vars["WCS"])
        cmd = "G10L2P0"

        pos = ""
        if x is not None and abs(x) < 10000.0:
            pos += "X" + str(round(x, 4))
        if y is not None and abs(y) < 10000.0:
            pos += "Y" + str(round(y, 4))
        if z is not None and abs(z) < 10000.0:
            pos += "Z" + str(round(z, 4))
        if a is not None and abs(a) < 3600000.0:
            pos += "A" + str(round(a, 4))
        cmd += pos

        self.sendGCode(cmd)

    def wcsClearRotation(self):
        cmd = "G10L2R0P0"
        self.sendGCode(cmd)

    def setRotation(self, rotation):
        """Set the rotation angle for the current coordinate system"""
        cmd = f"G10L2R{rotation:.3f}P0"
        self.sendGCode(cmd)

    def feedHold(self, event=None):
        if event is not None and not self.acceptKey(True):
            return
        if self.stream is None:
            return
        self.executeRealtime(ord("!"))
        self._pause = True

    def resume(self, event=None):
        if event is not None and not self.acceptKey(True):
            return
        if self.stream is None:
            return
        self.executeRealtime(ord("~"))
        self._alarm = False
        CNC.vars["alarm_message"] = ""
        self._pause = False

    def pause(self, event=None):
        if self.stream is None:
            return
        if self._pause:
            self.resume()
        else:
            self.feedHold()

    # ----------------------------------------------------------------------
    def _drain_stream_messages(self, timeout_s=0.3):
        """Read and parse pending RX bytes for up to timeout_s; return messages."""
        messages = []
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not self.stream or not self.stream.waiting_for_recv():
                time.sleep(0.01)
                continue
            data = self.stream.recv()
            if data:
                messages.extend(self.comms.feed(data, allow_wire_switch=False))
        return messages

    def _flush_rx(self):
        """Discard any unread host RX bytes and reset the protocol parser."""
        serial_port = getattr(self.stream, "serial", None) if self.stream else None
        if serial_port is not None:
            try:
                serial_port.reset_input_buffer()
            except Exception:
                pass
            try:
                while serial_port.in_waiting:
                    serial_port.read(serial_port.in_waiting)
            except Exception:
                pass
        self.comms.reset_parser()

    @staticmethod
    def _looks_like_status(text):
        t = (text or "").lstrip()
        return t.startswith("<") and ("|" in t or "MPos" in t or "Idle" in t or "Run" in t)

    def _await_status_response(self, timeout_s=1.0):
        """Send a status query and wait for a status frame/line."""
        self.executeRealtime(ord("?"))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for message in self._drain_stream_messages(timeout_s=0.05):
                if self._looks_like_status(message.text):
                    return True
        return False

    def request_baud_upgrade(self, baud):
        """Send firmware baud command, then switch the host UART to match."""
        if self.connection_type != CONN_USB or self.stream != self.usb_stream:
            return
        if not hasattr(self.usb_stream, "reopen_at_baud"):
            return
        if self.sendNUM != 0 or self.loadNUM != 0:
            self.log.put((self.MSG_ERROR, "Failed to change serial speed: transfer in progress"))
            return
        baud = int(baud)
        self._baud_switch_in_progress = True
        self._refresh_heartbeat = True
        # Stop streamIO and wait until it is parked so it cannot steal the "ok".
        self.pauseStream(0.0)
        try:
            # streamIO is parked at this point, so the queue would never drain.
            self.executeCommand(f"baud {baud}\n", immediate=True)
            # Firmware prints framed/text "ok" at the old baud, then switches.
            # Give TX time to finish, then reopen the host port at the new rate.
            time.sleep(0.15)
            self._flush_rx()
            if not self.usb_stream.reopen_at_baud(baud):
                raise RuntimeError("Failed to set host serial baud rate")
            # Ensure Controller still points at the reopened USB stream.
            self.stream = self.usb_stream
            self.comms.reset_parser()
            if not self._await_status_response(timeout_s=1.5):
                # Recover: try bringing both sides back to 115200.
                self._recover_baud_after_failed_upgrade(baud)
                raise RuntimeError(f"no status response after switching to {baud} baud")
            self.log.put((self.MSG_NORMAL, f"Serial speed set to {baud} baud"))
            self._refresh_heartbeat = True
        except Exception as e:
            self.log.put((self.MSG_ERROR, f"Failed to change serial speed: {e}"))
            self._refresh_heartbeat = True
        finally:
            self._baud_switch_in_progress = False
            self.resumeStream()

    def _recover_baud_after_failed_upgrade(self, attempted_baud):
        """Best-effort restore of 115200 after a failed high-baud switch."""
        try:
            # Machine may already be at attempted_baud — ask it to drop back.
            self.executeCommand("baud 115200\n", immediate=True)
            time.sleep(0.15)
        except Exception:
            pass
        try:
            self._flush_rx()
            if self.usb_stream.reopen_at_baud(115200):
                self.stream = self.usb_stream
            self.comms.reset_parser()
        except Exception:
            logger.exception("Failed to revert host baud to 115200 after upgrade to %s", attempted_baud)

    # ----------------------------------------------------------------------
    def parseLine(self, line):
        if not line:
            return True
        try:
            if line[0] == "<":
                self.parseBracketAngle(line)
                self.sio_status = False
            elif line[0] == "{":
                if not self.sio_diagnose:
                    self.log.put((self.MSG_NORMAL, line))
                else:
                    self.parseBigParentheses(line)
                    self.sio_diagnose = False
            elif line[0] == "[" in line:
                # Log raw WCS parameters before parsing
                self.log.put((self.MSG_NORMAL, line))
                # Parse WCS parameters: [G54:-123.6800,-123.6800,-123.6800,-50,0.000,25.123]
                self.parseWCSParameters(line)
            elif line[0] == "#":
                self.log.put((self.MSG_INTERIOR, line))
            elif line[0] == "^":
                if line[1] == "Y":
                    self._clear_continuous_jog_state()
            elif "error" in line.lower() or "alarm" in line.lower():
                self.log.put((self.MSG_ERROR, line))
                if line.upper().startswith("ERROR:"):
                    msg = line[len("ERROR:") :].strip()
                    if msg:
                        CNC.vars["alarm_message"] = msg
            else:
                # Firmware continuous-jog timeout: clear local state so jogging can restart.
                if "Stop request timeout" in line or "Internal stop request reset" in line:
                    self._clear_continuous_jog_state()
                self.log.put((self.MSG_NORMAL, line))
        except (LookupError, ArithmeticError, ValueError) as e:
            self.log.put((self.MSG_ERROR, f"Failed to parse machine response: {line}"))
            logger.error(f"Parser error in parseLine: {e}, line: {line}")

    # ----------------------------------------------------------------------
    def g28Command(self):
        self.sendGCode("G28.1")  # FIXME: ???

    def g30Command(self):
        self.sendGCode("G30.1")  # FIXME: ???

    # ----------------------------------------------------------------------
    def emptyQueue(self):
        while self.queue.qsize() > 0:
            try:
                self.queue.get_nowait()
            except Empty:
                break

    def pauseStream(self, wait_s=0.0):
        """Stop the streamIO RX loop so file transfer owns the byte stream."""
        self.pausing = True
        # Pause RX immediately — do not wait before setting paused, or framed
        # file-transfer packets (MD5/etc.) can be consumed by streamIO.
        self.paused = True
        # Wait until streamIO acknowledges the pause before the caller touches RX.
        deadline = time.time() + 1.0
        while not self._stream_io_parked and time.time() < deadline:
            time.sleep(0.01)
        if wait_s > 0:
            time.sleep(wait_s)
        self.pausing = False

    def resumeStream(self):
        self.paused = False
        self.pausing = False
        self._stream_io_parked = False

    def _handle_protocol_message(self, message):
        """Dispatch a ParsedMessage from the active communication protocol."""
        if message.kind == MessageKind.LOAD_EOF:
            self.loadEOF = True
            return
        if message.kind == MessageKind.LOAD_ERROR:
            self.loadERR = True
            return

        text = message.text or ""
        if message.kind == MessageKind.LOAD_CHUNK:
            cleaned = re.sub(r"<.*?>", "", text).strip()
            if not cleaned:
                return
            for line2 in cleaned.replace("\r\n", "\n").split("\n"):
                if line2:
                    self.load_buffer.put(line2)
                    self.load_buffer_size += len(line2) + 1
            return

        # LINE
        if self.loadNUM == 0 or "|MPos" in text:
            self.parseLine(text)
            return
        cleaned_line = re.sub(r"<.*?>", "", text).strip()
        if cleaned_line:
            for line2 in cleaned_line.replace("\r\n", "\n").split("\n"):
                if line2:
                    self.load_buffer.put(line2)
                    self.load_buffer_size += len(line2) + 1

    # ----------------------------------------------------------------------
    # thread performing I/O on serial line
    # ----------------------------------------------------------------------
    def streamIO(self):
        self.sio_status = False
        self.sio_diagnose = False
        dynamic_delay = 0.1
        tr = td = time.time()
        last_error = ""

        while not self.stop.is_set():
            if not self.stream or self.paused:
                self._stream_io_parked = True
                # Short sleep so baud-switch / file-transfer pause ends promptly.
                time.sleep(0.05)
                continue
            self._stream_io_parked = False
            t = time.time()
            # refresh machine position?
            running = self.sendNUM > 0 or self.loadNUM > 0 or self.pausing
            try:
                if not running and self.protocol_ready:
                    if t - tr > STREAM_POLL:
                        self.viewStatusReport(True)
                        tr = t
                    if self.diagnosing and t - td > DIAGNOSE_POLL:
                        self.viewDiagnoseReport(True)
                        td = t
                    # Release at most one queued command per iteration; the next
                    # is held until the machine is heard from again (or the ack
                    # timeout passes), so bursts cannot wedge the firmware's
                    # receive path.
                    queued_command = self._cmd_flow.pop_ready(t)
                    if queued_command is not None:
                        self._send_command_now(queued_command, echo=False)
                        dynamic_delay = 0
                else:
                    tr = t
                    td = t

                if self.stream.waiting_for_recv():
                    data = self.stream.recv()
                    if data:
                        allow_wire_switch = self.sendNUM == 0 and self.loadNUM == 0
                        messages = list(self.comms.feed(data, allow_wire_switch=allow_wire_switch))
                        if messages:
                            self._cmd_flow.note_receive()
                        for message in messages:
                            self._handle_protocol_message(message)
                    dynamic_delay = 0
                else:
                    if self.sendNUM == 0 and self.loadNUM == 0:
                        dynamic_delay = 0.1 if dynamic_delay >= 0.09 else dynamic_delay + 0.01
                    else:
                        dynamic_delay = 0

            except Exception:
                self.comms.reset_parser()
                exc_msg = str(sys.exc_info()[1])
                if self._baud_switch_in_progress:
                    last_error = exc_msg
                    continue
                if last_error != exc_msg:
                    self.log.put((Controller.MSG_ERROR, exc_msg))
                    last_error = exc_msg

            if dynamic_delay > 0:
                time.sleep(dynamic_delay)

    def parseWCSParameters(self, line):
        """Parse WCS parameters from machine response"""
        # Parse format: [G54:-123.6800,-123.6800,-123.6800,-50,0.000,25.123]
        # Extract all WCS entries from the line

        # parse the current WCS from the "get wcs" command
        get_wcs_pattern = r"\[current WCS: (G5[4-9][.1-3]*)\]"
        current_wcs_matches = re.findall(get_wcs_pattern, line)

        if current_wcs_matches:
            # if not on community firmware or rotation angle is not set,
            # the active coordinate system is tracked through the "get wcs" command
            if not self.is_community_firmware or not CNC.can_rotate_wcs:
                CNC.vars["active_coord_system"] = CNC.wcs_names.index(current_wcs_matches[0])
            return

        wcs_pattern = r"\[(G5[4-9][.1-3]*):([^]]+)\]"
        matches = re.findall(wcs_pattern, line)
        wcs_data = {}
        for wcs_code, values_str in matches:
            # Split the values by comma
            values = values_str.split(",")
            if len(values) >= 5:  # X, Y, Z, A, B, Rotation
                try:
                    x = float(values[0])
                    y = float(values[1])
                    z = float(values[2])
                    a = float(values[3])
                    b = float(values[4])  # B is always 0
                    if self.is_community_firmware and CNC.can_rotate_wcs:
                        rotation = float(values[5])
                    else:
                        rotation = 0.0
                    wcs_data[wcs_code] = [x, y, z, a, b, rotation]  # Store only X, Y, Z, A, B, Rotation

                except (ValueError, IndexError):
                    logger.error(f"Error parsing WCS values for {wcs_code}: {values_str}")

        # Send the parsed data to the WCS Settings popup if it's open
        if hasattr(self, "wcs_popup_callback") and self.wcs_popup_callback:
            self.wcs_popup_callback(wcs_data)
