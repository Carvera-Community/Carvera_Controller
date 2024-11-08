
import time
import serial
import sys

from .XMODEM import XMODEM
import logging


SERIAL_TIMEOUT = 0.3  # s
# ==============================================================================
# USB stream class
# ==============================================================================
class USBStream:

    serial = None

    # ----------------------------------------------------------------------
    def __init__(self):
        self.modem = XMODEM(self.getc, self.putc, 'xmodem')
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.modem.log.addHandler(handler)


    # ----------------------------------------------------------------------
    def send(self, data):
        self.serial.write(data)

    # ----------------------------------------------------------------------
    def recv(self):
        return self.serial.read()

    # ----------------------------------------------------------------------
    def open(self, address):
        self.serial = serial.serial_for_url(
            address.replace('\\', '\\\\'),  # Escape for windows
            115200,
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
    def close(self):
        if self.serial is None: return
        time.sleep(0.5)
        try:
            self.modem.clear_mode_set()
            self.serial.close()
        except:
            pass
        self.serial = None
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