"""Practice-view flag and the sample toolpath. No UI toolkit."""

from __future__ import annotations

import os

_demo_active = False

# A short rectangle with one tool. Large enough to show a path, small enough
# to parse immediately. Not one of the multi-thousand-line example jobs.
SAMPLE_GCODE = """\
; Practice toolpath — not a file on the machine
G21
G90
G17
T1 M6
G0 Z5.000
G0 X0.000 Y0.000
G1 Z-1.000 F200
G1 X40.000 F600
G1 Y25.000
G1 X0.000
G1 Y0.000
G0 Z5.000
G0 X8.000 Y6.000
G1 Z-1.000 F200
G1 X32.000 F500
G1 Y19.000
G1 X8.000
G1 Y6.000
G0 Z5.000
G0 X16.000 Y10.000
G1 Z-0.500 F200
G1 X24.000 F400
G1 Y15.000
G1 X16.000
G1 Y10.000
G0 Z5.000
M5
M30
"""


def demo_is_active() -> bool:
    return _demo_active


def set_demo_active(active: bool) -> None:
    global _demo_active
    _demo_active = bool(active)


def blocks_machine_io(stream: object | None) -> bool:
    """Block sends only while the practice view is up and nothing is connected.

    A live stream is left alone so E-stop still works if a link exists. The
    tour refuses to start over a live link, so this is the disconnected case.
    """
    return _demo_active and stream is None


def tutorial_blocks_motion() -> bool:
    """Config and Run / play must not start a job during the practice view."""
    return _demo_active


def write_sample_gcode(directory: str) -> str:
    path = os.path.join(directory, "tutorial-rectangle.nc")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(SAMPLE_GCODE)
    return path
