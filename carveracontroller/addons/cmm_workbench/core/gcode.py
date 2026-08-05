"""G-code helpers and M118 serial capture for CMM Workbench."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from carveracontroller.Controller import Controller

_logger = logging.getLogger(__name__)

# Firmware probe result variables
# See https://carvera-community.gitbook.io/docs/firmware/features/variables
PROBE_VAR_DIA_X = "151"
PROBE_VAR_DIA_Y = "152"
PROBE_VAR_ANGLE = "153"
PROBE_VAR_CENTER_X = "154"
PROBE_VAR_CENTER_Y = "155"
PROBE_VAR_CENTER_Z = "156"

VAR_SETS: dict[str, list[str]] = {
    "M466": [PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y, PROBE_VAR_CENTER_Z],
    "M461": [PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y],
    "M462": [PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y],
    "M463": [PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y],
    "M464": [PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y],
    "M465": [PROBE_VAR_ANGLE],
}


@dataclass(frozen=True)
class ProbeProgram:
    """A probe run split into phases so they can be sent at different times.
    Sending everything at once can cause timeout issues when using the Makera protocol.
    """

    setup: list[str]
    probe: str
    tail: list[str]


def build_m118_echo_tail(op: str, result_vars: Sequence[str] | None = None) -> list[str]:
    """Append START, M118.1 P# for each variable, then END."""
    if result_vars is not None:
        vars_ = [str(v).strip() for v in result_vars if str(v).strip()]
        if not vars_:
            raise ValueError(f"Empty result_vars for {op}")
    else:
        vars_ = VAR_SETS.get(op)
        if not vars_:
            raise ValueError(f"Unknown op for echo tail: {op}")
    var_list = " ".join(vars_)
    lines: list[str] = [
        f"M118 CMMProbe START {op} {var_list}",
    ]
    for v in vars_:
        lines.append(f"M118.1 P#{v}")
    lines.append("M118 CMMProbe END")
    return lines


def parse_cmm_start_remainder(remainder: str) -> tuple[list[str], int]:
    """Parse variable indices after ``CMMProbe START <op>`` (digits only tokens)."""
    tokens = remainder.split()
    if not tokens:
        return [], 0
    for t in tokens:
        if not t.isdigit():
            return [], 0
    return tokens, len(tokens)


def parse_probe_program(lines: Sequence[str]) -> str:
    return "\n".join(x.strip() for x in lines if x and str(x).strip())


RE_CMM_START = re.compile(r"CMMProbe\s+START\s+(\S+)\s+(.+)", re.IGNORECASE)
RE_CMM_END = re.compile(r"CMMProbe\s+END\s*", re.IGNORECASE)
_RE_VAR_EQ = re.compile(r"#([0-9]+)\s*=\s*(-?[0-9]*\.?[0-9]+)")


def extract_result_line(line: str) -> tuple[str, float] | None:
    """Parse an ``M118.1`` result line into ``(var_key, value)``.

    ``var_key`` is the ``#`` variable index (without the ``#``) echoed by the
    firmware (e.g. ``#151 = 12.345`` -> ``("151", 12.345)``). Returns ``None``
    when the line is not a parseable variable result.
    """
    m = _RE_VAR_EQ.search(line.strip())
    if not m:
        return None
    return m.group(1), float(m.group(2))


def extract_probe_start_meta(line: str) -> tuple[str, list[str]] | None:
    """If ``line`` embeds ``CMMProbe START``, return probe op and #var key list."""
    m = RE_CMM_START.search(line)
    if not m:
        return None
    op = m.group(1).strip().upper()
    rem = (m.group(2) or "").strip()
    keys, n = parse_cmm_start_remainder(rem)
    if not keys or n == 0:
        return None
    return op, keys


class M118ProbeCapture:
    """Stateful parser for CMMProbe START/END blocks on the serial stream."""

    def __init__(
        self,
        on_complete: Callable[[str, dict[str, float], list[str]], None],
        on_abort: Callable[[str, dict[str, float], list[str]], None] | None = None,
    ):
        self._on_complete = on_complete
        self._on_abort = on_abort
        self._host_armed = False
        self._active = False
        self._op: str | None = None
        self._expected: int = 0
        self._var_keys: list[str] = []
        self._values: dict[str, float] = {}

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
        self._values.clear()

    def feed_line(self, msg_kind: int, line: str) -> None:
        if msg_kind == Controller.MSG_ERROR:
            return
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
            self._values.clear()
            return

        if RE_CMM_END.search(s):
            # Stale END from a prior run can arrive right after prime_upstream.
            if self._host_armed and not self._values:
                return
            if self._active and self._expected > 0:
                if len(self._values) < self._expected and self._on_abort is not None:
                    try:
                        self._on_abort(self._op or "", dict(self._values), list(self._var_keys))
                    except Exception:
                        _logger.exception("M118 probe capture abort callback")
            self.reset()
            return

        if self._active and self._op:
            parsed = extract_result_line(s)
            if parsed is None:
                return
            key, v = parsed
            # Ignore echoes for variables we didn't request or already captured.
            if key not in self._var_keys or key in self._values:
                return
            self._values[key] = v
            if len(self._values) == self._expected:
                try:
                    self._on_complete(self._op, dict(self._values), list(self._var_keys))
                except Exception:
                    _logger.exception("M118 probe capture callback")
                self.reset()


def _fmt(v: float | int | str) -> str:
    if isinstance(v, str):
        return v.strip()
    if float(v).is_integer():
        return str(int(float(v)))
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def _word(letter: str, val: str | float) -> str | None:
    s = str(val).strip()
    return f"{letter}{_fmt(val)}" if s else None


def _build_probe_cmd(
    op: str,
    axis_words: list[str | None],
    *,
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    d_tip: str = "",
    l_repeat: str = "",
    r_retract: str = "",
    result_vars: list[str] | None = None,
) -> ProbeProgram:
    parts = [op]
    parts.extend(w for w in axis_words if w)
    parts.append(f"F{_fmt(f_probe)}")
    parts.append(f"K{_fmt(k_rapid)}")
    dw = _word("D", d_tip)
    if dw:
        parts.append(dw)
    lw = _word("L", l_repeat)
    if lw:
        parts.append(lw)
    rw = _word("R", r_retract)
    if rw:
        parts.append(rw)
    return ProbeProgram(
        setup=["G21", "G90", "G17", "G94"],
        probe=" ".join(parts),
        tail=build_m118_echo_tail(op, result_vars=result_vars),
    )


def build_m466(
    *,
    x: str = "",
    y: str = "",
    e: str = "",
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    xw, yw = _word("X", x), _word("Y", y)
    result_vars: list[str] = []
    if xw:
        result_vars.append(PROBE_VAR_CENTER_X)
    if yw:
        result_vars.append(PROBE_VAR_CENTER_Y)
    return _build_probe_cmd(
        "M466",
        [xw, yw, _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
        result_vars=result_vars or list(VAR_SETS["M466"]),
    )


def build_m461(
    *,
    x: str = "",
    y: str = "",
    e: str = "",
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    xw, yw = _word("X", x), _word("Y", y)
    result_vars: list[str] = []
    if xw:
        result_vars.extend([PROBE_VAR_DIA_X, PROBE_VAR_CENTER_X])
    if yw:
        result_vars.extend([PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_Y])
    return _build_probe_cmd(
        "M461",
        [xw, yw, _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
        result_vars=result_vars or list(VAR_SETS["M461"]),
    )


def build_m462(
    *,
    x: str = "",
    y: str = "",
    e_depth: str = "",
    j_clearance: str = "",
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    xw, yw = _word("X", x), _word("Y", y)
    result_vars: list[str] = []
    if xw:
        result_vars.extend([PROBE_VAR_DIA_X, PROBE_VAR_CENTER_X])
    if yw:
        result_vars.extend([PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_Y])
    return _build_probe_cmd(
        "M462",
        [xw, yw, _word("J", j_clearance), _word("E", e_depth), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
        result_vars=result_vars or list(VAR_SETS["M462"]),
    )


def build_m463(
    x: float,
    y: float,
    *,
    e: str = "",
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    return _build_probe_cmd(
        "M463",
        [f"X{_fmt(x)}", f"Y{_fmt(y)}", _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
    )


def build_m464(
    x: float,
    y: float,
    *,
    e: str = "",
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    return _build_probe_cmd(
        "M464",
        [f"X{_fmt(x)}", f"Y{_fmt(y)}", _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
    )


def build_m465(
    x: str = "",
    y: str = "",
    e: str = "",
    *,
    h: str = "",
    c: str = "",
    d_tip: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> ProbeProgram:
    return _build_probe_cmd(
        "M465",
        [_word("X", x), _word("Y", y), _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe,
        k_rapid=k_rapid,
        d_tip=d_tip,
        l_repeat=l_repeat,
        r_retract=r_retract,
    )
