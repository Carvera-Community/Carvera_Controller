"""Userspace USB bulk transport for Makera Z1.

The Z1 presents VID 0x303A / PID 0x4002 as a vendor-class device with bulk IN
and bulk OUT endpoints, not a FTDI serial port like previous Makera machines.

This module uses libusb to interact with the Z1

Windows still needs the WinUSB driver bound to 303A:4002 (via Zadig).
"""

from __future__ import annotations

import importlib
import logging
import platform
import time
from urllib.parse import quote, unquote

from .XMODEM import XMODEM

logger = logging.getLogger(__name__)

try:
    import usb
    import usb.core
    import usb.util
except ImportError:  # Android / iOS builds omit pyusb
    usb = None

Z1_USB_VID = 0x303A
Z1_USB_PID = 0x4002
USB_BULK_DEVICE_IDS = ((Z1_USB_VID, Z1_USB_PID),)

USB_BULK_SCHEME = "usbbulk://"
BULK_WRITE_TIMEOUT_MS = 2000
DEFAULT_MAX_PACKET = 512
Z1_USB_DOCS_URL = "https://carvera-community.gitbook.io/docs/controller/features/z1-usb-support"

# libusb error codes used for user-facing hints.
LIBUSB_ERROR_ACCESS = -3


class USBBulkError(RuntimeError):
    """Raised when a vendor-class USB device cannot be opened or I/O fails."""


def format_usb_bulk_address(vid, pid, serial=""):
    address = f"{USB_BULK_SCHEME}{int(vid):04X}:{int(pid):04X}"
    serial = (serial or "").strip()
    if serial:
        address = f"{address}/{quote(serial, safe='')}"
    return address


def is_usb_bulk_address(address):
    return bool(address) and str(address).lower().startswith(USB_BULK_SCHEME)


def parse_usb_bulk_address(address):
    """Return ``(vid, pid, serial)`` or None if *address* is not a bulk URL."""
    if not is_usb_bulk_address(address):
        return None
    rest = str(address)[len(USB_BULK_SCHEME) :]
    if "/" in rest:
        id_part, serial = rest.split("/", 1)
        serial = unquote(serial).strip()
    else:
        id_part, serial = rest, ""
    parts = id_part.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0], 16), int(parts[1], 16), serial
    except ValueError:
        return None


def _is_bulk_endpoint(endpoint):
    return (int(getattr(endpoint, "bmAttributes", 0)) & 0x03) == 2


def _is_in_endpoint(endpoint):
    return bool(int(getattr(endpoint, "bEndpointAddress", 0)) & 0x80)


def find_bulk_pair(interfaces):
    """Return ``(interface, ep_in, ep_out)`` for the first bulk IN+OUT pair."""
    for interface in interfaces:
        try:
            endpoints = list(interface)
        except TypeError:
            continue
        ep_in = ep_out = None
        for endpoint in endpoints:
            if not _is_bulk_endpoint(endpoint):
                continue
            if _is_in_endpoint(endpoint):
                ep_in = endpoint
            else:
                ep_out = endpoint
        if ep_in is not None and ep_out is not None:
            return interface, ep_in, ep_out
    return None, None, None


def merge_usb_device_lists(serial_devices, bulk_devices):
    """Omit bulk entries that are already exposed as OS serial ports."""
    serial_ids = {entry["device_id"].upper() for entry in serial_devices}
    serial_keys = {(entry["device_id"].upper(), (entry.get("serial") or "").casefold()) for entry in serial_devices}
    merged = list(serial_devices)
    for entry in bulk_devices:
        device_id = entry["device_id"].upper()
        serial = (entry.get("serial") or "").strip()
        if serial and (device_id, serial.casefold()) in serial_keys:
            continue
        if not serial and device_id in serial_ids:
            continue
        merged.append(entry)
    return merged


def _is_timeout_error(exc):
    if usb is not None and isinstance(exc, getattr(usb.core, "USBTimeoutError", ())):
        return True
    return _usb_error_code(exc) == -7  # LIBUSB_ERROR_TIMEOUT


def _usb_error_code(exc):
    for attr in ("errno", "backend_error_code"):
        value = getattr(exc, attr, None)
        if value is not None:
            return value
    return None


def _hint_for_open_failure(exc):
    system = platform.system()
    code = _usb_error_code(exc)
    message = str(exc).strip() or exc.__class__.__name__
    if system == "Linux" and code == LIBUSB_ERROR_ACCESS:
        return (
            "The Z1 USB device was found but could not be opened due to\n"
            "insufficient permissions on the USB device.\n\n"
            "See the documentation on how to fix these permissions on Linux:\n"
            f"{Z1_USB_DOCS_URL}#linux"
        )
    if system == "Windows":
        return (
            "The Z1 USB device was found but could not be opened.\n\n"
            "See the documentation on how to install the WinUSB driver on Windows:\n"
            f"{Z1_USB_DOCS_URL}#windows"
        )
    return message


def _get_libusb_backend():
    if usb is None:
        return None
    try:
        import libusb_package

        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            return backend
    except Exception:
        logger.debug("libusb-package backend unavailable", exc_info=True)
    try:
        libusb1 = importlib.import_module("usb.backend.libusb1")
        return libusb1.get_backend()
    except Exception:
        logger.debug("system libusb backend unavailable", exc_info=True)
        return None


def _safe_usb_string(device, attr):
    try:
        value = getattr(device, attr, None)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _bulk_device_label(vid, pid, serial, product):
    if serial:
        return serial
    if product:
        return product
    if (vid, pid) == (Z1_USB_VID, Z1_USB_PID):
        return "Z1 USB"
    return f"{vid:04X}:{pid:04X}"


def list_usb_bulk_devices(find_devices=None):
    """List configured vendor-class bulk devices as dropdown entries."""
    if find_devices is None:
        if usb is None:
            return []
        backend = _get_libusb_backend()
        if backend is None:
            logger.debug("libusb backend is not available; skipping USB bulk discovery")
            return []

        def find_devices(vid, pid):
            return usb.core.find(find_all=True, idVendor=vid, idProduct=pid, backend=backend) or []

    devices = []
    for vid, pid in USB_BULK_DEVICE_IDS:
        try:
            found = list(find_devices(vid, pid))
        except Exception:
            logger.debug("USB bulk scan failed for %04X:%04X", vid, pid, exc_info=True)
            continue
        for device in found:
            serial = _safe_usb_string(device, "serial_number")
            product = _safe_usb_string(device, "product")
            devices.append(
                {
                    "device_path": format_usb_bulk_address(vid, pid, serial),
                    "device_id": f"{vid:04X}:{pid:04X}",
                    "label": _bulk_device_label(vid, pid, serial, product),
                    "vid": int(vid),
                    "pid": int(pid),
                    "serial": serial,
                    "transport": "bulk",
                }
            )
    return devices


def _detach_kernel_driver(device, interface_number):
    try:
        if device.is_kernel_driver_active(interface_number):
            device.detach_kernel_driver(interface_number)
    except (NotImplementedError, AttributeError):
        return
    except Exception:
        logger.debug("Could not detach kernel driver on interface %s", interface_number, exc_info=True)


def _interface_number(interface):
    descriptor = getattr(interface, "bInterfaceNumber", None)
    if descriptor is not None:
        return int(descriptor)
    return 0


class USBBulkStream:
    """Byte-stream transport over USB bulk IN/OUT endpoints."""

    resets_on_open = False
    supports_baud = False

    def __init__(self, log_sent_receive=False):
        self.modem = XMODEM(self.getc, self.putc, "xmodem")
        self.log_sent_receive = log_sent_receive
        self.uses_framed_transfer = False
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        self.dev = None
        self.ep_in = None
        self.ep_out = None
        self.interface = None
        self._address = ""
        self._rx_buf = bytearray()
        self._stop = False

    def send(self, data):
        if self.dev is None:
            return
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        self._write(data)
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
            logger.debug("SENT: %s", line.decode("utf-8", errors="replace").rstrip("\r\n"))
        if len(self._send_log_buffer) > 4096:
            logger.debug("SENT: <%d bytes (no newline)>", len(self._send_log_buffer))
            self._send_log_buffer = b""

    def recv(self):
        if self.dev is None or self._stop:
            return b""
        if not self._rx_buf:
            self._pump(timeout_ms=1)
        data = bytes(self._rx_buf)
        self._rx_buf.clear()
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

    def open(self, address, find_devices=None):
        parsed = parse_usb_bulk_address(address)
        if parsed is None:
            raise USBBulkError(f"Not a USB bulk address: {address}")
        vid, pid, serial = parsed
        self._address = address
        device = self._find_device(vid, pid, serial, find_devices=find_devices)
        try:
            self._claim_device(device)
        except USBBulkError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise USBBulkError(_hint_for_open_failure(exc)) from exc

        try:
            self._write(b"\n;\n")
        except Exception:
            logger.debug("Failed to flush machine receive buffer after USB bulk open", exc_info=True)
        return True

    def close(self):
        self._stop = True
        device = self.dev
        self.dev = None
        self.ep_in = None
        self.ep_out = None
        if device is not None:
            try:
                if self.interface is not None and usb is not None:
                    usb.util.release_interface(device, self.interface)
            except Exception:
                pass
            try:
                if usb is not None:
                    usb.util.dispose_resources(device)
            except Exception:
                pass
        try:
            self.modem.clear_mode_set()
        except Exception:
            pass
        self.interface = None
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        self.reset_input_buffer()
        return True

    def waiting_for_send(self):
        return self.dev is not None

    def waiting_for_recv(self):
        if self.dev is None or self._stop:
            return False
        if self._rx_buf:
            return True
        self._pump(timeout_ms=1)
        return bool(self._rx_buf)

    def reset_input_buffer(self):
        self._rx_buf.clear()

    def getc(self, size, timeout=1):
        if self.dev is None:
            return None
        deadline = time.time() + timeout
        while True:
            if len(self._rx_buf) >= size:
                data = bytes(self._rx_buf[:size])
                del self._rx_buf[:size]
                return data
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self._pump(timeout_ms=max(1, int(min(0.05, remaining) * 1000)))

    def putc(self, data, timeout=1):
        if self.dev is None:
            return None
        timeout_ms = int(timeout * 1000) if timeout else BULK_WRITE_TIMEOUT_MS
        self._write(data, timeout_ms=timeout_ms)
        return len(data)

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

    def _find_device(self, vid, pid, serial, find_devices=None):
        if find_devices is None:
            if usb is None:
                raise USBBulkError("USB library (pyusb) is not available on this system.")
            backend = _get_libusb_backend()
            if backend is None:
                raise USBBulkError("USB library (libusb) is not available on this system.")

            def find_devices(find_vid, find_pid):
                return usb.core.find(find_all=True, idVendor=find_vid, idProduct=find_pid, backend=backend) or []

        try:
            matches = list(find_devices(vid, pid))
        except Exception as exc:
            raise USBBulkError(_hint_for_open_failure(exc)) from exc
        if serial:
            serial_matches = [
                device
                for device in matches
                if _safe_usb_string(device, "serial_number").casefold() == serial.casefold()
            ]
            if serial_matches:
                matches = serial_matches
        if not matches:
            raise USBBulkError(f"USB device {vid:04X}:{pid:04X} was not found.")
        return matches[0]

    def _claim_device(self, device):
        if usb is None:
            raise USBBulkError("USB library (pyusb) is not available on this system.")
        try:
            device.set_configuration()
        except Exception:
            logger.debug("set_configuration skipped or already configured", exc_info=True)
        try:
            configuration = device.get_active_configuration()
        except Exception as exc:
            raise USBBulkError(_hint_for_open_failure(exc)) from exc
        interface, ep_in, ep_out = find_bulk_pair(configuration)
        if interface is None:
            raise USBBulkError("USB device does not have bulk IN and bulk OUT endpoints.")
        interface_number = _interface_number(interface)
        _detach_kernel_driver(device, interface_number)
        try:
            usb.util.claim_interface(device, interface)
        except Exception as exc:
            raise USBBulkError(_hint_for_open_failure(exc)) from exc
        self.dev = device
        self.interface = interface
        self.ep_in = ep_in
        self.ep_out = ep_out
        self._stop = False
        self.reset_input_buffer()

    def _write(self, data, timeout_ms=BULK_WRITE_TIMEOUT_MS):
        if self.dev is None or self.ep_out is None:
            raise USBBulkError("USB bulk device is not open.")
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        offset = 0
        max_packet = int(getattr(self.ep_out, "wMaxPacketSize", 0) or DEFAULT_MAX_PACKET)
        endpoint = self.ep_out.bEndpointAddress
        while offset < len(data):
            chunk = data[offset : offset + max_packet]
            written = self.dev.write(endpoint, chunk, timeout=timeout_ms)
            if not written:
                raise USBBulkError("USB bulk write returned 0 bytes")
            offset += written

    def _pump(self, timeout_ms=1):
        if self.dev is None or self.ep_in is None or self._stop:
            return
        try:
            data = self.dev.read(
                self.ep_in.bEndpointAddress,
                int(getattr(self.ep_in, "wMaxPacketSize", 0) or DEFAULT_MAX_PACKET),
                timeout=timeout_ms,
            )
        except Exception as exc:
            if self._stop or self.dev is None:
                return
            if _is_timeout_error(exc):
                return
            raise USBBulkError("USB device disconnected") from exc
        if data:
            self._rx_buf.extend(bytes(data))
