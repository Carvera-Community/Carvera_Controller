"""Flow control for queued command sends.

The firmware holds very little inbound command headroom. In Makera framed
mode over WiFi there is a single pending-command slot: while it is occupied,
``WifiProvider::on_idle`` stops reading from the WiFi module entirely —
including status queries — so a burst of commands stalls the link until the
heartbeat drops it (firmware issue
https://github.com/Carvera-Community/Carvera_Community_Firmware/issues/400).
Over USB the framed command queue is four deep and silently drops when full,
and smoothie text mode assembles lines from a single 256-byte receive ring.

``CommandFlowControl`` serializes queued commands: after a send, the next
command is released only once the machine has been heard from again
(evidence its receive path is live), or after ``ACK_TIMEOUT_S`` as a
fallback so an unresponsive machine cannot wedge the queue. Callers inject
the clock (``now``) so the logic stays deterministic and testable.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Union

# Fallback release time when nothing is heard back after a send.
ACK_TIMEOUT_S = 0.5
# Minimum spacing between queued sends even when responses arrive quickly.
MIN_SEND_GAP_S = 0.02

QueuedCommand = Union[str, bytes]


class CommandFlowControl:
    """Thread-safe FIFO of pending commands with paced release."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._queue: deque[QueuedCommand] = deque()
        self._last_send_time: float | None = None
        self._heard_since_send = True

    def enqueue(self, command: QueuedCommand) -> None:
        with self._lock:
            self._queue.append(command)

    def note_receive(self) -> None:
        """Record that a complete message arrived from the machine."""
        with self._lock:
            self._heard_since_send = True

    def pop_ready(self, now: float) -> QueuedCommand | None:
        """Return the next command if one may be sent at ``now``, else None.

        A command is releasable when nothing was sent yet, or when the
        machine has been heard from since the last send (after a minimum
        gap), or when ``ACK_TIMEOUT_S`` has elapsed with no response.
        Popping marks the command as sent.
        """
        with self._lock:
            if not self._queue:
                return None
            if self._last_send_time is not None:
                elapsed = now - self._last_send_time
                acked = self._heard_since_send and elapsed >= MIN_SEND_GAP_S
                if not acked and elapsed < ACK_TIMEOUT_S:
                    return None
            self._last_send_time = now
            self._heard_since_send = False
            return self._queue.popleft()

    def clear(self) -> None:
        """Drop all pending commands (connection closed, abort, …)."""
        with self._lock:
            self._queue.clear()
            self._last_send_time = None
            self._heard_since_send = True

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)
