"""Parse M118 probe echo blocks from serial lines."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .gcode_m118 import (
    RE_CMM_END,
    RE_CMM_START,
    VAR_SETS,
    extract_float_line,
    parse_cmm_start_remainder,
)

logger = logging.getLogger(__name__)


class M118ProbeCapture:
    """Stateful parser for CMMProbe START/END blocks on the serial stream."""

    def __init__(
        self, on_complete: Callable[[str, list[float], list[str]], None]
    ):
        self._on_complete = on_complete
        self._host_armed = False
        self._active = False
        self._op: str | None = None
        self._expected: int = 0
        self._var_keys: list[str] = []
        self._buf: list[float] = []

    def prime_upstream(self, op: str, var_keys: list[str]) -> None:
        """Arm capture from outgoing G-code; ignores serial START while host-armed."""
        self.reset()
        ks = [str(k).strip() for k in var_keys if str(k).strip()]
        if not ks:
            return
        self._host_armed = True
        self._active = True
        self._op = op.upper()
        self._var_keys = ks
        self._expected = len(ks)

    def reset(self):
        self._host_armed = False
        self._active = False
        self._op = None
        self._expected = 0
        self._var_keys.clear()
        self._buf.clear()

    def feed_line(self, _msg_kind: int, line: str) -> None:
        s = line.rstrip("\r\n")

        m_start = RE_CMM_START.search(s)
        if m_start:
            if self._host_armed:
                return
            self._active = True
            raw_op = m_start.group(1)
            rem = (m_start.group(2) or "").strip()
            self._op = raw_op.upper()
            self._var_keys, self._expected = parse_cmm_start_remainder(rem)
            if self._expected == 0 or not self._var_keys:
                self.reset()
                return
            self._buf.clear()
            return

        if RE_CMM_END.search(s):
            self.reset()
            return

        if self._active and self._op:
            v = extract_float_line(s)
            if v is not None and len(self._buf) < self._expected:
                self._buf.append(v)
                if len(self._buf) == self._expected:
                    try:
                        self._on_complete(
                            self._op, list(self._buf), list(self._var_keys)
                        )
                    except Exception:
                        logger.exception("M118 probe capture callback")
                    self.reset()


def map_values_to_dict(
    op: str, values: list[float], var_keys: list[str] | None = None
) -> dict[str, float]:
    """Map captured floats to # variable indices in order."""
    keys = var_keys if var_keys else VAR_SETS.get(op.upper(), [])
    out: dict[str, float] = {}
    for i, k in enumerate(keys):
        if i < len(values):
            out[k] = values[i]
    return out
