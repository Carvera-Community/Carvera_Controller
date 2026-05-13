"""Construct probe G-code strings for the scan tool."""

from __future__ import annotations

from .gcode_m118 import VAR_SETS, merge_probe_program


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
    l_repeat: str = "",
    r_retract: str = "",
    result_vars: list[str] | None = None,
) -> str:
    parts = [op]
    parts.extend(w for w in axis_words if w)
    parts.append(f"F{_fmt(f_probe)}")
    parts.append(f"K{_fmt(k_rapid)}")
    lw = _word("L", l_repeat)
    if lw:
        parts.append(lw)
    rw = _word("R", r_retract)
    if rw:
        parts.append(rw)
    head = "\n".join(["G21", "G90", "G17", "G94", " ".join(parts)])
    return merge_probe_program(head, op, result_vars=result_vars)


def build_m466(
    *,
    x: str = "",
    y: str = "",
    z: str = "",
    e: str = "",
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    xw, yw, zw = _word("X", x), _word("Y", y), _word("Z", z)
    result_vars: list[str] = []
    if xw:
        result_vars.append("154")
    if yw:
        result_vars.append("155")
    if zw:
        result_vars.append("156")
    return _build_probe_cmd(
        "M466",
        [xw, yw, zw, _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
        result_vars=result_vars or list(VAR_SETS["M466"]),
    )


def build_m461(
    *,
    x: str = "",
    y: str = "",
    e: str = "",
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    return _build_probe_cmd(
        "M461",
        [_word("X", x), _word("Y", y), _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
    )


def build_m462(
    *,
    x: str = "",
    y: str = "",
    e_depth: str = "",
    j_clearance: str = "",
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    return _build_probe_cmd(
        "M462",
        [_word("X", x), _word("Y", y), _word("J", j_clearance),
         _word("E", e_depth), _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
    )


def build_m463(
    x: float,
    y: float,
    *,
    e: str = "",
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    return _build_probe_cmd(
        "M463",
        [f"X{_fmt(x)}", f"Y{_fmt(y)}",
         _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
    )


def build_m464(
    x: float,
    y: float,
    *,
    e: str = "",
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    return _build_probe_cmd(
        "M464",
        [f"X{_fmt(x)}", f"Y{_fmt(y)}",
         _word("E", e), _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
    )


def build_m465(
    x: str = "",
    y: str = "",
    e: str = "",
    *,
    h: str = "",
    c: str = "",
    f_probe: float = 300.0,
    k_rapid: float = 800.0,
    l_repeat: str = "",
    r_retract: str = "",
) -> str:
    return _build_probe_cmd(
        "M465",
        [_word("X", x), _word("Y", y), _word("E", e),
         _word("H", h), _word("C", c)],
        f_probe=f_probe, k_rapid=k_rapid,
        l_repeat=l_repeat, r_retract=r_retract,
    )


def split_execute_lines(program: str) -> list[str]:
    out: list[str] = []
    for ln in program.replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        if s and not s.startswith(";"):
            out.append(s)
    return out
