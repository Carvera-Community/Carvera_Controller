
import time
import serial
import sys

from .XMODEM import XMODEM
import logging

logger = logging.getLogger(__name__)

SERIAL_TIMEOUT = 0.3  # s
# ==============================================================================
# USB stream class
# ==============================================================================
class USBStream:

    serial = None

    # ----------------------------------------------------------------------
    def __init__(self, log_sent_receive = False):
        self.modem = XMODEM(self.getc, self.putc, 'xmodem')
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.modem.log.addHandler(handler)
        self.log_sent_receive = log_sent_receive
        self._send_log_buffer = b''
        self._recv_log_buffer = b''

    # ----------------------------------------------------------------------
    def send(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8', errors='replace')
        self.serial.write(data)
        if not self.log_sent_receive:
            return
        if data == b'?':
            logger.debug("SENT: ?")
            return
        self._send_log_buffer += data
        while b'\n' in self._send_log_buffer:
            idx = self._send_log_buffer.index(b'\n') + 1
            line = self._send_log_buffer[:idx]
            self._send_log_buffer = self._send_log_buffer[idx:]
            line_str = line.decode('utf-8', errors='replace').rstrip('\r\n')
            logger.debug("SENT: %s", line_str)
        if len(self._send_log_buffer) > 4096:
            logger.debug("SENT: <%d bytes (no newline)>", len(self._send_log_buffer))
            self._send_log_buffer = b''

    # ----------------------------------------------------------------------
    def recv(self):
        data = self.serial.read()
        if self.log_sent_receive and data:
            self._recv_log_buffer += data
            while b'\n' in self._recv_log_buffer:
                idx = self._recv_log_buffer.index(b'\n') + 1
                line = self._recv_log_buffer[:idx]
                self._recv_log_buffer = self._recv_log_buffer[idx:]
                logger.debug("RECV: %s", line.decode('utf-8', errors='replace').rstrip('\r\n'))
            if len(self._recv_log_buffer) > 4096:
                logger.debug("RECV: <%d bytes (no newline)>", len(self._recv_log_buffer))
                self._recv_log_buffer = b''
        return data

    # ----------------------------------------------------------------------
    def open(self, address, baud=115200):
        self._address = address.replace('\\', '\\\\')
        self.serial = serial.serial_for_url(
            self._address,
            baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
            xonxoff=False,
            rtscts=False)
        # Toggle DTR to reset Arduino
        try:
            self.serial.setDTR(0)
        except IOError:
            pass
        time.sleep(0.5)

        self.serial.flushInput()
        try:
            self.serial.setDTR(1)
        except IOError:
            pass
        time.sleep(0.5)

        return True

    # ----------------------------------------------------------------------
    def reopen_at_baud(self, baud):
        """Close the current serial port and reopen at the given baud rate."""
        if self.serial is None:
            return False
        try:
            self.serial.close()
        except Exception:
            pass
        self.serial = None
        self._send_log_buffer = b''
        self._recv_log_buffer = b''
        time.sleep(0.1)
        self.serial = serial.serial_for_url(
            self._address,
            baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
            xonxoff=False,
            rtscts=False)
        return True

    # ----------------------------------------------------------------------
    def close(self):
        if self.serial is None: return
        time.sleep(0.5)
        try:
            self.modem.clear_mode_set()
            self.serial.close()
        except:
            pass
        self.serial = None
        self._send_log_buffer = b''
        self._recv_log_buffer = b''
        return True

    # ----------------------------------------------------------------------
    def waiting_for_send(self):
        return self.serial.out_waiting < 1

    # ----------------------------------------------------------------------
    def waiting_for_recv(self):
        return self.serial.in_waiting

    # ----------------------------------------------------------------------
    def getc(self, size, timeout=1):
        return self.serial.read(size) or None

    def putc(self, data, timeout=1):
        return self.serial.write(data) or None

    def upload(self, filename, local_md5, callback):
        # do upload
        stream = open(filename, 'rb')
        result = self.modem.send(stream, md5 = local_md5, retry = 10, callback = callback)
        stream.close()
        return result

    def download(self, filename, local_md5, callback):
        stream = open(filename, 'wb')
        result = self.modem.recv(stream, md5 = local_md5, retry = 10, callback = callback)
        stream.close()
        return result

    def cancel_process(self):
        self.modem.canceled = True