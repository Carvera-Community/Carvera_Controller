"""When the tour may start, and what Skip does. No UI toolkit."""

from __future__ import annotations

from dataclasses import dataclass

WELCOME = "welcome"
DEMO = "demo"

REFUSE = "refuse"
ALLOW = "allow"
CONFIRM_DISCONNECT = "confirm_disconnect"

MARK_COMPLETE = "mark_complete"
TEARDOWN = "teardown"

DISCONNECTED = "N/A"
MOVING_STATES = frozenset({"Run", "Pause", "Hold", "Tool"})


def tour_start_decision(state: str, *, link_busy: bool = False) -> str:
    """Return refuse, allow, or confirm_disconnect.

    A live job is refused. A disconnected, idle link is allowed. Any other
    connection — including a link that is still opening — asks before disconnect.
    """
    if state in MOVING_STATES:
        return REFUSE
    if state == DISCONNECTED and not link_busy:
        return ALLOW
    return CONFIRM_DISCONNECT


def skip_effect(phase: str) -> str:
    """Welcome Skip only records completion. Skip during the demo tears it down."""
    if phase == WELCOME:
        return MARK_COMPLETE
    if phase == DEMO:
        return TEARDOWN
    raise ValueError(f"unknown tour phase: {phase}")


@dataclass(frozen=True)
class SkipResult:
    mark_complete: bool
    teardown: bool
    start_demo: bool


def resolve_skip(phase: str) -> SkipResult:
    """Skip never starts the practice view."""
    effect = skip_effect(phase)
    if effect == MARK_COMPLETE:
        return SkipResult(mark_complete=True, teardown=False, start_demo=False)
    return SkipResult(mark_complete=True, teardown=True, start_demo=False)
