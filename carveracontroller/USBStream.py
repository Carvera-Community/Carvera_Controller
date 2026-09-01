import logging
import time

import serial

from .XMODEM import XMODEM

logger = logging.getLogger(__name__)

SERIAL_TIMEOUT = 0.3  # s


# ==============================================================================
# USB stream class
# ==============================================================================
class USBStream:
    serial = None
    resets_on_open = True
    supports_baud = True

    # ----------------------------------------------------------------------
    def __init__(self, log_sent_receive=False):
        self.modem = XMODEM(self.getc, self.putc, "xmodem")
        # Rely on the app/Kivy root logger; do not attach extra StreamHandlers to
        # the shared "xmodem.XMODEM" logger (USB+WiFi would duplicate every line).
        self.log_sent_receive = log_sent_receive
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        # Set by Controller when the communication protocol is selected.
        self.uses_framed_transfer = False

    # ----------------------------------------------------------------------
    def send(self, data):
        if self.serial is None:
            return
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        self.serial.write(data)
        if not self.log_sent_receive:
            return
        if data == b"?":
            logger.debug("SENT: ?")
            return
        self._send_log_buffer += data
        while b"\n" in self._send_log_buffer:
            idx = self._send_log_buffer.index(b"\n") + 1
            line = self._send_log_buffer[:idx]
            self._send_log_buffer = self._send_log_buffer[idx:]
            line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
            logger.debug("SENT: %s", line_str)
        if len(self._send_log_buffer) > 4096:
            logger.debug("SENT: <%d bytes (no newline)>", len(self._send_log_buffer))
            self._send_log_buffer = b""

    # ----------------------------------------------------------------------
    def recv(self):
        if self.serial is None:
            return b""
        data = self.serial.read()
        if self.log_sent_receive and data:
            self._recv_log_buffer += data
            while b"\n" in self._recv_log_buffer:
                idx = self._recv_log_buffer.index(b"\n") + 1
                line = self._recv_log_buffer[:idx]
                self._recv_log_buffer = self._recv_log_buffer[idx:]
                logger.debug("RECV: %s", line.decode("utf-8", errors="replace").rstrip("\r\n"))
            if len(self._recv_log_buffer) > 4096:
                logger.debug("RECV: <%d bytes (no newline)>", len(self._recv_log_buffer))
                self._recv_log_buffer = b""
        return data

    # ----------------------------------------------------------------------
    def open(self, address, baud=115200):
        self._address = address.replace("\\", "\\\\")
        self.serial = serial.serial_for_url(
            self._address,
            baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
            xonxoff=False,
            rtscts=False,
        )
        # Toggle DTR to reset Arduino
        try:
            self.serial.setDTR(0)
        except OSError:
            pass
        time.sleep(0.5)

        self.serial.flushInput()
        try:
            self.serial.setDTR(1)
        except OSError:
            pass
        time.sleep(0.5)

        # Try to clear machine receive buffer from a previous controller session
        self.serial.write(b"\n;\n")

        return True

    # ----------------------------------------------------------------------
    def reopen_at_baud(self, baud):
        """
        Close and reopen the serial port at a new baud rate.
        """
        if not self._address:
            return False
        baud = int(baud)
        old = self.serial
        self.serial = None
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        if old is not None:
            try:
                old.dtr = False
                old.rts = False
            except Exception:
                pass
            try:
                old.close()
            except Exception:
                pass
        time.sleep(0.1)
        try:
            ser = serial.serial_for_url(
                self._address,
                baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                do_not_open=True,
            )
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            ser.open()
            try:
                ser.dtr = False
            except Exception:
                pass
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass
            self.serial = ser
            return True
        except Exception:
            logger.exception("Failed to reopen serial at %s baud", baud)
            return False

    # ----------------------------------------------------------------------
    def close(self):
        if self.serial is None:
            return None
        time.sleep(0.5)
        try:
            self.modem.clear_mode_set()
            self.serial.close()
        except:
            pass
        self.serial = None
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        return True

    # ----------------------------------------------------------------------
    def waiting_for_send(self):
        if self.serial is None:
            return False
        return self.serial.out_waiting < 1

    # ----------------------------------------------------------------------
    def waiting_for_recv(self):
        if self.serial is None:
            return 0
        return self.serial.in_waiting

    # ----------------------------------------------------------------------
    def getc(self, size, timeout=1):
        if self.serial is None:
            return None
        return self.serial.read(size) or None

    def putc(self, data, timeout=1):
        if self.serial is None:
            return None
        return self.serial.write(data) or None

    def upload(self, filename, local_md5, callback):
        stream = open(filename, "rb")
        if self.uses_framed_transfer:
            result = self.modem.send(stream, md5=local_md5, retry=50, callback=callback)
        else:
            result = self.modem.send_legacy(stream, md5=local_md5, retry=10, callback=callback)
        stream.close()
        return result

    def download(self, filename, local_md5, callback):
        stream = open(filename, "wb")
        if self.uses_framed_transfer:
            result = self.modem.recv(stream, md5=local_md5, retry=50, callback=callback)
        else:
            result = self.modem.recv_legacy(stream, md5=local_md5, retry=10, callback=callback)
        stream.close()
        return result

    def cancel_process(self):
        self.modem.canceled = True
