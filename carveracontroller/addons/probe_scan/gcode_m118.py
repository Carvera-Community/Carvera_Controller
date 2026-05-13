"""G-code helpers for M118 / M118.1 probe echo tails and serial parsing."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

# Variable indices per operation (firmware probe result registers)
VAR_SETS: dict[str, list[str]] = {
    "M466": ["154", "155", "156"],
    "M461": ["151", "152", "154", "155"],
    "M462": ["151", "152", "154", "155"],
    "M463": ["154", "155"],
    "M464": ["154", "155"],
    "M465": ["153"],
}


def build_m118_echo_tail(
    op: str, result_vars: Sequence[str] | None = None
) -> str:
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
    return "\n".join(lines)


def merge_probe_program(
    head: str, op: str, *, result_vars: Sequence[str] | None = None
) -> str:
    """Join head G-code (may be multi-line) with echo tail for ``op``."""
    head = head.strip()
    tail = build_m118_echo_tail(op, result_vars=result_vars)
    return f"{head}\n{tail}\n"


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
_RE_FLOAT = re.compile(r"^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?\s*$")
_RE_RESULT_EQ = re.compile(
    r"result\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)",
    re.IGNORECASE,
)


def extract_float_line(line: str) -> float | None:
    """Parse a lone float line or firmware-style ``result = <float>``."""
    s = line.strip()
    if _RE_FLOAT.match(s):
        try:
            v = float(s)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except ValueError:
            return None
    m = _RE_RESULT_EQ.search(s)
    if m:
        try:
            v = float(m.group(1))
        except ValueError:
            return None
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    return None


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
