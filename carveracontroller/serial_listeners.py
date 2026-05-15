"""
Serial line notification for addons.

Incoming lines from the machine are processed on a background thread in
``Makera.monitorSerial()``.  After each line is read from
``Controller.log``, ``dispatch_serial_line()`` forwards it to registered
listeners on the **Kivy main thread** via ``Clock.schedule_once``.

Callback signature::

    callback(msg_kind: int, line: str) -> None

``msg_kind`` matches ``Controller.MSG_NORMAL`` (0) or ``Controller.MSG_ERROR`` (1).

Listeners must return quickly and avoid blocking; perform heavy work asynchronously.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from kivy.clock import Clock

logger = logging.getLogger(__name__)

_listeners: dict[int, Callable[[int, str], None]] = {}
_next_id = 0
_lock = threading.Lock()


def register_serial_listener(
    callback: Callable[[int, str], None],
) -> int:
    """Register a listener; returns a handle for :func:`unregister_serial_listener`."""
    global _next_id
    with _lock:
        _next_id += 1
        hid = _next_id
        _listeners[hid] = callback
    return hid


def unregister_serial_listener(handle: int) -> None:
    """Remove a listener by handle returned from :func:`register_serial_listener`."""
    with _lock:
        _listeners.pop(handle, None)


def dispatch_serial_line(msg_kind: int, line: str) -> None:
    """
    Called from the serial reader thread for each line dequeued from
    ``Controller.log``. Schedules one main-thread tick that invokes all
    listeners registered **at run time**, so ``unregister_serial_listener``
    removes a callback before it can fire for lines whose dispatch was
    scheduled earlier.
    """
    with _lock:
        if not _listeners:
            return

    def _run(_dt):
        with _lock:
            cbs = tuple(_listeners.values())
        if not cbs:
            return
        for cb in cbs:
            try:
                cb(msg_kind, line)
            except Exception:
                logger.exception("serial listener failed")

    Clock.schedule_once(_run, 0)
