#!/usr/bin/python

from __future__ import absolute_import
from __future__ import print_function

import re
import sys
import time
import threading
import webbrowser
import math
import logging
logger = logging.getLogger(__name__)

from datetime import datetime

try:
    from Queue import *
except ImportError:
    from queue import *

from .CNC import CNC
from .USBStream import USBStream
from .WIFIStream import WIFIStream
from kivy.app import App
from kivy.utils import platform as kivy_platform

STREAM_POLL = 0.2 # s
DIAGNOSE_POLL = 0.5  # s
RX_BUFFER_SIZE = 128

GPAT = re.compile(r"[A-Za-z]\s*[-+]?\d+.*")
FEEDPAT = re.compile(r"^(.*)[fF](\d+\.?\d+)(.*)$")

STATUSPAT = re.compile(r"^<(\w*?),MPos:([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),WPos:([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),?(.*)>$")
POSPAT	  = re.compile(r"^\[(...):([+\-]?\d*\.\d*),([+\-]?\d*\.\d*),([+\-]?\d*\.\d*):?(\d*)\]$")
TLOPAT	  = re.compile(r"^\[(...):([+\-]?\d*\.\d*)\]$")
DOLLARPAT = re.compile(r"^\[G\d* .*\]$")
SPLITPAT  = re.compile(r"[:,]")
VARPAT    = re.compile(r"^\$(\d+)=(\d*\.?\d*) *\(?.*")


WIKI = "https://github.com/vlachoudis/bCNC/wiki"

CONNECTED = "Wait"
NOT_CONNECTED = "N/A"

STATECOLORDEF = (155/255, 155/255, 155/255, 1)  # Default color for unknown types or not connected
STATECOLOR = {
    "Idle":         (52/255, 152/255, 219/255, 1),
    "Run":          (34/255, 153/255, 84/255, 1),
    "Tool":        (34/255, 153/255, 84/255, 1),
    "Alarm":        (231/255, 76/255, 60/255, 1),
    "Home":         (247/255, 220/255, 111/255, 1),
    "Hold":         (34/255, 153/255, 84/255, 1),
    'Wait':         (247/255, 220/255, 111/255, 1),
    'Disable':      (100/255, 100/255, 100/255, 1),
    'Sleep':        (220/255, 220/255, 220/255, 1),
    'Pause':        (52/255, 152/255, 219/255, 1),
    NOT_CONNECTED:  (155/255, 155/255, 155/255, 1)
}

LOAD_DIR   = 1
LOAD_RM    = 2
LOAD_MV    = 3
LOAD_MKDIR = 4
LOAD_WIFI  = 7
LOAD_CONN_WIFI = 8

SEND_FILE = 1

CONN_USB = 0
CONN_WIFI = 1
FRAME_HEADER = 34408
FRAME_END = 21930
PTYPE_CTRL_SINGLE = 161
PTYPE_CTRL_MULTI = 162
PTYPE_FILE_START = 176
MAX_DATA_LEN = 1024
PTYPE_STATUS_RES = 129
PTYPE_DIAG_RES = 130
PTYPE_LOAD_INFO = 131
PTYPE_LOAD_FINISH = 132
PTYPE_LOAD_ERROR = 133
PTYPE_NORMAL_INFO = 144
from enum import Enum, auto

class RevPacketState(Enum):
    WAIT_HEADER = auto()
    READ_LENGTH = auto()
    READ_DATA = auto()
    CHECK_FOOTER = auto()

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

    def __init__(self, cnc, callback):
        if kivy_platform == 'ios':
            self.usb_stream = None
        else:
            self.usb_stream = USBStream()
        self.wifi_stream = WIFIStream()
        
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
        self._msg = None
        self._sumcline = 0
        self._lastFeed = 0
        self._newFeed = 0

        self._onStart = ""
        self._onStop = ""

        self.paused = False
        self.pausing = False

        self.diagnosing = False
        self.currentState = RevPacketState.WAIT_HEADER
        self.packetData = bytearray()
        self.headerBuffer = bytearray(2)
        self.footerBuffer = bytearray(2)
        self.bytesNeeded = 2
        self.expectedLength = 0

        self.is_community_firmware = False

        # Jog related variables
        self.jog_mode = Controller.JOG_MODE_STEP
        self.jog_speed = 10000  # mm/min. A value of 0 here would suggest to use last used feed
        self.continuous_jog_active = False

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
    #	  False otherwise
    # ----------------------------------------------------------------------
    def executeGcode(self, line):
        if isinstance(line, tuple) or \
                (line and len(line) > 0 and line[0] in ("$", "!", "~", "?", "(", "@")) or GPAT.match(line):
            self.sendGCode(line)
            return True
        return False

    # ----------------------------------------------------------------------
    # Execute a single command
    # ----------------------------------------------------------------------
    def crc16_ccitt(self, data: bytes, length: int) -> int:
        crc_table = [0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7, 0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef, 0x1231, 0x0210, 0x3273, 0x2252, 0x52b5, 0x4294, 0x72f7, 0x62d6, 0x9339, 0x8318, 0xb37b, 0xa35a, 0xd3bd, 0xc39c, 0xf3ff, 0xe3de, 0x2462, 0x3443, 0x0420, 0x1401, 0x64e6, 0x74c7, 0x44a4, 0x5485, 0xa56a, 0xb54b, 0x8528, 0x9509, 0xe5ee, 0xf5cf, 0xc5ac, 0xd58d, 0x3653, 0x2672, 0x1611, 0x0630, 0x76d7, 0x66f6, 0x5695, 0x46b4, 0xb75b, 0xa77a, 0x9719, 0x8738, 0xf7df, 0xe7fe, 0xd79d, 0xc7bc, 0x48c4, 0x58e5, 0x6886, 0x78a7, 0x0840, 0x1861, 0x2802, 0x3823, 0xc9cc, 0xd9ed, 0xe98e, 0xf9af, 0x8948, 0x9969, 0xa90a, 0xb92b, 0x5af5, 0x4ad4, 0x7ab7, 0x6a96, 0x1a71, 0x0a50, 0x3a33, 0x2a12, 0xdbfd, 0xcbdc, 0xfbbf, 0xeb9e, 0x9b79, 0x8b58, 0xbb3b, 0xab1a, 0x6ca6, 0x7c87, 0x4ce4, 0x5cc5, 0x2c22, 0x3c03, 0x0c60, 0x1c41, 0xedae, 0xfd8f, 0xcdec, 0xddcd, 0xad2a, 0xbd0b, 0x8d68, 0x9d49, 0x7e97, 0x6eb6, 0x5ed5, 0x4ef4, 0x3e13, 0x2e32, 0x1e51, 0x0e70, 0xff9f, 0xefbe, 0xdfdd, 0xcffc, 0xbf1b, 0xaf3a, 0x9f59, 0x8f78, 0x9188, 0x81a9, 0xb1ca, 0xa1eb, 0xd10c, 0xc12d, 0xf14e, 0xe16f, 0x1080, 0x00a1, 0x30c2, 0x20e3, 0x5004, 0x4025, 0x7046, 0x6067, 0x83b9, 0x9398, 0xa3fb, 0xb3da, 0xc33d, 0xd31c, 0xe37f, 0xf35e, 0x02b1, 0x1290, 0x22f3, 0x32d2, 0x4235, 0x5214, 0x6277, 0x7256, 0xb5ea, 0xa5cb, 0x95a8, 0x8589, 0xf56e, 0xe54f, 0xd52c, 0xc50d, 0x34e2, 0x24c3, 0x14a0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405, 0xa7db, 0xb7fa, 0x8799, 0x97b8, 0xe75f, 0xf77e, 0xc71d, 0xd73c, 0x26d3, 0x36f2, 0x0691, 0x16b0, 0x6657, 0x7676, 0x4615, 0x5634, 0xd94c, 0xc96d, 0xf90e, 0xe92f, 0x99c8, 0x89e9, 0xb98a, 0xa9ab, 0x5844, 0x4865, 0x7806, 0x6827, 0x18c0, 0x08e1, 0x3882, 0x28a3, 0xcb7d, 0xdb5c, 0xeb3f, 0xfb1e, 0x8bf9, 0x9bd8, 0xabbb, 0xbb9a, 0x4a75, 0x5a54, 0x6a37, 0x7a16, 0x0af1, 0x1ad0, 0x2ab3, 0x3a92, 0xfd2e, 0xed0f, 0xdd6c, 0xcd4d, 0xbdaa, 0xad8b, 0x9de8, 0x8dc9, 0x7c26, 0x6c07, 0x5c64, 0x4c45, 0x3ca2, 0x2c83, 0x1ce0, 0x0cc1, 0xef1f, 0xff3e, 0xcf5d, 0xdf7c, 0xaf9b, 0xbfba, 0x8fd9, 0x9ff8, 0x6e17, 0x7e36, 0x4e55, 0x5e74, 0x2e93, 0x3eb2, 0x0ed1, 0x1ef0]
        crc = 0
        if length == 0:
            for byte in data:
                tmp = (crc >> 8 ^ byte) & 255
                crc = (crc << 8 ^ crc_table[tmp]) & 65535
        else:
            for i in range(length):
                tmp = (crc >> 8 ^ data[i]) & 255
                crc = (crc << 8 ^ crc_table[tmp]) & 65535
        return crc

    def executeSingleCharCommand(self, char: int):
        data_length = 4
        crc_data = data_length.to_bytes(2, 'big') + PTYPE_CTRL_SINGLE.to_bytes(1, 'big') + char.to_bytes(1, 'big')
        crc = self.crc16_ccitt(crc_data, 0)
        packet = FRAME_HEADER.to_bytes(2, byteorder='big') + crc_data + crc.to_bytes(2, byteorder='big') + FRAME_END.to_bytes(2, byteorder='big')
        self.stream.send(packet)

    def executeMultiCharCommand(self, data: bytes) -> bytes:
        assert isinstance(data, bytes), 'data must be bytes type'
        DATA_LENGTH = 1 + len(data) + 2
        crc_payload = DATA_LENGTH.to_bytes(2, 'big') + bytes([PTYPE_CTRL_MULTI]) + data
        crc = self.crc16_ccitt(crc_payload, 0)
        packet = FRAME_HEADER.to_bytes(2, 'big') + DATA_LENGTH.to_bytes(2, 'big') + bytes([PTYPE_CTRL_MULTI]) + data + crc.to_bytes(2, 'big') + FRAME_END.to_bytes(2, 'big')
        self.stream.send(packet)

    def executeFileCommand(self, data: bytes) -> bytes:
        assert isinstance(data, bytes), 'data must be bytes type'
        DATA_LENGTH = 1 + len(data) + 2
        crc_payload = DATA_LENGTH.to_bytes(2, 'big') + bytes([PTYPE_FILE_START]) + data
        crc = self.crc16_ccitt(crc_payload, 0)
        packet = FRAME_HEADER.to_bytes(2, 'big') + DATA_LENGTH.to_bytes(2, 'big') + bytes([PTYPE_FILE_START]) + data + crc.to_bytes(2, 'big') + FRAME_END.to_bytes(2, 'big')
        self.stream.send(packet)

    def executeCommand(self, line, nodisplay=False):
        if self.stream and line:
            try:
                self.executeMultiCharCommand(line.encode())
                if self.execCallback and (not nodisplay):
                    self.execCallback(line)
            except:
                self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))

    def executeTransfileCommand(self, line, nodisplay=False):
        if self.stream and line:
            try:
                # Check if line has content before accessing indices
                if len(line) > 0 and line[(-1)]!= '\n':
                    line += '\n'
                self.executeFileCommand(line.encode())
                if self.execCallback:
                    print(f"line: {line}")
                    if line.endswith('.lz\n') and len(line) > 4:
                        new_line = line[:(-4)] + '\n'
                    else:  # inserted
                        new_line = line
                    if not nodisplay:
                        self.execCallback(new_line)
            except:
                self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))

    # ----------------------------------------------------------------------
    def autoCommand(self, margin=False, zprobe=False, zprobe_abs=False, leveling=False, goto_origin=False, z_probe_offset_x=0, z_probe_offset_y=0, i=3, j=3, h=5, buffer=False, auto_level_offsets = [0,0,0,0]):
        if not (margin or zprobe or leveling or goto_origin):
            return
        if abs(CNC.vars['xmin']) > CNC.vars['worksize_x'] or abs(CNC.vars['ymin']) > CNC.vars['worksize_y']:
            return
        cmd = "M495 X%gY%g" % (CNC.vars['xmin'], CNC.vars['ymin'])
        if margin:
            cmd = cmd + "C%gD%g" % (CNC.vars['xmax'], CNC.vars['ymax'])
            if buffer:
                cmd = "buffer " + cmd
            self.executeCommand(cmd) #run margin command. Has to be two seperate commands to offset the start of the autolevel process
        cmd = "M495 X%gY%g" % (CNC.vars['xmin'] + auto_level_offsets[0], CNC.vars['ymin'] + auto_level_offsets[2]) #reinitialize command with any autolevel offsets
        if zprobe:
            if zprobe_abs:
                cmd = "M495 X%gY%g" % (CNC.vars['xmin'], CNC.vars['ymin']) #reset command for 4th axis
                cmd = cmd + "O0"
            else:
                cmd = cmd + "O%gF%g" % (z_probe_offset_x, z_probe_offset_y)
        if leveling:
            cmd = cmd + "A%gB%gI%dJ%dH%d" % (CNC.vars['xmax'] - (CNC.vars['xmin']+auto_level_offsets[1]+ auto_level_offsets[0]) , CNC.vars['ymax'] - (CNC.vars['ymin']+auto_level_offsets[3] + auto_level_offsets[2]), i, j, h)
        if goto_origin:
            cmd = cmd + "P1"
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
        if abs(CNC.vars['xmin']) <= CNC.vars['worksize_x'] and abs(CNC.vars['ymin']) <= CNC.vars['worksize_y']:
            cmd = "M496.5 X%gY%g\n" % (CNC.vars['xmin'], CNC.vars['ymin'])
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
        self.executeCommand("reset\n")

    def change(self):
        self.executeCommand("M490.2\n")

    def setFeedScale(self, scale):
        self.executeCommand("M220 S%d\n" % (scale))

    def setLaserScale(self, scale):
        self.executeCommand("M325 S%d\n" % (scale))

    def setSpindleScale(self, scale):
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

    def clampToolCommand(self):
        self.executeCommand("M490.1\n")

    def unclampToolCommand(self):
        self.executeCommand("M490.2\n")

    def changeToolCommand(self, tool):
        if tool == 'e':
            self.executeCommand("M6T0\n")
        elif tool == 'r':
            self.executeCommand("M6T8888\n")
        elif tool == 'm':
            #custom tool number
            pass
        else:
            self.executeCommand("M6T%s\n" % tool)

    def setToolCommand(self, tool):
        if tool == 'e':
            self.executeCommand("M493.2T0\n")
        elif tool == 'r':
            self.executeCommand("M493.2T8888\n")
        elif tool == 'm':
            #custom tool number
            pass
        elif tool == 'y':
            self.executeCommand("M493.2T-1\n")
        else:
            self.executeCommand("M493.2T%s\n" % tool)

    def bufferChangeToolCommand(self, tool):
        self.executeCommand("buffer M6T%s\n" % tool)

    # ------------------------------------------------------------------------------
    # escape special characters
    # ------------------------------------------------------------------------------
    def escape(self, value):
        return value.replace('?', '\x02').replace('&', '\x03').replace('!', '\x04').replace('~', '\x05')

    def lsCommand(self, ls_dir):
        ls_command = "ls -e -s %s\n" % ls_dir.replace(' ', '\x01')
        if '\\' in ls_dir:
            ls_command = "ls -e -s %s\n" % '/'.join(ls_dir.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(ls_command))

    def catCommand(self, filename):
        cat_command = "cat %s -e\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            cat_command = "cat %s -e\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(cat_command))

    def rmCommand(self, filename):
        rm_command = "rm %s -e\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            rm_command = "rm %s -e\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(rm_command))

    def mvCommand(self, file, newfile):
        mv_command = "mv %s %s -e\n" % (file.replace(' ', '\x01'), newfile.replace(' ', '\x01'))
        if '\\' in file or '\\' in newfile:
            mv_command = "mv %s %s -e\n" % ('/'.join(file.split('\\')).replace(' ', '\x01'), '/'.join(newfile.split('\\')).replace(' ', '\x01'))
        self.executeCommand(self.escape(mv_command))

    def mkdirCommand(self, dirname):
        mkdir_command = "mkdir %s -e\n" % dirname.replace(' ', '\x01')
        if '\\' in dirname:
            mkdir_command = "mkdir %s -e\n" % '/'.join(dirname.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(mkdir_command))

    def md5Command(self, filename):
        md5_command = "md5sum %s -e\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            md5_command = "md5sum %s -e\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(md5_command))

    def loadWiFiCommand(self):
        self.executeCommand("wlan -e\n")

    def disconnectWiFiCommand(self):
        self.executeCommand("wlan -d disconnect\n")

    def connectWiFiCommand(self, ssid, password):
        wifi_command = "wlan %s %s -e\n" % (ssid.replace(' ', '\x01'), password.replace(' ', '\x01'))
        self.executeCommand(self.escape(wifi_command))

    def loadConfigCommand(self):
        self.executeCommand("config-get-all -e\n")

    def restoreConfigCommand(self):
        self.executeCommand("config-restore\n")

    def defaultConfigCommand(self):
        self.executeCommand("config-default\n")

    def uploadCommand(self, filename):
        upload_command = "upload %s\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            upload_command = "upload %s\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeTransfileCommand(self.escape(upload_command))

    def downloadCommand(self, filename):
        download_command = "download %s\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            download_command = "download %s\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeTransfileCommand(self.escape(download_command))

    def suspendCommand(self):
        self.executeCommand("suspend\n")

    def resumeCommand(self):
        self.executeCommand("resume\n")

    def playCommand(self, filename):
        play_command = "play %s\n" % filename.replace(' ', '\x01')
        if '\\' in filename:
            play_command = "play %s\n" % '/'.join(filename.split('\\')).replace(' ', '\x01')
        self.executeCommand(self.escape(play_command))

    def abortCommand(self):
        self.executeCommand("abort\n")

    def feedholdCommand(self):
        if self.stream:
            self.executeSingleCharCommand(ord('!'))

    def toggleFeedholdCommand(self, holding):
        if self.stream:
            if holding:
                self.executeSingleCharCommand(ord('~'))
            else:
                self.executeSingleCharCommand(ord('!'))

    def cyclestartCommand(self):
        if self.stream:
            self.executeSingleCharCommand(ord('~'))

    def estopCommand(self):
        if self.stream:
            self.executeSingleCharCommand(24)

    # ----------------------------------------------------------------------
    def hardResetPre(self):
        self.executeMultiCharCommand(b"reset\n")

    def hardResetAfter(self):
        time.sleep(6)

    def parseBracketAngle(self, line,):
        # R: Rotation Angle; G: active Coord System;
        # <Idle|MPos:68.9980,-49.9240,40.0000,12.3456|WPos:68.9980,-49.9240,40.0000,5.3|R:0.0|G:0|F:12345.12,100.0|S:1.2,100.0|T:1|L:0>
        # F: Feed, overide | S: Spindle RPM
        ln = line[1:-1]  # strip off < .. >

        # split fields
        l = ln.split('|')

        # strip off status
        CNC.vars["state"] = l[0]

        # strip of rest into a dict of name: [values,...,]
        d = {}
        try:
            d = {a: [float(y) for y in b.split(',')] for a, b in [x.split(':') for x in l[1:]]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse status data: {e}")
            return
            
        if 'R' in d and len(d['R']) > 0:
            CNC.vars["rotation_angle"] = float(d['R'][0])
            CNC.can_rotate_wcs = True
        else:
            CNC.vars["rotation_angle"] = 0.0
        if 'G' in d and len(d['G']) > 0:
            CNC.vars["active_coord_system"] = int(d['G'][0])
        if 'C' in d and len(d['C']) > 3:
            CNC.vars['MachineModel'] = int(d['C'][0])
            CNC.vars['FuncSetting'] = int(d['C'][1])
            CNC.vars['inch_mode'] = int(d['C'][2])
            CNC.vars['absolute_mode'] = int(d['C'][3])
        else:
            CNC.vars['MachineModel'] = 1
            CNC.vars['FuncSetting'] = 0
            CNC.vars['inch_mode'] = 0
            CNC.vars['absolute_mode'] = 0
        if CNC.vars['inch_mode'] != 999:
            if CNC.vars['inch_mode'] == 1:
                CNC.UnitScale = 25.4
            else:
                CNC.UnitScale = 1
        else:
            CNC.UnitScale = 1
        CNC.vars["mx"] = float(d['MPos'][0])
        CNC.vars["my"] = float(d['MPos'][1])
        CNC.vars["mz"] = float(d['MPos'][2])
        if len(d['MPos']) > 3:
            CNC.vars["ma"] = float(d['MPos'][3])
        else:
            CNC.vars["ma"] = 0.0
        CNC.vars["wx"] = float(d['WPos'][0])
        CNC.vars["wy"] = float(d['WPos'][1])
        CNC.vars["wz"] = float(d['WPos'][2])
        if len(d['WPos']) > 3:
            CNC.vars["wa"] = float(d['WPos'][3])
        else:
            CNC.vars["wa"] = 0.0
        CNC.vars["wcox"] = round(CNC.vars["mx"] - (math.cos(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wx"] - math.sin(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wy"]), 3)
        CNC.vars["wcoy"] = round(CNC.vars["my"] - (math.sin(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wx"] + math.cos(CNC.vars["rotation_angle"] * math.pi / 180) * CNC.vars["wy"]), 3)
        CNC.vars["wcoz"] = round(CNC.vars["mz"] - CNC.vars["wz"], 3)
        CNC.vars["wcoa"] = round(CNC.vars["ma"] - CNC.vars["wa"], 3)
        if 'F' in d:
           CNC.vars["curfeed"] = float(d['F'][0])
           CNC.vars["tarfeed"] = float(d['F'][1])
           CNC.vars["OvFeed"]  = int(d['F'][2])
        if 'S' in d:
            CNC.vars["curspindle"]  = float(d['S'][0])
            CNC.vars["tarspindle"]  = float(d['S'][1])
            CNC.vars["OvSpindle"]   = float(d['S'][2])
            if len(d['S']) > 3:
                CNC.vars["vacuummode"] = int(d['S'][3])
            if len(d['S']) > 4:
                CNC.vars["spindletemp"] = float(d['S'][4])
        if 'T' in d:
            CNC.vars["tool"] = int(d['T'][0])
            CNC.vars["tlo"] = float(d['T'][1])
            if len(d['T']) > 2:
                CNC.vars["target_tool"] = int(d['T'][2])
            else:
                CNC.vars["target_tool"] = -1
        else:
            CNC.vars["tool"] = -1
            CNC.vars["tlo"] = 0.0
            CNC.vars["target_tool"] = -1
        if 'W' in d:
            CNC.vars["wpvoltage"] = float(d['W'][0])
        if 'L' in d:
            CNC.vars["lasermode"]  = int(d['L'][0])
            CNC.vars["laserstate"] = int(d['L'][1])
            CNC.vars["lasertesting"] = int(d['L'][2])
            CNC.vars["laserpower"] = float(d['L'][3])
            CNC.vars["laserscale"] = float(d['L'][4])
        if 'P' in d:
            CNC.vars["playedlines"] = int(d['P'][0])
            CNC.vars["playedpercent"] = int(d['P'][1])
            CNC.vars["playedseconds"] = int(d['P'][2])
        else:
            # not playing file
            CNC.vars["playedlines"] = -1

        if 'A' in d:
            CNC.vars["atc_state"] = int(d['A'][0])
        else:
            CNC.vars["atc_state"] = 0

        if 'O' in d:
            CNC.vars["max_delta"] = float(d['O'][0])
        else:
            CNC.vars["max_delta"] = 0.0

        if 'H' in d:
            CNC.vars["halt_reason"] = int(d['H'][0])

        self.posUpdate = True

    def parseBigParentheses(self, line):
        # {S:0,5000|L:0,0|F:1,0|V:0,1|G:0|T:0|E:0,0,0,0,0,0|P:0,0|A:1,0}
        ln = line[1:-1]  # strip off < .. >

        # split fields
        l = ln.split('|')

        # strip of rest into a dict of name: [values,...,]
        d = {}
        for x in l:
            if ':' in x:
                try:
                    a, b = x.split(':', 1)  # Split on first colon only
                    d[a] = [int(y) for y in b.split(',')]
                except (ValueError, IndexError) as e:
                    logger.warning(f"parseBigParentheses: Failed to parse line '{x}': {e}")
                    continue
        if 'S' in d:
            CNC.vars["sw_spindle"] = int(d['S'][0])
            CNC.vars["sl_spindle"] = int(d['S'][1])
        if 'L' in d:
            CNC.vars["sw_laser"]  = int(d['L'][0])
            CNC.vars["sl_laser"]  = int(d['L'][1])
        if 'F' in d:
            CNC.vars["sw_spindlefan"] = int(d['F'][0])
            CNC.vars["sl_spindlefan"] = int(d['F'][1])
        if 'V' in d:
            CNC.vars["sw_vacuum"] = int(d['V'][0])
            CNC.vars["sl_vacuum"] = int(d['V'][1])
        if 'G' in d:
            CNC.vars["sw_light"] = int(d['G'][0])
        if 'T' in d:
            CNC.vars["sw_tool_sensor_pwr"] = int(d['T'][0])
        if 'R' in d:
            CNC.vars["sw_air"] = int(d['R'][0])
        if 'C' in d:
            CNC.vars["sw_wp_charge_pwr"] = int(d['C'][0])
        if 'RSSI' in d:
            CNC.vars["RSSI"] = int(d['RSSI'][0])

        if 'E' in d:
            CNC.vars["st_x_min"] = int(d['E'][0])
            CNC.vars["st_x_max"] = int(d['E'][1])
            CNC.vars["st_y_min"] = int(d['E'][2])
            CNC.vars["st_y_max"] = int(d['E'][3])
            CNC.vars["st_z_max"] = int(d['E'][4])
            CNC.vars["st_cover"] = int(d['E'][5])
        if 'P' in d:
            CNC.vars["st_probe"] = int(d['P'][0])
            CNC.vars["st_calibrate"] = int(d['P'][1])
        if 'A' in d:
            CNC.vars["st_atc_home"] = int(d['A'][0])
            CNC.vars["st_tool_sensor"] = int(d['A'][1])
        if 'I' in d:
            CNC.vars["st_e_stop"] = int(d['I'][0])


        self.diagnoseUpdate = True

    # ----------------------------------------------------------------------
    def help(self, event=None):
        webbrowser.open(WIKI, new=2)

    # ----------------------------------------------------------------------
    # Open serial port or wifi connect
    # ----------------------------------------------------------------------
    def open(self, conn_type, address):
        # init connection
        if conn_type == CONN_USB:
            self.stream = self.usb_stream
        else:
            self.stream = self.wifi_stream

        if self.stream.open(address):
            CNC.vars["state"] = CONNECTED
            CNC.vars["color"] = STATECOLOR[CNC.vars["state"]]
            self.log.put((self.MSG_NORMAL, 'Connected to machine!'))
            #self.stream.send(b"\n")
            self._gcount = 0
            self._alarm = True
            # Reset manual disconnect flag when connection is established
            self._manual_disconnect = False
            try:
                self.clearRun()
            except:
                self.log.put((self.MSG_ERROR, 'Controller clear thread error!'))
            self.thread = threading.Thread(target=self.streamIO)
            self.thread.start()
            return True
        else:
            self.log.put((self.MSG_ERROR, 'Connection Failed!'))

    # ----------------------------------------------------------------------
    # Close connection port
    # ----------------------------------------------------------------------
    def close(self):
        if self.stream is None: return
        try:
            self.stopRun()
        except:
            self.log.put((self.MSG_ERROR, 'Controller stop thread error!'))
        self._runLines = 0
        time.sleep(0.5)
        self.thread = None
        try:
            self.stream.close()
        except:
            self.log.put((self.MSG_ERROR, 'Controller close stream error!'))
        self.stream = None
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[CNC.vars["state"]]
        
        # Start reconnection if enabled
        if self.reconnect_enabled and self.reconnect_callback:
            self.start_reconnection()

    def close_manual(self):
        """Close connection manually (user initiated) - don't auto-reconnect"""
        if self.stream is None: return
        try:
            self.stopRun()
        except:
            self.log.put((self.MSG_ERROR, 'Controller stop thread error!'))
        self._runLines = 0
        time.sleep(0.5)
        self.thread = None
        try:
            self.stream.close()
        except:
            self.log.put((self.MSG_ERROR, 'Controller close stream error!'))
        self.stream = None
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
        if self.reconnect_attempts_remaining <= 0:
            if self.cancel_reconnect_callback:
                self.cancel_reconnect_callback()
            return
            
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

    def cancel_reconnection(self):
        """Cancel the reconnection process"""
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            self.reconnect_timer = None
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
        if self.stream is None: return
        self.executeMultiCharCommand(chr(int(hexcode, 16)).encode())
        self.stream.flush()

    def viewStatusReport(self, sio_status):
        if self.loadNUM == 0 and self.sendNUM == 0:
            if self.continuous_jog_active:
                self.executeMultiCharCommand(b'?1')
            else:
                self.executeSingleCharCommand(ord('?'))
            self.sio_status = sio_status

    def viewDiagnoseReport(self, sio_diagnose):
        if self.loadNUM == 0 and self.sendNUM == 0:
            self.executeMultiCharCommand(b"diagnose\n")
            self.sio_diagnose = sio_diagnose

    # ----------------------------------------------------------------------
    def stopProbe(self):
        # Stop any active probing operations
        pass

    def busy(self):
        # Set busy state - can be overridden for UI updates
        pass

    def notBusy(self):
        # Clear busy state - can be overridden for UI updates
        pass

    def openClose(self):
        # Toggle connection state - can be overridden for specific behavior
        pass

    def hardReset(self):
        self.busy()
        if self.stream is not None:
            self.hardResetPre()
            self.openClose()
            self.hardResetAfter()
        self.openClose()
        self.stopProbe()
        self._alarm = False
        CNC.vars["_OvChanged"] = True  # force a feed change if any
        self.notBusy()

    def softReset(self, clearAlarm=True):
        if self.stream:
            self.executeSingleCharCommand(24)  # Ctrl+X
        self.stopProbe()
        if clearAlarm: self._alarm = False
        CNC.vars["_OvChanged"] = True  # force a feed change if any

    def unlock(self, clearAlarm=True):
        if clearAlarm: self._alarm = False
        self.sendGCode("$X")

    def home(self, event=None):
        self.sendGCode("$H")

    def viewSettings(self):
        pass

    def viewParameters(self):
        self.sendGCode("$#")

    def viewWCS(self):
        self.sendGCode("get wcs")

    def parseWCSParameters(self, line):
        """Parse WCS parameters from machine response"""
        # Parse format: [G54:-123.6800,-123.6800,-123.6800,-50,0.000,25.123]
        # Extract all WCS entries from the line

        # parse the current WCS from the "get wcs" command
        get_wcs_pattern = r'\[current WCS: (G5[4-9][.1-3]*)\]'
        current_wcs_matches = re.findall(get_wcs_pattern, line)
        
        if current_wcs_matches:
            # if not on community firmware or rotation angle is not set,
            # the active coordinate system is tracked through the "get wcs" command
            if not self.is_community_firmware or not CNC.can_rotate_wcs:
                CNC.vars["active_coord_system"] = CNC.wcs_names.index(current_wcs_matches[0])
            return

        wcs_pattern = r'\[(G5[4-9][.1-3]*):([^]]+)\]'
        matches = re.findall(wcs_pattern, line)
        wcs_data = {}
        for wcs_code, values_str in matches:
            # Split the values by comma
            values = values_str.split(',')
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
        if hasattr(self, 'wcs_popup_callback') and self.wcs_popup_callback:
            self.wcs_popup_callback(wcs_data)

    def viewState(self):
        self.sendGCode("$G")

    def viewBuild(self):
        self.executeMultiCharCommand(b"version\n")
        self.sendGCode("$I")

    def viewStartup(self):
        pass

    def checkGcode(self):
        pass

    def grblHelp(self):
        self.executeMultiCharCommand(b"help\n")

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
            self.jog_mode = mode
            if self.continuous_jog_active:
                self.stopContinuousJog()

    def startContinuousJog(self, _dir, speed=None, scale_feed_override=None):
        """Start continuous jogging in the specified direction"""
        if self.jog_mode != Controller.JOG_MODE_CONTINUOUS:
            return
        self.continuous_jog_active = True
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
        
        # Send Y^ (Ctrl+Y) to stop continuous jogging
        if self.stream is not None and self.continuous_jog_active:
            self.executeSingleCharCommand(25)

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
            if not self.continuous_jog_active:
                self.startContinuousJog(_dir)

    # ----------------------------------------------------------------------

    def goto(self, x=None, y=None, z=None):
        cmd = "G90G0"
        if x is not None: cmd += "X%g" % (x)
        if y is not None: cmd += "Y%g" % (y)
        if z is not None: cmd += "Z%g" % (z)
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
        self.sendGCode("G53 G0 X%g Y%g" % (CNC.vars['wcox'], CNC.vars['wcoy']))

    def wcsSetA(self, a = None):
        cmd = "G92.4"
        if a is not None and abs(a) < 3600000.0: cmd += "A" + str(round(a, 5))

        self.sendGCode(cmd)

    def shrinkA(self):
        self.sendGCode("G92.4 A0 S0")

    def RapMoveA(self, a = None):
        cmd = "G90G0"
        cmd += "X"  + str(round(a, 5))
        cmd = "G92.4"
        cmd += " A " + str(round(a, 5)) + " R0"
        if a is not None and abs(a) < 3600000.0: self.sendGCode(cmd)

    def wcsSet(self, x = None, y = None, z = None, a = None):
        cmd = "G10L20P0"

        pos = ""
        if x is not None and abs(x) < 10000.0: pos += "X" + str(round(x, 4))
        if y is not None and abs(y) < 10000.0: pos += "Y" + str(round(y, 4))
        if z is not None and abs(z) < 10000.0: pos += "Z" + str(round(z, 4))
        if a is not None and abs(a) < 3600000.0: pos += "A" + str(round(a, 4))
        cmd += pos

        self.sendGCode(cmd)

    def wcsSetM(self, x = None, y = None, z = None, a = None):
        # p = WCS.index(CNC.vars["WCS"])
        cmd = "G10L2P0"

        pos = ""
        if x is not None and abs(x) < 10000.0: pos += "X" + str(round(x, 4))
        if y is not None and abs(y) < 10000.0: pos += "Y" + str(round(y, 4))
        if z is not None and abs(z) < 10000.0: pos += "Z" + str(round(z, 4))
        if a is not None and abs(a) < 3600000.0: pos += "A" + str(round(a, 4))
        cmd += pos

        self.sendGCode(cmd)

    def wcsClearRotation(self):
        cmd = "G10L2R0P0"
        self.sendGCode(cmd)

    def setRotation(self, rotation):
        """Set the rotation angle for the current coordinate system"""
        cmd = f"G10L2R{rotation:.1f}P0"
        self.sendGCode(cmd)

    def feedHold(self, event=None):
        if event is not None and not self.acceptKey(True): return
        if self.stream is None: return
        self.executeSingleCharCommand(ord('!'))
        self.stream.flush()
        self._pause = True

    def acceptKey(self, key):
        # Simple key acceptance method - can be overridden for more complex logic
        return True

    def resume(self, event=None):
        if event is not None and not self.acceptKey(1): return
        if self.stream is None: return
        self.executeSingleCharCommand(ord('~'))
        self.stream.flush()
        self._alarm = False
        self._pause = False

    def pause(self, event=None):
        if self.stream is None: return
        if self._pause:
            self.resume()
        else:
            self.feedHold()

    # ----------------------------------------------------------------------
    def parseLine(self, line):
        if not line:
            return True
        # Check if line has at least one character before accessing line[0]
        if len(line) == 0:
            return True
        elif line[0] == "<":
            self.parseBracketAngle(line)
            self.sio_status = False
        elif line[0] == "{":
            self.parseBigParentheses(line)
            self.sio_diagnose = False
        elif line[0] == "[":
            # Log raw WCS parameters before parsing
            self.log.put((self.MSG_NORMAL, line))
            # Parse WCS parameters: [G54:-123.6800,-123.6800,-123.6800,-50,0.000,25.123]
            self.parseWCSParameters(line)
        elif line[0] == "#":
            self.log.put((self.MSG_INTERIOR, line))
        elif line[0] == "^":
            if line[1] == "Y":
                self.continuous_jog_active = False
        elif "error" in line.lower() or "alarm" in line.lower():
            self.log.put((self.MSG_ERROR, line))
        else:
            self.log.put((self.MSG_NORMAL, line))

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

    def pauseStream(self, wait_s):
        self.pausing = True
        time.sleep(wait_s)
        self.paused = True
        self.pausing = False

    def resumeStream(self):
        self.paused = False
        self.pausing = False

    def process_packet(self):
        if len(self.packetData) < 2:
            self.packetData.clear()
            return
        calcCRC = self.crc16_ccitt(self.packetData, len(self.packetData) - 2)
        receivedCRC = self.packetData[-2] << 8 | self.packetData[-1]
        if calcCRC == receivedCRC:
            if len(self.packetData) >= 3:
                return self.packetData[2]
            self.packetData.clear()
            return
        self.packetData.clear()
        return None

    # ----------------------------------------------------------------------
    # thread performing I/O on serial line
    # ----------------------------------------------------------------------
    def streamIO(self):
        self.sio_status = False
        self.sio_diagnose = False
        dynamic_delay = 0.1
        tr = td = time.time()
        line = b''
        last_error = ''
        while not self.stop.is_set():
            if not self.stream or self.paused:
                time.sleep(1)
                continue
            t = time.time()
            # refresh machine position?
            running = self.sendNUM > 0 or self.loadNUM > 0 or self.pausing
            try:
                app = App.get_running_app()
                if not running and app.root.echosended:
                    if t - tr > STREAM_POLL:
                        self.viewStatusReport(True)
                        tr = t
                    if self.diagnosing and t - td > DIAGNOSE_POLL:
                        self.viewDiagnoseReport(True)
                        td = t
                else:
                    tr = t
                    td = t
                if self.stream.waiting_for_recv():
                    received = [bytes([b]) for b in self.stream.recv()]
                    for byte in received:
                        byte = ord(byte)
                        if self.currentState == RevPacketState.WAIT_HEADER:
                            self.headerBuffer[0] = self.headerBuffer[1]
                            self.headerBuffer[1] = byte
                            checksum = self.headerBuffer[0] << 8 | self.headerBuffer[1]
                            if checksum == FRAME_HEADER:
                                self.currentState = RevPacketState.READ_LENGTH
                                self.bytesNeeded = 2
                                self.packetData.clear()
                        elif self.currentState == RevPacketState.READ_LENGTH:
                            self.packetData.append(byte)
                            self.bytesNeeded -= 1
                            if self.bytesNeeded == 0:
                                # Check if we have enough bytes to read length
                                if len(self.packetData) < 2:
                                    logger.warning("Not enough bytes to read packet length")
                                    self.currentState = RevPacketState.WAIT_HEADER
                                    continue
                                self.expectedLength = self.packetData[0] << 8 | self.packetData[1]
                                self.currentState = RevPacketState.READ_DATA
                                self.bytesNeeded = self.expectedLength
                        elif self.currentState == RevPacketState.READ_DATA:
                            self.packetData.append(byte)
                            self.bytesNeeded -= 1
                            if self.bytesNeeded == 0:
                                self.currentState = RevPacketState.CHECK_FOOTER
                                self.bytesNeeded = 2
                        elif self.currentState == RevPacketState.CHECK_FOOTER:
                            self.footerBuffer[0] = self.footerBuffer[1]
                            self.footerBuffer[1] = byte
                            self.bytesNeeded -= 1
                            if self.bytesNeeded == 0:
                                checksum = self.footerBuffer[0] << 8 | self.footerBuffer[1]
                                self.currentState = RevPacketState.WAIT_HEADER
                                if checksum == FRAME_END:
                                    cmd = self.process_packet()
                                    # Check if packetData has enough elements before slicing
                                    if len(self.packetData) < 6:
                                        logger.warning(f"Packet too short: {len(self.packetData)} bytes")
                                        continue
                                    
                                    if cmd == PTYPE_STATUS_RES or cmd == PTYPE_DIAG_RES or cmd == PTYPE_NORMAL_INFO:
                                        line = self.packetData[3:-3]
                                        self.parseLine(line.decode(errors='ignore'))
                                        continue
                                    if cmd == PTYPE_LOAD_FINISH:
                                        self.loadEOF = True
                                        continue
                                    if cmd == PTYPE_LOAD_ERROR:
                                        self.loadERR = True
                                        continue
                                    line = self.packetData[3:-3]
                                    if self.loadNUM == 0:
                                        self.parseLine(line.decode(errors='ignore'))
                                        continue
                                    decoded_line = line.decode(errors='ignore')
                                    cleaned_line = re.sub(r'<.*?>', '', decoded_line)
                                    cleaned_line = cleaned_line.strip()
                                    if len(cleaned_line) != 0:
                                        split_lines = cleaned_line.replace('\r\n', '\n').split('\n')
                                        for line2 in split_lines:
                                            self.load_buffer.put(line2)
                                            self.load_buffer_size += len(line2) + 1
                    dynamic_delay = 0
                else:
                    if self.sendNUM == 0 and self.loadNUM == 0:
                        dynamic_delay = (0.1 if dynamic_delay >= 0.09 else dynamic_delay + 0.01)
                    else:
                        dynamic_delay = 0

            except:
                print(f"error: {sys.exc_info()[1]}")
                line = b''
                if last_error != str(sys.exc_info()[1]):
                    self.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))
                    last_error = str(sys.exc_info()[1])

            if dynamic_delay > 0:
                time.sleep(dynamic_delay)

    def parseWCSParameters(self, line):
        """Parse WCS parameters from machine response"""
        # Parse format: [G54:-123.6800,-123.6800,-123.6800,-50,0.000,25.123]
        # Extract all WCS entries from the line

        # parse the current WCS from the "get wcs" command
        get_wcs_pattern = r'\[current WCS: (G5[4-9][.1-3]*)\]'
        current_wcs_matches = re.findall(get_wcs_pattern, line)
        
        if current_wcs_matches:
            # if not on community firmware or rotation angle is not set,
            # the active coordinate system is tracked through the "get wcs" command
            if not self.is_community_firmware or not CNC.can_rotate_wcs:
                CNC.vars["active_coord_system"] = CNC.wcs_names.index(current_wcs_matches[0])
            return

        wcs_pattern = r'\[(G5[4-9][.1-3]*):([^]]+)\]'
        matches = re.findall(wcs_pattern, line)
        wcs_data = {}
        for wcs_code, values_str in matches:
            # Split the values by comma
            values = values_str.split(',')
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
        if hasattr(self, 'wcs_popup_callback') and self.wcs_popup_callback:
            self.wcs_popup_callback(wcs_data)