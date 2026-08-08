"""Validation helpers for MDI console input.

The firmware bounds a single command line on every transport, so input that
exceeds those bounds is truncated or dropped by the machine:

- Smoothie (text) mode: received characters are staged in a
  ``RingBuffer<char, 256>`` before line assembly, on both USB
  (``SerialConsole``) and WiFi (``WifiProvider``).
- Makera (framed) mode over USB: a ``CTRL_MULTI`` payload is copied into a
  fixed 256-byte queue slot (``MAKERA_CMD_MAX_LEN``) before dispatch, and the
  whole payload is dispatched as a single console line.

Splitting multi-line input into one write per line and capping each line keeps
MDI input inside those limits on every transport/protocol combination.
"""

from __future__ import annotations

# 256-byte firmware limit, minus the line terminator, minus one byte of slack.
MDI_MAX_LINE_BYTES = 254


def prepare_mdi_lines(text: str) -> tuple[list[str], list[str]]:
    """Split raw MDI input into individual command lines.

    Returns ``(lines, rejected)``: ``lines`` are the non-empty commands, in
    order, each safe to send as its own write; ``rejected`` are lines whose
    UTF-8 encoding exceeds ``MDI_MAX_LINE_BYTES`` and must not be sent.
    """
    lines: list[str] = []
    rejected: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line.encode("utf-8")) > MDI_MAX_LINE_BYTES:
            rejected.append(line)
        else:
            lines.append(line)
    return lines, rejected
